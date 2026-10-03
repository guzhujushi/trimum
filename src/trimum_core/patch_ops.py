"""E7 self-built coding agent — edit primitives and session audit trail.

This module is slice 1 of the E7 coding-agent work: a small set of editing
primitives (anchor replacement + unified-diff application) plus per-session
file snapshots that make every edit rollbackable.  It is deliberately
standalone — wiring into the agent loop / ToolGateway happens in slice 5.

Only the standard library is used (difflib / pathlib / json / dataclasses /
re).  No third-party dependencies.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from .models import TRMErrorCode, TrimumError
from . import paths

PathLike = Union[str, Path]

#: File extensions treated as secret material, whatever their name/location.
_SECRET_SUFFIXES = {".pem", ".key", ".p12"}

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class PatchResult:
    path: str
    added_lines: int
    removed_lines: int
    difference: str
    snapshot_id: str | None
    status: str
    reason: str = field(default="")


def diff_text(old: str, new: str, path: str) -> str:
    """Unified diff (n=3) between ``old`` and ``new`` for ``path``."""
    # Use the basename in the diff headers so the header matches the
    # target path's basename when the diff is later applied.
    name = Path(path).name
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    old_no_nl = bool(old) and not old.endswith(("\n", "\r\n"))
    new_no_nl = bool(new) and not new.endswith(("\n", "\r\n"))
    marker = "\\ No newline at end of file\n"

    # Compare on the *exact* line, terminator included: ``"y++\n"`` and
    # ``"y++\r\n"`` are different lines.  Comparing stripped content made the
    # matcher treat them as equal and silently kept the old terminator, so a
    # file could come out with the wrong line endings.
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    parts: list[str] = [f"--- {name}\n", f"+++ {name}\n"]
    ctx = 3

    def _emit(prefix: str, line: str, is_last_no_nl: bool) -> None:
        """Emit one diff body line, adding the GNU marker when needed.

        The marker always goes on its own physical line; when a side's last
        line has no trailing newline we emit the line *with* a ``\\n`` (so the
        marker starts a new physical line) and follow it with the marker.
        A trailing-newline-only change (``"x\ny"`` -> ``"x\ny\n"``) needs no
        special case: the exact-line comparison already sees the last line as
        different and emits a normal replace hunk for it.
        """
        if is_last_no_nl:
            # Force a newline so the marker sits on its own physical line.
            parts.append(prefix + line + "\n")
            parts.append(marker)
        else:
            parts.append(prefix + line)

    # get_grouped_opcodes(3) groups nearby changes into non-overlapping
    # hunks with 3 lines of context; emit one hunk per group.
    for group in sm.get_grouped_opcodes(ctx):
        first = group[0]
        last = group[-1]
        hunk_i1 = first[1]
        hunk_i2 = last[2]
        hunk_j1 = first[3]
        hunk_j2 = last[4]
        old_start = hunk_i1 + 1 if hunk_i2 > hunk_i1 else 0
        new_start = hunk_j1 + 1 if hunk_j2 > hunk_j1 else 0
        parts.append(
            f"@@ -{old_start},{hunk_i2 - hunk_i1} "
            f"+{new_start},{hunk_j2 - hunk_j1} @@\n"
        )
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for k in range(i1, i2):
                    _emit(" ", old_lines[k],
                          k == len(old_lines) - 1 and old_no_nl)
            elif tag == "delete":
                for k in range(i1, i2):
                    _emit("-", old_lines[k],
                          k == len(old_lines) - 1 and old_no_nl)
            elif tag == "insert":
                for k in range(j1, j2):
                    _emit("+", new_lines[k],
                          k == len(new_lines) - 1 and new_no_nl)
            elif tag == "replace":
                for k in range(i1, i2):
                    _emit("-", old_lines[k],
                          k == len(old_lines) - 1 and old_no_nl)
                for k in range(j1, j2):
                    _emit("+", new_lines[k],
                          k == len(new_lines) - 1 and new_no_nl)

    return "".join(parts)


def _count_diff_lines(difference: str) -> tuple[int, int]:
    """Count added/removed lines by hunk structure, not by line prefixes.

    Only lines after each ``@@ ... @@`` header are inspected, so body lines
    whose *content* starts with ``-``/``+`` (rendered as ``----`` / ``+++``)
    are counted, while the ``--- ``/``+++ `` file headers outside hunks never
    are.
    """
    added = 0
    removed = 0
    in_hunk = False
    for line in difference.splitlines():
        if line.startswith("@@ "):
            in_hunk = True
            continue
        if line.startswith("\\ "):
            continue
        if in_hunk and line and line[0] in "+-":
            if line[0] == "+":
                added += 1
            else:
                removed += 1
    return added, removed


def _check_protected(p: Path) -> None:
    if any(part.casefold() == ".git" or part.casefold().endswith(".git") for part in p.parts):
        raise TrimumError(
            TRMErrorCode.CWD_JAIL_VIOLATION,
            message=f"protected path (.git): {p}",
            context={"path": str(p)},
        )
    for sub in ("certs", "identity", "memory"):
        root = paths.trimum_path(sub).resolve()
        # Casefold each path segment so CERTS/ Identity/ MEMORY/ are
        # rejected too (defect B).
        root_cf = tuple(part.casefold() for part in root.parts)
        p_cf = tuple(part.casefold() for part in p.parts)
        if p_cf == root_cf or p_cf[: len(root_cf)] == root_cf:
            raise TrimumError(
                TRMErrorCode.CWD_JAIL_VIOLATION,
                message=f"protected trimum directory ({sub}): {p}",
                context={"path": str(p)},
            )
    if p.suffix.casefold() in _SECRET_SUFFIXES:
        raise TrimumError(
            TRMErrorCode.CWD_JAIL_VIOLATION,
            message=f"protected secret file ({p.suffix}): {p}",
            context={"path": str(p)},
        )
    if p.name.casefold() == ".env":
        raise TrimumError(
            TRMErrorCode.CWD_JAIL_VIOLATION,
            message=f"protected env file: {p}",
            context={"path": str(p)},
        )


def _safe_path(p: PathLike) -> Path:
    resolved = Path(p).resolve()
    _check_protected(resolved)
    return resolved


def is_protected_path(p: PathLike) -> bool:
    """``True`` = 该路径受保护（与 :func:`_check_protected` 同一口径）。

    只判定、从不抛异常：非路径类型（``None`` / ``123`` 之类）或底层报错一律按
    「受保护」返回 ``True``（宁可误报，不可漏报）；不存在的普通路径照常按名字与位置判定。
    """
    try:
        _check_protected(Path(p).resolve())
    except Exception:  # noqa: BLE001 — 拿不准一律按「受保护」处理
        return True
    return False


def _read(path: PathLike) -> Path:
    resolved = _safe_path(path)
    if not resolved.exists():
        raise TrimumError(
            TRMErrorCode.FILE_NOT_FOUND,
            message=f"file not found: {resolved}",
            context={"path": str(resolved)},
        )
    if resolved.is_dir():
        raise TrimumError(
            TRMErrorCode.PATCH_REJECTED,
            message=f"目标是目录，不是文件：{resolved}",
            context={"path": str(resolved)},
        )
    return resolved


def _read_text(path: Path) -> str:
    """Read ``path`` as UTF-8, keeping every byte (CRLF/LF) untouched."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _session_dir(session_id: str) -> Path:
    return paths.trimum_path("sessions", session_id)


