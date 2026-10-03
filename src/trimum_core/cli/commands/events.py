"""`trm events` — read-only observability exit for the event bus.

History comes from the RPC route ``events.history``; stats come from the
``bus`` field of the daemon ``health`` payload.  This command only reads —
it never publishes, dispatches, or mutates anything.
"""

from __future__ import annotations

import argparse
import json
import time

from .._utils import emit, fail, load_config, rpc_call

DEFAULT_LIMIT = 50
DEFAULT_INTERVAL = 2.0

__command_meta__ = {
    "events": {
        "summary": "Show recent daemon events (event bus history and stats)",
        "args": "[--limit N] [--follow] [--interval SECS]",
        "examples": ["trm events", "trm events --limit 20 --json", "trm events --follow"],
        "tags": ["daemon", "observability"],
        "risk": "low",
    }
}


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("events", help="show recent daemon events")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"number of recent events to fetch (default {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="poll for new events until Ctrl+C",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"poll interval for --follow (seconds, default {DEFAULT_INTERVAL})",
    )
    parser.set_defaults(handler=handler)


def handler(args: argparse.Namespace) -> int:
    """Fetch and print recent daemon events, optionally following."""
    limit = int(getattr(args, "limit", DEFAULT_LIMIT))
    if limit <= 0:
        return fail("--limit must be a positive integer")

    config = load_config(args)

    if getattr(args, "follow", False):
        interval = float(getattr(args, "interval", DEFAULT_INTERVAL))
        if interval <= 0:
            return fail("--interval must be positive")
        return _follow(config, limit, interval)

    data = _collect(config, limit)
    if data is None:
        return fail(
            "daemon is not running — `trm events` needs a live daemon "
            "(socket/HTTP unreachable)"
        )
    emit(args, data, _human_events)
    return 0


def _collect(config, limit: int) -> dict | None:
    """Gather event history plus bus stats, or ``None`` when the daemon is offline.

    The offline check must compare against ``None`` explicitly: an empty
    history (``[]``) is a *valid* result and must not be mistaken for the
    daemon being down.
    """
    events = rpc_call(config, "events.history", {"limit": limit})
    if events is None or not isinstance(events, list):
        return None
    health = rpc_call(config, "health")
    stats = health.get("bus") if isinstance(health, dict) else None
    return {"events": events, "count": len(events), "stats": stats}


def _event_key(event: dict) -> tuple:
    """Stable dedup key for a history entry (there is no ``event_id`` field)."""
    return (
        event.get("timestamp"),
        event.get("event_type"),
        event.get("source"),
        json.dumps(event.get("payload") or {}, sort_keys=True, default=str),
    )


def _human_line(event: dict) -> str:
    ts = event.get("timestamp")
    if ts is not None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    else:
        stamp = "-"
    severity = event.get("severity")
    severity = getattr(severity, "value", severity) or "info"
    return f"{stamp}  {severity:<8} {event.get('event_type') or '?'}  [{event.get('source') or '?'}]"


def _human_events(data: dict) -> None:
    count = data.get("count", len(data.get("events", [])))
    stats = data.get("stats")
    line = f"{count} event(s)"
    if isinstance(stats, dict) and stats:
        parts = []
        for key in ("patterns", "subscribers", "history", "dispatch_failures"):
            if key in stats:
                parts.append(f"{key}={stats[key]}")
        if parts:
            line += " | " + " ".join(parts)
    print(line)
    for event in data.get("events", []):
        print(_human_line(event))


def _follow(config, limit: int, interval: float) -> int:
    """Poll ``events.history`` and print only newly seen events until Ctrl+C.

    Follow is polling, not streaming: the RPC surface has no push channel, the
    bus keeps only a 100-entry ring, and the ring is cleared on daemon restart.
    """
    seen: set = set()
    try:
        while True:
            data = _collect(config, limit)
            if data is None:
                return fail(
                    "daemon is not running — `trm events --follow` needs a live daemon"
                )
            for event in data.get("events", []):
                key = _event_key(event)
                if key in seen:
                    continue
                seen.add(key)
                print(_human_line(event))
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
        return 0


__all__ = ["add_subparsers", "handler"]
