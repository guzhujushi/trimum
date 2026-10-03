"""`trm version` command."""

from __future__ import annotations

import argparse

from .._utils import emit, get_version


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("version", help="display version number")
    parser.set_defaults(handler=handler)


def handler(args: argparse.Namespace) -> int:
    """Print the trimum version and return 0."""
    version = get_version()
    data = {"name": "trimum", "version": version}

    def human(_: dict) -> None:
        print(f"trimum v{version}")

    emit(args, data, human)
    return 0


__all__ = ["add_subparsers", "handler"]
