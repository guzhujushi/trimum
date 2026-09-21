"""Event Bus 硬化（2026-09-21）的回归测试。

三件事一起钉住：

1. **索引与旧口径等价** —— ``publish`` 改走首段分桶索引后，哪些订阅者收到事件必须与旧的
   「整表扫描 + 通配匹配」逐条相同（换实现不换语义）；
2. **失败不再静默** —— 订阅者抛异常要记日志 + 计数 + 广播 ``event.eventbus.dispatch_failed``，
   严格模式（``TRIMUM_BUS_STRICT=1``）下异常还能抛回给 ``wait_for_handlers()``；
3. **退订同步索引** —— 退订之后索引里不能再留人（否则事件会继续发给已经走了的人）。
"""

from __future__ import annotations

import asyncio

import pytest

from trimum_core.event_bus import (
    STRICT_ENV,
    EventBus,
    callback_name,
    strict_from_env,
)
from trimum_core.event_index import EventIndex, matches
from trimum_core.models import EventSeverity, TRMErrorCode, SystemEvent, TrimumError


def make_event(event_type: str, **payload) -> SystemEvent:
    """一条只带类型与载荷的事件（source / timestamp 不是本文件关心的）。"""
    return SystemEvent(event_type=event_type, source="test", payload=payload)


def named_listener(pattern: str):
    """带名字的假监听器 —— 索引返回的就是注册进去的那个对象，按身份比对。"""

    def listener(event):  # pragma: no cover - 只用于身份比对
        return None

    listener.pattern = pattern
    return listener


#: 通配规则表：模块级 matches / EventBus._matches / EventIndex._matches 三处必须同一答案。
MATCH_CASES = [
    ("*", "task.node.started", True),
    ("*", "task", True),
    ("task.*", "task.node.started", True),
    ("task.*", "event.task.started", False),
    ("*.completed", "task.node.completed", True),
    ("node.*.completed", "node.wf1.A.completed", True),
    ("node.*.completed", "node.wf1.completed", True),
    ("node.*.completed", "node.wf1.A.started", False),
    ("node.*.completed", "node.completed", False),
    ("task.node.started", "task.node.started", True),
    ("task.node.started", "task.node.started.extra", False),
]

PATTERNS = [
    "*",
    "task.*",
    "task.node.completed",
    "task.node.started",
    "*.completed",
    "node.*.completed",
    "event.mcp_call",
    "security.alert",
]

EVENT_TYPES = [
    "task.node.started",
    "task.node.completed",
    "task.workflow.started",
    "task.completed",
    "event.mcp_call",
    "event.security.alert",
    "security.alert",
    "node.wf1.A.completed",
]


class TestWildcardMatchParity:
    @pytest.mark.parametrize("pattern,actual,expected", MATCH_CASES)
    def test_module_level_matches(self, pattern, actual, expected):
        assert matches(pattern, actual) is expected

    @pytest.mark.parametrize("pattern,actual,expected", MATCH_CASES)
    def test_bus_and_index_agree_with_the_module(self, pattern, actual, expected):
        assert EventBus._matches(pattern, actual) is expected
        assert EventBus.matches(pattern, actual) is expected
        assert EventIndex._matches(pattern, actual) is expected

    @pytest.mark.parametrize("pattern", PATTERNS)
    @pytest.mark.parametrize("actual", EVENT_TYPES)
    def test_full_matrix_agrees(self, pattern, actual):
        assert (
            matches(pattern, actual)
            == EventBus._matches(pattern, actual)
            == EventIndex._matches(pattern, actual)
        )

    def test_index_returns_exactly_what_a_linear_scan_would(self):
        """索引的听众列表与旧的「整表扫描」逐条相同（含顺序）。"""
        index = EventIndex()
        registered = {}
        for pattern in PATTERNS:
            listener = named_listener(pattern)
            registered[pattern] = listener
            index.add_listener(pattern, listener)

        for actual in EVENT_TYPES:
            expected = [registered[p] for p in PATTERNS if matches(p, actual)]
            assert index.match(actual) == expected, actual

    def test_listeners_under_one_pattern_keep_insertion_order(self):
        index = EventIndex()
        first, second = named_listener("a"), named_listener("b")
        index.add_listener("task.*", first)
        index.add_listener("task.*", second)
        assert index.match("task.node.started") == [first, second]

    def test_removed_pattern_leaves_no_bucket_behind(self):
        index = EventIndex()
        listener = named_listener("task.*")
        index.add_listener("task.*", listener)
        index.remove_listener("task.*", listener)
        assert index.match("task.node.started") == []
        assert index._buckets == {}

    def test_pattern_with_more_segments_never_matches(self):
        assert matches("a.b.c", "a.b") is False
        assert matches("a.b", "a.b.c") is False


class TestPublishThroughTheIndex:
    @pytest.mark.asyncio
    async def test_only_matching_subscribers_are_called(self):
        bus = EventBus()
        seen = []
        bus.subscribe("task.node.completed", lambda event: seen.append("node"))
        bus.subscribe("task.node.started", lambda event: seen.append("started"))
        bus.subscribe("*", lambda event: seen.append("all"))

        await bus.publish(make_event("task.node.completed"))
        await bus.wait_for_handlers()

        assert seen == ["node", "all"]

    @pytest.mark.asyncio
    async def test_unsubscribe_drops_the_listener_from_the_index(self):
        bus = EventBus()
        seen = []

        def listener(event):
            seen.append(event.event_type)

        bus.subscribe("task.completed", listener)
        await bus.publish(make_event("task.completed"))
        bus.unsubscribe("task.completed", listener)
        await bus.publish(make_event("task.completed"))
        await bus.wait_for_handlers()

        assert seen == ["task.completed"]
        assert bus.stats()["patterns"] == 0
        assert bus._index.match("task.completed") == []

    @pytest.mark.asyncio
    async def test_emit_event_prepends_namespace_and_takes_severity(self):
        bus = EventBus()
        got = []
        bus.subscribe("*", got.append)

        await bus.emit_event(
            "tool.executing", "agent-sdk", {"tool": "rg"}, severity=EventSeverity.WARNING
        )
        await bus.wait_for_handlers()

        assert [event.event_type for event in got] == ["event.tool.executing"]
        assert got[0].severity is EventSeverity.WARNING
        assert got[0].source == "agent-sdk"

    @pytest.mark.asyncio
    async def test_history_keeps_what_was_published(self):
        bus = EventBus()
        await bus.publish(make_event("task.started"))
        assert [event.event_type for event in bus.get_history()] == ["task.started"]


