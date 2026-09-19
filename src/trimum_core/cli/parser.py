"""argparse parser construction for the `trm` CLI."""

from __future__ import annotations

import argparse

from ._utils import get_version
from . import commands


def _inject_json_flag(parser: argparse.ArgumentParser) -> None:
    """Add the global ``--json`` flag to a parser if it does not have one.

    ``default=argparse.SUPPRESS`` is used so a subcommand flag does not
    overwrite ``--json`` when it is supplied before the subcommand.
    """
    if any(action.dest == "json" for action in parser._actions):
        return
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )


def _inject_json_flags(subparsers: argparse._SubParsersAction) -> None:
    """Recursively inject ``--json`` into all command and nested parsers."""
    for parser in subparsers.choices.values():
        _inject_json_flag(parser)
        nested = _find_subparsers_action(parser)
        if nested is not None:
            _inject_json_flags(nested)


def _find_subparsers_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    """Return the parser's subparser action, if it defines any."""
    group = getattr(parser, "_subparsers", None)
    if group is None:
        return None
    if isinstance(group, argparse._SubParsersAction):
        return group
    for action in getattr(group, "_group_actions", []):
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def build_parser() -> argparse.ArgumentParser:
    """Build and return the complete `trm` argument parser."""
    parser = argparse.ArgumentParser(
        prog="trm",
        description="trimum — AI Process Runtime",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output machine-readable JSON where supported",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"trimum v{get_version()}",
    )

    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    commands.register_all(subparsers)
    _inject_json_flags(subparsers)
    return parser


__all__ = ["build_parser"]
