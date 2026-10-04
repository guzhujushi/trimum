"""Per-user data root for trimum.

Everything trimum owns lives under one directory — ``~/.trimum`` on a normal
install.  Resolving it through a single function keeps three future doors open:

* **multi-user** (docs/ECOSYSTEM-STRATEGY.md §7.2): each user gets its own root,
  so per-user ``certs/`` ``identity/`` ``skills/`` ``tools/`` stay separated;
* **system-wide assets**: a later ``/etc/trimum`` for the official trust root and
  shared tools can be layered next to it;
* **tests and provisioning**: ``TRIMUM_HOME`` points at a throwaway root instead
  of the real home directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

#: Override the data root (tests, provisioning, future per-user profiles).
HOME_ENV = "TRIMUM_HOME"

#: Subdirectories the wizard creates on first run.  ``agent-skills`` is the
#: fallback skill target used when no third-party harness is installed at all.
DATA_SUBDIRS = (
    "agents",
    "agent-skills",
    "certs",
    "config",
    "identity",
    "learning",
    "mcp",
    "memory",
    "sessions",
    "skills",
    "tools",
    "workflows",
)


def trimum_home() -> Path:
    """Return the trimum data root, honouring ``TRIMUM_HOME``."""
    override = os.environ.get(HOME_ENV)
    if override and override.strip():
        return Path(override).expanduser()
    return Path.home() / ".trimum"


def trimum_path(*parts: str) -> Path:
    """Return a path inside the trimum data root."""
    return trimum_home().joinpath(*parts)


def data_dir(name: str, *, env: str | None = None, config: Any = None) -> Path:
    """解析数据子目录。优先级：显式 env 变量 → 配置文件 ``paths.<name>`` → 默认 ``<TRIMUM_HOME>/<name>``。"""
    if env:
        value = os.environ.get(env)
        if value and value.strip():
            return Path(value).expanduser()
    if config is None:
        from .config import Config

        config = Config()
    try:
        raw = config.get(f"paths.{name}", None)
        if isinstance(raw, str) and raw.strip():
            return Path(raw).expanduser()
    except Exception:
        pass
    return trimum_path(name)


def ensure_trimum_home(*, subdirs: tuple[str, ...] = DATA_SUBDIRS) -> Path:
    """Create the data root (and its known subdirectories) if missing."""
    root = trimum_home()
    root.mkdir(parents=True, exist_ok=True)
    for name in subdirs:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


__all__ = [
    "HOME_ENV",
    "DATA_SUBDIRS",
    "trimum_home",
    "trimum_path",
    "ensure_trimum_home",
    "data_dir",
]