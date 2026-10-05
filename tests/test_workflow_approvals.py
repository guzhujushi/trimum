"""cfm1c：workflow 定义声明放行规则（顶层/节点级 approvals.allow → 网关同一路径）。

参照 tests/test_gateway_approval.py 的搭法；全部 tmp_path 隔离，不许碰真 ~/.trimum。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from trimum_core.approvals import ApprovalStore, match_allow_rules
from trimum_core.models import (
    Action,
    RiskLevel,
    SourceType,
    ToolType,
)
from trimum_core.security_rule import DecisionResult
from trimum_core.tool_gateway import ToolGateway
from trimum_core.workflow_engine import NodeDefinition, WorkflowDefV2
from trimum_core.workflow_runtime import WorkflowRuntime
from trimum_core.event_bus import EventBus


class FakeRule:
    """最小 SecurityRule 替身：稳定给出 CONFIRM 决策。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def can_execute(self, agent_id, command, sandbox="default", resource_ctx=None, source_type=None):
        self.calls.append({"agent_id": agent_id, "command": command})
        return DecisionResult("confirm", "needs approval", risk_level="medium")


class FakeDispatcherRegistry:
    def __init__(self):
        self.dispatched: list[str] = []

    def get(self, tool_type):
        return None

    async def dispatch(self, request):
        from trimum_core.models import ExecuteResponse

        self.dispatched.append(" ".join(request.args))
        return ExecuteResponse(status="success", output="ok", exit_code=0)


def _confirm_gateway(tmp_path: Path, **kwargs) -> tuple[ToolGateway, FakeDispatcherRegistry]:
    policy = type("ConfirmPolicy", (), {
        "evaluate": lambda self, command, source_type=None: (RiskLevel.LOW, Action.AUTO, "fine"),
    })()
    registry = FakeDispatcherRegistry()
    gw = ToolGateway(
        policy_engine=policy,
        dispatcher_registry=registry,
        security_rule=FakeRule(),
        enable_cwd_jail=False,
        enable_credential_redact=False,
        enable_jit_auth=False,
        work_dir=str(tmp_path),
        **kwargs,
    )
    gw.sec_monitor = None
    return gw, registry


def _pending_files(store: ApprovalStore) -> list[Path]:
    if not store.directory.is_dir():
        return []
    return [p for p in store.directory.glob("*.json") if p.is_file()]


class TestMatchAllowRules:
    def test_match_allow_rules_basic(self):
        # 精确命中
        assert match_allow_rules([{"tool": "shell", "cwd": "/x"}], tool="shell", cwd="/x")
        # cwd 前缀命中
        assert match_allow_rules([{"tool": "shell", "cwd": "/x"}], tool="shell", cwd="/x/sub/deep")
        # tool 空 = 任意
        assert match_allow_rules([{"cwd": "/x"}], tool="shell", cwd="/x")
        # cwd 空 = 任意
        assert match_allow_rules([{"tool": "shell"}], tool="shell", cwd="")
        assert match_allow_rules([{"tool": "shell"}], tool="shell", cwd="/anywhere")
        # 不命中
        assert not match_allow_rules([{"tool": "shell", "cwd": "/x"}], tool="shell", cwd="/y")
        assert not match_allow_rules([{"tool": "browser", "cwd": "/x"}], tool="shell", cwd="/x")
        # 非 list ⇒ False
        assert not match_allow_rules(None)
        assert not match_allow_rules({"tool": "shell"})
        assert not match_allow_rules("shell")
        # 元素混入非 dict ⇒ 只认 dict
        assert match_allow_rules([1, "x", None, {"tool": "shell", "cwd": "/x"}], tool="shell", cwd="/x")
        assert not match_allow_rules([1, "x", None], tool="shell", cwd="/x")


def _write_wf(tmp_path: Path, text: str) -> Path:
    f = tmp_path / "workflow.yaml"
    f.write_text(text, encoding="utf-8")
    return f


