"""`trm approve` command — 非交互通道的一次性审批入口。

web / API / workflow 触发高风险操作时只能拿到 confirm 决策；人用本命令
批准/拒绝落盘的待批请求（`ApprovalStore`），过期记录 fail-closed。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .._utils import emit, fail

__all__ = ["add_subparsers", "handler"]


def _format_expires(at: float) -> str:
    try:
        return datetime.fromtimestamp(at, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return str(at)


def _print_list(data: dict) -> None:
    rows = data.get("pending", [])
    if not rows:
        print("(no pending approvals)")
        return
    for row in rows:
        print("\t".join([str(row.get("id", "")), str(row.get("tool", "")), str(row.get("command", ""))]))


def _print_record(data: dict) -> None:
    print(f"id: {data.get('id', '')}")
    print(f"status: {data.get('status', '')}")
    print(f"tool: {data.get('tool', '')}")
    print(f"command: {data.get('command', '')}")
    print(f"expires_at: {_format_expires(float(data.get('expires_at') or 0.0))}")


def handler(args: argparse.Namespace) -> int:
    """Execute the requested approve action."""
    from trimum_core.approvals import ApprovalStore

    store = ApprovalStore()

    if args.list or not args.request_id:
        emit(args, {"pending": [r.to_dict() for r in store.list_pending()]}, _print_list)
        return 0

    record = store.decide(args.request_id, approved=not args.deny, decided_by=args.by)
    if record is None:
        return fail(f"approval request not found: {args.request_id}")
    if record.status == "expired":
        return fail(f"approval request expired (fail-closed): {args.request_id}")
    if not args.deny and record.status != "approved":
        return fail(f"approval request is already {record.status}: {args.request_id}")
    emit(args, record.to_dict(), _print_record)
    return 0


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "approve",
        help="approve or deny a pending confirmation request (non-CLI channel)",
    )
    parser.add_argument("request_id", nargs="?", default="")
    parser.add_argument("--deny", action="store_true", help="deny the request instead of approving")
    parser.add_argument("--list", action="store_true", help="list pending approval requests")
    parser.add_argument("--by", default="user", help="approver name recorded on the decision")
    parser.set_defaults(handler=handler)


__command_meta__ = {
    "approve": {
        "summary": "approve or deny a pending confirmation request (non-CLI channel)",
        "args": "<request_id> [--deny] [--list] [--by NAME]",
        "examples": ["trm approve 3f2a", "trm approve --list"],
        "requires_sudo": False,
        "risk": "medium",
        "tags": ["security"],
    },
}
