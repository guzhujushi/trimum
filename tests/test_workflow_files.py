"""Tests for workflow file-ization — load_yaml + load_from_dir."""

import tempfile
from pathlib import Path

import pytest

from trimum_core.workflow_engine import WorkflowDefV2, AgentTask, WorkflowStep, WorkflowStepCondition


SAMPLE_YAML = """
id: blog-deploy
name: 博客部署
description: Git push → SSH restart → Health check
steps:
  - trigger:
      event_type: workflow.request
      condition: 'payload.get("action") == "deploy"'
    execute:
      - agent_type: shell
        instruction: git push origin main
        timeout_seconds: 30
      - agent_type: shell
        instruction: ssh root@server "systemctl restart blog"
        timeout_seconds: 10
  - trigger:
      event_type: workflow.completed
    execute:
      - agent_type: http
        instruction: check health endpoint
        timeout_seconds: 15
config:
  notify_on_failure: true
"""

SIMPLE_YAML = """
id: simple
name: 简单工作流
steps:
  - trigger:
      event_type: system.heartbeat
    execute:
      - agent_type: system-monitor
        instruction: check CPU
        timeout_seconds: 30
"""


class TestLoadYaml:
    """WorkflowDefV2.load_yaml() 测试。"""

    def test_load_basic(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.yaml"
            p.write_text(SAMPLE_YAML, encoding="utf-8")
            wf = WorkflowDefV2.load_yaml(p)
            assert wf.id == "blog-deploy"
            assert wf.name == "博客部署"
            assert len(wf.steps) == 2
            assert wf.config.get("notify_on_failure") is True

    def test_steps_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.yaml"
            p.write_text(SAMPLE_YAML, encoding="utf-8")
            wf = WorkflowDefV2.load_yaml(p)

            # Step 0
            step0 = wf.steps[0]
            assert step0.trigger.event_type == "workflow.request"
            assert step0.trigger.condition == 'payload.get("action") == "deploy"'
            assert len(step0.execute) == 2
            assert step0.execute[0].agent_type == "shell"
            assert step0.execute[0].timeout_seconds == 30
            assert step0.execute[1].agent_type == "shell"

            # Step 1
            step1 = wf.steps[1]
            assert step1.trigger.event_type == "workflow.completed"
            assert step1.execute[0].agent_type == "http"

    def test_simple_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "simple.yaml"
            p.write_text(SIMPLE_YAML, encoding="utf-8")
            wf = WorkflowDefV2.load_yaml(p)
            assert wf.id == "simple"
            assert len(wf.steps) == 1
            assert wf.steps[0].trigger.event_type == "system.heartbeat"

    def test_to_workflow_definition(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.yaml"
            p.write_text(SIMPLE_YAML, encoding="utf-8")
            wf = WorkflowDefV2.load_yaml(p)
            wf_def = wf.to_workflow_definition()
            assert wf_def.id == "simple"
            assert len(wf_def.nodes) >= 1

    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "nope.yaml"
            with pytest.raises(FileNotFoundError):
                WorkflowDefV2.load_yaml(p)

    def test_load_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.yaml"
            p.write_text("not valid: yaml: [[[", encoding="utf-8")
            with pytest.raises(Exception):
                WorkflowDefV2.load_yaml(p)


class TestLoadFromDir:
    """WorkflowDefV2.load_from_dir() 测试。"""

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            wfs = WorkflowDefV2.load_from_dir(tmp)
            assert wfs == []

    def test_single_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf_dir = Path(tmp) / "blog-deploy"
            wf_dir.mkdir()
            (wf_dir / "workflow.yaml").write_text(SAMPLE_YAML, encoding="utf-8")
            wfs = WorkflowDefV2.load_from_dir(tmp)
            assert len(wfs) == 1
            assert wfs[0].id == "blog-deploy"

    def test_multiple_workflows(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in [("wf1", SAMPLE_YAML), ("wf2", SIMPLE_YAML)]:
                d = Path(tmp) / name
                d.mkdir()
                (d / "workflow.yaml").write_text(content, encoding="utf-8")
            wfs = WorkflowDefV2.load_from_dir(tmp)
            assert len(wfs) == 2
            ids = {w.id for w in wfs}
            assert "blog-deploy" in ids
            assert "simple" in ids

    def test_workflow_yml_fallback(self):
        """同时支持 .yaml 和 .yml 扩展名。"""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "demo"
            d.mkdir()
            (d / "workflow.yml").write_text(SIMPLE_YAML.replace("id: simple", "id: demo"), encoding="utf-8")
            wfs = WorkflowDefV2.load_from_dir(tmp)
            assert len(wfs) == 1
            assert wfs[0].id == "demo"

    def test_skip_non_workflow_dirs(self):
        """没有 workflow.yaml 的目录应该被跳过。"""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "not-a-workflow"
            d.mkdir()
            (d / "random.txt").write_text("hello", encoding="utf-8")
            wfs = WorkflowDefV2.load_from_dir(tmp)
            assert wfs == []

    def test_malformed_yaml_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "broken"
            d.mkdir()
            (d / "workflow.yaml").write_text("bad: [[[ yaml", encoding="utf-8")
            wfs = WorkflowDefV2.load_from_dir(tmp)
            assert wfs == []

    def test_default_path(self, monkeypatch):
        """默认路径 ~/.trimum/workflows/ 可以加载真实文件。"""
        import trimum_core.workflow_engine as we
        orig = WorkflowDefV2.load_from_dir
        try:
            wfs = WorkflowDefV2.load_from_dir(None)  # 用默认路径
            # 不断言具体数量——前面的测试可能已经创建了文件
            assert isinstance(wfs, list)
        finally:
            pass


class TestRoundtrip:
    """YAML → WorkflowDefV2 → WorkflowDefinition 完整链路。"""

    def test_full_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.yaml"
            p.write_text(SAMPLE_YAML, encoding="utf-8")
            wf_v2 = WorkflowDefV2.load_yaml(p)
            wf_def = wf_v2.to_workflow_definition()
            assert wf_def.id == "blog-deploy"
            assert len(wf_def.nodes) >= 2
            assert len(wf_def.edges) >= 1

class TestRunPersistence:
    """run 记录落盘 + 读取（G-2）：只在 tmp 下，不碰真机 ~/.trimum。"""

    def test_run_persists_and_loads(self, tmp_path):
        import asyncio

        from trimum_core.event_bus import EventBus
        from trimum_core.workflow_runtime import WorkflowRuntime

        yaml_file = tmp_path / "wf.yaml"
        yaml_file.write_text(SIMPLE_YAML, encoding="utf-8")
        runs_path = tmp_path / "workflow-runs.jsonl"
        bus = EventBus()
        runtime = WorkflowRuntime(bus, runs_path=runs_path)
        workflow = WorkflowDefV2.load_yaml(yaml_file)
        runtime.register(workflow, source="file")
        record = asyncio.run(runtime.run_now(workflow.id))

        runs = runtime.load_runs()
        assert any(r.get("run_id") == record.run_id for r in runs)
        got = runtime.get_run(record.run_id)
        assert got is not None
        assert got["run_id"] == record.run_id
        assert got["status"] == record.status
        assert runs_path.exists()

    def test_load_runs_skips_bad_lines(self, tmp_path):
        import json as _json
        from trimum_core.event_bus import EventBus
        from trimum_core.workflow_runtime import WorkflowRuntime

        runs_path = tmp_path / "workflow-runs.jsonl"
        good = _json.dumps({"run_id": "wf-x#all-0001", "status": "completed"})
        # 三行：截半的坏行 + 纯垃圾行 + 一条正常行；前面再垫一条正常行
        truncated = '{"run_id": "wf-x#all-0001", "status": "co'
        runs_path.write_text(
            '{"run_id": "wf-x#all-0000", "status": "completed"}\n'
            + truncated + "\n"
            + 'this is not json at all\n'
            + good + "\n",
            encoding="utf-8",
        )
        runtime = WorkflowRuntime(EventBus(), runs_path=runs_path)
        runs = runtime.load_runs()
        assert [r["run_id"] for r in runs] == [
            "wf-x#all-0000",
            "wf-x#all-0001",
        ]

    def test_cli_status_unknown_run_nonzero(self, tmp_path, monkeypatch):
        from trimum_core.cli import main

        # 把 TRIMUM_HOME 指到 tmp，status 去空的 <tmp>/workflow-runs.jsonl 找记录
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
        rc = main(["workflow", "status", "nope#all-0000"])
        assert rc != 0


class TestGetRunLooksPastTail:
    """回归：get_run 必须能查到落盘文件里早于尾部的 run（CLI 一次性进程场景）。"""

    def test_get_run_hits_non_tail_persisted_run(self, tmp_path):
        import json as _json
        from trimum_core.event_bus import EventBus
        from trimum_core.workflow_runtime import WorkflowRuntime

        runs_path = tmp_path / "workflow-runs.jsonl"
        runs_path.write_text(
            _json.dumps({"run_id": "a#all-0001", "status": "completed"}) + "\n"
            + _json.dumps({"run_id": "b#all-0002", "status": "completed"}) + "\n",
            encoding="utf-8",
        )
        runtime = WorkflowRuntime(EventBus(), runs_path=runs_path)

        got = runtime.get_run("a#all-0001")
        assert got is not None
        assert got["run_id"] == "a#all-0001"

        # 钉死 load_runs 的 limit 语义没被改：limit=1 只回最后一行
        tail = runtime.load_runs(limit=1)
        assert [r["run_id"] for r in tail] == ["b#all-0002"]

    def test_cli_status_finds_earlier_persisted_run(self, tmp_path, monkeypatch):
        import json as _json
        from trimum_core.cli import main
        from trimum_core.paths import trimum_path

        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
        runs_file = trimum_path("workflow-runs.jsonl")
        runs_file.parent.mkdir(parents=True, exist_ok=True)
        runs_file.write_text(
            _json.dumps({"run_id": "earlier#all-0001", "status": "completed"}) + "\n"
            + _json.dumps({"run_id": "later#all-0002", "status": "completed"}) + "\n",
            encoding="utf-8",
        )

        rc = main(["workflow", "status", "earlier#all-0001"])
        assert rc == 0

        rc_unknown = main(["workflow", "status", "missing#all-9999"])
        assert rc_unknown != 0
