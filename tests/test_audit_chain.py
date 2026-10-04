"""审计哈希链落到真实写路径（SECURITY-DEFENSE-PLAN §4.2.2）。

ToolGateway → ``AuditStore.append()``（``audit.jsonl``）此前没有 hash 链；本片给
``AuditEvent`` 加 ``prev_hash`` / ``hmac`` 两个字段，复用 ``sec_monitor.AuditChainVerifier``
的 ``compute_hash``（唯一一份哈希实现），并支持轮转跨文件校验。

落盘一律 ``tmp_path``，不碰 ``~/.trimum`` / ``~/.local/share/trimum``，无网络、不调 LLM。
"""

from __future__ import annotations

import json
import os
import pytest
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.audit_store import AuditStore  # noqa: E402
from trimum_core.models import AuditEvent, AuditRecord  # noqa: E402
from trimum_core.sec_executor import SecAudit  # noqa: E402


def _store(tmp_path: Path, name: str = "audit.jsonl") -> AuditStore:
    return AuditStore(path=tmp_path / name)


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _event(eid: str, command: str = "echo hi") -> AuditEvent:
    return AuditEvent(event_id=eid, command=command, event_type="tool_executed", risk="low")


# T1 —— 写链：连写 3 条，链字段前后衔接，verify 通过
def test_t1_write_chain(tmp_path):
    store = _store(tmp_path)
    for eid in ("a1", "a2", "a3"):
        assert store.append(_event(eid)) is True
    rows = _lines(store.path)
    assert len(rows) == 3
    assert rows[0]["prev_hash"] == ""
    assert rows[1]["prev_hash"] == rows[0]["hmac"]
    assert rows[2]["prev_hash"] == rows[1]["hmac"]
    ok, errors = store.verify_chain()
    assert ok is True and errors == []


# T2 —— 篡改必红：改掉中间行的 command
def test_t2_tamper_detected(tmp_path):
    store = _store(tmp_path)
    for eid in ("b1", "b2", "b3"):
        store.append(_event(eid))
    rows = _lines(store.path)
    rows[1]["command"] = "rm -rf /"
    store.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    ok, errors = store.verify_chain()
    assert ok is False
    assert any("HMAC mismatch" in e or "Hash chain broken" in e for e in errors)
    assert any("b2" in e for e in errors)


# T3 —— 历史行只允许出现在链开始之前
def test_t3_legacy_only_before_chain(tmp_path):
    store = _store(tmp_path)
    legacy = {"event_id": "legacy0", "command": "old-format", "event_type": "tool_executed"}
    store.path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    for eid in ("c1", "c2", "c3"):
        store.append(_event(eid))

    ok, errors = store.verify_chain()
    assert ok is True, errors

    # 反向对照：删掉「链已开始之后」那条新行（第 2 条链行）的 hmac ⇒ 必须红。
    # 注意不能删第 1 条链行的 hmac —— 那时链还没开始，按「历史行只在链之前」的规则它会被当旧行跳过，
    # 这条规则本身容忍「整个文件都没有链字段」，所以判别力必须落在「链已开始之后」。
    rows = _lines(store.path)
    assert len(rows) == 4 and "hmac" in rows[2]
    del rows[2]["hmac"]
    store.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    ok2, errors2 = store.verify_chain()
    assert ok2 is False
    assert any("Missing HMAC after chain start" in e for e in errors2)


# T4 —— 文件不存在 / 空文件；append 自建父目录
def test_t4_missing_and_empty(tmp_path):
    store = _store(tmp_path)  # audit.jsonl 尚不存在
    assert store.verify_chain() == (True, [])

    empty = tmp_path / "empty" / "audit.jsonl"
    empty.parent.mkdir(parents=True)
    empty.write_text("", encoding="utf-8")
    store_empty = AuditStore(path=empty)
    assert store_empty.verify_chain() == (True, [])

    # 父目录不存在时 append 能自建
    deep = tmp_path / "no" / "such" / "dir" / "audit.jsonl"
    deep_store = AuditStore(path=deep)
    assert deep_store.append(_event("d1")) is True
    assert deep.exists()


