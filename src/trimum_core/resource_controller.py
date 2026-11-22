"""Resource controllers and token usage tracking.

This module provides a small abstraction layer for inspecting and limiting
per-agent resource consumption.  Two controller implementations are included:

* :class:`PsutilController` - cross-platform best-effort sampling via psutil.
* :class:`CgroupV2Controller` - Linux cgroup v2 integration.

It also includes :class:`TokenUsageTracker` for LLM token accounting.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

try:
    import psutil
except ImportError:  # pragma: no cover - exercised by optional dependency setup
    psutil = None  # type: ignore[assignment]

log = logging.getLogger("trimum_core.resource_controller")


@dataclass
class ResourceUsage:
    """Snapshot of an agent's current resource consumption."""

    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    io_read_bytes: int = 0
    io_write_bytes: int = 0
    file_writes_1m: int = 0
    network_requests_1m: int = 0


@dataclass
class ResourceLimits:
    """Resource limits that an agent is allowed to consume.

    ``max_cpu_percent`` is expressed as a percentage of **one CPU core**:
    ``100`` means one full core (``cpu.max = 100000 100000``), ``250`` means
    2.5 cores.  A non-positive value means *no CPU quota* and is written as
    ``max 100000``.  ``max_memory_mb`` follows the same sentinel convention:
    a non-positive value means *no memory limit* (``memory.max = max``).
    """

    max_cpu_percent: float = 80.0
    max_memory_mb: float = 512.0
    max_file_writes_per_minute: int = 60
    max_network_requests_per_minute: int = 30


@dataclass
class Violation:
    """A single resource limit violation."""

    resource: str
    limit: float
    actual: float
    message: str


@dataclass
class ResourceCheckResult:
    """Result of a resource limit check."""

    allowed: bool = True
    violations: list[Violation] = field(default_factory=list)


@dataclass(frozen=True)
class CgroupApplyResult:
    """Outcome of trying to place a PID under a cgroup.

    ``verified is True`` means the PID was read back from ``cgroup.procs``.
    ``limits_verified is True`` means ``cpu.max`` and ``memory.max`` were read
    back and matched the requested values.  ``None`` means the controller
    could not verify that dimension (for example, non-cgroup platforms);
    callers enforcing a *hard* limit must treat ``None`` as failure.
    """

    applied: bool
    verified: bool | None = None
    detail: str = ""
    limits_verified: bool | None = None

    @property
    def enforced(self) -> bool:
        return (
            self.applied
            and self.verified is True
            and self.limits_verified is True
        )

    @property
    def prepared(self) -> bool:
        """Limits are written **and** read back; no PID has to be attached yet."""

        return self.applied and self.limits_verified is True


@dataclass
class TokenUsage:
    """Token usage for one or more LLM calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0


class _SlidingWindowCounter:
    """Minute-scale in-memory sliding window event counter."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def record(self, agent_id: str, count: int = 1) -> None:
        now = time.time()
        events = self._events[agent_id]
        for _ in range(max(0, count)):
            events.append(now)
        self._prune(agent_id, now)

    def count(self, agent_id: str) -> int:
        now = time.time()
        self._prune(agent_id, now)
        return len(self._events.get(agent_id, ()))

    def _prune(self, agent_id: str, now: float) -> None:
        cutoff = now - self.window_seconds
        events = self._events.get(agent_id)
        if not events:
            return
        while events and events[0] < cutoff:
            events.popleft()


