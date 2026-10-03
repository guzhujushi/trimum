"""P0 安全响应链 —— ``security.monitor_result`` 载荷契约（扁平，2026-09-21）。

背景：2026-09-20 只读审计发现生产端把 ``ThreatMatch`` 嵌进 ``payload["threat"]``，
而内置剧本的条件写的是**扁平**的 ``payload.get("threat_name")`` —— 即使事件接上也不会
触发。本文件把「生产端发出去的载荷能命中每一条内置剧本」锁成契约，避免两边再次漂移。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import threat_workflows  # noqa: E402
from trimum_core.event_bus import EVENT_SEC_MONITOR, EventBus  # noqa: E402
from trimum_core.models import (  # noqa: E402
    DefenseAction,
    SourceType,
    SystemEvent,
    ThreatCategory,
    ThreatMatch,
)
from trimum_core.sec_monitor import (  # noqa: E402
    OpContextClassifier,
    SecMonitor,
    ThreatMatcher,
    monitor_result_payload,
)
from trimum_core.workflow_runtime import WorkflowRuntime  # noqa: E402


def make_threat(**overrides) -> ThreatMatch:
    fields = {
        "threat_name": "ld_preload",
        "category": ThreatCategory.PRIV_ESCAPE,
        "defense": DefenseAction.DENY,
        "confidence": 0.9,
        "matched_pattern": r"\bLD_PRELOAD\b",
        "workflow_name": "threat-prelink-check",
        "reason": "ld_preload detected",
    }
    fields.update(overrides)
    return ThreatMatch(**fields)


def make_event(**payload) -> SystemEvent:
    return SystemEvent(
        event_type="agent.executing",
        source="tool_gateway",
        source_type=SourceType.AI,
        payload=payload,
    )


class _StubExecutor:
    """记录调用即可 —— 本文件验的是载荷契约，不验阻断动作。"""

    def __init__(self) -> None:
        self.calls: list[tuple[ThreatMatch, SystemEvent]] = []

    async def execute(self, threat: ThreatMatch, event: SystemEvent) -> None:
        self.calls.append((threat, event))


async def make_monitor(executor=None):
    """按 daemon 的真实装配方式建一个 SecMonitor（``start()`` 才注册订阅）。"""
    bus = EventBus()
    captured: list[SystemEvent] = []

    async def capture(event: SystemEvent) -> None:
        captured.append(event)

    bus.subscribe(EVENT_SEC_MONITOR, capture)
    monitor = SecMonitor(
        bus, ThreatMatcher(), OpContextClassifier(), executor or _StubExecutor()
    )
    await monitor.start()
    return monitor, bus, captured


class TestMonitorResultPayload:
    """载荷本身：扁平、带上下文、可序列化。"""

    def test_is_flat_and_carries_all_threat_match_fields(self):
        payload = monitor_result_payload(make_threat(), make_event(agent_id="a1"))

        for key in ("threat_name", "category", "defense", "confidence",
                    "matched_pattern", "workflow_name", "reason"):
            assert key in payload, key
        assert payload["threat_name"] == "ld_preload"
        assert payload["defense"] == "deny"          # 取的是枚举值，不是枚举对象
        assert payload["category"] == "priv_escape"
        assert payload["confidence"] == 0.9

    def test_does_not_nest_the_threat_object(self):
        payload = monitor_result_payload(make_threat(), make_event(agent_id="a1"))
        assert "threat" not in payload
        assert "original_event" not in payload

    def test_carries_the_triggering_context_flat(self):
        event = make_event(
            agent_id="a1", command="echo x >> /etc/ld.so.preload", pid=4242,
            sandbox="docker", layer_hit="L4",
        )
        payload = monitor_result_payload(make_threat(), event)

        assert payload["agent_id"] == "a1"
        assert payload["command"] == "echo x >> /etc/ld.so.preload"
        assert payload["pid"] == 4242
        assert payload["sandbox"] == "docker"
        assert payload["layer_hit"] == "L4"
        assert payload["source_event_type"] == "agent.executing"

    def test_context_defaults_when_the_event_carries_nothing(self):
        payload = monitor_result_payload(make_threat(), make_event())

        assert payload["agent_id"] == "unknown"
        assert payload["command"] == ""
        assert payload["pid"] == 0
        assert payload["sandbox"] == "default"
        assert payload["layer_hit"] == "L2"

    def test_is_json_serializable(self):
        payload = monitor_result_payload(make_threat(), make_event(agent_id="a1"))
        assert json.loads(json.dumps(payload))["threat_name"] == "ld_preload"


class TestDispatchPublishesTheFlatContract:
    """``_dispatch`` / ``_on_executing`` 真的发这个载荷，并且仍然交给 SecExecutor。"""

    @pytest.mark.asyncio
    async def test_dispatch_publishes_a_flat_monitor_result(self):
        monitor, _bus, captured = await make_monitor()
        await monitor._dispatch(make_threat(), make_event(agent_id="a1", command="ls"))
        await asyncio.sleep(0.05)

        assert len(captured) == 1
        assert captured[0].event_type == EVENT_SEC_MONITOR
        assert captured[0].source == "sec_monitor"
        assert captured[0].payload["threat_name"] == "ld_preload"
        assert captured[0].payload["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_dispatch_hands_the_threat_to_the_executor(self):
        executor = _StubExecutor()
        monitor, _bus, _captured = await make_monitor(executor)
        await monitor._dispatch(make_threat(), make_event(agent_id="a1"))

        assert len(executor.calls) == 1
        assert executor.calls[0][0].threat_name == "ld_preload"

    @pytest.mark.asyncio
    async def test_inspect_reports_a_real_threat_and_matches_the_builtin_script(self):
        """真命令 → 真威胁 → 发出去的载荷必须命中对应剧本。"""
        executor = _StubExecutor()
        monitor, bus, captured = await make_monitor(executor)

        threats = await monitor.inspect(make_event(
            agent_id="a1", command="echo 'x' >> /etc/ld.so.preload", pid=4242,
        ))
        await asyncio.sleep(0.05)

        assert [item.threat_name for item in threats] == ["ld_preload"]
        assert executor.calls, "威胁没有被交给 SecExecutor"
        assert len(captured) == 1
        payload = captured[0].payload
        assert payload["threat_name"] == "ld_preload"

        entry = next(
            item for item in threat_workflows.THREAT_WORKFLOWS
            if item["name"] == "threat-prelink-check"
        )
        assert WorkflowRuntime.eval_condition(
            threat_workflows.trigger_condition(entry), payload
        )


class TestScanEntryPoint:
    """扫描入口只剩一个：``inspect()``；事件订阅已删，别留两条路重复阻断。"""

    @pytest.mark.asyncio
    async def test_clean_command_reports_nothing(self):
        executor = _StubExecutor()
        monitor, _bus, captured = await make_monitor(executor)

        threats = await monitor.inspect(make_event(agent_id="a1", command="echo hello"))
        await asyncio.sleep(0.05)

        assert threats == []
        assert captured == []
        assert executor.calls == []

    @pytest.mark.asyncio
    async def test_start_does_not_subscribe_agent_executing(self):
        """往总线发 agent.executing 不应再触发扫描（ToolGateway 直连 inspect 才是入口）。"""
        executor = _StubExecutor()
        _monitor, bus, captured = await make_monitor(executor)

        await bus.publish(make_event(
            agent_id="a1", command="echo 'x' >> /etc/ld.so.preload",
        ))
        await asyncio.sleep(0.05)

        assert executor.calls == []
        assert captured == []


class TestBuiltinWorkflowContract:
    """生产端 ↔ 消费端契约：内置剧本的条件必须能被生产端载荷命中。"""

    def test_every_monitor_triggered_script_matches_the_produced_payload(self):
        event = make_event(agent_id="a1", command="crontab -l", pid=7)
        checked = 0

        for entry in threat_workflows.THREAT_WORKFLOWS:
            if entry.get("trigger") != "security.monitor_result":
                continue
            threat_name = (entry.get("filter") or {})["threat_name"]
            payload = monitor_result_payload(
                make_threat(threat_name=threat_name), event
            )
            condition = threat_workflows.trigger_condition(entry)
            assert WorkflowRuntime.eval_condition(condition, payload), (
                entry["name"], condition
            )
            checked += 1

        assert checked >= 15, "16 条内置剧本里应有 15 条监听 security.monitor_result"

    def test_unrelated_threat_does_not_satisfy_a_specific_script(self):
        entry = next(
            item for item in threat_workflows.THREAT_WORKFLOWS
            if item["name"] == "threat-ebpf-scan"
        )
        payload = monitor_result_payload(
            make_threat(threat_name="ld_preload"), make_event(agent_id="a1")
        )
        assert not WorkflowRuntime.eval_condition(
            threat_workflows.trigger_condition(entry), payload
        )

    def test_every_signature_points_at_an_existing_script_filtering_it(self):
        by_name = {entry["name"]: entry for entry in threat_workflows.THREAT_WORKFLOWS}
        signatures = ThreatMatcher().signatures

        assert signatures
        for signature in signatures:
            entry = by_name.get(signature.trigger_workflow)
            assert entry is not None, f"{signature.name} 指向了不存在的剧本"
            assert (entry.get("filter") or {}).get("threat_name") == signature.name
