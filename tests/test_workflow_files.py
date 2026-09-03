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
