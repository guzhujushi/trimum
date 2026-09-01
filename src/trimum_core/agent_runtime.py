"""Agent Runtime — sub-agent process lifecycle manager.

职责：
- 只负责子 Agent 进程的开/关信号
- 不参与业务逻辑，不决定"做什么"
- 通过 Unix Socket 与子 Agent 通信（start/stop）
- 通过 Event Bus 广播状态变更
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .agent_socket import (
    AgentSocketServer,
    AgentSocketClient,
    SocketMessage,
    MSG_START,
    MSG_STOP,
    MSG_STATUS,
)
from .event_bus import EventBus, AGENT_STATUS_CHANGED
from .models import EventSeverity

log = logging.getLogger("trimum_core.agent_runtime")


class AgentRuntime:
    """Manages sub-agent process lifecycle.

    - start_agent(agent_id, config): starts sub-agent process + Socket channel
    - stop_agent(agent_id): sends stop signal via Socket, cleans up
    - Publishes status changes to Event Bus
    - Listens on Event Bus for signals from Workflow Engine
    """

    def __init__(
        self,
        socket_path: str,
        event_bus: EventBus,
        max_agents: int = 10,
    ) -> None:
        self._socket_server = AgentSocketServer(socket_path)
        self._event_bus = event_bus
        self._max_agents = max_agents
        self._agents: dict[str, asyncio.subprocess.Process] = {}
        self._stopped = False
        self._event_task: Optional[asyncio.Task] = None

        # Register socket handlers
        self._socket_server.register_handler(MSG_STATUS, self._handle_status)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the socket server and begin listening for events."""
        await self._socket_server.start()
        # Subscribe to Event Bus for start/stop signals from Workflow Engine
        self._event_task = asyncio.create_task(self._event_loop())
        log.info("AgentRuntime started")

    async def stop(self) -> None:
        """Stop all agents and clean up."""
        self._stopped = True
        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass
        # Stop all managed agents
        for agent_id in list(self._agents.keys()):
            await self.stop_agent(agent_id)
        await self._socket_server.stop()
        log.info("AgentRuntime stopped")

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    async def start_agent(
        self,
        agent_id: str,
        agent_type: str,
        config: dict | None = None,
    ) -> bool:
        """Start a sub-agent process and open Socket channel.

        Sub-agent script location: ~/.local/share/trimum/agents/{type}/main.py

        Returns True if started successfully.
        """
        if len(self._agents) >= self._max_agents:
            log.warning("Max agents reached (%d)", self._max_agents)
            return False

        if agent_id in self._agents:
            log.warning("Agent %s already running", agent_id)
            return False

        # Stub: sub-agent script will be implemented in Phase 3 Agent SDK
        # script = Path.home() / ".local/share/trimum/agents" / agent_type / "main.py"
        # process = await asyncio.create_subprocess_exec(
        #     sys.executable, str(script),
        #     stdout=asyncio.subprocess.PIPE,
        #     stderr=asyncio.subprocess.PIPE,
        # )

        # For now: record without actually spawning (Phase 3 stub)
        self._agents[agent_id] = None  # placeholder for Process ref

        # Publish status to Event Bus
        await self._event_bus.emit_event(
            event_type=AGENT_STATUS_CHANGED,
            source="agent_runtime",
            payload={
                "agent_id": agent_id,
                "status": "started",
                "config": config or {},
            },
        )
        log.info("Agent %s started (type=%s)", agent_id, agent_type)
        return True

    async def stop_agent(self, agent_id: str) -> bool:
        """Stop a sub-agent process.

        Sends stop signal via Socket, waits for clean shutdown.
        """
        if agent_id not in self._agents:
            log.warning("Agent %s not found", agent_id)
            return False

        # TODO Phase 3: send stop via Socket, wait for shutdown
        del self._agents[agent_id]

        # Publish status to Event Bus
        await self._event_bus.emit_event(
            event_type=AGENT_STATUS_CHANGED,
            source="agent_runtime",
            payload={
                "agent_id": agent_id,
                "status": "stopped",
            },
        )
        log.info("Agent %s stopped", agent_id)
        return True

    async def get_status(self, agent_id: str) -> str | None:
        """Get current status of an agent."""
        if agent_id in self._agents:
            return "running"
        return None

    def list_agents(self) -> list[str]:
        """List all managed agent IDs."""
        return list(self._agents.keys())

    # ------------------------------------------------------------------
    # Socket message handlers
    # ------------------------------------------------------------------

    async def _handle_status(self, message: SocketMessage) -> None:
        """Handle status update from a sub-agent."""
        status = message.payload.get("status", "unknown")
        await self._event_bus.emit_event(
            event_type=AGENT_STATUS_CHANGED,
            source=f"agent:{message.agent_id}",
            payload={
                "agent_id": message.agent_id,
                "status": status,
                "detail": message.payload,
            },
        )

    # ------------------------------------------------------------------
    # Event Bus loop
    # ------------------------------------------------------------------

    async def _event_loop(self) -> None:
        """Listen on Event Bus for start/stop signals from Workflow Engine."""
        # Stub: in Phase 3 this will subscribe to task.assigned events
        # and route them to the appropriate agent via Socket.
        while not self._stopped:
            await asyncio.sleep(1)
