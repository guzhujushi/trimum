"""Unit tests for trimum_core.tool_dispatchers --non-file dispatchers.Covers: GitDispatcher, HttpDispatcher, ProcessDispatcher,        SystemDispatcher, ShellDispatcher, EnvDispatcher, DispatcherRegistry.Uses pytest + asyncio with mocked external dependencies.
"""
from __future__ import annotations

import asyncio
import os
import platform
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from trimum_core.models import ExecuteRequest, ExecuteResponse, ToolType, RiskLevel, Action
from trimum_core.tool_dispatchers import (
    GitDispatcher,
    HttpDispatcher,
    ProcessDispatcher,
    SystemDispatcher,
    ShellDispatcher,
    EnvDispatcher,
    DispatcherRegistry,
)

# ===================================================================
# Helpers
# ===================================================================


def _make_req(
    tool: ToolType,
    args: list[str] | None = None,
    cwd: str | None = None,
    timeout: float = 30.0,
) -> ExecuteRequest:
    return ExecuteRequest(
        tool=tool,
        args=args or [],
        cwd=cwd,
        timeout_seconds=timeout,
    )


def _mock_subprocess_proc(stdout: str = "", stderr: str = "", rc: int = 0) -> AsyncMock:
    """Create a mock asyncio.subprocess.Process for create_subprocess_exec/shell."""
    m = AsyncMock(spec=asyncio.subprocess.Process)
    m.stdout = None
    m.stderr = None
    m.communicate = AsyncMock(
        return_value=(stdout.encode("utf-8"), stderr.encode("utf-8"))
    )
    m.returncode = rc
    m.kill = MagicMock()
    m.wait = AsyncMock(return_value=0)
    return m
# ===================================================================
# GitDispatcher
# ===================================================================


class TestGitDispatcher:
    """GitDispatcher uses asyncio.create_subprocess_exec for all operations."""

    # 鈹€鈹€ Normal paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_git_status_ok(self):
        d = GitDispatcher()
        mp = _mock_subprocess_proc(stdout="On branch main\nnothing to commit", rc=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT_STATUS, cwd="/repo"))
        assert resp.exit_code == 0
        assert resp.status == "allowed"
        assert "On branch main" in resp.output

    @pytest.mark.asyncio
    async def test_git_log_ok(self):
        d = GitDispatcher()
        mp = _mock_subprocess_proc(stdout="abc123 commit msg\n", rc=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT_LOG, cwd="/repo"))
        assert resp.exit_code == 0
        assert "abc123" in resp.output

    @pytest.mark.asyncio
    async def test_git_commit_ok(self):
        d = GitDispatcher()
        mp = _mock_subprocess_proc(stdout="[main abc123] my msg", rc=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT_COMMIT, args=["my msg"], cwd="/repo"))
        assert resp.exit_code == 0
        assert "my msg" in resp.output

    @pytest.mark.asyncio
    async def test_git_push_ok(self):
        d = GitDispatcher()
        mp = _mock_subprocess_proc(stdout="Everything up-to-date", rc=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT_PUSH, args=["origin", "main"], cwd="/repo"))
        assert resp.exit_code == 0
        assert "up-to-date" in resp.output

    @pytest.mark.asyncio
    async def test_git_pull_ok(self):
        d = GitDispatcher()
        mp = _mock_subprocess_proc(stdout="Already up to date.", rc=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT_PULL, cwd="/repo"))
        assert resp.exit_code == 0
        assert "up to date" in resp.output

    @pytest.mark.asyncio
    async def test_git_branch_ok(self):
        d = GitDispatcher()
        mp = _mock_subprocess_proc(stdout="* main\n  feature/x", rc=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT_BRANCH, cwd="/repo"))
        assert resp.exit_code == 0
        assert "* main" in resp.output

    @pytest.mark.asyncio
    async def test_git_diff_ok(self):
        d = GitDispatcher()
        mp = _mock_subprocess_proc(stdout="--- a/file\n+++ b/file", rc=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT_DIFF, cwd="/repo"))
        assert resp.exit_code == 0
        assert "+++" in resp.output

    @pytest.mark.asyncio
    async def test_git_generic_ok(self):
        d = GitDispatcher()
        mp = _mock_subprocess_proc(stdout="output", rc=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT, args=["rev-parse", "HEAD"], cwd="/repo"))
        assert resp.exit_code == 0
        assert "output" in resp.output

    # 鈹€鈹€ Exception paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_git_not_a_repo(self):
        d = GitDispatcher()
        mp = _mock_subprocess_proc(stderr="fatal: not a git repository", rc=128)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT_STATUS, cwd="/tmp"))
        assert resp.exit_code == 128
        assert resp.status == "denied"
        assert "not a git repository" in resp.error

    @pytest.mark.asyncio
    async def test_git_cwd_not_exists(self):
        d = GitDispatcher()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError("No such file or directory")),
        ):
            resp = await d.execute(_make_req(ToolType.GIT_STATUS, cwd="/nonexistent"))
        assert resp.exit_code == 127
        assert resp.status == "denied"
        assert "Git not found" in resp.error

    @pytest.mark.asyncio
    async def test_git_timeout(self):
        d = GitDispatcher()
        mp = AsyncMock(spec=asyncio.subprocess.Process)
        mp.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mp.kill = MagicMock()
        mp.wait = AsyncMock(return_value=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.GIT_STATUS, cwd="/repo", timeout=1))
        assert resp.exit_code == -1
        assert "timed out" in resp.error

    @pytest.mark.asyncio
    async def test_git_unknown_tool(self):
        d = GitDispatcher()
        resp = await d.execute(_make_req(ToolType.SHELL))
        assert resp.status == "denied"
        assert "Unsupported" in resp.error

