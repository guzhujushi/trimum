"""`trm commands` command group — publish and validate the command surface.

This is the agent-facing discovery contract: an agent can enumerate every
capability (``trm commands --json``) instead of guessing, and CI/tests can prove
the metadata still matches the parser (``trm commands --check``).
"""

from __future__ import annotations

import argparse

from .._utils import emit
from ..registry import (
    check_commands,
    collect_commands,
    load_command_metadata,
)

__command_meta__ = {
    "commands": {
        "summary": "Enumerate or validate the trm command surface",
        "args": "[--all] [--check]",
        "examples": ["trm commands", "trm commands --json", "trm commands --check"],
        "tags": ["meta", "agent"],
        "risk": "low",
    }
}


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "commands", help="enumerate or validate the trm command surface"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="include commands flagged as hidden",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the command metadata contract and exit non-zero on problems",
    )
    parser.set_defaults(handler=handler)


def _format_row(item: dict) -> str:
    flags: list[str] = []
    if item["requires_sudo"]:
        flags.append("sudo")
    if item["risk"]:
        flags.append(f"risk:{item['risk']}")
    suffix = f"  [{', '.join(flags)}]" if flags else ""
    return f"  {item['route']:<38}{item['summary']}{suffix}"


def _human(data: dict) -> None:
    lines = [
        f"{data['count']} of {data['total']} commands in {data['groups']} groups"
        "  (--all includes hidden)"
    ]
    lines.extend(_format_row(item) for item in data["commands"])
    print("\n".join(lines))


def _human_check(data: dict) -> None:
    if data["ok"]:
        print(f"ok: {data['total']} commands checked, no problems")
        return
    print(f"{len(data['problems'])} problem(s) found:")
    for problem in data["problems"]:
        print(f"  - {problem}")


def handler(args: argparse.Namespace) -> int:
    """List the command surface, optionally validating it."""
    from ..parser import build_parser

    parser = build_parser()
    metadata = load_command_metadata()
    commands = collect_commands(parser, metadata)
    problems = check_commands(parser, commands, metadata)

    shown = commands if getattr(args, "all", False) else [
        info for info in commands if not info.hidden
    ]
    payload = {
        "ok": not problems,
        "count": len(shown),
        "total": len(commands),
        "groups": len({info.group for info in commands if info.group}),
        "commands": [info.to_dict() for info in shown],
        "problems": problems,
    }

    if getattr(args, "check", False):
        emit(args, payload, _human_check)
        return 1 if problems else 0

    emit(args, payload, _human)
    return 0


__all__ = ["add_subparsers", "handler"]