def _load_entries(session_id: str) -> list:
    data = _session_dir(session_id) / "session.json"
    if not data.exists():
        return []
    with data.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return raw if isinstance(raw, list) else []


def _save_entries(session_id: str, entries: list) -> None:
    data = _session_dir(session_id) / "session.json"
    with data.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def snapshot(path: PathLike, session_id: str) -> str:
    """Snapshot the current content of ``path``; return the snapshot filename.

    Every call allocates a fresh ``000X-<name>`` snapshot (``X`` = existing
    ``session.json`` entry count + 1) and appends one entry, so each edit keeps
    its own pre-edit state and ``rollback`` can walk them newest-first.
    """
    resolved = _read(path)
    sdir = _session_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=True)
    entries = _load_entries(session_id)
    n = len(entries) + 1
    snap_name = f"{n:04d}-{resolved.name}"
    (sdir / snap_name).write_bytes(resolved.read_bytes())
    entries.append({"n": n, "path": str(resolved), "snapshot": snap_name})
    _save_entries(session_id, entries)
    return snap_name


def replace_anchor(
    path: PathLike,
    anchor: str,
    replacement: str,
    *,
    count: int = 1,
    dry_run: bool = False,
    session_id: str | None = None,
) -> PatchResult:
    resolved = _read(path)
    try:
        old = _read_text(resolved)
    except UnicodeDecodeError as exc:
        raise TrimumError(
            TRMErrorCode.PATCH_REJECTED,
            message=f"不是 UTF-8 文本文件：{path}",
            context={"path": str(path)},
        ) from exc
    n = old.count(anchor)
    if n != count:
        raise TrimumError(
            TRMErrorCode.PATCH_REJECTED,
            message=f"anchor appears {n} times, expected {count}: {anchor!r}",
            context={"path": str(resolved), "found": n, "expected": count},
        )
    new = old.replace(anchor, replacement)
    if new == old:
        raise TrimumError(
            TRMErrorCode.PATCH_REJECTED,
            message="replacement produces no change",
            context={"path": str(resolved)},
        )
    difference = diff_text(old, new, str(resolved))
    added, removed = _count_diff_lines(difference)
    if dry_run:
        return PatchResult(
            path=str(resolved),
            added_lines=added,
            removed_lines=removed,
            difference=difference,
            snapshot_id=None,
            status="preview",
        )
    if session_id is None:
        raise TrimumError(
            TRMErrorCode.PATCH_REJECTED,
            message="session_id is required to write to disk",
            context={"path": str(resolved)},
        )
    snap = snapshot(resolved, session_id)
    _write_text(resolved, new)
    return PatchResult(
        path=str(resolved),
        added_lines=added,
        removed_lines=removed,
        difference=difference,
        snapshot_id=snap,
        status="applied",
    )


