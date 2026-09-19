"""`trm install` command — interactive first-time setup."""

from __future__ import annotations

import argparse


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "install",
        help="run the interactive first-time setup wizard",
    )
    parser.set_defaults(handler=handler)


def handler(args: argparse.Namespace) -> int:
    """Delegate to the existing ``install_fn.install`` implementation."""
    del args
    from trimum_core.install_fn import install

    install()
    return 0


__all__ = ["add_subparsers", "handler"]
