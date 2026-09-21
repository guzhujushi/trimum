"""Workflow Listener — 系统总监听器（TARL 三段式的执行端）。

随 daemon 一同启动，监听 Event Bus 上的关键事件：
1. **Transform Agent 的 TARL 输出**（``event.transform.completed``）→ 按 confidence 三段式决策
2. **Planner Agent 的 task 事件**（``event.planner.task_created``）→ 转 ``workflow.trigger``
3. **系统状态**（``event.system.status``）→ 健康跟踪

入口是 :meth:`WorkflowListener.submit`：它把一句自然语言交给 Transform Agent 翻译，
再把结果发到 ``event.transform.completed``。这条事件到 2026-09-21 之前**没有任何生产者**，
所以整条「意图驱动」链（含 ``workflow.trigger``）从来没有被真正跑起来过。

架构位置：
  用户 → submit(text) → Transform Agent → event.transform.completed
                                            └→ Workflow Listener → [Shell → Tool Gateway]
                                                                   ├ [高匹配 → workflow.trigger → Engine]
                                                                   ├ [中匹配 → 弹窗确认（没人确认即拒绝）]
                                                                   └ [低匹配 → Planner Agent → Engine]
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from trimum_core.event_bus import EventBus, NAMESPACE_EVENT
from trimum_core.logger import get_logger
from trimum_core.models import SourceType, SystemEvent, EventSeverity
from trimum_core.transform_agent import TransformAgent, TransformResult
from trimum_core.tool_gateway import ToolGateway
from trimum_core.tarl_parser import parse_line, serialize

# structlog 口径：``log.info("事件名", key=value)``。stdlib 的 Logger 收不了关键字参数，
# 以前这个文件用错日志器 —— 每次调用都 TypeError，而被总线的静默 _safe_call 吞掉了。
log = get_logger("trimum_core.workflow_listener")


# ── 匹配度阈值 ───────────────────────────────────────

# confidence >= HIGH_CONFIDENCE: 高匹配，直接执行
HIGH_CONFIDENCE = 0.7
# confidence >= MID_CONFIDENCE: 中匹配，弹窗确认
MID_CONFIDENCE = 0.4
# confidence < MID_CONFIDENCE: 低匹配，转 Planner Agent
LOW_CONFIDENCE = 0.4


class WorkflowListener:
    """系统总监听器（随启动运行）。

    订阅所有关键事件类型，根据事件类型做不同决策。

    启动方式:
        listener = WorkflowListener(event_bus, transform_agent, tool_gateway, ...)
        await listener.start()
        # listener 开始监听事件，直到 stop() 被调用
    """

    def __init__(
        self,
        event_bus: EventBus,
        transform_agent: TransformAgent,
        tool_gateway: ToolGateway,
        planner_agent: Any | None = None,  # 延迟 import 避免循环依赖
        *,
        high_confidence: float = HIGH_CONFIDENCE,
        mid_confidence: float = MID_CONFIDENCE,
    ) -> None:
        self._bus = event_bus
        self._transform = transform_agent
        self._gateway = tool_gateway
        self._planner = planner_agent
        self._high_confidence = high_confidence
        self._mid_confidence = mid_confidence

        self._running = False
        self._confirm_callbacks: list[ConfirmCallback] = []

    # ── 声明周期 ──────────────────────────────────────────

    async def start(self) -> None:
        """启动监听器，订阅所有需要监听的事件类型。"""
        if self._running:
            return
        self._running = True

        # ── Transform Agent 事件 ──
        self._bus.subscribe(
            f"{NAMESPACE_EVENT}transform.completed",
            self._on_transform_completed,
        )

        # ── Planner Agent 事件 ──
        self._bus.subscribe(
            f"{NAMESPACE_EVENT}planner.task_created",
            self._on_planner_task,
        )

        # ── 系统状态事件 ──
        self._bus.subscribe(
            f"{NAMESPACE_EVENT}system.status",
            self._on_system_status,
        )

        log.info("workflow_listener.started",
                 high=self._high_confidence, mid=self._mid_confidence)

    async def stop(self) -> None:
        """停止监听器。"""
        self._running = False
        log.info("workflow_listener.stopped")

    # ── 确认回调注册 ─────────────────────────────────────

    def on_confirm(self, callback: ConfirmCallback) -> None:
        """注册确认弹窗的回调函数。

        前端/CLI 通过此回调处理中匹配时的用户确认。
        """
        self._confirm_callbacks.append(callback)

    # ── 入口：自然语言 → Transform Agent → 总线 ──────────

    async def submit(self, instruction: str) -> TransformResult:
        """把一句自然语言交给 Transform Agent，并把结果发到总线。

        这是 ``event.transform.completed`` 的**唯一生产者**，也就是整条意图驱动链的入口。
        决策在本类的回调里异步跑（``publish`` 是 fire-and-forget）—— 想等它跑完，
        ``await self._bus.wait_for_handlers()``。
        """
        result = await self._transform.translate_async(instruction)
        await self._bus.emit_event(
            "transform.completed",
            "transform-agent",
            {"result": result.to_dict()},
        )
        log.info(
            "listener.transform_submitted",
            output_type=result.output_type,
            confidence=result.confidence,
        )
        return result

    # ── Transform 事件处理（三段式决策） ──────────────────

    async def _on_transform_completed(self, event: SystemEvent) -> None:
        """Transform Agent 翻译完成后的三段式决策。

        根据 TransformResult.confidence 做判断:
        - high (>= 0.7): 终端命令直接走 Tool Gateway，TARL 走 Workflow Engine
        - mid (0.4 ~ 0.7): 弹窗确认后执行
        - low (< 0.4): 转 Planner Agent 重新拆解
        """
        if not self._running:
            return

        payload = event.payload or {}
        result_dict = payload.get("result", {})

        # 重建 TransformResult
        tarl = result_dict.get("tarl", "")
        confidence = result_dict.get("confidence", 0.0)
        original = result_dict.get("original", "")
        shell_cmd = result_dict.get("shell_command")
        output_type = result_dict.get("output_type", "tarl")

        tarl_data = parse_line(tarl)
        cmd = tarl_data.get("cmd", original)

        # ── 情况 A: 终端命令，直接走 Tool Gateway ──
        if output_type == "shell" and shell_cmd:
            log.info("listener.exec_shell", cmd=cmd, confidence=confidence)
            await self._execute_shell(shell_cmd, original, confidence)
            return

        # ── 情况 B: TARL，根据 confidence 三段式决策 ──

        # 高匹配：直接执行
        if confidence >= self._high_confidence:
            log.info("listener.high_match", tarl=tarl, confidence=confidence)
            await self._emit_workflow_event(cmd, tarl, original, "high")
            return

        # 中匹配：弹窗确认
        if self._mid_confidence <= confidence < self._high_confidence:
            log.info("listener.mid_match", tarl=tarl, confidence=confidence)
            confirmed = await self._request_confirm(original, tarl, confidence)
            if confirmed:
                await self._emit_workflow_event(cmd, tarl, original, "confirmed")
            else:
                log.info("listener.cancelled_by_user", tarl=tarl)
            return

        # 低匹配：转 Planner Agent
        log.info("listener.low_match", tarl=tarl, confidence=confidence)
        if self._planner:
            await self._delegate_to_planner(original, tarl, confidence)
        else:
            log.warning("listener.no_planner", original=original)

    # ── 终端命令执行 ─────────────────────────────────────

    async def _execute_shell(
        self,
        shell_cmd: str,
        original: str,
        confidence: float,
    ) -> None:
        """终端命令直接走 Tool Gateway 的 shell dispatcher。"""
        from trimum_core.models import ExecuteRequest, ToolType

        # ExecuteRequest 的字段是 ``args``（命令整条塞进去，dispatcher 原样 join 回来），
        # 没有 ``command`` / ``raw_input`` —— 写错的时候 pydantic 不报错，命令会静默变空。
        request = ExecuteRequest(
            tool=ToolType.SHELL,
            args=[shell_cmd],
            raw_command=shell_cmd,
            agent_id="workflow-listener",
            source_type=SourceType.HUMAN,
        )

        response = await self._gateway.execute(request)

        await self._bus.emit_event("shell.executed", "listener", {
            "command": shell_cmd,
            "original": original,
            "confidence": confidence,
            "status": response.status if hasattr(response, "status") else "unknown",
            "risk": str(response.risk) if hasattr(response, "risk") else "unknown",
        })

        if getattr(response, "status", "") == "denied":
            log.warning("listener.shell_denied", cmd=shell_cmd)
            await self._bus.emit_event("shell.denied", "listener", {
                "command": shell_cmd,
                "reason": getattr(response, "reason", "no_permission"),
            })

    # ── 弹窗确认 ─────────────────────────────────────────

    async def _request_confirm(
        self,
        original: str,
        tarl: str,
        confidence: float,
    ) -> bool:
        """请求用户确认中匹配操作。

        同步等待所有已注册的 confirm callback 返回。
        默认超时 30 秒，超时视为拒绝。
        """
        if not self._confirm_callbacks:
            # 红线：确认缺位 ≠ 放行。没有回调就是没有人能同意，必须拒绝 ——
            # 「没装确认通道」不能悄悄变成「自动批准」。
            log.warning("listener.no_confirm_callback_denied", tarl=tarl)
            return False

        # 并行调用所有确认回调
        tasks = [
            cb(original, tarl, confidence)
            for cb in self._confirm_callbacks
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 只要有一个 callback 确认就视为确认
        for r in results:
            if r is True:
                return True
        return False

    # ── 转 Planner Agent ─────────────────────────────────

    async def _delegate_to_planner(
        self,
        original: str,
        tarl: str,
        confidence: float,
    ) -> None:
        """低匹配时转 Planner Agent 拆解。"""
        from trimum_core.planner_agent import PlannerAgent

        planner: PlannerAgent = self._planner  # type: ignore[assignment]

        try:
            workflow = await planner.run(
                request=original,
                context={"tarl": tarl, "transform_confidence": confidence},
            )

            if workflow:
                await self._bus.emit_event("planner.workflow_created", "listener", {
                    "workflow_name": workflow.name,
                    "node_count": len(workflow.nodes),
                    "original": original,
                })
            else:
                await self._bus.emit_event("planner.failed", "listener", {
                    "original": original,
                    "reason": "planner returned None",
                })

        except Exception as e:
            log.error("listener.planner_error", error=str(e))
            await self._bus.emit_event("planner.failed", "listener", {
                "original": original,
                "error": str(e),
            })

    # ── 触发 Workflow Engine ──────────────────────────────

    async def _emit_workflow_event(
        self,
        cmd: str,
        tarl: str,
        original: str,
        decision: str,
    ) -> None:
        """发出 workflow 执行事件。

        高匹配和确认后的中匹配都走这里。
        Workflow Engine 的 `listen_transform` 方法会捕获此事件。
        """
        await self._bus.emit_event("workflow.trigger", "listener", {
            "cmd": cmd,
            "tarl": tarl,
            "original": original,
            "decision": decision,
            "timestamp": time.time(),
        })

    # ── Planner Task 事件处理 ────────────────────────────

    async def _on_planner_task(self, event: SystemEvent) -> None:
        """Planner Agent 创建 task 后，转为 Workflow Engine 执行。"""
        payload = event.payload or {}
        workflow_def = payload.get("workflow")
        if workflow_def:
            log.info("listener.planner_workflow_received",
                     name=workflow_def.get("name", ""))
            await self._bus.emit_event("workflow.trigger", "listener", {
                "cmd": workflow_def.get("name", ""),
                "tarl": f"cmd:{workflow_def.get('name', '')}",
                "original": payload.get("original", ""),
                "decision": "planner",
            })

    # ── 系统状态监控 ─────────────────────────────────────

    async def _on_system_status(self, event: SystemEvent) -> None:
        """系统状态事件处理。"""
        payload = event.payload or {}
        status = payload.get("status", "unknown")
        log.info("listener.system_status", status=status)


# ── 类型定义 ──────────────────────────────────────────

ConfirmCallback = Any  # Callable[[str, str, float], Awaitable[bool]]


__all__ = [
    "WorkflowListener",
    "HIGH_CONFIDENCE",
    "MID_CONFIDENCE",
    "LOW_CONFIDENCE",
]
