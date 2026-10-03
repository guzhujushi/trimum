"""§6 解冻第二片：记忆的读路径（experience hint）。

experience_learner 把失败沉淀成 agent_memory 命名空间下的 experience.<fp> 条目；
本片验证 AgentLoop 在规划时把它们读回并注入发给 LLM 的 messages。

约定（照 tests/test_agent_loop.py）：
- AgentLoop(agent_name="t-agent")
- monkeypatch _chat_completion 记录 messages，返回合法 JSON 计划 + TokenUsage
- ContextManager 一律落 tmp_path，不碰 ~/.trimum；不真调 LLM、无网络
"""
import json

import pytest

from trimum_core.agent_loop import AgentLoop
from trimum_core.context_manager import ContextManager
from trimum_core.event_bus import EventBus
from trimum_core.experience_learner import ExperienceLearner
from trimum_core.memory_bridge import MemoryBridge
from trimum_core.resource_controller import TokenUsage

HINT_HEADER = "以往同类失败的教训"


def _plan_json() -> str:
    return json.dumps(
        {"title": "t", "steps": [{"name": "x", "command": "echo hi", "risk": "low"}]}
    )


def _make_fake_chat(captured: list):
    async def fake_chat(**kwargs):
        captured.append(kwargs["messages"])
        return (_plan_json(),
                TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2, calls=1))

    return fake_chat


def _step_json() -> str:
    return json.dumps({"name": "x", "command": "echo hi", "risk": "low"})


def _make_fake_chat_step(captured: list):
    """``_plan_single_step`` 要的是**步骤**形状的 JSON（不是 plan 形状）。"""

    async def fake_chat(**kwargs):
        captured.append(kwargs["messages"])
        return (_step_json(),
                TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2, calls=1))

    return fake_chat


def _flat_text(messages) -> str:
    return json.dumps(messages, ensure_ascii=False)


@pytest.mark.asyncio
async def test_t1_inject_experience_when_present(tmp_path, monkeypatch):
    cm = ContextManager(str(tmp_path / "ctx.db"))
    await cm.initialize("t-agent")
    await cm.set(
        "t-agent",
        "experience.aaa",
        {"pattern": "缺 fixture 会红", "advice": "先补 fixture", "count": 3},
        namespace="agent_memory",
    )
    loop = AgentLoop(agent_name="t-agent", context_manager=cm)
    captured = []
    monkeypatch.setattr(loop, "_chat_completion", _make_fake_chat(captured))

    await loop._plan("echo hi")

    text = _flat_text(captured[0])
    assert "缺 fixture 会红" in text
    assert "先补 fixture" in text
    assert "x3" in text
    await cm.close()


@pytest.mark.asyncio
async def test_t2_single_step_plan_injects_too(tmp_path, monkeypatch):
    cm = ContextManager(str(tmp_path / "ctx.db"))
    await cm.initialize("t-agent")
    await cm.set(
        "t-agent",
        "experience.aaa",
        {"pattern": "缺 fixture 会红", "advice": "先补 fixture", "count": 3},
        namespace="agent_memory",
    )
    loop = AgentLoop(agent_name="t-agent", context_manager=cm)
    captured = []
    monkeypatch.setattr(loop, "_chat_completion", _make_fake_chat_step(captured))

    step = await loop._plan_single_step("echo hi", None)

    assert step is not None and step.get("command") == "echo hi"
    text = _flat_text(captured[0])
    assert "缺 fixture 会红" in text
    assert "先补 fixture" in text
    assert "x3" in text
    await cm.close()


@pytest.mark.asyncio
async def test_t3_plain_key_is_ignored(tmp_path, monkeypatch):
    cm = ContextManager(str(tmp_path / "ctx.db"))
    await cm.initialize("t-agent")
    await cm.set("t-agent", "note", {"pattern": "不该出现"}, namespace="agent_memory")
    loop = AgentLoop(agent_name="t-agent", context_manager=cm)
    captured = []
    monkeypatch.setattr(loop, "_chat_completion", _make_fake_chat(captured))

    await loop._plan("echo hi")

    text = _flat_text(captured[0])
    assert "不该出现" not in text
    assert HINT_HEADER not in text
    await cm.close()


class _ExplodingCM:
    """initialize 正常，list_namespace 抛 RuntimeError —— 验证 best-effort 不拦规划。"""

    async def initialize(self, agent_id=None):
        return None

    async def list_namespace(self, agent_id, namespace):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_t4_best_effort_never_blocks_planning(tmp_path, monkeypatch):
    loop = AgentLoop(agent_name="t-agent", context_manager=_ExplodingCM())
    captured = []
    monkeypatch.setattr(loop, "_chat_completion", _make_fake_chat(captured))

    plan = await loop._plan("echo hi")

    assert plan is not None
    assert plan["title"] == "t"
    text = _flat_text(captured[0])
    assert HINT_HEADER not in text


