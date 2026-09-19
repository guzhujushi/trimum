"""`trm ask` command — run an AI agent loop."""

from __future__ import annotations

import argparse
import asyncio

from .._utils import fail, print_json, wants_json


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "ask",
        aliases=["run"],
        help="ask the AI agent to execute a natural-language instruction",
    )
    parser.add_argument("prompt", help="natural-language instruction")
    parser.add_argument(
        "--agent",
        default="trm-exec",
        help="agent name to use (default: trm-exec)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="enter interactive multi-turn mode",
    )
    parser.set_defaults(handler=handler)


def handler(args: argparse.Namespace) -> int:
    """Run ``AgentLoop.run`` or ``AgentLoop.run_interactive``."""
    if not args.prompt.strip():
        return fail("prompt must not be empty")

    from trimum_core.agent_loop import AgentLoop

    loop = AgentLoop(agent_name=args.agent)
    if args.interactive:
        results = asyncio.run(loop.run_interactive(args.prompt))
    else:
        results = asyncio.run(loop.run(args.prompt))

    data = {
        "agent": args.agent,
        "interactive": args.interactive,
        "results": results,
    }
    if wants_json(args):
        print_json(data)
    return 0


__all__ = ["add_subparsers", "handler"]
