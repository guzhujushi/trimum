"""源码卫生护栏（TODO P3①）：`src/**/*.py` 末行必须有换行符。

背景：`paths.py` 曾在 `cfg2left`（`86fa1be`）之前缺末行换行，仓库没有 .editorconfig /
pre-commit / ruff 之类机械护栏 ⇒ 用一条用例钉死，避免复发。
"""
from __future__ import annotations

from pathlib import Path


def _src_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src"


def test_all_source_files_end_with_newline():
    offenders = []
    for path in sorted(_src_root().rglob("*.py")):
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            offenders.append(str(path.relative_to(_src_root())))
    assert offenders == [], f"src/**/*.py 缺末行换行：{offenders}"


def test_all_source_files_are_utf8_decodable():
    """顺带钉住编码：不许有非 UTF-8 字节混进来。"""
    broken = []
    for path in sorted(_src_root().rglob("*.py")):
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            broken.append(str(path.relative_to(_src_root())))
    assert broken == [], f"src/**/*.py 非 UTF-8：{broken}"
