"""API Server 启动路径测试（P1 学习反馈环接线 + 启动期回归）。

背景：`_learning_loop` 一度被定义在 `startup()` 内部、却在定义之前被
`create_task` 引用，导致 daemon 启动即 `UnboundLocalError` 退出
（`Application startup failed. Exiting.`）。这里直接跑一遍 startup handler，
保证启动路径本身可用。
"""

import asyncio
import os
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


async def teardown(app, state) -> None:
    if state.learning_task is not None:
        state.learning_task.cancel()
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