# ===================================================================
# HttpDispatcher
# ===================================================================


class TestHttpDispatcher:
    """HttpDispatcher uses urllib.request.urlopen via run_in_executor."""

    def _patch_urlopen(self, status=200, body="OK", side_effect=None):
        """Patch urllib.request.urlopen and make run_in_executor run synchronously."""
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        mock_resp.status = status
        mock_resp.read.return_value = body.encode("utf-8")

        urlopen_mock = (
            MagicMock(side_effect=side_effect) if side_effect else MagicMock(return_value=mock_resp)
        )
        return patch.multiple(
            "trimum_core.tool_dispatchers.urllib.request",
            urlopen=urlopen_mock,
        )

    async def _exec_sync(self, d, req):
        """Wrap dispatcher.execute so run_in_executor calls the function directly."""
        orig_exec = d.execute

        async def patched_exec(request):
            loop = asyncio.get_event_loop()
            original_rne = loop.run_in_executor

            async def mock_rne(executor, func, *args):
                return func(*args) if args else func()

            loop.run_in_executor = mock_rne
            try:
                return await orig_exec(request)
            finally:
                loop.run_in_executor = original_rne

        return await patched_exec(req)

    # 鈹€鈹€ Normal paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_http_get_ok(self):
        d = HttpDispatcher()
        with self._patch_urlopen(200, '{"status":"ok"}'):
            resp = await self._exec_sync(
                d, _make_req(ToolType.HTTP_GET, args=["https://example.com"])
            )
        assert resp.status == "allowed"
        assert "[200]" in resp.output
        assert "ok" in resp.output

    @pytest.mark.asyncio
    async def test_http_post_ok(self):
        d = HttpDispatcher()
        with self._patch_urlopen(201, '{"created":true}'):
            resp = await self._exec_sync(
                d,
                _make_req(ToolType.HTTP_POST, args=["https://example.com", '{"key":"val"}']),
            )
        assert resp.status == "allowed"
        assert "[201]" in resp.output
        assert "created" in resp.output

    @pytest.mark.asyncio
    async def test_http_generic_get(self):
        d = HttpDispatcher()
        with self._patch_urlopen(200, "OK"):
            resp = await self._exec_sync(
                d, _make_req(ToolType.HTTP, args=["GET", "https://example.com"])
            )
        assert resp.status == "allowed"
        assert "[200]" in resp.output

    @pytest.mark.asyncio
    async def test_http_generic_post(self):
        d = HttpDispatcher()
        with self._patch_urlopen(201, "created"):
            resp = await self._exec_sync(
                d,
                _make_req(ToolType.HTTP, args=["POST", "https://example.com", "body"]),
            )
        assert resp.status == "allowed"
        assert "[201]" in resp.output

    # 鈹€鈹€ Exception paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_http_get_no_url(self):
        d = HttpDispatcher()
        resp = await d.execute(_make_req(ToolType.HTTP_GET))
        assert resp.status == "denied"
        assert "Usage" in resp.error

    @pytest.mark.asyncio
    async def test_http_timeout(self):
        d = HttpDispatcher()
        with self._patch_urlopen(side_effect=TimeoutError("urlopen error timed out")):
            resp = await self._exec_sync(
                d, _make_req(ToolType.HTTP_GET, args=["https://slow.example.com"])
            )
        assert resp.status == "denied"
        assert "timed out" in resp.error.lower() or "error" in resp.error

    @pytest.mark.asyncio
    async def test_http_400_error(self):
        d = HttpDispatcher()
        with self._patch_urlopen(side_effect=Exception("HTTP Error 400: Bad Request")):
            resp = await self._exec_sync(
                d, _make_req(ToolType.HTTP_GET, args=["https://example.com/400"])
            )
        assert resp.status == "denied"
        assert "400" in resp.error or "HTTP" in resp.error

    @pytest.mark.asyncio
    async def test_http_unsupported_tool(self):
        d = HttpDispatcher()
        resp = await d.execute(_make_req(ToolType.SHELL))
        assert resp.status == "denied"
        assert "Unsupported" in resp.error