def _parse_diff(difference: str, path: Path) -> list:
    """Parse the narrow difflib-shaped unified diff; return hunk list.

    Each hunk is a dict with ``start`` (1-based old-file line) and ``body``
    (list of raw body lines, each starting with ' ', '+' or '-').
    """
    def _reject(reason: str) -> None:
        raise TrimumError(
            TRMErrorCode.PATCH_REJECTED,
            message=reason,
            context={"path": str(path)},
        )
    lines = difference.splitlines(keepends=True)
    i = 0
    # Only the first two lines may be the '--- '/'+++ ' file headers;
    # a '--- ' line anywhere inside a hunk is body content (defect C).
    # A second '--- ' after the first hunk means a multi-file diff.
    if i >= len(lines) or not lines[i].startswith("--- "):
        _reject("diff missing leading '--- ' header")
    i += 1
    if i >= len(lines) or not lines[i].startswith("+++ "):
        _reject("diff missing '+++ ' header")
    i += 1
    saw_hunk = False
    while i < len(lines) and not lines[i].startswith("@@ "):
        if lines[i].startswith("--- "):
            _reject("multi-file diff not supported")
        i += 1
    hunks = []
    while i < len(lines):
        line = lines[i]
        m = _HUNK_RE.match(line)
        if not m:
            _reject(f"malformed hunk header: {line!r}")
        i += 1
        old_start = int(m.group(1))
        old_count = int(m.group(2)) if m.group(2) is not None else 1
        body = []
        seen_ctx = 0
        seen_del = 0
        while i < len(lines):
            bl = lines[i]
            if bl.startswith("@@ "):
                break
            if (
                bl.startswith("--- ")
                and seen_del + seen_ctx == old_count
                and i + 1 < len(lines)
                and lines[i + 1].startswith("+++ ")
            ):
                # This hunk's old-side lines are already fully consumed, so a
                # '--- ' here cannot be a deleted body line (a deleted line
                # only *looks* like this when its content starts with '-- ',
                # and those are counted as they are collected): it is the
                # header of a second file in the diff.
                _reject("multi-file diff not supported")
            if bl.startswith("--- ") and not body and not saw_hunk:
                # A '--- ' line directly after a hunk header is a deleted
                # line whose content starts with '-- ' (defect C); only the
                # diff's first line is a file header.
                body.append((bl, False))
                seen_del += 1
                i += 1
                continue
            if bl.startswith("\\ "):
                # "\ No newline at end of file" marker: applies to the
                # immediately preceding body line.  Mark it in-place.
                if not body:
                    _reject(
                        "malformed diff: '\\ No newline' marker without "
                        "preceding line"
                    )
                # body[-1] is (raw, no_nl); set no_nl=True.
                raw, _ = body[-1]
                body[-1] = (raw, True)
                i += 1
                continue
            if bl[0] in ("+", "-", " "):
                body.append((bl, False))
                if bl[0] == "-":
                    seen_del += 1
                elif bl[0] == " ":
                    seen_ctx += 1
                i += 1
            else:
                break
        if seen_del + seen_ctx != old_count:
            _reject(
                f"hunk line count mismatch: header says old={old_count}, "
                f"body has {seen_del + seen_ctx}"
            )
        # Validate: a no-newline marker may only appear on the last line of
        # its side within the hunk (i.e. the last '-'/' ' line for old, or
        # the last '+' line for new).
        for bi, (raw, no_nl) in enumerate(body):
            if no_nl:
                if raw[0] in ("-", " "):
                    # Must be the last old-side line in this hunk.
                    for r2, _ in body[bi + 1:]:
                        if r2[0] in ("-", " "):
                            _reject(
                                "malformed diff: '\\ No newline' marker not "
                                "on the last line of its side"
                            )
                elif raw[0] == "+":
                    for r2, _ in body[bi + 1:]:
                        if r2[0] == "+":
                            _reject(
                                "malformed diff: '\\ No newline' marker not "
                                "on the last line of its side"
                            )
        hunks.append({"start": old_start, "body": body})
        saw_hunk = True
    return hunks


