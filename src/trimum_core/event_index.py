"""Event Index — index layer reserved for optimizing EventBus listener matching.

The current ``EventBus._matches()`` performs a linear scan over all
registered patterns. This module preserves those wildcard-matching
semantics exactly while storing listeners in first-segment buckets so a
future EventBus integration only has to inspect relevant buckets.

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

        This mirrors ``EventBus._matches`` semantics:
        - ``*`` matches any single segment.
        - A trailing ``*`` matches all remaining segments.
        - A non-trailing ``*`` floats to match one or more segments.
        - A pattern with more segments than *actual* never matches.
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