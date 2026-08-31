"""Event Bus — 三层命名空间 + async pub/sub + 生命周期管理."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from .models import EventSeverity, SystemEvent

# ── 类型别名 ──────────────────────────────────────────────

EventHandler = Callable[[SystemEvent], Awaitable[None]]
"""异步事件处理器签名."""

# ── 命名空间常量 ──────────────────────────────────────────

NAMESPACE_TASK = "task."
"""Workflow Engine 写入, Agent 可订阅. e.g. task.workflow.started, task.node.completed"""

NAMESPACE_EVENT = "event."
"""所有 Agent 可读写. e.g. event.agent.hello, event.data.fetched"""

NAMESPACE_SYSTEM = "system."
"""仅 Runtime 自身写入. e.g. system.bus.started, system.shutdown"""


class SubscriptionPolicy(str, Enum):
    """订阅策略: 一次 / 持久 / 最后一次."""

    ONCE = "once"           # 触发一次后自动取消
    PERSISTENT = "persistent"  # 持续订阅
    LAST = "last"           # 只保留最后一个处理器 (覆盖)


class EventBus:
    """三层命名空间事件总线.

    职责:
    - 接收 SystemEvent → 按 event_type 路由给订阅者
    - 维护三层命名空间隔离 (task./event./system.)
    - 支持 async 订阅/取消/过滤模式匹配
    - 生命周期: start → (emit/receive)* → stop
    """

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._loop = loop or asyncio.get_event_loop()

        # 订阅者存储: {pattern: [(handler, policy)]}
        self._subscribers: dict[str, list[tuple[EventHandler, SubscriptionPolicy]]] = defaultdict(list)

        # 历史事件缓存 (用于 LAST 策略的背压回放)
        self._last_events: dict[str, SystemEvent] = {}

        # 生命周期标志
        self._running = False
        self._started_at: float = 0.0

        # 统计
        self._total_emitted = 0
        self._total_delivered = 0
        self._total_errors = 0

    # ── 生命周期 ──────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._running

    @property
    def uptime(self) -> float:
        return time.time() - self._started_at if self._running else 0.0

    async def start(self) -> None:
        """启动事件总线."""
        self._running = True
        self._started_at = time.time()
        await self.emit(SystemEvent(
            event_type="system.bus.started",
            source="core.event_bus",
            severity=EventSeverity.INFO,
            payload={"uptime": self.uptime},
        ))

    async def stop(self) -> None:
        """停止事件总线: 排空 pending, 发送关闭事件, 清订阅."""
        await self.emit(SystemEvent(
            event_type="system.bus.stopping",
            source="core.event_bus",
            severity=EventSeverity.INFO,
        ))
        self._running = False
        self._subscribers.clear()
        self._last_events.clear()

    # ── 命名空间校验 ──────────────────────────────────────

    @staticmethod
    def _validate_namespace(event_type: str) -> None:
        """校验 event_type 是否在合法的三层命名空间内."""
        if not (
            event_type.startswith(NAMESPACE_TASK)
            or event_type.startswith(NAMESPACE_EVENT)
            or event_type.startswith(NAMESPACE_SYSTEM)
        ):
            raise ValueError(
                f"event_type '{event_type}' 必须以 '{NAMESPACE_TASK}', "
                f"'{NAMESPACE_EVENT}' 或 '{NAMESPACE_SYSTEM}' 开头"
            )

    # ── 订阅 / 取消订阅 ───────────────────────────────────

    def subscribe(
        self,
        pattern: str,
        handler: EventHandler,
        policy: SubscriptionPolicy = SubscriptionPolicy.PERSISTENT,
    ) -> None:
        """订阅事件模式.

        支持通配符: event.agent.* 匹配所有 event.agent.xxx 事件.
        task.** 匹配所有 task. 下的事件.
        """
        # 将 ** 转为内部通配符标记, * 转为精确前缀匹配
        if "**" in pattern:
            # task.** → 匹配所有 task. 前缀
            self._validate_namespace(pattern.rstrip("*."))
        elif "*" in pattern:
            # task.node.* → 前缀 task.node.
            prefix = pattern.rsplit("*", 1)[0]
            self._validate_namespace(prefix.rstrip(".") + ".dummy")
        else:
            self._validate_namespace(pattern)

        self._subscribers[pattern].append((handler, policy))

        # LAST 策略: 如果有历史事件, 立即回放
        if policy == SubscriptionPolicy.LAST:
            for etype, event in self._last_events.items():
                if self._match_pattern(etype, pattern):
                    self._loop.create_task(handler(event))

    def unsubscribe(self, pattern: str, handler: EventHandler) -> None:
        """取消特定模式的特定处理器."""
        handlers = self._subscribers.get(pattern, [])
        self._subscribers[pattern] = [
            (h, p) for h, p in handlers if h is not handler
        ]
        if not self._subscribers[pattern]:
            del self._subscribers[pattern]

    def unsubscribe_all(self, pattern: Optional[str] = None) -> None:
        """取消某模式下的所有订阅, 或全部订阅."""
        if pattern:
            self._subscribers.pop(pattern, None)
            self._last_events.pop(pattern, None)
        else:
            self._subscribers.clear()
            self._last_events.clear()

    # ── 模式匹配 ──────────────────────────────────────────

    @staticmethod
    def _match_pattern(event_type: str, pattern: str) -> bool:
        """判断 event_type 是否匹配 pattern.

        规则:
        - "event.agent.*" → 匹配 "event.agent.xxx" (前缀按段匹配)
        - "task.**" → 匹配所有 task. 下事件 (前缀匹配)
        - "event.agent.hello" → 精确匹配
        """
        if "**" in pattern:
            prefix = pattern.replace("**", "").rstrip(".")
            return event_type.startswith(prefix + ".") or event_type == prefix
        if "*" in pattern:
            prefix = pattern.rsplit("*", 1)[0]
            return event_type.startswith(prefix) and len(event_type) > len(prefix)
        return event_type == pattern

    def _get_matching_subscribers(
        self, event_type: str
    ) -> list[tuple[EventHandler, SubscriptionPolicy]]:
        """获取所有匹配 event_type 的处理器."""
        matched: list[tuple[EventHandler, SubscriptionPolicy]] = []
        for pattern, handlers in list(self._subscribers.items()):
            if self._match_pattern(event_type, pattern):
                matched.extend(handlers)
        return matched

    # ── 发送事件 ──────────────────────────────────────────

    async def emit(self, event: SystemEvent) -> None:
        """发送事件到所有匹配的订阅者.

        对于 task.** 和 event.** 的 emit, 自动补全 timestamp.
        system.** 的 emit 不强制, 但建议 caller 传.
        """
        self._validate_namespace(event.event_type)

        # 补全 timestamp
        if event.timestamp is None:
            event.timestamp = time.time()

        # 记录历史 (用于 LAST 策略)
        self._last_events[event.event_type] = event

        self._total_emitted += 1

        # 收集匹配处理器
        subscribers = self._get_matching_subscribers(event.event_type)

        if not subscribers:
            return  # 无订阅者, 静默丢弃

        # 并发投递
        tasks = []
        for handler, policy in subscribers:
            tasks.append(self._safe_dispatch(handler, event, policy))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    self._total_errors += 1

    async def _safe_dispatch(
        self,
        handler: EventHandler,
        event: SystemEvent,
        policy: SubscriptionPolicy,
    ) -> None:
        """安全分发: 捕获异常, ONCE 策略自动取消."""
        try:
            await handler(event)
            self._total_delivered += 1
        except Exception as e:
            self._total_errors += 1
            # 异常不作为 emit, 直接 log
            print(f"[EventBus] Handler error for {event.event_type}: {e}")

        if policy == SubscriptionPolicy.ONCE:
            # 从所有订阅模式中移除该 handler
            for pattern in list(self._subscribers.keys()):
                self._subscribers[pattern] = [
                    (h, p) for h, p in self._subscribers[pattern] if h is not handler
                ]
                if not self._subscribers[pattern]:
                    del self._subscribers[pattern]

    # ── 便捷方法 ──────────────────────────────────────────

    async def emit_task(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """便捷: 发送 task.* 事件."""
        await self.emit(SystemEvent(
            event_type=f"{NAMESPACE_TASK}{event_type}",
            source="core.event_bus",
            severity=EventSeverity.INFO,
            payload=payload or {},
        ))

    async def emit_event(self, event_type: str, source: str, payload: dict[str, Any] | None = None) -> None:
        """便捷: 发送 event.* 事件."""
        await self.emit(SystemEvent(
            event_type=f"{NAMESPACE_EVENT}{event_type}",
            source=source,
            severity=EventSeverity.INFO,
            payload=payload or {},
        ))

    async def emit_system(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """便捷: 发送 system.* 事件."""
        await self.emit(SystemEvent(
            event_type=f"{NAMESPACE_SYSTEM}{event_type}",
            source="core.event_bus",
            severity=EventSeverity.INFO,
            payload=payload or {},
        ))

    # ── 统计 & 调试 ───────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "uptime": self.uptime,
            "subscriber_patterns": len(self._subscribers),
            "total_emitted": self._total_emitted,
            "total_delivered": self._total_delivered,
            "total_errors": self._total_errors,
            "last_events_cached": len(self._last_events),
        }

    def subscriber_count(self, pattern: str) -> int:
        """获取某模式下的订阅者数量."""
        return len(self._subscribers.get(pattern, []))

    def debug_subscribers(self) -> dict[str, int]:
        """返回 {pattern: 订阅者数量}."""
        return {p: len(h) for p, h in self._subscribers.items()}


# ── 工程便利: 获取全局 EventBus ──────────────────────────

_bus_instance: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取全局 EventBus 单例."""
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = EventBus()
    return _bus_instance


def set_event_bus(bus: EventBus) -> None:
    """设置全局 EventBus (主要在测试时覆盖)."""
    global _bus_instance
    _bus_instance = bus