# T5 —— 轮转跨文件：.1 在前，一条链
def test_t5_rotation_across_files(tmp_path):
    store = _store(tmp_path)
    store.append(_event("e1"))
    store.append(_event("e2"))
    backup = store.path.with_suffix(store.path.suffix + ".1")
    store.path.rename(backup)  # 模拟轮转
    store.append(_event("e3"))
    store.append(_event("e4"))

    ok, errors = store.verify_chain()
    assert ok is True, errors

    # 再篡改 .1 里第 1 行的 command ⇒ 必须红
    rows = _lines(backup)
    rows[0]["command"] = "evil"
    backup.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    ok2, errors2 = store.verify_chain()
    assert ok2 is False
    assert any("e1" in e for e in errors2)


# T6 —— 载荷兼容：新旧字段都在；老读者 read() 不报错且字段一致
def test_t6_payload_compatible(tmp_path):
    store = _store(tmp_path)
    store.append(_event("f1", command="ls -la"))
    dump = json.loads(json.dumps(_lines(store.path)[0]))
    for key in ("event_id", "command", "sandbox", "seccomp", "prev_hash", "hmac"):
        assert key in dump, key
    assert dump["command"] == "ls -la"

    # 老读者：read() 读带链字段的行不报错，字段与写入一致
    rows = store.read()
    assert len(rows) == 1
    assert rows[0]["command"] == "ls -la"
    assert rows[0]["event_id"] == "f1"


# T8 —— 新实例续链（daemon 重启 / CLI 与 daemon 各写同一文件）
def test_t8_new_instance_continues_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    store_a = AuditStore(path=path)
    store_a.append(_event("g1"))
    store_a.append(_event("g2"))

    store_b = AuditStore(path=path)  # 惰性读尾
    store_b.append(_event("g3"))

    rows = _lines(path)
    assert rows[2]["prev_hash"] == rows[1]["hmac"]
    ok, errors = store_b.verify_chain()
    assert ok is True, errors


# T7 —— SecAudit 不被带坏
def test_t7_secaudit_still_works(tmp_path):
    import asyncio

    audit = SecAudit(audit_path=tmp_path / "security.log")
    asyncio.run(audit.log(AuditRecord(event_id="h1", command="echo 1")))
    asyncio.run(audit.log(AuditRecord(event_id="h2", command="echo 2")))
    ok, errors = audit.verify_chain()
    assert ok is True, errors


# T9 —— 末行删 hmac（判别力：链末行缺字段必须红）
def test_t9_last_line_missing_hmac(tmp_path):
    store = _store(tmp_path)
    for eid in ("i1", "i2", "i3"):
        store.append(_event(eid))
    rows = _lines(store.path)
    del rows[-1]["hmac"]
    store.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    ok, errors = store.verify_chain()
    assert ok is False
    assert any("Missing HMAC after chain start" in e for e in errors)


# T10 —— 全量删 hmac（F2 的洞：不许整份文件退化通过）
def test_t10_all_hmac_removed(tmp_path):
    store = _store(tmp_path)
    for eid in ("j1", "j2", "j3"):
        store.append(_event(eid))
    rows = [
        {k: v for k, v in r.items() if k not in ("hmac", "prev_hash")}
        for r in _lines(store.path)
    ]
    store.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    ok, errors = store.verify_chain()
    assert ok is False
    assert any("Chain start record not found" in e for e in errors)


# T11 —— 锚文件被删（不许退回全 legacy 宽松模式）
def test_t11_anchor_deleted(tmp_path):
    store = _store(tmp_path)
    for eid in ("k1", "k2"):
        store.append(_event(eid))
    store._marker_path().unlink()

    ok, errors = store.verify_chain()
    assert ok is False
    assert any("anchor missing" in e for e in errors)


# T12 —— 二次轮转（F1：最老文件锚点丢失被容忍，其余严格，链不永久假红）
def test_t12_double_rotation(tmp_path):
    store = AuditStore(path=tmp_path / "audit.jsonl", max_bytes=1200)
    for i in range(30):
        assert store.append(_event(f"r{i:02d}")) is True
    backup = store.path.with_suffix(store.path.suffix + ".1")
    assert backup.exists()
    main_rows = _lines(store.path)
    assert len(main_rows) > 0

    ok, errors = store.verify_chain()
    assert ok is True, errors


