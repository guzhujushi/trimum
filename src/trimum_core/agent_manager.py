"""Agent lifecycle manager for trimum Core.

Manages spawning, stopping, health-checking, and cleanup of Agent processes.
Concrete agent scripts are stubbed for Phase 3; the manager creates AgentInfo
records and manages their lifecycle without actually exec-ing child processes.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import psutil

from .logger import get_logger
from .models import AgentInfo, AgentStatus, SpawnRequest, SpawnResponse

log = get_logger("trimum_core.agent_manager")


def _short_uuid() -> str:
    """Return a short (8-char) hex fragment of a UUID."""
    return uuid.uuid4().hex[:8]


class AgentManager:
    """Manage Agent process lifecycle.

    Uses ``asyncio.create_subprocess_exec`` (stubbed) to launch agent scripts
    located at ``~/.local/share/trimum/agents/{type}/main.py``.

    Thread safety is provided via an ``asyncio.Lock`` protecting the internal
    ``_agents`` dict.
    """

    def __init__(self, max_agents: int = 10, health_check_interval: int = 30) -> None:
        self._max_agents = max_agents
        self._health_check_interval = health_check_interval
        self._agents: Dict[str, "_AgentRecord"] = {}
        self._lock = asyncio.Lock()
        self._health_task: Optional[asyncio.Task[None]] = None
        self._stopped = False
        log.info(
            "agent_manager.initialized",
            max_agents=max_agents,
            health_check_interval=health_check_interval,
        )

    # ------------------------------------------------------------------
    # Internal record
    # ------------------------------------------------------------------

    class _AgentRecord:
        """Internal tracking info for a managed agent."""

        __slots__ = (
            "info",
            "process",
            "started_at",
        )

        def __init__(
            self,
            info: AgentInfo,
            process: Optional[asyncio.subprocess.Process],
        ) -> None:
            self.info = info
            self.process = process
            self.started_at = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def spawn(self, request: SpawnRequest) -> SpawnResponse:
        """Spawn a new Agent.

        Generates an agent_id when not provided (``{type}-{short_uuid}``),
        checks the ``max_agents`` ceiling, creates the ``AgentInfo`` record,
        and attempts to start the agent script.  The actual subprocess spawn
        is a stub — Phase 3 will fill in the concrete ``main.py`` entry-point.
        """
        agent_id = request.agent_id or f"{request.agent_type}-{_short_uuid()}"

        async with self._lock:
            if len(self._agents) >= self._max_agents:
                log.warning(
                    "agent_manager.spawn.limit_reached",
                    max_agents=self._max_agents,
                )
                return SpawnResponse(
                    agent_id=agent_id,
                    status=AgentStatus.FAILED,
                    pid=None,
                    message=f"Agent limit reached ({self._max_agents})",
                )

            if agent_id in self._agents:
                log.warning(
                    "agent_manager.spawn.duplicate_id",
                    agent_id=agent_id,
                )
                return SpawnResponse(
                    agent_id=agent_id,
                    status=AgentStatus.FAILED,
                    pid=None,
                    message=f"Agent '{agent_id}' already exists",
                )

            info = AgentInfo(
                agent_id=agent_id,
                agent_type=request.agent_type,
                status=AgentStatus.INITIALIZED,
                config=request.config,
            )

            # --- Stub spawn logic (Phase 3) ---
            # The real implementation will launch:
            #   script = Path.home() / ".local/share/trimum/agents/{type}/main.py"
            #   process = await asyncio.create_subprocess_exec(
            #       sys.executable, str(script),
            #       stdout=asyncio.subprocess.PIPE,
            #       stderr=asyncio.subprocess.PIPE,
            #   )
            process: Optional[asyncio.subprocess.Process] = None
            pid: Optional[int] = None
            if process is not None:
                pid = process.pid
                info.status = AgentStatus.RUNNING
                info.pid = pid
                message = f"Agent '{agent_id}' spawned (pid={pid})"
            else:
                info.status = AgentStatus.INITIALIZED
                message = f"Agent '{agent_id}' registered (stub — no child spawned)"

            record = self._AgentRecord(info=info, process=process)
            self._agents[agent_id] = record

        log.info(
            "agent_manager.spawn.ok",
            agent_id=agent_id,
            agent_type=request.agent_type,
            pid=pid,
            status=info.status.value,
        )

        return SpawnResponse(
            agent_id=agent_id,
            status=info.status,
            pid=pid,
            message=message,
        )

    async def stop(self, agent_id: str, timeout: float = 5.0) -> bool:
        """Stop an Agent by ``agent_id``.

        1. Send SIGTERM (Windows: ``terminate()`` or ``wm_taskkill`` fallback).
        2. Wait up to *timeout* seconds for graceful exit.
        3. If still alive, SIGKILL (``kill()``).
        4. Update status to ``STOPPED``.
        """
        async with self._lock:
            record = self._agents.get(agent_id)
            if record is None:
                log.warning("agent_manager.stop.not_found", agent_id=agent_id)
                return False

            info = record.info
            proc = record.process

            if proc is not None and proc.returncode is None:
                log.info(
                    "agent_manager.stop.terminating",
                    agent_id=agent_id,
                    pid=info.pid,
                )
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    log.warning(
                        "agent_manager.stop.timeout_killing",
                        agent_id=agent_id,
                        pid=info.pid,
                    )
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    # Process already gone
                    pass
            elif proc is not None:
                log.info(
                    "agent_manager.stop.already_exited",
                    agent_id=agent_id,
                    returncode=proc.returncode,
                )

            # If there's a PID but no asyncio.Process (stub case), try kill via psutil
            if info.pid is not None and (proc is None or proc.returncode is None):
                if psutil.pid_exists(info.pid):
                    log.info(
                        "agent_manager.stop.psutil_kill",
                        agent_id=agent_id,
                        pid=info.pid,
                    )
                    try:
                        p = psutil.Process(info.pid)
                        p.terminate()
                        p.wait(timeout=timeout)
                    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                        try:
                            p.kill()
                        except psutil.NoSuchProcess:
                            pass

            info.status = AgentStatus.STOPPED
            record.process = None

        log.info("agent_manager.stop.done", agent_id=agent_id)
        return True

    async def list(self) -> list[AgentInfo]:
        """Return all managed agents' info."""
        async with self._lock:
            return [self._refresh_uptime(r) for r in self._agents.values()]

    async def get(self, agent_id: str) -> Optional[AgentInfo]:
        """Return info for a single agent, or ``None`` if unknown."""
        async with self._lock:
            record = self._agents.get(agent_id)
            if record is None:
                return None
            return self._refresh_uptime(record)

    async def cleanup(self) -> int:
        """Remove agents whose lifecycle has ended and are older than 5 minutes.

        Statuses considered "completed": ``COMPLETED``, ``FAILED``, ``STOPPED``.
        """
        now = time.time()
        cutoff = now - 300  # 5 minutes
        removed = 0

        async with self._lock:
            stale_ids = [
                aid
                for aid, r in self._agents.items()
                if r.info.status
                in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.STOPPED)
                and r.started_at < cutoff
            ]
            for aid in stale_ids:
                del self._agents[aid]
                removed += 1

        if removed:
            log.info("agent_manager.cleanup.removed", count=removed)
        return removed

    async def start_health_check(self) -> None:
        """Start a periodic health-check background task.

        Calling this when a task is already running is a no-op.
        """
        if self._health_task is not None and not self._health_task.done():
            log.debug("agent_manager.health_check.already_running")
            return
        self._stopped = False
        self._health_task = asyncio.create_task(self._health_loop())
        log.info(
            "agent_manager.health_check.started",
            interval=self._health_check_interval,
        )

    async def stop_health_check(self) -> None:
        """Stop the periodic health-check background task."""
        self._stopped = False  # signal sentinel
        if self._health_task is not None and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None
            log.info("agent_manager.health_check.stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_uptime(self, record: _AgentRecord) -> AgentInfo:
        """Update the ``uptime`` field on the record's info in-place and return it."""
        now = time.time()
        record.info.uptime = now - record.started_at
        return record.info

    async def _health_loop(self) -> None:
        """Background loop that periodically checks all managed agent processes."""
        while not self._stopped:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._check_all_agents()
            except asyncio.CancelledError:
                log.debug("agent_manager.health_loop.cancelled")
                break
            except Exception:
                log.exception("agent_manager.health_loop.error")

    async def _check_all_agents(self) -> None:
        """Check every running agent's process, updating status if dead."""
        async with self._lock:
            for agent_id, record in list(self._agents.items()):
                info = record.info
                if info.status not in (AgentStatus.RUNNING, AgentStatus.INITIALIZED):
                    continue

                pid = info.pid
                alive = False
                if pid is not None:
                    try:
                        alive = psutil.pid_exists(pid) and psutil.Process(
                            pid
                        ).is_running()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        alive = False

                if pid is not None and not alive:
                    log.warning(
                        "agent_manager.health_check.dead",
                        agent_id=agent_id,
                        pid=pid,
                    )
                    info.status = AgentStatus.FAILED
                    record.process = None
                elif pid is None:
                    # Stub agents – nothing to check
                    pass
