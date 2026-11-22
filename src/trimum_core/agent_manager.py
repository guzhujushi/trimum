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
from typing import Callable, Dict, Optional

import psutil

from .agent_launcher import launch_agent, resolve_agent_script
from .logger import get_logger
from .models import AgentInfo, AgentStatus, SpawnRequest, SpawnResponse
from .resource_controller import (
    CgroupApplyResult,
    ResourceController,
    create_resource_controller,
    default_resource_enforcement,
    resource_enforcement_from_config,
    resource_limits_from_config,
)

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

    def __init__(
        self,
        max_agents: int = 10,
        health_check_interval: int = 30,
        resource_controller: Optional[ResourceController] = None,
        agents_root: Optional[str] = None,
        resource_enforcement: Optional[str] = None,
    ) -> None:
        self._max_agents = max_agents
        self._health_check_interval = health_check_interval
        self._agents_root = agents_root
        self._resource_controller = resource_controller or create_resource_controller()
        self._resource_enforcement = (
            resource_enforcement or default_resource_enforcement()
        )
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

            limits = resource_limits_from_config(request.config)
            enforcement = resource_enforcement_from_config(
                request.config, default=self._resource_enforcement
            )
            try:
                await self._resource_controller.set_limits(agent_id, limits)
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                if enforcement == "hard":
                    log.error(
                        "agent_manager.spawn.resource_policy_not_recorded",
                        agent_id=agent_id,
                        detail=detail,
                    )
                    return SpawnResponse(
                        agent_id=agent_id,
                        status=AgentStatus.FAILED,
                        pid=None,
                        message=(
                            "resource enforcement required but the policy could "
                            f"not be recorded: {detail}"
                        ),
                    )
                log.warning(
                    "agent_manager.spawn.resource_policy_not_recorded",
                    agent_id=agent_id,
                    detail=detail,
                )

            # ── hard：先准备并验证 cgroup，再启动进程 ───────────────────
            # 这一步是安全边界：进程一旦 exec，就可能已经执行代码或派生
            # 子进程。准备失败时 hard 直接拒绝启动，绝不「先跑再追着绑」。
            script = resolve_agent_script(request.agent_type, self._agents_root)
            preexec: Optional[Callable[[], None]] = None
            prepared = False
            prepare_detail = ""
            if script is not None:
                prepare = getattr(self._resource_controller, "prepare_cgroup", None)
                if callable(prepare):
                    try:
                        prep = await prepare(agent_id, limits)
                    except Exception as exc:
                        prep = CgroupApplyResult(
                            applied=False,
                            verified=False,
                            limits_verified=False,
                            detail=f"{type(exc).__name__}: {exc}",
                        )
                    if isinstance(prep, CgroupApplyResult) and prep.prepared:
                        hook_maker = getattr(
                            self._resource_controller, "preexec_hook", None
                        )
                        if callable(hook_maker):
                            preexec = hook_maker(agent_id)
                        if preexec is None:
                            prepare_detail = (
                                "controller cannot provide a pre-exec cgroup hook"
                            )
                        else:
                            prepared = True
                            prepare_detail = prep.detail
                    elif isinstance(prep, CgroupApplyResult):
                        prepare_detail = (
                            prep.detail or "cgroup limits could not be verified"
                        )
                    else:
                        prepare_detail = (
                            "controller returned no cgroup preparation result"
                        )
                else:
                    prepare_detail = (
                        "controller does not support pre-spawn cgroup preparation"
                    )

                if enforcement == "hard" and not prepared:
                    detail = prepare_detail or "cgroup preparation failed"
                    log.error(
                        "agent_manager.spawn.resource_enforcement_not_prepared",
                        agent_id=agent_id,
                        detail=detail,
                    )
                    return SpawnResponse(
                        agent_id=agent_id,
                        status=AgentStatus.FAILED,
                        pid=None,
                        message=(
                            "resource enforcement required but not prepared "
                            f"before launch: {detail}"
                        ),
                    )

            # 真实 spawn：脚本存在才起进程（未安装脚本 → 仅登记，保持旧语义）
            launch = await launch_agent(
                agent_id,
                request.agent_type,
                script=script,
                base=self._agents_root,
                preexec=preexec,
            )
            process = launch.process
            pid = launch.pid
            if launch.script is None:
                info.status = AgentStatus.INITIALIZED
                message = (
                    f"Agent '{agent_id}' registered "
                    f"(no agent script installed for type '{request.agent_type}')"
                )
            elif launch.error is not None:
                info.status = AgentStatus.FAILED
                info.pid = pid
                message = launch.error
            else:
                info.status = AgentStatus.RUNNING
                info.pid = pid
                message = f"Agent '{agent_id}' spawned (pid={pid})"

            record = self._AgentRecord(info=info, process=process)

            enforcement_ok: bool | None = None
            enforcement_detail = prepare_detail
            if pid is not None and info.status == AgentStatus.RUNNING:
                try:
                    # 进程已在 preexec 里入组（若可用）；这里再次写 PID 并读回
                    # cpu.max / memory.max，证明内核实际配置符合请求。
                    result = await self._resource_controller.apply_cgroup(
                        agent_id, pid, limits
                    )
                    if isinstance(result, CgroupApplyResult):
                        enforcement_ok = result.enforced
                        enforcement_detail = result.detail or enforcement_detail
                    elif enforcement == "hard":
                        # 旧 controller 只能证明 PID，不能证明内核限额 → hard 拒绝。
                        enforcement_ok = False
                        enforcement_detail = (
                            "controller only verified PID, not kernel limits"
                        )
                    else:
                        # 兼容只实现旧签名的 controller：读回确认，别假定成功。
                        enforcement_ok = await self._verify_assignment(agent_id, pid)
                        if enforcement_ok is None:
                            enforcement_detail = (
                                enforcement_detail
                                or "cgroup assignment could not be verified"
                            )
                except Exception as exc:
                    enforcement_ok = False
                    enforcement_detail = f"{type(exc).__name__}: {exc}"
                    log.warning(
                        "agent_manager.spawn.resource_limits_failed",
                        agent_id=agent_id,
                        exc_info=True,
                    )

            if (
                pid is not None
                and info.status == AgentStatus.RUNNING
                and enforcement_ok is not True
            ):
                detail = enforcement_detail or "cgroup assignment could not be verified"
                if enforcement == "hard":
                    await self._stop_record(record, timeout=5.0)
                    info.status = AgentStatus.FAILED
                    message = (
                        "resource enforcement required but not verified: " + detail
                    )
                    log.error(
                        "agent_manager.spawn.resource_enforcement_required",
                        agent_id=agent_id,
                        pid=pid,
                        detail=detail,
                    )
                else:
                    message = f"{message} (resource limits degraded: {detail})"
                    log.warning(
                        "agent_manager.spawn.resource_limits_degraded",
                        agent_id=agent_id,
                        pid=pid,
                        detail=detail,
                    )
            elif (
                enforcement == "soft"
                and info.status == AgentStatus.RUNNING
                and not prepared
            ):
                # soft 允许降级，但「限制是在 spawn 之后才施加」必须让调用方看见。
                message = (
                    f"{message} (resource limits applied after spawn; "
                    f"no pre-exec guarantee: {prepare_detail})"
                )

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
            await self._stop_record(record, timeout=timeout)

        log.info("agent_manager.stop.done", agent_id=agent_id)
        return True

    async def _verify_assignment(self, agent_id: str, pid: int) -> bool | None:
        """Read back cgroup membership for controllers with the old signature."""

        reader = getattr(self._resource_controller, "assigned_pids", None)
        if not callable(reader):
            return None
        try:
            pids = await reader(agent_id)
        except Exception:
            return None
        if not pids:
            return None
        return pid in pids

    async def _stop_record(self, record: "AgentManager._AgentRecord", timeout: float) -> None:
        """Terminate one record.  Caller must hold ``self._lock``."""

        info = record.info
        proc = record.process

        if proc is not None and proc.returncode is None:
            log.info(
                "agent_manager.stop.terminating",
                agent_id=info.agent_id,
                pid=info.pid,
            )
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                log.info(
                    "agent_manager.stop.timeout_killing",
                    agent_id=info.agent_id,
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
                agent_id=info.agent_id,
                returncode=proc.returncode,
            )

        # If there's a PID but no asyncio.Process (stub case), try kill via psutil
        if info.pid is not None and (proc is None or proc.returncode is None):
            if psutil.pid_exists(info.pid):
                log.info(
                    "agent_manager.stop.psutil_kill",
                    agent_id=info.agent_id,
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

        # 主进程退出不代表它派生的子进程已经消失。cgroup.kill 能一次清掉
        # 整棵进程树；控制器没有该能力时保留上面的单 PID 兜底语义。
        kill_group = getattr(self._resource_controller, "kill_cgroup", None)
        if callable(kill_group):
            try:
                await kill_group(info.agent_id)
            except Exception:
                log.warning(
                    "agent_manager.stop.cgroup_cleanup_failed",
                    agent_id=info.agent_id,
                    exc_info=True,
                )

        info.status = AgentStatus.STOPPED
        record.process = None

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
