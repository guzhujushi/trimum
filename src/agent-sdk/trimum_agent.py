"""
TrimumAgent — 在 Pydantic AI Agent 上包装 trimum 权限层。

核心设计：
- 不重写 Agent loop —— 直接复用 pydantic_ai.Agent 的 run_sync() / run()
- 在 tool 调用前插入 Security Agent 的 can_execute() 检查
- 执行走 Tool Gateway（已有双层权限检查：Policy Engine + Agent Manifest）
- 保持 pydantic_ai 的类型安全、结构化输出、模型切换等所有原生能力
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import RunContext


# ---------------------------------------------------------------------------
# TrimumAgent
# ---------------------------------------------------------------------------


class TrimumAgent:
    """Pydantic AI Agent 的 trimum 安全包装。

    把 Pydantic AI 的原生 Agent loop 与 trimum 的 Tool Gateway + Security Agent
    连接起来。Agent 编写者只需定义 tool 函数，权限层自动拦截。

    用法::

        from pydantic_ai import Agent
        from agent_sdk import TrimumAgent

        base = Agent('openai:gpt-4o', system_prompt="你是 trimum 助手")
        trimum_agent = TrimumAgent(
            base_agent=base,
            tool_gateway=tool_gateway_instance,
            security_agent=security_agent_instance,
            agent_id="my-agent",
        )
        result = await trimum_agent.run("查看磁盘")
    """

    def __init__(
        self,
        base_agent: PydanticAgent,
        tool_gateway: Optional[Any] = None,
        security_agent: Optional[Any] = None,
        agent_id: Optional[str] = None,
        agent_manifest: Optional[Any] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        self._base = base_agent
        self._gateway = tool_gateway
        self._security = security_agent
        self._agent_id = agent_id or f"agent-{uuid.uuid4().hex[:8]}"
        self._manifest = agent_manifest
        self._event_bus = event_bus

    # ── 属性代理（保持 pydantic_ai.Agent 的 API 可用） ──────────

    @property
    def name(self) -> str:
        base_name = getattr(self._base, "name", None)
        return base_name or self._agent_id

    @property
    def base_agent(self) -> PydanticAgent:
        return self._base

    # ── 运行接口 ──────────────────────────────────────────

    async def run(self, user_input: str, **kwargs: Any) -> Any:
        """运行 Agent，所有 tool 调用自动经过 Security Agent 检查。"""
        return await self._base.run(user_input, **kwargs)

    def run_sync(self, user_input: str, **kwargs: Any) -> Any:
        """同步方式运行 Agent。"""
        return self._base.run_sync(user_input, **kwargs)

    # ── 安全工具注册 ──────────────────────────────────────

    def tool(self, func=None, *, security_context: Optional[dict] = None):
        """注册一个 tool，自动包装 Security Agent 权限检查。

        用法::

            @trimum_agent.tool
            async def my_tool(ctx: RunContext, arg: str) -> str:
                return "result"

        或者带安全上下文:

            @trimum_agent.tool(security_context={"risk": "high"})
            async def risky_tool(ctx: RunContext, arg: str) -> str:
                return "result"
        """
        _security_ctx = security_context or {}

        def decorator(fn):
            # 如果传入了 gateway/security，包装安全检查
            if self._gateway is not None and self._security is not None:
                wrapped = self._wrap_with_security(fn, _security_ctx)
            else:
                wrapped = fn
            return self._base.tool(wrapped)

        if func is not None:
            return decorator(func)
        return decorator

    def tool_plain(self, func=None, *, security_context: Optional[dict] = None):
        """注册一个无 RunContext 的 tool，包装安全检查。"""
        _security_ctx = security_context or {}

        def decorator(fn):
            if self._gateway is not None and self._security is not None:
                wrapped = self._wrap_with_security_plain(fn, _security_ctx)
            else:
                wrapped = fn
            return self._base.tool_plain(wrapped)

        if func is not None:
            return decorator(func)
        return decorator

    # ── 安全检查包装器 ────────────────────────────────────

    def _wrap_with_security(self, fn, security_ctx: dict):
        """包装一个有 RunContext 的 tool 函数，调用前检查权限。"""
        import functools

        @functools.wraps(fn)
        async def wrapper(ctx: RunContext, *args, **kwargs):
            # 1. 构建命令描述（tool 的 docstring 或函数名）
            cmd_desc = security_ctx.get("command", fn.__name__)

            # 2. 走 Security Agent 检查
            decision = await self._security.can_execute(
                agent_id=self._agent_id,
                command=cmd_desc,
                sandbox=security_ctx.get("sandbox", "default"),
            )

            if decision.action == "deny":
                raise PermissionError(
                    f"Security Agent denied: {decision.reason}"
                )

            if decision.action == "confirm":
                # 如果没有外部弹窗系统，走 confirm（默认 false）
                confirmed = security_ctx.get("auto_confirm", False)
                if not confirmed:
                    # 触发弹窗，如果没实现就拒绝
                    confirm_result = await self._security.confirm(decision)
                    if confirm_result.action != "allow":
                        raise PermissionError(
                            f"Security Agent denied (user): {decision.reason}"
                        )

            # 3. 发布事件（如果有 Event Bus）
            if self._event_bus is not None:
                try:
                    await self._event_bus.publish(
                        "tool.executing",
                        {
                            "agent_id": self._agent_id,
                            "tool": fn.__name__,
                            "command": cmd_desc,
                            "risk": getattr(decision, "risk_level", "low"),
                        },
                    )
                except Exception:
                    pass  # 事件发布失败不阻塞执行

            # 4. 执行实际 tool 函数
            return await fn(ctx, *args, **kwargs)

        return wrapper

    def _wrap_with_security_plain(self, fn, security_ctx: dict):
        """包装一个无 RunContext 的 tool 函数。"""
        import functools

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            cmd_desc = security_ctx.get("command", fn.__name__)

            decision = await self._security.can_execute(
                agent_id=self._agent_id,
                command=cmd_desc,
                sandbox=security_ctx.get("sandbox", "default"),
            )

            if decision.action == "deny":
                raise PermissionError(
                    f"Security Agent denied: {decision.reason}"
                )

            if decision.action == "confirm":
                confirmed = security_ctx.get("auto_confirm", False)
                if not confirmed:
                    confirm_result = await self._security.confirm(decision)
                    if confirm_result.action != "allow":
                        raise PermissionError(
                            f"Security Agent denied (user): {decision.reason}"
                        )

            return await fn(*args, **kwargs)

        return wrapper

    # ── Tool Gateway 快捷调用 ─────────────────────────────

    async def execute_tool(
        self,
        tool_name: str,
        args: Optional[list[str]] = None,
        **kwargs,
    ) -> str:
        """通过 Tool Gateway 直接执行工具（跳过 LLM，由代码主动调用）。

        适用于 AI Shell 风格的使用 —— Transform Agent 解析出 TARL 后直接执行。

        用法::

            # 执行 shell 命令
            result = await agent.execute_tool("shell", args=["ls", "-la"])

            # 文件读取
            result = await agent.execute_tool("file.read", args=["cat", "/etc/hostname"])
        """
        if self._gateway is None:
            raise RuntimeError("ToolGateway not configured")

        from trimum_core.models import ExecuteRequest, ToolType

        # 解析 tool_name 到 ToolType
        try:
            tool_type = ToolType(tool_name)
        except ValueError:
            raise ValueError(f"Unknown tool: {tool_name}")

        request = ExecuteRequest(
            tool=tool_type,
            args=args or [],
            agent_id=self._agent_id,
            agent_manifest=self._manifest,
            **{k: v for k, v in kwargs.items() if hasattr(ExecuteRequest, k)},
        )

        response = await self._gateway.execute(request)

        if response.status == "denied":
            raise PermissionError(
                f"Tool Gateway denied: {response.reason}"
            )

        return response.output

    # ── 工具注册快捷方法 ──────────────────────────────────

    def tool_auto_confirm(self, func=None):
        """注册一个 tool，安全检查不过时自动确认（不弹窗）。

        适用于低风险工具，如只读查询。
        """
        return self.tool(func=func, security_context={"auto_confirm": True})

    # ── 辅助 ─────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"TrimumAgent(id={self._agent_id}, "
            f"base={type(self._base).__name__}, "
            f"gateway={'yes' if self._gateway else 'no'}, "
            f"security={'yes' if self._security else 'no'})"
        )


__all__ = ["TrimumAgent"]
