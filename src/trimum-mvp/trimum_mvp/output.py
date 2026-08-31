"""Rich 输出格式化模块。

统一管理 CLI 的所有终端输出样式：
- 成功绿色 / 警告黄色 / 错误红色 / 信息蓝色
- 计划步骤、命令、风险级别的展示
- 风险级别 -> 颜色映射

平台安全（H-1 / M-4）：
- 窄编码终端（如 GBK/cp936）无法编码 ⚠/✔/✘ 等符号，
  按 sys.stdout.encoding 自动回退到 ASCII 符号（[!]/[OK]/[X]）。
- 所有不可信文本（命令输出、LLM 文案）以 markup=False / Text 渲染，
  避免 `[foo] bar` 被 rich 当作样式标签吞掉。
"""

from __future__ import annotations

import sys
from typing import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text


def _supports_unicode(encoding: str | None) -> bool:
    """判断终端编码是否支持非 ASCII 符号（⚠/✔/✘ 等）。"""
    if not encoding:
        return False
    enc = encoding.lower().replace("-", "").replace("_", "")
    return enc in ("utf8", "cp65001") or enc.startswith("utf")


def _select_symbols(encoding: str | None) -> dict[str, str]:
    """根据终端编码选择安全符号：GBK 等窄编码回退 ASCII。"""
    if _supports_unicode(encoding):
        return {"warn": "⚠", "ok": "✔", "err": "✘"}
    return {"warn": "[!]", "ok": "[OK]", "err": "[X]"}


class _SafeConsoleFile:
    """对无法按终端编码输出的字符做替换，避免 GBK 崩溃（H-1）。

    例如 cp936 终端输出包含 emoji 的命令输出时，
    UnicodeEncodeError 会被拦截并把不可编码字符替换为 '?'。
    """

    def __init__(self, stream: object) -> None:
        self._stream = stream
        self.encoding = getattr(stream, "encoding", None) or "utf-8"

    @property
    def closed(self) -> bool:
        return bool(getattr(self._stream, "closed", False))

    def write(self, text: str) -> int:
        data = text.encode(self.encoding, errors="replace").decode(self.encoding)
        return self._stream.write(data)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        try:
            return self._stream.isatty()
        except Exception:
            return False

    def fileno(self) -> int:
        return self._stream.fileno()


# 全局控制台（stderr 留给日志，stdout 输出主内容；窄编码终端安全回退）
console = Console(file=_SafeConsoleFile(sys.stdout))

# 平台安全符号（executor 等模块可复用）
SYMBOLS = _select_symbols(getattr(sys.stdout, "encoding", None))
WARN_SYMBOL = SYMBOLS["warn"]
OK_SYMBOL = SYMBOLS["ok"]
ERR_SYMBOL = SYMBOLS["err"]

# 风险级别 -> (显示名, 颜色)
RISK_STYLE: dict[str, tuple[str, str]] = {
    "low": ("低风险 Low", "green"),
    "medium": ("中风险 Medium", "yellow"),
    "high": ("高风险 High", "red"),
    "critical": ("关键风险 Critical", "bold red"),
}

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def risk_priority(risk: str) -> int:
    """返回风险级别的数值优先级（越大越危险）。"""
    return _RISK_ORDER.get(risk, 1)


def info(message: str) -> None:
    """蓝色信息输出（markup=False，避免 [x] 被解析为样式）。"""
    console.print(message, style="blue", markup=False)


def success(message: str) -> None:
    """绿色成功输出。"""
    console.print(message, style="green", markup=False)


def warning(message: str) -> None:
    """黄色警告输出。"""
    console.print(message, style="yellow", markup=False)


def error(message: str) -> None:
    """红色错误输出。"""
    console.print(message, style="red", markup=False)


def show_risk(risk: str, command: str | None = None) -> None:
    """按风险级别着色输出风险提示。"""
    name, color = RISK_STYLE.get(risk, (risk, "yellow"))
    label = Text(f"风险级别：{name}", style=color)
    if command:
        label.append(f"\n命令：{command}")
    console.print(label)


def show_plan(plan: Sequence[str]) -> None:
    """展示计划步骤（编号列表）。"""
    if not plan:
        return
    console.print("执行计划：", style="cyan", markup=False)
    for index, step in enumerate(plan, start=1):
        console.print(f"  {index}. {step}", style="cyan", markup=False)


def show_commands(commands: Sequence[str]) -> None:
    """展示将要执行的命令列表。"""
    if not commands:
        return
    console.print("我将运行：", style="cyan", markup=False)
    for command in commands:
        console.print(f"  {command}", style="bold", markup=False)


def show_output(output: str, error: bool = False) -> None:
    """展示命令输出（Text 渲染，避免 [word] 被当作样式标签）。"""
    if not output:
        return
    content = Text(output.rstrip("\n"))
    if error:
        console.print(Panel(content, title="stderr", border_style="red"))
    else:
        console.print(Panel(content, title="输出 Output", border_style="blue"))


def show_rejection(message: str) -> None:
    """展示拒绝信息。"""
    console.print(Panel(Text(message), title="已拒绝 Denied", border_style="bold red"))


def ask_confirm(question: str = "继续执行？ Continue? [y/N]", default: bool = False) -> bool:
    """Rich 交互式确认，返回用户是否同意。"""
    return Confirm.ask(f"[yellow]{question}[/yellow]", default=default)