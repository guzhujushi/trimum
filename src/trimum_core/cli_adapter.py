"""通用 CLI 适配器（E4）—— 把机器上已有的命令行工具登记成 trimum 工具。

动机（`docs/ECOSYSTEM-STRATEGY.md` 缺口 #4）：为每个应用手写 harness 不可持续，
而绝大多数 CLI 自己就有 ``--help``。本模块做四件事：

1. **探测**（:func:`probe_binary`）：跑 ``<binary> --help``（必要时补 ``-h``，再对少量子命令
   各跑一次 ``<binary> <sub> --help``），全程只读；
2. **解析**（:func:`parse_help`）：从帮助文本里抽子命令与旗标。**解析不到就不写** ——
   宁可少登记，也不编一个不存在的子命令；
3. **定级**（``ecosystem.assess_risk``）：子命令名 + 旗标 → 风险等级 + 理由；
4. **落盘**（:func:`write_tool`）：生成 ``tool.json5`` + 一层薄壳 ``main.py``，
   默认 ``enabled: false``（注册 ≠ 授权）。

生成物只是薄壳；真正的执行在 :func:`generic_executor`，它自己再兜一层白名单
（子命令必须在探测集合里、旗标必须在 ``allowed_flags`` 里、二进制必须用 ``shutil.which``
现算）—— 也就是说**手改 manifest 也绕不过这一层**。

``--help`` 的输出只用来**描述**能力，绝不用来执行；本模块不 import、不 eval 任何被导入物。
"""

from __future__ import annotations

import asyncio
import json
import locale
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import sandbox_exec
from .ecosystem import ESCALATING_FLAGS, EcosystemEntry, ImportRefused, assess_risk

#: 探测 ``--help`` 的候选旗标（按顺序试）。
HELP_FLAGS: tuple[str, ...] = ("--help", "-h")

#: 帮 ``--help`` 的默认超时（秒）—— 探测卡住比探测失败更糟。
PROBE_TIMEOUT = 5.0

#: 展开探测的子命令上限：``git`` / ``apt`` 这类巨型 CLI 不该把导入变成全量扫描。
DEFAULT_SUBCOMMAND_LIMIT = 12

#: 登记到 manifest 的子命令/旗标上限（防止 manifest 失控）。
MAX_SUBCOMMANDS = 64
MAX_FLAGS = 200

#: 生成工具的默认超时。
DEFAULT_TOOL_TIMEOUT = 30.0

_SAFE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
#: 两种命令块标题：裸标题（``COMMANDS``）与带句子的标题（``The most commonly used git commands are:``）。
_BARE_HEADING_RE = re.compile(
    r"^(commands?|subcommands?|命令|子命令)\s*[:：]?$",
    re.IGNORECASE,
)
#: 以 Commands 结尾的标题（``CORE COMMANDS``）。
_ENDS_WITH_COMMANDS_RE = re.compile(
    r"^.{0,80}(commands?|subcommands?|命令|子命令)\s*[:：]?\s*$",
    re.IGNORECASE,
)
#: 含 Commands 且以冒号结尾的标题（``The most commonly used git commands are:``）。
_SENTENCE_HEADING_RE = re.compile(
    r"^.{0,80}(commands?|subcommands?|命令|子命令).{0,80}[:：]\s*$",
    re.IGNORECASE,
)
#: 命令块内部的分组标题（``CORE COMMANDS`` / ``启动一个工作区：``），遇到它要接着往下扫。
_GROUP_HEADING_RE = re.compile(r"^(?:[A-Z][A-Z0-9 /_-]{2,30}|.{1,30}[:：])$")


def _is_commands_heading(line: str) -> bool:
    stripped = line.strip()
    return bool(
        _BARE_HEADING_RE.match(stripped)
        or _ENDS_WITH_COMMANDS_RE.match(stripped)
        or _SENTENCE_HEADING_RE.match(stripped)
    )
