"""W1 — workflow 执行语义：v2 编译、触发器匹配、内置剧本、运行时记账。

这里全部用**假网关**（``FakeGateway``）：真 shell 执行由 ``trm exec`` 那条线覆盖，
本文件要验的是「命令有没有经过网关」「命中 / 未命中 / 失败怎么记账」，以及
``WorkflowRuntime`` 的匹配与并发语义。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import threat_workflows  # noqa: E402
from trimum_core.event_bus import EventBus  # noqa: E402
from trimum_core.models import ExecuteResponse, SourceType  # noqa: E402
from trimum_core.workflow_engine import WorkflowDefV2  # noqa: E402
from trimum_core.workflow_runtime import (  # noqa: E402
    REVIEW_AGENT,
    WorkflowRuntime,
    workflow_enabled,
)


SIMPLE = """
id: demo
name: Demo
description: trigger -> shell
steps:
  - trigger:
      event_type: security.monitor_result
      condition: 'payload.get("threat_name") == "cron_persistence"'
    execute:
      - agent_type: shell
        instruction: echo hello
        timeout_seconds: 5
      - agent_type: shell
        instruction: echo world
        timeout_seconds: 5
"""

TWO_STEPS = """
id: two
name: Two steps
steps:
  - trigger:
      event_type: security.monitor_result
    execute:
      - agent_type: shell
        instruction: echo first
  - trigger:
      event_type: system.heartbeat
    execute:
      - agent_type: shell
        instruction: echo second
"""


LOOPY = """
id: loopy
name: Loopy
steps:
  - trigger: {event_type: security.monitor_result}
    execute:
      - agent_type: shell
        instruction: echo kick
  - trigger: {event_type: workflow.finished}
    execute:
      - agent_type: shell
        instruction: echo a
  - trigger: {event_type: workflow.finished}
    execute:
      - agent_type: shell
        instruction: echo b
"""


def build(text: str) -> WorkflowDefV2:
    return WorkflowDefV2(**yaml.safe_load(text))


class FakeGateway:
    """记录请求的假网关。"""

    def __init__(self, *, deny: bool = False, exit_code: int = 0):
        self.requests: list = []
        self.deny = deny
        self.exit_code = exit_code
        self.block = None

    async def execute(self, request):
        self.requests.append(request)
        if self.block is not None:
            await self.block.wait()
        if self.deny:
            return ExecuteResponse(
                execution_id="x",
                status="denied",
                error="denied by policy",
                exit_code=1,
                reason="policy",
            )
        return ExecuteResponse(
            execution_id="x", status="allowed", output="ok", exit_code=self.exit_code
        )


class TestV2Compilation:
    """E4 遗留修复：``instruction`` 必须落到可执行节点上。"""

    def test_instruction_and_agent_type_land_in_config(self):
        definition = build(SIMPLE).to_workflow_definition()
        first = definition.nodes[0]
        assert first.handler == "shell"
        assert first.config["instruction"] == "echo hello"
        assert first.config["agent_type"] == "shell"
        assert first.config["trigger_event"] == "security.monitor_result"
        assert first.timeout_seconds == 5

    def test_label_falls_back_to_trigger_and_agent_type(self):
        definition = build(SIMPLE).to_workflow_definition()
        assert definition.nodes[0].label == "echo hello"

    def test_input_data_and_input_from_are_carried(self):
        workflow = build(
            """
id: chain
steps:
  - trigger:
      event_type: workflow.request
    execute:
      - agent_type: shell
        instruction: echo one
      - agent_type: shell
        instruction: echo two
        input_from: [step_0_task_0]
        input_data: {threshold: 3}
