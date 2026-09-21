"""剧本自动触发策略（2026-09-21 定）：取证类武装、处置类不武装、自动触发不派子 Agent。

判据在 ``threat_workflows.step_kind``：``auto``（只读取证命令）/ ``review``（要判断，人工）/
``action``（处置，人工）。这里把「数据位 ↔ 步骤性质」的一致性钉住，再验运行期的步骤闸门：
事件自动触发只跑取证命令步骤，人工 ``run_now`` 全跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import threat_workflows  # noqa: E402
from trimum_core.event_bus import EventBus  # noqa: E402
from trimum_core.models import ExecuteResponse  # noqa: E402
from trimum_core.workflow_engine import WorkflowDefV2  # noqa: E402
from trimum_core.workflow_runtime import WorkflowRuntime, workflow_enabled  # noqa: E402


#: 取证类剧本（命令式取证步骤 + 判断步骤，无处置步骤）→ 事件来了自动跑
FORENSIC_PLAYBOOKS = (
    "threat-prelink-check",
    "threat-ebpf-scan",
    "threat-kernel-scan",
    "threat-crypto-scan",
    "threat-ssh-audit",
    "threat-cron-audit",
    "threat-systemd-audit",
    "threat-memfd-scan",
)

#: 处置类 / 没有可自动执行的步骤 → 不武装（处置要人点）
MANUAL_PLAYBOOKS = (
    "threat-revshell-cleanup",
    "threat-pipe-download-check",
    "threat-ransomware-response",
    "threat-btrfs-snapshot-protect",
    "threat-persistence-sweep",
    "threat-supply-chain-audit",
    "threat-prompt-injection-check",
    "threat-audit-integrity-check",
)


class FakeGateway:
    """记录请求的假网关（真 shell 执行由 ``trm exec`` 那条线覆盖）。"""

    def __init__(self) -> None:
        self.requests: list = []

    async def execute(self, request):
        self.requests.append(request)
        return ExecuteResponse(
            execution_id="x", status="allowed", output="ok", exit_code=0
        )


def build(text: str) -> WorkflowDefV2:
    return WorkflowDefV2(**yaml.safe_load(text))


#: 一键剧本：第一步取证（默认放行）、第二步带闸门（自动触发不跑）
GATED = """
id: gated
name: Gated
steps:
  - trigger:
      event_type: security.monitor_result
    execute:
      - agent_type: shell
        instruction: crontab -l
      - agent_type: shell
        instruction: echo 处置
        config:
          step_kind: action
          auto_run: false
