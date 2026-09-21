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
from rich.console import RenderResult
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Confirm, Prompt
from rich.status import Status
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .event_bus import NAMESPACE_EVENT, EventBus, SystemEvent

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
        # 订阅表：(pattern, callback) —— 进度（<namespace>.*）与安全告警（security.*）两棵命名空间
        self._subscriptions: list[tuple[str, Any]] = []
        # 同一个（种类, 名字）连播两次就不重复打印：直接调用与事件订阅会撞车
        self._last_step_key: Optional[tuple[str, str]] = None

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

    def _already_shown(self, kind: str, name: str) -> bool:
        """同一个（种类, 名字）连着来两次 → 不重复打印。

        为什么会有连着两次：``AgentLoop`` 既直接调 ``step_*``，又通过 Event Bus 订阅
        ``task.*``（两条路都在，重复打印只是噪音）。
        """
        key = (kind, name)
        if self._last_step_key == key:
            return True
        self._last_step_key = key
        return False

    def step_start(self, name: str):
        if self._already_shown("start", name):
            return
        _console.print(f"   [{Text('进行中', style='bold cyan')}] {name}")

    def step_done(self, name: str, detail: str = ""):
        if self._already_shown("done", name):
            return
        msg = f"  ✅ [bold]{name}[/]"
        if detail:
            msg += f" — {detail}"
        _console.print(msg)

    def step_skip(self, name: str, reason: str = ""):
        if self._already_shown("skip", name):
            return
        _console.print(f"  ⏭ [{Text('跳过', style='dim')}] {name}"
                      f"{' — ' + reason if reason else ''}")

    def step_output(self, text: str):
        """显示命令输出（缩进）。"""
        if text.strip():
            for line in text.strip().split("\n"):
                _console.print(f"    {Text(line, style='dim')}")

    # ── Event 流订阅 ──

    async def subscribe_events(self, namespace: str = "agent"):
        """订阅 Event Bus 的任务进度事件并显示。

        匹配按**段**判（``task.started`` / ``task.node.started`` / ``event.task.started``
        都算 ``started``）：以前按全等比较，于是除了 ``AgentLoop`` 自己发的
        ``task.started``，其余（含引擎的 ``task.node.started``）都点不亮。
        安全告警按后缀判（``security.alert`` 与 ``event.security.alert`` 都收）。
        订阅两棵命名空间：``<namespace>.*`` 收进度、``security.*`` 收告警 —— 以前只订前者，
        于是告警那条分支从来没有被喂到过。
        """
        if not self.event_bus:
            self.warning("Event Bus 未配置，无法订阅事件")
            return

        async def _handler(event: SystemEvent):
            event_type = event.event_type
            payload = event.payload or {}
            segments = event_type.split(".")
            kind = segments[-1]
            name = payload.get("name", "未知任务")

            if "task" in segments and kind == "started":
                self.step_start(name)
            elif "task" in segments and kind == "completed":
                self.step_done(name)
            elif "task" in segments and kind == "skipped":
                self.step_skip(name, payload.get("reason", ""))
            elif event_type.endswith("security.alert"):
                self.warning(f"安全告警: {payload.get('detail', '')}")

        # 告警两种前缀都有人发：SecExecutor 直接造 ``security.alert``，
        # 走 emit_event 的则是 ``event.security.alert``
        patterns = [f"{namespace}.*", "security.*", f"{NAMESPACE_EVENT}security.*"]
        for pattern in patterns:
            self.event_bus.subscribe(pattern, _handler)
            self._subscriptions.append((pattern, _handler))

    def unsubscribe(self):
        """取消事件订阅（进度与安全告警一起摘）。"""
        if self.event_bus:
            for pattern, callback in self._subscriptions:
                self.event_bus.unsubscribe(pattern, callback)
        self._subscriptions = []

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


__all__ = ["LiveConsole", "TokenStatusPanel"]


class TokenStatusPanel:
    """Rich renderable for live token + resource tracking during interactive sessions."""

    def __init__(self):
        self._agent_id: str = ""
        self.refresh_interval: float = 2.0
        self._refresh_interval: float = self.refresh_interval
        self._cpu_percent: float = 0.0
        self._memory_mb: float = 0.0
        self._memory_limit_mb: float = 512.0
        self._token_used: int = 0
        self._token_limit: int = 0
        self._calls_5min: int = 0
        self._calls_limit: int = 0

    def set_agent(self, agent_id: str) -> None:
        """设置当前 agent。"""
        self._agent_id = agent_id

    def update(
        self,
        cpu_percent: float = 0,
        memory_mb: float = 0,
        token_used: int = 0,
        token_limit: int = 0,
        calls_5min: int = 0,
        calls_limit: int = 0,
    ) -> None:
        """由 AgentLoop 调用推送新数据。"""
        self._cpu_percent = cpu_percent
        self._memory_mb = memory_mb
        self._token_used = token_used
        self._token_limit = token_limit
        self._calls_5min = calls_5min
        self._calls_limit = calls_limit

    def __rich_console__(self, console, options) -> RenderResult:
        """渲染 Rich Panel。"""
        token_ratio = self._ratio(self._token_used, self._token_limit)
        cpu_ratio = self._ratio(self._cpu_percent, 100.0)
        memory_ratio = self._ratio(self._memory_mb, self._memory_limit_mb)
        calls_ratio = self._ratio(self._calls_5min, self._calls_limit)

        lines = [
            self._line("Token Usage", self._format_bar(token_ratio), f"{self._token_used} / {self._token_limit}"),
            self._line("CPU", self._format_bar(cpu_ratio), f"{self._cpu_percent:.1f}%"),
            self._line("Memory", self._format_bar(memory_ratio), f"{self._memory_mb:.0f} / {self._memory_limit_mb:.0f} MB"),
            self._line("Calls (5min)", self._format_bar(calls_ratio), f"{self._calls_5min} / {self._calls_limit}"),
        ]

        yield Panel(Text("\n".join(lines)), expand=False)

    @staticmethod
    def _format_bar(ratio: float, width: int = 20) -> str:
        """返回如 ████████░░░░ 的 Unicode 进度条。"""
        filled = min(int(ratio * width), width)
        return "█" * filled + "░" * (width - filled)

    @staticmethod
    def _ratio(value: float, limit: float) -> float:
        """计算进度条比例，limit <= 0 时返回 0。"""
        if limit <= 0:
            return 0.0
        return max(0.0, min(value / limit, 1.0))

    @staticmethod
    def _line(label: str, bar: str, value: str) -> str:
        """生成一行左标签 + Unicode 进度条 + 右侧数值。"""
        return f"{label:<14}{bar}   {value}"
