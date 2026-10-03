"""把 KEY=VALUE 形式的 .env 读进 os.environ（已存在的环境变量优先）。

为什么需要它：安装器会把 key 写进 ``~/.trimum/.env``，但工程里没有任何代码去读它 ——
于是在 daemon 里会出现「明明配了 key，``trm doctor`` 还是 MISSING」，只能靠人肉 export。

读取顺序（**按 key 叠加**：同一个 key 以先出现的文件为准，后面的文件只补它没有的 key）：
    1. ``TRIMUM_ENV_FILE``（显式指定，运维/测试用）
    2. ``$TRIMUM_HOME/.env``
    3. ``~/.trimum/.env``（安装器的默认落点）
    4. ``./.env``（在仓库里跑 CLI 时的开发便利）

默认**不覆盖**已经存在的环境变量：systemd / Shell 里显式设的更可信。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("trimum_core.env_file")

ENV_FILE_VAR = "TRIMUM_ENV_FILE"

_loaded = False


def candidate_paths() -> list[Path]:
    """按优先级列出候选 .env 路径。"""
    paths: list[Path] = []
    explicit = os.environ.get(ENV_FILE_VAR, "").strip()
    if explicit:
        paths.append(Path(explicit).expanduser())
    home = os.environ.get("TRIMUM_HOME", "").strip()
    if home:
        paths.append(Path(home).expanduser() / ".env")
    paths.append(Path.home() / ".trimum" / ".env")
    paths.append(Path.cwd() / ".env")
    return paths


def parse_env_file(text: str) -> dict[str, str]:
    """解析 .env 文本：空行与 ``#`` 注释跳过，容忍 ``export `` 前缀与成对引号。"""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env_file(path: Optional[Path] = None, *, override: bool = False) -> dict[str, str]:
    """读 .env 写进 ``os.environ``，返回本次新生效的键值（便于 doctor 展示/测试）。"""
    candidates = [Path(path)] if path is not None else candidate_paths()
    applied: dict[str, str] = {}
    loaded: list[str] = []
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            text = candidate.read_text(encoding="utf-8")
        except OSError as exc:  # 权限/编码问题不该拦住启动
            log.debug("env file 读不了：%s（%s）", candidate, exc)
            continue

        parsed = parse_env_file(text)
        if not parsed:
            continue
        for key, value in parsed.items():
            if not override and os.environ.get(key):
                continue
            os.environ[key] = value
            applied[key] = value
        loaded.append(str(candidate))
    if loaded:
        log.debug("env file 已加载：%s（本次生效 %d 个键）", ", ".join(loaded), len(applied))
    return applied


def ensure_loaded() -> None:
    """进程级只加载一次；CLI 与 daemon 入口各调一次即可。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    load_env_file()


def reset_loaded() -> None:
    """清掉「本进程已加载」标记，让下一次 ``ensure_loaded()`` 重新读盘。"""
    global _loaded
    _loaded = False
