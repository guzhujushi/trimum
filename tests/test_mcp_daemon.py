"""M4 daemon wiring — the shared pool must be *the* path the daemon takes.

`trm mcp call` is a one-shot process: it starts a server, calls it and exits.
The point of M4 is that the daemon does not work that way — one pool, reused
across calls, reaped when idle, bound to a cgroup when it can be, and reachable
from `trm mcp status` / `trm mcp restart` over IPC.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.cli import main  # noqa: E402
from trimum_core.api_server import build_mcp_pool, create_app, wire_mcp_dispatchers  # noqa: E402
from trimum_core.config import Config  # noqa: E402
from trimum_core.mcp_client import MCPError  # noqa: E402
from trimum_core.mcp_registry import MCP_DIR_ENV, MCPRegistry, MCPServerPool  # noqa: E402
from trimum_core.models import ExecuteRequest, ToolType  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"


def build_config(tmp_path: Path) -> Config:
    """Point every on-disk location at tmp (ensure_dirs creates them)."""
    config = Config()
    config.set("logging.file", str(tmp_path / "logs" / "trimum.log"))
    config.set("context.db_path", str(tmp_path / "context.db"))
    config.set("core.socket_path", str(tmp_path / "trimum.sock"))
    config.set("policy.path", str(tmp_path / "policy.yaml"))
    return config


def write_server(directory: Path, name: str = "echo", **overrides) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "command": sys.executable,
        "args": [str(FIXTURE)],
        "enabled": True,
        "timeout": 10.0,
    }
    data.update(overrides)
    (directory / f"{name}.json5").write_text(json.dumps(data, indent=2), encoding="utf-8")


async def run_startup(app) -> None:
    for handler in list(getattr(app.router, "on_startup", [])):
        await handler()


async def run_shutdown(app) -> None:
    for handler in list(getattr(app.router, "on_shutdown", [])):
        await handler()


async def teardown(state) -> None:
    if state.learning_task is not None:
        state.learning_task.cancel()
    await state.agent_manager.stop_health_check()
    if state.mcp_pool is not None:
        await state.mcp_pool.close_all()
    if state.ipc is not None:
        await state.ipc.stop()
    if state.driver is not None:
        await state.driver.stop()
    if state.context is not None:
        await state.context.close()


class RecordingPool:
    """Pool stand-in that only records the calls shutdown makes."""

    def __init__(self) -> None:
        self.closed = 0
        self.restarts: list[str] = []

    async def close_all(self) -> None:
        self.closed += 1

    async def restart(self, name: str) -> bool:
        self.restarts.append(name)
        return True


class BrokenPool(RecordingPool):
    async def restart(self, name: str) -> bool:
        raise MCPError(f"MCP server not found: {name}")


# ---------------------------------------------------------------------------
# startup wiring
# ---------------------------------------------------------------------------


class TestStartupWiring:
    @pytest.mark.asyncio
    async def test_shared_pool_is_handed_to_the_mcp_dispatchers(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MCP_DIR_ENV, str(tmp_path / "mcp"))
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)

            listed = state.tool_gateway.dispatchers.get(ToolType.MCP_TOOLS_LIST)
            called = state.tool_gateway.dispatchers.get(ToolType.MCP_TOOLS_CALL)
            assert listed is called, "list/call 必须是同一个分发器实例"
            assert listed.pool is state.mcp_pool
            assert state.mcp_pool is not None
            # 没有配置任何 server 时，状态是空表而不是异常
            assert await state.mcp_pool.status() == []
        finally:
            await teardown(state)

    @pytest.mark.asyncio
    async def test_reaper_is_running_and_dies_with_the_pool(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MCP_DIR_ENV, str(tmp_path / "mcp"))
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)
            assert state.mcp_reaper is not None
            assert not state.mcp_reaper.done()
            assert state.mcp_reaper.get_name() == "mcp-idle-reaper"

            await state.mcp_pool.close_all()
            assert state.mcp_reaper.done()
        finally:
            await teardown(state)

    @pytest.mark.asyncio
    async def test_wiring_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MCP_DIR_ENV, str(tmp_path / "mcp"))
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        pool = build_mcp_pool(state.config)

        first = wire_mcp_dispatchers(state, pool)
        second = wire_mcp_dispatchers(state, pool)

        assert len(first) == 1, "应当只有一个 MCP 分发器实例"
        assert second == first
        assert first[0].pool is pool
        await first[0].close()

    @pytest.mark.asyncio
    async def test_a_failing_pool_does_not_take_the_daemon_down(self, tmp_path, monkeypatch):
        from trimum_core import api_server

        monkeypatch.setenv(MCP_DIR_ENV, str(tmp_path / "mcp"))
        monkeypatch.setattr(
            api_server, "build_mcp_pool", lambda config: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)  # 不再抛异常

            assert state.mcp_pool is None
            # 兜底：分发器仍按需自建池子，MCP 不至于整个哑掉
            dispatcher = state.tool_gateway.dispatchers.get(ToolType.MCP_TOOLS_CALL)
            assert dispatcher.pool is not None
            assert await dispatcher.pool_status() == []
        finally:
            await teardown(state)

    @pytest.mark.asyncio
    async def test_shutdown_closes_the_pool(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MCP_DIR_ENV, str(tmp_path / "mcp"))
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        real_pool = None
        try:
            await run_startup(app)
            real_pool = state.mcp_pool
            recorder = RecordingPool()
            state.mcp_pool = recorder

            await run_shutdown(app)
            assert recorder.closed == 1
        finally:
            state.mcp_pool = real_pool
            if real_pool is not None:
                await real_pool.close_all()
            await state.agent_manager.stop_health_check()


# ---------------------------------------------------------------------------
# the pool really is reused (the whole point of a resident daemon)
# ---------------------------------------------------------------------------


class TestDaemonPoolInUse:
    @pytest.mark.asyncio
    async def test_two_calls_share_one_server_process(self, tmp_path, monkeypatch):
        directory = tmp_path / "mcp"
        write_server(directory)
        monkeypatch.setenv(MCP_DIR_ENV, str(directory))

        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)
            dispatcher = state.tool_gateway.dispatchers.get(ToolType.MCP_TOOLS_CALL)

            first = await dispatcher.execute(
                ExecuteRequest(tool=ToolType.MCP_TOOLS_CALL, args=["echo", "echo", '{"text": "one"}'])
            )
            pid = state.mcp_pool.clients["echo"].pid
            second = await dispatcher.execute(
                ExecuteRequest(tool=ToolType.MCP_TOOLS_CALL, args=["echo", "echo", '{"text": "two"}'])
            )

            assert first.status == "allowed" and second.status == "allowed"
            assert len(state.mcp_pool.clients) == 1
            assert state.mcp_pool.clients["echo"].pid == pid
        finally:
            await teardown(state)

    @pytest.mark.asyncio
    async def test_daemon_pool_reaps_a_server_that_went_idle(self, tmp_path, monkeypatch):
        directory = tmp_path / "mcp"
        write_server(directory, idle_ttl=0.2)
        monkeypatch.setenv(MCP_DIR_ENV, str(directory))

        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)
            dispatcher = state.tool_gateway.dispatchers.get(ToolType.MCP_TOOLS_CALL)
            await dispatcher.execute(
                ExecuteRequest(tool=ToolType.MCP_TOOLS_CALL, args=["echo", "echo", '{"text": "hi"}'])
            )
            assert await state.mcp_pool.reap() == []

            await asyncio.sleep(0.25)
            assert await state.mcp_pool.reap() == ["echo"]
            assert state.mcp_pool.clients == {}
        finally:
            await teardown(state)


# ---------------------------------------------------------------------------
# IPC: mcp.status / mcp.restart
# ---------------------------------------------------------------------------


def ipc_handlers(state):
    from trimum_core.api_server import _register_ipc_routes
    from trimum_core.ipc_handler import IpcHandler

    ipc = IpcHandler(socket_path=str(Path(state.config.socket_path)))
    _register_ipc_routes(ipc, state)
    return ipc.router


class TestMcpIpcRoutes:
    def test_status_before_startup_is_empty(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        handler = ipc_handlers(state).get("mcp.status")
        assert asyncio.run(handler({})) == []

    def test_status_reports_the_pool_rows(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum

        class Pool:
            async def status(self):
                return [{"server": "echo", "connected": True, "pid": 4242}]

        state.mcp_pool = Pool()
        handler = ipc_handlers(state).get("mcp.status")
        rows = asyncio.run(handler({}))
        assert rows == [{"server": "echo", "connected": True, "pid": 4242}]

    def test_restart_needs_a_name(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        handler = ipc_handlers(state).get("mcp.restart")
        assert asyncio.run(handler({})) == {"success": False, "error": "server is required"}

    def test_restart_calls_the_pool(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        state.mcp_pool = RecordingPool()
        handler = ipc_handlers(state).get("mcp.restart")

        assert asyncio.run(handler({"server": "echo"})) == {"success": True, "server": "echo"}
        assert state.mcp_pool.restarts == ["echo"]

    def test_restart_reports_a_bad_server_without_raising(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        state.mcp_pool = BrokenPool()
        handler = ipc_handlers(state).get("mcp.restart")

        result = asyncio.run(handler({"server": "nope"}))
        assert result["success"] is False
        assert "not found" in result["error"]

# ---------------------------------------------------------------------------
# CLI: trm mcp status / trm mcp restart
# ---------------------------------------------------------------------------


class TestMcpLifecycleCli:
    def test_status_prefers_the_daemon_pool(self, monkeypatch, capsys):
        from trimum_core.cli.commands import mcp as mcp_mod

        calls = []

        def fake_rpc(config, method, params=None, timeout=2.0):
            calls.append((method, params))
            return [{"server": "echo", "connected": True, "pid": 7, "transport": "stdio"}]

        monkeypatch.setattr(mcp_mod, "rpc_call", fake_rpc)

        assert main(["--json", "mcp", "status"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert calls == [("mcp.status", None)]
        assert payload["source"] == "daemon"
        assert payload["running"] == 1

    def test_status_without_a_daemon_reads_definitions_only(self, monkeypatch, capsys, tmp_path):
        from trimum_core.cli.commands import mcp as mcp_mod

        directory = tmp_path / "mcp"
        write_server(directory)
        monkeypatch.setattr(mcp_mod, "rpc_call", lambda *a, **k: None)

        assert main(["--json", "mcp", "status", "--dir", str(directory)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["source"] == "cli"
        assert payload["running"] == 0, "读状态不能顺手把 server 拉起来"
        assert [row["server"] for row in payload["servers"]] == ["echo"]
        assert payload["servers"][0]["connected"] is False

    def test_status_survives_an_empty_directory(self, monkeypatch, capsys, tmp_path):
        from trimum_core.cli.commands import mcp as mcp_mod

        monkeypatch.setattr(mcp_mod, "rpc_call", lambda *a, **k: None)
        assert main(["--json", "mcp", "status", "--dir", str(tmp_path / "none")]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["servers"] == []

    def test_restart_goes_through_the_daemon(self, monkeypatch, capsys):
        from trimum_core.cli.commands import mcp as mcp_mod

        calls = []

        def fake_rpc(config, method, params=None, timeout=2.0):
            calls.append((method, params))
            return {"success": True, "server": "echo"}

        monkeypatch.setattr(mcp_mod, "rpc_call", fake_rpc)

        assert main(["--json", "mcp", "restart", "echo"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert calls == [("mcp.restart", {"server": "echo"})]
        assert payload == {"success": True, "server": "echo", "source": "daemon"}

    def test_restart_without_a_daemon_verifies_then_closes(self, monkeypatch, capsys, tmp_path):
        from trimum_core.cli.commands import mcp as mcp_mod

        directory = tmp_path / "mcp"
        write_server(directory)
        monkeypatch.setattr(mcp_mod, "rpc_call", lambda *a, **k: None)

        assert main(["--json", "mcp", "restart", "echo", "--dir", str(directory)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {"success": True, "server": "echo", "source": "cli"}

    def test_restart_reports_an_unknown_server(self, monkeypatch, capsys, tmp_path):
        from trimum_core.cli.commands import mcp as mcp_mod

        monkeypatch.setattr(mcp_mod, "rpc_call", lambda *a, **k: None)

        assert main(["--json", "mcp", "restart", "ghost", "--dir", str(tmp_path / "none")]) == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err
    def test_the_daemon_call_honours_config(self, monkeypatch, capsys, tmp_path):
        """回归：`trm --config X mcp status` 必须问 X 描述的 daemon。

        这里一度写死 `Config()`，于是自定义 socket 的隔离 daemon 被静默跳过，
        CLI 退回本地一次性路径（真机验收时 7 条断言因此全崩）。
        """
        from trimum_core.cli.commands import mcp as mcp_mod

        seen = []

        def fake_rpc(config, method, params=None, timeout=2.0):
            seen.append((method, config.socket_path))
            return []

        monkeypatch.setattr(mcp_mod, "rpc_call", fake_rpc)
        custom = tmp_path / "custom.yaml"
        custom.write_text("core:\n  socket_path: /tmp/custom-trimum.sock\n", encoding="utf-8")

        assert main(["--json", "--config", str(custom), "mcp", "status"]) == 0
        assert seen == [("mcp.status", "/tmp/custom-trimum.sock")]
        assert json.loads(capsys.readouterr().out)["source"] == "daemon"

    def test_restart_command_also_honours_config(self, monkeypatch, capsys, tmp_path):
        from trimum_core.cli.commands import mcp as mcp_mod

        seen = []

        def fake_rpc(config, method, params=None, timeout=2.0):
            seen.append((method, params, config.socket_path))
            return {"success": True, "server": "echo"}

        monkeypatch.setattr(mcp_mod, "rpc_call", fake_rpc)
        custom = tmp_path / "custom.yaml"
        custom.write_text("core:\n  socket_path: /tmp/custom-trimum.sock\n", encoding="utf-8")

        assert main(["--json", "--config", str(custom), "mcp", "restart", "echo"]) == 0
        assert seen == [("mcp.restart", {"server": "echo"}, "/tmp/custom-trimum.sock")]

class TestDropInDefinitions:
    """`~/.trimum/mcp/` 的承诺：放一个文件就是全部安装步骤（M4 之后才成立的）。"""

    def test_a_new_file_shows_up_without_a_restart(self, tmp_path):
        directory = tmp_path / "mcp"
        registry = MCPRegistry(directory)
        assert registry.names() == []  # 第一次读：目录还不存在

        write_server(directory, "echo")
        assert registry.names() == ["echo"], "放文件即接入，不该等 daemon 重启"

    def test_editing_a_definition_is_picked_up(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory, "echo", idle_ttl=300)
        registry = MCPRegistry(directory)
        assert registry.get("echo").idle_ttl == 300.0

        time.sleep(0.01)  # 文件系统 mtime 分辨率
        write_server(directory, "echo", idle_ttl=7)
        assert registry.get("echo").idle_ttl == 7.0

    @pytest.mark.asyncio
    async def test_a_running_pool_sees_a_server_added_later(self, tmp_path):
        directory = tmp_path / "mcp"
        pool = MCPServerPool(MCPRegistry(directory))
        assert await pool.status() == []

        write_server(directory, "echo")
        rows = await pool.status()
        assert [row["server"] for row in rows] == ["echo"]
    @pytest.mark.asyncio
    async def test_a_deleted_definition_closes_the_running_client(self, tmp_path):
        """定义被删掉（或写坏）后，client 立刻收掉，不等 DEFAULT_IDLE_TTL。"""
        directory = tmp_path / "mcp"
        write_server(directory, "echo", idle_ttl=0)  # 常驻，正常永远不回收
        pool = MCPServerPool(MCPRegistry(directory))
        await pool.client("echo")
        assert await pool.reap() == [], "idle_ttl=0 的 server 正常不会被回收"

        (directory / "echo.json5").unlink()
        assert await pool.reap() == ["echo"]
        assert pool.clients == {}
