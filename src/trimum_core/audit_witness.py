"""审计链的「带外见证」：把「链尾 + 各段边界」抄一份到**另一个目录**。

为什么需要
----------
``AuditStore.verify_chain()``（``audit_store.py``）的锚（``.chained``）与链**在同一个
数据目录**里，所以它自己 docstring 承认四条边界里有三条测不出来：
  ① 前缀截断（整段删 ``.1`` / 只删 ``.1`` 首行）与合法轮转不可区分 ⇒ 通过；
  ② 尾部截断（清空/截短主文件）⇒ 通过；
  ③ 把所有 hmac 删掉**并且**删掉 ``.chained`` 锚 ⇒ 退化成「纯 legacy 文件」而通过。
根因：**有目录写权限的人能同时改锚和链**。本片把「另一份记忆」放到另一个目录，
让「同时改两处」的成本更高。

带外指什么
----------
见证文件落在 ``$TRIMUM_HOME/audit-witness.json``（默认 ``~/.trimum/audit-witness.json``），
而审计数据落在数据目录（``~/.local/share/trimum/``）。**这是两个不同的目录**——
见证是「带外」的：删数据目录的人动不到它，反之亦然。

三条已知边界（别夸大它能防什么）
--------------------------------
  · 只**提高门槛**，不防「同时能写 ``$TRIMUM_HOME``」的攻击者；真正的远程见证要
    第二台可信节点（本项目暂无）。
  · 见证由写路径刷新；刷新失败只告警 ⇒ 见证停在旧状态（只会更容易误报「缩水」，
    不会漏报）。
  · 轮转（主文件 → ``.1``）是合法的「缩水」，靠「当前 ``.1`` 的末行 hmac == 见证里
    主文件的末行 hmac」识别。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .logger import get_logger
from .paths import trimum_path

log = get_logger("trimum_core.audit_witness")

WITNESS_FILENAME = "audit-witness.json"
WITNESS_VERSION = 1


def witness_path() -> Path:
    """见证文件的落盘路径：``$TRIMUM_HOME/audit-witness.json``（带外目录）。"""
    return trimum_path(WITNESS_FILENAME)


def _segment(name: str, path: Path) -> dict:
    """采集**单个段**的边界：非空行数 / 字节数 / 末行 hmac。

    取 ``last_hmac`` 的口径照 ``AuditStore._last_chained_hmac``（``audit_store.py:218``）：
    反向逐行 ``json.loads``，取第一条有非空 ``hmac`` 的行；坏行 / 空行跳过。
    这里**自己写**这十几行、不 import ``AuditStore``（会循环 import）。
    """
    if not path.exists():
        return {"name": name, "lines": 0, "bytes": 0, "last_hmac": ""}
    try:
        text = path.read_text(encoding="utf-8")
        st_size = path.stat().st_size
    except OSError:
        return {"name": name, "lines": 0, "bytes": 0, "last_hmac": ""}
    lines = text.splitlines()
    non_empty = sum(1 for line in lines if line.strip())
    last_hmac = ""
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        hmac = record.get("hmac") if isinstance(record, dict) else None
        if hmac:
            last_hmac = hmac
            break
    return {"name": name, "lines": non_empty, "bytes": st_size, "last_hmac": last_hmac}


def _segment_names(audit_path: Path) -> tuple[str, Path, str, Path]:
    """从主路径派生 ``(backup_name, backup_path, main_name, main_path)``。

    段顺序固定：``<name>.1`` 在前、主文件在后（与 ``verify_chain`` 的跨文件顺序一致）。
    """
    backup_path = audit_path.with_suffix(audit_path.suffix + ".1")
    return backup_path.name, backup_path, audit_path.name, audit_path


def snapshot(audit_path) -> dict:
    """只读采集当前审计链的状态（**绝不创建 / 写入任何文件**）。

    返回 ``{"version", "updated_at", "audit_path", "segments", "tail_hmac"}``。
    ``segments`` 顺序固定：``.1`` 在前、主文件在后。``tail_hmac`` 取**最靠后的那份
    存在段**的 ``last_hmac``（主文件优先；主文件没有则退到 ``.1``；都没有 ⇒ ``""``）。
    """
    path = Path(audit_path)
    backup_name, backup_path, main_name, main_path = _segment_names(path)
    segments = []
    for name, seg_path in ((backup_name, backup_path), (main_name, main_path)):
        if seg_path.exists():
            segments.append(_segment(name, seg_path))
    tail_hmac = ""
    # 主文件优先；主文件不存在 / 无 hmac 则退到 .1；都没有 ⇒ ""
    for seg in reversed(segments):
        if seg["last_hmac"]:
            tail_hmac = seg["last_hmac"]
            break
    return {
        "version": WITNESS_VERSION,
        "updated_at": time.time(),
        "audit_path": str(path),
        "segments": segments,
        "tail_hmac": tail_hmac,
    }


def read_witness(path=None) -> dict | None:
    """读见证文件；不存在 / 坏 JSON / 顶层不是 dict ⇒ ``None``。

    文件不存在是正常情况（还没写过）用 ``log.debug``；坏 JSON 才 ``log.warning``。
    """
    target = Path(path) if path is not None else witness_path()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.debug("audit_witness.read: missing %s", target)
        return None
    except OSError as e:
        log.warning("audit_witness.read_failed", error=str(e))
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.warning("audit_witness.read_bad_json", error=str(e))
        return None
    if not isinstance(data, dict):
        log.warning("audit_witness.read_not_dict")
        return None
    return data


def write_witness(state: dict, path=None) -> bool:
    """**原子写**见证文件（``os.replace``，替换式、最后写者胜）。任何异常都不抛。"""
    target = Path(path) if path is not None else witness_path()
    tmp: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件放同目录，保证 os.replace 是同文件系统内的原子替换
        tmp = target.with_name(target.name + ".tmp-%d" % os.getpid())
        # 先删掉可能残留的临时文件
        if tmp.exists():
            tmp.unlink()
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(state, ensure_ascii=False))
            os.replace(tmp, target)
            tmp = None
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink(missing_ok=True)
        return True
    except Exception as exc:  # 见证写失败绝不能拖垮审计写路径
        log.warning("audit_witness.write_failed", error=str(exc))
        return False


def record_witness(audit_path, path=None) -> bool:
    """写路径用的薄封装：``write_witness(snapshot(audit_path), path)``。绝不抛。"""
    return write_witness(snapshot(audit_path), path=path)


def compare_witness(witness, current) -> list[str]:
    """纯函数：比对见证与当前状态，返回违规描述列表（**空 = 没发现问题**）。

    不碰磁盘。判据：
      1. 见证 / 当前不是 dict，或版本不符，或 ``audit_path`` 不符 ⇒ 返回 ``[]``
         （不作数；调用方会重写一份）。
      2. 对见证里**每一个**段：当前缺同名段 ⇒ ``segment missing``（主文件 ⇒
         ``main segment missing``，但见第 4 条轮转瞬时窗口的容忍）；当前段缩水
         （lines/bytes 任一变小）⇒ 合法轮转放行，否则 ``segment shrank``；
         同 lines/bytes 但 ``last_hmac`` 变 ⇒ ``segment rewritten in place``。
      3. **合法轮转的识别**：轮转（主文件 → ``.1``）同时让 ``.1`` 变大、让**主文件
         变小**（主文件刚重新开始）。只有当「备份段存在、非空、且 ``备份段.last_hmac
         == 见证主文件.last_hmac``」时才认定是合法轮转：此时备份段的缩水、以及
         **主文件的缩水**都放行（主文件变小是刚轮转、不是被截断）。
      4. **轮转进行中容忍**：``main_name`` 不在当前段里、但备份段存在且
         ``备份段.last_hmac == 见证主文件.last_hmac`` ⇒ 不报 ``main segment missing``
         （那是轮转 rename 的瞬时窗口）。
      顺序按见证段顺序稳定输出。
    """
    if not isinstance(witness, dict) or not isinstance(current, dict):
        return []
    if witness.get("version") != WITNESS_VERSION:
        return []
    if witness.get("audit_path") != current.get("audit_path"):
        return []

    cur_segments = current.get("segments") or []
    wit_segments = witness.get("segments") or []
    if not wit_segments:
        return []

    cur_by_name = {seg["name"]: seg for seg in cur_segments if isinstance(seg, dict)}
    wit_by_name = {seg["name"]: seg for seg in wit_segments if isinstance(seg, dict)}

    # main = 当前段列表最后一个段的 name；兜底见证里最后一个
    main_name = cur_segments[-1]["name"] if cur_segments else wit_segments[-1]["name"]
    # backup = 段列表里除 main 之外的那一个（可能不存在）
    backup_name = None
    for seg in cur_segments:
        if seg["name"] != main_name:
            backup_name = seg["name"]
            break
    if backup_name is None:
        for seg in wit_segments:
            if seg["name"] != main_name:
                backup_name = seg["name"]
                break

    wit_main = wit_by_name.get(main_name, {})
    wit_main_last_hmac = wit_main.get("last_hmac", "")

    cur_backup = cur_by_name.get(backup_name) if backup_name else None
    # 合法轮转：备份段存在、非空、且末行 hmac == 见证主文件末行 hmac
    # （当前 .1 就是「刚才那份主文件」）
    legal_rotation = bool(
        cur_backup is not None
        and cur_backup.get("last_hmac")
        and cur_backup.get("last_hmac") == wit_main_last_hmac
    )
    # 轮转进行中：主文件不在当前段里，但备份段末行 hmac == 见证主文件末行 hmac
    in_rotation_window = (
        main_name not in cur_by_name and legal_rotation
    )

    findings: list[str] = []
    for w in wit_segments:
        wname = w["name"]
        c = cur_by_name.get(wname)
        if c is None:
            if wname == main_name:
                if in_rotation_window:
                    continue  # 轮转瞬时窗口，不报
                findings.append(
                    "main segment missing: %s (witness %d lines / %d bytes; now absent)"
                    % (wname, w["lines"], w["bytes"])
                )
            else:
                findings.append(
                    "segment missing: %s (witness %d lines / %d bytes; now absent)"
                    % (wname, w["lines"], w["bytes"])
                )
            continue

        # 当前有同名段
        if c["lines"] >= w["lines"] and c["bytes"] >= w["bytes"]:
            if (
                c["lines"] == w["lines"]
                and c["bytes"] == w["bytes"]
                and c.get("last_hmac", "") != w.get("last_hmac", "")
            ):
                findings.append(
                    "segment rewritten in place: %s (%d lines / %d bytes, "
                    "last_hmac %s -> %s)"
                    % (wname, c["lines"], c["bytes"], w.get("last_hmac"), c.get("last_hmac"))
                )
            # 否则正常增长 / 无变化，不违规
        else:
            # 缩水：备份段在合法轮转下放行；主文件在合法轮转下也放行（刚重新开始）
            if legal_rotation and (wname == backup_name or wname == main_name):
                continue
            findings.append(
                "segment shrank: %s (witness %d lines / %d bytes; now %d lines / %d bytes)"
                % (wname, w["lines"], w["bytes"], c["lines"], c["bytes"])
            )
    return findings
