"""`trm log` command group — tail and audit log output."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from trimum_core.audit_store import AuditStore, default_audit_path

from .._utils import fail, parse_duration, print_json, wants_json


def _add_log_flags(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "--audit",
        action="store_true",
        default=default,
        help="show audit log lines",
    )
    parser.add_argument(
        "--since",
        default=default,
        help="only show entries newer than a duration (e.g. 1h, 30m)",
    )
    parser.add_argument(
        "--follow",
        "-f",
        action="store_true",
        default=default,
        help="keep following new log lines",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=100 if not suppress_defaults else argparse.SUPPRESS,
        help="number of lines to show (default: 100)",
    )


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("log", help="inspect trimum logs")
    _add_log_flags(parser)

    nested = parser.add_subparsers(dest="log_command", title="log commands")
    tail_parser = nested.add_parser("tail", help="show the tail of the main log")
    _add_log_flags(tail_parser, suppress_defaults=True)
    tail_parser.set_defaults(handler=handler)

    audit_parser = nested.add_parser("audit", help="query the structured audit log")
    audit_parser.add_argument(
        "--since",
        default=argparse.SUPPRESS,
        help="only show entries newer than a duration",
    )
    audit_parser.add_argument(
        "--event-type",
        default=argparse.SUPPRESS,
        help="filter by event type (tool_executed, policy_denied, security_blocked, ...)",
    )
    audit_parser.add_argument(
        "--agent",
        default=argparse.SUPPRESS,
        help="filter by agent id",
    )
    audit_parser.add_argument(
        "--risk",
        default=argparse.SUPPRESS,
        help="filter by risk level (low/medium/high/critical)",
    )
    audit_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=handler)


def _log_path() -> Path:
    from trimum_core.config import Config

    return Path(Config().log_path)


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _parse_line_timestamp(line: str) -> float | None:
    try:
        payload = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None

    timestamp = payload.get("timestamp")
    if isinstance(timestamp, (int, float)):
        return float(timestamp)
    return None


def _filter_since(lines: list[str], since: str | None, path: Path) -> list[str]:
    duration = parse_duration(since)
    if duration <= 0:
        return lines

    cutoff = time.time() - duration
    filtered: list[str] = []
    for line in lines:
        timestamp = _parse_line_timestamp(line)
        if timestamp is not None:
            if timestamp >= cutoff:
                filtered.append(line)
            continue

        # Non-JSON lines do not carry a timestamp; use the file mtime only
        # when the whole file is newer than the requested window.
        try:
            if path.stat().st_mtime >= cutoff:
                filtered.append(line)
        except OSError:
            filtered.append(line)
    return filtered


def _audit_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "audit" in line.lower()]


def _format_audit_event(event: dict) -> str:
    """把一条结构化审计事件渲染成一行人类可读文本。"""
    ts = event.get("timestamp")
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError):
        stamp = "unknown-time"
    return (
        f"{stamp}  {event.get('event_type', '?'):16} "
        f"agent={event.get('agent_id', '?')}  "
        f"risk={event.get('risk', '?'):8} "
        f"action={event.get('action', '?'):9} "
        f"{event.get('command', '')}"
    )


def _handle_audit(args: argparse.Namespace, *, line_count: int, since: str | None) -> int:
    """优先查结构化审计文件；没有该文件时退回主日志文本过滤。"""
    duration = parse_duration(since)
    cutoff = time.time() - duration if duration > 0 else None

    store = AuditStore()
    events = store.query(
        since=cutoff,
        event_type=getattr(args, "event_type", None),
        agent_id=getattr(args, "agent", None),
        risk=getattr(args, "risk", None),
        limit=line_count,
    )

    if store.path.exists():
        if wants_json(args):
            print_json(events)
        elif events:
            for event in events:
                print(_format_audit_event(event))
        else:
            print(f"no audit events matched ({store.path})")
        return 0

    # 兼容旧部署：没有 audit.jsonl 时退回主日志里含 audit 的行
    path = _log_path()
    if not path.exists():
        return fail(f"audit log not found: {store.path}")
    lines = _audit_lines(_filter_since(_read_lines(path), since, path))
    _emit_lines(args, lines[-line_count:] if line_count > 0 else [])
    return 0


def _emit_lines(args: argparse.Namespace, lines: list[str]) -> None:
    if wants_json(args):
        parsed = []
        for line in lines:
            try:
                parsed.append(json.loads(line))
            except (json.JSONDecodeError, TypeError):
                parsed.append(line)
        print_json(parsed)
        return

    for line in lines:
        print(line)


def handler(args: argparse.Namespace) -> int:
    """Execute the requested log operation."""
    path = _log_path()
    command = getattr(args, "log_command", None)
    audit = bool(getattr(args, "audit", False)) or command == "audit"
    follow = bool(getattr(args, "follow", False))
    since = getattr(args, "since", None)
    line_count = int(getattr(args, "n", 100) or 100)

    if audit:
        return _handle_audit(args, line_count=line_count, since=since)

    if not path.exists():
        return fail(f"log file not found: {path}")

    lines = _filter_since(_read_lines(path), since, path)
    lines = lines[-line_count:] if line_count > 0 else []

    _emit_lines(args, lines)

    if follow:
        try:
            last = path.stat().st_size
            while True:
                time.sleep(1)
                size = path.stat().st_size
                if size == last:
                    continue
                last = size
                new_lines = _read_lines(path)[line_count:]
                _emit_lines(args, new_lines)
        except KeyboardInterrupt:
            return 0

    return 0


__all__ = ["add_subparsers", "handler"]
