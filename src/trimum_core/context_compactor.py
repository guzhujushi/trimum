"""Context Compactor — Agent 循环的上下文窗口管理。

背景（Phase 3 收尾差距审计 P0）：
``AgentLoop`` 之前只是把历史 ``context[-5:]`` 拼成 JSON 再硬截 3000 字符，
工具输出没有任何限长，长输出（日志、diff、目录树）会把上下文预算吃光，
早期的步骤信息也会被整体丢弃。

职责（单一职责，不做 LLM 摘要，纯规则）：
1. **工具输出限长** — 单条输出按 head/tail 保留，中间用省略标记替代
2. **滑窗** — 最近 N 步保留原文，更早的步骤压成一行摘要
3. **总预算** — 上下文总量控制在 ``max_context_chars`` 内，超出的按最新优先保留

Usage:
    compactor = ContextCompactor()
    text = compactor.build(context_history)   # context_history: [{"step": ..., "result": ...}]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class CompactionPolicy:
    """上下文压缩策略。"""

    max_output_chars: int = 2400   # 单条工具输出上限（须 <= max_context_chars）
    output_head_chars: int = 1600  # 截断时保留的头部
    output_tail_chars: int = 800   # 截断时保留的尾部
    recent_steps: int = 5          # 保留原文的最近步数
    max_context_chars: int = 3000  # 上下文总预算
    max_summary_chars: int = 160   # 单条早期步骤摘要上限


class ContextCompactor:
    """把 Agent 执行历史压成有预算上限的上下文文本。"""

    def __init__(self, policy: Optional[CompactionPolicy] = None) -> None:
        self.policy = policy or CompactionPolicy()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def truncate_output(self, text: Any) -> str:
        """单条工具输出限长：保留头尾，中间折叠。"""
        if text is None:
            return ""
        raw = text if isinstance(text, str) else str(text)
        limit = self.policy.max_output_chars
        if len(raw) <= limit:
            return raw

        head = raw[: self.policy.output_head_chars]
        tail = raw[-self.policy.output_tail_chars:] if self.policy.output_tail_chars else ""
        omitted = len(raw) - len(head) - len(tail)
        return f"{head}\n…（已省略 {omitted} 字符）…\n{tail}"

    def summarize_step(self, entry: dict[str, Any]) -> str:
        """把一条历史压成单行摘要。"""
        step = entry.get("step") or {}
        result = entry.get("result") or {}
        line = f"- {step.get('name', '步骤')}: {step.get('command', '')} → {result.get('status', 'unknown')}"
        detail = self._result_text(result)
        if detail:
            detail = detail.replace("\n", " ")
            if len(detail) > self.policy.max_summary_chars:
                detail = detail[: self.policy.max_summary_chars] + "…"
            line = f"{line} | {detail}"
        return line

    def build(self, history: list[dict[str, Any]]) -> str:
        """生成受预算约束的上下文文本（最新信息优先保留）。"""
        if not history:
            return ""

        policy = self.policy
        recent = list(history[-policy.recent_steps:])
        older = list(history[: len(history) - len(recent)])

        # 1) 最近步骤保留原文，从最新往回塞预算
        recent_blocks: list[str] = []
        used = 0
        dropped_recent = 0
        for entry in reversed(recent):
            block = self._render_step(entry)
            if recent_blocks and used + len(block) > policy.max_context_chars:
                dropped_recent += 1
                continue
            recent_blocks.append(block)
            used += len(block) + 1
        recent_blocks.reverse()

        # 2) 早期步骤摘要，用剩余预算从最新往回塞
        summary_lines = [self.summarize_step(entry) for entry in older]
        kept: list[str] = []
        for line in reversed(summary_lines):
            if used + len(line) + 1 > policy.max_context_chars:
                break
            kept.append(line)
            used += len(line) + 1
        kept.reverse()

        sections: list[str] = []
        if kept:
            sections.append("早期步骤摘要:\n" + "\n".join(kept))
        omitted_summaries = len(summary_lines) - len(kept)
        if omitted_summaries:
            sections.append(f"（另有 {omitted_summaries} 条早期步骤摘要因预算省略）")
        if recent_blocks:
            header = "最近步骤:"
            if dropped_recent:
                header = f"最近步骤（更早的 {dropped_recent} 条因预算省略）:"
            sections.append(header + "\n" + "\n".join(recent_blocks))
        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # 内部渲染
    # ------------------------------------------------------------------

    def _result_text(self, result: dict[str, Any]) -> str:
        text = result.get("output") or result.get("error") or ""
        return self.truncate_output(text)

    def _render_step(self, entry: dict[str, Any]) -> str:
        step = entry.get("step") or {}
        result = entry.get("result") or {}
        lines = [
            f"- 步骤: {step.get('name', '步骤')}",
            f"  命令: {step.get('command', '')}",
            f"  状态: {result.get('status', 'unknown')}",
        ]
        detail = self._result_text(result)
        if detail:
            lines.append(f"  输出:\n{detail}")
        return "\n".join(lines)


__all__ = ["CompactionPolicy", "ContextCompactor"]