# T13 —— 轮转窗口换进程（F4：主文件不存在时回退读 .1 末行 hmac 续链）
def test_t13_rotation_window_new_process(tmp_path):
    store_a = _store(tmp_path)
    store_a.append(_event("m1"))
    store_a.append(_event("m2"))
    backup = store_a.path.with_suffix(store_a.path.suffix + ".1")
    store_a.path.rename(backup)  # 手工把主文件改名成 .1（主文件此刻不存在）

    store_b = AuditStore(path=store_a.path)  # 新建实例（模拟换进程）
    assert store_b.append(_event("m3")) is True

    backup_rows = _lines(backup)
    new_rows = _lines(store_b.path)
    assert new_rows[0]["prev_hash"] == backup_rows[-1]["hmac"]
    ok, errors = store_b.verify_chain()
    assert ok is True, errors


# T14 —— 算签名失败不打断执行（F3：失败不抛、不推进 _last_hash，恢复后续链）
def test_t14_compute_failure_does_not_advance(tmp_path):
    store = _store(tmp_path)
    store.append(_event("n1"))
    prev_hmac = _lines(store.path)[0]["hmac"]

    def _boom(record):
        raise RuntimeError("boom")

    real_compute = store._verifier.compute_hash
    store._verifier.compute_hash = _boom
    try:
        assert store.append(_event("n2")) is False
    finally:
        store._verifier.compute_hash = real_compute
    assert store._last_hash == prev_hmac  # 失败没推进

    assert store.append(_event("n3")) is True
    rows = _lines(store.path)
    assert len(rows) == 2  # 失败那条没落盘
    assert rows[-1]["prev_hash"] == prev_hmac
    ok, errors = store.verify_chain()
    assert ok is True, errors


# T15 —— 锚缺失检查要覆盖 .1（H-A 回归：轮转窗口 + 删锚，链行全在 .1 里）
def test_t15_anchor_missing_scans_backup(tmp_path):
    store = _store(tmp_path)
    store.append(_event("s1"))
    store.append(_event("s2"))
    store.path.rename(store.path.with_suffix(store.path.suffix + ".1"))  # 轮转窗口：主文件不存在
    store._marker_path().unlink()

    ok, errors = store.verify_chain()
    assert ok is False, errors
    assert any("anchor missing" in e for e in errors)


# T16 —— 已知边界①：最老段（.1）被整段删掉，当前被容忍（片 A2 带外见证收口）
def test_t16_known_limit_oldest_segment_deleted(tmp_path):
    store = _store(tmp_path)
    for eid in ("t1", "t2", "t3"):
        store.append(_event(eid))
    backup = store.path.with_suffix(store.path.suffix + ".1")
    store.path.rename(backup)                       # 轮转：t1..t3 进 .1
    for eid in ("t4", "t5", "t6"):
        store.append(_event(eid))                   # 主文件 t4..t6（prev_hash 指向 t3）
    assert backup.exists()

    backup.unlink()                                 # 整段删掉最老段
    ok, errors = store.verify_chain()
    assert ok is True, errors   # TODO(片 A2)：带外见证到位后应收紧为 False


# T17 —— 已知边界②：尾部截断（最新一批记录被抹掉），当前被容忍（片 A2 带外见证收口）
def test_t17_known_limit_tail_truncated(tmp_path):
    store = _store(tmp_path)
    for eid in ("u1", "u2", "u3"):
        store.append(_event(eid))
    backup = store.path.with_suffix(store.path.suffix + ".1")
    store.path.rename(backup)
    for eid in ("u4", "u5", "u6"):
        store.append(_event(eid))
    assert backup.exists()

    store.path.write_text("", encoding="utf-8")      # 主文件被清空（最新一批没了）
    ok, errors = store.verify_chain()
    assert ok is True, errors   # TODO(片 A2)：带外见证到位后应收紧为 False


# T18 —— 多写者（F-A）：两个**同时活着**的实例交替 append，链必须仍连续
def test_t18_multi_writer_interleaved(tmp_path):
    store_a = _store(tmp_path)
    store_b = _store(tmp_path)          # 模拟 daemon 与 CLI 各建一个 AuditStore
    store_a.append(_event("w1"))
    store_b.append(_event("w2"))        # 旧实现会用实例缓存里的 "" 起链
    store_a.append(_event("w3"))        # 旧实现会接着 w1 的 hmac 串（丢 w2）

    rows = _lines(store_a.path)
    assert [r["event_id"] for r in rows] == ["w1", "w2", "w3"]
    assert rows[1]["prev_hash"] == rows[0]["hmac"]
    assert rows[2]["prev_hash"] == rows[1]["hmac"]
    ok, errors = store_a.verify_chain()
    assert ok is True, errors


