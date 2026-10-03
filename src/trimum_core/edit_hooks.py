"""E7 coding-agent 第 3 片（后半）：编辑前检查 / 编辑后提示钩子。

以总线订阅实现：命中保护路径或异常状态就**只提示**（默认不阻断），
需要时把命中的技能建议（``instruction_loader.plan_injection``）附在后面。
本模块只提示、不改写任何文件、不派生任何进程。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from . import patch_ops
from .instruction_loader import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_BODY_CHARS,
    DEFAULT_MAX_CHARS,
    plan_injection,
)
from .models import EventSeverity, SystemEvent

if TYPE_CHECKING:  # 只为类型注解，运行时不 import event_bus
    from .event_bus import EventBus

#: 总线事件名。
EDIT_PREVIEW_REQUESTED = "edit.preview_requested"   # 编辑前
EDIT_APPLIED = "edit.applied"                       # 编辑后
EDIT_ADVICE_PUBLISHED = "edit.advice_published"     # 钩子自己发出去的提示事件

#: 单条 advice 文本默认长度上限（超出按上限精确截断）。
DEFAULT_MAX_ADVICE_CHARS = 600

#: 判定结论（verdict）。
VERDICT_OK = "ok"
VERDICT_WARN = "warn"
VERDICT_BLOCKED = "blocked"

__all__ = [
    "EDIT_PREVIEW_REQUESTED",
    "EDIT_APPLIED",
    "EDIT_ADVICE_PUBLISHED",
    "DEFAULT_MAX_ADVICE_CHARS",
    "VERDICT_OK",
    "VERDICT_WARN",
    "VERDICT_BLOCKED",
    "EditHookNote",
    "BlockPolicy",
    "EditPreviewHook",
]


@dataclass(frozen=True)
class EditHookNote:
    """一次检查的结论：阶段、判定、技能建议与问题说明。"""

    stage: str                                  # EDIT_PREVIEW_REQUESTED | EDIT_APPLIED
    verdict: str                                # VERDICT_OK | VERDICT_WARN | VERDICT_BLOCKED
    advice: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    path: str = ""


@dataclass(frozen=True)
class BlockPolicy:
    """提示策略：默认只提示不阻断；可设阻断与单条建议长度上限。"""

    block_on_protected: bool = False            # 默认 False：只提示不阻断
    max_advice_chars: int = DEFAULT_MAX_ADVICE_CHARS


class EditPreviewHook:
    """订阅编辑前/后事件，产出只读提示（命中技能建议附在末尾）。"""

    def __init__(
        self,
        *,
        roots: Sequence[Path] | None = None,
        limit: int = DEFAULT_LIMIT,
        max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
        max_chars: int = DEFAULT_MAX_CHARS,
        policy: BlockPolicy | None = None,
    ) -> None:
        self._roots = list(roots) if roots is not None else None
        self._limit = limit
        self._max_body_chars = max_body_chars
        self._max_chars = max_chars
        self._policy = policy if policy is not None else BlockPolicy()
        self._bus: "EventBus | None" = None

    @property
    def policy(self) -> BlockPolicy:
        return self._policy

    # ------------------------------------------------------------------
    # 总线接线
    # ------------------------------------------------------------------

    def attach_to(self, bus: "EventBus | None") -> None:
        if bus is None:
            return
        self.detach_from(self._bus)
        bus.subscribe(EDIT_PREVIEW_REQUESTED, self._on_preview_requested)
        bus.subscribe(EDIT_APPLIED, self._on_applied)
        self._bus = bus

    def detach_from(self, bus: "EventBus | None") -> None:
        if bus is None:
            return
        bus.unsubscribe(EDIT_PREVIEW_REQUESTED, self._on_preview_requested)
        bus.unsubscribe(EDIT_APPLIED, self._on_applied)
        if self._bus is bus:
            self._bus = None

    async def _on_preview_requested(self, event: SystemEvent) -> None:
        note = self.advise_preview(*self._read_payload(event))
        await self._publish_note(note)

    async def _on_applied(self, event: SystemEvent) -> None:
        note = self.advise_applied(*self._read_payload(event))
        await self._publish_note(note)

    @staticmethod
    def _read_payload(event: SystemEvent) -> tuple[str, str]:
        """从 ``event.payload`` 取 path/summary；非 dict 或取不到都按空串，绝不抛。"""
        payload = event.payload
        if not isinstance(payload, dict):
            return "", ""
        path = payload.get("path", "")
        summary = payload.get("summary", "")
        return ("" if path is None else str(path),
                "" if summary is None else str(summary))

    async def _publish_note(self, note: EditHookNote) -> None:
        if self._bus is None:
            return
        severity = (
            EventSeverity.INFO if note.verdict == VERDICT_OK
            else EventSeverity.WARNING
        )
        await self._bus.publish(SystemEvent(
            event_type=EDIT_ADVICE_PUBLISHED,
            source=f"edit_hooks:{note.stage}",
            severity=severity,
            payload={
                "stage": note.stage,
                "verdict": note.verdict,
                "path": note.path,
                "advice": list(note.advice),
                "problems": list(note.problems),
            },
        ))

    # ------------------------------------------------------------------
    # 判定（纯函数，不触网、不写盘、不派生进程）
    # ------------------------------------------------------------------

    def advise_preview(self, path: str, summary: str = "") -> EditHookNote:
        return self._advise(EDIT_PREVIEW_REQUESTED, path, summary)

    def advise_applied(self, path: str, summary: str = "") -> EditHookNote:
        return self._advise(EDIT_APPLIED, path, summary)

    def _advise(self, stage: str, path: str, summary: str) -> EditHookNote:
        problems: list[str] = []
        verdict = VERDICT_OK
        resolved = ""

        stripped = (path or "").strip()
        if not stripped:
            return EditHookNote(
                stage=stage,
                verdict=VERDICT_WARN,
                problems=("缺少待编辑路径，拿不准一律按 warn 处理（没跑成永远不是 ok）",),
                advice=(),
            )

        resolved = str(Path(stripped).expanduser())
        if patch_ops.is_protected_path(resolved):
            verdict = (
                VERDICT_BLOCKED if self._policy.block_on_protected
                else VERDICT_WARN
            )
            problems.append(f"保护路径，编辑前需人工确认：{resolved}")

        if stage == EDIT_APPLIED and verdict == VERDICT_OK:
            if not Path(resolved).exists():
                verdict = VERDICT_WARN
                problems.append(
                    f"编辑后目标不存在，改动可能没落盘（没有真正写入）：{resolved}"
                )

        advice: list[str] = []
        try:
            plan = plan_injection(
                summary or resolved,
                roots=self._roots,
                limit=self._limit,
                max_body_chars=self._max_body_chars,
                max_chars=self._max_chars,
            )
            if plan.text:
                clipped = self._clip(plan.text)
                if clipped:
                    advice.append(clipped)
            if plan.dropped:
                dropped = self._clip(
                    "未注入的技能（超出上限）：" + ", ".join(plan.dropped)
                )
                if dropped:
                    advice.append(dropped)
        except Exception as exc:  # 注入不可用按拿不准处理，绝不外抛
            if verdict == VERDICT_OK:
                verdict = VERDICT_WARN
            problems.append(
                f"技能注入不可用（按拿不准处理）：{type(exc).__name__}: {exc}"
            )

        return EditHookNote(
            stage=stage,
            verdict=verdict,
            advice=tuple(advice),
            problems=tuple(problems),
            path=resolved,
        )

    def _clip(self, text: str) -> str:
        """单条 advice 裁剪：超上限精确截断；上限 <= 0 不产出（返回空串）。"""
        limit = self._policy.max_advice_chars
        if limit <= 0 or not text:
            return ""
        return text[:limit]
