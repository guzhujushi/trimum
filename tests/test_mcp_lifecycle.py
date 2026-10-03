"""Lifecycle tests for the MCP pool (M4): idle reaping and cgroup binding.

Both are driven with a fake client, a fake clock and a fake resource controller,
so "five minutes idle" is a number in a variable rather than a sleep, and the
cgroup path is exercised in all three shapes (bound / unavailable / error)
without needing root or a real ``/sys/fs/cgroup``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.mcp_registry import MCPServerPool, MCPRegistry  # noqa: E402


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeClient:
    """Stands in for ``MCPClient``: no process, no pipes."""

    def __init__(self, definition, *, pid: int | None = None) -> None:
        self.definition = definition
        self.name = definition.name
        self.pid = pid
        self.alive = False
        self.broken = ""
        self.connects = 0
        self.closed = 0

    async def connect(self) -> None:
        self.connects += 1
        self.alive = True

    async def close(self) -> None:
        self.closed += 1
        self.alive = False

    def to_dict(self) -> dict:
        return {"server": self.name, "alive": self.alive, "pid": self.pid}


class FakeCgroup:
    """Records ``apply_cgroup`` calls; ``land=False`` mimics a non-root host."""

    def __init__(self, *, land: bool = True, explode: bool = False) -> None:
        self.calls: list[tuple[str, int, object]] = []
        self.bound: dict[str, list[int]] = {}
        self.land = land
        self.explode = explode

    async def apply_cgroup(self, agent_id: str, pid: int, limits) -> None:
        if self.explode:
            raise PermissionError("/sys/fs/cgroup is not writable")
        self.calls.append((agent_id, pid, limits))
        if self.land:
            self.bound.setdefault(agent_id, []).append(pid)

    async def assigned_pids(self, agent_id: str) -> list[int]:
        return list(self.bound.get(agent_id, []))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def registry(tmp_path: Path, **overrides) -> MCPRegistry:
    directory = tmp_path / "mcp"
    directory.mkdir(parents=True, exist_ok=True)
    fields = {
        "idle_ttl": 300.0,
        **overrides,
    }
    body = ", ".join(
        f"{key}: {value}" if not isinstance(value, str) else f'{key}: "{value}"'
        for key, value in fields.items()
    )
    (directory / "echo.json5").write_text(
        '{ name: "echo", transport: "stdio", command: "python", enabled: true, %s }' % body,
        encoding="utf-8",
    )
    return MCPRegistry(directory)


def pool(tmp_path: Path, *, clock: Clock, clients: list | None = None, **kwargs):
    made: list[FakeClient] = clients if clients is not None else []

    def factory(definition):
        client = FakeClient(definition, pid=kwargs.pop("_pid", 4242) if False else 4242)
        made.append(client)
        return client

    return (
        MCPServerPool(registry(tmp_path, **kwargs.pop("definition", {})), client_factory=factory, clock=clock, **kwargs),
        made,
    )


# ---------------------------------------------------------------------------
# Idle reaping
# ---------------------------------------------------------------------------


class TestIdleReaping:
    @pytest.mark.asyncio
    async def test_idle_client_is_reaped_after_its_ttl(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock, definition={"idle_ttl": 300})
        try:
            client = await pool_.client("echo")
            clock.advance(299)
            assert await pool_.reap() == []
            clock.advance(2)
            assert await pool_.reap() == ["echo"]
            assert client.closed == 1
            assert pool_.clients == {}
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_using_a_client_resets_its_idle_timer(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock, definition={"idle_ttl": 100})
        try:
            await pool_.client("echo")
            clock.advance(90)
            await pool_.client("echo")  # touched again
            clock.advance(90)
            assert await pool_.reap() == []
            clock.advance(11)
            assert await pool_.reap() == ["echo"]
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_zero_ttl_means_keep_resident(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock, definition={"idle_ttl": 0})
        try:
            client = await pool_.client("echo")
            clock.advance(10_000)
            assert await pool_.reap() == []
            assert client.alive is True
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_reaping_twice_is_harmless(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock, definition={"idle_ttl": 10})
        try:
            await pool_.client("echo")
            clock.advance(11)
            assert await pool_.reap() == ["echo"]
            assert await pool_.reap() == []
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_status_reports_idle_seconds_and_pid(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock, definition={"idle_ttl": 120})
        try:
            await pool_.client("echo")
            clock.advance(12.34)
            row = (await pool_.status())[0]
            assert row["connected"] is True
            assert row["idle_seconds"] == 12.3
            assert row["idle_ttl"] == 120
            assert row["pid"] == 4242
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_idle_seconds_is_none_when_not_running(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock)
        try:
            assert (await pool_.status())[0]["idle_seconds"] is None
            assert pool_.idle_seconds("echo") is None
        finally:
            await pool_.close_all()


class TestBackgroundReaper:
    @pytest.mark.asyncio
    async def test_reaper_task_reaps_without_being_asked(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock, definition={"idle_ttl": 5})
        try:
            client = await pool_.client("echo")
            task = pool_.start_reaper(interval=0.02)
            assert task is not None
            clock.advance(6)
            await asyncio.sleep(0.15)
            assert client.closed == 1
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_start_reaper_is_idempotent(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock)
        try:
            first = pool_.start_reaper(interval=30)
            assert pool_.start_reaper(interval=30) is first
            await pool_.stop_reaper()
            assert first.cancelled() or first.done()
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_stop_reaper_is_safe_when_never_started(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock)
        await pool_.stop_reaper()

    @pytest.mark.asyncio
    async def test_a_failing_sweep_does_not_kill_the_loop(self, tmp_path, monkeypatch):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock)
        calls = {"count": 0}

        async def flaky(now=None):
            calls["count"] += 1
            raise RuntimeError("boom")

        monkeypatch.setattr(pool_, "reap", flaky)
        try:
            pool_.start_reaper(interval=0.02)
            # 等条件而不是等固定时长：整机满载时 0.2s 可能只够跑一轮
            for _ in range(50):
                if calls["count"] >= 2:
                    break
                await asyncio.sleep(0.05)
            assert calls["count"] >= 2
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_close_all_stops_the_reaper(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock)
        task = pool_.start_reaper(interval=30)
        await pool_.close_all()
        assert task.done()


# ---------------------------------------------------------------------------
# cgroup binding
# ---------------------------------------------------------------------------


class TestCgroupBinding:
    @pytest.mark.asyncio
    async def test_stdio_child_is_bound_and_verified(self, tmp_path):
        clock = Clock()
        cgroup = FakeCgroup()
        pool_, _ = pool(tmp_path, clock=clock, cgroup=cgroup)
        try:
            await pool_.client("echo")
            assert cgroup.calls[0][0] == "mcp-echo"
            assert cgroup.calls[0][1] == 4242
            assert pool_.cgroup_state == {"echo": "bound"}
            assert (await pool_.status())[0]["cgroup"] == "bound"
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_without_root_it_reports_unavailable(self, tmp_path):
        """controller 的 apply_cgroup 会吞掉权限错误 —— 所以读回确认，别谎报成功。"""
        clock = Clock()
        cgroup = FakeCgroup(land=False)
        pool_, _ = pool(tmp_path, clock=clock, cgroup=cgroup)
        try:
            client = await pool_.client("echo")
            assert client.alive is True  # 绑定失败不能拖垮调用
            assert pool_.cgroup_state["echo"].startswith("unavailable")
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_controller_errors_are_recorded(self, tmp_path):
        clock = Clock()
        cgroup = FakeCgroup(explode=True)
        pool_, _ = pool(tmp_path, clock=clock, cgroup=cgroup)
        try:
            await pool_.client("echo")
            assert pool_.cgroup_state["echo"].startswith("error")
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_limits_come_from_the_definition(self, tmp_path):
        clock = Clock()
        cgroup = FakeCgroup()
        pool_, _ = pool(
            tmp_path,
            clock=clock,
            cgroup=cgroup,
            definition={"max_memory_mb": 256, "max_cpu_percent": 25},
        )
        try:
            await pool_.client("echo")
            limits = cgroup.calls[0][2]
            assert limits.max_memory_mb == 256
            assert limits.max_cpu_percent == 25
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_defaults_are_kept_when_nothing_is_set(self, tmp_path):
        from trimum_core.resource_controller import ResourceLimits

        clock = Clock()
        cgroup = FakeCgroup()
        pool_, _ = pool(tmp_path, clock=clock, cgroup=cgroup)
        try:
            await pool_.client("echo")
            assert cgroup.calls[0][2] == ResourceLimits()
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_http_clients_have_no_pid_so_nothing_is_bound(self, tmp_path):
        clock = Clock()
        cgroup = FakeCgroup()
        made: list[FakeClient] = []

        def factory(definition):
            client = FakeClient(definition, pid=None)  # HTTP session: no process
            made.append(client)
            return client

        pool_ = MCPServerPool(
            registry(tmp_path), client_factory=factory, clock=clock, cgroup=cgroup
        )
        try:
            await pool_.client("echo")
            assert cgroup.calls == []
            assert pool_.cgroup_state == {}
        finally:
            await pool_.close_all()

    @pytest.mark.asyncio
    async def test_no_controller_means_no_binding_attempt(self, tmp_path):
        clock = Clock()
        pool_, _ = pool(tmp_path, clock=clock)  # cgroup=None
        try:
            await pool_.client("echo")
            assert pool_.cgroup_state == {}
        finally:
            await pool_.close_all()