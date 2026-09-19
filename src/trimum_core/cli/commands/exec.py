"""`trm exec` command — execute a shell command through ToolGateway."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import sys

from .._utils import fail, print_json, wants_json


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
        default="trm-exec",
        help="agent identifier recorded in the audit trail",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="command timeout in seconds (default: 60)",
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
    command = " ".join(command_tokens).strip()
    if not command:
        return fail('usage: trm exec "<command>"')

    from trimum_core.models import ExecuteRequest, SourceType, ToolType
    from trimum_core.tool_gateway import ToolGateway

    request = ExecuteRequest(
        tool=ToolType.SHELL,
        args=_split_command(command),
        agent_id=args.agent,
        timeout_seconds=args.timeout,
        source_type=SourceType.UNKNOWN,
        skip_cwd_check=True,
    )

    gateway = ToolGateway(interactive=False)
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


__all__ = ["add_subparsers", "handler"]