# ===================================================================
# ProcessDispatcher
# ===================================================================


class TestProcessDispatcher:
    """ProcessDispatcher varies behavior by platform.system()."""

    # 鈹€鈹€ Normal paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_process_list_windows(self):
        d = ProcessDispatcher()
        mp = _mock_subprocess_proc(stdout='"chrome.exe","1234"', rc=0)
        with patch("platform.system", MagicMock(return_value="Windows")):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
                resp = await d.execute(_make_req(ToolType.PROCESS_LIST))
        assert resp.exit_code == 0
        assert "chrome.exe" in resp.output

    @pytest.mark.asyncio
    async def test_process_list_linux(self):
        d = ProcessDispatcher()
        mp = _mock_subprocess_proc(stdout="root 1 init", rc=0)
        with patch("platform.system", MagicMock(return_value="Linux")):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
                resp = await d.execute(_make_req(ToolType.PROCESS_LIST))
        assert resp.status == "allowed"
        assert "init" in resp.output

    @pytest.mark.asyncio
    async def test_process_kill_windows(self):
        d = ProcessDispatcher()
        mp = _mock_subprocess_proc(stdout="SUCCESS", rc=0)
        with patch("platform.system", MagicMock(return_value="Windows")):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
                resp = await d.execute(_make_req(ToolType.PROCESS_KILL, args=["1234"]))
        assert resp.exit_code == 0
        assert "Killed PID 1234" in resp.output

    @pytest.mark.asyncio
    async def test_process_kill_linux(self):
        d = ProcessDispatcher()
        mp = _mock_subprocess_proc(stdout="", rc=0)
        with patch("platform.system", MagicMock(return_value="Linux")):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
                resp = await d.execute(_make_req(ToolType.PROCESS_KILL, args=["1234"]))
        assert resp.exit_code == 0
        assert "Killed PID 1234" in resp.output

    @pytest.mark.asyncio
    async def test_process_generic_list(self):
        d = ProcessDispatcher()
        mp = _mock_subprocess_proc(stdout="procs", rc=0)
        with patch("platform.system", MagicMock(return_value="Windows")):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
                resp = await d.execute(_make_req(ToolType.PROCESS, args=["list"]))
        assert resp.exit_code == 0

    # 鈹€鈹€ Exception paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_process_kill_invalid_pid(self):
        d = ProcessDispatcher()
        mp = _mock_subprocess_proc(stderr='ERROR: The process "999999" not found.', rc=128)
        with patch("platform.system", MagicMock(return_value="Windows")):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
                resp = await d.execute(_make_req(ToolType.PROCESS_KILL, args=["999999"]))
        assert resp.exit_code == 128
        assert resp.status == "denied"

    @pytest.mark.asyncio
    async def test_process_kill_permission_denied(self):
        d = ProcessDispatcher()
        mp = _mock_subprocess_proc(stderr="Operation not permitted", rc=1)
        with patch("platform.system", MagicMock(return_value="Linux")):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
                resp = await d.execute(_make_req(ToolType.PROCESS_KILL, args=["1"]))
        assert resp.exit_code == 1
        assert resp.status == "denied"

    @pytest.mark.asyncio
    async def test_process_kill_no_pid(self):
        d = ProcessDispatcher()
        resp = await d.execute(_make_req(ToolType.PROCESS_KILL))
        assert resp.status == "denied"
        assert "Usage" in resp.error

    @pytest.mark.asyncio
    async def test_process_unsupported_tool(self):
        d = ProcessDispatcher()
        resp = await d.execute(_make_req(ToolType.SHELL))
        assert resp.status == "denied"
        assert "Unsupported" in resp.error