"""


class TestStepKinds:
    @pytest.mark.parametrize("step,expected", [
        ("cat /etc/ld.so.preload", "auto"),
        ("ls -la /etc/ld.so.preload", "auto"),
        ("sha256sum /etc/ld.so.preload", "auto"),
        ("crontab -l", "auto"),
        ("systemctl list-units --state=enabled", "auto"),
        ("ps aux | grep crypto", "auto"),
        ("lsof | grep memfd", "auto"),
        ("sudo ls", "auto"),
        ("/usr/bin/cat /etc/hosts", "auto"),
        ("比对上次 hash 基线", "review"),
        ("报告新增条目", "review"),
        ("report", "review"),
        ("kill 对应 PID", "action"),
        ("firewall-cmd --add-rich-rule 阻断 IP", "action"),
        ("SIGSTOP 冻结进程", "action"),
        ("重新更新基线 hash 基线", "action"),
        ("rm -rf /", "action"),
        ("find / -delete", "action"),
        ("find / -exec rm {} ;", "action"),
        ("crontab -r", "action"),
        ("systemctl stop nginx", "action"),
        ("cat /etc/shadow > /tmp/x", "action"),
        ("", "action"),
    ])
    def test_step_kind(self, step, expected):
        assert threat_workflows.step_kind(step) == expected

    def test_only_readonly_whitelisted_commands_are_auto(self):
        """白名单之外、以及白名单里带危险参数/子命令的，都不自动跑。"""
        assert threat_workflows.step_kind("python -c 'x'") == "action"
        assert threat_workflows.step_kind("chmod 777 /etc/shadow") == "action"
        assert threat_workflows.step_kind("systemctl status nginx") == "auto"

    def test_unknown_prose_is_treated_as_action(self):
        """看不懂的散文一律不自动执行 —— 保守方向，宁可少跑。"""
        assert threat_workflows.step_kind("把配置改成另一种格式") == "action"
        assert threat_workflows.step_kind("verify signature") == "action"


class TestArmingConsistency:
    def test_every_playbook_declares_auto_trigger_explicitly(self):
        for entry in threat_workflows.THREAT_WORKFLOWS:
            assert isinstance(entry["auto_trigger"], bool), entry["name"]

    def test_arming_has_a_reason_either_way(self):
        for entry in threat_workflows.THREAT_WORKFLOWS:
            kinds = [threat_workflows.step_kind(step) for step in entry["steps"]]
            if entry["auto_trigger"]:
                assert kinds.count("auto") >= 1, entry["name"]
                assert kinds.count("action") == 0, entry["name"]
            else:
                assert kinds.count("action") >= 1 or kinds.count("auto") == 0, (
                    entry["name"],
                    kinds,
                )

    def test_forensic_and_manual_sets(self):
        assert sorted(threat_workflows.auto_trigger_workflows()) == sorted(
            FORENSIC_PLAYBOOKS
        )
        for name in MANUAL_PLAYBOOKS:
            entry = threat_workflows.get_workflow_by_name(name)
            assert entry is not None, name
            assert entry["auto_trigger"] is False, name

    def test_armed_playbooks_never_let_a_sub_agent_run_automatically(self):
        for workflow in threat_workflows.builtin_workflows():
            for step in workflow.steps:
                for task in step.execute:
                    if task.config["auto_run"]:
                        continue
                    assert task.agent_type == threat_workflows.REVIEW_AGENT, (
                        workflow.id,
                        task.instruction,
                    )

    def test_compiled_nodes_carry_the_gate(self):
        workflow = threat_workflows.to_workflow_def_v2(
            threat_workflows.get_workflow_by_name("threat-cron-audit")
        )
        nodes = workflow.to_workflow_definition().nodes
        assert [node.config["step_kind"] for node in nodes] == [
            "auto", "auto", "review", "review",
        ]
        assert [node.config["auto_run"] for node in nodes] == [True, True, False, False]

    def test_enabled_bit_follows_auto_trigger(self):
        for workflow in threat_workflows.builtin_workflows():
            assert workflow.config["enabled"] is workflow.config["auto_trigger"]
            assert workflow_enabled(workflow) is workflow.config["auto_trigger"]


class TestAutoRunGate:
    @pytest.mark.asyncio
    async def test_event_run_skips_the_gated_step(self):
        gateway = FakeGateway()
        bus = EventBus()
        runtime = WorkflowRuntime(bus, gateway=gateway)
        runtime.register(build(GATED))
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event(
                "security.monitor_result", "test", {"threat_name": "cron_persistence"}
            )
            records = await runtime.wait_for_runs(since=baseline, timeout=5)
        finally:
            await runtime.stop()

        assert len(records) == 1
        assert records[0].status == "completed"
        assert records[0].triggered_by == "event"
        assert [node.status for node in records[0].nodes] == ["completed", "skipped"]
        assert [request.args for request in gateway.requests] == [["crontab -l"]]

    @pytest.mark.asyncio
    async def test_skipped_step_says_why(self):
        bus = EventBus()
        runtime = WorkflowRuntime(bus, gateway=FakeGateway())
        runtime.register(build(GATED))
        reasons: list = []

        async def _on_skipped(event) -> None:
            reasons.append(event.payload.get("reason", ""))

        bus.subscribe("task.node.skipped", _on_skipped)
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event(
                "security.monitor_result", "test", {"threat_name": "cron_persistence"}
            )
            await runtime.wait_for_runs(since=baseline, timeout=5)
        finally:
            await runtime.stop()

        assert len(reasons) == 1
        assert "auto_run_blocked:action" in reasons[0]
        assert "人工" in reasons[0]

    @pytest.mark.asyncio
    async def test_manual_run_ignores_the_gate(self):
        gateway = FakeGateway()
        runtime = WorkflowRuntime(EventBus(), gateway=gateway)
        runtime.register(build(GATED))
        record = await runtime.run_now("gated")
        assert record.status == "completed"
        assert [node.status for node in record.nodes] == ["completed", "completed"]
        assert [request.args for request in gateway.requests] == [
            ["crontab -l"], ["echo 处置"],
        ]

    @pytest.mark.asyncio
    async def test_armed_playbook_runs_forensics_only(self):
        gateway = FakeGateway()
        bus = EventBus()
        runtime = WorkflowRuntime(bus, gateway=gateway)
        runtime.register_builtin()
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event(
                "security.monitor_result", "test", {"threat_name": "cron_persistence"}
            )
            records = await runtime.wait_for_runs(since=baseline, timeout=5)
        finally:
            await runtime.stop()

        assert [record.workflow_id for record in records] == ["threat-cron-audit"]
        assert records[0].status == "completed"
        assert [node.status for node in records[0].nodes] == [
            "completed", "completed", "skipped", "skipped",
        ]
        assert [request.args for request in gateway.requests] == [
            ["crontab -l"], ["ls /etc/cron.d/"],
        ]

    @pytest.mark.asyncio
    async def test_response_playbook_stays_quiet_on_its_event(self):
        bus = EventBus()
        runtime = WorkflowRuntime(bus, gateway=FakeGateway())
        runtime.register_builtin()
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event(
                "security.monitor_result", "test", {"threat_name": "reverse_shell"}
            )
            records = await runtime.wait_for_runs(since=baseline, timeout=1)
        finally:
            await runtime.stop()
        assert records == []


class TestRegisterBuiltinArming:
    def test_register_all_arms_forensics_only(self, tmp_path):
        runtime = WorkflowRuntime(EventBus(), gateway=FakeGateway())
        counts = runtime.register_all(str(tmp_path / "workflows"))
        assert len(counts["builtin"]) == len(threat_workflows.THREAT_WORKFLOWS)
        assert runtime.get("threat-cron-audit").enabled is True
        assert runtime.get("threat-revshell-cleanup").enabled is False

    def test_explicit_false_forces_everything_off(self):
        runtime = WorkflowRuntime(EventBus(), gateway=FakeGateway())
        runtime.register_builtin(enabled=False)
        listed = runtime.list_workflows()
        assert listed and all(item["enabled"] is False for item in listed)

    def test_explicit_true_forces_everything_on(self):
        """强制武装时不看剧本自己的位 —— 但步骤闸门仍在（那是另一层）。"""
        runtime = WorkflowRuntime(EventBus(), gateway=FakeGateway())
        runtime.register_builtin(enabled=True)
        assert runtime.get("threat-revshell-cleanup").enabled is True
        assert runtime.get("threat-cron-audit").enabled is True