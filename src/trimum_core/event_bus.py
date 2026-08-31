"""Async event publish/subscribe system for trimum Core."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Callable, Coroutine

from trimum_core.models import SystemEvent


Callback = Callable[[SystemEvent], Coroutine[Any, Any, None] | None]


class EventBus:
    """Async pub/sub event bus.

    Features:
    - Subscribe by event_type; `*` matches all events.
    - Each callback runs in its own asyncio Task (non-blocking publish).
    - In-memory history ring buffer (last 100 events).
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

        Each subscriber callback is dispatched as an independent asyncio
        Task so that a slow or failing subscriber never blocks the caller
        or other subscribers.
        """
        if event.timestamp is None:
            event.timestamp = time.time()

        # Keep a copy for history
        self._history.append(event.model_copy(deep=True))

        # Collect matching callbacks
        targets: list[Callback] = []
        # Wildcard subscribers always receive the event
        wildcard = self._subscribers.get("*", [])
        targets.extend(wildcard)

        # Type-specific subscribers
        type_subs = self._subscribers.get(event.event_type, [])
        targets.extend(type_subs)

        # Fire each in its own Task, catching & logging errors silently
        for cb in targets:
            asyncio.ensure_future(self._safe_call(cb, event))

    # ------------------------------------------------------------------
    # Subscribe / Unsubscribe
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, callback: Callback) -> None:
        """Register *callback* for *event_type*.

        Pass `\*` to receive *all* events.
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