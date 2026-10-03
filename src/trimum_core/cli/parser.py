"""argparse parser construction for the `trm` CLI."""

from __future__ import annotations

import argparse

from ._utils import get_version
from . import commands


_GLOBAL_ARGUMENTS: dict[str, dict] = {
    "json": {
        "args": ("--json",),
        "kwargs": {"action": "store_true"},
        "help": "output machine-readable JSON where supported",
    },
    "config": {
        "args": ("-c", "--config"),
        "kwargs": {},
        "help": "path to config YAML file",
    },
    "quiet": {
        "args": ("-q", "--quiet"),
        "kwargs": {"action": "store_true"},
        "help": "only print errors",
    },
    "verbose": {
        "args": ("-v", "--verbose"),
        "kwargs": {"action": "store_true"},
        "help": "print additional diagnostic detail",
    },
}


def _add_global_flag(
    parser: argparse.ArgumentParser,
    dest: str,
    *,
    suppress: bool = False,
) -> None:
    """Add one global flag to *parser* unless it already defines it."""
    if any(action.dest == dest for action in parser._actions):
        return

    spec = _GLOBAL_ARGUMENTS[dest]
    kwargs = dict(spec["kwargs"])
    kwargs["help"] = argparse.SUPPRESS if suppress else spec["help"]
    if suppress:
        kwargs["default"] = argparse.SUPPRESS
    parser.add_argument(*spec["args"], **kwargs)


def _inject_global_flags(subparsers: argparse._SubParsersAction) -> None:
    """Recursively inject global flags into all command and nested parsers."""
    for parser in subparsers.choices.values():
        for dest in _GLOBAL_ARGUMENTS:
            _add_global_flag(parser, dest, suppress=True)
        nested = _find_subparsers_action(parser)
        if nested is not None:
            _inject_global_flags(nested)


def _find_subparsers_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction | None:
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

    for dest in ("json", "config", "quiet", "verbose"):
        _add_global_flag(parser, dest)

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"trimum v{get_version()}",
    )

    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    commands.register_all(subparsers)
    _inject_global_flags(subparsers)
    return parser


__all__ = ["build_parser"]