#: 子命令行：缩进 + 名字（可带结尾冒号，``gh`` 就是 ``auth:`` 这种写法）+ 至少两空格。
_SUBCOMMAND_LINE_RE = re.compile(r"^(\s+)([A-Za-z][A-Za-z0-9._-]*):?(\s{2,}|$)")
_LONG_FLAG_RE = re.compile(r"(?<![\w-])(--[A-Za-z][A-Za-z0-9-]{0,30})(?![\w-])")
_SHORT_FLAG_RE = re.compile(r"(?:^|[\s,(\[])(-[A-Za-z])(?=[\s,)\[\]=]|$)")
_UNKNOWN_COMMAND_RE = re.compile(r"unknown (command|subcommand)|not a .*command|no such command", re.I)


@dataclass
class ProbeResult:
    """探测一个外部 CLI 的结果（只读）。"""

    binary: str
    path: str = ""
    found: bool = False
    help_flag: str = ""
    help_text: str = ""
    subcommands: list[str] = field(default_factory=list)
    verified_subcommands: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    probed_subcommands: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "binary": self.binary,
            "path": self.path,
            "found": self.found,
            "help_flag": self.help_flag,
            "help_bytes": len(self.help_text),
            "subcommands": list(self.subcommands),
            "verified_subcommands": list(self.verified_subcommands),
            "flags": list(self.flags),
            "probed_subcommands": list(self.probed_subcommands),
            "error": self.error,
        }


# ----------------------------------------------------------------------
# 探测
# ----------------------------------------------------------------------


def _decode(raw: bytes | None) -> str:
    """Decode CLI output, preferring UTF-8 and falling back to the code page."""
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False) or "utf-8", errors="replace")


def default_runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    """Run one read-only help command and capture everything.

    Two Windows-specific hazards shape this helper, and both are load-bearing:

    * ``stdin`` is pinned to ``DEVNULL``：不少 CLI 的 ``<cmd> <sub> --help`` 会开分页器
      （Windows 上 ``git clone --help`` 就是），而分页器一旦继承了可读的 stdin 就会
      一直等下去。探测绝不能阻塞在输入上。
    * output goes to **临时文件，绝不用管道**：被探测的 CLI 可能留下一个仍持有继承写句柄
      的后台孙进程（分页器、凭据助手、子进程）。Windows 上 ``subprocess.run`` 超时后会
      ``kill()`` 再**无超时地** ``communicate()`` 一次，而永不 EOF 的管道就会让探测永远挂住
      （实测 ``import-cli git`` 挂死）。文件没有 EOF 握手，泄漏的句柄卡不住我们。
    """
    argv = list(argv)
    out_file = tempfile.TemporaryFile()
    err_file = tempfile.TemporaryFile()
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=out_file,
            stderr=err_file,
            timeout=timeout,
            check=False,
        )
        out_file.seek(0)
        err_file.seek(0)
        return subprocess.CompletedProcess(
            argv,
            completed.returncode,
            _decode(out_file.read()),
            _decode(err_file.read()),
        )
    finally:
        out_file.close()
        err_file.close()


def _combined_output(result: Any) -> str:
    out = getattr(result, "stdout", "") or ""
    err = getattr(result, "stderr", "") or ""
    return f"{out}\n{err}" if err else out


def _next_subcommand_line(lines: list[str], start: int) -> int | None:
    """Index of the next non-blank line when it looks like a ``word  description`` row."""
    index = start
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or not lines[index][:1].isspace():
        return None
    return index if _SUBCOMMAND_LINE_RE.match(lines[index]) else None


def parse_help(text: str) -> tuple[list[str], list[str]]:
    """Extract ``(subcommands, flags)`` from one help text.

    Subcommands are only taken from an explicit ``Commands:``-style block, and
    flags are pattern-matched over the whole text.  Anything ambiguous is left
    out on purpose: a wrong subcommand is worse than a missing one, because the
    adapter re-checks calls against this list at runtime.

    The block ends at the first unindented line that is **not** followed by a
    subcommand row — that is how the real ``git --help`` (group titles separated
    by blank lines, then an ``Options:`` section) is walked correctly.
    """
    subcommands: list[str] = []
    seen: set[str] = set()
    lines = text.splitlines()

    index = 0
    while index < len(lines):
        if not _is_commands_heading(lines[index]):
            index += 1
            continue

        index += 1
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if not stripped:
                index += 1
                continue
            if line[:1].isspace():
                match = _SUBCOMMAND_LINE_RE.match(line)
                if match:
                    name = match.group(2)
                    if name not in seen and len(subcommands) < MAX_SUBCOMMANDS:
                        seen.add(name)
                        subcommands.append(name)
                index += 1
                continue
            # 非缩进行：只有"下一行仍是子命令行"才算分组标题，否则命令块到此为止
            if _next_subcommand_line(lines, index + 1) is not None:
                index += 1
                continue
            break

    flags: list[str] = []
    flag_seen: set[str] = set()
    for pattern, group in ((_LONG_FLAG_RE, 1), (_SHORT_FLAG_RE, 1)):
        for match in pattern.finditer(text):
            flag = match.group(group)
            if flag in flag_seen or len(flags) >= MAX_FLAGS:
                continue
            flag_seen.add(flag)
            flags.append(flag)

    return subcommands, flags


