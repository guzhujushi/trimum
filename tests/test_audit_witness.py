"""带外见证（片 A2 后半）：把「链尾 + 各段边界」抄一份到 $TRIMUM_HOME/（与数据目录分离）。

覆盖：snapshot 采集 / 轮转段顺序 / write-read 往返 / compare_witness 纯函数判据 /
版本·路径不符不作数 / record_witness 永不抛 / append() 接线 / 见证写不下来时 append 仍成功。

落盘一律 tmp_path；每条用例都 monkeypatch TRIMUM_HOME 指向临时目录，绝不碰 ~/.trimum。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.audit_store import AuditStore  # noqa: E402
from trimum_core.audit_witness import (  # noqa: E402
    WITNESS_VERSION,
    compare_witness,
    read_witness,
    record_witness,
    snapshot,
    write_witness,
)
from trimum_core.models import AuditEvent  # noqa: E402


def _event(eid: str, command: str = "echo hi") -> AuditEvent:
    return AuditEvent(event_id=eid, command=command, event_type="tool_executed", risk="low")


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _hmacs(path: Path) -> list[str]:
    return [line["hmac"] for line in _lines(path) if line.get("hmac")]


# T1 —— snapshot() 采集正确
def test_t1_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    store = AuditStore(path=tmp_path / "audit.jsonl", hmac_key="k-witness")
    for eid in ("a1", "a2", "a3"):
        assert store.append(_event(eid)) is True
    p = tmp_path / "audit.jsonl"

    snap = snapshot(p)
    # 只有主文件这一段
    assert [s["name"] for s in snap["segments"]] == ["audit.jsonl"]
    seg = snap["segments"][0]
    assert seg["lines"] == 3
    assert seg["bytes"] == p.stat().st_size
    assert seg["last_hmac"] == _hmacs(p)[2]
    assert snap["tail_hmac"] == _hmacs(p)[2]
    assert snap["audit_path"] == str(p)
    assert Path(snap["audit_path"]).is_absolute()


# T2 —— 轮转后段顺序与末行 hmac
def test_t2_rotation_order(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    main = tmp_path / "audit.jsonl"
    store = AuditStore(path=main, hmac_key="k-witness")
    assert store.append(_event("b1")) is True
    assert store.append(_event("b2")) is True
    # 模拟轮转：主文件 rename 成 .1
    backup = tmp_path / "audit.jsonl.1"
    main.rename(backup)
    # .1 有两行（b1、b2）⇒ 其「末行 hmac」是 b2（不是 b1）。
    # （提示词写「第一条的 hmac」，但 .1 有两条链行，末行是 b2；这里按不变量断言。）
    last_before_rotate = _hmacs(backup)[-1]
    # 再写一条到（新的）主文件
    store2 = AuditStore(path=main, hmac_key="k-witness")
    assert store2.append(_event("b3")) is True
    hmac3 = _hmacs(main)[0]

    snap = snapshot(main)
    # 顺序固定：.1 在前、主文件在后
    assert [s["name"] for s in snap["segments"]] == ["audit.jsonl.1", "audit.jsonl"]
    by = {s["name"]: s for s in snap["segments"]}
    assert by["audit.jsonl.1"]["last_hmac"] == last_before_rotate
    assert by["audit.jsonl"]["last_hmac"] == hmac3
    assert snap["tail_hmac"] == hmac3
    # bytes 与各自 st_size 一致（主文件段 bytes>0，防 "bytes 恒 0" 变异；
    # .1 段本轮只校验与 st_size 相等，bytes==0 的备份段问题另行处理，不在此断言）
    assert by["audit.jsonl.1"]["bytes"] == backup.stat().st_size
    assert by["audit.jsonl"]["bytes"] > 0
    assert by["audit.jsonl"]["bytes"] == main.stat().st_size


# T3 —— write_witness / read_witness 往返
def test_t3_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    store = AuditStore(path=tmp_path / "audit.jsonl", hmac_key="k-witness")
    assert store.append(_event("c1")) is True
    state = snapshot(store.path)

    assert write_witness(state) is True
    target = tmp_path / "home" / "audit-witness.json"
    assert target.exists()
    got = read_witness()
    assert isinstance(got, dict)
    assert got["version"] == WITNESS_VERSION == 1
    assert isinstance(got["updated_at"], float)
    assert got["audit_path"] == state["audit_path"]
    # 权限 0o600
    assert target.stat().st_mode & 0o777 == 0o600
    # 无残留临时文件
    leftovers = [f.name for f in (tmp_path / "home").iterdir() if f.name.startswith("audit-witness.json.tmp")]
    assert leftovers == []


# T4 —— compare_witness 纯函数五例（内存 dict，不碰磁盘）
def test_t4_compare_pure():
    def seg(name, lines, b, hmac):
        return {"name": name, "lines": lines, "bytes": b, "last_hmac": hmac}

    ap = "/data/audit.jsonl"
    base = {
        "version": WITNESS_VERSION,
        "updated_at": 1.0,
        "audit_path": ap,
        "segments": [seg("audit.jsonl", 3, 300, "h3")],
        "tail_hmac": "h3",
    }

    # ① 见证 == 当前 ⇒ []
    same = json.loads(json.dumps(base))
    assert compare_witness(base, same) == []

    # ② 尾部截断（当前主文件 lines/bytes 都变小，且不是轮转）⇒ segment shrank
    trunc = json.loads(json.dumps(base))
    trunc["segments"][0]["lines"] = 1
    trunc["segments"][0]["bytes"] = 100
    findings = compare_witness(base, trunc)
    assert any("segment shrank" in f for f in findings)

    # ③ .1 整段消失（见证有 .1、当前没有）⇒ segment missing
    with_backup_wit = {
        "version": WITNESS_VERSION,
        "updated_at": 1.0,
        "audit_path": ap,
        "segments": [seg("audit.jsonl.1", 2, 200, "h2"), seg("audit.jsonl", 1, 100, "h3")],
        "tail_hmac": "h3",
    }
    cur_no_backup = {
        "version": WITNESS_VERSION,
        "updated_at": 1.0,
        "audit_path": ap,
        "segments": [seg("audit.jsonl", 1, 100, "h3")],
        "tail_hmac": "h3",
    }
    findings = compare_witness(with_backup_wit, cur_no_backup)
    assert any("segment missing" in f for f in findings)

    # ④ 就地改写（同 lines/bytes 但 last_hmac 不同）⇒ rewritten in place
    rewritten = json.loads(json.dumps(base))
    rewritten["segments"][0]["last_hmac"] = "DIFFERENT"
    findings = compare_witness(base, rewritten)
    assert any("rewritten in place" in f for f in findings)

    # ⑤ 合法轮转（见证只有主文件；当前 .1.last_hmac == 见证主文件.last_hmac 且主文件变小）⇒ []
    rot_wit = {
        "version": WITNESS_VERSION,
        "updated_at": 1.0,
        "audit_path": ap,
        "segments": [seg("audit.jsonl", 5, 500, "h5")],
        "tail_hmac": "h5",
    }
    rot_cur = {
        "version": WITNESS_VERSION,
        "updated_at": 1.0,
        "audit_path": ap,
        "segments": [seg("audit.jsonl.1", 5, 500, "h5"), seg("audit.jsonl", 1, 100, "h6")],
        "tail_hmac": "h6",
    }
    assert compare_witness(rot_wit, rot_cur) == []


# T5 —— 版本 / 路径不符 ⇒ 不作数
def test_t5_version_path_mismatch():
    wit = {
        "version": WITNESS_VERSION,
        "updated_at": 1.0,
        "audit_path": "/data/audit.jsonl",
        "segments": [{"name": "audit.jsonl", "lines": 1, "bytes": 10, "last_hmac": "h"}],
        "tail_hmac": "h",
    }
    cur = json.loads(json.dumps(wit))
    # 版本不符
    bad_ver = json.loads(json.dumps(wit))
    bad_ver["version"] = 99
    assert compare_witness(bad_ver, cur) == []
    # 路径不符
    bad_path = json.loads(json.dumps(wit))
    bad_path["audit_path"] = "/elsewhere/audit.jsonl"
    assert compare_witness(bad_path, cur) == []


# T6 —— record_witness() 永不抛 + 接线
def test_t6_record_never_raises_and_wired(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    store = AuditStore(path=tmp_path / "audit.jsonl", hmac_key="k-witness")
    assert store.append(_event("d1")) is True

    # ① 指向不可写位置：notadir 是文件 ⇒ 父目录 mkdir 失败 ⇒ False 且不抛
    blocker = tmp_path / "notadir"
    blocker.write_text("x", encoding="utf-8")
    target_under_file = tmp_path / "notadir" / "w.json"
    result = record_witness(store.path, path=target_under_file)
    assert result is False

    # ② 接线：append 之后见证被刷
    got = read_witness()
    assert got is not None
    assert got["tail_hmac"] == _hmacs(tmp_path / "audit.jsonl")[0]


# T7 —— 见证写不下来时 append() 仍成功（审计是旁路，最要紧）
# 为什么不用 stdout/caplog：全量跑时别的用例调过 setup_logging()，structlog 的输出目的地
# 被改写 ⇒ 断言 stdout 在全量下必挂（实测 14→15 failed）。所以这里 monkeypatch 模块级
# log 替身，不依赖任何全局日志配置。
class _RecordingLog:
    """最小替身：把日志调用原样记下来，不碰任何全局日志配置。"""

    def __init__(self):
        self.calls = []

    def _record(self, level, *args, **kwargs):
        self.calls.append((level, args, kwargs))

    def debug(self, *args, **kwargs):
        self._record("debug", *args, **kwargs)

    def info(self, *args, **kwargs):
        self._record("info", *args, **kwargs)

    def warning(self, *args, **kwargs):
        self._record("warning", *args, **kwargs)

    def error(self, *args, **kwargs):
        self._record("error", *args, **kwargs)


def test_t7_append_succeeds_when_witness_unwritable(tmp_path, monkeypatch):
    from trimum_core import audit_witness

    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    # 父路径是文件 ⇒ witness 的父目录 mkdir 必失败
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "blocker" / "home"))
    store = AuditStore(path=tmp_path / "audit.jsonl", hmac_key="k-witness")

    # 换掉模块级 log（write_witness 走的就是这个全局名）⇒ 截获日志，不碰全局配置
    fake = _RecordingLog()
    monkeypatch.setattr(audit_witness, "log", fake)

    # append 必须成功（见证写不下来也不能拖累审计落盘）
    assert store.append(_event("e1")) is True

    # 那一行真的落进了审计文件
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert len([ln for ln in text.splitlines() if ln.strip()]) == 1
    # 见证写不下来
    assert read_witness() is None
    # 失败不许静默：write_failed 的 warning 一定被发出（扫全部参数，不假设位置）
    assert any(
        level == "warning"
        and any("audit_witness.write_failed" in str(a) for a in args)
        for level, args, _ in fake.calls
    )
