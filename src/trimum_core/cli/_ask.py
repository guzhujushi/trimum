"""One place for "ask the human" — and for refusing to hang when nobody is there.

``input()`` only raises ``EOFError`` when stdin is *closed*. A pipe that stays
open (``ssh host 'trm ...'``, a CI step, a wrapper script) just blocks forever,
so every prompt in the CLI goes through :func:`ask_confirm`, which answers
"no" when stdin is not a TTY.  Unattended callers use the explicit ``--yes``.
"""

from __future__ import annotations

import sys


def interactive() -> bool:
    """Return whether stdin can actually answer a question."""
    stream = sys.stdin
    return bool(stream is not None and getattr(stream, "isatty", lambda: False)())


def ask_confirm(question: str, *, default: bool = False) -> bool:
    """Ask a yes/no question; non-TTY (or EOF) answers *default* without blocking."""
    if not interactive():
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(f"{question}{suffix}").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        print()
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


__all__ = ["ask_confirm", "interactive"]
