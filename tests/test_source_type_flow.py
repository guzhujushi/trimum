"""P1 收尾：source_type 流转 + AgentLoop 步骤状态判定。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.agent_loop import AgentLoop
from trimum_core.models import (
    Action,
    ExecuteRequest,
    ExecuteResponse,
    RiskLevel,
    SourceType,
    ToolType,
)
from trimum_core.security_rule import SecurityRule
from trimum_core.tool_gateway import ToolGateway


class FakeConsole:
    """只记录调用的最小 console 替身，避免测试触碰 stdin。"""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _recorder(*args, **kwargs):
            self.calls.append((name, args))
            return True

        return _recorder


class TestSourceTypeFlow:
    @pytest.mark.asyncio
    async def test_gateway_forwards_source_type_to_security_rule(self):
        seen = {}

        class Rule:
            async def can_execute(self, agent_id, command, sandbox="default", resource_ctx=None, source_type=None):
                seen["source_type"] = source_type
                return None

        gw = ToolGateway(security_rule=Rule())
        req = ExecuteRequest(
            tool=ToolType.SHELL,
            args=["echo", "hi"],
            agent_id="t",
            source_type=SourceType.HUMAN,
            skip_cwd_check=True,
        )
        await gw.execute(req)
        assert seen["source_type"] == SourceType.HUMAN

    @pytest.mark.asyncio
    async def test_security_rule_forwards_source_type_to_policy(self):
        seen = {}

        class Policy:
            def evaluate(self, command, source_type=None):
                seen["source_type"] = source_type
                return RiskLevel.LOW, Action.AUTO, "ok"

        rule = SecurityRule(policy_engine=Policy(), enforce_resource_limits=False)
        result = await rule.can_execute("t", "echo hi", source_type=SourceType.AI)
        assert seen["source_type"] == SourceType.AI
        assert result.action == "allow"

    def test_trm_exec_marks_human_source(self, monkeypatch):
        from trimum_core.cli.commands import exec as exec_cmd

        captured = {}

        class FakeGateway:
            def __init__(self, *args, **kwargs):
                pass

            async def execute(self, request):
                captured["request"] = request
                return ExecuteResponse(status="allowed", output="hi", exit_code=0)

        monkeypatch.setattr(
            "trimum_core.tool_gateway.ToolGateway", FakeGateway, raising=True
        )
        rc = exec_cmd.handler(
            type("Args", (), {"command": ["echo", "hi"], "agent": "cli", "timeout": 5.0, "json": True, "quiet": False})()
        )
        assert rc == 0
        assert captured["request"].source_type == SourceType.HUMAN


class TestAgentLoopStepStatus:
    @pytest.mark.asyncio
    async def test_allowed_response_is_reported_as_ok(self):
        class Gateway:
            async def execute(self, request):
                return ExecuteResponse(
                    status="allowed", output="hi", exit_code=0, action=Action.AUTO
                )

        console = FakeConsole()
        loop = AgentLoop(gateway=Gateway(), console=console, agent_name="test-agent")
        step = await loop._execute_step({"name": "n", "command": "echo hi", "risk": "low"})

        assert step["status"] == "ok"
        assert step["gateway_status"] == "allowed"
        assert not [c for c in console.calls if c[0] == "warning"]

    @pytest.mark.asyncio
    async def test_confirmed_response_is_reported_as_ok(self):
        class Gateway:
            async def execute(self, request):
                return ExecuteResponse(
                    status="confirmed", output="hi", exit_code=0, action=Action.CONFIRM
                )

        loop = AgentLoop(gateway=Gateway(), console=FakeConsole(), agent_name="test-agent")
        step = await loop._execute_step({"name": "n", "command": "echo hi", "risk": "low"})

        assert step["status"] == "ok"
        assert step["gateway_status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_error_response_is_reported_as_error(self):
        class Gateway:
            async def execute(self, request):
                return ExecuteResponse(
                    status="error", error="boom", exit_code=1, action=Action.AUTO
                )

        console = FakeConsole()
        loop = AgentLoop(gateway=Gateway(), console=console, agent_name="test-agent")
        step = await loop._execute_step({"name": "n", "command": "echo hi", "risk": "low"})

        assert step["status"] == "error"
        assert step["gateway_status"] == "error"
        assert [c for c in console.calls if c[0] == "warning"]