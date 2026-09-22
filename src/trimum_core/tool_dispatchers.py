"""Tool Dispatchers — real Python execution logic for each tool type.

Each dispatcher implements the ``Dispatcher`` protocol with a single
``async def execute(...) -> ExecuteResponse`` method.

DispatcherRegistry maps ToolType values to their dispatcher instances.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import stat
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional, Protocol

from .models import (
    AuditEvent,
    ExecuteRequest,
    ExecuteResponse,
    RiskLevel,
    Action,
    ToolType,
)
from . import sandbox_exec
from .logger import get_logger
from .mcp_bridge import split_name

logger = get_logger("tool_dispatchers")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ok(
    output: str = "",
    execution_id: str = "",
    risk: RiskLevel = RiskLevel.LOW,
    action: Action = Action.AUTO,
    sandbox: str = "",
) -> ExecuteResponse:
    return ExecuteResponse(
        execution_id=execution_id or uuid.uuid4().hex[:12],
        status="allowed",
        output=output,
        exit_code=0,
        risk=risk,
        action=action,
        sandbox=sandbox,
    )


def _err(
    error: str,
    exit_code: int = 1,
    risk: RiskLevel = RiskLevel.MEDIUM,
    action: Action = Action.DENY,
    execution_id: str = "",
    sandbox: str = "",
) -> ExecuteResponse:
    return ExecuteResponse(
        execution_id=execution_id or uuid.uuid4().hex[:12],
        status="denied",
        error=error,
        exit_code=exit_code,
        risk=risk,
        action=action,
        reason=error,
        sandbox=sandbox,
    )


def _sandbox_denied(exc: "sandbox_exec.SandboxError") -> ExecuteResponse:
    """沙箱没能施加 → **命令不执行**（fail-closed 的统一出口，派生点共用）。

    错误串带 ``[SANDBOX]`` 前缀，调用方与审计一眼能分清「被策略拦」与「没装上沙箱」。
    """
    logger.error("dispatcher.sandbox_denied", error=str(exc), state=exc.state)
    return _err(f"[SANDBOX] {exc}", exit_code=126, sandbox=exc.state)


def _check_file_path(path: str) -> tuple[bool, str]:
    """Validate a filesystem path. Returns (ok, normalized_or_error)."""
    try:
        p = Path(path).resolve()
        return True, str(p)
    except (OSError, ValueError, RuntimeError) as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class Dispatcher(Protocol):
    """Protocol for a tool dispatcher."""

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        ...


# ===================================================================
# File Dispatcher — native Python file operations
# ===================================================================


class FileDispatcher:
    """Native Python file operations — no shell subprocess."""

    MAX_READ_BYTES = 10 * 1024 * 1024  # 10 MB

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        tool = request.tool
        args = request.args

        if tool == ToolType.FILE_READ:
            return await self._read(args, request.timeout_seconds)
        if tool == ToolType.FILE_WRITE:
            return await self._write(args)
        if tool == ToolType.FILE_DELETE:
            return await self._delete(args)
        if tool == ToolType.FILE_LIST:
            return await self._list_dir(args)
        if tool == ToolType.FILE_MOVE:
            return await self._move(args)
        if tool == ToolType.FILE_COPY:
            return await self._copy(args)
        if tool == ToolType.FILE_SEARCH:
            return await self._search(args)
        return _err(f"Unsupported file tool: {tool}", risk=RiskLevel.LOW)

    async def _read(self, args: list[str], timeout: float = 30.0) -> ExecuteResponse:
        if not args:
            return _err("Usage: file.read <path> [offset] [limit]")
        path = args[0]
        ok, resolved = _check_file_path(path)
        if not ok:
            return _err(f"Invalid path: {resolved}")
        if not os.path.isfile(resolved):
            return _err(f"Not a file: {resolved}")

        offset = int(args[1]) if len(args) > 1 else 0
        limit = int(args[2]) if len(args) > 2 else 0

        try:
            loop = asyncio.get_event_loop()

            def _read_file() -> str:
                size = os.path.getsize(resolved)
                if size > self.MAX_READ_BYTES and limit == 0:
                    return f"<File too large: {size} bytes. Use offset/limit or file.search.>"
                with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                    if offset > 0:
                        f.seek(offset)
                    if limit > 0:
                        return f.read(limit)
                    return f.read()

            content = await loop.run_in_executor(None, _read_file)
            return _ok(content)
        except PermissionError:
            return _err(f"Permission denied: {resolved}")
        except Exception as e:
            return _err(f"Read error: {e}")

    async def _write(self, args: list[str]) -> ExecuteResponse:
        if len(args) < 2:
            return _err("Usage: file.write <path> <content> [mode=w]")
        path = args[0]
        content = args[1]
        mode = args[2] if len(args) > 2 else "w"
        if mode not in ("w", "a"):
            return _err(f"Invalid write mode: {mode} (use w or a)")
        ok, resolved = _check_file_path(path)
        if not ok:
            return _err(f"Invalid path: {resolved}")
        try:
            loop = asyncio.get_event_loop()
            def _write_file() -> None:
                with open(resolved, mode, encoding="utf-8") as f:
                    f.write(content)
            await loop.run_in_executor(None, _write_file)
            return _ok(f"Wrote {len(content)} bytes to {resolved}")
        except PermissionError:
            return _err(f"Permission denied: {resolved}")
        except Exception as e:
            return _err(f"Write error: {e}")

    async def _delete(self, args: list[str]) -> ExecuteResponse:
        if not args:
            return _err("Usage: file.delete <path> [force=false]")
        path = args[0]
        force = len(args) > 1 and args[1].lower() in ("true", "1", "yes")
        ok, resolved = _check_file_path(path)
        if not ok:
            return _err(f"Invalid path: {resolved}")
        try:
            loop = asyncio.get_event_loop()
            def _do_delete() -> None:
                p = Path(resolved)
                if p.is_dir():
                    if force:
                        shutil.rmtree(resolved)
                    else:
                        p.rmdir()
                else:
                    p.unlink()
            await loop.run_in_executor(None, _do_delete)
            return _ok(f"Deleted: {resolved}")
        except OSError as e:
            return _err(f"Delete failed (try force=true?): {e}")
        except Exception as e:
            return _err(f"Delete error: {e}")

    async def _list_dir(self, args: list[str]) -> ExecuteResponse:
        path = args[0] if args else "."
        show_hidden = len(args) > 1 and args[1].lower() in ("true", "1", "yes", "-a")
        long_format = len(args) > 2 and args[2].lower() in ("true", "1", "yes", "-l")
        ok, resolved = _check_file_path(path)
        if not ok:
            return _err(f"Invalid path: {resolved}")
        if not os.path.isdir(resolved):
            return _err(f"Not a directory: {resolved}")
        try:
            loop = asyncio.get_event_loop()
            def _list() -> str:
                entries = os.listdir(resolved)
                if not show_hidden:
                    entries = [e for e in entries if not e.startswith(".")]
                if long_format:
                    lines = []
                    for e in sorted(entries):
                        full = os.path.join(resolved, e)
                        try:
                            st = os.stat(full)
                            m = stat.filemode(st.st_mode)
                            lines.append(f"{m} {st.st_uid}:{st.st_gid} {st.st_size:>8} {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))} {e}")
                        except OSError:
                            lines.append(f"? {e}")
                    return "\n".join(lines)
                return "\n".join(sorted(entries))
            listing = await loop.run_in_executor(None, _list)
            return _ok(listing)
        except PermissionError:
            return _err(f"Permission denied: {resolved}")
        except Exception as e:
            return _err(f"List error: {e}")

    async def _move(self, args: list[str]) -> ExecuteResponse:
        if len(args) < 2:
            return _err("Usage: file.move <src> <dst>")
        ok_src, src_r = _check_file_path(args[0])
        if not ok_src:
            return _err(f"Invalid source: {src_r}")
        ok_dst, dst_r = _check_file_path(args[1])
        if not ok_dst:
            return _err(f"Invalid dest: {dst_r}")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, shutil.move, src_r, dst_r)
            return _ok(f"Moved: {src_r} -> {dst_r}")
        except Exception as e:
            return _err(f"Move error: {e}")

    async def _copy(self, args: list[str]) -> ExecuteResponse:
        if len(args) < 2:
            return _err("Usage: file.copy <src> <dst>")
        ok_src, src_r = _check_file_path(args[0])
        if not ok_src:
            return _err(f"Invalid source: {src_r}")
        ok_dst, dst_r = _check_file_path(args[1])
        if not ok_dst:
            return _err(f"Invalid dest: {dst_r}")
        try:
            loop = asyncio.get_event_loop()
            def _do_copy():
                if os.path.isdir(src_r):
                    shutil.copytree(src_r, dst_r, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_r, dst_r)
            await loop.run_in_executor(None, _do_copy)
            return _ok(f"Copied: {src_r} -> {dst_r}")
        except Exception as e:
            return _err(f"Copy error: {e}")

    async def _search(self, args: list[str]) -> ExecuteResponse:
        if len(args) < 1:
            return _err("Usage: file.search <pattern> [path] [max_results=50]")
        pattern = args[0]
        search_path = args[1] if len(args) > 1 else "."
        max_results = int(args[2]) if len(args) > 2 else 50
        ok, resolved = _check_file_path(search_path)
        if not ok:
            return _err(f"Invalid path: {resolved}")
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            return _err(f"Invalid regex: {e}")
        try:
            loop = asyncio.get_event_loop()
            def _do_search() -> str:
                results = []
                for fpath in Path(resolved).rglob("*"):
                    if len(results) >= max_results:
                        break
                    if not fpath.is_file():
                        continue
                    try:
                        if os.path.getsize(fpath) > 1024 * 1024:
                            continue
                        text = fpath.read_text(encoding="utf-8", errors="replace")
                        for lineno, line in enumerate(text.splitlines(), 1):
                            if compiled.search(line):
                                results.append(f"{fpath}:{lineno}:{line.rstrip()[:200]}")
                                if len(results) >= max_results:
                                    break
                    except (OSError, UnicodeDecodeError):
                        continue
                if not results:
                    return f"No matches for pattern: {pattern}"
                return "\n".join(results[:max_results])
            output = await loop.run_in_executor(None, _do_search)
            return _ok(output)
        except Exception as e:
            return _err(f"Search error: {e}")


# ===================================================================
# Git Dispatcher — safe subprocess (no shell=True)
# ===================================================================


class GitDispatcher:
    """Git operations via ``sandbox_exec``（Layer K 施加点，不再直接 spawn）。"""

    GIT_CMD = "git"

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        tool = request.tool
        args = request.args
        cwd = request.cwd

        subcmd = self._tool_to_git_subcommand(tool)
        if subcmd is None:
            return _err(f"Unsupported git tool: {tool}", risk=RiskLevel.LOW)

        git_args: list[str] = []
        if subcmd == "log":
            git_args = ["log", "--oneline", "-20"]
        elif subcmd == "commit":
            msg = args[0] if args else "trimum: auto commit"
            git_args = ["commit", "-m", msg]
        elif subcmd == "push":
            remote = args[0] if args else "origin"
            branch = args[1] if len(args) > 1 else "main"
            git_args = ["push", remote, branch]
        elif subcmd == "pull":
            remote = args[0] if args else "origin"
            branch = args[1] if len(args) > 1 else "main"
            git_args = ["pull", remote, branch]
        elif subcmd == "branch":
            if args and args[0] not in ("-a", "-r", "--list"):
                git_args = ["branch", args[0]]
            else:
                git_args = ["branch", "-a"]
        elif subcmd == "diff":
            git_args = ["diff"] + args
        elif subcmd == "status":
            git_args = ["status"] + args
        else:
            git_args = args

        return await self._run_git(git_args, cwd, request.timeout_seconds, request)

    @staticmethod
    def _tool_to_git_subcommand(tool: ToolType) -> Optional[str]:
        mapping: dict[ToolType, str] = {
            ToolType.GIT: "",
            ToolType.GIT_STATUS: "status",
            ToolType.GIT_DIFF: "diff",
            ToolType.GIT_LOG: "log",
            ToolType.GIT_COMMIT: "commit",
            ToolType.GIT_PUSH: "push",
            ToolType.GIT_PULL: "pull",
            ToolType.GIT_BRANCH: "branch",
        }
        return mapping.get(tool)

    async def _run_git(
        self,
        git_args: list[str],
        cwd: Optional[str],
        timeout: float = 30.0,
        request: Optional[ExecuteRequest] = None,
    ) -> ExecuteResponse:
        cmd = [self.GIT_CMD] + git_args
        plan = sandbox_exec.plan_for(request, cwd=cwd)
        try:
            proc = await sandbox_exec.spawn_exec(
                plan, *cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=cwd,
            )
        except sandbox_exec.SandboxError as exc:
            return _sandbox_denied(exc)
        except FileNotFoundError:
            return _err("Git not found", exit_code=127, sandbox=plan.state)
        except Exception as e:
            return _err(f"Git error: {e}", exit_code=-1, sandbox=plan.state)

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return _err(f"Git timed out after {timeout}s", exit_code=-1, sandbox=plan.state)

        out = stdout.decode("utf-8", errors="replace") if stdout else ""
        err = stderr.decode("utf-8", errors="replace") if stderr else ""
        rc = proc.returncode or 0
        if rc == 0:
            return _ok(out.strip(), sandbox=plan.state)
        return _err(err or f"Git failed (rc={rc})", exit_code=rc, sandbox=plan.state)


# ===================================================================
# HTTP Dispatcher — stdlib only (urllib)
# ===================================================================


class HttpDispatcher:
    """HTTP requests using Python stdlib. No external deps needed."""

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        tool = request.tool
        args = request.args
        if tool == ToolType.HTTP_GET:
            return await self._get(args, request.timeout_seconds)
        if tool == ToolType.HTTP_POST:
            return await self._post(args, request.timeout_seconds)
        if tool == ToolType.HTTP:
            if not args:
                return _err("Usage: http <method> <url> [body]")
            method = args[0].upper()
            url = args[1] if len(args) > 1 else ""
            body = args[2] if len(args) > 2 else None
            if method == "GET":
                return await self._get([url], request.timeout_seconds)
            elif method == "POST":
                return await self._post([url, body] if body else [url], request.timeout_seconds)
            return _err(f"Unsupported HTTP method: {method}")
        return _err(f"Unsupported http tool: {tool}")

    async def _get(self, args: list[str], timeout: float = 30.0) -> ExecuteResponse:
        if not args:
            return _err("Usage: http.get <url>")
        url = args[0]
        try:
            loop = asyncio.get_event_loop()
            def _do_get() -> str:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    return f"[{resp.status}] {body[:10000]}"
            result = await loop.run_in_executor(None, _do_get)
            return _ok(result)
        except Exception as e:
            return _err(f"HTTP GET error: {e}")

    async def _post(self, args: list[str], timeout: float = 30.0) -> ExecuteResponse:
        if len(args) < 1:
            return _err("Usage: http.post <url> [body] [content_type]")
        url = args[0]
        body = args[1].encode("utf-8") if len(args) > 1 else b""
        content_type = args[2] if len(args) > 2 else "application/json"
        try:
            loop = asyncio.get_event_loop()
            def _do_post() -> str:
                data = body
                req = urllib.request.Request(url, data=data, method="POST")
                req.add_header("Content-Type", content_type)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    resp_body = resp.read().decode("utf-8", errors="replace")
                    return f"[{resp.status}] {resp_body[:10000]}"
            result = await loop.run_in_executor(None, _do_post)
            return _ok(result)
        except Exception as e:
            return _err(f"HTTP POST error: {e}")


# ===================================================================
# Process Dispatcher
# ===================================================================


class ProcessDispatcher:
    """Process operations via os + ``sandbox_exec``（Layer K 施加点）。"""

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        tool = request.tool
        args = request.args

        if tool == ToolType.PROCESS_LIST:
            return await self._list_processes(request)
        if tool == ToolType.PROCESS_KILL:
            return await self._kill_process(args, request)
        if tool == ToolType.PROCESS:
            if args and args[0] == "list":
                return await self._list_processes(request)
            if args and args[0] == "kill":
                return await self._kill_process(args[1:], request)
            return _err("Usage: process list | process kill <pid>")
        return _err(f"Unsupported process tool: {tool}", risk=RiskLevel.LOW)

    async def _list_processes(self, request: Optional[ExecuteRequest] = None) -> ExecuteResponse:
        """List running processes via `ps aux` on Linux or `tasklist` on Windows."""
        verb = ["tasklist", "/FO", "CSV", "/NH"] if platform.system() == "Windows" else ["ps", "aux"]
        plan = sandbox_exec.plan_for(request)
        try:
            proc = await sandbox_exec.spawn_exec(
                plan, *verb,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except sandbox_exec.SandboxError as exc:
            return _sandbox_denied(exc)
        stdout, stderr = await proc.communicate()
        out = stdout.decode("utf-8", errors="replace") if stdout else ""
        err = stderr.decode("utf-8", errors="replace") if stderr else ""
        if proc.returncode == 0:
            return _ok(out.strip()[:5000], sandbox=plan.state)
        return _err(
            err or f"ps/tasklist failed (rc={proc.returncode})",
            exit_code=proc.returncode or 1,
            sandbox=plan.state,
        )

    async def _kill_process(
        self,
        args: list[str],
        request: Optional[ExecuteRequest] = None,
    ) -> ExecuteResponse:
        if not args:
            return _err("Usage: process kill <pid> [signal=15]")
        pid = args[0]
        signal_num = args[1] if len(args) > 1 else ("9" if platform.system() == "Windows" else "15")
        verb = (
            ["taskkill", "/F" if signal_num == "9" else "", "/PID", pid]
            if platform.system() == "Windows"
            else ["kill", f"-{signal_num}", pid]
        )
        plan = sandbox_exec.plan_for(request)
        try:
            proc = await sandbox_exec.spawn_exec(
                plan, *verb,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except sandbox_exec.SandboxError as exc:
            return _sandbox_denied(exc)
        try:
            stdout, stderr = await proc.communicate()
            out = stdout.decode("utf-8", errors="replace") if stdout else ""
            err = stderr.decode("utf-8", errors="replace") if stderr else ""
            if proc.returncode == 0:
                return _ok(f"Killed PID {pid}", sandbox=plan.state)
            return _err(
                err or f"Kill failed (rc={proc.returncode})",
                exit_code=proc.returncode or 1,
                sandbox=plan.state,
            )
        except Exception as e:
            return _err(f"Kill error: {e}", sandbox=plan.state)


# ===================================================================
# System Dispatcher
# ===================================================================


class SystemDispatcher:
    """System information via os / platform stdlib."""

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        tool = request.tool
        if tool == ToolType.SYSTEM_INFO:
            return _ok(self._get_system_info())
        if tool == ToolType.SYSTEM_DISK:
            return _ok(self._get_disk_info())
        if tool == ToolType.SYSTEM_MEMORY:
            return _ok(self._get_memory_info())
        if tool == ToolType.SYSTEM:
            args = request.args
            if not args:
                return _ok(self._get_system_info())
            sub = args[0].lower()
            if sub == "info":
                return _ok(self._get_system_info())
            elif sub == "disk":
                return _ok(self._get_disk_info())
            elif sub == "memory":
                return _ok(self._get_memory_info())
            return _err("Usage: system [info|disk|memory]")
        return _err(f"Unsupported system tool: {tool}", risk=RiskLevel.LOW)

    @staticmethod
    def _get_system_info() -> str:
        lines = [
            f"System: {platform.system()} {platform.release()}",
            f"Node: {platform.node()}",
            f"Machine: {platform.machine()}",
            f"Processor: {platform.processor()}",
            f"Python: {platform.python_version()}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _get_disk_info() -> str:
        if platform.system() == "Windows":
            # Use shutil.disk_usage for current drive
            usage = shutil.disk_usage(os.path.abspath("."))
            return (
                f"Disk ({os.path.abspath('.')}):\n"
                f"  Total: {usage.total // (1024**3)} GB\n"
                f"  Used:  {usage.used // (1024**3)} GB\n"
                f"  Free:  {usage.free // (1024**3)} GB\n"
                f"  %:     {usage.used * 100 // usage.total}%"
            )
        else:
            try:
                import shutil as sh
                usage = sh.disk_usage("/")
                return (
                    f"Disk (/):\n"
                    f"  Total: {usage.total // (1024**3)} GB\n"
                    f"  Used:  {usage.used // (1024**3)} GB\n"
                    f"  Free:  {usage.free // (1024**3)} GB"
                )
            except Exception as e:
                return f"Disk info unavailable: {e}"

    @staticmethod
    def _get_memory_info() -> str:
        try:
            import shutil
            shutil.disk_usage("/")  # validate path
            # Not real memory, just placeholder until psutil available
            return "Memory info requires psutil. System info available via `system info`."
        except Exception as e:
            return f"Memory info unavailable: {e}"


# ===================================================================
# Shell Dispatcher — original subprocess fallback
# ===================================================================


class ShellDispatcher:
    """Shell command execution via ``sandbox_exec.spawn_shell``.

    This is the original _run_subprocess behavior, preserved for
    legitimate shell use (pipes, compound commands).

    内核层沙箱施在**子进程**上（preexec 钩子），daemon 自己不进沙箱 —— Landlock
    只能收紧、不可逆，施在自己身上就退不下来了（docs/SANDBOX-PLAN.md §6.1）。
    """

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        """Execute a shell command via a sandboxed subprocess shell=True."""
        cmd_str = " ".join(request.args) if isinstance(request.args, list) else request.args
        cmd_str = cmd_str.strip()
        if not cmd_str:
            return _err("Empty command")

        plan = sandbox_exec.plan_for(request)
        try:
            proc = await sandbox_exec.spawn_shell(
                plan,
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=request.env if request.env else None,
                cwd=request.cwd,
            )
        except sandbox_exec.SandboxError as exc:
            return _sandbox_denied(exc)
        except FileNotFoundError:
            return _err("Command not found", exit_code=127, sandbox=plan.state)
        except Exception as e:
            return _err(f"Shell error: {e}", exit_code=-1, sandbox=plan.state)

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=request.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return _err(
                f"Shell command timed out after {request.timeout_seconds}s",
                exit_code=-1,
                sandbox=plan.state,
            )
        except Exception as e:
            return _err(f"Shell error: {e}", exit_code=-1, sandbox=plan.state)

        out = stdout.decode("utf-8", errors="replace") if stdout else ""
        err = stderr.decode("utf-8", errors="replace") if stderr else ""
        rc = proc.returncode or 0

        return ExecuteResponse(
            execution_id=uuid.uuid4().hex[:12],
            status="allowed" if rc == 0 else "error",
            output=out,
            error=err,
            exit_code=rc,
            risk=RiskLevel.MEDIUM,
            action=Action.AUTO,
            sandbox=plan.state,
        )


# ===================================================================
# Env Dispatcher
# ===================================================================


class EnvDispatcher:
    """Environment variable operations."""

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        tool = request.tool
        args = request.args

        if tool == ToolType.ENV_GET:
            if not args:
                return _err("Usage: env.get <key>")
            val = os.environ.get(args[0], "")
            return _ok(f"{args[0]}={val}")
        if tool == ToolType.ENV_LIST:
            lines = sorted([f"{k}={v}" for k, v in os.environ.items()])
            return _ok("\n".join(lines))
        return _err(f"Unsupported env tool: {tool}", risk=RiskLevel.LOW)


# ===================================================================
# Reserved Dispatchers (stubs for future phases)
# ===================================================================


class KnowledgeDispatcher:
    """Placeholder for Knowledge/Memory layer (Phase 5)."""

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        return _err("Knowledge store not yet available (Phase 5)")


class NotificationDispatcher:
    """Placeholder for notification system."""

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        return _err("Notification system not yet available")


class MCPDispatcher:
    """MCP tool bridging — ``mcp.tools.list`` / ``mcp.tools.call``.

    Server definitions live in ``~/.trimum/mcp/<name>.json5`` (deny-by-default, see
    ``mcp_registry.py``) and the protocol lives in ``mcp_client.py``; this class is
    only the translation layer between trimum's argument convention and MCP:

    * ``mcp.tools.list [server]`` — one named server, or every enabled server;
    * ``mcp.tools.call <server> <tool> [json-arguments]`` — one tool invocation.

    Output is JSON (agents consume it directly).  Every call emits an ``mcp_call``
    audit event — server, tool, duration and outcome, never the argument *values* —
    and is broadcast as ``task.audit.mcp_call`` when an EventBus is bound by
    :class:`~trimum_core.tool_gateway.ToolGateway`.
    """

    def __init__(
        self,
        *,
        registry: Any = None,
        pool: Any = None,
        tool_index: Any = None,
        audit_store: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._registry = registry
        self._pool = pool
        self._tool_index = tool_index
        self.audit_store = audit_store
        self.event_bus = event_bus
        self._audit_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def bind_audit(self, *, audit_store: Any = None, event_bus: Any = None) -> None:
        """Attach the audit sinks (ToolGateway calls this once it is built)."""
        if audit_store is not None:
            self.audit_store = audit_store
        if event_bus is not None:
            self.event_bus = event_bus

    @property
    def registry(self) -> Any:
        """Server registry, created on first use (cheap: reads files only)."""
        if self._registry is None:
            from .mcp_registry import MCPRegistry

            self._registry = MCPRegistry()
        return self._registry

    @property
    def pool(self) -> Any:
        """Connection pool, created on first use (spawns servers lazily)."""
        if self._pool is None:
            from .mcp_registry import MCPServerPool

            self._pool = MCPServerPool(self.registry)
        return self._pool

    @property
    def tool_index(self) -> Any:
        """Index of aggregated remote tools, built on first use.

        Lazy for the same reason the pool is: an idle daemon should not touch
        the cache file until something actually asks for aggregated names.
        """
        if self._tool_index is None:
            from .mcp_bridge import MCPToolIndex

            self._tool_index = MCPToolIndex()
        return self._tool_index

    def set_tool_index(self, index: Any) -> None:
        """Adopt a shared index — the daemon hands over the one instance."""
        if index is not None:
            self._tool_index = index

    def status(self) -> dict[str, Any]:
        """Registry view for ``trm mcp list`` (no server is started)."""
        return self.registry.describe()

    def set_pool(self, pool: Any) -> None:
        """Adopt a shared pool — the daemon builds one and hands it over.

        Idempotent by design: ``MCP_TOOLS_LIST`` and ``MCP_TOOLS_CALL`` are two
        keys onto a *single* dispatcher instance, so startup walks the type
        table and may well hand the same pool over twice.  The daemon does this
        before the first call, so nothing is connected yet when it happens.
        """
        if pool is not None and pool is not self._pool:
            self._pool = pool

    async def pool_status(self) -> list[dict[str, Any]]:
        """Live view of the pool: what is running, idle for how long, bound."""
        return await self.pool.status()

    async def restart_server(self, name: str) -> bool:
        """Stop and reconnect one server, leaving the others alone."""
        return await self.pool.restart(name)

    async def close(self) -> None:
        """Stop every server this dispatcher started."""
        if self._pool is not None:
            await self._pool.close_all()

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        if request.tool == ToolType.MCP_TOOLS_LIST:
            return await self._list_tools(request)
        if request.tool == ToolType.MCP_TOOLS_CALL:
            return await self._call_tool(request)
        return _err(f"Unsupported MCP tool: {request.tool}", risk=RiskLevel.LOW)

    async def _list_tools(self, request: ExecuteRequest) -> ExecuteResponse:
        from .mcp_client import MCPError

        wanted = [str(arg) for arg in request.args if str(arg).strip()]
        if wanted:
            definition = self.registry.get(wanted[0])
            if definition is None:
                return _err(self._not_found(wanted[0]))
            if not definition.enabled:
                return _err(self._disabled(definition))
            definitions = [definition]
        else:
            definitions = self.registry.enabled()
            if not definitions:
                return _err(
                    "No enabled MCP server found in "
                    f"{self.registry.directory} (deny-by-default: set "
                    '"enabled": true in <name>.json5)'
                )

        servers: list[dict[str, Any]] = []
        for definition in definitions:
            try:
                client = await self.pool.client(definition.name)
                tools = await client.list_tools()
            except MCPError as exc:
                servers.append(
                    {"server": definition.name, "ok": False, "error": str(exc), "tools": []}
                )
                continue
            servers.append(
                {
                    "server": definition.name,
                    "ok": True,
                    "trust": definition.trust,
                    "risk": definition.risk,
                    "count": len(tools),
                    "tools": [tool.to_dict() for tool in tools],
                }
            )
            # 顺手写下清单：`trm tool list` 读的就是这份缓存，所以「列远端
            # 工具」不会把已经空闲回收掉的 server 再拉起来。
            self.tool_index.record(definition, [tool.to_dict() for tool in tools])

        failures = [row for row in servers if not row["ok"]]
        if failures and len(failures) == len(servers):
            return _err(
                "MCP tools/list failed: "
                + "; ".join(f"{row['server']}: {row['error']}" for row in failures)
            )

        output = json.dumps({"servers": servers}, ensure_ascii=False, indent=2)
        return _ok(
            output,
            risk=RiskLevel.MEDIUM if failures else RiskLevel.LOW,
        )

    async def _call_tool(self, request: ExecuteRequest) -> ExecuteResponse:
        from .mcp_client import MCPError

        args = [str(arg) for arg in request.args if str(arg).strip()]
        split = self._split_call(args)
        if split is None:
            return _err(
                "Usage: mcp.tools.call <server> <tool> [json-arguments] "
                "(example: mcp.tools.call filesystem read_file '{\"path\": \"/tmp/x\"}') "
                "- or the aggregated name shown by `trm tool list`: "
                "mcp.tools.call <server>__<tool> [json-arguments]"
            )

        server_name, tool_name, raw_arguments = split
        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
        except ValueError as exc:
            return _err(f"MCP tool arguments must be a JSON object: {exc}")
        if not isinstance(arguments, dict):
            return _err("MCP tool arguments must be a JSON object")

        definition = self.registry.get(server_name)
        if definition is None:
            return _err(self._not_found(server_name))
        if not definition.enabled:
            return _err(self._disabled(definition))
        if not definition.allows_tool(tool_name):
            patterns = ", ".join(definition.deny_patterns()) or "(allow_tools list)"
            reason = (
                f"MCP tool '{tool_name}' is denied for server '{definition.name}' "
                f"(allow_tools/deny_tools; deny patterns: {patterns})"
            )
            # 被策略拦下的调用也要留痕（它压根没触达服务器，duration 为 0）
            self._record_audit(
                request,
                definition,
                tool=tool_name,
                ok=False,
                is_error=False,
                duration_ms=0,
                error=reason,
                action="denied",
            )
            return _err(reason)

        started = time.monotonic()
        try:
            client = await self.pool.client(definition.name)
            result = await client.call_tool(tool_name, arguments, timeout=definition.timeout)
        except MCPError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            self._record_audit(
                request,
                definition,
                tool=tool_name,
                ok=False,
                is_error=False,
                duration_ms=duration_ms,
                error=str(exc),
                action="denied",
            )
            return _err(
                f"MCP call failed (TRM-4007): {exc}",
                risk=RiskLevel(definition.risk),
            )

        payload = {
            **result.to_dict(),
            "trust": definition.trust,
            "transport": definition.transport,
        }
        self._record_audit(
            request,
            definition,
            tool=tool_name,
            ok=not result.is_error,
            is_error=result.is_error,
            duration_ms=result.duration_ms,
            error=result.text[:300] if result.is_error else "",
            action="allowed",
            argument_keys=sorted(arguments),
        )

        output = json.dumps(payload, ensure_ascii=False, indent=2)
        if result.is_error:
            return ExecuteResponse(
                execution_id=uuid.uuid4().hex[:12],
                status="error",
                output=output,
                error=result.text[:400] or "MCP tool reported an error",
                exit_code=1,
                risk=RiskLevel(definition.risk),
                action=Action.AUTO,
                reason=f"MCP tool '{tool_name}' returned isError",
            )
        return _ok(output, risk=RiskLevel(definition.risk))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _split_call(self, args: list[str]) -> tuple[str, str, str] | None:
        """Parse call arguments into ``(server, tool, json)``; None if unusable.

        Both spellings mean the same thing::

            mcp.tools.call <server> <tool> [json-arguments]
            mcp.tools.call <server>__<tool> [json-arguments]

        The second is the name ``trm tool list`` shows for aggregated remote
        tools, so an agent reading that list does not have to split it back
        apart by hand.

        The only real ambiguity is a server literally named ``a__b``.  Server
        names may contain ``__``, so the registry gets the casting vote: when
        ``args[0]`` is a defined server the classic reading wins, otherwise
        ``args[0]`` is an aggregated name.
        """
        if not args:
            return None
        parts = split_name(args[0])
        if parts is not None and self.registry.get(args[0]) is None:
            return parts[0], parts[1], " ".join(args[1:]).strip()
        if len(args) < 2:
            return None
        return args[0], args[1], " ".join(args[2:]).strip()

    def _not_found(self, name: str) -> str:
        known = ", ".join(self.registry.names()) or "(none)"
        return (
            f"MCP server not found: {name or '(empty)'} "
            f"(looked in {self.registry.directory}; known: {known})"
        )

    @staticmethod
    def _disabled(definition: Any) -> str:
        return (
            f"MCP server '{definition.name}' is disabled "
            f"(set enabled: true in {definition.path or 'its definition file'})"
        )

    def _record_audit(
        self,
        request: ExecuteRequest,
        definition: Any,
        *,
        tool: str,
        ok: bool,
        is_error: bool,
        duration_ms: int,
        error: str = "",
        action: str = "allowed",
        argument_keys: list[str] | None = None,
    ) -> None:
        """Append an ``mcp_call`` audit event and broadcast it (never raises)."""
        event = AuditEvent(
            event_id=uuid.uuid4().hex[:12],
            event_type="mcp_call",
            agent_id=request.agent_id or "unknown",
            agent_name=request.agent_manifest.name if request.agent_manifest else "unknown",
            tool=ToolType.MCP_TOOLS_CALL.value,
            command=f"{definition.name}.{tool}"[:500],
            risk=str(definition.risk),
            action=action,
            reason=error,
            details={
                "server": definition.name,
                "tool": tool,
                "transport": definition.transport,
                "trust": definition.trust,
                "duration_ms": duration_ms,
                "ok": ok,
                "is_error": is_error,
                "argument_keys": argument_keys or [],
                "path": definition.path,
            },
            timestamp=time.time(),
            source_type=getattr(request.source_type, "value", str(request.source_type)),
        )

        logger.info(
            "mcp.audit",
            server=definition.name,
            tool=tool,
            risk=definition.risk,
            action=action,
            duration_ms=duration_ms,
            ok=ok,
        )

        if self.audit_store is not None:
            self.audit_store.append(event)

        if self.event_bus is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - sync caller
            return
        try:
            task = loop.create_task(
                self.event_bus.emit_task(
                    "audit.mcp_call",
                    payload=event.model_dump(),
                    source="mcp",
                    severity="warning" if not ok else "info",
                )
            )
        except RuntimeError:  # pragma: no cover - loop already closing
            return
        self._audit_tasks.add(task)
        task.add_done_callback(self._audit_tasks.discard)




class CustomDispatcher:
    """Placeholder for custom executable/script dispatch."""

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        return _err("Custom tool dispatch not yet available")


# ===================================================================
# DispatcherRegistry — maps ToolType to Dispatcher
# ===================================================================


class DispatcherRegistry:
    """Registry mapping ToolType values to Dispatcher instances.

    Two-tier loading:
    1. File-based: ~/.trimum/tools/<name>/main.py exports ``execute()``
    2. Built-in fallback: hardcoded dispatchers

    Usage::

        registry = DispatcherRegistry(tools_path="~/.trimum/tools")
        registry.load_from_files()
        response = await registry.dispatch(request)
    """

    TOOLTYPE_MAP: dict[str, list[ToolType]] = {
        "file": [ToolType.FILE_READ, ToolType.FILE_WRITE, ToolType.FILE_DELETE,
                 ToolType.FILE_LIST, ToolType.FILE_MOVE, ToolType.FILE_COPY,
                 ToolType.FILE_SEARCH],
        "git": [ToolType.GIT, ToolType.GIT_STATUS, ToolType.GIT_DIFF,
                ToolType.GIT_LOG, ToolType.GIT_COMMIT, ToolType.GIT_PUSH,
                ToolType.GIT_PULL, ToolType.GIT_BRANCH],
        "http": [ToolType.HTTP, ToolType.HTTP_GET, ToolType.HTTP_POST],
        "process": [ToolType.PROCESS, ToolType.PROCESS_LIST, ToolType.PROCESS_KILL],
        "system": [ToolType.SYSTEM, ToolType.SYSTEM_INFO, ToolType.SYSTEM_DISK, ToolType.SYSTEM_MEMORY],
        "shell": [ToolType.SHELL],
        "env": [ToolType.ENV_GET, ToolType.ENV_LIST],
        "knowledge": [ToolType.KNOWLEDGE_SEARCH, ToolType.KNOWLEDGE_STORE],
        "notification": [ToolType.NOTIFICATION, ToolType.NOTIFICATION_SEND],
        "mcp": [ToolType.MCP_TOOLS_LIST, ToolType.MCP_TOOLS_CALL],
        "custom": [ToolType.CUSTOM],
    }

    def __init__(self, tools_path: str | None = None) -> None:
        self._dispatchers: dict[ToolType, Any] = {}
        self._tools_path = tools_path or str(Path.home() / ".trimum" / "tools")
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register built-in dispatchers as fallback."""
        file_d = FileDispatcher()
        git_d = GitDispatcher()
        http_d = HttpDispatcher()
        process_d = ProcessDispatcher()
        system_d = SystemDispatcher()
        shell_d = ShellDispatcher()
        env_d = EnvDispatcher()
        knowledge_d = KnowledgeDispatcher()
        notif_d = NotificationDispatcher()
        mcp_d = MCPDispatcher()
        custom_d = CustomDispatcher()

        for types, dispatcher in [
            (self.TOOLTYPE_MAP["file"], file_d),
            (self.TOOLTYPE_MAP["git"], git_d),
            (self.TOOLTYPE_MAP["http"], http_d),
            (self.TOOLTYPE_MAP["process"], process_d),
            (self.TOOLTYPE_MAP["system"], system_d),
            (self.TOOLTYPE_MAP["shell"], shell_d),
            (self.TOOLTYPE_MAP["env"], env_d),
            (self.TOOLTYPE_MAP["knowledge"], knowledge_d),
            (self.TOOLTYPE_MAP["notification"], notif_d),
            (self.TOOLTYPE_MAP["mcp"], mcp_d),
            (self.TOOLTYPE_MAP["custom"], custom_d),
        ]:
            for tt in types:
                self._dispatchers[tt] = dispatcher

    def load_from_files(self) -> int:
        """Scan ~/.trimum/tools/<name>/main.py and register file-based dispatchers.

        Each tool directory with a main.py exporting ``async def execute()``
        replaces the built-in dispatcher for its ToolType(s).

        Returns number of file-based dispatchers loaded.
        """
        import importlib.util
        import sys as _sys

        tools_dir = Path(self._tools_path)
        if not tools_dir.is_dir():
            return 0

        count = 0
        for child in sorted(tools_dir.iterdir()):
            if not child.is_dir():
                continue
            main_py = child / "main.py"
            if not main_py.is_file():
                continue

            tool_name = child.name
            if tool_name not in self.TOOLTYPE_MAP:
                continue

            try:
                # Dynamic import like a Minecraft mod
                spec = importlib.util.spec_from_file_location(
                    f"trimum_tool_{tool_name}",
                    str(main_py),
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                _sys.modules[spec.name] = module
                spec.loader.exec_module(module)

                if not hasattr(module, "execute"):
                    continue

                # Wrap module.execute into a dispatcher-compatible callable
                class _FileDispatcher:
                    def __init__(self, mod):
                        self._mod = mod

                    async def execute(self, request):
                        result = await self._mod.execute(request.model_dump())
                        if isinstance(result, dict):
                            return ExecuteResponse(**result)
                        return result

                fd = _FileDispatcher(module)
                for tt in self.TOOLTYPE_MAP[tool_name]:
                    self._dispatchers[tt] = fd

                count += 1
                logger.debug("dispatcher.file_loaded", tool=tool_name)

            except Exception as e:
                logger.warning("dispatcher.file_load_failed", tool=tool_name, error=str(e))
                continue

        return count

    def register(self, tool_type: ToolType, dispatcher: Any) -> None:
        """Register (or override) a dispatcher for a specific ToolType."""
        self._dispatchers[tool_type] = dispatcher
        logger.debug("dispatcher_registry.register", tool=tool_type.value)

    def get(self, tool_type: ToolType) -> Optional[Any]:
        """Get the dispatcher for a ToolType, or None."""
        return self._dispatchers.get(tool_type)

    async def dispatch(self, request: ExecuteRequest) -> ExecuteResponse:
        """Execute a request via the appropriate dispatcher.

        Falls back to ShellDispatcher if no specific dispatcher is registered.
        """
        dispatcher = self._dispatchers.get(request.tool)
        if dispatcher is None:
            # Fallback: use ShellDispatcher for unrecognised tools
            logger.warning("dispatcher_registry.fallback", tool=request.tool.value)
            dispatcher = self._dispatchers.get(ToolType.SHELL)

        if dispatcher is None:
            return _err(f"No dispatcher available for tool: {request.tool.value}")

        return await dispatcher.execute(request)


__all__ = [
    "Dispatcher",
    "DispatcherRegistry",
    "FileDispatcher",
    "GitDispatcher",
    "HttpDispatcher",
    "ProcessDispatcher",
    "SystemDispatcher",
    "ShellDispatcher",
    "EnvDispatcher",
    "KnowledgeDispatcher",
    "NotificationDispatcher",
    "MCPDispatcher",
    "CustomDispatcher",
]