# ===================================================================
# SystemDispatcher
# ===================================================================


class TestSystemDispatcher:
    """SystemDispatcher uses pure stdlib (no mocks needed)."""

    # 鈹€鈹€ Normal paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_system_info(self):
        d = SystemDispatcher()
        resp = await d.execute(_make_req(ToolType.SYSTEM_INFO))
        assert resp.exit_code == 0
        assert "System:" in resp.output
        assert "Python:" in resp.output

    @pytest.mark.asyncio
    async def test_system_disk(self):
        d = SystemDispatcher()
        resp = await d.execute(_make_req(ToolType.SYSTEM_DISK))
        assert resp.exit_code == 0
        assert "Disk" in resp.output or "Total" in resp.output

    @pytest.mark.asyncio
    async def test_system_memory(self):
        d = SystemDispatcher()
        resp = await d.execute(_make_req(ToolType.SYSTEM_MEMORY))
        assert resp.exit_code == 0
        # Memory requires psutil; system returns a placeholder message
        assert resp.output is not None

    @pytest.mark.asyncio
    async def test_system_generic_no_args(self):
        d = SystemDispatcher()
        resp = await d.execute(_make_req(ToolType.SYSTEM))
        assert resp.exit_code == 0
        assert "System:" in resp.output

    @pytest.mark.asyncio
    async def test_system_generic_info(self):
        d = SystemDispatcher()
        resp = await d.execute(_make_req(ToolType.SYSTEM, args=["info"]))
        assert resp.exit_code == 0
        assert "System:" in resp.output

    @pytest.mark.asyncio
    async def test_system_generic_disk(self):
        d = SystemDispatcher()
        resp = await d.execute(_make_req(ToolType.SYSTEM, args=["disk"]))
        assert resp.exit_code == 0
        assert "Disk" in resp.output or "Total" in resp.output

    @pytest.mark.asyncio
    async def test_system_generic_memory(self):
        d = SystemDispatcher()
        resp = await d.execute(_make_req(ToolType.SYSTEM, args=["memory"]))
        assert resp.exit_code == 0

    # 鈹€鈹€ Exception paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_system_unknown_subcmd(self):
        d = SystemDispatcher()
        resp = await d.execute(_make_req(ToolType.SYSTEM, args=["unknown_cmd"]))
        assert resp.status == "denied"
        assert "Usage" in resp.error

    @pytest.mark.asyncio
    async def test_system_unsupported_tool(self):
        d = SystemDispatcher()
        resp = await d.execute(_make_req(ToolType.SHELL))
        assert resp.status == "denied"
        assert "Unsupported" in resp.error

# ===================================================================
# ShellDispatcher
# ===================================================================