def _check_diff_filename(difference: str, path: Path) -> None:
    """Reject a diff whose '--- '/'+++ ' header names a different file.

    The file-name part (after an optional ``a/`` / ``b/`` prefix) must equal
    the target path's basename; a header without a name (e.g. a bare
    ``--- ``) is accepted.
    """
    target_name = Path(path).name

    def _strip_side(filename: str) -> str:
        for prefix in ("a/", "b/"):
            if filename.startswith(prefix):
                return filename[len(prefix):]
        return filename

    lines = difference.splitlines()
    if not lines or not lines[0].startswith("--- ") or len(lines) < 2 or not lines[1].startswith("+++ "):
        return
    for marker, line in (("--- ", lines[0]), ("+++ ", lines[1])):
        name = line[len(marker):].split("\t")[0].strip()
        if not name:
            continue
        name = _strip_side(name)
        if name != target_name:
            raise TrimumError(
                TRMErrorCode.PATCH_REJECTED,
                message=(
                    "diff filename does not match target: "
                    f"header says {name!r}, target is {target_name!r}"
                ),
                context={"path": str(path)},
            )


def _apply_hunks(old_lines: list, hunks: list, path: Path) -> list:
    new_lines = list(old_lines)
    for idx, hunk in enumerate(hunks, start=1):
        start = hunk["start"]
        body = hunk["body"]
        # Old-file lines covered by this hunk: every body line that is a
        # deletion ('-') or context (' '); a deletion of an empty line is a
        # bare '-' line and is still counted here.  '+' lines are additions.
        old_len = sum(1 for raw, _ in body if not raw.startswith("+"))
        # start is 1-based in the old file, but a hunk that only inserts
        # at the very beginning carries start=0 (standard unified diff);
        # accept 0 and clamp the slice to the file's start.
        if start < 0 or start + old_len - 1 > len(old_lines):
            raise TrimumError(
                TRMErrorCode.PATCH_REJECTED,
                message=f"hunk {idx} out of bounds (start={start}, old_len={old_len})",
                context={"path": str(path)},
            )
        out = []
        pos = max(start, 1) - 1
        for bi, (bl, no_nl) in enumerate(body):
            # The diff text always carries a terminator on every body line
            # (we force one so the marker sits on its own physical line).
            # no_nl=True means the *actual* file line has no trailing newline,
            # so we strip the forced terminator for comparison and output.
            content = bl[1:]
            if no_nl:
                content = content.rstrip("\r\n")
            if bl.startswith("+"):
                out.append(content)
            elif bl.startswith("-"):
                if pos >= len(old_lines) or old_lines[pos] != content:
                    raise TrimumError(
                        TRMErrorCode.PATCH_REJECTED,
                        message=(
                            f"hunk {idx} context mismatch at line {pos + 1}: "
                            f"expected {old_lines[pos] if pos < len(old_lines) else None!r}, "
                            f"got {content!r}"
                        ),
                        context={"path": str(path), "line": pos + 1},
                    )
                pos += 1
            else:
                expected = old_lines[pos] if pos < len(old_lines) else None
                if expected != content:
                    raise TrimumError(
                        TRMErrorCode.PATCH_REJECTED,
                        message=(
                            f"hunk {idx} context mismatch at line {pos + 1}: "
                            f"expected {expected!r}, got {content!r}"
                        ),
                        context={"path": str(path), "line": pos + 1},
                    )
                out.append(content)
                pos += 1
        new_lines[max(start - 1, 0):max(start - 1, 0) + old_len] = out
    return new_lines


