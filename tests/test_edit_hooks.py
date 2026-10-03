"""edit_hooks 测试：编辑前检查 / 编辑后提示（只提示、不改写、不派生进程）。"""

from __future__ import annotations

import ast
import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import edit_hooks, patch_ops, paths
from trimum_core.edit_hooks import (
    EDIT_ADVICE_PUBLISHED,
    EDIT_APPLIED,
    EDIT_PREVIEW_REQUESTED,
    VERDICT_BLOCKED,
    VERDICT_OK,
    VERDICT_WARN,
    BlockPolicy,
    EditPreviewHook,
)
from trimum_core.event_bus import EventBus
from trimum_core.models import SystemEvent

REPO = Path(__file__).resolve().parents[1]


def _skill(root: Path, name: str, keywords: list[str], body: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\nname: %s\ndescription: 技能 %s\nkeywords: [%s]\n---\n\n%s\n"
        % (name, name, ", ".join(keywords), body),
        encoding="utf-8",
    )
    return root


def _make_skill_dir(tmp_path: Path, name: str = "banana", keywords=None,
                    body: str = "这是香蕉技能正文片段 BANANA_BODY。") -> Path:
    if keywords is None:
        keywords = ["香蕉"]
    return _skill(tmp_path, name, keywords, body)


def test_miss_no_injection(tmp_path):
    root = _make_skill_dir(tmp_path)
    hook = EditPreviewHook(roots=[root])
    note = hook.advise_preview(str(tmp_path / "lunch.py"), "今天午饭吃什么")
    assert note.advice == ()
    assert note.verdict == VERDICT_OK
    assert note.problems == ()


def test_hit_injects(tmp_path):
    root = _make_skill_dir(tmp_path)
    hook = EditPreviewHook(roots=[root])
    note = hook.advise_preview(str(tmp_path / "a.py"), "想吃香蕉")
    assert note.advice
    assert "BANANA_BODY" in note.advice[0]
    assert note.verdict == VERDICT_OK


def test_chinese_hit(tmp_path):
    root = _make_skill_dir(tmp_path, name="zh", keywords=["排障"],
                           body="中文技能正文片段 ZH_BODY。")
    hook = EditPreviewHook(roots=[root])
    note = hook.advise_preview(str(tmp_path / "a.py"), "排障流程怎么走")
    assert note.advice
    assert "ZH_BODY" in note.advice[0]


def test_case_insensitive_english(tmp_path):
    root = _make_skill_dir(tmp_path, name="rev", keywords=["Review"],
                           body="英文技能正文片段 REVIEW_BODY。")
    hook = EditPreviewHook(roots=[root])
    note = hook.advise_preview(str(tmp_path / "a.py"), "please review this")
    assert note.advice
    assert "REVIEW_BODY" in note.advice[0]


def test_protected_paths_default_warn(tmp_path):
    hook = EditPreviewHook()
    candidates = [
        str(tmp_path / ".git" / "config"),
        str(tmp_path / "a.pem"),
        str(tmp_path / ".env"),
        str(paths.trimum_path("certs", "x.txt")),
    ]
    for target in candidates:
        note = hook.advise_preview(target, "edit me")
        assert note.verdict == VERDICT_WARN, target
        assert any("保护路径" in pr for pr in note.problems), target


def test_protected_blocked_policy(tmp_path):
    hook = EditPreviewHook(policy=BlockPolicy(block_on_protected=True))
    note = hook.advise_preview(str(tmp_path / ".git/config"), "edit me")
    assert note.verdict == VERDICT_BLOCKED
    assert any("保护路径" in p for p in note.problems)


def test_protected_before_existence(tmp_path):
    hook = EditPreviewHook()
    note = hook.advise_applied(str(tmp_path / ".git" / "nope.txt"), "edit me")
    assert note.verdict == VERDICT_WARN
    joined = " | ".join(note.problems)
    assert "保护路径" in joined
    assert "没落盘" not in joined


def test_applied_missing_warn_preview_ok(tmp_path):
    hook = EditPreviewHook()
    target = str(tmp_path / "plain" / "a.py")
    applied = hook.advise_applied(target, "edit me")
    assert applied.verdict == VERDICT_WARN
    assert any("没落盘" in p for p in applied.problems)
    preview = hook.advise_preview(target, "edit me")
    assert preview.verdict == VERDICT_OK
    assert preview.problems == ()


def test_advice_length_cap(tmp_path):
    body = "长" * 500
    root = _make_skill_dir(tmp_path, name="long", keywords=["长"], body=body)
    capped = EditPreviewHook(roots=[root], policy=BlockPolicy(max_advice_chars=40))
    note = capped.advise_preview(str(tmp_path / "a.py"), "长")
    assert note.advice
    assert len(note.advice[0]) == 40
    assert len(body) > 40                # 注入原文确实比上限长，这条裁剪断言才有判别力
    assert body not in note.advice[0]    # 正文全文没有泄漏进 advice

    default = EditPreviewHook(roots=[root])
    note2 = default.advise_preview(str(tmp_path / "a.py"), "长")
    assert all(len(item) <= 600 for item in note2.advice)

    zero = EditPreviewHook(roots=[root], policy=BlockPolicy(max_advice_chars=0))
    note3 = zero.advise_preview(str(tmp_path / "a.py"), "长")
    assert note3.advice == ()