class TestShellDispatcher:
    """ShellDispatcher uses asyncio.create_subprocess_shell."""

    # 鈹€鈹€ Normal paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_shell_echo(self):
        d = ShellDispatcher()
        mp = _mock_subprocess_proc(stdout="hello world\n", rc=0)
        with patch("asyncio.create_subprocess_shell", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.SHELL, args=["echo hello world"]))
        assert resp.exit_code == 0
        assert resp.status == "allowed"
        assert "hello world" in resp.output

    @pytest.mark.asyncio
    async def test_shell_ls(self):
        d = ShellDispatcher()
        mp = _mock_subprocess_proc(stdout="file1\nfile2\n", rc=0)
        with patch("asyncio.create_subprocess_shell", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.SHELL, args=["ls -la"]))
        assert resp.exit_code == 0
        assert "file1" in resp.output

    @pytest.mark.asyncio
    async def test_shell_with_cwd(self):
        d = ShellDispatcher()
        mp = _mock_subprocess_proc(stdout="ok\n", rc=0)
        with patch("asyncio.create_subprocess_shell", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.SHELL, args=["pwd"], cwd="/tmp"))
        assert resp.exit_code == 0

    @pytest.mark.asyncio
    async def test_shell_with_env(self):
        d = ShellDispatcher()
        mp = _mock_subprocess_proc(stdout="custom\n", rc=0)
        with patch("asyncio.create_subprocess_shell", AsyncMock(return_value=mp)):
            req = _make_req(ToolType.SHELL, args=["echo $MY_VAR"])
            req.env = {"MY_VAR": "custom"}
            resp = await d.execute(req)
        assert resp.exit_code == 0
        assert "custom" in resp.output

    # 鈹€鈹€ Exception paths 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @pytest.mark.asyncio
    async def test_shell_empty_command(self):
        d = ShellDispatcher()
        resp = await d.execute(_make_req(ToolType.SHELL, args=[""]))
        assert resp.status == "denied"
        assert "Empty" in resp.error

    @pytest.mark.asyncio
    async def test_shell_timeout(self):
        d = ShellDispatcher()
        mp = AsyncMock(spec=asyncio.subprocess.Process)
        mp.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mp.kill = MagicMock()
        mp.wait = AsyncMock(return_value=0)
        with patch("asyncio.create_subprocess_shell", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.SHELL, args=["sleep 100"], timeout=0.1))
        assert resp.exit_code == -1
        assert "timed out" in resp.error

    @pytest.mark.asyncio
    async def test_shell_command_not_found(self):
        d = ShellDispatcher()
        with patch(
            "asyncio.create_subprocess_shell",
            AsyncMock(side_effect=FileNotFoundError("command not found")),
        ):
            resp = await d.execute(_make_req(ToolType.SHELL, args=["nonexistent_cmd_xyz"]))
        assert resp.exit_code == 127
        assert resp.status == "denied"

    @pytest.mark.asyncio
    async def test_shell_nonzero_exit(self):
        d = ShellDispatcher()
        mp = _mock_subprocess_proc(stderr="command failed", rc=1)
        with patch("asyncio.create_subprocess_shell", AsyncMock(return_value=mp)):
            resp = await d.execute(_make_req(ToolType.SHELL, args=["false"]))
        assert resp.exit_code == 1
        assert resp.status == "error"


# ===================================================================
# EnvDispatcher
# ===================================================================


class TestEnvDispatcher:
    """EnvDispatcher uses os.environ."""

    @pytest.mark.asyncio
    async def test_env_get_existing(self):
        d = EnvDispatcher()
        with patch.dict("os.environ", {"MY_TEST_KEY": "test_value"}):
            resp = await d.execute(_make_req(ToolType.ENV_GET, args=["MY_TEST_KEY"]))
        assert resp.status == "allowed"
        assert "MY_TEST_KEY=test_value" in resp.output

    @pytest.mark.asyncio
    async def test_env_get_missing(self):
        d = EnvDispatcher()
        with patch.dict("os.environ", {}, clear=True):
            resp = await d.execute(_make_req(ToolType.ENV_GET, args=["NONEXISTENT_KEY"]))
        assert resp.status == "allowed"
        assert "NONEXISTENT_KEY=" in resp.output

    @pytest.mark.asyncio
    async def test_env_get_no_arg(self):
        d = EnvDispatcher()
        resp = await d.execute(_make_req(ToolType.ENV_GET))
        assert resp.status == "denied"
        assert "Usage" in resp.error

    @pytest.mark.asyncio
    async def test_env_list_ok(self):
        d = EnvDispatcher()
        with patch.dict("os.environ", {"A": "1", "B": "2"}):
            resp = await d.execute(_make_req(ToolType.ENV_LIST))
        assert resp.status == "allowed"
        assert "A=1" in resp.output
        assert "B=2" in resp.output

    @pytest.mark.asyncio
    async def test_env_list_sorted(self):
        d = EnvDispatcher()
        with patch.dict("os.environ", {"Z": "z", "A": "a"}):
            resp = await d.execute(_make_req(ToolType.ENV_LIST))
        assert resp.status == "allowed"
        lines = resp.output.split("\n")
        assert lines[0].startswith("A=")
        assert lines[-1].startswith("Z=")

    @pytest.mark.asyncio
    async def test_env_unsupported_tool(self):
        d = EnvDispatcher()
        resp = await d.execute(_make_req(ToolType.SHELL))
        assert resp.status == "denied"
        assert "Unsupported" in resp.error


