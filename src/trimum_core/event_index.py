"""Event Index — first-segment bucket index for EventBus listener matching.

``EventBus.publish()`` matches subscribers through this index instead of walking
the whole subscriber map, and :meth:`EventIndex.match` returns exactly the
listeners the old linear scan would have returned — the wildcard rules live in
one place (:func:`matches`).

Example:
    index = EventIndex()
    index.add_listener("task.node.completed", callback)
    matches = index.match("task.node.completed")
"""

from __future__ import annotations

import asyncio
from inspect import isawaitable
from typing import Any, Callable, Coroutine

from trimum_core.models import SystemEvent

ListenerCallback = Callable[[SystemEvent], Coroutine[Any, Any, None] | None]
"""Type alias for an EventIndex listener callback."""


def matches(pattern: str, actual: str) -> bool:
    """事件类型通配匹配 —— **全库唯一实现**（``EventIndex`` 与 ``EventBus`` 都用它）。

    规则（2026-09-21 收敛到一处，改这里就是改全部）：

    - ``*`` 匹配任意单段；
    - 尾部 ``*`` 匹配剩余所有段；
    - 非尾部 ``*`` 浮动匹配 1+ 段（``node.*.completed`` 命中 ``node.wf1.A.completed``）；
    - pattern 段数多于 actual 段数 → 不匹配；
    - ``*`` 单独作为 pattern → 命中一切。

    注意这**不是** workflow 触发器的口径：触发器匹配（``WorkflowRuntime.type_matches``）
    会先剥掉 ``event.`` / ``task.`` 命名空间前缀再 ``fnmatch``（写 YAML 的人写的是「人话」）。
    两层口径都由测试钉住，别顺手「统一」——它们是给两种人写的两种宽松度。
    """
    if pattern == "*":
        return True
    pp = pattern.split(".")
    ap = actual.split(".")
    if len(pp) > len(ap):
        return False

    pi = 0
    ai = 0
    while pi < len(pp) and ai < len(ap):
        part = pp[pi]
        if part == "*":
            if pi == len(pp) - 1:
                return True
            remaining = len(pp) - pi - 1
            ai_end = len(ap) - remaining
            if ai_end <= ai:
                return False
            ai = ai_end
            pi += 1
            continue
        if part != ap[ai]:
            return False
        pi += 1
        ai += 1

    return pi == len(pp) and ai == len(ap)


class EventIndex:
    """First-segment index for event listeners.

    Patterns are bucketed by their first dot-separated segment. The
    wildcard-first bucket (``*``) is checked for every event because
    patterns such as ``*.completed`` can match any namespace.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, dict[str, list[ListenerCallback]]] = {}
        self._pattern_order: dict[str, int] = {}
        self._next_order: int = 0

    @staticmethod
    def _first_segment(event_type: str) -> str:
        """Return the first dot-separated segment of *event_type*."""
        return event_type.split(".", 1)[0]

    def add_listener(self, pattern: str, callback: ListenerCallback) -> None:
        """Register *callback* for *pattern* in its first-segment bucket."""
        first = self._first_segment(pattern)
        bucket = self._buckets.setdefault(first, {})
        if pattern not in bucket:
            self._pattern_order[pattern] = self._next_order
            self._next_order += 1
        bucket.setdefault(pattern, []).append(callback)

    def remove_listener(self, pattern: str, callback: ListenerCallback) -> None:
        """Remove *callback* for *pattern*.

        Unknown pattern/callback pairs are silently ignored. Empty
        pattern and bucket entries are removed.
        """
        first = self._first_segment(pattern)
        bucket = self._buckets.get(first)
        if bucket is None:
            return

        listeners = bucket.get(pattern)
        if listeners is None:
            return
        try:
            listeners.remove(callback)
        except ValueError:
            return

        if not listeners:
            del bucket[pattern]
            self._pattern_order.pop(pattern, None)
        if not bucket:
            del self._buckets[first]

    def match(self, event_type: str) -> list[ListenerCallback]:
        """Return listeners matching *event_type* in registration order.

        Only the bucket matching the event's first segment and the
        wildcard-first bucket (``*``) are inspected.
        """
        matched: list[tuple[int, list[ListenerCallback]]] = []
        relevant_buckets = dict.fromkeys((self._first_segment(event_type), "*"))
        for first in relevant_buckets:
            bucket = self._buckets.get(first)
            if not bucket:
                continue
            for pattern, listeners in bucket.items():
                if pattern == "*" or self._matches(pattern, event_type):
                    matched.append((self._pattern_order.get(pattern, 0), listeners))

        matched.sort(key=lambda item: item[0])
        result: list[ListenerCallback] = []
        for _, listeners in matched:
            result.extend(listeners)
        return result

    @staticmethod
    def _matches(pattern: str, actual: str) -> bool:
        """Return whether wildcard *pattern* matches *actual*.

        Thin alias of the module-level :func:`matches` — the wildcard rules
        live in exactly one place (``EventBus._matches`` delegates here too).
        """
        return matches(pattern, actual)

    async def _invoke(self, callback: ListenerCallback, event: SystemEvent) -> None:
        """Invoke a listener, awaiting async listeners when needed."""
        result = callback(event)
        if isawaitable(result):
            await result

    def as_callback(self) -> ListenerCallback:
        """Return a wrapper callback suitable for ``EventBus.subscribe``.

        The wrapper dispatches an incoming event to every matching
        registered listener and runs them concurrently.
        """

        async def _dispatch(event: SystemEvent) -> None:
            listeners = self.match(event.event_type)
            if not listeners:
                return
            await asyncio.gather(*(self._invoke(listener, event) for listener in listeners))

        return _dispatch