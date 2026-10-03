"""记忆链接线测试（§6 解冻第一件）。

MemoryBridge 与 ExperienceLearner 两个模块此前从未在生产代码里被实例化，
记忆链整条空转。这里验证 daemon startup 真的把它们装上、并且事件能落盘；
另起对照实验证明判别力（不起桥 ⇒ 失败事件的沉淀查不到）。
"""

import os
import sys
from pathlib import Path
from typing import Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.api_server import create_app
from trimum_core.config import Config
from trimum_core.context_manager import ContextManager
from trimum_core.event_bus import EventBus
from trimum_core.experience_learner import ExperienceEntry, ExperienceLearner
from trimum_core.memory_bridge import MemoryBridge

FAKE_LLM_RESPONSE = (
    '{"pattern": "pytest 红在缺 fixture", "advice": "补上 fixture", "severity": "warning"}'
)


def build_config(tmp_path: Path) -> Config:
    """照 tests/test_api_server_startup.py 的口径：落盘全指 tmp，不碰 ~/.trimum。"""
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
    for handler in getattr(app.router, "on_shutdown", []):
        await handler()


async def fake_call_llm(self, system_prompt, user_prompt, timeout=15.0) -> Optional[str]:
    """只替外部 LLM：固定返回一条经验 JSON（被测逻辑一律真跑）。"""
    return FAKE_LLM_RESPONSE


class TestMemoryChainOffline:
    """T1/T2/T4：直接用仓内真模块，不绑 TCP、不调真 LLM。"""

    @pytest.mark.asyncio
    async def test_bridge_persists_agent_memory(self, tmp_path):
        """T1：memory.agent.set 经桥真落盘到 ContextManager。"""
        bus = EventBus()
        cm = ContextManager(tmp_path / "ctx.db")
        await cm.initialize()
        await cm.initialize("a1")
        bridge = MemoryBridge(bus, cm)
        await bridge.start()
        try:
            # emit_event 会自动补 `event.` 前缀（NAMESPACE_EVENT），这里写人话名
            await bus.emit_event(
                "memory.agent.set", "test", {"agent_id": "a1", "key": "k1", "value": {"n": 1}}
            )
            # publish 是 fire-and-forget：等总线把在飞的订阅者回调排干再断言
            await bus.wait_for_handlers()
            assert await cm.get("a1", "k1", namespace="agent_memory") == {"n": 1}
        finally:
            await bridge.stop()
            await cm.close()

    @pytest.mark.asyncio
    async def test_failed_event_persists_experience(self, tmp_path, monkeypatch):
        """T2：task.failed → LLM（假）→ 经桥落 experience.<fingerprint>。

        只替外部 LLM（_call_llm）；fingerprint 用 ExperienceEntry 现算，不写死。
        """
        bus = EventBus()
        cm = ContextManager(tmp_path / "ctx.db")
        await cm.initialize()
        await cm.initialize("a1")
        bridge = MemoryBridge(bus, cm)
        learner = ExperienceLearner(bus)
        await bridge.start()
        await learner.start()
        try:
            monkeypatch.setattr(
                ExperienceLearner, "_call_llm", fake_call_llm, raising=True
            )
            await bus.emit_event("task.failed", "test", {"agent_id": "a1", "error": "boom"})
            # publish 是 fire-and-forget：等总线把在飞的订阅者回调排干再断言
            await bus.wait_for_handlers()

            # 取法一：用 ExperienceEntry 现算 fingerprint 直接查键。
            # 注意键是 `experience.<fingerprint>`（learner._store_experience 里加了前缀），
            # 不是裸 fingerprint —— 2026-10-01 实现窗口就栽在这半个前缀上。
            key = "experience." + ExperienceEntry(
                pattern="pytest 红在缺 fixture",
                advice="补上 fixture",
                severity="warning",
            ).fingerprint
            assert await cm.get("a1", key, namespace="agent_memory") is not None
        finally:
            await learner.stop()
            await bridge.stop()
            await cm.close()

    @pytest.mark.asyncio
    async def test_failed_event_without_bridge_stays_unpersisted(self, tmp_path, monkeypatch):
        """T4 对照组：只起 learner、不起桥 ⇒ 沉淀事件没人接，查不到 experience.* 条目。"""
        bus = EventBus()
        cm = ContextManager(tmp_path / "ctx.db")
        await cm.initialize()
        await cm.initialize("a1")
        learner = ExperienceLearner(bus)
        await learner.start()
        try:
            monkeypatch.setattr(
                ExperienceLearner, "_call_llm", fake_call_llm, raising=True
            )
            await bus.emit_event("task.failed", "test", {"agent_id": "a1", "error": "boom"})
            # publish 是 fire-and-forget：等总线把在飞的订阅者回调排干再断言
            await bus.wait_for_handlers()

            # 取法二：遍历 agent 记忆找 experience. 前缀的键（对照实验里
            # 不知道 learner 会不会走到写键那一步，遍历比现算指纹更稳）。
            entries = await cm.list_namespace("a1", "agent_memory")
            assert not any(k.startswith("experience.") for k in entries), entries
        finally:
            await learner.stop()
            await cm.close()


