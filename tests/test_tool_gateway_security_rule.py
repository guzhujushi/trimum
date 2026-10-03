"""ToolGateway Layer 2.5 — SecurityRule 接入测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from trimum_core.models import (
    Action,
    ExecuteRequest,
    RiskLevel,
    SourceType,
    ToolType,
    TRMErrorCode,
    TrimumError,
)
from trimum_core.security_rule import DecisionResult, SecurityRule
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


def _request(command: str = "echo hello") -> ExecuteRequest:
    return ExecuteRequest(
        tool=ToolType.SHELL,
        args=command.split(),
        agent_id="tester",
        source_type=SourceType.AI,
        skip_cwd_check=True,
    )


def _audit_types(gateway: ToolGateway) -> list[str]:
    return [event.event_type for event in gateway._audit_log]


class TestSecurityRuleWiring:
    @pytest.mark.asyncio
    async def test_gateway_builds_default_security_rule(self):
        """未显式注入时，网关自动构造 SecurityRule（Layer 2.5 生效）。"""
        gw = ToolGateway()
        assert isinstance(gw.security_rule, SecurityRule)

    @pytest.mark.asyncio
    async def test_gateway_can_disable_security_rule(self):
        gw = ToolGateway(enable_security_rule=False)
        assert gw.security_rule is None

    @pytest.mark.asyncio
    async def test_explicit_rule_is_used(self):
        rule = FakeRule(DecisionResult("allow", "fine"))
        gw = ToolGateway(security_rule=rule)
        resp = await gw.execute(_request())
        assert resp.status in ("allowed", "success")
        assert rule.calls and rule.calls[0]["agent_id"] == "tester"

    @pytest.mark.asyncio
    async def test_deny_blocks_execution_and_audits(self):
        rule = FakeRule(DecisionResult("deny", "critical risk: rm -rf /", risk_level="critical"))
        gw = ToolGateway(security_rule=rule)
        resp = await gw.execute(_request())
        assert resp.status == "denied"
        assert resp.action == Action.DENY
        assert resp.exit_code == 1
        assert resp.risk == RiskLevel.CRITICAL
        assert "critical risk" in resp.error
        assert "security_blocked" in _audit_types(gw)

    @pytest.mark.asyncio
    async def test_confirm_sets_confirm_action(self):
        rule = FakeRule(
            DecisionResult("confirm", "behavior anomaly detected", risk_level="high")
        )
        gw = ToolGateway(security_rule=rule)
        resp = await gw.execute(_request())
        assert resp.action == Action.CONFIRM
        assert resp.status == "confirmed"
        assert "behavior anomaly" in (resp.reason or "")

    @pytest.mark.asyncio
    async def test_interactive_confirm_declined(self):
        rule = FakeRule(DecisionResult("confirm", "cross-tool access", risk_level="medium"))
        gw = ToolGateway(security_rule=rule, interactive=True)

        async def _deny(*args, **kwargs) -> bool:
            return False

        gw._prompt_confirm = _deny
        resp = await gw.execute(_request())
        assert resp.status == "denied"
        assert "User cancelled" in resp.error
        assert "user_cancelled" in _audit_types(gw)

    @pytest.mark.asyncio
    async def test_interactive_confirm_accepted_runs_command(self):
        rule = FakeRule(DecisionResult("confirm", "cross-tool access", risk_level="medium"))
        gw = ToolGateway(security_rule=rule, interactive=True)

        async def _allow(*args, **kwargs) -> bool:
            return True

        gw._prompt_confirm = _allow
        resp = await gw.execute(_request("echo layer25"))
        assert resp.status in ("allowed", "success")
        assert resp.action == Action.AUTO

    @pytest.mark.asyncio
    async def test_confirm_fails_closed_when_stdin_is_not_a_tty(self, monkeypatch):
        """管道还开着时 input() 会一直块住 → 非 TTY 必须直接拒绝（fail closed）。"""
        import trimum_core.tool_gateway as gateway_module

        class NotATty:
            def isatty(self):
                return False

            def readline(self, *args):
                return ""

        monkeypatch.setattr(gateway_module.sys, "stdin", NotATty())
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")
        gw = ToolGateway(security_rule=FakeRule())
        assert (
            await gw._prompt_confirm("rm -rf /", RiskLevel.CRITICAL, "why", "terminal")
            is False
        )

    @pytest.mark.asyncio
    async def test_confirm_reads_the_answer_on_a_tty(self, monkeypatch):
        import trimum_core.tool_gateway as gateway_module

        class Tty:
            def isatty(self):
                return True

        monkeypatch.setattr(gateway_module.sys, "stdin", Tty())
        gw = ToolGateway(security_rule=FakeRule())

        monkeypatch.setattr("builtins.input", lambda prompt="": "y")
        assert await gw._prompt_confirm("echo hi", RiskLevel.MEDIUM, "why", "terminal") is True

        monkeypatch.setattr("builtins.input", lambda prompt="": "n")
        assert await gw._prompt_confirm("echo hi", RiskLevel.MEDIUM, "why", "terminal") is False

    @pytest.mark.asyncio
    async def test_resource_limit_error_becomes_deny(self):
        rule = FakeRule(error=TrimumError(TRMErrorCode.RESOURCE_LIMIT_EXCEEDED, message="CPU 超限"))
        gw = ToolGateway(security_rule=rule)
        resp = await gw.execute(_request())
        assert resp.status == "denied"
        assert resp.risk == RiskLevel.HIGH
        assert "CPU 超限" in resp.error
        assert "security_blocked" in _audit_types(gw)

    @pytest.mark.asyncio
    async def test_unexpected_error_fails_open(self):
        rule = FakeRule(error=RuntimeError("boom"))
        gw = ToolGateway(security_rule=rule)
        resp = await gw.execute(_request())
        assert resp.status in ("allowed", "success")


class TestBehaviorMonitorIntegration:
    @pytest.mark.asyncio
    async def test_anomaly_triggers_confirm(self):
        class AnomalyMonitor:
            async def check_command(self, agent_id, command, sandbox="default"):
                return "anomaly"

        rule = SecurityRule(
            behavior_monitor=AnomalyMonitor(),
            enforce_resource_limits=False,
        )
        gw = ToolGateway(security_rule=rule)
        resp = await gw.execute(_request())
        assert resp.action == Action.CONFIRM

    @pytest.mark.asyncio
    async def test_resource_limits_disabled_skips_controller(self):
        """网关场景：enforce_resource_limits=False 时不查资源阈值。"""
        class FailingController:
            def __init__(self):
                self.calls = 0

            async def get_usage(self, agent_id):
                self.calls += 1
                return None

            async def check_limits(self, agent_id, usage=None):
                from trimum_core.resource_controller import ResourceCheckResult, Violation
                return ResourceCheckResult(
                    allowed=False,
                    violations=[Violation("max_memory_mb", 512, 4096, "内存超限")],
                )

        rule = SecurityRule(enforce_resource_limits=False)
        controller = FailingController()
        rule.set_resource_controller(controller)
        result = await rule.can_execute("tester", "echo hello")
        assert result.action in ("allow", "confirm")
        assert controller.calls == 0