class TestDispatchFailures:
    @pytest.mark.asyncio
    async def test_failure_is_counted_logged_and_does_not_stop_others(self, caplog):
        bus = EventBus()
        survived = []

        def boom(event):
            raise RuntimeError("订阅者写错了")

        bus.subscribe("task.node.completed", boom)
        bus.subscribe(
            "task.node.completed", lambda event: survived.append(event.event_type)
        )

        with caplog.at_level("WARNING", logger="trimum_core.event_bus"):
            await bus.publish(make_event("task.node.completed"))
            await bus.wait_for_handlers()

        assert survived == ["task.node.completed"]
        assert bus.dispatch_failures == 1
        failure = bus.last_failure
        assert failure["event_type"] == "task.node.completed"
        assert failure["callback"].endswith("boom")
        assert "RuntimeError" in failure["error"]
        assert bus.strict is False
        assert any(
            "event_bus.dispatch_failed" in record.getMessage() for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_failure_is_broadcast_on_the_bus(self):
        bus = EventBus()
        seen = []

        def boom(event):
            raise ValueError("boom")

        bus.subscribe("task.started", boom)
        bus.subscribe(EventBus.FAILURE_EVENT_TYPE, lambda event: seen.append(event.payload))

        await bus.publish(make_event("task.started"))
        for _ in range(3):  # 失败事件本身也是 publish 出来的，多等一轮
            await bus.wait_for_handlers()

        assert len(seen) == 1
        assert seen[0]["callback"].endswith("boom")
        assert "ValueError" in seen[0]["error"]

    @pytest.mark.asyncio
    async def test_a_failing_failure_listener_does_not_recurse(self):
        bus = EventBus()

        def boom(event):
            raise RuntimeError("谁都会写错")

        bus.subscribe("task.started", boom)
        bus.subscribe(EventBus.FAILURE_EVENT_TYPE, boom)

        await bus.publish(make_event("task.started"))
        for _ in range(5):
            await bus.wait_for_handlers()

        # 原始那次 + 听失败事件的那次，到此为止（不再发第二条失败事件）
        assert bus.dispatch_failures == 2
        assert bus._history[-1].event_type == EventBus.FAILURE_EVENT_TYPE

    @pytest.mark.asyncio
    async def test_strict_mode_raises_through_wait_for_handlers(self):
        bus = EventBus(strict=True)

        def boom(event):
            raise RuntimeError("订阅者写错了")

        bus.subscribe("task.started", boom)
        await bus.publish(make_event("task.started"))

        with pytest.raises(TrimumError) as excinfo:
            await bus.wait_for_handlers()

        assert excinfo.value.code is TRMErrorCode.EVENT_BUS_DISPATCH_FAILED
        assert "boom" in str(excinfo.value)
        assert bus.dispatch_failures == 1

    @pytest.mark.asyncio
    async def test_wait_for_handlers_actually_waits(self):
        bus = EventBus()
        done = []

        async def slow(event):
            await asyncio.sleep(0.02)
            done.append(event.event_type)

        bus.subscribe("task.started", slow)
        await bus.publish(make_event("task.started"))
        assert done == []  # publish 是 fire-and-forget
        await bus.wait_for_handlers()
        assert done == ["task.started"]

    @pytest.mark.asyncio
    async def test_stats_reports_the_observability_surface(self):
        bus = EventBus()
        bus.subscribe("*", lambda event: None)

        await bus.publish(make_event("task.started"))
        await bus.wait_for_handlers()

        stats = bus.stats()
        assert stats["patterns"] == 1
        assert stats["subscribers"] == 1
        assert stats["history"] == 1
        assert stats["in_flight"] == 0
        assert stats["dispatch_failures"] == 0
        assert stats["last_failure"] is None
        assert stats["strict"] is False


class TestStrictSwitch:
    def test_strict_from_env(self, monkeypatch):
        monkeypatch.delenv(STRICT_ENV, raising=False)
        assert strict_from_env() is False
        assert EventBus().strict is False

        for value in ("1", "true", "TRUE", "yes", "on", " On "):
            monkeypatch.setenv(STRICT_ENV, value)
            assert strict_from_env() is True, value

        monkeypatch.setenv(STRICT_ENV, "0")
        assert strict_from_env() is False

    def test_the_explicit_argument_wins_over_the_environment(self, monkeypatch):
        monkeypatch.setenv(STRICT_ENV, "1")
        assert EventBus().strict is True
        assert EventBus(strict=False).strict is False

    def test_callback_name_is_readable(self):
        class Subscriber:
            def __call__(self, event):
                return None

        assert callback_name(lambda event: None).endswith("<lambda>")
        assert callback_name(Subscriber()).startswith("<")

        def named(event):
            return None

        assert callback_name(named).endswith("named")