def _build_check_result(
    usage: ResourceUsage,
    limits: ResourceLimits,
) -> ResourceCheckResult:
    """Compare a usage snapshot against limits and collect violations."""

    violations: list[Violation] = []

    # Non-positive CPU/memory limits mean "unlimited" (see ResourceLimits).
    if limits.max_cpu_percent > 0 and usage.cpu_percent > limits.max_cpu_percent:
        violations.append(
            Violation(
                resource="cpu_percent",
                limit=float(limits.max_cpu_percent),
                actual=float(usage.cpu_percent),
                message=(
                    f"CPU usage {usage.cpu_percent:.2f}% exceeds "
                    f"limit {limits.max_cpu_percent:.2f}%"
                ),
            )
        )

    if limits.max_memory_mb > 0 and usage.memory_mb > limits.max_memory_mb:
        violations.append(
            Violation(
                resource="memory_mb",
                limit=float(limits.max_memory_mb),
                actual=float(usage.memory_mb),
                message=(
                    f"Memory usage {usage.memory_mb:.2f} MB exceeds "
                    f"limit {limits.max_memory_mb:.2f} MB"
                ),
            )
        )

    if usage.file_writes_1m > limits.max_file_writes_per_minute:
        violations.append(
            Violation(
                resource="file_writes_1m",
                limit=float(limits.max_file_writes_per_minute),
                actual=float(usage.file_writes_1m),
                message=(
                    f"File write rate {usage.file_writes_1m} writes/min exceeds "
                    f"limit {limits.max_file_writes_per_minute} writes/min"
                ),
            )
        )

    if usage.network_requests_1m > limits.max_network_requests_per_minute:
        violations.append(
            Violation(
                resource="network_requests_1m",
                limit=float(limits.max_network_requests_per_minute),
                actual=float(usage.network_requests_1m),
                message=(
                    f"Network request rate {usage.network_requests_1m} "
                    f"requests/min exceeds limit "
                    f"{limits.max_network_requests_per_minute} requests/min"
                ),
            )
        )

    return ResourceCheckResult(allowed=not violations, violations=violations)


class ResourceController(ABC):
    """Abstract interface for resource inspection and enforcement."""

    @abstractmethod
    async def get_usage(self, agent_id: str) -> ResourceUsage:
        """Return the current resource usage snapshot for an agent."""

    @abstractmethod
    async def check_limits(
        self,
        agent_id: str,
        usage: ResourceUsage | None = None,
    ) -> ResourceCheckResult:
        """Check whether an agent exceeds its resource limits."""

    @abstractmethod
    async def set_limits(
        self,
        agent_id: str,
        limits: ResourceLimits,
    ) -> None:
        """Set per-agent resource limits."""

    @abstractmethod
    async def get_limits(self, agent_id: str) -> ResourceLimits:
        """Return the effective limits for an agent."""

    @abstractmethod
    async def apply_cgroup(
        self,
        agent_id: str,
        pid: int,
        limits: ResourceLimits,
    ) -> "CgroupApplyResult | None":
        """Apply cgroup v2 constraints to a process."""

    async def prepare_cgroup(
        self,
        agent_id: str,
        limits: ResourceLimits,
    ) -> CgroupApplyResult:
        """Create/configure the agent cgroup **before** a process exists.

        A hard-enforcement spawn must call this first and refuse to start the
        child unless the returned result is :attr:`CgroupApplyResult.enforced`.
        The default implementation reports "unsupported" so callers fail closed
        instead of silently spawning outside the resource boundary.
        """

        return CgroupApplyResult(
            applied=False,
            verified=False,
            limits_verified=False,
            detail="controller does not support pre-spawn cgroup preparation",
        )

    def preexec_hook(self, agent_id: str) -> Callable[[], None] | None:
        """Return a child-side hook that joins the agent cgroup before ``exec``.

        The hook runs in the forked child (``preexec_fn``) and must be invoked
        before Landlock/seccomp are applied.  Returning ``None`` means the
        controller cannot close the post-spawn race.
        """

        return None

    async def kill_cgroup(self, agent_id: str) -> bool:
        """Kill every process in the agent cgroup (best effort)."""

        return False

    async def assigned_pids(self, agent_id: str) -> list[int]:
        """PIDs actually constrained for *agent_id* (empty when unknowable).

        ``apply_cgroup`` is deliberately silent about a failure it cannot fix
        (no permission on ``/sys/fs/cgroup``), so callers that need to *report*
        the state — ``trm mcp status`` for one — read it back from here instead
        of assuming the call succeeded.
        """
        return []


