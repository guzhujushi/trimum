"""Live console UI for trm exec — Rich-based terminal progress display.

功能：
- 步骤进度面板（计划列表 + 状态标记）
- 确认对话框（y/N）
- Event Bus 事件实时订阅显示
- 最终总结输出
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Confirm, Prompt
from rich.status import Status
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .event_bus import EventBus, SystemEvent

# Windows GBK 控制台不支持 emoji，自动降级
import sys
if sys.platform == "win32":
    _EMOJI_MAP: dict[str, str] = {}
def _sanitize(text: str) -> str:
    for emoji, repl in _EMOJI_MAP.items():
        text = text.replace(emoji, repl)
    return text


import os
_force_utf8 = os.environ.get("PYTHONIOENCODING", "").lower() == "utf-8" or sys.stdout.encoding == "utf-8"

_console = Console(force_terminal=not _force_utf8, color_system="auto")


class LiveConsole:
    """终端交互界面。

    用法：
        console = LiveConsole()
        console.print("Hello")
        confirmed = await console.confirm("删除文件?")
        console.show_plan(plan)
        console.step_done("完成")
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus
        self._progress: Optional[Progress] = None
        self._live: Optional[Live] = None
        self._subscription_id: Optional[str] = None

    # ── 基本输出 ──

    def print(self, *args, **kwargs):
        _console.print(*args, **kwargs)

    def info(self, msg: str, emoji: str = "ℹ"):
        _console.print(f" {emoji} {msg}")

    def success(self, msg: str):
        _console.print(f" ✅ {msg}")

    def warning(self, msg: str):
        _console.print(f" ⚠️  {msg}")

    def error(self, msg: str):
        _console.print(f" ❌ {msg}")

    def divider(self):
        _console.print("─" * 40)

    # ── 确认对话框 ──

    async def confirm(self, question: str, default: bool = False) -> bool:
        """询问用户确认。支持 --yes 环境变量跳过。"""
        # 支持环境变量 TRM_YES=1 跳过全部确认
        import os
        if os.environ.get("TRM_YES") == "1":
            self.info(f"自动确认 (TRM_YES): {question}")
            return True

        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None,
            lambda: Confirm.ask(f" [{Text('需要确认', style='bold yellow')}] {question}",
                                default=default),
        )
        return answer

    async def prompt(self, text: str, default: str = "") -> str:
        """请求用户输入文本。"""
        import os
        if os.environ.get("TRM_YES") == "1" and default:
            return default
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: Prompt.ask(text, default=default))

    # ── 计划展示 ──

    def show_plan(self, title: str, steps: list[dict]):
        """展示多步骤计划。

        steps: [{"name": "...", "description": "...", "risk": "low|medium|high"}, ...]
        """
        tree = Tree(f" 计划: {title}")
        for i, step in enumerate(steps, 1):
            risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🔴"}
            icon = risk_icon.get(step.get("risk", "low"), "⚪")
            name = step.get("name", f"Step {i}")
            desc = step.get("description", "")
            label = f"[bold]{icon} {i}. {name}[/]"
            if desc:
                label += f" — {desc}"
            tree.add(label)
        _console.print(tree)

    # ── 步骤状态 ──

    def step_start(self, name: str):
        _console.print(f"   [{Text('进行中', style='bold cyan')}] {name}")

    def step_done(self, name: str, detail: str = ""):
        msg = f"  ✅ [bold]{name}[/]"
        if detail:
            msg += f" — {detail}"
        _console.print(msg)

    def step_skip(self, name: str, reason: str = ""):
        _console.print(f"  ⏭ [{Text('跳过', style='dim')}] {name}"
                      f"{' — ' + reason if reason else ''}")

    def step_output(self, text: str):
        """显示命令输出（缩进）。"""
        if text.strip():
            for line in text.strip().split("\n"):
                _console.print(f"    {Text(line, style='dim')}")

    # ── Event 流订阅 ──

    async def subscribe_events(self, namespace: str = "agent"):
        """订阅 Event Bus 的任务进度事件并显示。"""
        if not self.event_bus:
            self.warning("Event Bus 未配置，无法订阅事件")
            return

        async def _handler(event: SystemEvent):
            event_type = event.event_type
            payload = event.payload or {}

            if event_type == "task.started":
                name = payload.get("name", "未知任务")
                self.step_start(name)
            elif event_type == "task.completed":
                name = payload.get("name", "未知任务")
                self.step_done(name)
            elif event_type == "task.skipped":
                name = payload.get("name", "未知任务")
                reason = payload.get("reason", "")
                self.step_skip(name, reason)
            elif event_type == "security.alert":
                detail = payload.get("detail", "")
                self.warning(f"安全告警: {detail}")

        self._subscription_id = self.event_bus.subscribe(
            f"{namespace}.*", _handler
        )

    def unsubscribe(self):
        """取消事件订阅。"""
        if self._subscription_id and self.event_bus:
            self.event_bus.unsubscribe(self._subscription_id)
            self._subscription_id = None

    # ── 进度条 ──

    @staticmethod
    def spinner(task: str) -> Status:
        """返回一个 spinner context manager 用于异步任务。"""
        return Status(f"  {task}...", console=_console)

    # ── 最终总结 ──

    def show_summary(self, results: list[dict]):
        """展示执行总结表。"""
        table = Table(title="执行总结", show_header=True, header_style="bold")
        table.add_column("步骤", style="cyan")
        table.add_column("状态", style="green")
        table.add_column("耗时", style="magenta")
        table.add_column("输出", style="white", max_width=40)

        for r in results:
            status_icon = "✅" if r.get("status") == "ok" else "❌"
            table.add_row(
                r.get("name", "?"),
                status_icon,
                f"{r.get('elapsed_ms', 0)}ms",
                r.get("output", "")[:40],
            )

        _console.print(table)


__all__ = ["LiveConsole"]
