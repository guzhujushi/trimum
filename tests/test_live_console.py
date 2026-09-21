"""LiveConsole 的事件订阅（2026-09-21 修）：进度按段匹配 + 重复不重复打印。

背景：``subscribe_events`` 以前订 ``<namespace>.*``、却按 ``task.started`` 全等比较，
于是除 ``AgentLoop`` 自己发的 ``task.started``，引擎的 ``task.node.started`` /
``task.workflow.started`` 一条都点不亮 —— 进度永远不动。
"""

from __future__ import annotations

import pytest

from trimum_core import live_console as live_console_module
from trimum_core.event_bus import EventBus, NAMESPACE_EVENT, NAMESPACE_TASK
from trimum_core.live_console import LiveConsole
from trimum_core.models import SystemEvent


class FakeConsole:
    """只接住 ``print()`` 的参数，不真的往终端画。"""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args, **kwargs) -> None:
        self.lines.append(" ".join(str(arg) for arg in args))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture()
def fake_console(monkeypatch):
    fake = FakeConsole()
    monkeypatch.setattr(live_console_module, "_console", fake)
    return fake


def task_event(event_type: str, name: str, **extra) -> SystemEvent:
    """引擎/AgentLoop 发的进度事件（真实类型是 ``task.node.started`` 这种三段式）。"""
    return SystemEvent(
        event_type=f"{NAMESPACE_TASK}{event_type}",
        source="workflow",
        payload={"name": name, **extra},
    )


@pytest.mark.asyncio
async def test_segment_matched_progress_events_light_up(fake_console):
    bus = EventBus()
    console = LiveConsole(bus)
    await console.subscribe_events("task")

    await bus.publish(task_event("node.started", "扫描 prelink"))
    await bus.publish(task_event("node.completed", "扫描 prelink"))
    await bus.publish(task_event("node.skipped", "处置", reason="auto_run_blocked:action"))
    await bus.wait_for_handlers()

    assert "进行中" in fake_console.text
    assert "扫描 prelink" in fake_console.text
    assert "✅" in fake_console.text
    assert "auto_run_blocked:action" in fake_console.text


@pytest.mark.asyncio
async def test_repeated_events_print_once(fake_console):
    bus = EventBus()
    console = LiveConsole(bus)
    await console.subscribe_events("task")

    for _ in range(2):
        await bus.publish(task_event("node.started", "扫描"))
    await bus.wait_for_handlers()

    assert len(fake_console.lines) == 1


@pytest.mark.asyncio
async def test_direct_call_and_event_do_not_double_print(fake_console):
    bus = EventBus()
    console = LiveConsole(bus)
    await console.subscribe_events("task")

    console.step_start("扫描")                       # AgentLoop 直接调
    await bus.publish(task_event("node.started", "扫描"))   # 事件又说一遍
    await bus.wait_for_handlers()

    assert len(fake_console.lines) == 1


@pytest.mark.asyncio
async def test_security_alert_is_shown(fake_console):
    """`security.alert` 的真实类型没有 `event.` 前缀（SecExecutor 直接造 SystemEvent）。"""
    bus = EventBus()
    console = LiveConsole(bus)
    await console.subscribe_events("task")

    await bus.publish(
        SystemEvent(
            event_type="security.alert",
            source="sec-executor",
            payload={"detail": "检测到 prelink 劫持"},
        )
    )
    await bus.publish(
        SystemEvent(
            event_type=f"{NAMESPACE_EVENT}security.alert",
            source="sec-monitor",
            payload={"detail": "内核模块异常"},
        )
    )
    await bus.wait_for_handlers()

    assert fake_console.text.count("安全告警") == 2
    assert "检测到 prelink 劫持" in fake_console.text
    assert "内核模块异常" in fake_console.text


@pytest.mark.asyncio
async def test_unrelated_events_stay_silent(fake_console):
    bus = EventBus()
    console = LiveConsole(bus)
    await console.subscribe_events("task")

    await bus.emit_event("mcp_call", "gateway", {"tool": "echo"})
    await bus.publish(
        SystemEvent(event_type="security.monitor_result", source="monitor", payload={})
    )
    await bus.wait_for_handlers()

    assert fake_console.lines == []


@pytest.mark.asyncio
async def test_unsubscribe_stops_listening(fake_console):
    bus = EventBus()
    console = LiveConsole(bus)
    await console.subscribe_events("task")
    console.unsubscribe()

    await bus.publish(task_event("node.started", "扫描"))
    await bus.wait_for_handlers()

    assert fake_console.lines == []
    assert bus.stats()["patterns"] == 0


@pytest.mark.asyncio
async def test_without_a_bus_it_only_warns(fake_console):
    console = LiveConsole(None)
    await console.subscribe_events("task")
    assert "Event Bus 未配置" in fake_console.text