class PsutilController(ResourceController):
    """Best-effort resource controller backed by psutil.

    CPU and memory are sampled from ``psutil.Process()``.  File-write and
    network-request rates are tracked with in-memory one-minute sliding
    windows.  When psutil is unavailable, usage falls back to empty data.
    """

    def __init__(self) -> None:
        self._limits: dict[str, ResourceLimits] = {}
        self._default_limits = ResourceLimits()
        self._file_writes = _SlidingWindowCounter(window_seconds=60.0)
        self._network_requests = _SlidingWindowCounter(window_seconds=60.0)

    async def get_usage(self, agent_id: str) -> ResourceUsage:
        usage = ResourceUsage(
            file_writes_1m=self._file_writes.count(agent_id),
            network_requests_1m=self._network_requests.count(agent_id),
        )

        if psutil is None:
            return usage

        try:
            proc = psutil.Process()
        except Exception:
            return usage

        try:
            usage.cpu_percent = float(proc.cpu_percent())
        except Exception:
            pass

        try:
            usage.memory_mb = float(proc.memory_info().rss) / (1024 * 1024)
        except Exception:
            pass

        try:
            counters = proc.io_counters()
            usage.io_read_bytes = int(counters.read_bytes)
            usage.io_write_bytes = int(counters.write_bytes)
        except Exception:
            pass

        return usage

    async def check_limits(
        self,
        agent_id: str,
        usage: ResourceUsage | None = None,
    ) -> ResourceCheckResult:
        if usage is None:
            usage = await self.get_usage(agent_id)
        limits = await self.get_limits(agent_id)
        return _build_check_result(usage, limits)

    async def set_limits(
        self,
        agent_id: str,
        limits: ResourceLimits,
    ) -> None:
        self._limits[agent_id] = replace(limits)

    async def get_limits(self, agent_id: str) -> ResourceLimits:
        limits = self._limits.get(agent_id, self._default_limits)
        return replace(limits)

    async def apply_cgroup(
        self,
        agent_id: str,
        pid: int,
        limits: ResourceLimits,
    ) -> CgroupApplyResult:
        log.warning("platform not supported")
        return CgroupApplyResult(
            applied=False,
            verified=False,
            limits_verified=False,
            detail="cgroup v2 is not supported on this platform",
        )

    async def assigned_pids(self, agent_id: str) -> list[int]:
        """This controller has no cgroup, so it can never report assignments."""

        return []

    def record_file_write(self, agent_id: str, count: int = 1) -> None:
        """Record file-write events for the one-minute sliding window."""

        self._file_writes.record(agent_id, count)

    def record_network_request(self, agent_id: str, count: int = 1) -> None:
        """Record network requests for the one-minute sliding window."""

        self._network_requests.record(agent_id, count)


def _parse_cpu_max(value: str) -> float | None:
    """Parse a cgroup v2 ``cpu.max`` value into a percentage of one core.

    ``max 100000`` means *no quota* and maps to the ``0`` sentinel used by
    :class:`ResourceLimits`; it must not be confused with ``100%``.
    """

    parts = value.strip().split()
    if not parts:
        return None
    if parts[0] == "max":
        return 0.0

    try:
        quota = int(parts[0])
        period = int(parts[1]) if len(parts) > 1 else 100000
    except ValueError:
        return None

    if period <= 0 or quota < 0:
        return None
    if quota == 0:
        return 0.0
    return round(quota / period * 100.0, 2)


def _parse_memory_max(value: str) -> float | None:
    """Parse a cgroup v2 ``memory.max`` value into megabytes.

    ``max`` means *no memory limit* and maps to the ``0`` sentinel; an empty or
    malformed value stays ``None`` so callers can distinguish "unlimited" from
    "could not read".
    """

    value = value.strip()
    if not value:
        return None
    if value == "max":
        return 0.0
    try:
        return int(value) / (1024 * 1024)
    except ValueError:
        return None


def _format_cpu_max(max_cpu_percent: float) -> str:
    """Format a CPU percentage as a cgroup v2 ``cpu.max`` quota/period.

    Percentages are relative to **one core**: ``100`` becomes
    ``100000 100000`` (one full core) and ``250`` becomes ``250000 100000``
    (2.5 cores).  A non-positive percentage is the explicit "unlimited"
    sentinel and becomes ``max 100000``.
    """

    if max_cpu_percent <= 0:
        return "max 100000"
    period = 100000
    quota = max(1, int(round(max_cpu_percent / 100.0 * period)))
    return f"{quota} {period}"


def _format_memory_max(max_memory_mb: float) -> str:
    """Format a megabyte limit for ``memory.max`` (non-positive = unlimited)."""

    if max_memory_mb <= 0:
        return "max"
    return str(int(max_memory_mb * 1024 * 1024))


