"""审计链看门狗（片 A2 前半）：启动即校 + 定时校，断链发事件与告警日志。

落盘一律 ``tmp_path``（显式 hmac_key，不碰 ``~/.trimum/audit.key``），无网络、不调 LLM。
事件断言用 ``EventBus().get_history()``（publish 同步写 history，await 完即可直接看）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.audit_store import AuditStore  # noqa: E402
from trimum_core.audit_watchdog import AuditWatchdog  # noqa: E402
from trimum_core.event_bus import EventBus  # noqa: E402
from trimum_core.models import AuditEvent, EventSeverity  # noqa: E402

BREACH = "security.audit_breach"


def _store(tmp_path: Path) -> AuditStore:
    return AuditStore(path=tmp_path / "audit.jsonl", hmac_key="k-watchdog")


def _breaches(bus: EventBus) -> list:
    return [e for e in bus.get_history() if e.event_type == BREACH]


async def _append_three(store: AuditStore) -> None:
    for eid in ("a1", "a2", "a3"):
        store.append(AuditEvent(event_id=eid, command="echo hi", event_type="tool_executed", risk="low"))


@pytest.mark.asyncio
async def test_t1_ok_chain_no_event(tmp_path):
    bus = EventBus()
    watchdog = AuditWatchdog(bus, store=_store(tmp_path), interval=30)
    await _append_three(watchdog._store)
    ok, errors = await watchdog.verify_once()
    assert ok is True and errors == []
    assert _breaches(bus) == []


@pytest.mark.asyncio
async def test_t2_tamper_publishes_breach_event(tmp_path):
    bus = EventBus()
    watchdog = AuditWatchdog(bus, store=_store(tmp_path), interval=30)
    await _append_three(watchdog._store)
    rows = [json.loads(line) for line in watchdog._store.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[1]["command"] = "rm -rf /"
    watchdog._store.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    ok, errors = await watchdog.verify_once()
    assert ok is False and len(errors) >= 1

    events = _breaches(bus)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == BREACH
    assert event.source == "audit-watchdog"
    assert event.severity == EventSeverity.CRITICAL
    payload = event.payload
    assert payload["error_count"] >= 1
    assert payload["errors"], "errors 非空"
    assert payload["audit_path"] == str(watchdog._store.path)
    assert isinstance(payload["checked_at"], (int, float))


class _BoomStore:
    def __init__(self, tmp_path: Path) -> None:
        self.path = tmp_path / "audit.jsonl"

    def verify_chain(self):
        raise PermissionError("denied")


@pytest.mark.asyncio
async def test_t3_verify_raises_fail_closed_breach(tmp_path):
    bus = EventBus()
    watchdog = AuditWatchdog(bus, store=_BoomStore(tmp_path), interval=30)
    ok, errors = await watchdog.verify_once()
    assert ok is False
    assert "PermissionError" in errors[0]
    assert len(_breaches(bus)) == 1


@pytest.mark.asyncio
async def test_t4_verify_before_sleep(tmp_path):
    bus = EventBus()
    watchdog = AuditWatchdog(bus, store=_store(tmp_path), interval=30)
    await _append_three(watchdog._store)
    rows = [json.loads(line) for line in watchdog._store.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[0]["command"] = "rm -rf /"
    watchdog._store.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    task = asyncio.create_task(watchdog.run_forever())
    await asyncio.sleep(0.05)
    assert task.done() is False  # 进了 sleep，没提前返回
    assert len(_breaches(bus)) == 1  # 未等 interval 就校过一次
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_t5_interval_zero_runs_once(tmp_path):
    bus = EventBus()
    watchdog = AuditWatchdog(bus, store=_store(tmp_path), interval=0)
    await _append_three(watchdog._store)
    rows = [json.loads(line) for line in watchdog._store.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[2]["command"] = "rm -rf /"
    watchdog._store.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    await asyncio.wait_for(watchdog.run_forever(), timeout=1.0)  # 正常返回，不超时不卡死
    assert len(_breaches(bus)) == 1


@pytest.mark.asyncio
async def test_t6_tail_truncation_caught_by_witness(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    bus = EventBus()
    watchdog = AuditWatchdog(bus, store=_store(tmp_path), interval=30)
    await _append_three(watchdog._store)
    lines = [line for line in watchdog._store.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    watchdog._store.path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    ok_chain, chain_errors = watchdog._store.verify_chain()
    assert ok_chain is True and chain_errors == []  # 链自己看不出尾部截断

    ok, errors = await watchdog.verify_once()
    assert ok is False
    assert any(e.startswith("witness: ") for e in errors)

    events = _breaches(bus)
    assert len(events) == 1
    assert events[0].event_type == BREACH
    payload = events[0].payload
    assert payload["witness_violations"]
    assert payload["error_count"] >= 1
    assert payload["errors"] == []


@pytest.mark.asyncio
async def test_t7_witness_absent_reseeds_without_breach(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    bus = EventBus()
    watchdog = AuditWatchdog(bus, store=_store(tmp_path), interval=30)
    store = watchdog._store
    store.append(AuditEvent(event_id="a1", command="echo hi", event_type="tool_executed", risk="low"))
    store.append(AuditEvent(event_id="a2", command="echo hi", event_type="tool_executed", risk="low"))

    from trimum_core.audit_witness import read_witness, witness_path

    witness_path().unlink()

    ok, errors = await watchdog.verify_once()
    assert ok is True and errors == []

    reseeded = read_witness()
    assert reseeded is not None
    last_rows = [json.loads(l) for l in store.path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(last_rows) == 2
    assert reseeded["tail_hmac"] == last_rows[1]["hmac"]
    assert _breaches(bus) == []


@pytest.mark.asyncio
async def test_t8_no_audit_file_no_alarm_no_reseed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    bus = EventBus()
    store = AuditStore(path=tmp_path / "empty" / "audit.jsonl", hmac_key="k-watchdog")
    watchdog = AuditWatchdog(bus, store=store, interval=30)

    ok, errors = await watchdog.verify_once()
    assert ok is True and errors == []

    from trimum_core.audit_witness import read_witness

    assert read_witness() is None
    assert _breaches(bus) == []


@pytest.mark.asyncio
async def test_t9_witness_read_failure_is_fail_closed(tmp_path, monkeypatch):
    """读见证就抛异常 ⇒ 必须按违规处理（fail-closed），不许静默返回 []。"""
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    bus = EventBus()
    store = AuditStore(path=tmp_path / "audit.jsonl", hmac_key="k-a2m")
    store.append(AuditEvent(event_id="t9-1", command="echo hi",
                            event_type="tool_executed", risk="low"))
    watchdog = AuditWatchdog(bus, store=store, interval=30)

    import trimum_core.audit_watchdog as watchdog_mod

    def boom():
        raise RuntimeError("witness unreadable")

    monkeypatch.setattr(watchdog_mod, "read_witness", boom)

    ok, errors = await watchdog.verify_once()
    assert ok is False
    assert any(e.startswith("witness: witness check failed") for e in errors)
    breaches = _breaches(bus)
    assert len(breaches) == 1
    assert breaches[0].payload["witness_violations"]


@pytest.mark.asyncio
async def test_t10_witness_snapshot_failure_is_fail_closed(tmp_path, monkeypatch):
    """采当前状态就抛异常 ⇒ 同样按违规处理。"""
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    bus = EventBus()
    store = AuditStore(path=tmp_path / "audit.jsonl", hmac_key="k-a2m")
    store.append(AuditEvent(event_id="t10-1", command="echo hi",
                            event_type="tool_executed", risk="low"))
    watchdog = AuditWatchdog(bus, store=store, interval=30)

    import trimum_core.audit_watchdog as watchdog_mod

    def boom(_path):
        raise OSError("snapshot failed")

    monkeypatch.setattr(watchdog_mod, "snapshot", boom)

    ok, errors = await watchdog.verify_once()
    assert ok is False
    assert any(e.startswith("witness: witness check failed") for e in errors)
    assert len(_breaches(bus)) == 1
