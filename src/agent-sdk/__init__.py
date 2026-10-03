"""
trimum Agent SDK

基于 Pydantic AI 构建，包装 trimum 的 Tool Gateway + Security Agent 权限层。

用法:
    from agent_sdk import TrimumAgent
    from pydantic_ai import Agent

    agent = TrimumAgent(
        base_agent=Agent('openai:gpt-4o', system_prompt="你是一个 AI Shell 助手"),
        tool_gateway=tool_gateway,
        security_agent=security_agent,
        agent_id="ai-shell",
    )

    result = await agent.run("查看磁盘使用")
"""

from .trimum_agent import TrimumAgent

__all__ = ["TrimumAgent"]
