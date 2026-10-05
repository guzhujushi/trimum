"""拉起 codex CLI 的薄封装（决策 18：workflow 节点可以直接拉起 codex 窗口）。

本模块只做「解析命令行 + 把 prompt 填进 argv」，不执行、不做沙箱裁决 —— 执行在
``workflow_runtime._handle_codex_node`` 里。命令行一律配置优先（决策 24）：

    env ``TRIMUM_CODEX_CMD`` > 配置 ``workflows.codex.command`` > ``DEFAULT_CODEX_ARGV``

缺失 / 坏配置 / 该项为空 一律静默走默认，**不许抛**（决策 24）。
"""

from __future__ import annotations

import os
import shlex
from typing import Any, Mapping

#: 覆盖 codex 命令行的环境变量
CODEX_CMD_ENV = "TRIMUM_CODEX_CMD"

#: 配置文件里的点分键
CODEX_CMD_KEY = "workflows.codex.command"

#: 默认命令行：安全档 workspace-write。真机若沙箱不可用，由运营者在配置里显式覆盖。
DEFAULT_CODEX_ARGV = ("codex", "exec", "--skip-git-repo-check", "-s", "workspace-write")

#: prompt 占位符
PROMPT_PLACEHOLDER = "{prompt}"


def _split(value: Any) -> list[str] | None:
    """把配置值规范成 argv：str ⇒ shlex.split；list/tuple ⇒ 逐项 str；其它/空 ⇒ None。"""
    if isinstance(value, str):
        parts = shlex.split(value)
    elif isinstance(value, (list, tuple)):
        parts = [str(part) for part in value]
    else:
        return None
    return [part for part in parts if part] or None


def _config_command(config: Any = None) -> Any:
    """读配置里的 codex 命令行；配置缺失/坏/抛异常 ⇒ None（走默认）。"""
    if config is not None:
        try:
            return config.get(CODEX_CMD_KEY, None)
        except Exception:
            return None
    try:
        from .config import Config

        return Config().get(CODEX_CMD_KEY, None)
    except Exception:
        return None


def resolve_codex_argv(
    prompt: str,
    *,
    env: Mapping[str, str] | None = None,
    config: Any = None,
) -> list[str]:
    """按 env > 配置 > 默认 解析出拉起 codex 的 argv，并把 ``prompt`` 填进去。"""
    environ = os.environ if env is None else env
    raw_env = environ.get(CODEX_CMD_ENV) or ""
    argv = _split(raw_env)
    if argv is None:
        argv = _split(_config_command(config))
    if argv is None:
        argv = list(DEFAULT_CODEX_ARGV)

    text = str(prompt or "")
    if any(PROMPT_PLACEHOLDER in token for token in argv):
        return [token.replace(PROMPT_PLACEHOLDER, text) for token in argv]
    return [*argv, text]


__all__ = [
    "CODEX_CMD_ENV",
    "CODEX_CMD_KEY",
    "DEFAULT_CODEX_ARGV",
    "PROMPT_PLACEHOLDER",
    "resolve_codex_argv",
]
