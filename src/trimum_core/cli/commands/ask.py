"""`trm ask` command — run an AI agent loop."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .._utils import fail, is_quiet, load_config, print_json, wants_json


class _QuietConsole:
    """No-op console used for ``--json`` / ``--quiet`` output."""

    async def confirm(self, question: str, default: bool = False) -> bool:
        del question, default
        return True

    async def prompt(self, text: str, default: str = "") -> str:
        del text
        return default

    async def subscribe_events(self, namespace: str = "agent") -> None:
        del namespace

    def unsubscribe(self) -> None:
        return None

    def __getattr__(self, name: str):
        del name
        return lambda *args, **kwargs: None


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

    async def _execute():
        context_manager = None
        if args.interactive:
            try:
                from trimum_core.context_manager import ContextManager

                config = load_config(args)
                context_manager = ContextManager(config.context_db_path)
                await context_manager.initialize()
            except Exception:
                context_manager = None

        stream_output = bool(
            not wants_json(args) and not is_quiet(args) and sys.stdout.isatty()
        )
        console = None
        if wants_json(args) or is_quiet(args):
            console = _QuietConsole()
        loop = AgentLoop(
            agent_name=args.agent,
            stream_output=stream_output,
            console=console,
            context_manager=context_manager,
        )
        try:
            if args.interactive:
                results = await loop.run_interactive(args.prompt)
            else:
                results = await loop.run(args.prompt)
            return results, loop.get_token_usage()
        finally:
            if context_manager is not None:
                try:
                    await context_manager.close()
                except Exception:
                    pass

    try:
        results, usage = asyncio.run(_execute())
    except KeyboardInterrupt:
        print()
        print(" interrupted by user")
        return 130

    data = {
        "agent": args.agent,
        "interactive": args.interactive,
        "results": results,
        "token_usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "calls": usage.calls,
        },
    }
    if wants_json(args):
        print_json(data)
    return 0


__all__ = ["add_subparsers", "handler"]
