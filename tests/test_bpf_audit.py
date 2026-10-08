"""eBPF 审计源（daemon 侧）测试：helper 回灌 ⇒ `security.ebpf_alert` 事件 + 审计。

口径：真调被测函数；假 bus / 假 audit_store，不碰真 `AuditStore` / `~/.trimum`。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import bpf_audit as B  # noqa: E402


def _line(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"


class _FakeBus:
    def __init__(self, *, raise_on_emit: bool = False):
        self.calls = []
        self.raise_on_emit = raise_on_emit

    async def emit_event(self, event_type, source, payload=None, severity=None):
        if self.raise_on_emit:
            raise RuntimeError("boom")
        self.calls.append((event_type, source, payload))


class _FakeAuditStore:
    def __init__(self, *, raise_on_append: bool = False):
        self.events = []
        self.raise_on_append = raise_on_append

    def append(self, event):
        if self.raise_on_append:
            raise RuntimeError("boom")
        self.events.append(event)


# ---- ① alert_path：显式 > env > config > 默认；各种坏值回默认 ----

def test_alert_path_explicit_wins(monkeypatch):
    monkeypatch.setenv(B.ALERT_PATH_ENV, "/env/path")

    class _Cfg:
        def get(self, key):
            return "/cfg/path"

    got = B.alert_path(explicit="/exp/path", config=_Cfg())
    assert got == B.Path("/exp/path")


def test_alert_path_env_when_no_explicit(monkeypatch):
    monkeypatch.setenv(B.ALERT_PATH_ENV, "/env/path")
    assert B.alert_path() == B.Path("/env/path")


def test_alert_path_env_empty_falls_to_config(monkeypatch):
    monkeypatch.setenv(B.ALERT_PATH_ENV, "   ")

    class _Cfg:
        def get(self, key):
            return "/cfg/path"

    assert B.alert_path(config=_Cfg()) == B.Path("/cfg/path")


def test_alert_path_env_empty_falls_to_default(monkeypatch):
    monkeypatch.setenv(B.ALERT_PATH_ENV, "")
    assert B.alert_path() == B.Path(B.DEFAULT_ALERT_PATH)


def test_alert_path_config_value(monkeypatch):
    monkeypatch.delenv(B.ALERT_PATH_ENV, raising=False)

    class _Cfg:
        def get(self, key):
            return "/cfg/path"

    assert B.alert_path(config=_Cfg()) == B.Path("/cfg/path")


def test_alert_path_config_empty_string_falls_to_default(monkeypatch):
    monkeypatch.delenv(B.ALERT_PATH_ENV, raising=False)

    class _Cfg:
        def get(self, key):
            return ""

    assert B.alert_path(config=_Cfg()) == B.Path(B.DEFAULT_ALERT_PATH)


def test_alert_path_config_non_string_falls_to_default(monkeypatch):
    monkeypatch.delenv(B.ALERT_PATH_ENV, raising=False)

    class _Cfg:
        def get(self, key):
            return 12345

    assert B.alert_path(config=_Cfg()) == B.Path(B.DEFAULT_ALERT_PATH)


def test_alert_path_config_raises_falls_to_default(monkeypatch):
    monkeypatch.delenv(B.ALERT_PATH_ENV, raising=False)

    class _Cfg:
        def get(self, key):
            raise RuntimeError("no config")

    assert B.alert_path(config=_Cfg()) == B.Path(B.DEFAULT_ALERT_PATH)


def test_alert_path_all_missing_falls_to_default(monkeypatch):
    monkeypatch.delenv(B.ALERT_PATH_ENV, raising=False)
    assert B.alert_path(config=None) == B.Path(B.DEFAULT_ALERT_PATH)


# ---- ② parse_alert_line ----

@pytest.mark.parametrize("kind", list(B.HELPER_ALERT_KINDS))
def test_parse_happy_alert_kinds(kind):
    a = B.parse_alert_line(_line({"kind": kind, "pid": 42, "comm": "trm", "detail": "x"}))
    assert a is not None
    assert a.kind == kind
    assert a.pid == 42
    assert a.comm == "trm"
    assert a.detail == "x"


def test_helper_alert_kinds_cover_both_programs():
    """`bpf_guard` 的四个 kind + `exec_guard` 的 `exec` 都要认得（否则 exec 事件被静默丢弃）。"""
    assert set(B.HELPER_ALERT_KINDS) == {"bpf_attach", "bpf_detach", "prog_load", "map_write", "exec"}
    alert = B.parse_alert_line(_line({"kind": "exec", "pid": 3, "comm": "bash",
                                      "detail": "/usr/bin/ls"}))
    assert alert is not None and alert.kind == "exec" and alert.detail == "/usr/bin/ls"


def test_parse_accepts_bytes_input():
    a = B.parse_alert_line(b'{"kind":"prog_load","pid":7}')
    assert a is not None
    assert a.kind == "prog_load"
    assert a.pid == 7


def test_parse_bad_utf8_bytes_returns_none():
    assert B.parse_alert_line(b"\xff\xfe\x00{") is None


def test_parse_pid_defaults_to_zero():
    a = B.parse_alert_line(_line({"kind": "map_write"}))
    assert a is not None
    assert a.pid == 0
    assert a.comm == ""
    assert a.detail == ""


def test_parse_truncates_long_comm_and_detail():
    long_comm = "c" * (B.MAX_COMM_LEN + 50)
    long_detail = "d" * (B.MAX_DETAIL_LEN + 100)
    a = B.parse_alert_line(_line({"kind": "bpf_attach", "comm": long_comm, "detail": long_detail}))
    assert a is not None
    assert len(a.comm) == B.MAX_COMM_LEN
    assert len(a.detail) == B.MAX_DETAIL_LEN


def test_parse_ignores_unknown_top_level_keys():
    a = B.parse_alert_line(_line({"kind": "bpf_detach", "pid": 3, "extra": 9, "another": [1, 2]}))
    assert a is not None
    assert a.kind == "bpf_detach"
    assert a.pid == 3


def test_parse_bad_json_returns_none():
    assert B.parse_alert_line(b"not-json{") is None


def test_parse_blank_line_returns_none():
    assert B.parse_alert_line(b"   \n  ") is None
    assert B.parse_alert_line("") is None


def test_parse_non_dict_top_level_returns_none():
    assert B.parse_alert_line(b"[1,2,3]") is None
    assert B.parse_alert_line(b'"just a string"') is None


def test_parse_unknown_kind_returns_none():
    assert B.parse_alert_line(_line({"kind": "suspicious", "pid": 1})) is None


def test_parse_negative_pid_returns_none():
    assert B.parse_alert_line(_line({"kind": "prog_load", "pid": -5})) is None


def test_parse_string_pid_returns_none():
    assert B.parse_alert_line(_line({"kind": "prog_load", "pid": "12"})) is None


def test_parse_bool_pid_returns_none():
    assert B.parse_alert_line(_line({"kind": "prog_load", "pid": True})) is None


# ---- ③ to_bus_payload：四键逐字 ----

def test_to_bus_payload_exact_keys():
    a = B.BpfAlert(kind="map_write", pid=9, comm="trm", detail="w")
    payload = B.to_bus_payload(a)
    assert set(payload) == {"kind", "pid", "comm", "detail"}
    assert payload == {"kind": "map_write", "pid": 9, "comm": "trm", "detail": "w"}


# ---- ④ to_audit_event ----

def test_to_audit_event_fields():
    a = B.BpfAlert(kind="prog_load", pid=1, comm="c", detail="d")
    ev = B.to_audit_event(a, timestamp=1234.5)
    assert ev.event_type == "security.ebpf_alert"
    assert ev.source_type == "bpf-helper"
    assert ev.risk == "high"
    assert ev.action == "alert"
    assert ev.reason == "eBPF helper 告警：prog_load"
    assert set(ev.details) == {"kind", "pid", "comm", "detail"}
    assert ev.timestamp == 1234.5


def test_to_audit_event_defaults_and_untouched_chain():
    a = B.BpfAlert(kind="bpf_attach")
    ev = B.to_audit_event(a, timestamp=100.0)
    assert ev.event_id == ""
    assert ev.hmac == ""
    assert ev.prev_hash == ""
    assert ev.agent_id == ""


# ---- ⑤ read_new_alerts ----

def test_read_three_lines_then_incremental(tmp_path):
    p = tmp_path / "alerts.jsonl"
    base = {
        "bpf_attach": _line({"kind": "bpf_attach", "pid": 1}),
        "bpf_detach": _line({"kind": "bpf_detach", "pid": 2}),
        "prog_load": _line({"kind": "prog_load", "pid": 3}),
    }
    p.write_bytes(base["bpf_attach"] + base["bpf_detach"] + base["prog_load"])
    size = p.stat().st_size

    alerts, new_offset = B.read_new_alerts(p, 0)
    assert len(alerts) == 3
    assert new_offset == size

    # 追加 1 行，只拿到新增
    p.write_bytes(p.read_bytes() + _line({"kind": "map_write", "pid": 4}))
    alerts2, new_offset2 = B.read_new_alerts(p, new_offset)
    assert len(alerts2) == 1
    assert alerts2[0].kind == "map_write"
    assert new_offset2 == p.stat().st_size


def test_read_bad_line_does_not_block_good_line(tmp_path):
    p = tmp_path / "alerts.jsonl"
    good1 = _line({"kind": "prog_load", "pid": 1})
    bad = b"this is not json\n"
    good2 = _line({"kind": "map_write", "pid": 2})
    p.write_bytes(good1 + bad + good2)

    alerts, new_offset = B.read_new_alerts(p, 0)
    assert [a.kind for a in alerts] == ["prog_load", "map_write"]
    assert new_offset == p.stat().st_size


def test_read_half_line_not_consumed_until_completed(tmp_path):
    p = tmp_path / "alerts.jsonl"
    first = _line({"kind": "bpf_attach", "pid": 1})
    half = _line({"kind": "map_write", "pid": 2})[:-1]  # 去掉结尾 \n
    p.write_bytes(first + half)
    half_start = len(first)

    alerts, new_offset = B.read_new_alerts(p, 0)
    assert [a.kind for a in alerts] == ["bpf_attach"]
    assert new_offset == half_start  # offset 停在半行起点

    # 补齐 \n 后再读能拿到半行
    p.write_bytes(p.read_bytes() + b"\n")
    alerts2, new_offset2 = B.read_new_alerts(p, new_offset)
    assert [a.kind for a in alerts2] == ["map_write"]
    assert new_offset2 == p.stat().st_size


def test_read_missing_file_returns_empty_keeps_offset(tmp_path):
    missing = tmp_path / "nope.jsonl"
    alerts, new_offset = B.read_new_alerts(missing, 123)
    assert alerts == []
    assert new_offset == 123


def test_read_offset_larger_than_file_resets_to_zero(tmp_path):
    p = tmp_path / "alerts.jsonl"
    p.write_bytes(_line({"kind": "prog_load", "pid": 1}))
    alerts, new_offset = B.read_new_alerts(p, 99999)
    assert [a.kind for a in alerts] == ["prog_load"]
    assert new_offset == p.stat().st_size


def test_read_bad_offset_types_treated_as_zero(tmp_path):
    p = tmp_path / "alerts.jsonl"
    p.write_bytes(_line({"kind": "prog_load", "pid": 1}))
    for bad in (-5, None, 1.5):
        alerts, new_offset = B.read_new_alerts(p, bad)  # type: ignore[arg-type]
        assert [a.kind for a in alerts] == ["prog_load"]
        assert new_offset == p.stat().st_size


# ---- ⑥ publish_alert（async） ----

@pytest.mark.asyncio
async def test_publish_alert_bus_and_audit():
    bus = _FakeBus()
    store = _FakeAuditStore()
    a = B.BpfAlert(kind="prog_load", pid=5, comm="trm", detail="x")

    ok = await B.publish_alert(a, bus=bus, audit_store=store)
    assert ok is True
    assert len(bus.calls) == 1
    etype, source, payload = bus.calls[0]
    assert etype == "security.ebpf_alert"
    assert source == "bpf-helper"
    assert set(payload) == {"kind", "pid", "comm", "detail"}
    assert len(store.events) == 1
    assert store.events[0].event_type == "security.ebpf_alert"
    assert store.events[0].details == B.to_bus_payload(a)


@pytest.mark.asyncio
async def test_publish_alert_bus_raises_returns_false_not_raised():
    bus = _FakeBus(raise_on_emit=True)
    store = _FakeAuditStore()
    a = B.BpfAlert(kind="map_write", pid=1)
    ok = await B.publish_alert(a, bus=bus, audit_store=store)
    # audit_store 成功 ⇒ 至少成功一步 ⇒ True；关键是不抛
    assert ok is True
    assert len(store.events) == 1


@pytest.mark.asyncio
async def test_publish_alert_both_raise_returns_false():
    bus = _FakeBus(raise_on_emit=True)
    store = _FakeAuditStore(raise_on_append=True)
    a = B.BpfAlert(kind="bpf_attach", pid=1)
    ok = await B.publish_alert(a, bus=bus, audit_store=store)
    assert ok is False
    assert bus.calls == []
    assert store.events == []


@pytest.mark.asyncio
async def test_publish_alert_both_none_returns_false():
    a = B.BpfAlert(kind="bpf_detach", pid=1)
    assert (await B.publish_alert(a, bus=None, audit_store=None)) is False


@pytest.mark.asyncio
async def test_publish_alert_only_audit_store_returns_true():
    store = _FakeAuditStore()
    a = B.BpfAlert(kind="prog_load", pid=2)
    ok = await B.publish_alert(a, bus=None, audit_store=store)
    assert ok is True
    assert len(store.events) == 1


@pytest.mark.asyncio
async def test_publish_alert_only_bus_returns_true():
    bus = _FakeBus()
    a = B.BpfAlert(kind="map_write", pid=3)
    ok = await B.publish_alert(a, bus=bus, audit_store=None)
    assert ok is True
    assert len(bus.calls) == 1


# ---- ⑦ BpfAlertTailer ----

def test_tailer_seek_end_skips_history_and_polls_incremental(tmp_path):
    p = tmp_path / "alerts.jsonl"
    p.write_bytes(_line({"kind": "bpf_attach", "pid": 1}) + _line({"kind": "bpf_detach", "pid": 2}))

    tailer = B.BpfAlertTailer(p)
    assert tailer.path == B.Path(p)
    assert tailer.offset == 0

    new_offset = tailer.seek_end()
    assert new_offset == p.stat().st_size
    assert tailer.offset == new_offset
    assert tailer.poll() == []  # 历史不重放

    # 追加 1 行，poll 只拿到这 1 条
    p.write_bytes(p.read_bytes() + _line({"kind": "map_write", "pid": 3}))
    got = tailer.poll()
    assert [a.kind for a in got] == ["map_write"]
    assert tailer.offset == p.stat().st_size


def test_tailer_path_defaults_to_alert_path(monkeypatch, tmp_path):
    monkeypatch.setenv(B.ALERT_PATH_ENV, str(tmp_path / "env.jsonl"))
    tailer = B.BpfAlertTailer()
    assert tailer.path == B.Path(tmp_path / "env.jsonl")
    assert tailer.offset == 0


def test_tailer_seek_end_missing_file_returns_zero(tmp_path):
    tailer = B.BpfAlertTailer(tmp_path / "absent.jsonl")
    assert tailer.seek_end() == 0
    assert tailer.poll() == []


# ---- alert_interval（ebpf1f：显式 > env > config > 默认） ----

class _Cfg:
    def __init__(self, value):
        self._value = value

    def get(self, key):
        return self._value


def test_alert_interval_explicit_wins(monkeypatch):
    monkeypatch.setenv(B.ALERT_INTERVAL_ENV, "9")
    cfg = _Cfg(7)
    assert B.alert_interval(explicit=3.5, config=cfg) == 3.5


def test_alert_interval_explicit_int_and_float():
    assert B.alert_interval(explicit=2) == 2.0
    assert B.alert_interval(explicit=0.25) == 0.25


@pytest.mark.parametrize("bad", ["abc", 0, -1.5, True])
def test_alert_interval_explicit_bad_falls_through_to_env(monkeypatch, bad):
    monkeypatch.setenv(B.ALERT_INTERVAL_ENV, "4")
    assert B.alert_interval(explicit=bad) == 4.0


def test_alert_interval_env_when_no_explicit(monkeypatch):
    monkeypatch.delenv(B.ALERT_INTERVAL_ENV, raising=False)
    monkeypatch.setenv(B.ALERT_INTERVAL_ENV, "6.5")
    assert B.alert_interval() == 6.5


@pytest.mark.parametrize("raw", ["", "abc"])
def test_alert_interval_env_empty_or_bad_falls_to_config(monkeypatch, raw):
    monkeypatch.setenv(B.ALERT_INTERVAL_ENV, raw)
    assert B.alert_interval(config=_Cfg(5)) == 5.0


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_alert_interval_env_non_positive_falls_to_config(monkeypatch, raw):
    monkeypatch.setenv(B.ALERT_INTERVAL_ENV, raw)
    assert B.alert_interval(config=_Cfg(5)) == 5.0


def test_alert_interval_config_value():
    cfg = _Cfg(7.5)
    assert B.alert_interval(config=cfg) == 7.5


@pytest.mark.parametrize("bad", [True, "7", 0, -2, None])
def test_alert_interval_config_bad_falls_to_default(monkeypatch, bad):
    monkeypatch.delenv(B.ALERT_INTERVAL_ENV, raising=False)
    assert B.alert_interval(config=_Cfg(bad)) == B.DEFAULT_POLL_INTERVAL_SECONDS


def test_alert_interval_config_raises_falls_to_default(monkeypatch):
    monkeypatch.delenv(B.ALERT_INTERVAL_ENV, raising=False)

    class _Boom:
        def get(self, key):
            raise RuntimeError("boom")

    assert B.alert_interval(config=_Boom()) == B.DEFAULT_POLL_INTERVAL_SECONDS


def test_alert_interval_all_missing_falls_to_default(monkeypatch):
    monkeypatch.delenv(B.ALERT_INTERVAL_ENV, raising=False)
    assert B.alert_interval() == 2.0
    assert B.DEFAULT_POLL_INTERVAL_SECONDS == 2.0


# ---- BpfAlertPoller（ebpf1f：seek_end 跳历史 + 轮询发布） ----

@pytest.mark.asyncio
async def test_poller_seek_end_then_poll_once_publishes_only_new(tmp_path):
    p = tmp_path / "alerts.jsonl"
    p.write_bytes(_line({"kind": "bpf_attach", "pid": 11}))
    bus = _FakeBus()
    store = _FakeAuditStore()
    poller = B.BpfAlertPoller(bus=bus, audit_store=store, path=p, interval=60.0)
    assert poller.tailer.seek_end() > 0
    assert await poller.poll_once() == 0
    assert bus.calls == []
    p.write_bytes(p.read_bytes() + _line({"kind": "exec", "pid": 22, "comm": "bash", "detail": "x"}))
    assert await poller.poll_once() == 1
    assert bus.calls == [
        (B.EVENT_SEC_EBPF, B.EVENT_SOURCE, {"kind": "exec", "pid": 22, "comm": "bash", "detail": "x"})
    ]
    assert len(store.events) == 1
    assert store.events[0].event_type == B.EVENT_SEC_EBPF
    assert store.events[0].details == {"kind": "exec", "pid": 22, "comm": "bash", "detail": "x"}
    assert store.events[0].risk == "high"
    assert store.events[0].action == "alert"


@pytest.mark.asyncio
async def test_poller_poll_once_swallows_publish_failure(tmp_path):
    p = tmp_path / "alerts.jsonl"
    p.write_bytes(b"")  # 空文件：构造时 seek_end 推到 0
    poller = B.BpfAlertPoller(
        bus=_FakeBus(raise_on_emit=True),
        audit_store=_FakeAuditStore(raise_on_append=True),
        path=p,
        interval=60.0,
    )
    # 构造后追加 2 行（对 poller 来说是「新」行，不是历史）
    p.write_bytes(p.read_bytes() + _line({"kind": "prog_load", "pid": 1}) + _line({"kind": "map_write", "pid": 2}))
    assert await poller.poll_once() == 2


@pytest.mark.asyncio
async def test_poller_poll_once_missing_file_returns_zero(tmp_path):
    bus = _FakeBus()
    store = _FakeAuditStore()
    poller = B.BpfAlertPoller(
        bus=bus,
        audit_store=store,
        path=tmp_path / "nope.jsonl",
        interval=60.0,
    )
    assert await poller.poll_once() == 0
    assert bus.calls == []


def test_poller_defaults_path_from_alert_path(monkeypatch):
    monkeypatch.delenv(B.ALERT_INTERVAL_ENV, raising=False)
    poller = B.BpfAlertPoller()
    assert poller.path == B.alert_path()


@pytest.mark.asyncio
async def test_poller_defaults_path_and_poll_no_side_effect(tmp_path, monkeypatch):
    monkeypatch.delenv(B.ALERT_INTERVAL_ENV, raising=False)
    poller = B.BpfAlertPoller(bus=None, audit_store=None)
    assert poller.path == B.alert_path()
    assert await poller.poll_once() == 0


def test_poller_interval_from_explicit_config_and_env(monkeypatch):
    # 显式优先：env 设了 1.5、config 给 3，但传了 interval=0.5 ⇒ 仍是 0.5
    monkeypatch.setenv(B.ALERT_INTERVAL_ENV, "1.5")
    assert B.BpfAlertPoller(interval=0.5).interval == 0.5
    assert B.BpfAlertPoller(interval=0.5, config=_Cfg(3)).interval == 0.5
    # 不传 interval：去掉 env 后落到 config ⇒ 3.0
    monkeypatch.delenv(B.ALERT_INTERVAL_ENV, raising=False)
    assert B.BpfAlertPoller(config=_Cfg(3)).interval == 3.0


@pytest.mark.asyncio
async def test_poller_run_forever_no_replay_and_reads_new(tmp_path):
    p = tmp_path / "alerts.jsonl"
    p.write_bytes(_line({"kind": "bpf_attach", "pid": 1}))
    bus = _FakeBus()
    store = _FakeAuditStore()
    poller = B.BpfAlertPoller(bus=bus, audit_store=store, path=p, interval=0.01)
    task = asyncio.create_task(poller.run_forever())
    await asyncio.sleep(0.05)  # 让首轮 seek_end 跑完
    p.write_bytes(p.read_bytes() + _line({"kind": "map_write", "pid": 5}))
    deadline = time.monotonic() + 3.0
    while len(store.events) < 1 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert len(store.events) == 1
    assert store.events[0].details["kind"] == "map_write"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_poller_run_forever_survives_publish_failure(tmp_path):
    p = tmp_path / "alerts.jsonl"
    p.write_bytes(_line({"kind": "prog_load", "pid": 1}))
    poller = B.BpfAlertPoller(
        bus=_FakeBus(raise_on_emit=True),
        audit_store=None,
        path=p,
        interval=0.01,
    )
    task = asyncio.create_task(poller.run_forever())
    await asyncio.sleep(0.05)
    assert not task.done()
    p.write_bytes(p.read_bytes() + _line({"kind": "map_write", "pid": 2}))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
