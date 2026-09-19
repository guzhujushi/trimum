"""Subcommand registration for the `trm` CLI.

Each sibling module exposes an ``add_subparsers(subparsers)`` function that
adds its command(s) to the root parser.  This module imports those siblings
dynamically so adding a new command is as simple as dropping in a new module.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil


def register_all(subparsers: argparse._SubParsersAction) -> None:
    """Import every command module and call its ``add_subparsers`` hook."""
    package = __package__ or __name__
    for module_info in pkgutil.iter_modules(__path__):
        name = module_info.name
        if name.startswith("_"):
            continue

        module = importlib.import_module(f".{name}", package)
        add_subparsers = getattr(module, "add_subparsers", None)
        if callable(add_subparsers):
            add_subparsers(subparsers)


__all__ = ["register_all"]
