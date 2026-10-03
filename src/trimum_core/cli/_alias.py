"""Command alias expansion for ``trm`` (``.trimumrc``).

One ``alias = command`` per line. Only ``argv[0]`` is expanded, one level.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Mapping

from .parser import _find_subparsers_action

RC_NAME = ".trimumrc"


class AliasError(Exception):
    """Raised when an alias config is malformed or collides with a command."""


def find_config() -> Path | None:
    """First existing ``.trimumrc`` by priority, else ``None``."""
    paths: list[Path] = []
    home = os.environ.get("TRIMUM_HOME", "").strip()
    if home:
        paths.append(Path(home).expanduser() / RC_NAME)
    paths.append(Path.home() / RC_NAME)
    paths.append(Path.cwd() / RC_NAME)
    for path in paths:
        if path.is_file():
            return path
    return None


def load_aliases(path: Path) -> dict[str, str]:
    """Parse ``alias = command`` lines; blank/``#`` lines are skipped."""
    aliases: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise AliasError(f"{RC_NAME} 第 {number} 行：缺少 '='")
        alias, _, command = line.partition("=")
        alias = alias.strip()
        command = command.strip()
        if not alias:
            raise AliasError(f"{RC_NAME} 第 {number} 行：别名为空")
        if not command:
            raise AliasError(f"{RC_NAME} 第 {number} 行：命令为空")
        if any(ch.isspace() for ch in alias):
            raise AliasError(f"{RC_NAME} 第 {number} 行：别名含空白")
        if any(ch.isspace() for ch in command):
            raise AliasError(f"{RC_NAME} 第 {number} 行：命令含空白")
        aliases[alias] = command
    return aliases


def expand_argv(argv: list[str], parser: argparse.ArgumentParser) -> list[str]:
    """Expand ``argv[0]`` against ``.trimumrc`` aliases, one level, non-mutating."""
    if not argv or argv[0].startswith("-"):
        return list(argv)
    config = find_config()
    if config is None:
        return list(argv)
    aliases = load_aliases(config)
    first = argv[0]
    if first not in aliases:
        return list(argv)
    command = aliases[first]
    action = _find_subparsers_action(parser)
    if action is not None:
        known = set(getattr(action, "choices", {}) or {})
        if first in known:
            raise AliasError(f"别名 '{first}' 与已有命令冲突")
    return [command, *argv[1:]]
