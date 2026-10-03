"""技能与规则运行时 —— 按任务关键词把技能内容注入上下文（E7 第 3 片，前半）。

扫描技能根目录（复用 :mod:`trimum_core.skill_sync` 的源根口径），解析新格式
``SKILL.md``（复用 :mod:`trimum_core.skill_import.read_frontmatter`）与旧格式
``skill.yaml``（复用 :mod:`trimum_core.skill_loader.parse_skill_yaml`），
按任务文本里的关键词命中，把命中的技能正文渲染成一段有长度上限的文本。

纪律：本模块只读文本、不派生任何进程、不运行技能里的任何内容 ——
技能正文里的命令行只是文本，原样渲染出去。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import skill_sync
from .skill_import import AGENT_SKILL_FILE, TRIMUM_SKILL_FILE, read_frontmatter
from .skill_loader import parse_skill_yaml

KIND_AGENT_SKILL = "skill-md"       # 新格式 SKILL.md
KIND_TRIMUM_SKILL = "skill-yaml"    # 旧格式 skill.yaml

DEFAULT_LIMIT = 3
DEFAULT_MAX_BODY_CHARS = 1200
DEFAULT_MAX_CHARS = 4000
TRUNCATION_MARK = "\n…（已截断）"


@dataclass(frozen=True)
class InstructionBlock:
    """一条技能（或其旧格式等价物），正文是纯文本。"""

    name: str
    description: str
    keywords: tuple[str, ...]
    body: str
    path: str
    kind: str


@dataclass(frozen=True)
class MatchedInstruction:
    """命中任务文本的一条技能；``truncated`` 只表示单块正文被 ``max_body_chars`` 截了。"""

    block: InstructionBlock
    matched: tuple[str, ...]
    truncated: bool = False


@dataclass(frozen=True)
class InjectionPlan:
    """一次注入的完整结果：进了上下文什么、丢了什么、扫描时报过什么问题。"""

    text: str
    used: tuple[MatchedInstruction, ...] = ()
    dropped: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()


def default_instruction_roots() -> list[Path]:
    """技能源根，口径与 skill 分发一致：``<TRIMUM_HOME>/skills`` →（可选覆盖）→ 仓库 ``skills/``。"""
    return list(skill_sync.default_source_roots())


def load_instructions(
    roots: Sequence[Path] | None = None,
) -> tuple[list[InstructionBlock], list[str]]:
    """按给定顺序扫描各根的子目录，返回按 name 升序的 blocks 与 problems。

    任何根不存在、技能文件损坏、重名都只记 problems，不抛异常、不中断扫描。
    """
    if roots is None:
        roots = default_instruction_roots()

    blocks: list[InstructionBlock] = []
    problems: list[str] = []
    seen: dict[str, str] = {}

    for root in roots:
        root = Path(root)
        if not root.is_dir():
            problems.append(f"技能根不存在，已跳过：{root}")
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if (child / AGENT_SKILL_FILE).is_file():
                front, fm_problems = read_frontmatter(child)
                if fm_problems:
                    problems.append(f"{child}：{'; '.join(fm_problems)}")
                    continue
                text = (child / AGENT_SKILL_FILE).read_text(encoding="utf-8")
                head, sep, body = text.lstrip()[3:].partition("\n---")
                block = InstructionBlock(
                    name=str(front.get("name") or child.name).strip(),
                    description=str(front.get("description") or "").strip(),
                    keywords=_keywords_from_frontmatter(front),
                    body=body.lstrip("\n").strip(),
                    path=str(child),
                    kind=KIND_AGENT_SKILL,
                )
            elif (child / TRIMUM_SKILL_FILE).is_file():
                try:
                    definition = parse_skill_yaml(str(child / TRIMUM_SKILL_FILE))
                except ValueError as exc:
                    problems.append(f"{child}：skill.yaml 解析失败，已跳过（{exc}）")
                    continue
                if definition is None:
                    problems.append(f"{child}：skill.yaml 解析失败，已跳过")
                    continue
                body = "\n".join(definition.experience + definition.prompts)
                if not body:
                    body = definition.description
                block = InstructionBlock(
                    name=definition.name,
                    description=definition.description,
                    keywords=_keywords_from_definition(definition.name, definition.description),
                    body=body,
                    path=str(child),
                    kind=KIND_TRIMUM_SKILL,
                )
            else:
                continue
            if block.name in seen:
                problems.append(f"重名技能被忽略：{block.name}（{block.path}）")
                continue
            seen[block.name] = block.path
            blocks.append(block)

    blocks.sort(key=lambda block: block.name)
    return blocks, problems


def _keywords_from_frontmatter(front: Mapping[str, Any]) -> tuple[str, ...]:
    """frontmatter 的 ``keywords``：list/tuple 逐项 str 化；字符串按 ASCII 逗号 ``,`` 切分。

    每项 strip、去空、按首次出现去重；为空时从 ``name`` / ``description`` 派生。
    """
    raw = front.get("keywords")
    items: list[str] = []
    if isinstance(raw, (list, tuple)):
        items = [str(item) for item in raw]
    elif isinstance(raw, str):
        items = raw.split(",")

    keywords: list[str] = []
    for item in items:
        token = item.strip()
        if token and token not in keywords:
            keywords.append(token)

    if not keywords:
        keywords = list(_keywords_from_definition(
            str(front.get("name") or ""),
            str(front.get("description") or ""),
        ))
    return tuple(keywords)


def _keywords_from_definition(name: str, description: str) -> list[str]:
    """从 name 与 description 派生关键词：``\\w``（含中文）切分、长度 ≥ 2、casefold、去重保序。"""
    tokens = re.split(r"[^\w]+", f"{name} {description}")
    keywords: list[str] = []
    for token in tokens:
        folded = token.casefold()
        if len(folded) >= 2 and folded not in keywords:
            keywords.append(folded)
    return keywords


def match_instructions(
    task: str,
    blocks: Sequence[InstructionBlock],
    *,
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> tuple[MatchedInstruction, ...]:
    """关键词子串命中（casefold，中英文都适用）；命中数为 0 的技能不进结果。

    排序决定注入顺序：命中数降序 → 命中关键词里最长者的长度降序 → name 升序。
    """
    folded_task = task.casefold()
    matches: list[MatchedInstruction] = []
    for block in blocks:
        hit = [kw for kw in block.keywords if kw.casefold() in folded_task]
        if not hit:
            continue
        body = block.body
        truncated = False
        if max_body_chars > 0 and len(body) > max_body_chars:
            if max_body_chars > len(TRUNCATION_MARK):
                body = body[: max_body_chars - len(TRUNCATION_MARK)] + TRUNCATION_MARK
            else:
                body = body[:max_body_chars]
            truncated = True
        shown = replace(block, body=body) if truncated else block
        matches.append(MatchedInstruction(block=shown, matched=tuple(hit), truncated=truncated))

    matches.sort(key=lambda m: (-len(m.matched), -max(len(k) for k in m.matched), m.block.name))
    return tuple(matches)


def _render_block(match: MatchedInstruction) -> str:
    if match.block.body:
        return f"### {match.block.name}\n{match.block.description}\n\n{match.block.body}"
    return f"### {match.block.name}\n{match.block.description}"


def render_injection(
    matches: Sequence[MatchedInstruction],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> InjectionPlan:
    """逐条拼注入文本；超过 ``max_chars`` 的条目进 ``dropped``，但第一条命中必须收下。

    第一条命中单独就超限时截断到 ``max_chars`` 并记进 ``used``。
    """
    used: list[MatchedInstruction] = []
    dropped: list[str] = []
    text = ""
    for index, match in enumerate(matches):
        chunk = _render_block(match)
        candidate = chunk if not text else f"{text}\n\n{chunk}"
        if len(candidate) <= max_chars:
            text = candidate
            used.append(match)
            continue
        if index == 0:
            if max_chars > len(TRUNCATION_MARK):
                text = chunk[: max_chars - len(TRUNCATION_MARK)] + TRUNCATION_MARK
            else:
                text = chunk[:max_chars]
            used.append(match)
        else:
            dropped.append(match.block.name)
    return InjectionPlan(text=text, used=tuple(used), dropped=tuple(dropped))


def plan_injection(
    task: str,
    *,
    roots: Sequence[Path] | None = None,
    limit: int = DEFAULT_LIMIT,
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> InjectionPlan:
    """串联：load → match → 取前 ``limit`` 条 → render；被 limit 截掉的名字并入 ``dropped``。"""
    blocks, problems = load_instructions(roots)
    matches = match_instructions(task, blocks, max_body_chars=max_body_chars)
    chosen, leftover = matches[:limit], matches[limit:]
    plan = render_injection(chosen, max_chars=max_chars)
    return InjectionPlan(
        text=plan.text,
        used=plan.used,
        dropped=plan.dropped + tuple(m.block.name for m in leftover),
        problems=tuple(problems),
    )


__all__ = [
    "KIND_AGENT_SKILL",
    "KIND_TRIMUM_SKILL",
    "DEFAULT_LIMIT",
    "DEFAULT_MAX_BODY_CHARS",
    "DEFAULT_MAX_CHARS",
    "TRUNCATION_MARK",
    "InstructionBlock",
    "MatchedInstruction",
    "InjectionPlan",
    "default_instruction_roots",
    "load_instructions",
    "match_instructions",
    "render_injection",
    "plan_injection",
]