def test_empty_path_warn(tmp_path):
    hook = EditPreviewHook()
    for blank in ("", "   "):
        note = hook.advise_preview(blank, "anything")
        assert note.verdict == VERDICT_WARN
        assert note.problems
        assert note.advice == ()


def test_injection_exception_degrades(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise RuntimeError("注入炸了")

    monkeypatch.setattr(edit_hooks, "plan_injection", boom)
    hook = EditPreviewHook()
    note = hook.advise_preview(str(tmp_path / "ok.py"), "x")
    assert note.verdict == VERDICT_WARN
    assert any("RuntimeError" in p for p in note.problems)
    assert note.advice == ()


def test_bus_end_to_end(tmp_path):
    root = _make_skill_dir(tmp_path)
    target = str(tmp_path / "plain.py")

    async def run():
        bus = EventBus()
        hook = EditPreviewHook(roots=[root])
        received: list[SystemEvent] = []
        bus.subscribe(EDIT_ADVICE_PUBLISHED, lambda ev: received.append(ev))
        hook.attach_to(bus)

        await bus.publish(SystemEvent(
            event_type=EDIT_PREVIEW_REQUESTED, source="t",
            payload={"path": target, "summary": "想吃香蕉"},
        ))
        for _ in range(10):
            await asyncio.sleep(0)

        await bus.publish(SystemEvent(
            event_type=EDIT_APPLIED, source="t",
            payload={"path": target, "summary": "想吃香蕉"},
        ))
        for _ in range(10):
            await asyncio.sleep(0)
        return received

    received = asyncio.run(run())
    assert len(received) == 2
    first, second = received
    assert first.event_type == EDIT_ADVICE_PUBLISHED
    assert first.source == "edit_hooks:edit.preview_requested"
    assert first.payload["stage"] == EDIT_PREVIEW_REQUESTED
    assert first.payload["verdict"] == VERDICT_OK
    assert first.payload["advice"]
    assert "BANANA_BODY" in first.payload["advice"][0]
    assert second.payload["stage"] == EDIT_APPLIED
    assert second.source == "edit_hooks:edit.applied"


def test_attach_none_and_detach(tmp_path):
    root = _make_skill_dir(tmp_path)

    async def run():
        hook = EditPreviewHook(roots=[root])
        hook.attach_to(None)  # 不炸
        bus = EventBus()
        received: list[SystemEvent] = []
        bus.subscribe(EDIT_ADVICE_PUBLISHED, lambda ev: received.append(ev))
        hook.attach_to(bus)
        for _ in range(2):
            hook.attach_to(bus)  # 重复 attach 不挂两份
        await bus.publish(SystemEvent(
            event_type=EDIT_PREVIEW_REQUESTED, source="t",
            payload={"path": str(tmp_path / "a.py"), "summary": "香蕉"},
        ))
        for _ in range(10):
            await asyncio.sleep(0)
        assert len(received) == 1  # 重复 attach 只收到一份

        hook.detach_from(bus)
        await bus.publish(SystemEvent(
            event_type=EDIT_PREVIEW_REQUESTED, source="t",
            payload={"path": str(tmp_path / "a.py"), "summary": "香蕉"},
        ))
        for _ in range(10):
            await asyncio.sleep(0)
        assert len(received) == 1  # detach 后不再收到
        hook.detach_from(None)  # 不炸
        return received

    received = asyncio.run(run())
    assert len(received) == 1


def test_payload_not_dict(tmp_path):
    root = _make_skill_dir(tmp_path)
    hook = EditPreviewHook(roots=[root])
    # SystemEvent 的 payload 有 dict 校验，这里用 model_construct 绕过，
    # 直接喂一个非 dict 的 payload，走回调路径验证「不抛异常」。
    event = SystemEvent.model_construct(
        event_type=EDIT_PREVIEW_REQUESTED, source="t", payload=[1, 2],
    )
    note = hook.advise_preview(*EditPreviewHook._read_payload(event))
    assert note.verdict == VERDICT_WARN
    assert note.path == ""
    # 回调本身也不抛
    asyncio.run(hook._on_preview_requested(event))


def test_is_protected_path(tmp_path):
    assert patch_ops.is_protected_path(str(tmp_path / ".git" / "x"))
    assert patch_ops.is_protected_path(str(tmp_path / "x.pem"))
    assert patch_ops.is_protected_path(str(tmp_path / ".env"))
    assert patch_ops.is_protected_path(str(paths.trimum_path("certs", "x")))
    assert not patch_ops.is_protected_path(str(tmp_path / "ok.py"))
    assert patch_ops.is_protected_path(None)   # 非路径类型：拿不准一律按受保护，且绝不抛异常
    assert patch_ops.is_protected_path(123)
    assert "is_protected_path" in patch_ops.__all__


def test_real_repo_integration():
    hook = EditPreviewHook(roots=[REPO / "skills"])
    note = hook.advise_preview(
        "src/trimum_core/edit_hooks.py", "pytest 跑红了一片，怎么定位"
    )
    assert note.advice
    assert note.verdict == VERDICT_OK


def test_redline_source_clean():
    src = inspect.getsource(edit_hooks)
    for literal in (
        "subprocess", "os.system", "popen",
        "write_text", "write_bytes", '"open("', "open(",
        "unlink", "rmtree", "shutil",
        "replace_anchor", "apply_difference", "rollback",
        "eval(", "exec(",
    ):
        assert literal not in src, literal

    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "subprocess" not in imported
    assert "os" not in imported
    assert "shutil" not in imported
