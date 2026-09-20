"""`trm install` command — legacy first-time setup guide.

Two entry points live here on purpose:

* ``trm install`` keeps the original guided flow (systemd service, API key,
  preset agents) implemented by :func:`trimum_core.install_fn.install`;
* ``trm install --setup`` runs the structured first-run wizard
  (``trm setup``: host detection → identity certificate → opt-in toolchain →
  Agent Skills distribution).

The plain ``trm install <name>`` form is reserved for the official package
channel (E5 in ``docs/ECOSYSTEM-STRATEGY.md``); that is why the wizard itself
is named ``trm setup`` and only mirrored here for convenience.
"""

from __future__ import annotations

import argparse

from .._utils import emit


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "install",
        help="run the interactive first-time setup wizard",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="run the newer structured wizard (same as trm setup)",
    )
    parser.set_defaults(handler=handler)


def handler(args: argparse.Namespace) -> int:
    """Run the legacy guide, or the structured wizard with ``--setup``."""
    if getattr(args, "setup", False):
        from trimum_core.cli.commands.setup import _human
        from trimum_core.setup_wizard import STEPS, run_setup

        report = run_setup(steps=STEPS)
        emit(args, report, _human)
        return 0

    from trimum_core.install_fn import install

    install()
    return 0


__all__ = ["add_subparsers", "handler"]