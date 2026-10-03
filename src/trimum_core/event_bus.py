"""Async event publish/subscribe system for trimum Core."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Any, Callable, Coroutine

from trimum_core.event_index import EventIndex
from trimum_core.event_index import matches as event_type_matches
from trimum_core.models import EventSeverity, SystemEvent, TRMErrorCode, TrimumError

log = logging.getLogger(__name__)


Callback = Callable[[SystemEvent], Coroutine[Any, Any, None] | None]

STRICT_ENV = "TRIMUM_BUS_STRICT"
"""环境变量：置 1/true/yes/on → 订阅者异常直接抛出（默认只记一笔 + 广播失败事件）。"""


def strict_from_env() -> bool:
    """从环境变量读严格模式（daemon / CI 想「静默失败算失败」就打开）。"""
    return os.environ.get(STRICT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def callback_name(callback: Callable[..., Any]) -> str:
    """订阅者的可读名字（日志与失败事件里点名用）。"""
    name = getattr(callback, "__qualname__", None) or getattr(callback, "__name__", None)
    return str(name) if name else repr(callback)


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
        severity: EventSeverity | str = EventSeverity.INFO,
    ) -> None:
        """Convenience: create and publish a SystemEvent in one call.

        Automatically prepends NAMESPACE_EVENT.
        """
        event = SystemEvent(
            event_type=f"{NAMESPACE_EVENT}{event_type}",
            source=source,
            severity=EventSeverity(severity),
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

    FAILURE_EVENT_TYPE = f"{NAMESPACE_EVENT}eventbus.dispatch_failed"
    """订阅者抛异常时广播的事件类型（``event.eventbus.dispatch_failed``）。"""

    def __init__(self, *, strict: bool | None = None) -> None:
        """``strict=None`` 时看环境变量 ``TRIMUM_BUS_STRICT``（默认关）。"""
        self._subscribers: dict[str, list[Callback]] = {}
        self._history: deque[SystemEvent] = deque(maxlen=self._MAX_HISTORY)
        # 首段分桶索引：publish 不再对整张订阅表线性扫描（2026-09-21 总线硬化）
        self._index = EventIndex()
        self._strict = strict_from_env() if strict is None else strict
        self._dispatch_failures = 0
        self._last_failure: dict[str, Any] | None = None
        self._pending: list[asyncio.Task[None]] = []

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

        # 匹配走首段分桶索引（返回的听众与旧的全表扫描逐条相同，见 EventIndex.match）
        targets = self._index.match(event.event_type)

        # 每条一个 Task（互不阻塞）；失败不再静默，见 _safe_call
        self._pending = [task for task in self._pending if not task.done()]
        for cb in targets:
            self._pending.append(asyncio.ensure_future(self._safe_call(cb, event)))

    # ------------------------------------------------------------------
    # Subscribe / Unsubscribe
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, callback: Callback) -> None:
        """Register *callback* for *event_type*.

        Pass ``*`` to receive *all* events.
        """
        self._subscribers.setdefault(event_type, []).append(callback)
        self._index.add_listener(event_type, callback)

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

        # 索引跟着退订走（不然 publish 还会把事件发给已经退订的人）
        self._index.remove_listener(event_type, callback)

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
        """通配符匹配（实现只有一处：``event_index.matches``，这里只是转发）。

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
        return event_type_matches(pattern, actual)

    @classmethod
    def matches(cls, pattern: str, actual: str) -> bool:
        """公开口径：总线订阅匹配（segment 严格，**不**剥命名空间前缀）。

        与 workflow 触发器匹配（``WorkflowRuntime.type_matches``）**故意不同**：后者先去掉
        ``event.`` / ``task.`` 前缀再 ``fnmatch``（写 YAML 的人写的是「人话」）。两层口径
        都由测试钉住，别顺手「统一」—— 它们是给两种人写的两种宽松度。
        """
        return cls._matches(pattern, actual)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _safe_call(self, callback: Callback, event: SystemEvent) -> None:
        """跑一个订阅者。**出错不再静默**（2026-09-21 总线硬化）：

        - 记日志（订阅者名 + 事件类型 + 堆栈）+ 计数（:attr:`dispatch_failures`）；
        - 广播 :attr:`FAILURE_EVENT_TYPE`，让「事件到底发没发出去」在总线上看得见；
        - 严格模式（``TRIMUM_BUS_STRICT=1`` / ``EventBus(strict=True)``）把异常抛出去，
          交给 :meth:`wait_for_handlers` 收集 —— 订阅者写错就是错，不该只表现为「事件没反应」。

        坏的订阅者仍然**不会**影响别的订阅者、也不影响发事件的人：那些都在各自的 Task 里。
        """
        try:
            result = callback(event)
            if result is not None:
                # 协程函数 —— await 它
                await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._on_dispatch_failure(callback, event, exc)
            if self._strict:
                raise TrimumError(
                    TRMErrorCode.EVENT_BUS_DISPATCH_FAILED,
                    message=(
                        f"subscriber {callback_name(callback)} failed on "
                        f"{event.event_type}: {exc}"
                    ),
                    context={"event_type": event.event_type},
                ) from exc

    async def _on_dispatch_failure(
        self, callback: Callback, event: SystemEvent, exc: BaseException
    ) -> None:
        """记一笔 + 广播失败事件（失败事件自己再失败时只记不播，防转圈）。"""
        self._dispatch_failures += 1
        self._last_failure = {
            "event_type": event.event_type,
            "callback": callback_name(callback),
            "source": event.source,
            "error": f"{type(exc).__name__}: {exc}",
            "at": time.time(),
        }
        log.warning(
            "event_bus.dispatch_failed event=%s callback=%s error=%s",
            self._last_failure["event_type"],
            self._last_failure["callback"],
            self._last_failure["error"],
            exc_info=exc,
        )
        if event.event_type == self.FAILURE_EVENT_TYPE:
            return
        if not self._index.match(self.FAILURE_EVENT_TYPE):
            return  # 没人听就不发，省掉无谓的 Task
        await self.emit_event(
            "eventbus.dispatch_failed",
            "event-bus",
            dict(self._last_failure),
            severity=EventSeverity.WARNING,
        )

    # ── 观测面（「事件到底发没发出去」） ──────────────

    @property
    def dispatch_failures(self) -> int:
        """订阅者异常计数（进程内累计）。"""
        return self._dispatch_failures

    @property
    def last_failure(self) -> dict[str, Any] | None:
        """最近一次订阅者异常（``None`` = 还没坏过）。"""
        return None if self._last_failure is None else dict(self._last_failure)

    @property
    def strict(self) -> bool:
        """严格模式（订阅者异常会被抛出来）。"""
        return self._strict

    def stats(self) -> dict[str, Any]:
        """总线自述（排障与观测面用）。"""
        return {
            "patterns": len(self._subscribers),
            "subscribers": sum(len(subs) for subs in self._subscribers.values()),
            "history": len(self._history),
            "in_flight": sum(1 for task in self._pending if not task.done()),
            "dispatch_failures": self._dispatch_failures,
            "last_failure": self.last_failure,
            "strict": self._strict,
        }

    async def wait_for_handlers(self, *, timeout: float | None = None) -> None:
        """等「在飞的订阅者回调」跑完；异常按原样抛出（严格模式与测试用）。

        ``publish`` 是 fire-and-forget（每个订阅者一个 Task），所以严格模式下的异常
        得有个地方收 —— 就是这里。
        """
        pending = [task for task in self._pending if not task.done()]
        if not pending:
            return
        gather = asyncio.gather(*pending)
        if timeout is None:
            await gather
        else:
            await asyncio.wait_for(gather, timeout)