# ===================================================================
# DispatcherRegistry
# ===================================================================


class TestDispatcherRegistry:
    """DispatcherRegistry maps ToolType to Dispatcher and dispatches."""

    @pytest.mark.asyncio
    async def test_initialise_defaults(self):
        """Registry initialises with all default dispatchers."""
        reg = DispatcherRegistry()
        assert reg.get(ToolType.SHELL) is not None
        assert reg.get(ToolType.FILE_READ) is not None
        assert reg.get(ToolType.GIT_STATUS) is not None
        assert reg.get(ToolType.HTTP_GET) is not None
        assert reg.get(ToolType.PROCESS_LIST) is not None
        assert reg.get(ToolType.SYSTEM_INFO) is not None
        assert reg.get(ToolType.ENV_GET) is not None

    @pytest.mark.asyncio
    async def test_dispatch_file_read(self):
        """Dispatching FILE_READ returns a response (even if file not found)."""
        reg = DispatcherRegistry()
        resp = await reg.dispatch(
            _make_req(ToolType.FILE_READ, args=["/nonexistent/nope.txt"])
        )
        assert resp is not None
        assert resp.status in ("allowed", "denied", "error")

    @pytest.mark.asyncio
    async def test_dispatch_git_status(self):
        """Dispatching GIT_STATUS goes to GitDispatcher."""
        reg = DispatcherRegistry()
        mp = _mock_subprocess_proc(stdout="On branch main", rc=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mp)):
            resp = await reg.dispatch(_make_req(ToolType.GIT_STATUS, cwd="/repo"))
        assert resp.exit_code == 0
        assert "On branch main" in resp.output

    @pytest.mark.asyncio
    async def test_dispatch_system_info(self):
        reg = DispatcherRegistry()
        resp = await reg.dispatch(_make_req(ToolType.SYSTEM_INFO))
        assert resp.status == "allowed"
        assert "System:" in resp.output

    @pytest.mark.asyncio
    async def test_dispatch_env_get(self):
        reg = DispatcherRegistry()
        with patch.dict("os.environ", {"PATH": "/usr/bin"}):
            resp = await reg.dispatch(_make_req(ToolType.ENV_GET, args=["PATH"]))
        assert resp.status == "allowed"
        assert "PATH=/usr/bin" in resp.output

    @pytest.mark.asyncio
    async def test_register_override(self):
        reg = DispatcherRegistry()
        original = reg.get(ToolType.SHELL)
        new_d = ShellDispatcher()
        reg.register(ToolType.SHELL, new_d)
        assert reg.get(ToolType.SHELL) is new_d
        assert reg.get(ToolType.SHELL) is not original

    @pytest.mark.asyncio
    async def test_empty_registry(self):
        reg = DispatcherRegistry()
        reg._dispatchers.clear()
        resp = await reg.dispatch(_make_req(ToolType.SHELL))
        assert resp.status == "denied"
        assert "No dispatcher" in resp.error

    @pytest.mark.asyncio
    async def test_reserved_dispatchers_stub(self):
        reg = DispatcherRegistry()

        resp_knowledge = await reg.dispatch(_make_req(ToolType.KNOWLEDGE_SEARCH))
        assert resp_knowledge.status == "denied"
        assert "Knowledge" in resp_knowledge.error

        resp_notif = await reg.dispatch(_make_req(ToolType.NOTIFICATION))
        assert resp_notif.status == "denied"
        assert "Notification" in resp_notif.error

        resp_mcp = await reg.dispatch(_make_req(ToolType.MCP_TOOLS_LIST))
        assert resp_mcp.status == "denied"
        assert "MCP" in resp_mcp.error

        resp_custom = await reg.dispatch(_make_req(ToolType.CUSTOM))
        assert resp_custom.status == "denied"
        assert "Custom" in resp_custom.error

# ===================================================================
