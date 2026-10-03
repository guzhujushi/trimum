"""SystemMonitor 事件出口 + agent.status_changed 前缀 bug 的判别用例。

所有用例都不真读真机指标：用 monkeypatch 把 ``system_monitor.psutil`` 换成假对象。
事件断言用 ``EventBus().get_history()``（publish 同步写 history，await 完即可直接看）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import system_monitor  # noqa: E402
from trimum_core.agent_runtime import AgentRuntime  # noqa: E402
from trimum_core.agent_socket import SocketMessage, MSG_STATUS  # noqa: E402
from trimum_core.event_bus import EventBus  # noqa: E402
from trimum_core.models import EventSeverity  # noqa: E402
from trimum_core.system_monitor import (  # noqa: E402
    DEFAULT_INTERVAL_SECONDS,
    EVENT_SYSTEM_ALERT,
    EVENT_SYSTEM_HEARTBEAT,
    SystemMonitor,
    default_interval,
)

HEARTBEAT = "system.heartbeat"
ALERT = "system.alert"


class _FakeVm:
    def __init__(self, total, used, available, percent):
        self.total = total
        self.used = used
        self.available = available
        self.percent = percent


class _FakeDiskUsage:
    def __init__(self, total, used, free, percent):
        self.total = total
        self.used = used
        self.free = free
        self.percent = percent


class _FakeDiskPart:
    def __init__(self, mountpoint, fstype):
        self.mountpoint = mountpoint
        self.fstype = fstype


class _FakeNet:
    def __init__(self):
        self.bytes_sent = 100 * 1024 * 1024
        self.bytes_recv = 200 * 1024 * 1024
        self.packets_sent = 10
        self.packets_recv = 20


class _FakePsutil:
    """假 psutil：cpu/mem/load 可控，并记录「已完成采集次数」。"""

    def __init__(self, cpu=10.0, mem=20.0, load=1.0):
        self._cpu = cpu
        self._mem = mem
        self._load = load
        self.collects = 0

    def cpu_percent(self, interval=None):
        self.collects += 1
        return self._cpu

    def cpu_count(self):
        return 4

    def getloadavg(self):
        return (self._load, self._load, self._load)

    def virtual_memory(self):
        total = 16 * 1024 ** 3
        used = int(total * self._mem / 100.0)
        return _FakeVm(total, used, total - used, self._mem)

    def disk_partitions(self):
        return [_FakeDiskPart("/", "ext4")]

    def disk_usage(self, mp):
        total = 100 * 1024 ** 3
        used = int(total * 0.10)
        return _FakeDiskUsage(total, used, total - used, 10.0)

    def net_io_counters(self):
        return _FakeNet()

    def boot_time(self):
        return 0.0


def _heartbeats(bus: EventBus) -> list:
    return [e for e in bus.get_history() if e.event_type == HEARTBEAT]


def _alerts(bus: EventBus) -> list:
    return [e for e in bus.get_history() if e.event_type == ALERT]


@pytest.mark.asyncio
async def test_t1_heartbeat_event(monkeypatch):
    monkeypatch.setattr(system_monitor, "psutil", _FakePsutil(cpu=10.0, mem=20.0, load=1.0))
    bus = EventBus()
    monitor = SystemMonitor(bus)
    await monitor.collect()

    hbs = _heartbeats(bus)
    assert len(hbs) == 1
    event = hbs[0]
    assert event.event_type == HEARTBEAT  # 精确相等，不是 event. 前缀
    assert event.source == "system-monitor"
    assert event.severity == EventSeverity.INFO
    assert event.payload["alerts"] == 0
    assert event.payload["cpu_percent"] == 10.0


@pytest.mark.asyncio
async def test_t2_alert_events(monkeypatch):
    monkeypatch.setattr(system_monitor, "psutil", _FakePsutil(cpu=95.0, mem=90.0, load=1.0))
    bus = EventBus()
    monitor = SystemMonitor(bus)
    await monitor.collect()

    assert len(_heartbeats(bus)) == 1
    assert _heartbeats(bus)[0].payload["alerts"] == 2

    al = _alerts(bus)
    assert len(al) == 2
    assert all(e.severity == EventSeverity.WARNING for e in al)
    types = {e.payload["type"] for e in al}
    assert types == {"cpu_high", "memory_high"}


def test_t3_default_interval(monkeypatch):
    monkeypatch.delenv("TRIMUM_SYSTEM_MONITOR_INTERVAL", raising=False)
    assert default_interval() == DEFAULT_INTERVAL_SECONDS == 60.0
    monkeypatch.setenv("TRIMUM_SYSTEM_MONITOR_INTERVAL", "15")
    assert default_interval() == 15.0
    monkeypatch.setenv("TRIMUM_SYSTEM_MONITOR_INTERVAL", "abc")
    assert default_interval() == 60.0  # 解析失败回退默认，不抛


@pytest.mark.asyncio
async def test_t4_loop_nonblocking_and_runs_once(monkeypatch):
    fake = _FakePsutil(cpu=10.0, mem=20.0, load=1.0)
    monkeypatch.setattr(system_monitor, "psutil", fake)
    bus = EventBus()
    monitor = SystemMonitor(bus, interval=0.05)
    task = asyncio.create_task(monitor.start_collecting())
    await asyncio.sleep(0.25)
    assert len(_heartbeats(bus)) >= 1
    assert 1 <= fake.collects <= 6  # ≥1 且没有重复刷屏
    monitor.stop_collecting()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # interval<=0 ⇒ 只采一次就正常返回
    fake2 = _FakePsutil(cpu=10.0, mem=20.0, load=1.0)
    monkeypatch.setattr(system_monitor, "psutil", fake2)
    bus2 = EventBus()
    monitor2 = SystemMonitor(bus2, interval=0.05)
    await asyncio.wait_for(monitor2.start_collecting(interval=0), timeout=1.0)
    assert fake2.collects == 1
    assert len(_heartbeats(bus2)) == 1


@pytest.mark.asyncio
async def test_t5_legacy_callback_compatible(monkeypatch):
    fake = _FakePsutil(cpu=95.0, mem=90.0, load=1.0)
    monkeypatch.setattr(system_monitor, "psutil", fake)
    bus = EventBus()
    monitor = SystemMonitor(bus)
    calls: list = []
    monitor.set_event_callback(lambda et, payload: calls.append((et, payload)))
    await monitor.collect()

    assert len(calls) >= 1
    assert calls[0][0] == "system.alert" == EVENT_SYSTEM_ALERT
    assert calls[0][1]["type"] in {"cpu_high", "memory_high"}


@pytest.mark.asyncio
async def test_t6_agent_status_changed_exact_type(tmp_path):
    bus = EventBus()
    runtime = AgentRuntime(socket_path=str(tmp_path / "rt.sock"), event_bus=bus)
    await runtime._handle_status(SocketMessage(MSG_STATUS, "a1", {"status": "running"}))

    matches = [e for e in bus.get_history() if e.event_type == "agent.status_changed"]
    assert len(matches) == 1
    assert matches[0].event_type == "agent.status_changed"  # 精确，不带 event. 前缀
    assert matches[0].source == "agent:a1"
    assert matches[0].payload["status"] == "running"
