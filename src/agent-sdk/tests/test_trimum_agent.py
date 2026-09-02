"""Agent SDK 基础测试。"""

from agent_sdk import TrimumAgent
from pydantic_ai import Agent


class TestTrimumAgent:
    """测试 TrimumAgent 初始化和属性代理。"""

    def test_init_no_security(self):
        """不传 security/gateway 时，TrimumAgent 应该能正常创建。"""
        base = Agent('test', system_prompt="测试助手")
        agent = TrimumAgent(base_agent=base, agent_id="test-agent")

        assert agent is not None
        assert agent.name == "test-agent"
        assert agent.base_agent is base
        assert agent._gateway is None
        assert agent._security is None

    def test_repr(self):
        """__repr__ 应该清晰反映状态。"""
        base = Agent('test', system_prompt="test")
        agent = TrimumAgent(base_agent=base, agent_id="my-agent")
        r = repr(agent)
        assert "my-agent" in r
        assert "gateway=no" in r
        assert "security=no" in r

    def test_run_sync_basic(self):
        """使用 test model 的 run_sync 应该正常工作。"""
        base = Agent('test', system_prompt="你是一个助手")
        agent = TrimumAgent(base_agent=base)

        result = agent.run_sync("你好")
        assert result is not None
        assert result.output is not None
