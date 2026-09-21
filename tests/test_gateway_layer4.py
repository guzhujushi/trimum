"""P0 步骤 2 —— ToolGateway Layer 4 走 ``SecMonitor.inspect()``。

以前 L4 旁路调用 ``scan_command()``：威胁命中了，但既不广播 ``security.monitor_result``
也不交 SecExecutor —— 挡住的是「执行」，缺的是「响应 / 记录 / 通知 / 工作流触发」。
本文件端到端接一遍 Layer 4（真 SecMonitor + 真 SecExecutor，只有审计落临时目录），
验四件事：拒绝执行、事件广播、审计落盘、内置剧本条件被命中。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import threat_workflows  # noqa: E402
from trimum_core.event_bus import (  # noqa: E402
    EVENT_SEC_ALERT,
    EVENT_SEC_BLOCKED,
    EVENT_SEC_MONITOR,
    EVENT_WORKFLOW_TRIGGER,
    EventBus,
)
from trimum_core.models import (  # noqa: E402
    ExecuteRequest,
    SourceType,
    SystemEvent,
    ToolType,
)
from trimum_core.sec_executor import SecAudit, SecExecutor, SecNotif  # noqa: E402
from trimum_core.sec_monitor import (  # noqa: E402
    OpContextClassifier,
    SecMonitor,
    ThreatMatcher,
)
from trimum_core.tool_gateway import ToolGateway  # noqa: E402
from trimum_core.workflow_runtime import WorkflowRuntime  # noqa: E402


def _request(command: str) -> ExecuteRequest:
    return ExecuteRequest(
        tool=ToolType.SHELL,
        args=command.split(),
        agent_id="tester",
        source_type=SourceType.AI,
        skip_cwd_check=True,
    )


class _Recorder:
    """订阅关心的安全事件（总线是异步扇出，断言前记得 sleep 一拍）。"""

    WATCHED = (EVENT_SEC_MONITOR, EVENT_SEC_ALERT, EVENT_SEC_BLOCKED, EVENT_WORKFLOW_TRIGGER)

    def __init__(self, bus: EventBus) -> None:
        self.events: dict[str, list[SystemEvent]] = {key: [] for key in self.WATCHED}
        for key in self.WATCHED:
            bus.subscribe(key, self._make(key))

    def _make(self, key: str):
        async def capture(event: SystemEvent) -> None:
            self.events[key].append(event)
        return capture

    def __getitem__(self, key: str) -> list[SystemEvent]:
        return self.events[key]


@pytest.fixture
def wired(tmp_path):
    """按 main.py ``init_security()`` 的方式装配 Layer 4（审计写临时目录）。"""
    bus = EventBus()
    recorder = _Recorder(bus)
    audit = SecAudit(audit_path=str(tmp_path / "security.log"))
    executor = SecExecutor(bus, audit, SecNotif(bus))
    monitor = SecMonitor(bus, ThreatMatcher(), OpContextClassifier(), executor)
    gateway = ToolGateway(sec_monitor=monitor, sec_executor=executor, event_bus=bus)
    return gateway, recorder, tmp_path


class TestLayer4Deny:
    """DENY 类威胁：拒绝执行 + 广播 + 审计 + 工作流触发，四件都要发生。"""

    @pytest.mark.asyncio
    async def test_command_is_blocked_by_the_monitor(self, wired):
        gateway, recorder, _tmp = wired

        resp = await gateway.execute(_request("cat /etc/ld.so.preload"))
        await asyncio.sleep(0.05)

        assert resp.status == "denied"
        assert resp.exit_code == 137
        assert "SECURITY BLOCKED" in (resp.error or "")
        assert resp.action.value == "deny"

    @pytest.mark.asyncio
    async def test_flat_monitor_result_is_broadcast_with_the_scan_context(self, wired):
        gateway, recorder, _tmp = wired

        await gateway.execute(_request("cat /etc/ld.so.preload"))
        await asyncio.sleep(0.05)

        assert len(recorder[EVENT_SEC_MONITOR]) == 1
        payload = recorder[EVENT_SEC_MONITOR][0].payload
        assert payload["threat_name"] == "ld_preload"
        assert payload["command"] == "cat /etc/ld.so.preload"
        assert payload["agent_id"] == "tester"
        assert payload["layer_hit"] == "L4"
        assert payload["pid"] == 0, "L4 是执行前闸门，不能拿 daemon 自己的 PID 冒充"

    @pytest.mark.asyncio
    async def test_executor_audits_and_notifies_and_triggers_the_script(self, wired):
        gateway, recorder, tmp_path = wired

        await gateway.execute(_request("cat /etc/ld.so.preload"))
        await asyncio.sleep(0.05)

        assert [event.payload["threat_name"] for event in recorder[EVENT_SEC_BLOCKED]] == ["ld_preload"]
        assert [event.payload["workflow_name"] for event in recorder[EVENT_WORKFLOW_TRIGGER]] == [
            "threat-prelink-check"
        ]
        audit_text = (tmp_path / "security.log").read_text(encoding="utf-8")
        assert "ld_preload" in audit_text and "deny" in audit_text

    @pytest.mark.asyncio
    async def test_payload_satisfies_the_builtin_script_condition(self, wired):
        """契约闭环：L4 发出去的载荷真的能让内置剧本条件成立。"""
        gateway, recorder, _tmp = wired

        await gateway.execute(_request("cat /etc/ld.so.preload"))
        await asyncio.sleep(0.05)

        payload = recorder[EVENT_SEC_MONITOR][0].payload
        entry = next(
            item for item in threat_workflows.THREAT_WORKFLOWS
            if item["name"] == "threat-prelink-check"
        )
        assert WorkflowRuntime.eval_condition(
            threat_workflows.trigger_condition(entry), payload
        )


class TestLayer4NonDeny:
    """非 DENY 类威胁（CONFIRM / FREEZE / ISOLATE）：今天只响应不拦，行为已锁。"""

    @pytest.mark.asyncio
    async def test_confirm_threat_is_reported_but_the_command_still_runs(self, wired):
        gateway, recorder, _tmp = wired

        resp = await gateway.execute(_request("echo npm install demo"))
        await asyncio.sleep(0.05)

        assert resp.status in ("allowed", "confirmed", "success")
        assert [event.payload["threat_name"] for event in recorder[EVENT_SEC_MONITOR]] == [
            "supply_chain"
        ]
        assert [event.payload["threat_name"] for event in recorder[EVENT_SEC_ALERT]] == [
            "supply_chain"
        ]
        assert recorder[EVENT_SEC_BLOCKED] == []


class TestLayer4QuietPath:
    @pytest.mark.asyncio
    async def test_clean_command_stays_quiet(self, wired):
        gateway, recorder, tmp_path = wired

        resp = await gateway.execute(_request("echo hello"))
        await asyncio.sleep(0.05)

        assert resp.status in ("allowed", "confirmed", "success")
        for key in _Recorder.WATCHED:
            assert recorder[key] == [], key
        assert not (tmp_path / "security.log").exists()

    @pytest.mark.asyncio
    async def test_gateway_without_monitor_skips_layer4(self):
        """没装监控的网关（CLI / agent loop）就没有 L4：同一条威胁命令只会照常往下走。

        这条断言是**缺口陈述**而不是赞美：L1 策略放行 `cat`、L2.5 也放行，挡下
        ld_preload 的只有 L4。命令本身跑不跑得起来取决于宿主（Windows 没有 `cat`），
        所以这里只断言「没有被拦」+「没有 monitor_result」。
        """
        bus = EventBus()
        recorder = _Recorder(bus)
        gateway = ToolGateway(event_bus=bus)

        resp = await gateway.execute(_request("cat /etc/ld.so.preload"))
        await asyncio.sleep(0.05)

        assert resp.status != "denied"
        assert recorder[EVENT_SEC_MONITOR] == []
