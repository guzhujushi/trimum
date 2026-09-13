"""Async event publish/subscribe system for trimum Core."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Callable, Coroutine

from trimum_core.models import EventSeverity, SystemEvent


Callback = Callable[[SystemEvent], Coroutine[Any, Any, None] | None]


# ── Namespace constants (consumed by planner_agent) ──────────

NAMESPACE_EVENT = "event."
"""Prefix for event namespace events."""

NAMESPACE_TASK = "task."
"""Prefix for task namespace events."""

# 安全/监控事件常量（供 sec_monitor.py 等引用）
AGENT_STATUS_CHANGED = "agent.status_changed"
EVENT_SEC_MONITOR = "security.monitor_result"
EVENT_SEC_ALERT = "security.alert"
EVENT_SEC_BLOCKED = "security.blocked"
EVENT_SEC_EBPF = "security.ebpf_alert"
EVENT_SEC_FUSE = "security.fuse_triggered"
EVENT_SEC_AUDIT_BREACH = "security.audit_breach"
EVENT_WORKFLOW_TRIGGER = "workflow.trigger"


class EventBus:

    async def emit_event(
        self,
        event_type: str,
        source: str,
        payload: dict | None = None,
    ) -> None:
        """Convenience: create and publish a SystemEvent in one call.

        Automatically prepends NAMESPACE_EVENT.
        """
        event = SystemEvent(
            event_type=f"{NAMESPACE_EVENT}{event_type}",
            source=source,
            severity=EventSeverity.INFO,
            payload=payload or {},
            timestamp=time.time(),
        )
        await self.publish(event)

    async def emit_task(
        self,
        task_type: str,
        payload: dict | None = None,
        source: str = "workflow",
        severity: str | None = None,
    ) -> None:
        """Convenience: create and publish a task SystemEvent.

        Automatically prepends NAMESPACE_TASK.
        Used by WorkflowEngine for node/workflow lifecycle events.

        Args:
            task_type: Type string (e.g. "node.completed", "workflow.started")
            payload: Event payload dict
            source: Event source identifier
            severity: Override severity (default INFO). Use "warn" for blocked/timeout.
        """
        event = SystemEvent(
            event_type=f"{NAMESPACE_TASK}{task_type}",
            source=source,
            severity=EventSeverity(severity) if severity else EventSeverity.INFO,
            payload=payload or {},
            timestamp=time.time(),
        )
        await self.publish(event)

    """Async pub/sub event bus.

    Features:
    - Subscribe by event_type; ``*`` matches all events.
    - Each callback runs in its own asyncio Task (non-blocking publish).
    - In-memory history ring buffer (last 100 events).
    - ``subscribe_with_replay`` replays matching past events for new
      subscribers, solving the late-subscriber race.
    """

    _MAX_HISTORY = 100

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callback]] = {}
        self._history: deque[SystemEvent] = deque(maxlen=self._MAX_HISTORY)

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, event: SystemEvent) -> None:
        """Publish an event to all matching subscribers.

        Supports wildcard patterns: a subscriber registered for
        ``node.*.completed`` will receive ``node.wf1.A.completed`` and
        similar.  ``*`` alone matches everything.

        Each subscriber callback is dispatched as an independent asyncio
        Task so that a slow or failing subscriber never blocks the caller
        or other subscribers.
        """
        if event.timestamp is None:
            event.timestamp = time.time()

        # Keep a copy for history
        self._history.append(event.model_copy(deep=True))

        # Collect matching callbacks — iterate entire subscriber map
        # since any pattern may be a wildcard.
        targets: list[Callback] = []
        for pattern, subs in self._subscribers.items():
            if pattern == "*" or self._matches(pattern, event.event_type):
                targets.extend(subs)

        # Fire each in its own Task, catching & logging errors silently
        for cb in targets:
            asyncio.ensure_future(self._safe_call(cb, event))

    # ------------------------------------------------------------------
    # Subscribe / Unsubscribe
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, callback: Callback) -> None:
        """Register *callback* for *event_type*.

        Pass ``*`` to receive *all* events.
        """
        self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: str, callback: Callback) -> None:
        """Remove a previously registered *callback* for *event_type*.

        If the callback is not registered the call is silently ignored.
        """
        subs = self._subscribers.get(event_type)
        if subs is None:
            return
        try:
            subs.remove(callback)
        except ValueError:
            pass

        # Clean up empty subscriber lists
        if not subs:
            del self._subscribers[event_type]

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(self, limit: int = 50) -> list[SystemEvent]:
        """Return the most recent *limit* events (newest last)."""
        if limit <= 0:
            return []
        if limit >= len(self._history):
            return list(self._history)
        slice_start = len(self._history) - limit
        return [self._history[i] for i in range(slice_start, len(self._history))]

    # ------------------------------------------------------------------
    # Subscribe with replay
    # ------------------------------------------------------------------

    def subscribe_with_replay(
        self,
        event_type: str,
        callback: Callback,
        replay_count: int = 0,
    ) -> None:
        """注册回调并重放最近 *replay_count* 条匹配历史事件。

        用于场景：Agent 启动后注册监听，但目标事件可能已经发出，
        通过重放历史事件可避免竞态问题。

        如果 event_type 包含通配符 (``*``)，会用 :meth:`_matches`
        做模式匹配。
        """
        if replay_count > 0:
            for event in self.get_history(limit=replay_count):
                if self._matches(event_type, event.event_type):
                    asyncio.ensure_future(self._safe_call(callback, event))
        self.subscribe(event_type, callback)

    @staticmethod
    def _matches(pattern: str, actual: str) -> bool:
        """通配符匹配，``*``  匹配任意单段，支持 pattern 短于 actual。

        规则：
        - ``*`` 匹配任意单段
        - ``*`` 在非尾部时，浮动匹配 1+ 段，将其余 pattern 段对齐 actual 尾部
        - pattern 段数 > actual 段数 → 不匹配
        - 示例：
            "node.*.completed"  vs "node.wf1.A.completed"  → True
            "node.*.completed"  vs "node.wf1.completed"   → True
            "confirm.*.required"  vs "confirm.wf1.A.required"  → True
            "node.*.completed"  vs "node.wf1.B.started"  → False
        """
        if pattern == "*":
            return True
        pp = pattern.split(".")
        ap = actual.split(".")
        if len(pp) > len(ap):
            return False

        pi = 0  # pattern index
        ai = 0  # actual index
        while pi < len(pp) and ai < len(ap):
            p = pp[pi]
            if p == "*":
                # * 在尾部：匹配剩余所有段
                if pi == len(pp) - 1:
                    return True
                # * 在中间：找出剩余 pattern 能否在 actual 中匹配
                # 把剩下的 pattern (pi+1 起) 对齐 actual 尾部
                remaining = len(pp) - pi - 1
                # 必须至少给 remaining 段留位置
                ai_end = len(ap) - remaining
                # * 匹配的段数 = ai_end - ai；至少 1 段
                if ai_end <= ai:
                    return False
                # 跳过这 1+ 段，直接去匹配后面的段
                ai = ai_end
                pi += 1
                continue
            if p != ap[ai]:
                return False
            pi += 1
            ai += 1

        return pi == len(pp) and ai == len(ap)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _safe_call(callback: Callback, event: SystemEvent) -> None:
        """Await *callback* and swallow any exception.

        Exceptions are intentionally suppressed so that one broken
        subscriber never poisons the event bus for others.
        """
        try:
            result = callback(event)
            if result is not None:
                # It is a coroutine function — await it
                await result
        except Exception:  # noqa: BLE001
            # Logged / surfaced through a dedicated channel in production.
            pass
