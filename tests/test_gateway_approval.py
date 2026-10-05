"""ToolGateway 非交互 confirm 审批接线测试（cfm1b：A3 声明式放行 + fail-closed）。

参照 tests/test_tool_gateway_security_rule.py 的搭法；全部 tmp_path 隔离，
不许碰真 ~/.trimum。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from trimum_core.approvals import ApprovalStore
from trimum_core.models import (
    Action,
    ExecuteRequest,
    RiskLevel,
    SourceType,
    ToolType,
)
from trimum_core.security_rule import DecisionResult
from trimum_core.tool_gateway import ToolGateway


class FakeRule:
    """最小 SecurityRule 替身：记录调用并返回预设决策。"""

    def __init__(self, decision: DecisionResult | None = None, error: Exception | None = None):
        self.decision = decision
        self.error = error
        self.calls: list[dict] = []

    async def can_execute(
        self, agent_id, command, sandbox="default", resource_ctx=None, source_type=None
    ):
        self.calls.append({
            "agent_id": agent_id,
            "command": command,
            "sandbox": sandbox,
            "source_type": source_type,
        })
        if self.error is not None:
            raise self.error
        return self.decision


class FakeDispatcherRegistry:
    """记录调用的假分发器：dispatch 被调就记一笔并返回成功响应。"""

    def __init__(self):
        self.dispatched: list[str] = []

    def get(self, tool_type):
        return None

    async def dispatch(self, request):
        from trimum_core.models import ExecuteResponse

        self.dispatched.append(" ".join(request.args))
        return ExecuteResponse(status="success", output="ok", exit_code=0)


def _confirm_gateway(
    tmp_path: Path, enable_audit: bool = False, **kwargs
) -> tuple[ToolGateway, FakeDispatcherRegistry]:
    """Layer 1/2.5/4 全部绕过，让 SecurityRule 稳定给出 CONFIRM 决策。"""
    policy = type("ConfirmPolicy", (), {
        "evaluate": lambda self, command, source_type=None: (
            RiskLevel.LOW, Action.AUTO, "fine"
        ),
    })()
    registry = FakeDispatcherRegistry()
    gw = ToolGateway(
        policy_engine=policy,
        dispatcher_registry=registry,
        security_rule=FakeRule(DecisionResult("confirm", "needs approval", risk_level="medium")),
        enable_cwd_jail=False,
        enable_credential_redact=False,
        enable_audit=enable_audit,
        enable_jit_auth=False,
        work_dir=str(tmp_path),
        **kwargs,
    )
    gw.sec_monitor = None
    return gw, registry


def _request(command: str = "echo hello", cwd: str | None = None) -> ExecuteRequest:
    return ExecuteRequest(
        tool=ToolType.SHELL,
        args=command.split(),
        agent_id="tester",
        source_type=SourceType.AI,
        skip_cwd_check=True,
        cwd=cwd,
    )


def _pending_files(store: ApprovalStore) -> list[Path]:
    if not store.directory.is_dir():
        return []
    files = []
    for path in store.directory.glob("*.json"):
        if path.is_file():
            files.append(path)
    return files


class TestGatewayApprovalWiring:
    @pytest.mark.asyncio
    async def test_no_store_keeps_legacy_behavior(self, tmp_path):
        """回归红线：不传 approval_store ⇒ 非交互 confirm 照旧执行。"""
        gw, registry = _confirm_gateway(tmp_path)
        assert gw._approval_store is None
        resp = await gw.execute(_request())
        assert resp.status != "approval_required"
        assert registry.dispatched == ["echo hello"]

    @pytest.mark.asyncio
    async def test_noninteractive_confirm_creates_pending_and_blocks(self, tmp_path):
        store = ApprovalStore(directory=tmp_path / "approvals")
        gw, registry = _confirm_gateway(tmp_path, approval_store=store, enable_audit=True)
        resp = await gw.execute(_request())
        assert resp.status == "approval_required"
        assert resp.exit_code == 1
        assert resp.action == Action.CONFIRM
        assert "trm approve" in (resp.error or "")
        # 命令没有真的执行
        assert registry.dispatched == []
        # 目录里多出一个 pending 文件
        pending = _pending_files(store)
        assert len(pending) == 1
        data = json.loads(pending[0].read_text(encoding="utf-8"))
        assert data["status"] == "pending"
        assert data["command"] == "echo hello"
        assert f"trm approve {data['id']}" in (resp.error or "")
        # 审计留痕
        assert "approval_required" in [e.event_type for e in gw._audit_log]

    @pytest.mark.asyncio
    async def test_preauthorized_rule_allows(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        store = ApprovalStore(directory=tmp_path / "approvals")

        class Cfg:
            def get(self, key, default=None):
                assert key == "approvals.allow"
                return [{"tool": "shell", "cwd": str(tmp_path)}]

        gw, registry = _confirm_gateway(
            tmp_path,
            approval_store=ApprovalStore(directory=tmp_path / "approvals", config=Cfg()),
        )
        resp = await gw.execute(_request(cwd=str(sub)))
        assert resp.status in ("allowed", "success")
        assert resp.action != Action.CONFIRM
        assert "[preauthorized]" in (resp.reason or "")
        assert registry.dispatched == ["echo hello"]
        # 没落 pending
        assert _pending_files(store) == []

    @pytest.mark.asyncio
    async def test_preauthorized_cwd_prefix_miss(self, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        store = ApprovalStore(directory=tmp_path / "approvals")

        class Cfg:
            def get(self, key, default=None):
                assert key == "approvals.allow"
                return [{"tool": "shell", "cwd": str(tmp_path / "sub")}]

        gw, registry = _confirm_gateway(
            tmp_path,
            approval_store=ApprovalStore(directory=tmp_path / "approvals", config=Cfg()),
        )
        resp = await gw.execute(_request(cwd=str(other)))
        assert resp.status == "approval_required"
        assert registry.dispatched == []
        assert len(_pending_files(store)) == 1

    @pytest.mark.asyncio
    async def test_interactive_still_prompts(self, tmp_path):
        """interactive=True 走既有 _confirm_interactively 路径，不受新分支影响。"""
        gw, registry = _confirm_gateway(tmp_path, interactive=True)
        prompts: list[str] = []

        async def _confirm_interactively(self, *, request, execution_id, cmd_str, risk, reason):
            prompts.append(cmd_str)
            return None  # 用户确认 ⇒ 继续执行

        gw._confirm_interactively = _confirm_interactively.__get__(gw, ToolGateway)
        resp = await gw.execute(_request("echo interactive"))
        assert prompts == ["echo interactive"]
        assert resp.status in ("allowed", "success")
        assert resp.action == Action.AUTO
        assert "User confirmed" in (resp.reason or "")
        assert registry.dispatched == ["echo interactive"]

        # 拒绝分支
        prompts.clear()
        registry.dispatched.clear()

        async def _deny_interactively(self, *, request, execution_id, cmd_str, risk, reason):
            prompts.append(cmd_str)
            from trimum_core.models import ExecuteResponse

            return ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                error="User cancelled",
                exit_code=1,
                risk=risk,
                action=Action.DENY,
                reason="User declined confirmation prompt",
            )

        gw._confirm_interactively = _deny_interactively.__get__(gw, ToolGateway)
        resp = await gw.execute(_request("echo no"))
        assert prompts == ["echo no"]
        assert resp.status == "denied"
        assert registry.dispatched == []
