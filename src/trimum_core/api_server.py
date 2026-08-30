"""FastAPI API Server for trimum Core."""

from __future__ import annotations

import json
import os
import socket as stdlib_socket
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .models import (
    ExecuteRequest,
    ExecuteResponse,
    SpawnRequest,
    SpawnResponse,
    AgentInfo,
    SystemEvent,
    ContextEntry,
)
from .tool_gateway import ToolGateway
from .policy_engine import PolicyEngine
from .event_bus import EventBus
from .context_manager import ContextManager
from .agent_manager import AgentManager
from .config import Config, ensure_dirs
from .logger import setup_logging, get_logger

logger = get_logger("api_server")


class AppState:
    """Shared state for the FastAPI app."""

    def __init__(self, config: Config):
        self.config = config
        self.policy = PolicyEngine(Path(config.policy_path))
        self.tool_gateway = ToolGateway(self.policy)
        self.event_bus = EventBus()
        self.agent_manager = AgentManager(
            max_agents=config.max_agents,
            health_check_interval=config.health_check_interval,
        )
        self.context: Optional[ContextManager] = None
        self.socket_server: Optional[stdlib_socket.socket] = None


def create_app(config: Config) -> FastAPI:
    """Create and configure the FastAPI application."""
    state = AppState(config)

    app = FastAPI(
        title="trimum Core",
        version="0.2.0",
        description="trimum AI Runtime - system-level agent execution engine",
    )

    # Store state
    app.state.trimum = state

    # ─── Routes ────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok", "version": "0.2.0"}

    @app.post("/api/execute", response_model=ExecuteResponse)
    async def execute(request: ExecuteRequest):
        """Execute a tool command via Tool Gateway."""
        response = await state.tool_gateway.execute(request)
        # Publish event
        state.event_bus.publish(
            SystemEvent(
                event_type="tool.executed",
                source=request.agent_id or "api",
                severity="info",
                payload={
                    "tool": request.tool.value,
                    "command": " ".join(request.args),
                    "status": response.status,
                    "risk": response.risk.value,
                    "execution_id": response.execution_id,
                },
            )
        )
        return response

    @app.post("/api/execute/check")
    async def execute_check(request: ExecuteRequest):
        """Check command risk without executing."""
        if not request.args:
            raise HTTPException(status_code=400, detail="No command provided")
        cmd_str = " ".join(request.args)
        risk, action, reason = state.policy.evaluate(cmd_str)
        return {"command": cmd_str, "risk": risk.value, "action": action.value, "reason": reason}

    @app.get("/api/agents", response_model=list[AgentInfo])
    async def list_agents():
        """List all agents."""
        return await state.agent_manager.list()

    @app.get("/api/agents/{agent_id}", response_model=AgentInfo)
    async def get_agent(agent_id: str):
        """Get a specific agent's info."""
        agent = await state.agent_manager.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        return agent

    @app.post("/api/agents/spawn", response_model=SpawnResponse)
    async def spawn_agent(request: SpawnRequest):
        """Spawn a new agent process."""
        return await state.agent_manager.spawn(request)

    @app.post("/api/agents/{agent_id}/stop")
    async def stop_agent(agent_id: str):
        """Stop an agent."""
        success = await state.agent_manager.stop(agent_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        return {"status": "stopped", "agent_id": agent_id}

    @app.get("/api/events")
    async def get_events(limit: int = 50):
        """Get recent event history."""
        return state.event_bus.get_history(limit=limit)

    @app.get("/api/events/stream")
    async def stream_events():
        """SSE stream of real-time events."""

        async def event_generator():
            queue: asyncio.Queue = asyncio.Queue()
            callback = lambda event: queue.put_nowait(event)

            state.event_bus.subscribe("*", callback)
            try:
                while True:
                    event = await queue.get()
                    data = json.dumps(event.model_dump(), default=str)
                    yield f"data: {data}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                state.event_bus.unsubscribe("*", callback)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/api/context/{agent_id}")
    async def get_context(agent_id: str, namespace: str = "default"):
        """Get all context entries for an agent."""
        if not state.context:
            raise HTTPException(status_code=503, detail="Context manager not initialized")
        entries = await state.context.list_namespace(agent_id, namespace)
        return {"agent_id": agent_id, "namespace": namespace, "entries": entries}

    @app.post("/api/context/{agent_id}")
    async def set_context(agent_id: str, entry: ContextEntry):
        """Set a context entry for an agent."""
        if not state.context:
            raise HTTPException(status_code=503, detail="Context manager not initialized")
        await state.context.set(
            agent_id, entry.key, entry.value,
            namespace=entry.namespace,
            ttl_seconds=entry.ttl_seconds,
        )
        return {"status": "ok"}

    @app.on_event("startup")
    async def startup():
        """Initialize services on startup."""
        import asyncio as _asyncio

        # Ensure directories exist
        ensure_dirs(config)

        # Setup logging
        setup_logging(config)

        # Init context manager
        ctx = ContextManager(config.context_db_path)
        await ctx.initialize()
        state.context = ctx

        # Start health check
        asyncio.create_task(state.agent_manager.start_health_check())

        # Start Unix Socket listener
        socket_path = config.socket_path
        if os.name != "nt":  # Unix only
            try:
                if os.path.exists(socket_path):
                    os.unlink(socket_path)
                sock = stdlib_socket.socket(stdlib_socket.AF_UNIX, stdlib_socket.SOCK_STREAM)
                sock.bind(socket_path)
                sock.listen(1)
                os.chmod(socket_path, 0o700)
                state.socket_server = sock
                logger.info("unix_socket_started", path=socket_path)
            except Exception as e:
                logger.warning("unix_socket_failed", error=str(e))

        logger.info("trimum_core_started", host=config.host, port=config.port)

    @app.on_event("shutdown")
    async def shutdown():
        """Clean up on shutdown."""
        if state.context:
            await state.context.close()
        await state.agent_manager.stop_health_check()
        if state.socket_server:
            state.socket_server.close()
            socket_path = config.socket_path
            if os.path.exists(socket_path):
                os.unlink(socket_path)
        logger.info("trimum_core_stopped")

    return app


def run_core(config: Config | None = None) -> None:
    """Run the trimum Core daemon."""
    import asyncio

    if config is None:
        config = Config()

    app = create_app(config)

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        reload=False,
    )


# Import asyncio at module level for type annotations
import asyncio
