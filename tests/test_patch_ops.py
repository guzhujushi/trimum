"""E7 自研编码智能体 · 第 1 片 —— 编辑原语与会话留痕（``trimum_core.patch_ops``）。

覆盖：锚点替换（唯一 / 0 次 / 2 次 / 无差异）、``diff_text`` 往返、unified
diff 应用（上下文行不符 / hunk 越界 / 多文件 / 无换行标记）、保护路径
（``.git`` / ``certs`` / 秘密后缀 / ``.env`` → ``CWD_JAIL_VIOLATION``）、
``dry_run`` 不落盘不建快照，以及连改两次后 ``rollback`` 逐字节还原。

所有快照都通过 ``monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))`` 挪到临时目录，
不碰开发者真实的 ``~/.trimum``。
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import paths  # noqa: E402
from trimum_core import patch_ops  # noqa: E402
from trimum_core.models import TRMErrorCode, TrimumError  # noqa: E402

SESSION = "patch-test"


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
    return tmp_path


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _assert_code(err, code):
    assert err.code == code


# ① 锚点唯一 → 替换成功
def test_anchor_unique_applies(tmp_path):
    p = _write(tmp_path, "a.py", "alpha\nbeta\ngamma\n")
    res = patch_ops.replace_anchor(p, "beta", "BETA", session_id=SESSION)
    assert p.read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"
    assert res.status == "applied"
    assert res.difference
    # 与差异里 + / - 行的实际条数一致（不含 +++/--- 头）
    plus = sum(1 for ln in res.difference.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    minus = sum(1 for ln in res.difference.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    assert res.added_lines == plus == 1
    assert res.removed_lines == minus == 1
    assert res.snapshot_id is not None
    assert (paths.trimum_path("sessions", SESSION) / res.snapshot_id).exists()


# ② 锚点 0 次 → PATCH_REJECTED
def test_anchor_zero_times_rejected(tmp_path):
    p = _write(tmp_path, "a.py", "alpha\nbeta\n")
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.replace_anchor(p, "nope", "x", session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert "0" in excinfo.value.message
    assert p.read_text(encoding="utf-8") == "alpha\nbeta\n"


# ③ 锚点 2 次 → PATCH_REJECTED 且文件未改
def test_anchor_two_times_rejected(tmp_path):
    p = _write(tmp_path, "a.py", "dup\nmid\ndup\n")
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.replace_anchor(p, "dup", "DUP", session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert "2" in excinfo.value.message
    assert p.read_text(encoding="utf-8") == "dup\nmid\ndup\n"


# ④ 无差异 → PATCH_REJECTED
def test_no_diff_rejected(tmp_path):
    p = _write(tmp_path, "a.py", "same\n")
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.replace_anchor(p, "same", "same", session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert p.read_text(encoding="utf-8") == "same\n"


# ⑤ diff_text 往返
def test_diff_text_roundtrip(tmp_path):
    old = "line1\nline2\nline3\nline4\nline5\n"
    new = "line1\nline2-changed\nline3\nline4\nline5\nextra\n"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_text(encoding="utf-8") == new


# ⑥ 上下文行不符 → PATCH_REJECTED
def test_context_mismatch_rejected(tmp_path):
    p = _write(tmp_path, "a.py", "one\ntwo\nthree\n")
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,3 @@\n one\n- two\n+ TWO\n  three\n"
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.apply_difference(p, diff, session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert "context mismatch" in excinfo.value.message
    assert p.read_text(encoding="utf-8") == "one\ntwo\nthree\n"


# ⑦ hunk 行号越界 → PATCH_REJECTED
def test_hunk_out_of_bounds_rejected(tmp_path):
    p = _write(tmp_path, "a.py", "one\ntwo\nthree\n")
    diff = "--- a/a.py\n+++ b/a.py\n@@ -9,3 +9,3 @@\n  one\n- two\n+ TWO\n  three\n"
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.apply_difference(p, diff, session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert "out of bounds" in excinfo.value.message


# ⑧ 多文件 / 无换行标记 → PATCH_REJECTED
def test_multi_file_rejected(tmp_path):
    p = _write(tmp_path, "a.py", "one\ntwo\nthree\n")
    diff = (
        "--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,3 @@\n  one\n- two\n+ TWO\n  three\n"
        "--- a/b.py\n+++ b/b.py\n@@ -1,3 +1,3 @@\n  one\n- two\n+ TWO\n  three\n"
    )
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.apply_difference(p, diff, session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert "multi-file" in excinfo.value.message


# ⑨ 保护路径 → CWD_JAIL_VIOLATION
def test_protected_paths_jail(tmp_path):
    (tmp_path / "repo.git").mkdir(parents=True)
    gitconfig = _write(tmp_path / "repo.git", "config", "x = 1\n")

    (tmp_path / "certs").mkdir()
    pem = _write(tmp_path / "certs", "x.pem", "PEM\n")

    key = _write(tmp_path, "secret.key", "KEY\n")
    env = _write(tmp_path, ".env", "SECRET=1\n")

    for target in (gitconfig, pem, key, env):
        with pytest.raises(TrimumError) as excinfo:
            patch_ops.replace_anchor(target, "x", "y", session_id=SESSION)
        _assert_code(excinfo.value, TRMErrorCode.CWD_JAIL_VIOLATION)


# ⑩ dry_run：不改文件、不建 sessions/、status=preview
def test_dry_run_no_side_effects(tmp_path):
    p = _write(tmp_path, "a.py", "alpha\nbeta\ngamma\n")
    before = p.read_text(encoding="utf-8")
    mtime_before = p.stat().st_mtime_ns
    res = patch_ops.replace_anchor(p, "beta", "BETA", dry_run=True, session_id=SESSION)
    assert res.status == "preview"
    assert res.snapshot_id is None
    assert p.read_text(encoding="utf-8") == before
    assert p.stat().st_mtime_ns == mtime_before
    assert not paths.trimum_path("sessions").exists()


# ⑪ 回滚：连改两次后逐字节回到最初；快照已清
def test_rollback_restores_original(tmp_path):
    original = "alpha\nbeta\ngamma\n"
    p = _write(tmp_path, "a.py", original)
    patch_ops.replace_anchor(p, "beta", "BETA", session_id=SESSION)
    patch_ops.replace_anchor(p, "BETA", "BETA2", session_id=SESSION)
    assert p.read_text(encoding="utf-8") == "alpha\nBETA2\ngamma\n"

    sdir = paths.trimum_path("sessions", SESSION)
    snaps_before = sorted(f.name for f in sdir.iterdir() if f.suffix != ".json")
    assert snaps_before  # 应有快照

    restored = patch_ops.rollback(SESSION)
    assert p.read_bytes() == original.encode("utf-8")
    # 每个改动一条快照，逆序还原；同一文件被改两次 ⇒ 路径出现两次
    assert restored == [str(p), str(p)]
    # 快照文件被清掉
    snaps_after = [f for f in sdir.iterdir() if f.suffix != ".json"]
    assert snaps_after == []


def test_rollback_missing_session_raises(tmp_path):
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.rollback("no-such-session")
    _assert_code(excinfo.value, TRMErrorCode.FILE_NOT_FOUND)


# ⑫ 缺陷 1：末行无换行符 —— 三种往返
def test_diff_text_roundtrip_no_trailing_newline_both(tmp_path):
    """两侧都没有尾换行。"""
    old = "x\ny"
    new = "x\nZ"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


def test_diff_text_roundtrip_no_trailing_newline_old_only(tmp_path):
    """old 无尾换行，new 有尾换行。"""
    old = "x\ny"
    new = "x\nZ\n"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


def test_diff_text_roundtrip_no_trailing_newline_new_only(tmp_path):
    """old 有尾换行，new 无尾换行。"""
    old = "x\ny\n"
    new = "x\nZ"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


def test_diff_text_roundtrip_trailing_newline_both(tmp_path):
    """两侧都有尾换行（回归）。"""
    old = "x\ny\n"
    new = "x\nZ\n"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


def test_no_newline_marker_in_diff(tmp_path):
    """diff_text 对末行无换行的输入产出 \\ No newline 标记。"""
    old = "x\ny"
    new = "x\nZ"
    diff = patch_ops.diff_text(old, new, "p")
    assert "\\ No newline at end of file" in diff


def test_no_newline_marker_rejected_mid_hunk(tmp_path):
    """标记出现在非末行位置 → PATCH_REJECTED。"""
    p = _write(tmp_path, "a.py", "one\ntwo\nthree\n")
    diff = (
        "--- a.py\n+++ b.py\n@@ -1,3 +1,3 @@\n"
        "-one\n\\ No newline at end of file\n"
        "-two\n+TWO\n  three\n"
    )
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.apply_difference(p, diff, session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)


# ⑬ 缺陷 2：CRLF 行尾保留
def test_crlf_roundtrip(tmp_path):
    old = "a\r\nb\r\n"
    new = "a\r\nB\r\n"
    p = tmp_path / "a.py"
    p.write_bytes(old.encode("utf-8"))
    diff = patch_ops.diff_text(old, new, str(p))
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


def test_crlf_rollback_byte_identical(tmp_path):
    original = "alpha\r\nbeta\r\ngamma\r\n"
    p = tmp_path / "a.py"
    p.write_bytes(original.encode("utf-8"))
    patch_ops.replace_anchor(p, "beta", "BETA", session_id=SESSION)
    assert p.read_bytes() == "alpha\r\nBETA\r\ngamma\r\n".encode("utf-8")
    restored = patch_ops.rollback(SESSION)
    assert p.read_bytes() == original.encode("utf-8")


# ⑭ 缺陷 3：非 UTF-8 文件 → PATCH_REJECTED
def test_non_utf8_rejected(tmp_path):
    p = tmp_path / "binary.bin"
    p.write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.replace_anchor(p, "x", "y", session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert "UTF-8" in excinfo.value.message


# ⑮ 缺陷 4：保护路径大小写
def test_protected_path_case_insensitive_certs_pem(tmp_path):
    certs = tmp_path / "CERTS"
    certs.mkdir()
    pem = _write(certs, "x.PEM", "PEM\n")
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.replace_anchor(pem, "PEM", "X", session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.CWD_JAIL_VIOLATION)


def test_protected_path_case_insensitive_git_segment(tmp_path):
    gitdir = tmp_path / ".GIT"
    gitdir.mkdir()
    cfg = _write(gitdir, "config", "x = 1\n")
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.replace_anchor(cfg, "x", "y", session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.CWD_JAIL_VIOLATION)


def test_protected_path_case_insensitive_env(tmp_path):
    env = _write(tmp_path, ".ENV", "SECRET=1\n")
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.replace_anchor(env, "SECRET", "X", session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.CWD_JAIL_VIOLATION)


def test_protected_path_case_insensitive_key_suffix(tmp_path):
    key = _write(tmp_path, "secret.KEY", "KEY\n")
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.replace_anchor(key, "KEY", "X", session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.CWD_JAIL_VIOLATION)


# ⑯ 缺陷 5①：内容以 -/+ 开头的行计数
def test_count_diff_lines_content_starts_with_minus_plus(tmp_path):
    old = "----\n+++\nfoo\n"
    new = "----\n+++\nBAR\n"
    p = _write(tmp_path, "a.py", old)
    res = patch_ops.replace_anchor(p, "foo", "BAR", session_id=SESSION)
    assert res.status == "applied"
    assert res.added_lines == 1
    assert res.removed_lines == 1


# ⑰ 缺陷 5②：差异头文件名不一致
def test_diff_filename_mismatch_rejected(tmp_path):
    p = _write(tmp_path, "target.txt", "one\ntwo\n")
    diff = "--- OTHER.txt\n+++ OTHER.txt\n@@ -1,2 +1,2 @@\n one\n-two\n+TWO\n"
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.apply_difference(p, diff, session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert "OTHER.txt" in excinfo.value.message
    assert "target.txt" in excinfo.value.message


def test_diff_filename_empty_header_accepted(tmp_path):
    p = _write(tmp_path, "target.txt", "one\ntwo\n")
    diff = "--- \n+++ \n@@ -1,2 +1,2 @@\n one\n-two\n+TWO\n"
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"


# ⑱ 第三轮缺陷 A：相邻改动 → 单个合并 hunk，往返逐字节一致
def test_diff_text_adjacent_changes_roundtrip(tmp_path):
    old = "alpha\nbeta\ngamma\ndelta\n"
    new = "alpha\nBETA\ngamma\nDELTA\n"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    assert diff.count("@@ ") == 1, "相邻改动应合并进同一个 hunk"
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")
    assert res.added_lines == 2
    assert res.removed_lines == 2


def test_diff_text_adjacent_blanks_roundtrip(tmp_path):
    old = "a\n\n\nb\n\n"
    new = "a\n\nc\n\n\n"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


# ⑲ 第三轮缺陷 B：保护目录前缀大小写不敏感
def test_protected_prefix_case_insensitive(tmp_path):
    for sub in ("CERTS", "Identity", "MEMORY"):
        target = tmp_path / sub / "notes.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        _write(target.parent, target.name, "x\n")
        with pytest.raises(TrimumError) as excinfo:
            patch_ops.replace_anchor(target, "x", "y", session_id=SESSION)
        _assert_code(excinfo.value, TRMErrorCode.CWD_JAIL_VIOLATION)


# ⑳ 第三轮缺陷 C：内容以 '-- '/'++ ' 开头的行不被误判为文件头
def test_diff_text_body_minus_minus_line_roundtrip(tmp_path):
    old = "-- x\nfoo\n"
    new = "foo\n"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


def test_diff_text_insert_plus_plus_line_roundtrip(tmp_path):
    old = "foo\n"
    new = "foo\n++ x\n"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


# ㉑ 第三轮缺陷 D：目标是目录 → PATCH_REJECTED（不是裸 IsADirectoryError）
def test_apply_difference_on_directory_rejected(tmp_path):
    d = tmp_path / "adirectory"
    d.mkdir()
    diff = "--- a.py\n+++ a.py\n@@ -1,1 +1,1 @@\n a\n+b\n"
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.apply_difference(d, diff, session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert "目录" in excinfo.value.message


def test_replace_anchor_on_directory_rejected(tmp_path):
    d = tmp_path / "adirectory"
    d.mkdir()
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.replace_anchor(d, "x", "y", session_id=SESSION)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert "目录" in excinfo.value.message


# ㉒ 第三轮守门：随机文本往返属性测试（缺陷 A 的守门人）
def test_roundtrip_random_texts(tmp_path):
    rng = random.Random(20260927)
    words = ["alpha", "beta", "", "中文", "x--", "y++", "  indented", "\u00e9"]

    def rand_line():
        return rng.choice(words)

    def rand_text():
        n = rng.randint(0, 10)
        lines = [rand_line() for _ in range(n)]
        if not lines:
            return ""
        sep = rng.choice(["\n", "\r\n"])
        text = sep.join(lines)
        if rng.random() < 0.7:
            text += sep
        return text

    # 手工加组，覆盖任务点名的小形状（含多处相距很近的改动）
    extra = [
        ("alpha\nbeta\ngamma\ndelta\n", "alpha\nBETA\ngamma\nDELTA\n"),
        ("a\n\n\nb\n\n", "a\n\nc\n\n\n"),
        ("a\nb\nc\nd\ne\nf\ng\nh\n", "a\nB\nc\nd\ne\nf\ng\nH\n"),
        ("only\n", "ONLY\n"),
        ("", "created\n"),
        ("gone\n", ""),
    ]
    pairs = []
    for _ in range(60):
        old = rand_text()
        new = rand_text()
        pairs.append((old, new))
    pairs.extend(extra)

    for idx, (old, new) in enumerate(pairs):
        if old == new:
            continue
        p = tmp_path / f"rt-{idx}.txt"
        p.write_bytes(old.encode("utf-8"))
        diff = patch_ops.diff_text(old, new, str(p))
        res = patch_ops.apply_difference(p, diff, session_id=SESSION)
        assert res.status == "applied", f"case {idx}: {old!r} -> {new!r}"
        assert p.read_bytes() == new.encode("utf-8"), (
            f"case {idx}: {old!r} -> {new!r}\n{diff!r}\ngot {p.read_bytes()!r}"
        )


def test_diff_text_delete_minus_minus_adjacent_insert_plus_plus(tmp_path):
    """body 里 `--- x` 紧接 `+++ y`：是「删 `-- x` 行 + 加 `++ y` 行」，不是第二个文件头。"""
    old = "head\n-- x\n"
    new = "head\n++ y\n"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    assert "\n--- x\n+++ y\n" in diff, repr(diff)
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


def test_apply_difference_adjacent_minus_minus_plus_plus_in_later_hunk(tmp_path):
    """第二个 hunk 里同样形态的相邻行：不能误判成 multi-file。"""
    old = "a\nb\nc\nd\ne\nf\ng\nh\n-- x\n"
    new = "A\nb\nc\nd\ne\nf\ng\nh\n++ y\n"
    p = _write(tmp_path, "a.py", old)
    diff = patch_ops.diff_text(old, new, str(p))
    assert diff.count("@@ ") == 2, repr(diff)
    res = patch_ops.apply_difference(p, diff, session_id=SESSION)
    assert res.status == "applied"
    assert p.read_bytes() == new.encode("utf-8")


def test_apply_difference_without_session_id_rejected(tmp_path):
    """真实写盘必须带 session_id；缺了 → PATCH_REJECTED，且文件不动。"""
    p = _write(tmp_path, "a.py", "one\ntwo\n")
    diff = "--- a.py\n+++ a.py\n@@ -1,2 +1,2 @@\n one\n-two\n+TWO\n"
    with pytest.raises(TrimumError) as excinfo:
        patch_ops.apply_difference(p, diff)
    _assert_code(excinfo.value, TRMErrorCode.PATCH_REJECTED)
    assert p.read_bytes() == b"one\ntwo\n"
