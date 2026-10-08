"""API Server 启动路径测试（P1 学习反馈环接线 + 启动期回归）。

背景：`_learning_loop` 一度被定义在 `startup()` 内部、却在定义之前被
`create_task` 引用，导致 daemon 启动即 `UnboundLocalError` 退出
（`Application startup failed. Exiting.`）。这里直接跑一遍 startup handler，
保证启动路径本身可用。
"""

import asyncio
import os
import time
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.api_server import create_app
from trimum_core.config import Config


def build_config(tmp_path: Path) -> Config:
    """把落盘位置全部指到 tmp，避免碰用户目录（ensure_dirs 会建这些目录）。"""
    config = Config()
    config.set("logging.file", str(tmp_path / "logs" / "trimum.log"))
    config.set("context.db_path", str(tmp_path / "context.db"))
    config.set("core.socket_path", str(tmp_path / "trimum.sock"))
    config.set("policy.path", str(tmp_path / "policy.yaml"))
    return config


async def run_startup(app) -> None:
    handlers = list(getattr(app.router, "on_startup", []))
    assert handlers, "startup handler 未注册"
    for handler in handlers:
        await handler()


async def run_shutdown(app) -> None:
    handlers = list(getattr(app.router, "on_shutdown", []))
    assert handlers, "shutdown handler 未注册"
    for handler in handlers:
        await handler()


async def teardown(app, state) -> None:
    if state.learning_task is not None:
        state.learning_task.cancel()
    if getattr(state, "bpf_alert_task", None) is not None:
        state.bpf_alert_task.cancel()
    await state.agent_manager.stop_health_check()
    if state.ipc is not None:
        await state.ipc.stop()
    if state.context is not None:
        await state.context.close()


class TestStartup:
    @pytest.mark.asyncio
    async def test_startup_completes_and_schedules_learning_loop(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)  # 不能再抛 UnboundLocalError

            assert state.learning_task is not None
            assert not state.learning_task.done()
            assert state.learning_task.get_name().startswith("Task-")
        finally:
            await teardown(app, state)

    @pytest.mark.asyncio
    async def test_learning_loop_is_module_level(self):
        """协程必须是模块级函数：定义在 startup() 内部会再犯同样的错。"""
        from trimum_core import api_server

        loop_fn = getattr(api_server, "_learning_loop", None)
        assert loop_fn is not None
        assert asyncio.iscoroutinefunction(loop_fn)
        assert loop_fn.__qualname__.count(".") == 0

    def test_learning_routes_registered(self, tmp_path):
        app = create_app(build_config(tmp_path))
        paths = {route.path for route in app.routes}
        assert "/api/security/learn" in paths
        assert "/api/security/learning" in paths


class TestWorkflowRuntimeWiring:
    """W1：daemon 起来之后 workflow 运行时与意图驱动监听器都必须已经在监听 Event Bus。"""

    @pytest.mark.asyncio
    async def test_startup_starts_the_workflow_runtime(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)

            runtime = state.workflow_runtime
            assert runtime is not None
            assert runtime.running is True

            ids = {item["id"] for item in runtime.list_workflows()}
            assert "threat-cron-audit" in ids
            # 剧本自动触发策略：取证类武装、处置类不武装（细节见
            # tests/test_playbook_auto_trigger.py）
            assert runtime.get("threat-cron-audit").enabled is True
            assert runtime.get("threat-revshell-cleanup").enabled is False

            await runtime.stop()
            assert runtime.running is False
        finally:
            await teardown(app, state)

    @pytest.mark.asyncio
    async def test_startup_wires_the_workflow_listener(self, tmp_path):
        """W1 遗留接线（2026-09-21）：daemon 启动必须把 WorkflowListener 真的装上。

        它以前从未被实例化 —— 于是 ``event.transform.completed`` 没有消费者、
        ``workflow.trigger`` 没有生产者，整条意图驱动链是摆设。
        """
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)

            assert state.workflow_listener is not None
            assert "event.transform.completed" in set(state.event_bus._subscribers)
        finally:
            if state.workflow_listener is not None:
                await state.workflow_listener.stop()
            await teardown(app, state)

    def test_workflow_routes_registered(self, tmp_path):
        app = create_app(build_config(tmp_path))
        paths = {route.path for route in app.routes}
        assert "/api/workflows" in paths
        assert "/api/workflows/runs" in paths

    def test_events_publish_route_registered(self, tmp_path):
        """G-1：`events.publish` RPC 路由必须挂上，`trm events --publish` 才有人接。"""
        from trimum_core.api_server import _register_ipc_routes
        from trimum_core.ipc_handler import IpcHandler

        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        ipc = IpcHandler(socket_path=str(tmp_path / "trimum.sock"))
        _register_ipc_routes(ipc, state)
        handler = ipc.router.get("events.publish")
        assert handler is not None