def probe_binary(
    binary: str,
    *,
    runner: Callable[[Sequence[str], float], Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    timeout: float = PROBE_TIMEOUT,
    subcommand_limit: int = DEFAULT_SUBCOMMAND_LIMIT,
) -> ProbeResult:
    """Probe one binary with read-only help invocations.

    ``runner`` / ``which`` are injectable so tests never depend on a real
    binary being installed.
    """
    run = runner or default_runner
    resolve = which or shutil.which
    result = ProbeResult(binary=binary)

    name = (binary or "").strip()
    if not name:
        result.error = "empty binary name"
        return result

    path = resolve(name)
    if not path:
        result.error = f"binary not found on PATH: {name}"
        return result
    result.path = str(path)
    result.found = True

    for flag in HELP_FLAGS:
        try:
            completed = run([result.path, flag], timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            result.error = f"{flag} failed: {exc}"
            continue
        text = _combined_output(completed)
        if text.strip():
            result.help_flag = flag
            result.help_text = text
            break

    if not result.help_text:
        result.error = result.error or "no help output"
        return result

    subcommands, flags = parse_help(result.help_text)
    result.subcommands = subcommands
    result.flags = flags

    if subcommand_limit > 0 and subcommands:
        extra_flags = list(flags)
        for sub in subcommands[:subcommand_limit]:
            try:
                completed = run([result.path, sub, "--help"], timeout)
            except (OSError, subprocess.SubprocessError):
                continue
            text = _combined_output(completed)
            if not text.strip() or _UNKNOWN_COMMAND_RE.search(text):
                continue
            result.probed_subcommands.append(sub)
            result.verified_subcommands.append(sub)
            _, sub_flags = parse_help(text)
            for flag in sub_flags:
                if flag not in extra_flags and len(extra_flags) < MAX_FLAGS:
                    extra_flags.append(flag)
        result.flags = extra_flags

    return result


# ----------------------------------------------------------------------
# 定级与产物
# ----------------------------------------------------------------------


def safe_flags(flags: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split probed flags into ``(allowed, dropped)``.

    "免确认"类旗标（``--force`` / ``-y`` …）默认不进白名单：登记一个 CLI 不该顺手
    把它的"跳过确认"能力也登记进来。要放行就自己改 manifest。
    """
    allowed: list[str] = []
    dropped: list[str] = []
    for flag in flags:
        if flag.lower() in ESCALATING_FLAGS:
            dropped.append(flag)
        elif flag not in allowed:
            allowed.append(flag)
    return allowed, dropped


def build_entry(
    probe: ProbeResult,
    *,
    name: str | None = None,
    trust: str = "third-party",
    source_url: str = "",
    author: str = "",
    origin: str = "",
) -> EcosystemEntry:
    """Turn a probe into an ecosystem entry with graded risk."""
    tool_name = (name or probe.binary).strip().lower()
    risk, reasons = assess_risk(
        probe.binary,
        *probe.subcommands,
        flags=probe.flags,
    )
    description = (
        f"{probe.binary} — imported CLI "
        f"({len(probe.subcommands)} subcommands detected from {probe.help_flag or '--help'})"
    )
    return EcosystemEntry(
        name=tool_name,
        kind="tool",
        description=description,
        trust=trust,
        risk=risk,
        requires=[probe.binary],
        source_url=source_url,
        author=author,
        origin=origin or f"help-probe:{probe.path or probe.binary}",
        enabled=False,
        tags=["cli", "imported"],
        risk_reasons=reasons,
        details={
            "binary": probe.binary,
            "path": probe.path,
            "help_flag": probe.help_flag,
            "subcommands": list(probe.subcommands),
            "verified_subcommands": list(probe.verified_subcommands),
            "flags": list(probe.flags),
        },
    )


def tool_manifest(entry: EcosystemEntry, *, timeout: float = DEFAULT_TOOL_TIMEOUT) -> dict[str, Any]:
    """Build the ``tool.json5`` payload for an imported CLI."""
    details = entry.details or {}
    allowed, dropped = safe_flags(details.get("flags") or [])
    manifest = {
        "name": entry.name,
        "description": entry.description,
        "kind": "custom",
        "entry": "./main.py",
        "language": "python",
        "timeout": float(timeout),
        "risk": entry.risk,
        "allowed_flags": allowed,
        "enabled": bool(entry.enabled),
        # ── 生态元数据（缺口 #7：四层用同一套字段） ──
        "trust": entry.trust,
        "requires": list(entry.requires),
        "source_url": entry.source_url,
        "author": entry.author,
        "origin": entry.origin,
        "tags": list(entry.tags),
        "risk_reasons": list(entry.risk_reasons),
        "binding": {
            "binary": details.get("binary") or entry.name,
            "subcommands": list(details.get("subcommands") or []),
            "allowed_flags": allowed,
            "dropped_flags": dropped,
        },
    }
    return manifest


MAIN_TEMPLATE = '''"""Generated by `trm tool import-cli` — do not edit by hand.

Re-generate with: ``trm tool import-cli {binary} --force``
"""

from __future__ import annotations

from typing import Any

from trimum_core.cli_adapter import generic_executor

BINDING: dict[str, Any] = {binding}


async def execute(request: dict[str, Any]) -> dict[str, Any]:
    """Run the bound CLI; ToolGateway keeps ownership of policy and audit."""
    return await generic_executor(BINDING, request)
'''


def render_main_module(entry: EcosystemEntry) -> str:
    """Render the thin ``main.py`` shell for an imported CLI."""
    manifest = tool_manifest(entry)
    binding = manifest["binding"]
    return MAIN_TEMPLATE.format(
        binary=entry.details.get("binary") or entry.name,
        binding=json.dumps(binding, ensure_ascii=False, indent=4, sort_keys=True),
    )


def tools_root(root: Path | str | None = None) -> Path:
    """Return the tool root (``<TRIMUM_HOME>/tools`` by default)."""
    if root is not None:
        return Path(root).expanduser()
    from .paths import trimum_path

    return trimum_path("tools")


def plan_import(
    probe: ProbeResult,
    *,
    name: str | None = None,
    trust: str = "third-party",
    source_url: str = "",
    author: str = "",
    root: Path | str | None = None,
    timeout: float = DEFAULT_TOOL_TIMEOUT,
) -> dict[str, Any]:
    """Describe what importing this probe would do (used by ``--dry-run``)."""
    entry = build_entry(
        probe, name=name, trust=trust, source_url=source_url, author=author
    )
    manifest = tool_manifest(entry, timeout=timeout)
    target_dir = tools_root(root) / entry.name
    return {
        "entry": entry,
        "manifest": manifest,
        "main_module": render_main_module(entry),
        "target_dir": str(target_dir),
        "target_exists": target_dir.exists(),
        "files": [str(target_dir / "tool.json5"), str(target_dir / "main.py")],
        "warnings": list(entry.risk_reasons) if entry.risk in ("high", "critical") else [],
    }


def write_tool(
    plan: dict[str, Any],
    *,
    dry_run: bool = False,
    force: bool = False,
    enable: bool = False,
) -> list[str]:
    """Write the planned files. Returns paths (empty list for a dry run).

    Refuses to touch an existing tool directory unless ``force`` is set.
    """
    if dry_run:
        return []

    entry: EcosystemEntry = plan["entry"]
    target = Path(plan["target_dir"])
    if target.exists() and not force:
        raise ImportRefused(
            f"{target} already exists (use --force to overwrite)"
        )

    manifest = dict(plan["manifest"])
    if enable:
        entry.enabled = True
        manifest["enabled"] = True

    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "tool.json5"
    main_path = target / "main.py"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=4, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    main_path.write_text(plan["main_module"], encoding="utf-8", newline="\n")
    return [str(manifest_path), str(main_path)]


# ----------------------------------------------------------------------
# 生成的 main.py 使用的通用执行器
# ----------------------------------------------------------------------


def _ok(output: str = "", data: Any = None) -> dict[str, Any]:
    return {"status": "allowed", "output": output, "data": data, "error": "", "exit_code": 0}


def _err(error: str, exit_code: int = 1) -> dict[str, Any]:
    return {
        "status": "denied",
        "output": "",
        "data": None,
        "error": error,
        "exit_code": exit_code,
    }


def _flag_key(arg: str) -> str:
    """``--flag=value`` / ``--flag`` → ``--flag``."""
    return arg.split("=", 1)[0]


def validate_argv(binding: dict[str, Any], args: Sequence[str]) -> str:
    """Return an error message if *args* is not allowed by *binding*, else ""."""
    allowed_flags = set(binding.get("allowed_flags") or [])
    subcommands = list(binding.get("subcommands") or [])

    positional = [arg for arg in args if not arg.startswith("-")]
    for arg in args:
        if not arg.startswith("-"):
            continue
        key = _flag_key(arg)
        if key not in allowed_flags:
            return f"flag not allowed by {binding.get('binary')}: {key}"

    if positional and subcommands and positional[0] not in subcommands:
        preview = ", ".join(subcommands[:8])
        return f"unknown subcommand for {binding.get('binary')}: {positional[0]} (known: {preview})"

    return ""


async def generic_executor(
    binding: dict[str, Any],
    request: dict[str, Any],
    *,
    which: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Run the bound binary after re-checking the binding's own whitelists."""
    binary = str(binding.get("binary") or "").strip()
    if not binary:
        return _err("adapter binding has no binary")

    args = [str(item) for item in (request.get("args") or [])]
    problem = validate_argv(binding, args)
    if problem:
        return _err(problem, exit_code=2)

    resolve = which or shutil.which
    path = resolve(binary)
    if not path:
        return _err(f"binary not found on PATH: {binary}")

    timeout = request.get("timeout_seconds")
    try:
        timeout = float(timeout) if timeout else DEFAULT_TOOL_TIMEOUT
    except (TypeError, ValueError):
        timeout = DEFAULT_TOOL_TIMEOUT

    cwd = request.get("cwd") or None
    # Layer K：E4 的 CLI 广接入也是一条真实派生通道，同样收到 sandbox_exec
    plan = sandbox_exec.plan_for(request, cwd=cwd)
    try:
        proc = await sandbox_exec.spawn_exec(
            plan,
            path,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except sandbox_exec.SandboxError as exc:
        return {**_err(f"[SANDBOX] {exc}", exit_code=126), "sandbox": plan.state}
    except OSError as exc:
        return _err(f"cannot start {binary}: {exc}")

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return _err(f"{binary} timed out after {timeout:g}s", exit_code=124)

    out = (stdout or b"").decode("utf-8", "replace")
    err = (stderr or b"").decode("utf-8", "replace")
    exit_code = int(proc.returncode or 0)
    if exit_code != 0:
        return {
            "status": "denied",
            "output": out,
            "data": {"exit_code": exit_code},
            "error": err or f"{binary} exited with {exit_code}",
            "exit_code": exit_code,
            "sandbox": plan.state,
        }
    return {**_ok(output=out, data={"stderr": err, "exit_code": exit_code}), "sandbox": plan.state}


__all__ = [
    "DEFAULT_SUBCOMMAND_LIMIT",
    "DEFAULT_TOOL_TIMEOUT",
    "HELP_FLAGS",
    "ImportRefused",
    "MAX_FLAGS",
    "MAX_SUBCOMMANDS",
    "PROBE_TIMEOUT",
    "ProbeResult",
    "build_entry",
    "default_runner",
    "generic_executor",
    "parse_help",
    "plan_import",
    "probe_binary",
    "render_main_module",
    "safe_flags",
    "tool_manifest",
    "tools_root",
    "validate_argv",
    "write_tool",
]