@pytest.mark.asyncio
async def test_t5_sort_and_limit(tmp_path, monkeypatch):
    cm = ContextManager(str(tmp_path / "ctx.db"))
    await cm.initialize("t-agent")
    for n in range(1, 8):  # count 1..7
        await cm.set(
            "t-agent",
            f"experience.e{n}",
            {"pattern": f"pattern_{n}", "count": n},
            namespace="agent_memory",
        )
    loop = AgentLoop(agent_name="t-agent", context_manager=cm)
    captured = []
    monkeypatch.setattr(loop, "_chat_completion", _make_fake_chat(captured))

    await loop._plan("echo hi")

    text = _flat_text(captured[0])
    for n in (3, 4, 5, 6, 7):
        assert f"pattern_{n}" in text, f"top-5 should contain pattern_{n}"
    for n in (1, 2):
        assert f"pattern_{n}" not in text, f"pattern_{n} should be trimmed out"
    await cm.close()


@pytest.mark.asyncio
async def test_t6_read_write_closed_loop(tmp_path, monkeypatch):
    pattern = "缺 fixture 会红（闭环）"
    fake_llm_payload = json.dumps(
        {"pattern": pattern, "advice": "先补 fixture", "severity": "error"}
    )

    async def fake_call_llm(self, system_prompt, user_prompt, timeout=15.0):
        return fake_llm_payload

    monkeypatch.setattr(ExperienceLearner, "_call_llm", fake_call_llm)

    bus = EventBus()
    cm = ContextManager(str(tmp_path / "ctx.db"))
    await cm.initialize("t-agent")
    bridge = MemoryBridge(bus, cm)
    learner = ExperienceLearner(bus)
    try:
        await bridge.start()
        await learner.start()

        await bus.emit_event(
            "task.failed",
            "t-agent",
            {"agent_id": "t-agent", "error": "boom"},
        )
        await bus.wait_for_handlers()

        loop = AgentLoop(agent_name="t-agent", context_manager=cm)
        captured = []
        monkeypatch.setattr(loop, "_chat_completion", _make_fake_chat(captured))

        await loop._plan("echo hi")

        text = _flat_text(captured[0])
        assert pattern in text
    finally:
        await learner.stop()
        await bridge.stop()
        await cm.close()


@pytest.mark.asyncio
async def test_t7_agent_isolation(tmp_path, monkeypatch):
    cm = ContextManager(str(tmp_path / "ctx.db"))
    await cm.initialize("t-agent")
    await cm.initialize("other-agent")
    await cm.set(
        "t-agent",
        "experience.mine",
        {"pattern": "只有我的经验", "count": 1},
        namespace="agent_memory",
    )
    await cm.set(
        "other-agent",
        "experience.theirs",
        {"pattern": "别人的经验", "count": 1},
        namespace="agent_memory",
    )
    loop = AgentLoop(agent_name="t-agent", context_manager=cm)
    captured = []
    monkeypatch.setattr(loop, "_chat_completion", _make_fake_chat(captured))

    await loop._plan("echo hi")

    text = _flat_text(captured[0])
    assert "只有我的经验" in text
    assert "别人的经验" not in text
    await cm.close()


@pytest.mark.asyncio
async def test_t8a_bad_entry_never_blocks_planning(tmp_path, monkeypatch):
    cm = ContextManager(str(tmp_path / "ctx.db"))
    await cm.initialize("t-agent")
    await cm.set(
        "t-agent",
        "experience.bad",
        {"pattern": "坏数据", "count": "many"},
        namespace="agent_memory",
    )
    loop = AgentLoop(agent_name="t-agent", context_manager=cm)
    captured = []
    monkeypatch.setattr(loop, "_chat_completion", _make_fake_chat_step(captured))

    plan = await loop._plan_single_step("echo hi", None)

    assert plan is not None
    assert isinstance(plan, dict) and "command" in plan
    text = _flat_text(captured[0])
    assert HINT_HEADER not in text
    assert "坏数据" not in text
    await cm.close()


@pytest.mark.asyncio
async def test_t8b_bad_entry_only_drops_itself(tmp_path, monkeypatch):
    cm = ContextManager(str(tmp_path / "ctx.db"))
    await cm.initialize("t-agent")
    await cm.set(
        "t-agent",
        "experience.bad",
        {"pattern": "坏数据", "count": "many"},
        namespace="agent_memory",
    )
    await cm.set(
        "t-agent",
        "experience.good",
        {"pattern": "好数据", "advice": "照这个做", "count": 2},
        namespace="agent_memory",
    )
    loop = AgentLoop(agent_name="t-agent", context_manager=cm)
    captured = []
    monkeypatch.setattr(loop, "_chat_completion", _make_fake_chat_step(captured))

    plan = await loop._plan_single_step("echo hi", None)

    assert plan is not None
    text = _flat_text(captured[0])
    assert HINT_HEADER in text
    assert "好数据" in text
    assert "照这个做" in text
    assert "坏数据" not in text
    await cm.close()