"""
        ).to_workflow_definition()
        second = workflow.nodes[1]
        assert second.input_from == ["step_0_task_0"]
        assert second.config["input_data"] == {"threshold": 3}

    def test_nodes_chain_sequentially(self):
        definition = build(SIMPLE).to_workflow_definition()
        assert len(definition.nodes) == 2
        assert len(definition.edges) == 1
        assert definition.edges[0].source == "step_0_task_0"
        assert definition.edges[0].target == "step_0_task_1"


class TestTriggerMatching:
    def test_exact_match(self):
        assert WorkflowRuntime.type_matches("security.monitor_result", "security.monitor_result")

    def test_namespace_prefix_is_ignored(self):
        """YAML 写人话，总线上的类型带 ``event.`` / ``task.`` 前缀。"""
        assert WorkflowRuntime.type_matches(
            "security.monitor_result", "event.security.monitor_result"
        )
        assert WorkflowRuntime.type_matches("node.completed", "task.node.completed")

    def test_wildcard_match(self):
        assert WorkflowRuntime.type_matches("security.*", "event.security.monitor_result")
        assert WorkflowRuntime.type_matches("*", "event.anything")

    def test_empty_trigger_never_matches(self):
        assert not WorkflowRuntime.type_matches("", "event.security.monitor_result")

    def test_unrelated_type_does_not_match(self):
        assert not WorkflowRuntime.type_matches("security.monitor_result", "event.tool.executed")

    def test_condition_empty_means_pass(self):
        assert WorkflowRuntime.eval_condition("", {})

    def test_condition_reads_payload(self):
        expr = 'payload.get("threat_name") == "cron_persistence"'
        assert WorkflowRuntime.eval_condition(expr, {"threat_name": "cron_persistence"})
        assert not WorkflowRuntime.eval_condition(expr, {"threat_name": "other"})
        assert not WorkflowRuntime.eval_condition(expr, {})

    def test_condition_has_no_builtins(self):
        assert not WorkflowRuntime.eval_condition('__import__("os").getcwd()', {})
        assert not WorkflowRuntime.eval_condition('open("/etc/passwd").read()', {})

    def test_broken_condition_is_not_a_pass(self):
        assert not WorkflowRuntime.eval_condition("payload[", {})


class TestBuiltinPlaybooks:
    def test_every_threat_playbook_compiles(self):
        builtins = threat_workflows.builtin_workflows()
        assert len(builtins) == len(threat_workflows.THREAT_WORKFLOWS)
        assert all(wf.id and wf.steps for wf in builtins)

    def test_builtins_are_disabled_by_default(self):
        for workflow in threat_workflows.builtin_workflows():
            assert workflow_enabled(workflow) is False
            assert workflow.config["builtin"] is True

    def test_builtin_playbooks_listen_to_the_fact_chain_only(self):
        """归属（P0 步骤 3）：剧本只监听 ``security.monitor_result``（L4 事实事件）与
        ``cron``（定时）；``workflow.trigger`` 是意图驱动那条链的，剧本不碰它。"""
        allowed = {"security.monitor_result", "cron"}
        for workflow in threat_workflows.builtin_workflows():
            for step in workflow.steps:
                assert step.trigger.event_type in allowed, (
                    workflow.id, step.trigger.event_type
                )
        assert threat_workflows.get_workflows_by_trigger("workflow.trigger") == []
        assert len(threat_workflows.get_workflows_by_trigger("security.monitor_result")) == 15

    def test_filter_becomes_a_condition(self):
        workflow = threat_workflows.to_workflow_def_v2(
            threat_workflows.get_workflow_by_name("threat-cron-audit")
        )
        trigger = workflow.steps[0].trigger
        assert trigger.event_type == "security.monitor_result"
        assert trigger.condition == (
            'payload.get(\'threat_name\') == \'cron_persistence\''
        )

    def test_command_steps_compile_to_shell_and_prose_to_agent(self):
        workflow = threat_workflows.to_workflow_def_v2(
            threat_workflows.get_workflow_by_name("threat-cron-audit")
        )
        types = [task.agent_type for task in workflow.steps[0].execute]
        assert types[:2] == ["shell", "shell"]
        assert REVIEW_AGENT in types

    def test_is_local_command(self):
        assert threat_workflows.is_local_command("crontab -l")
        assert threat_workflows.is_local_command("ls /etc/cron.d/")
        assert not threat_workflows.is_local_command("比对上次 cron hash")
        assert not threat_workflows.is_local_command("report")
        assert not threat_workflows.is_local_command("")

    def test_trigger_condition_of_playbook_without_filter(self):
        workflow = threat_workflows.to_workflow_def_v2(
            threat_workflows.get_workflow_by_name("threat-audit-integrity-check")
        )
        assert workflow.steps[0].trigger.condition == ""
        assert workflow.steps[0].trigger.event_type == "cron"


class TestEnabledFlag:
    def test_default_is_enabled(self):
        assert workflow_enabled(build(SIMPLE))

    def test_config_enabled_wins(self):
        assert not workflow_enabled(build("id: x\nconfig: {enabled: false}\n"))

    def test_ecosystem_enabled_is_honoured(self):
        """E4 导入产物把启用位写在 ``config.ecosystem.enabled``。"""
        assert not workflow_enabled(
            build("id: x\nconfig: {ecosystem: {enabled: false}}\n")
        )
        assert workflow_enabled(build("id: x\nconfig: {ecosystem: {enabled: true}}\n"))


def json_output(capsys) -> dict:
    """Read the ``trm --json`` output.

    On a real machine ``~/.trimum/tools/*/main.py`` may import something that
    prints a warning to stdout at import time (pymupdf's ``fitz`` does), so the
    JSON document is taken from the first ``{``.
    """
    out = capsys.readouterr().out
    return json.loads(out[out.index("{"):])


def collect_events(bus: EventBus, pattern: str = "*") -> list:
    seen: list = []

    async def _callback(event) -> None:
        seen.append(event)

    bus.subscribe(pattern, _callback)
    return seen


def runtime_with(
    text: str,
    gateway: FakeGateway | None = None,
    source: str = "file",
    **kwargs,
):
    bus = EventBus()
    runtime = WorkflowRuntime(bus, gateway=gateway or FakeGateway(), **kwargs)
    workflow = runtime.register(build(text), source=source)
    return runtime, bus, workflow


class TestRuntimeEventDriven:
    """「监听 Event Bus → 驱动执行」本体。"""

    @pytest.mark.asyncio
    async def test_matching_event_runs_the_step_through_the_gateway(self):
        gateway = FakeGateway()
        runtime, bus, _ = runtime_with(SIMPLE, gateway)
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
        assert records[0].trigger_event == "event.security.monitor_result"
        assert [node.status for node in records[0].nodes] == ["completed", "completed"]
        # 红线：命令是经过网关执行的，而且整条命令没被拆过
        assert [request.args for request in gateway.requests] == [
            ["echo hello"], ["echo world"]
        ]
        assert gateway.requests[0].source_type is SourceType.WORKFLOW

    @pytest.mark.asyncio
    async def test_condition_blocks_the_run(self):
        gateway = FakeGateway()
        runtime, bus, _ = runtime_with(SIMPLE, gateway)
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event("security.monitor_result", "test", {"threat_name": "other"})
            records = await runtime.wait_for_runs(since=baseline, timeout=0.5, grace=0.2)
        finally:
            await runtime.stop()

        assert records == []
        assert gateway.requests == []

    @pytest.mark.asyncio
    async def test_unrelated_event_does_not_run(self):
        runtime, bus, _ = runtime_with(SIMPLE)
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event("system.heartbeat", "test", {})
            records = await runtime.wait_for_runs(since=baseline, timeout=0.5, grace=0.2)
        finally:
            await runtime.stop()
        assert records == []

    @pytest.mark.asyncio
    async def test_empty_trigger_is_manual_only(self):
        runtime, bus, _ = runtime_with("id: manual\nsteps: [{execute: []}]\n")
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event("security.monitor_result", "test", {})
            records = await runtime.wait_for_runs(since=baseline, timeout=0.5, grace=0.2)
        finally:
            await runtime.stop()
        assert records == []

    @pytest.mark.asyncio
    async def test_two_steps_listen_independently(self):
        runtime, bus, _ = runtime_with(TWO_STEPS)
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event("security.monitor_result", "test", {})
            await bus.emit_event("system.heartbeat", "test", {})
            records = await runtime.wait_for_runs(since=baseline, timeout=5)
        finally:
            await runtime.stop()

        assert [record.step_index for record in records] == [0, 1]
        assert all(record.status == "completed" for record in records)

    @pytest.mark.asyncio
    async def test_disabled_workflow_is_not_driven_by_events(self):
        gateway = FakeGateway()
        runtime, bus, _ = runtime_with(SIMPLE, gateway)
        runtime.get("demo").enabled = False
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event(
                "security.monitor_result", "test", {"threat_name": "cron_persistence"}
            )
            records = await runtime.wait_for_runs(since=baseline, timeout=0.5, grace=0.2)
        finally:
            await runtime.stop()

        assert records == []
        # 但手动跑仍然可以（人已经明确点了）
        record = await runtime.run_now("demo")
        assert record.status == "completed"

    @pytest.mark.asyncio
    async def test_already_running_step_is_skipped(self):
        gateway = FakeGateway()
        gateway.block = asyncio.Event()
        runtime, bus, _ = runtime_with(SIMPLE, gateway)
        await runtime.start()

        events = collect_events(bus, "event.workflow.skipped")
        try:
            baseline = runtime.run_count
            await bus.emit_event(
                "security.monitor_result", "test", {"threat_name": "cron_persistence"}
            )
            await asyncio.sleep(0.05)
            await bus.emit_event(
                "security.monitor_result", "test", {"threat_name": "cron_persistence"}
            )
            await asyncio.sleep(0.05)
            assert runtime.run_count - baseline == 1
            assert len(events) == 1
            assert events[0].payload["reason"] == "already_running"
            gateway.block.set()
            await runtime.wait_for_runs(since=baseline, timeout=5)
        finally:
            gateway.block.set()
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_event_loop_between_steps_is_throttled(self):
        """两个 step 都监听 ``workflow.finished`` 时会互相点火 —— 必须有熔断。

        没有熔断时这条链会一直跑下去（每次运行都发 finishing 事件、又命中下一个
        step）。这里只断言两件事：熔断事件出现过，且运行数真的停下来了。
        """
        runtime, bus, _ = runtime_with(
            LOOPY,
            FakeGateway(),
            run_window_seconds=10.0,
            max_runs_per_window=3,
        )
        throttled = collect_events(bus, "event.workflow.throttled")
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event("security.monitor_result", "test", {})
            await runtime.wait_for_runs(since=baseline, timeout=5)
            await asyncio.sleep(0.3)
            settled = runtime.run_count
            await asyncio.sleep(0.3)
            assert runtime.run_count == settled
        finally:
            await runtime.stop()

        assert runtime.run_count - baseline > 1
        assert len(throttled) >= 1
        assert throttled[0].payload["max_runs"] == 3

    @pytest.mark.asyncio
    async def test_stop_does_not_hang_on_a_blocked_node(self):
        gateway = FakeGateway()
        gateway.block = asyncio.Event()
        runtime, bus, _ = runtime_with(SIMPLE, gateway)
        await runtime.start()
        baseline = runtime.run_count
        await bus.emit_event(
            "security.monitor_result", "test", {"threat_name": "cron_persistence"}
        )
        await asyncio.sleep(0.05)
        assert runtime.in_flight == 1
        await asyncio.wait_for(runtime.stop(), timeout=3)
        assert runtime.in_flight == 0
        assert runtime.running is False


class TestRuntimeBookkeeping:
    @pytest.mark.asyncio
    async def test_run_now_executes_every_step(self):
        gateway = FakeGateway()
        runtime, _, _ = runtime_with(TWO_STEPS, gateway)
        record = await runtime.run_now("two")
        assert record.status == "completed"
        assert record.step_index == -1
        assert [request.args for request in gateway.requests] == [["echo first"], ["echo second"]]

    @pytest.mark.asyncio
    async def test_manual_trigger_returns_one_record_per_step(self):
        runtime, _, _ = runtime_with(TWO_STEPS)
        records = await runtime.trigger("two")
        assert [record.step_index for record in records] == [0, 1]
        assert all(record.triggered_by == "manual" for record in records)

    @pytest.mark.asyncio
    async def test_denied_command_fails_the_node(self):
        gateway = FakeGateway(deny=True)
        runtime, bus, _ = runtime_with(SIMPLE, gateway)
        await runtime.start()
        try:
            baseline = runtime.run_count
            await bus.emit_event(
                "security.monitor_result", "test", {"threat_name": "cron_persistence"}
            )
            records = await runtime.wait_for_runs(since=baseline, timeout=5)
        finally:
            await runtime.stop()

        record = records[0]
        assert record.status == "failed"
        # 第一个节点被拒 → FAILED；后继节点因前驱没完成而不再入队（DAG 语义）
        assert record.failed_nodes() == ["step_0_task_0"]
        assert [node.status for node in record.nodes] == ["failed", "created"]
        assert "denied by policy" in record.nodes[0].error

    @pytest.mark.asyncio
    async def test_missing_instruction_fails_loudly(self):
        runtime, _, _ = runtime_with(
            """
id: empty
steps:
  - trigger: {event_type: security.monitor_result}
    execute:
      - agent_type: shell
"""
        )
        record = await runtime.run_now("empty")
        assert record.status == "failed"
        assert "no instruction" in record.nodes[0].error

    @pytest.mark.asyncio
    async def test_run_events_are_broadcast(self):
        runtime, bus, _ = runtime_with(SIMPLE)
        triggered = collect_events(bus, "event.workflow.triggered")
        finished = collect_events(bus, "event.workflow.finished")
        record = await runtime.run_now("demo")
        await asyncio.sleep(0.05)
        assert triggered and triggered[0].payload["run_id"] == record.run_id
        assert finished and finished[0].payload["status"] == "completed"

    @pytest.mark.asyncio
    async def test_node_ids_keep_the_global_step_index(self):
        runtime, _, _ = runtime_with(TWO_STEPS)
        records = await runtime.trigger("two")
        assert [node.node_id for node in records[1].nodes] == ["step_1_task_0"]

    @pytest.mark.asyncio
    async def test_history_and_listing(self):
        runtime, _, _ = runtime_with(SIMPLE)
        await runtime.run_now("demo")
        assert len(runtime.runs("demo")) == 1
        assert runtime.runs("nope") == []
        listing = runtime.list_workflows()
        assert listing[0]["id"] == "demo"
        assert listing[0]["triggers"] == ["security.monitor_result"]
        assert listing[0]["tasks"] == 2

    @pytest.mark.asyncio
    async def test_wait_for_runs_times_out_without_a_run(self):
        runtime, _, _ = runtime_with(SIMPLE)
        assert await runtime.wait_for_runs(since=0, timeout=0.2, grace=0.1) == []

    @pytest.mark.asyncio
    async def test_unknown_workflow_is_rejected(self):
        runtime, _, _ = runtime_with(SIMPLE)
        with pytest.raises(Exception):
            await runtime.run_now("nope")
        with pytest.raises(Exception):
            await runtime.trigger("nope")

    def test_register_rejects_foreign_objects(self):
        runtime = WorkflowRuntime(EventBus(), gateway=FakeGateway())
        with pytest.raises(Exception):
            runtime.register({"id": "nope"})

    def test_get_finds_by_name(self):
        runtime, _, _ = runtime_with(SIMPLE)
        assert runtime.get("Demo").id == "demo"

    def test_unregister(self):
        runtime, _, _ = runtime_with(SIMPLE)
        assert runtime.unregister("demo") is True
        assert runtime.unregister("demo") is False

    @pytest.mark.asyncio
    async def test_register_all_lets_files_override_builtins(self, tmp_path):
        root = tmp_path / "workflows"
        (root / "threat-cron-audit").mkdir(parents=True)
        (root / "threat-cron-audit" / "workflow.yaml").write_text(
            "id: threat-cron-audit\nname: mine\nconfig: {enabled: true}\n"
            "steps:\n  - trigger: {event_type: security.monitor_result}\n"
            "    execute:\n      - agent_type: shell\n        instruction: echo mine\n",
            encoding="utf-8",
        )
        runtime = WorkflowRuntime(EventBus(), gateway=FakeGateway())
        counts = runtime.register_all(str(root))
        assert counts["builtin"] and counts["file"] == ["threat-cron-audit"]
        assert runtime.get("threat-cron-audit").enabled is True
        assert runtime.get("threat-cron-audit").source == "file"


class TestCli:
    """``trm workflow`` 命令行：列表 / 预演 / 手动跑 / 事件触发 / enable。"""

    def _root(self, tmp_path: Path) -> Path:
        root = tmp_path / "workflows"
        (root / "demo").mkdir(parents=True)
        (root / "demo" / "workflow.yaml").write_text(
            SIMPLE, encoding="utf-8"
        )
        return root

    def test_list_shows_file_workflows(self, tmp_path, capsys):
        from trimum_core.cli import main

        root = self._root(tmp_path)
        assert main(["--json", "workflow", "list", "--root", str(root)]) == 0
        data = json_output(capsys)
        assert data["count"] == 1
        assert data["workflows"][0]["id"] == "demo"
        assert data["workflows"][0]["source"] == "file"

    def test_list_all_includes_builtins_disabled(self, tmp_path, capsys):
        from trimum_core.cli import main

        root = self._root(tmp_path)
        assert main(["--json", "workflow", "list", "--all", "--root", str(root)]) == 0
        data = json_output(capsys)
        by_id = {item["id"]: item for item in data["workflows"]}
        assert by_id["demo"]["enabled"] is True
        assert by_id["threat-cron-audit"]["source"] == "builtin"
        assert by_id["threat-cron-audit"]["enabled"] is False

    def test_dry_run_executes_nothing(self, tmp_path, capsys, monkeypatch):
        from trimum_core.cli import main
        from trimum_core.cli.commands import workflow as workflow_mod

        def _boom(*args, **kwargs):
            raise AssertionError("dry-run must not execute anything")

        monkeypatch.setattr(workflow_mod, "_execute", _boom)
        assert main(["--json", "workflow", "run", "demo", "--dry-run",
                     "--root", str(self._root(tmp_path))]) == 0
        data = json_output(capsys)
        assert data["dry_run"] is True
        assert [node["instruction"] for node in data["nodes"]] == ["echo hello", "echo world"]

    def test_run_executes_through_the_real_gateway(self, tmp_path, capsys):
        from trimum_core.cli import main

        root = tmp_path / "workflows"
        (root / "echo-demo").mkdir(parents=True)
        (root / "echo-demo" / "workflow.yaml").write_text(
            "id: echo-demo\nsteps:\n"
            "  - trigger: {event_type: security.monitor_result}\n"
            "    execute:\n"
            "      - agent_type: shell\n        instruction: echo trimum-w1\n",
            encoding="utf-8",
        )
        assert main(["--json", "workflow", "run", "echo-demo", "--root", str(root)]) == 0
        data = json_output(capsys)
        assert data["triggered_by"] == "manual"
        assert data["runs"][0]["status"] == "completed"
        assert data["runs"][0]["nodes"][0]["result"]["output"].strip() == "trimum-w1"

    def test_run_waits_for_the_event(self, tmp_path, capsys):
        from trimum_core.cli import main

        root = self._root(tmp_path)
        assert main([
            "--json", "workflow", "run", "demo",
            "--root", str(root),
            "--event", "security.monitor_result",
            "--payload", json.dumps({"threat_name": "cron_persistence"}),
        ]) == 0
        data = json_output(capsys)
        assert data["triggered_by"] == "event"
        assert data["runs"][0]["step_index"] == 0

    def test_run_reports_a_trigger_that_never_fires(self, tmp_path, capsys):
        from trimum_core.cli import main

        root = self._root(tmp_path)
        assert main([
            "workflow", "run", "demo",
            "--root", str(root),
            "--event", "nope.event",
            "--timeout", "0.3",
        ]) == 1
        assert "no run triggered" in capsys.readouterr().err

    @staticmethod
    def _shared_event(root: Path) -> Path:
        """一个 root 里的三份 workflow：good / bad 听同一事件，quiet 听另一个。"""
        bodies = {
            "good": "id: good\nsteps:\n"
                    "  - trigger: {event_type: security.monitor_result}\n"
                    "    execute:\n"
                    "      - agent_type: shell\n        instruction: echo good\n",
            "bad": "id: bad\nsteps:\n"
                   "  - trigger: {event_type: security.monitor_result}\n"
                   "    execute:\n"
                   "      - agent_type: trm-agent\n        instruction: think\n",
            "quiet": "id: quiet\nsteps:\n"
                     "  - trigger: {event_type: system.heartbeat}\n"
                     "    execute:\n"
                     "      - agent_type: shell\n        instruction: echo quiet\n",
        }
        for name, body in bodies.items():
            (root / name).mkdir(parents=True)
            (root / name / "workflow.yaml").write_text(body, encoding="utf-8")
        return root

    def test_event_run_answers_only_for_the_named_workflow(self, tmp_path, capsys):
        """事件是广播的：顺带跑掉的别的 workflow 如实汇报，但不算进本命令的成败。"""
        from trimum_core.cli import main

        root = self._shared_event(tmp_path / "workflows")
        assert main([
            "--json", "workflow", "run", "good", "--root", str(root),
            "--event", "security.monitor_result",
        ]) == 0
        data = json_output(capsys)
        assert [run["workflow_id"] for run in data["runs"]] == ["good"]
        assert data["runs"][0]["status"] == "completed"
        assert data["other_triggered"] == ["bad"]

    def test_event_run_says_so_when_only_other_workflows_fire(self, tmp_path, capsys):
        from trimum_core.cli import main

        root = self._shared_event(tmp_path / "workflows")
        assert main([
            "workflow", "run", "quiet", "--root", str(root),
            "--event", "security.monitor_result",
        ]) == 1
        err = capsys.readouterr().err
        assert "was not triggered" in err and "bad, good" in err

    def test_unknown_workflow(self, tmp_path, capsys):
        from trimum_core.cli import main

        assert main(["workflow", "run", "nope", "--root", str(self._root(tmp_path))]) == 1
        assert "unknown workflow" in capsys.readouterr().err

    def test_enable_materializes_a_builtin(self, tmp_path, capsys):
        from trimum_core.cli import main

        root = tmp_path / "workflows"
        assert main([
            "workflow", "enable", "threat-cron-audit",
            "--root", str(root), "--yes",
        ]) == 0
        capsys.readouterr()
        target = root / "threat-cron-audit" / "workflow.yaml"
        assert target.exists()
        loaded = WorkflowDefV2.load_yaml(target)
        assert workflow_enabled(loaded) is True

        # 落盘之后它只是普通的文件 workflow，而且同名时压过内置那份
        assert main(["--json", "workflow", "list", "--all", "--root", str(root)]) == 0
        data = json_output(capsys)
        by_id = {item["id"]: item for item in data["workflows"]}
        assert by_id["threat-cron-audit"]["source"] == "file"
        assert by_id["threat-cron-audit"]["enabled"] is True

        # 再 enable 一次会拒绝覆盖
        assert main([
            "workflow", "enable", "threat-cron-audit",
            "--root", str(root), "--yes",
        ]) == 1

    def test_enable_refuses_local_workflows(self, tmp_path):
        from trimum_core.cli import main

        assert main([
            "workflow", "enable", "demo", "--root", str(self._root(tmp_path)), "--yes",
        ]) == 1
