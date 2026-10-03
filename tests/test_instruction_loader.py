"""Tests for the instruction runtime —— E7 第 3 片（前半）.

只读技能文本、按任务关键词命中、渲染有长度上限的注入文本。
技能目录一律用 tmp_path 现造，不碰真实 ``~/.trimum``。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import instruction_loader as il  # noqa: E402
from trimum_core.instruction_loader import (  # noqa: E402
    KIND_AGENT_SKILL,
    KIND_TRIMUM_SKILL,
    TRUNCATION_MARK,
    InstructionBlock,
    MatchedInstruction,
    load_instructions,
    plan_injection,
)

REPO = Path(__file__).resolve().parents[1]


def _skill(root: Path, name: str, *, description: str = "一条测试技能。", keywords=None, body: str = "正文：第 1 步；第 2 步；第 3 步。") -> Path:
    """在 root 下造一个最小 SKILL.md 技能目录。"""
    directory = root / name
    directory.mkdir(parents=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if keywords is not None:
        lines.append(f"keywords: {keywords}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    lines.append(body)
    (directory / "SKILL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return directory


def _block(name: str, keywords, body: str = "正文") -> InstructionBlock:
    return InstructionBlock(
        name=name,
        description=f"{name} 的说明",
        keywords=tuple(keywords),
        body=body,
        path=f"/skills/{name}",
        kind=KIND_AGENT_SKILL,
    )


def _match(name: str, keywords, body: str = "正文", truncated: bool = False) -> MatchedInstruction:
    return MatchedInstruction(block=_block(name, keywords, body), matched=tuple(keywords), truncated=truncated)


# ---------------------------------------------------------------- 未命中 / 命中


def test_unmatched_task_injects_nothing(tmp_path):
    _skill(tmp_path, "alpha", keywords="[alpha, zeta]")
    plan = plan_injection("今天天气怎么样", roots=[tmp_path])
    assert plan.text == ""
    assert plan.used == ()
    assert plan.dropped == ()


def test_chinese_keyword_hits():
    plan = plan_injection("这次改动要先加测试再改代码", roots=[REPO / "skills"])
    names = [match.block.name for match in plan.used]
    assert "testing" in names


def test_case_insensitive_english():
    blocks = [_block("alpha", ["TDD"])]
    matches = il.match_instructions("Let's do tdd today", blocks)
    assert len(matches) == 1
    assert matches[0].matched == ("TDD",)


def test_keywords_as_comma_string(tmp_path):
    _skill(tmp_path, "alpha", keywords='"tdd, 红绿, pytest"')
    plan = plan_injection("跑 pytest 红了", roots=[tmp_path])
    assert plan.text != ""
    assert plan.used[0].block.name == "alpha"
    assert "pytest" in plan.used[0].matched


def test_keywords_derived_from_name_and_description(tmp_path):
    _skill(tmp_path, "delta", description="处理 delta 与 边界 的情况。")
    blocks, problems = load_instructions([tmp_path])
    assert problems == []
    assert blocks[0].name == "delta"
    # 派生：delta / 边界 保留（≥2 且 casefold）
    assert "delta" in blocks[0].keywords
    assert "边界" in blocks[0].keywords
    plan = plan_injection("这里有个边界问题", roots=[tmp_path])
    assert plan.used and plan.used[0].matched == ("边界",)


def test_derived_short_tokens_dropped(tmp_path):
    _skill(tmp_path, "ab", description="a b c。")
    blocks, _ = load_instructions([tmp_path])
    # name `ab` 本身 ≥2 保留；description 里的单字母 token 全丢
    assert blocks[0].keywords == ("ab",)
    plan = plan_injection("a b c", roots=[tmp_path])
    assert plan.text == ""


# ---------------------------------------------------------------- 排序


def test_sort_by_hit_count_desc():
    blocks = [_block("a", ["x"]), _block("b", ["x", "y", "z"]), _block("c", ["x", "y"])]
    matches = il.match_instructions("x y z", blocks)
    assert [m.block.name for m in matches] == ["b", "c", "a"]


def test_sort_by_longest_hit_keyword():
    """规则②要能判别：name 升序会把 aaa 排前面，最长命中关键词降序才把 zzz 排前面。"""
    blocks = [_block("zzz", ["abcdef"]), _block("aaa", ["ab"])]
    matches = il.match_instructions("abcdef ab", blocks)
    assert [m.block.name for m in matches] == ["zzz", "aaa"]


def test_sort_by_name_asc():
    blocks = [_block("z", ["same"]), _block("m", ["same"]), _block("a", ["same"])]
    matches = il.match_instructions("same", blocks)
    assert [m.block.name for m in matches] == ["a", "m", "z"]


# ---------------------------------------------------------------- body 截断


def test_body_truncated_to_exact_limit():
    body = "x" * 2000
    matches = il.match_instructions("alpha", [_block("alpha", ["alpha"], body)], max_body_chars=1200)
    assert len(matches) == 1
    assert matches[0].truncated is True
    assert len(matches[0].block.body) == 1200
    assert matches[0].block.body.endswith(TRUNCATION_MARK)


def test_body_not_truncated_under_limit():
    matches = il.match_instructions("alpha", [_block("alpha", ["alpha"], "短正文")], max_body_chars=1200)
    assert matches[0].truncated is False
    assert matches[0].block.body == "短正文"


def test_body_max_body_chars_non_positive_disables_truncation():
    matches = il.match_instructions("alpha", [_block("alpha", ["alpha"], "y" * 5000)], max_body_chars=0)
    assert matches[0].truncated is False
    assert len(matches[0].block.body) == 5000


def test_body_truncation_with_tiny_cap_is_exact():
    matches = il.match_instructions(
        "alpha", [_block("alpha", ["alpha"], "x" * 100)], max_body_chars=3
    )
    assert len(matches[0].block.body) == 3
    assert matches[0].truncated is True


# ---------------------------------------------------------------- 总长上限


def test_second_block_dropped_when_over_max_chars():
    first = _match("first", ["a"], body="f" * 100)
    second = _match("second", ["b"], body="s" * 100)
    plan = il.render_injection([first, second], max_chars=200)
    assert "### first" in plan.text
    assert "### second" not in plan.text
    assert [m.block.name for m in plan.used] == ["first"]
    assert plan.dropped == ("second",)


def test_first_block_truncated_but_kept():
    first = _match("first", ["a"], body="f" * 1000)
    plan = il.render_injection([first], max_chars=200)
    assert plan.text
    assert len(plan.text) == 200
    assert plan.text.endswith(TRUNCATION_MARK)
    assert [m.block.name for m in plan.used] == ["first"]
    assert plan.dropped == ()


def test_render_empty_matches():
    plan = il.render_injection([])
    assert plan.text == ""
    assert plan.used == ()
    assert plan.dropped == ()


def test_render_empty_body_omits_blank_lines():
    match = _match("empty", ["a"], body="")
    plan = il.render_injection([match])
    assert plan.text == "### empty\nempty 的说明"


# ---------------------------------------------------------------- limit


def test_limit_drops_extra_matches_into_dropped(tmp_path):
    for name in ("a", "b", "c", "d"):
        _skill(tmp_path, name, keywords="[k]")
    plan = plan_injection("k", roots=[tmp_path], limit=2)
    assert [m.block.name for m in plan.used] == ["a", "b"]
    assert plan.dropped == ("c", "d")


def test_limit_smaller_than_hits_on_real_repo_skills():
    """命中数 > limit 的真实路径（上一轮这里直接 AttributeError）。"""
    plan = plan_injection(
        "trm audit pytest 报错 定位 review 回归", roots=[REPO / "skills"], limit=1
    )
    assert len(plan.used) == 1
    assert len(plan.dropped) >= 1


def test_dropped_order_total_cap_first_then_limit(tmp_path):
    """dropped 顺序：先「被总长上限丢掉的」，再「被 limit 截掉的」。"""
    for name in ("a", "b", "c", "d"):
        _skill(tmp_path, name, keywords="[k]", body="z" * 300)
    plan = plan_injection("k", roots=[tmp_path], limit=3, max_chars=400)
    assert [m.block.name for m in plan.used] == ["a"]
    assert plan.dropped == ("b", "c", "d")


# ---------------------------------------------------------------- 根 / 损坏


def test_missing_root_recorded_not_raised(tmp_path):
    blocks, problems = load_instructions([tmp_path / "nope"])
    assert blocks == []
    assert problems == [f"技能根不存在，已跳过：{tmp_path / 'nope'}"]


def test_bad_frontmatter_skips_only_that_skill(tmp_path):
    _skill(tmp_path, "good", keywords="[ok]")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\nname: bad\n---\n\n# 没有 description\n", encoding="utf-8"
    )
    blocks, problems = load_instructions([tmp_path])
    assert [b.name for b in blocks] == ["good"]
    assert any("bad" in p for p in problems)
    assert any("description" in p for p in problems)


def test_skillless_subdir_silently_skipped(tmp_path):
    _skill(tmp_path, "good", keywords="[ok]")
    (tmp_path / "empty-dir").mkdir()
    (tmp_path / "empty-dir" / "notes.txt").write_text("不是技能", encoding="utf-8")
    blocks, problems = load_instructions([tmp_path])
    assert [b.name for b in blocks] == ["good"]
    assert problems == []


def test_duplicate_name_first_wins(tmp_path):
    first = tmp_path / "r1"
    second = tmp_path / "r2"
    _skill(first, "dup", description="第一条。", keywords="[dup]")
    _skill(second, "dup", description="第二条。", keywords="[dup]")
    blocks, problems = load_instructions([first, second])
    assert len(blocks) == 1
    assert blocks[0].description == "第一条。"
    assert any(p.startswith(f"重名技能被忽略：dup（{second / 'dup'}）") for p in problems)


def test_load_instructions_sorted_by_name(tmp_path):
    _skill(tmp_path, "zeta", keywords="[1]")
    _skill(tmp_path, "alpha", keywords="[2]")
    blocks, _ = load_instructions([tmp_path])
    assert [b.name for b in blocks] == ["alpha", "zeta"]


# ---------------------------------------------------------------- 旧格式


def test_legacy_skill_yaml_loads(tmp_path):
    directory = tmp_path / "legacy"
    directory.mkdir()
    (directory / "skill.yaml").write_text(
        "name: legacy\n"
        "description: 旧格式技能，演示加载。\n"
        "steps:\n"
        "  - tool: echo\n"
        "    args: []\n"
        "experience:\n"
        "  - 第 1 条经验\n"
        "  - 第 2 条经验\n",
        encoding="utf-8",
    )
    blocks, problems = load_instructions([tmp_path])
    assert problems == []
    assert len(blocks) == 1
    assert blocks[0].kind == KIND_TRIMUM_SKILL
    assert blocks[0].body == "第 1 条经验\n第 2 条经验"


def test_legacy_skill_yaml_bad_file_skipped(tmp_path):
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "skill.yaml").write_text("steps: []\n", encoding="utf-8")
    blocks, problems = load_instructions([tmp_path])
    assert blocks == []
    assert len(problems) == 1
    assert "skill.yaml" in problems[0]


# ---------------------------------------------------------------- 真实仓库


def test_repo_skills_discovered():
    blocks, problems = load_instructions([REPO / "skills"])
    names = {b.name for b in blocks}
    assert {"trm-cli", "testing", "code-review", "troubleshooting"} <= names
    for block in blocks:
        assert block.description, block.name


def test_repo_plan_hits_pytask():
    plan = plan_injection("pytest 跑红了一片，怎么定位", roots=[REPO / "skills"])
    assert plan.used
    assert plan.text


def test_repo_plan_miss_lunch():
    plan = plan_injection("今天午饭吃什么", roots=[REPO / "skills"])
    assert plan.text == ""
    assert plan.used == ()


# ---------------------------------------------------------------- 红线


def test_module_source_has_no_execution_primitives():
    source = inspect.getsource(il)
    for forbidden in ("subprocess", "os.system", "popen"):
        assert forbidden not in source, f"instruction_loader 源码里出现了 {forbidden!r}"