class TestDaemonWiring:
    """T3：跑真 startup handler，验证接线而不是「构造了没订阅」。"""

    @pytest.mark.asyncio
    async def test_startup_wires_memory_chain(self, tmp_path, monkeypatch):
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        try:
            await run_startup(app)

            # ① 两个模块都真的被实例化并挂到 state 上
            assert state.memory_bridge is not None
            assert state.experience_learner is not None

            # ② 判别力：在 daemon 自己的总线上发 memory.agent.set，
            #    桥必须把它落到 daemon 自己的 ContextManager 里。
            await state.context.initialize("a2")
            await state.event_bus.emit_event(
                "memory.agent.set", "test", {"agent_id": "a2", "key": "k2", "value": 42}
            )
            await state.event_bus.wait_for_handlers()
            assert await state.context.get("a2", "k2", namespace="agent_memory") == 42

            # ③ 这条才是 learner 的判别力：只断言「非 None」验的是「构造了」，
            #    而 ds 2026-10-01 验收用 M2（删掉 `await state.experience_learner.start()`）
            #    证明那样全绿 —— 恰好是本片要根除的「实例化了但没接线」。
            #    所以在 daemon 总线上发一条失败事件：假 LLM ⇒ 经验必须落到 daemon 的 ContextManager。
            monkeypatch.setattr(ExperienceLearner, "_call_llm", fake_call_llm, raising=True)
            await state.context.initialize("a3")
            await state.event_bus.emit_event(
                "task.failed", "test", {"agent_id": "a3", "error": "boom"}
            )
            await state.event_bus.wait_for_handlers()
            exp_key = "experience." + ExperienceEntry(
                pattern="pytest 红在缺 fixture",
                advice="补上 fixture",
                severity="warning",
            ).fingerprint
            assert await state.context.get("a3", exp_key, namespace="agent_memory") is not None
        finally:
            await run_shutdown(app)

    @pytest.mark.asyncio
    async def test_shutdown_is_clean_and_unsubscribes(self, tmp_path):
        """关停不许抛，**并且**订阅必须真的摘干净（后者才有判别力）。

        ds 2026-10-01 实测：删掉 shutdown 里那两段 stop，旧版「不许抛」断言全绿（判别力 0）；
        而数订阅表能抓住（干净时键被 `EventBus.unsubscribe` 删掉，泄漏时残留）。
        """
        app = create_app(build_config(tmp_path))
        state = app.state.trimum
        bus = state.event_bus
        await run_startup(app)
        assert "event.task.failed" in bus._subscribers, "启动后 learner 应已订阅失败事件"
        assert "event.memory.agent.set" in bus._subscribers, "启动后桥应已订阅 memory.*"
        # 逐个 await on_shutdown handler，不许抛
        await run_shutdown(app)
        assert "event.task.failed" not in bus._subscribers, "关停后 learner 的订阅没摘干净"
        assert "event.memory.agent.set" not in bus._subscribers, "关停后桥的订阅没摘干净"