class TestWorkflowParse:
    def test_workflow_yaml_approvals_parse(self, tmp_path):
        text = (
            "id: wf1\n"
            "name: demo\n"
            "steps:\n"
            "  - trigger:\n"
            "      event_type: workflow.request\n"
            "    execute:\n"
            "      - agent_type: shell\n"
            "        instruction: echo hi\n"
            "        approvals:\n"
            "          allow:\n"
            "            - {tool: shell, cwd: /node}\n"
            "approvals:\n"
            "  allow:\n"
            "    - {tool: shell, cwd: /top}\n"
        )
        wf = WorkflowDefV2.load_yaml(_write_wf(tmp_path, text))
        # 顶层解析
        assert wf.approvals == {"allow": [{"tool": "shell", "cwd": "/top"}]}
        # 节点级覆盖顶层
        node_rules = wf.resolve_approval_rules(wf.steps[0].execute[0])
        assert node_rules == [{"tool": "shell", "cwd": "/node"}]


class TestToWorkflowDefinition:
    def test_to_workflow_definition_carries_rules(self, tmp_path):
        text = (
            "id: wf2\n"
            "steps:\n"
            "  - trigger:\n"
            "      event_type: workflow.request\n"
            "    execute:\n"
            "      - agent_type: shell\n"
            "        instruction: echo hi\n"
            "      - agent_type: shell\n"
            "        instruction: echo bye\n"
            "approvals:\n"
            "  allow:\n"
            "    - {tool: shell, cwd: /top}\n"
            "    - not_a_dict\n"
        )
        wf = WorkflowDefV2.load_yaml(_write_wf(tmp_path, text))
        nodes = wf.to_workflow_definition().nodes
        # 声明了 approvals（无节点级）⇒ 用顶层，过滤掉非 dict
        assert nodes[0].config["approval_rules"] == [{"tool": "shell", "cwd": "/top"}]
        # 没声明节点级 approvals 但顶层有 ⇒ 仍然带上顶层规则
        assert nodes[1].config["approval_rules"] == [{"tool": "shell", "cwd": "/top"}]

        # 完全没声明 approvals ⇒ config 里没有 approval_rules 键
        text2 = (
            "id: wf3\n"
            "steps:\n"
            "  - trigger:\n"
            "      event_type: workflow.request\n"
            "    execute:\n"
            "      - agent_type: shell\n"
            "        instruction: echo hi\n"
        )
        wf3 = WorkflowDefV2.load_yaml(_write_wf(tmp_path, text2))
        node3 = wf3.to_workflow_definition().nodes[0]
        assert "approval_rules" not in node3.config
        assert node3.config.get("approval_rules") is None


class TestShellNodePreauthorized:
    @pytest.mark.asyncio
    async def test_shell_node_preauthorized_by_workflow(self, tmp_path):
        store = ApprovalStore(directory=tmp_path / "approvals")
        gw, registry = _confirm_gateway(
            tmp_path,
            approval_store=store,
        )
        runtime = WorkflowRuntime(EventBus(), gateway=gw)

        # 声明了 approval_rules，前缀命中（cwd 用 str(tmp_path)）
        node_ok = NodeDefinition(
            id="step_0_task_0",
            label="echo hello",
            handler="shell",
            config={
                "instruction": "echo hello",
                "approval_rules": [{"tool": "shell", "cwd": str(tmp_path)}],
            },
        )
        result = await runtime._handle_shell_node("wf", node_ok, {})
        assert result["success"] is True
        assert registry.dispatched == ["echo hello"]
        # 没落 pending
        assert _pending_files(store) == []

        # 对照：没有 approval_rules ⇒ 被 pending 拦住 → 节点 FAILED
        store2 = ApprovalStore(directory=tmp_path / "approvals2")
        gw2, registry2 = _confirm_gateway(tmp_path, approval_store=store2)
        runtime2 = WorkflowRuntime(EventBus(), gateway=gw2)
        node_no = NodeDefinition(
            id="step_0_task_0",
            label="echo hello",
            handler="shell",
            config={"instruction": "echo hello"},
        )
        with pytest.raises(Exception) as exc:
            await runtime2._handle_shell_node("wf", node_no, {})
        assert "TOOL_EXECUTION_FAILED" in str(exc.value) or "failed" in str(exc.value).lower()
        assert registry2.dispatched == []
        assert len(_pending_files(store2)) == 1