# T19 —— 并发冒烟：多线程各建实例同时 append，行数与链完整性都要对（判别力主要靠 T18）
def test_t19_concurrent_writers_smoke(tmp_path):
    import threading

    errors_seen: list[str] = []

    def _worker(tag: str) -> None:
        store = _store(tmp_path)        # 每线程独立实例（模拟独立进程）
        for i in range(10):
            if store.append(_event(f"{tag}{i}")) is not True:
                errors_seen.append(f"append failed: {tag}{i}")

    threads = [threading.Thread(target=_worker, args=(tag,)) for tag in ("x", "y", "z")]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert errors_seen == []
    rows = _lines(tmp_path / "audit.jsonl")
    assert len(rows) == 30
    ok, errors = _store(tmp_path).verify_chain()
    assert ok is True, errors


# T20 —— 已知边界④：链已开始之后又出现无 hmac 行（旧写者混写）⇒ 永久红（锁定语义，A2 归档收口）
def test_t20_known_limit_legacy_after_chain_start(tmp_path):
    store = _store(tmp_path)
    store.append(_event("v1"))
    store.append(_event("v2"))
    with store.path.open("a", encoding="utf-8") as fh:          # 模拟旧版写者追加一行
        fh.write(json.dumps({"event_id": "old-writer", "command": "echo old"}) + "\n")

    ok, errors = store.verify_chain()
    assert ok is False, errors
    assert any("Missing HMAC after chain start" in e for e in errors)


# T21 —— 末行是坏 JSON 时不许借 .1 的旧 hmac（F-D 第二种形态；坏尾行 ≠ 轮转窗口）
def test_t21_malformed_tail_does_not_borrow_backup(tmp_path):
    store = _store(tmp_path)
    store.append(_event("y1"))
    y1_hmac = _lines(store.path)[0]["hmac"]

    backup = store.path.with_suffix(store.path.suffix + ".1")
    backup.write_text(json.dumps({"event_id": "stale", "hmac": "stale-hmac"}) + "\n", encoding="utf-8")
    with store.path.open("a", encoding="utf-8") as fh:
        fh.write('{"event_id": "broken"\n')      # 末行是坏 JSON（但主文件非空）

    fresh = _store(tmp_path)
    assert fresh._current_prev_hash() == y1_hmac       # 不是 "stale-hmac"
    assert fresh.append(_event("y2")) is True


# T22 —— 显式 key 优先且不落盘（key 落盘在 <TRIMUM_HOME>/audit.key）
def test_t22_explicit_key_wins_no_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_AUDIT_HMAC_KEY", raising=False)
    from trimum_core.audit_store import audit_key_path

    store = AuditStore(path=tmp_path / "audit.jsonl", hmac_key="k-explicit")
    assert store.hmac_key == "k-explicit"
    assert not audit_key_path().exists()


