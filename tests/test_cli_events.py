"""Tests for the `trm events` read-only observability exit.

Every case isolates itself with monkeypatched RPC — nothing here talks to a
real daemon, socket, or the on-disk ``~/.trimum`` state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.cli import main  # noqa: E402
from trimum_core.cli.commands import events as events_mod  # noqa: E402
from trimum_core.cli.commands import status as status_mod  # noqa: E402
from trimum_core.event_bus import EventBus  # noqa: E402
from trimum_core.models import EventSeverity  # noqa: E402


def _fake_rpc(history, health=None, calls=None):
    def fake(config, method, params=None, timeout=2.0):
        if calls is not None:
            calls.append((method, params))
        if method == "events.history":
            return history
        if method == "health":
            return health if health is not None else {}
        raise AssertionError(f"unexpected rpc method: {method}")

    return fake


class FakeConfig:
    host = "127.0.0.1"
    port = 8321
    socket_path = "/tmp/trimum-test-events.sock"


def test_events_history_and_stats_json(monkeypatch, capsys):
    history = [{
        "event_type": "tool.executed",
        "source": "core",
        "severity": EventSeverity.WARNING,
        "payload": {"cmd": "ls"},
        "timestamp": 1730000000.0,
    }]
    health = {"bus": {
        "patterns": 1,
        "subscribers": 2,
        "history": 1,
        "in_flight": 0,
        "dispatch_failures": 0,
        "last_failure": None,
        "strict": False,
    }}
    monkeypatch.setattr(events_mod, "rpc_call", _fake_rpc(history, health))
    assert main(["--json", "events"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 1
    assert data["events"][0]["event_type"] == "tool.executed"
    assert data["stats"]["subscribers"] == 2


def test_events_limit_is_forwarded(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        events_mod,
        "rpc_call",
        _fake_rpc([], {"bus": {}}, calls),
    )
    assert main(["--json", "events", "--limit", "2"]) == 0
    capsys.readouterr()
    assert ("events.history", {"limit": 2}) in calls


def test_events_offline_fails_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(events_mod, "rpc_call", lambda *a, **k: None)
    assert main(["events"]) == 1
    out, err = capsys.readouterr()
    assert "daemon" in err
    assert out == ""


def test_events_empty_history_is_not_offline(monkeypatch, capsys):
    history = []
    health = {"bus": {"patterns": 0, "subscribers": 0, "history": 0, "dispatch_failures": 0}}
    monkeypatch.setattr(events_mod, "rpc_call", _fake_rpc(history, health))
    assert main(["--json", "events"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 0
    assert data["events"] == []


def test_events_limit_and_interval_zero_exit_early(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        events_mod,
        "rpc_call",
        _fake_rpc([], {"bus": {}}, calls),
    )
    assert main(["events", "--limit", "0"]) == 1
    _, err = capsys.readouterr()
    assert "positive" in err
    assert calls == []
    assert main(["events", "--follow", "--interval", "0"]) == 1
    _, err = capsys.readouterr()
    assert "positive" in err
    assert calls == []


def test_events_follow_only_prints_new(monkeypatch, capsys):
    e1 = {"event_type": "a.started", "source": "core", "severity": "info", "payload": {}, "timestamp": 1.0}
    e2 = {"event_type": "b.done", "source": "core", "severity": "info", "payload": {}, "timestamp": 2.0}
    state = {"n": 0}

    def fake(config, method, params=None, timeout=2.0):
        if method == "events.history":
            state["n"] += 1
            return [e1] if state["n"] == 1 else [e1, e2]
        if method == "health":
            return {}
        raise AssertionError(f"unexpected rpc method: {method}")

    monkeypatch.setattr(events_mod, "rpc_call", fake)

    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise KeyboardInterrupt
        return None

    monkeypatch.setattr(events_mod.time, "sleep", fake_sleep)
    assert main(["events", "--follow", "--interval", "0.5"]) == 0
    out = capsys.readouterr().out
    assert out.count("a.started") == 1
    assert out.count("b.done") == 1
    assert sleeps and sleeps[0] == 0.5


def test_status_includes_bus(monkeypatch):
    monkeypatch.setattr(
        status_mod,
        "get_daemon_status",
        lambda config: {
            "running": True,
            "source": "rpc",
            "health": {"version": "0.5.0", "bus": {"patterns": 3, "subscribers": 4}},
        },
    )
    monkeypatch.setattr(status_mod, "_find_daemon_pid", lambda *a, **k: None)
    monkeypatch.setattr(status_mod, "_process_info", lambda pid: None)
    monkeypatch.setattr(status_mod, "_system_snapshot", lambda: {})
    monkeypatch.setattr(status_mod, "_agent_count", lambda config: 0)
    data = status_mod.get_status_data(FakeConfig())
    assert data["bus"]["patterns"] == 3

    monkeypatch.setattr(
        status_mod,
        "get_daemon_status",
        lambda config: {"running": False, "source": None, "health": None},
    )
    data = status_mod.get_status_data(FakeConfig())
    assert data["bus"] is None


def test_events_human_normalises_severity(monkeypatch, capsys):
    history = [{
        "event_type": "tool.executed",
        "source": "core",
        "severity": EventSeverity.WARNING,
        "payload": {},
        "timestamp": 1730000000.0,
    }]
    health = {"bus": {"patterns": 1, "subscribers": 2, "history": 1, "dispatch_failures": 0}}
    monkeypatch.setattr(events_mod, "rpc_call", _fake_rpc(history, health))
    assert main(["events"]) == 0
    out = capsys.readouterr().out
    assert "tool.executed" in out
    assert "warning" in out
    assert "1 event" in out
    assert "EventSeverity" not in out


def test_health_payload_includes_bus_stats():
    """钉住 `api_server._health_payload` 真的把总线统计发出去（删掉那 3 行必挂）。"""
    from trimum_core.api_server import _health_payload

    class _Cfg:
        socket_path = "/tmp/x.sock"
        http_enabled = False

    class _State:
        event_bus = EventBus()
        ipc = None  # _health_payload 硬读 state.ipc；置 None ⇒ 不产生 "ipc" 键

    payload = _health_payload(_Cfg(), _State())
    assert set(payload["bus"]) == {
        "patterns",
        "subscribers",
        "history",
        "in_flight",
        "dispatch_failures",
        "last_failure",
        "strict",
    }
    assert payload["bus"]["history"] == 0
    # state 可能是 None（老路径 / 轻量构造）⇒ 不许抛 AttributeError，也不许有 bus 键
    assert "bus" not in _health_payload(_Cfg(), None)
