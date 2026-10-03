"""`trm exec` command — run one shell command, or open a coding session with ``--code``."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import sys

from .._utils import fail, is_quiet, print_json, run_async, wants_json


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "exec",
        help="execute a shell command through the tool gateway",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="shell command and arguments to execute",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="agent identifier recorded in the audit trail",
    )
    parser.add_argument(
        "--code",
        default=None,
        metavar="TASK",
        help="open a coding session for TASK (multi-step edits + verification), instead of running one command",
    )
    parser.add_argument("--dry-run", action="store_true", help="code mode: preview edits only (never writes)")
    parser.add_argument("--yes", action="store_true", help="code mode: apply edits without asking")
    parser.add_argument("--skill", default=None, metavar="NAME", help="code mode: inject only this skill")
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="command timeout in seconds (default: 60); code mode: per-command/verification timeout",
    )
    parser.set_defaults(handler=handler)


def _split_command(command: str) -> list[str]:
    """Split a command string into argv tokens, with a Windows fallback."""
    try:
        return shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return command.split()


def handler(args: argparse.Namespace) -> int:
    """Execute the requested command and print its result."""
    command_tokens = list(args.command)
    if command_tokens and command_tokens[-1] == "--json":
        args.json = True
        command_tokens = command_tokens[:-1]
    if getattr(args, "code", None) is not None:
        return _run_code(args)
    if (
        getattr(args, "dry_run", False)
        or getattr(args, "yes", False)
        or getattr(args, "skill", None) is not None
    ):
        return fail("--dry-run/--yes/--skill 只在 --code 模式下有意义")
    command = " ".join(command_tokens).strip()
    if not command:
        return fail('usage: trm exec "<command>"')

    from trimum_core.audit_store import AuditStore
    from trimum_core.models import ExecuteRequest, SourceType, ToolType
    from trimum_core.tool_gateway import ToolGateway

    request = ExecuteRequest(
        tool=ToolType.SHELL,
        args=_split_command(command),
        agent_id=args.agent or "trm-exec",
        timeout_seconds=args.timeout,
        # 人工在终端敲的命令 → HUMAN，AI 发起的走 AgentLoop(SourceType.AI)
        source_type=SourceType.HUMAN,
        skip_cwd_check=True,
    )

    gateway = ToolGateway(interactive=False, audit_store=AuditStore())
    response = asyncio.run(gateway.execute(request))
    data = response.model_dump()
    if wants_json(args):
        print_json(data)
    elif response.output:
        print(response.output)
    if response.error and not wants_json(args):
        print(response.error, file=sys.stderr)

    if response.exit_code != 0 or response.status in {"denied", "error"}:
        return 1
    return 0


def _run_code(args: argparse.Namespace) -> int:
    """Run one coding session (``trm exec --code``)."""
    task = (args.code or "").strip()
    if not task:
        return fail('usage: trm exec --code "<task>"')

    from trimum_core import coding_agent
    from trimum_core.models import TrimumError

    try:
        session = coding_agent.CodingSession(
            task,
            cwd=os.getcwd(),
            agent_id=args.agent or "trm-code",
            dry_run=args.dry_run,
            yes=args.yes,
            skill=args.skill,
            command_timeout=args.timeout,
        )
        record = run_async(session.run())
    except coding_agent.NoModelError as exc:
        return fail(f"编码会话无法开始（{exc}）")
    except TrimumError as exc:
        return fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - CLI 兜底：任何异常都不许假装完成
        return fail(f"编码会话失败：{exc}")

    if not is_quiet(args):
        if wants_json(args):
            print_json(record.to_dict())
        else:
            _render_code(record, dry_run=args.dry_run)
    return 0 if record.ok else 1


def _render_code(record, *, dry_run: bool) -> None:
    """Print a plain-text summary of one coding session (two-space indent)."""
    suffix = "（dry-run：只出差异，不落盘）" if dry_run else ""
    print(f"任务: {record.task}{suffix}")
    print(f"session: {record.session_id}")
    for step in record.steps or []:
        kind = step.get("kind", "") if isinstance(step, dict) else getattr(step, "kind", "")
        status = step.get("status", "") if isinstance(step, dict) else getattr(step, "status", "")
        detail = ""
        if isinstance(step, dict):
            detail = step.get("summary") or step.get("detail") or step.get("command") or ""
        else:
            detail = getattr(step, "summary", None) or getattr(step, "command", None) or ""
        print(f"  [{kind}] {status}  {detail}".rstrip())
    changes = list(record.changes or [])
    print(f"changes ({len(changes)}):")
    for change in changes:
        print(f"  {change.path}  (+{change.added_lines}/-{change.removed_lines}, {change.status})")
        if change.status in {"preview", "applied"} and change.difference:
            lines = change.difference.rstrip("\n").split("\n")
            for line in lines[:40]:
                print(f"    {line}")
            if len(lines) > 40:
                print(f"  …（还有 {len(lines) - 40} 行）")
        if change.reason:
            print(f"    原因: {change.reason}")
    verifications = list(record.verifications or [])
    print(f"verifications ({len(verifications)}):")
    for verification in verifications:
        kind = getattr(verification, "kind", "")
        verdict = getattr(verification, "verdict", "")
        command = getattr(verification, "command", "")
        print(f"  {kind} {verdict}  {command}".rstrip())
        if verdict in {"red", "unknown"}:
            failures = list(getattr(verification, "failures", []) or [])
            for item in failures[:10]:
                message = getattr(item, "message", None)
                if message is None:
                    print(f"    - {item}")
                else:
                    print(f"    - {getattr(item, 'file', '')}:{getattr(item, 'line', '')} {message}")
            if len(failures) > 10:
                print(f"  …（还有 {len(failures) - 10} 条失败）")
    outcome = "ok" if record.ok else "failed"
    print(f"结论: {outcome}  ({record.reason})")


__all__ = ["add_subparsers", "handler"]