def make_cgroup_preexec_hook(path: str | Path) -> Callable[[], None]:
    """Build a child-side hook that writes its own PID to ``cgroup.procs``.

    The hook is intentionally syscall-only (``os.open``/``os.write``) so it is
    safe to run between ``fork`` and ``exec``.  It must be composed **before**
    the Landlock/seccomp hook: once those are applied the child may no longer
    be able to write the cgroup file.
    """

    target = str(path)

    def _hook() -> None:  # pragma: no cover - runs in the forked child
        fd = os.open(target, os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        finally:
            os.close(fd)

    return _hook


def _parse_io_stat(value: str) -> tuple[int, int]:
    """Sum ``rbytes`` / ``wbytes`` from a cgroup v2 ``io.stat`` file.

    Real format is one device per line, with the device number as the first
    field::

        8:0 rbytes=90430464 wbytes=299008000 rios=123 wios=456
        8:16 rbytes=1024 wbytes=2048

    The previous implementation treated the first field as a key, so it never
    matched ``rbytes``/``wbytes``.  Sum across devices because
    :class:`ResourceUsage` has one aggregate byte counter pair.
    """

    read_bytes = 0
    write_bytes = 0
    for line in value.splitlines():
        for field_value in line.split():
            key, sep, raw = field_value.partition("=")
            if not sep:
                continue
            try:
                number = int(raw)
            except ValueError:
                continue
            if key == "rbytes":
                read_bytes += number
            elif key == "wbytes":
                write_bytes += number
    return read_bytes, write_bytes


class CgroupV2Controller(ResourceController):
    """Linux cgroup v2 controller.

    The controller reads actual usage and configured limits from the cgroup
    filesystem and degrades silently to defaults when files are unavailable.
    """

    def __init__(self, cgroup_root: str | Path = "/sys/fs/cgroup") -> None:
        self._cgroup_root = Path(cgroup_root)
        self._trimum_root = self._cgroup_root / "trimum"
        self._limits: dict[str, ResourceLimits] = {}
        self._file_writes = _SlidingWindowCounter(window_seconds=60.0)
        self._network_requests = _SlidingWindowCounter(window_seconds=60.0)
        self._last_cpu: dict[str, tuple[float, int]] = {}

    def _agent_dir(self, agent_id: str) -> Path:
        return self._trimum_root / agent_id

    def _read_text(self, agent_id: str, filename: str) -> str | None:
        try:
            return (
                (self._agent_dir(agent_id) / filename)
                .read_text(encoding="utf-8")
                .strip()
            )
        except (OSError, ValueError):
            return None

    async def get_usage(self, agent_id: str) -> ResourceUsage:
        usage = ResourceUsage(
            file_writes_1m=self._file_writes.count(agent_id),
            network_requests_1m=self._network_requests.count(agent_id),
        )

        memory_current = self._read_text(agent_id, "memory.current")
        if memory_current is not None:
            try:
                usage.memory_mb = int(memory_current) / (1024 * 1024)
            except ValueError:
                pass

        cpu_stat = self._read_text(agent_id, "cpu.stat")
        if cpu_stat is not None:
            usage.cpu_percent = self._cpu_percent_from_stat(agent_id, cpu_stat)

        io_stat = self._read_text(agent_id, "io.stat")
        if io_stat is not None:
            usage.io_read_bytes, usage.io_write_bytes = _parse_io_stat(io_stat)

        return usage

    def _cpu_percent_from_stat(self, agent_id: str, cpu_stat: str) -> float:
        usage_usec: int | None = None
        for line in cpu_stat.splitlines():
            key, _, value = line.partition(" ")
            if key == "usage_usec":
                try:
                    usage_usec = int(value)
                except ValueError:
                    return 0.0
                break

        if usage_usec is None:
            return 0.0

        now = time.time()
        previous = self._last_cpu.get(agent_id)
        self._last_cpu[agent_id] = (now, usage_usec)

        if previous is None:
            return 0.0

        previous_time, previous_usec = previous
        elapsed = now - previous_time
        if elapsed <= 0:
            return 0.0

        delta = max(0, usage_usec - previous_usec)
        return round(delta / (elapsed * 1_000_000) * 100.0, 2)

    async def check_limits(
        self,
        agent_id: str,
        usage: ResourceUsage | None = None,
    ) -> ResourceCheckResult:
        if usage is None:
            usage = await self.get_usage(agent_id)
        limits = await self.get_limits(agent_id)
        return _build_check_result(usage, limits)

    async def set_limits(
        self,
        agent_id: str,
        limits: ResourceLimits,
    ) -> None:
        self._limits[agent_id] = replace(limits)

    async def get_limits(self, agent_id: str) -> ResourceLimits:
        stored = self._limits.get(agent_id)
        limits = replace(stored) if stored is not None else ResourceLimits()

        cpu_max = self._read_text(agent_id, "cpu.max")
        if cpu_max is not None:
            cpu_percent = _parse_cpu_max(cpu_max)
            if cpu_percent is not None:
                limits.max_cpu_percent = cpu_percent

        memory_max = self._read_text(agent_id, "memory.max")
        if memory_max is not None:
            memory_mb = _parse_memory_max(memory_max)
            if memory_mb is not None:
                limits.max_memory_mb = memory_mb

        return limits

    async def prepare_cgroup(
        self,
        agent_id: str,
        limits: ResourceLimits,
    ) -> CgroupApplyResult:
        """Create the agent cgroup and prove the kernel accepted the limits.

        This runs **before** any agent process exists.  A hard-enforcement
        caller must refuse to spawn unless :attr:`CgroupApplyResult.prepared`
        is true; reading ``cgroup.procs`` alone only proves membership, not
        that ``cpu.max`` / ``memory.max`` match the request.
        """

        expected_cpu = _format_cpu_max(limits.max_cpu_percent)
        expected_memory = _format_memory_max(limits.max_memory_mb)
        try:
            agent_dir = self._agent_dir(agent_id)
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "cpu.max").write_text(expected_cpu, encoding="utf-8")
            (agent_dir / "memory.max").write_text(expected_memory, encoding="utf-8")
        except (OSError, ValueError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            log.warning("prepare_cgroup failed for %s", agent_id, exc_info=True)
            return CgroupApplyResult(
                applied=False,
                verified=False,
                limits_verified=False,
                detail=detail,
            )

        actual_cpu = self._read_text(agent_id, "cpu.max")
        actual_memory = self._read_text(agent_id, "memory.max")
        mismatches: list[str] = []
        if actual_cpu is None:
            mismatches.append("cpu.max unreadable")
        elif actual_cpu != expected_cpu:
            mismatches.append(f"cpu.max={actual_cpu!r} expected {expected_cpu!r}")
        if actual_memory is None:
            mismatches.append("memory.max unreadable")
        elif actual_memory != expected_memory:
            mismatches.append(
                f"memory.max={actual_memory!r} expected {expected_memory!r}"
            )
        if mismatches:
            return CgroupApplyResult(
                applied=True,
                verified=None,
                limits_verified=False,
                detail="limit readback mismatch: " + "; ".join(mismatches),
            )
        return CgroupApplyResult(
            applied=True,
            verified=None,
            limits_verified=True,
            detail=(
                f"limits verified (cpu.max={actual_cpu!r}, "
                f"memory.max={actual_memory!r})"
            ),
        )

    def preexec_hook(self, agent_id: str) -> Callable[[], None]:
        """Join this agent's cgroup before the child calls ``exec``."""

        return make_cgroup_preexec_hook(self._agent_dir(agent_id) / "cgroup.procs")

    async def apply_cgroup(
        self,
        agent_id: str,
        pid: int,
        limits: ResourceLimits,
    ) -> CgroupApplyResult:
        prepared = await self.prepare_cgroup(agent_id, limits)
        if not prepared.applied:
            return prepared

        try:
            (self._agent_dir(agent_id) / "cgroup.procs").write_text(
                str(int(pid)),
                encoding="utf-8",
            )
        except (OSError, ValueError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            log.warning("apply_cgroup failed for %s", agent_id, exc_info=True)
            return CgroupApplyResult(
                applied=False,
                verified=False,
                limits_verified=prepared.limits_verified,
                detail=detail,
            )

        pids = await self.assigned_pids(agent_id)
        if not pids:
            return CgroupApplyResult(
                applied=True,
                verified=None,
                limits_verified=prepared.limits_verified,
                detail=prepared.detail + "; cgroup.procs is empty or unreadable",
            )
        if pid in pids:
            return CgroupApplyResult(
                applied=True,
                verified=True,
                limits_verified=prepared.limits_verified,
                detail=prepared.detail + "; pid listed",
            )
        return CgroupApplyResult(
            applied=True,
            verified=False,
            limits_verified=prepared.limits_verified,
            detail=prepared.detail + "; pid is not listed in cgroup.procs",
        )

    async def kill_cgroup(self, agent_id: str) -> bool:
        """Kill the whole agent cgroup, including grandchildren.

        ``cgroup.kill`` is the preferred path (kernel >= 5.14).  If it is not
        available, fall back to SIGKILL for every PID currently listed in the
        cgroup, then let the caller's process-tree cleanup cover the rest.
        """

        agent_dir = self._agent_dir(agent_id)
        try:
            (agent_dir / "cgroup.kill").write_text("1", encoding="utf-8")
            return True
        except (OSError, ValueError):
            pass

        killed = False
        for pid in await self.assigned_pids(agent_id):
            try:
                os.kill(pid, signal.SIGKILL)
                killed = True
            except (OSError, ValueError):
                continue
        return killed

    async def assigned_pids(self, agent_id: str) -> list[int]:
        """PIDs listed in the agent's ``cgroup.procs`` (empty when unreadable)."""
        text = self._read_text(agent_id, "cgroup.procs")
        if not text:
            return []
        pids: list[int] = []
        for line in text.splitlines():
            try:
                pids.append(int(line.strip()))
            except ValueError:
                continue
        return pids

    def record_file_write(self, agent_id: str, count: int = 1) -> None:
        """Record file-write events for the one-minute sliding window."""

        self._file_writes.record(agent_id, count)

    def record_network_request(self, agent_id: str, count: int = 1) -> None:
        """Record network requests for the one-minute sliding window."""

        self._network_requests.record(agent_id, count)


class TokenUsageTracker:
    """Track per-agent token usage over sliding time windows."""

    def __init__(self, window_minutes: int = 5) -> None:
        self.window_minutes = max(0, int(window_minutes))
        self._per_agent: dict[str, list[TokenUsage]] = {}
        self._timestamps: dict[str, list[float]] = {}

    def record(self, agent_id: str, usage: TokenUsage) -> None:
        """Record one token-usage snapshot for an agent call."""

        self._per_agent.setdefault(agent_id, []).append(usage)
        self._timestamps.setdefault(agent_id, []).append(time.time())
        self._cleanup_agent(agent_id)

    def get_usage(self, agent_id: str) -> TokenUsage:
        """Return the summed usage inside the configured tracking window."""

        result = TokenUsage()
        for _, usage in self._entries_in_window(agent_id, self.window_minutes):
            result.prompt_tokens += usage.prompt_tokens
            result.completion_tokens += usage.completion_tokens
            result.total_tokens += usage.total_tokens or (
                usage.prompt_tokens + usage.completion_tokens
            )
            result.calls += usage.calls or 1
        return result

    def get_all_usage(self) -> dict[str, TokenUsage]:
        """Return summed usage for every tracked agent."""

        return {agent_id: self.get_usage(agent_id) for agent_id in self._per_agent}

    def get_history(
        self,
        agent_id: str,
        minutes: int = 30,
    ) -> list[TokenUsage]:
        """Return raw usage snapshots from the requested history window."""

        return [
            usage
            for _, usage in self._entries_in_window(agent_id, max(0, int(minutes)))
        ]

    def get_resource_usage_str(self, agent_id: str) -> str:
        """Return a compact human-readable usage summary."""

        usage = self.get_usage(agent_id)
        return (
            f"{agent_id}: {usage.prompt_tokens} prompt tokens, "
            f"{usage.completion_tokens} completion tokens, "
            f"{usage.total_tokens} total tokens, "
            f"{usage.calls} calls in last {self.window_minutes} min"
        )

    def _entries_in_window(
        self,
        agent_id: str,
        minutes: int,
    ) -> list[tuple[float, TokenUsage]]:
        cutoff = time.time() - minutes * 60
        usages = self._per_agent.get(agent_id, [])
        timestamps = self._timestamps.get(agent_id, [])
        return [
            (timestamp, usage)
            for timestamp, usage in zip(timestamps, usages)
            if timestamp >= cutoff
        ]

    def _cleanup_agent(self, agent_id: str) -> None:
        retention_minutes = max(self.window_minutes, 30)
        cutoff = time.time() - retention_minutes * 60

        usages = self._per_agent.get(agent_id)
        timestamps = self._timestamps.get(agent_id)
        if not usages or not timestamps:
            return

        kept_usages: list[TokenUsage] = []
        kept_timestamps: list[float] = []
        for timestamp, usage in zip(timestamps, usages):
            if timestamp >= cutoff:
                kept_usages.append(usage)
                kept_timestamps.append(timestamp)

        if kept_usages:
            self._per_agent[agent_id] = kept_usages
            self._timestamps[agent_id] = kept_timestamps
        else:
            self._per_agent.pop(agent_id, None)
            self._timestamps.pop(agent_id, None)


def resource_limits_from_config(config: dict[str, Any] | None) -> ResourceLimits:
    """Build :class:`ResourceLimits` from a ``resource_limits`` mapping.

    Accepted keys mirror :class:`ResourceLimits` fields.  Unknown keys are
    ignored and missing keys fall back to the dataclass defaults.
    """

    mapping: dict[str, Any] = {}
    if config:
        nested = config.get("resource_limits")
        if isinstance(nested, dict):
            mapping.update(nested)
        # Top-level keys are also accepted so callers can pass ``SpawnRequest.config``
        # directly without wrapping them in a nested ``resource_limits`` dict.
        for key in (
            "max_cpu_percent",
            "max_memory_mb",
            "max_file_writes_per_minute",
            "max_network_requests_per_minute",
        ):
            if key in config:
                mapping[key] = config[key]

    def _number(value: Any, default: float | int) -> float | int:
        if value is None or isinstance(value, bool):
            return default
        try:
            return type(default)(value)
        except (TypeError, ValueError):
            return default

    return ResourceLimits(
        max_cpu_percent=_number(mapping.get("max_cpu_percent"), ResourceLimits().max_cpu_percent),
        max_memory_mb=_number(mapping.get("max_memory_mb"), ResourceLimits().max_memory_mb),
        max_file_writes_per_minute=_number(
            mapping.get("max_file_writes_per_minute"),
            ResourceLimits().max_file_writes_per_minute,
        ),
        max_network_requests_per_minute=_number(
            mapping.get("max_network_requests_per_minute"),
            ResourceLimits().max_network_requests_per_minute,
        ),
    )


def _normalize_enforcement(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    if lowered in {"hard", "strict", "required", "fail-closed", "fail_closed"}:
        return "hard"
    if lowered in {"soft", "best-effort", "best_effort", "warn"}:
        return "soft"
    return None


def default_resource_enforcement() -> str:
    """Global fallback for spawns that do not specify a policy.

    Resolution order follows the project-wide rule: environment >
    ``agent_manager.resource_enforcement`` > ``soft``.  Missing/broken config
    silently falls back; a resource policy must never prevent the daemon from
    starting.
    """

    env_value = _normalize_enforcement(os.environ.get("TRIMUM_RESOURCE_ENFORCEMENT"))
    if env_value is not None:
        return env_value
    try:
        from .config import Config

        config_value = _normalize_enforcement(
            Config().get("agent_manager.resource_enforcement")
        )
    except Exception:
        return "soft"
    return config_value or "soft"


def resource_enforcement_from_config(
    config: dict[str, Any] | None,
    *,
    default: str | None = None,
) -> str:
    """Return ``hard`` or ``soft`` for an agent spawn request.

    ``hard`` means resource constraints are a precondition: if the cgroup
    cannot be applied and verified, the agent must not keep running.  ``soft``
    preserves the historical best-effort behaviour and reports degradation in
    the spawn result.  Missing/invalid values fall back to ``soft``.
    """

    fallback = _normalize_enforcement(default) or "soft"
    if not isinstance(config, dict):
        return fallback

    raw: Any = config.get("resource_enforcement")
    nested = config.get("resource_limits")
    if raw is None and isinstance(nested, dict):
        raw = nested.get("enforcement")
    return _normalize_enforcement(raw) or fallback


def create_resource_controller() -> ResourceController:
    """Return the best available resource controller for this platform.

    Linux uses cgroup v2 integration; other platforms degrade to the
    cross-platform :class:`PsutilController`.
    """

    if sys.platform.startswith("linux"):
        return CgroupV2Controller()
    return PsutilController()


__all__ = [
    "CgroupApplyResult",
    "CgroupV2Controller",
    "PsutilController",
    "ResourceCheckResult",
    "ResourceController",
    "ResourceLimits",
    "ResourceUsage",
    "TokenUsage",
    "TokenUsageTracker",
    "Violation",
    "create_resource_controller",
    "default_resource_enforcement",
    "resource_enforcement_from_config",
    "resource_limits_from_config",
]