def apply_difference(
    path: PathLike,
    difference: str,
    *,
    dry_run: bool = False,
    session_id: str | None = None,
) -> PatchResult:
    resolved = _read(path)
    try:
        old = _read_text(resolved)
    except UnicodeDecodeError as exc:
        raise TrimumError(
            TRMErrorCode.PATCH_REJECTED,
            message=f"不是 UTF-8 文本文件：{path}",
            context={"path": str(path)},
        ) from exc
    old_lines = old.splitlines(keepends=True)
    _check_diff_filename(difference, resolved)
    hunks = _parse_diff(difference, resolved)
    new_lines = _apply_hunks(old_lines, hunks, resolved)
    new = "".join(new_lines)
    if new == old:
        raise TrimumError(
            TRMErrorCode.PATCH_REJECTED,
            message="difference produces no change",
            context={"path": str(resolved)},
        )
    difference_final = diff_text(old, new, str(resolved))
    added, removed = _count_diff_lines(difference_final)
    if dry_run:
        return PatchResult(
            path=str(resolved),
            added_lines=added,
            removed_lines=removed,
            difference=difference_final,
            snapshot_id=None,
            status="preview",
        )
    if session_id is None:
        raise TrimumError(
            TRMErrorCode.PATCH_REJECTED,
            message="session_id is required to write to disk",
            context={"path": str(resolved)},
        )
    snap = snapshot(resolved, session_id)
    _write_text(resolved, new)
    return PatchResult(
        path=str(resolved),
        added_lines=added,
        removed_lines=removed,
        difference=difference_final,
        snapshot_id=snap,
        status="applied",
    )


def rollback(session_id: str) -> list[str]:
    sdir = _session_dir(session_id)
    data = sdir / "session.json"
    if not data.exists():
        raise TrimumError(
            TRMErrorCode.FILE_NOT_FOUND,
            message=f"session not found: {data}",
            context={"path": str(data)},
        )
    entries = _load_entries(session_id)
    # Each entry holds the file state *before* that edit; restoring them
    # newest-first (reverse order) walks the edit history backwards and
    # reproduces the original file byte-for-byte.  Returns the restored paths
    # in reverse (restore) order.
    restored: list[str] = []
    for entry in reversed(entries):
        snap_file = sdir / entry["snapshot"]
        target = Path(entry["path"])
        if not snap_file.exists():
            raise TrimumError(
                TRMErrorCode.FILE_NOT_FOUND,
                message=f"snapshot not found: {snap_file}",
                context={"path": str(snap_file)},
            )
        target.write_bytes(snap_file.read_bytes())
        snap_file.unlink()
        restored.append(str(target))
    return restored


__all__ = [
    "PatchResult",
    "diff_text",
    "snapshot",
    "replace_anchor",
    "apply_difference",
    "rollback",
    "is_protected_path",
]