class TestSystemMonitorWiring:
    """M1：daemon 启动必须把 SystemMonitor 定时采集任务真正跑起来，shutdown 必须把它收掉。"""

    @pytest.mark.asyncio
    async def test_startup_starts_the_system_monitor(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)

            assert state.system_monitor is not None
            assert isinstance(state.system_monitor_task, asyncio.Task)
            assert not state.system_monitor_task.done()
        finally:
            await teardown(app, state)

    @pytest.mark.asyncio
    async def test_shutdown_stops_the_system_monitor(self, tmp_path):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)
            assert state.system_monitor_task is not None

            await run_shutdown(app)
            assert state.system_monitor_task.done()
        finally:
            if state.system_monitor_task is not None and not state.system_monitor_task.done():
                state.system_monitor_task.cancel()
            await teardown(app, state)


class TestHealthVersion:
    """`/health` 的版本号只能有一处口径（`trimum_core.__version__`）。

    回归：IPC 路径写死 "0.2.1"、HTTP 路径写死 "0.2.0"，与包版本 0.5.0 三处
    各说各话。
    """

    def test_http_and_ipc_health_report_package_version(self, tmp_path):
        import trimum_core
        from fastapi.testclient import TestClient

        from trimum_core.api_server import _register_ipc_routes
        from trimum_core.ipc_handler import IpcHandler

        app = create_app(build_config(tmp_path))
        state = app.state.trimum

        # HTTP 路径（不进入 lifespan，就不需要跑整个 startup）
        response = TestClient(app).get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["version"] == trimum_core.__version__
        assert app.version == trimum_core.__version__

        # IPC 路径：与 HTTP 逐字段一致（pid / uptime / http / ipc 一起比；
        # uptime 会在两次调用之间走一点点，单独比）
        ipc = IpcHandler(socket_path=str(tmp_path / "trimum.sock"))
        _register_ipc_routes(ipc, state)
        handler = ipc.router.get("health")
        assert handler is not None
        rpc_body = asyncio.run(handler({}))
        assert rpc_body.keys() == body.keys()
        assert {k: v for k, v in rpc_body.items() if k != "uptime"} == {
            k: v for k, v in body.items() if k != "uptime"
        }


class _Recorder:
    """假 AuditStore：只记 append 进来的事件（本文件不做真落盘）。"""

    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


class TestBpfAlertPollerWiring:
    """ebpf1f：daemon startup 必须把 BpfAlertPoller 常驻跑起来，shutdown 必须把它收掉。"""

    @pytest.mark.asyncio
    async def test_startup_wires_the_bpf_alert_poller(self, tmp_path):
        config = build_config(tmp_path)
        config.set("security.bpf_alerts", str(tmp_path / "bpf-alerts.jsonl"))
        config.set("security.bpf_alert_interval", 0.25)
        app = create_app(config)
        state = app.state.trimum
        try:
            await run_startup(app)
            assert state.bpf_alert_poller is not None
            assert isinstance(state.bpf_alert_task, asyncio.Task)
            assert not state.bpf_alert_task.done()
            assert str(state.bpf_alert_poller.path) == str(tmp_path / "bpf-alerts.jsonl")
            assert state.bpf_alert_poller.interval == 0.25
        finally:
            if state.bpf_alert_task is not None:
                state.bpf_alert_task.cancel()
            await teardown(app, state)

    @pytest.mark.asyncio
    async def test_replay_file_lands_in_audit_store_end_to_end(self, tmp_path):
        """/run 换成 tmp 文件：历史行不许发，新行必须经 publish_alert 落审计。"""
        alerts = tmp_path / "bpf-alerts.jsonl"
        alerts.write_bytes(b'{"kind":"bpf_attach","pid":1}\n')  # 历史
        config = build_config(tmp_path)
        config.set("security.bpf_alerts", str(alerts))
        config.set("security.bpf_alert_interval", 0.01)
        app = create_app(config)
        state = app.state.trimum
        fake = _Recorder()
        state.audit_store = fake  # 起任务前换掉
        try:
            await run_startup(app)
            with open(alerts, "ab") as fh:
                fh.write(b'{"kind":"exec","pid":42,"comm":"bash","detail":"d"}\n')
            deadline = time.monotonic() + 3.0
            while len(fake.events) < 1 and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert len(fake.events) == 1, fake.events  # 恰好 1 条：历史没重放
            event = fake.events[0]
            assert event.event_type == "security.ebpf_alert"
            assert event.details == {"kind": "exec", "pid": 42, "comm": "bash", "detail": "d"}
        finally:
            if state.bpf_alert_task is not None:
                state.bpf_alert_task.cancel()
            await teardown(app, state)

    @pytest.mark.asyncio
    async def test_shutdown_cancels_the_bpf_alert_task(self, tmp_path):
        config = build_config(tmp_path)
        config.set("security.bpf_alerts", str(tmp_path / "bpf-alerts.jsonl"))
        config.set("security.bpf_alert_interval", 0.25)
        app = create_app(config)
        state = app.state.trimum
        try:
            await run_startup(app)
            assert state.bpf_alert_task is not None
            await run_shutdown(app)
            with pytest.raises(asyncio.CancelledError):
                await state.bpf_alert_task
            assert state.bpf_alert_task.cancelled()
        finally:
            if state.bpf_alert_task is not None and not state.bpf_alert_task.done():
                state.bpf_alert_task.cancel()
            await teardown(app, state)
