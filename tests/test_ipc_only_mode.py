"""TCP 收口：`core.http_enabled=false` 时的 daemon 契约（docs/SANDBOX-PLAN.md §9.3.5）。

背景：把 TCP 面关掉之前，socket 那一侧必须先补齐 —— 否则「关掉 TCP」等于「关掉
daemon」。这里钉住四件事：

1. `health` 自报 `pid` / `uptime` / `http` / `ipc`（pid 原先靠 psutil 扫 8321）；
2. `trm security tokens|learning|learn` 有 socket 腿（原先只有 HTTP）；
3. `core.http_enabled`（+ `TRIMUM_HTTP`）能把 HTTP 面关掉；
4. HTTP 关掉、socket 又起不来时启动必须失败（不能对 systemd 报 active 却什么都不提供）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.api_server import _health_payload, _register_ipc_routes, create_app
from trimum_core.config import Config
from trimum_core.ipc_handler import IpcHandler, IpcUnavailableError
from trimum_core.models import ToolType


def build_config(tmp_path: Path) -> Config:
    """把落盘位置全指到 tmp（ensure_dirs 会建这些目录）。"""
    config = Config()
    config.set("logging.file", str(tmp_path / "logs" / "trimum.log"))
    config.set("context.db_path", str(tmp_path / "context.db"))
    config.set("core.socket_path", str(tmp_path / "trimum.sock"))
    config.set("policy.path", str(tmp_path / "policy.yaml"))
    return config


class TestHttpToggle:
    def test_default_is_enabled(self, monkeypatch):
        monkeypatch.delenv("TRIMUM_HTTP", raising=False)
        assert Config().http_enabled is True
        assert Config().get("core.http_enabled") is True

    def test_config_switch_turns_http_off(self):
        config = Config()
        config.set("core.http_enabled", False)
        assert config.http_enabled is False

    def test_env_overrides_config(self, monkeypatch):
        """`TRIMUM_HTTP=0` 要能压过 config：单元里加一行就能收口、删一行就能退。"""
        monkeypatch.setenv("TRIMUM_HTTP", "0")
        assert Config().http_enabled is False

        monkeypatch.setenv("TRIMUM_HTTP", "1")
        config = Config()
        config.set("core.http_enabled", False)
        assert config.http_enabled is True

    def test_garbage_env_value_keeps_http_on(self, monkeypatch):
        """写错一个字符串不许把 daemon 的唯一入口憋没。"""
        monkeypatch.setenv("TRIMUM_HTTP", "maybe")
        assert Config().http_enabled is True


class TestHealthContract:
    """`trm status` 的 pid / http / ipc 全靠 health 自报。"""

    def test_http_and_rpc_health_agree(self, tmp_path):
        from fastapi.testclient import TestClient

        app = create_app(build_config(tmp_path))
        state = app.state.trimum

        http_body = TestClient(app).get("/health").json()

        ipc = IpcHandler(socket_path=str(tmp_path / "trimum.sock"))
        _register_ipc_routes(ipc, state)
        rpc_body = asyncio.run(ipc.router.get("health")({}))

        # uptime 会在两次调用之间走一点点，单独比；其余字段必须逐字一致。
        assert http_body.keys() == rpc_body.keys()
        assert http_body["uptime"] >= 0 and rpc_body["uptime"] >= 0
        assert {k: v for k, v in http_body.items() if k != "uptime"} == {
            k: v for k, v in rpc_body.items() if k != "uptime"
        }

    def test_reports_pid_uptime_and_flags(self, tmp_path):
        app = create_app(build_config(tmp_path))
        payload = _health_payload(app.state.trimum.config, app.state.trimum)

        assert payload["pid"] == os.getpid()
        assert payload["uptime"] >= 0
        assert payload["http"] is True
        assert payload["socket"] == str(tmp_path / "trimum.sock")

    def test_ipc_flag_is_false_until_socket_listens(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        state.ipc = IpcHandler(socket_path=str(tmp_path / "never.sock"))

        assert _health_payload(state.config, state)["ipc"] is False


class TestSecurityRpcMethods:
    """`trm security tokens|learning|learn` 的 socket 腿。"""

    def build(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        ipc = IpcHandler(socket_path=str(tmp_path / "trimum.sock"))
        _register_ipc_routes(ipc, state)
        assert ipc.router.get("security.tokens") is not None
        assert ipc.router.get("security.learning") is not None
        assert ipc.router.get("security.learn") is not None
        return ipc, state

    def test_tokens_lists_live_ones_and_masks_the_secret(self, tmp_path):
        ipc, state = self.build(tmp_path)
        token = state.tool_gateway.issue_jit_token(
            agent_id="a1", tool=ToolType.SHELL, command="ls", ttl=300
        )

        payload = asyncio.run(ipc.router.get("security.tokens")({"agent_id": "a1"}))

        assert [item["agent_id"] for item in payload["tokens"]] == ["a1"]
        assert payload["tokens"][0]["token"] == token.token[:8] + "..."
        assert payload["tokens"][0]["command"] == "ls"

    def test_tokens_filter_by_agent(self, tmp_path):
        ipc, state = self.build(tmp_path)
        state.tool_gateway.issue_jit_token(
            agent_id="a1", tool=ToolType.SHELL, command="ls", ttl=300
        )

        payload = asyncio.run(ipc.router.get("security.tokens")({"agent_id": "a2"}))

        assert payload["tokens"] == []

    def test_learn_runs_analysis(self, tmp_path):
        ipc, _ = self.build(tmp_path)

        payload = asyncio.run(ipc.router.get("security.learn")({"inject": False}))

        assert payload["injected"] == 0
        assert "summary" in payload
        assert payload["mode"]

    def test_learning_reports_summary_and_profiles(self, tmp_path):
        ipc, _ = self.build(tmp_path)

        payload = asyncio.run(ipc.router.get("security.learning")({}))

        assert set(payload) == {"summary", "profiles"}


def _break_ipc(monkeypatch) -> None:
    """让 IpcHandler.start() 必定失败（不依赖 AF_UNIX，Windows 上也能跑）。"""
    from trimum_core import ipc_handler as ipc_module

    async def failing_start(self) -> None:
        self.socket_start_error = "模拟 bind 失败"

    monkeypatch.setattr(ipc_module.IpcHandler, "start", failing_start)


async def run_handlers(app) -> None:
    handlers = list(getattr(app.router, "on_startup", []))
    assert handlers, "startup handler 未注册"
    for handler in handlers:
        await handler()


async def teardown(app, state) -> None:
    if state.learning_task is not None:
        state.learning_task.cancel()
    await state.agent_manager.stop_health_check()
    if state.ipc is not None:
        await state.ipc.stop()
    if state.context is not None:
        await state.context.close()


class TestIpcFailureWithoutHttp:
    """HTTP 关掉 + socket 起不来 = 没有任何入口，必须当场起不来。"""

    @pytest.mark.asyncio
    async def test_http_on_keeps_running_when_socket_fails(self, tmp_path, monkeypatch):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        _break_ipc(monkeypatch)
        try:
            await run_handlers(app)

            assert state.ipc.socket_start_error == "模拟 bind 失败"
        finally:
            await teardown(app, state)

    @pytest.mark.asyncio
    async def test_http_off_aborts_when_socket_fails(self, tmp_path, monkeypatch):
        config = build_config(tmp_path)
        config.set("core.http_enabled", False)
        app = create_app(config)
        state = app.state.trimum
        _break_ipc(monkeypatch)
        try:
            with pytest.raises(IpcUnavailableError):
                await run_handlers(app)
        finally:
            await teardown(app, state)


class TestFatalAbortIsImmediate:
    """`abort_startup(hard=True)` 必须**立刻**终止进程。

    回归（真机实测，见 docs/SANDBOX-PLAN.md §9.3.8）：致命判定发生在启动**中途**时，
    `ContextManager` 的 aiosqlite 连接线程已经活着，而它是非 daemon 线程 ——
    `sys.exit(3)` 之后解释器会卡在 `threading._shutdown()` 等它，
    `timeout 90` 只能 SIGKILL 收场，退出码 124 而不是 3。
    """

    def test_hard_abort_does_not_wait_for_non_daemon_threads(self):
        import subprocess

        src = str(Path(__file__).resolve().parents[1] / "src")
        code = (
            "import sys, threading, time\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from trimum_core.main import abort_startup\n"
            "threading.Thread(target=time.sleep, args=(300,)).start()\n"
            "abort_startup('boom', 'hint', hard=True)\n"
        )

        proc = subprocess.run(
            [sys.executable, "-c", code, src],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert proc.returncode == 3
        assert "启动中止" in proc.stderr

    def test_soft_abort_still_raises_system_exit(self):
        from trimum_core.main import abort_startup

        with pytest.raises(SystemExit) as excinfo:
            abort_startup("boom", "hint")

        assert excinfo.value.code == 3


class TestIpcOnlyRunner:
    """`main._serve_without_http` 走的必须是与 uvicorn 同一条 lifespan。"""

    @pytest.mark.asyncio
    async def test_boots_and_stops_the_daemon(self, tmp_path, monkeypatch):
        from trimum_core import ipc_handler as ipc_module

        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        started: list[str] = []

        async def fake_start(self) -> None:
            started.append("ipc")
            self.socket_start_error = None

        monkeypatch.setattr(ipc_module.IpcHandler, "start", fake_start)

        import trimum_core.main as main_module

        task = asyncio.create_task(
            main_module._serve_without_http(app, state.config)
        )
        try:
            for _ in range(200):
                if started:
                    break
                await asyncio.sleep(0.01)
            assert started == ["ipc"], "lifespan 没被拉起来：on_startup handler 没跑"
            assert state.context is not None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        # 退出时 shutdown handler 跑过了：context 收干净、IPC 也停了
        assert state.ipc.listening is False