# T23 —— 无 key 时生成并 0600 落盘；第二实例复用；链仍然可验
def test_t23_generate_persist_0600_and_reuse(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_AUDIT_HMAC_KEY", raising=False)

    from trimum_core.audit_store import audit_key_path

    store1 = AuditStore(path=tmp_path / "audit.jsonl")
    key_path = audit_key_path()
    assert key_path.exists()
    assert key_path.stat().st_mode & 0o777 == 0o600
    text = key_path.read_text(encoding="utf-8").strip()
    assert len(text) == 64
    int(text, 16)  # 64 位 hex，不抛

    assert store1.append(_event("z1")) is True
    assert store1.append(_event("z2")) is True
    ok, errors = store1.verify_chain()
    assert ok is True, errors

    store2 = AuditStore(path=tmp_path / "audit.jsonl")  # 第二次读文件，不重新生成
    assert store2.hmac_key == store1.hmac_key
    assert store2.append(_event("z3")) is True
    ok, errors = store2.verify_chain()
    assert ok is True, errors


# T24 —— 已有 key 文件则复用；宽松权限只告警不重建
def test_t24_existing_file_reused_and_loose_perms_warn(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_AUDIT_HMAC_KEY", raising=False)
    import os as _os

    from trimum_core.audit_store import audit_key_path

    key_path = audit_key_path()
    key_path.parent.mkdir(parents=True)
    key_path.write_text("written-key", encoding="utf-8")
    _os.chmod(key_path, 0o644)

    with caplog.at_level("WARNING", logger="trimum_core.audit_store"):
        store = AuditStore(path=tmp_path / "audit.jsonl")
    assert store.hmac_key == "written-key"
    assert any("key_permissions_loose" in record.getMessage() for record in caplog.records)


# T25 —— env 优先于文件，且不覆盖文件
def test_t25_env_wins_over_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_AUDIT_HMAC_KEY", raising=False)

    from trimum_core.audit_store import audit_key_path

    key_path = audit_key_path()
    key_path.parent.mkdir(parents=True)
    key_path.write_text("from-file", encoding="utf-8")
    monkeypatch.setenv("TRIMUM_AUDIT_HMAC_KEY", "from-env")

    store = AuditStore(path=tmp_path / "audit.jsonl")
    assert store.hmac_key == "from-env"
    assert key_path.read_text(encoding="utf-8") == "from-file"


# T26 —— 空文件就地修复（确定性）：模拟「建好还没写」现场
def test_t26_empty_file_repaired_in_place(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_AUDIT_HMAC_KEY", raising=False)

    from trimum_core.audit_store import audit_key_path, resolve_hmac_key

    key_path = audit_key_path()
    key_path.parent.mkdir(parents=True)
    # 手工建一个空的 key 文件（0600）：模拟 O_EXCL 建了空文件但还没写内容的窗口现场
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)

    key = resolve_hmac_key()
    assert key != ""
    assert len(key) == 64
    # 坏文件被就地修好
    assert audit_key_path().read_text(encoding="utf-8").strip() == key
    # 稳定、不抖：再调一次仍是同一个 key
    assert resolve_hmac_key() == key


# T27 —— 真并发首建（回归 ds 的复现）：8 进程同抢，去重后只有 1 个且非空
def test_t27_concurrent_first_create_single_key(tmp_path):
    env = dict(os.environ, TRIMUM_HOME=str(tmp_path / "home"))
    env.pop("TRIMUM_AUDIT_HMAC_KEY", None)
    code = (
        "import sys; sys.path.insert(0, 'src');"
        "from trimum_core.audit_store import resolve_hmac_key; print(resolve_hmac_key())"
    )
    cwd = Path(__file__).resolve().parents[1]
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert out.strip(), (p.returncode, err)
        outs.append(out.strip())
    assert len(set(outs)) == 1, outs          # 全一致
    assert len(outs[0]) == 64 and int(outs[0], 16) >= 0


# T28 —— key 文件读不了（EACCES）⇒ fail-closed：抛 AuditKeyUnreadable，绝不当「空」换 key
def test_t28_unreadable_key_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_AUDIT_HMAC_KEY", raising=False)

    from trimum_core.audit_store import AuditKeyUnreadable, audit_key_path, resolve_hmac_key

    key = resolve_hmac_key()  # 正常拿一把 key
    key_path = audit_key_path()
    original = key_path.read_text(encoding="utf-8")

    real_read_text = Path.read_text

    def _deny_read_text(self, *args, **kwargs):
        if self == key_path:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _deny_read_text)
    with pytest.raises(AuditKeyUnreadable):
        resolve_hmac_key()
    Path.read_text = real_read_text  # 只恢复 read_text（保留 TRIMUM_HOME），再断言文件没被动过
    # fail-closed 后 key 文件仍在、内容一字未变（没被 unlink / 覆盖 / 换新 key）
    assert key_path.exists()
    assert key_path.read_text(encoding="utf-8") == original


# T29 —— 恢复可读后复用同一把 key（证明 T28 没生成过第二把、没改过文件）
def test_t29_readable_again_reuses_same_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_AUDIT_HMAC_KEY", raising=False)

    from trimum_core.audit_store import AuditKeyUnreadable, audit_key_path, resolve_hmac_key

    key = resolve_hmac_key()
    key_path = audit_key_path()

    real_read_text = Path.read_text

    def _deny_read_text(self, *args, **kwargs):
        if self == key_path:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _deny_read_text)
    with pytest.raises(AuditKeyUnreadable):
        resolve_hmac_key()
    Path.read_text = real_read_text  # 只恢复 read_text（保留 TRIMUM_HOME，防泄漏到后续用例）

    assert resolve_hmac_key() == key  # 同一把，没换
