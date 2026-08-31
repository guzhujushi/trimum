"""FastAPI API Server for trimum Core."""

from __future__ import annotations

import json
import os
import socket as stdlib_socket
from pathlib import Path
from typing import Optional

import json
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from typing import Any

from .models import (
    ExecuteRequest,
    ExecuteResponse,
    SpawnRequest,
    SpawnResponse,
    AgentInfo,
    SystemEvent,
    ContextEntry,
    ToolType,
)
from .planner_agent import PlannerAgent
from .workflow_engine import NodeDefinition, WorkflowDefinition, WorkflowEngine
from .tool_gateway import ToolGateway
from .policy_engine import PolicyEngine
from .event_bus import EventBus
from .context_manager import ContextManager
from .agent_manager import AgentManager
from .config import Config, ensure_dirs
from .logger import setup_logging, get_logger
from .ipc_handler import IpcHandler

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
        self.ipc: Optional[IpcHandler] = None
        self.workflow_engine: Optional[WorkflowEngine] = None
        self.planner: Optional[PlannerAgent] = None


def _register_ipc_routes(ipc: IpcHandler, state: AppState) -> None:
    """Register all JSON-RPC methods for the IPC handler."""
    router = ipc.router

    @router.register("health")
    async def rpc_health(params: dict) -> dict:
        return {"status": "ok", "version": "0.2.1"}

    @router.register("execute")
    async def rpc_execute(params: dict) -> dict:
        req = ExecuteRequest(**params)
        resp = await state.tool_gateway.execute(req)
        return resp.model_dump()

    @router.register("execute.check")
    async def rpc_check(params: dict) -> dict:
        cmd = " ".join(params.get("args", []))
        risk, action, reason = state.policy.evaluate(cmd)
        return {"command": cmd, "risk": risk.value, "action": action.value, "reason": reason}

    @router.register("agents.list")
    async def rpc_list_agents(params: dict) -> list:
        agents = await state.agent_manager.list()
        return [a.model_dump() for a in agents]

    @router.register("agents.get")
    async def rpc_get_agent(params: dict) -> dict | None:
        agent = await state.agent_manager.get(params["agent_id"])
        return agent.model_dump() if agent else None

    @router.register("agents.spawn")
    async def rpc_spawn_agent(params: dict) -> dict:
        req = SpawnRequest(**params)
        resp = await state.agent_manager.spawn(req)
        return resp.model_dump()

    @router.register("agents.stop")
    async def rpc_stop_agent(params: dict) -> dict:
        ok = await state.agent_manager.stop(params["agent_id"])
        return {"success": ok}

    @router.register("events.history")
    async def rpc_events(params: dict) -> list:
        events = state.event_bus.get_history(limit=params.get("limit", 50))
        return [e.model_dump() for e in events]

    @router.register("context.get")
    async def rpc_get_context(params: dict) -> dict:
        if not state.context:
            return {"error": "context not initialized"}
        entries = await state.context.list_namespace(
            params["agent_id"], params.get("namespace", "default")
        )
        return {"agent_id": params["agent_id"], "entries": entries}

    @router.register("context.set")
    async def rpc_set_context(params: dict) -> dict:
        if not state.context:
            return {"error": "context not initialized"}
        await state.context.set(
            params["agent_id"],
            params["key"],
            params["value"],
            namespace=params.get("namespace", "default"),
            ttl_seconds=params.get("ttl_seconds"),
        )
        return {"status": "ok"}


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

    # ── Workflow Engine ────────────────────────────────────────

    @app.post("/api/workflow/run")
    async def run_workflow(request: WorkflowDefinition):
        """执行一个 Workflow."""
        if not state.workflow_engine:
            raise HTTPException(status_code=503, detail="Workflow Engine 未初始化")
        result = await state.workflow_engine.run(request)
        return result.model_dump()

    @app.get("/api/workflow/list")
    async def list_workflows():
        """列出所有已固化的 workflow."""
        if not state.planner:
            return []
        return state.planner.list_workflows()

    @app.get("/api/workflow/{name}")
    async def get_workflow(name: str):
        """加载指定 workflow."""
        if not state.planner:
            raise HTTPException(status_code=503, detail="Planner Agent 未初始化")
        wf = state.planner.load_workflow(name)
        if not wf:
            raise HTTPException(status_code=404, detail=f"Workflow '{name}' 未找到")
        return wf.model_dump()

    # ── Planner Agent ───────────────────────────────────────────

    class PlanRequest(BaseModel):
        request: str
        context: dict = {}

    @app.post("/api/planner/plan")
    async def plan_workflow(req: PlanRequest):
        """使用 Planner Agent 将自然语言请求拆解为 Workflow."""
        if not state.planner:
            raise HTTPException(status_code=503, detail="Planner Agent 未初始化")
        wf = await state.planner.run(req.request, req.context)
        if wf is None:
            raise HTTPException(status_code=400, detail="Planner 无法拆解此请求")
        return wf.model_dump()

    @app.post("/api/planner/plan-and-run")
    async def plan_and_run(req: PlanRequest):
        """Planner 拆解 → WorkflowEngine 自动执行."""
        if not state.planner or not state.workflow_engine:
            raise HTTPException(status_code=503, detail="Planner 或 Workflow Engine 未初始化")

        wf = await state.planner.run(req.request, req.context)
        if wf is None:
            raise HTTPException(status_code=400, detail="Planner 无法拆解此请求")

        result = await state.workflow_engine.run(wf)
        return {
            "workflow": wf.model_dump(),
            "result": result.model_dump(),
        }

    # ── Agent 管理 ──────────────────────────────────────────────

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

        # Start IPC handler (JSON-RPC over Unix Socket)
        ipc = IpcHandler(
            socket_path=config.socket_path,
            max_conn=config.max_agents,
        )
        _register_ipc_routes(ipc, state)
        state.ipc = ipc
        asyncio.create_task(ipc.start())

        # Init Workflow Engine
        state.workflow_engine = WorkflowEngine(state.event_bus)

        # Init Planner Agent (按需启动, 但保留单例引用)
        state.planner = PlannerAgent(
            state.event_bus,
            available_capabilities=[
                "shell.exec",
                "file.read",
                "file.write",
                "system.monitor",
                "system.diagnose",
            ],
        )

        # Register default node handler (shell.exec 等)
        async def _shell_exec_handler(
            workflow_id: str,
            node: NodeDefinition,
            context: dict,
        ) -> Any:
            """默认节点处理器: 通过 Tool Gateway 执行 shell 命令."""
            cmd = node.config.get("command", "")
            if not cmd:
                return {"error": "no command in node config"}
            parts = cmd.split()
            req = ExecuteRequest(
                tool=ToolType.SHELL,
                args=parts,
                agent_id=f"workflow:{workflow_id}",
                timeout_seconds=node.timeout_seconds,
            )
            resp = await state.tool_gateway.execute(req)
            return {
                "output": resp.output,
                "error": resp.error,
                "exit_code": resp.exit_code,
                "status": resp.status,
            }

        state.workflow_engine.set_default_handler(_shell_exec_handler)

        logger.info("trimum_core_started", host=config.host, port=config.port)

    @app.on_event("shutdown")
    async def shutdown():
        """Clean up on shutdown."""
        if state.context:
            await state.context.close()
        await state.agent_manager.stop_health_check()
        if state.ipc:
            await state.ipc.stop()
        if state.socket_server:
            state.socket_server.close()
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
