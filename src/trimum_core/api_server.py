"""FastAPI API Server for trimum Core."""

from __future__ import annotations

import asyncio
import time

import json
import os
import socket as stdlib_socket
from pathlib import Path
from typing import Any, Optional

import json
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
    ToolType,
)
from .tool_gateway import ToolGateway
from .behavior_monitor import BehaviorMonitor
from .audit_store import AuditStore
from .learning_engine import LearningEngine
from .policy_engine import PolicyEngine
from .event_bus import EventBus
from .context_manager import ContextManager
from .agent_manager import AgentManager
from .config import Config, ensure_dirs
from .logger import setup_logging, get_logger
from .ipc_handler import IpcHandler
from .workflow_event_driver import WorkflowEventDriver

logger = get_logger("api_server")

# 策略学习分析间隔（秒）
LEARNING_INTERVAL_SECONDS = 60

# MCP 空闲回收扫描间隔（秒）；每个 server 自己的 idle_ttl 决定回收时点
MCP_REAPER_INTERVAL_SECONDS = 30.0


class AppState:
    """Shared state for the FastAPI app."""

    def __init__(self, config: Config):
        self.config = config
        self.policy = PolicyEngine(Path(config.policy_path))
        from .llm_policy import LlmPolicyEngine
        from .security_config import SecurityConfig
        from .file_trust import FileTrustTracker

        # LLM 增强策略（#11）：复用 policy 引擎 + 安全配置
        sec_cfg = SecurityConfig()
        sec_cfg.load()
        self.llm_policy = LlmPolicyEngine(
            policy_engine=self.policy,
            security_config=sec_cfg,
        )
        self.file_trust = FileTrustTracker(db_path=":memory:")

        # Layer 2.5：SecurityRule + BehaviorMonitor（弹性沙箱决策）。
        # SecurityRule 由 ToolGateway 按需构造，这里只注入行为基线监控。
        self.behavior_monitor = BehaviorMonitor()
        self.event_bus = EventBus()
        # 审计：JSONL 落盘（trm log audit 查询）+ EventBus 广播 task.audit.*
        self.audit_store = AuditStore()
        # 学习反馈环：BehaviorMonitor 喂数据 → LearningEngine 出规则
        self.learning_engine = LearningEngine(monitor=self.behavior_monitor)
        self.tool_gateway = ToolGateway(
            self.policy,
            llm_policy=self.llm_policy,
            file_trust_tracker=self.file_trust,
            behavior_monitor=self.behavior_monitor,
            event_bus=self.event_bus,
            audit_store=self.audit_store,
            learning_engine=self.learning_engine,
        )
        self.agent_manager = AgentManager(
            max_agents=config.max_agents,
            health_check_interval=config.health_check_interval,
        )
        self.context: Optional[ContextManager] = None
        self.socket_server: Optional[stdlib_socket.socket] = None
        self.ipc: Optional[IpcHandler] = None
        self.driver: Optional[WorkflowEventDriver] = None
        self.learning_task: Optional[asyncio.Task] = None
        # MCP 连接池（M4）。在 startup() 里构造而不是这里：池子的空闲回收器
        # 和 cgroup 绑定都要在事件循环里跑，构造点必须和运行点重合。
        self.mcp_pool: Optional[Any] = None
        self.mcp_reaper: Optional[asyncio.Task] = None
        # MCP 聚合工具索引（M4.5）：远端工具在注册表里的名字是
        # `<server>__<tool>`，缓存落在 ~/.trimum/mcp-tools.json
        self.mcp_index: Optional[Any] = None


async def _learning_loop(state: AppState) -> None:
    """周期性跑一次 analyze()；auto 模式下自动注入学到的规则。"""
    while True:
        try:
            await asyncio.sleep(LEARNING_INTERVAL_SECONDS)
            summary = state.learning_engine.analyze()
            injected = 0
            if state.learning_engine.get_mode() == "auto":
                injected = state.learning_engine.inject_to_policy(state.policy)
            logger.info(
                "learning_analysis_done",
                agents=len(summary),
                injected=injected,
                mode=state.learning_engine.get_mode(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("learning_loop_failed", error=str(e))


def build_mcp_pool(config: Config):
    """构造 daemon 共享的 MCP 连接池（M4）。

    池子是常驻的，这正是 M4 的意义所在：`trm mcp call` 那种一次性进程每次都得
    重新拉起 server，而 daemon 可以复用、可以空闲回收、可以把子进程交出去做
    资源约束。日志落在 `config.log_path` 同级目录（子进程 stderr 不用管道）。
    """
    from .mcp_registry import MCPServerPool
    from .resource_controller import create_resource_controller

    cgroup = None
    try:
        cgroup = create_resource_controller()
    except Exception as e:  # 配额是尽力而为：拿不到控制器不该拖垮 daemon
        logger.warning("mcp_cgroup_controller_unavailable", error=str(e))

    log_dir = None
    try:
        log_dir = Path(config.log_path).expanduser().parent
    except Exception:  # pragma: no cover - 仅防御性兜底
        log_dir = None

    return MCPServerPool(log_dir=log_dir, cgroup=cgroup)


def wire_mcp_dispatchers(state: AppState, pool: Any) -> list[Any]:
    """把共享池交给所有 MCP 分发器，返回真正接上线的那些。

    `mcp.tools.list` 与 `mcp.tools.call` 在 DispatcherRegistry 里指向同一个
    `MCPDispatcher` 实例，所以按 id 去重；`set_pool` 自己也幂等。
    """
    wired: list[Any] = []
    seen: set[int] = set()
    for tool_type in (ToolType.MCP_TOOLS_LIST, ToolType.MCP_TOOLS_CALL):
        dispatcher = state.tool_gateway.dispatchers.get(tool_type)
        if dispatcher is None or id(dispatcher) in seen:
            continue
        seen.add(id(dispatcher))
        setter = getattr(dispatcher, "set_pool", None)
        if callable(setter):
            setter(pool)
            wired.append(dispatcher)
    return wired


def build_mcp_tool_index() -> Any:
    """聚合工具的缓存索引（远端工具并进 ToolRegistry，M4.5）。

    daemon 全程只用**一个**实例：`MCPDispatcher` 往里写（每次成功的
    ``tools/list`` 顺手落盘），`ToolGateway` 的注册表从里读。两条路必须是
    同一份缓存，否则刚列过的工具在 `trm tool list` 里依然看不见。
    """
    from .mcp_bridge import MCPToolIndex

    return MCPToolIndex()


def prune_mcp_index(index: Any, registry: Any) -> int:
    """把「定义已经不存在」的 server 从缓存里剔掉，返回剔掉的数量。

    目录读不到时什么都不做 —— 那说明「不知道有哪些 server」，而不是「一个
    server 都没有」；按后者处理会把整份缓存清空。
    """
    directory = getattr(registry, "directory", None)
    if directory is None or not Path(directory).is_dir():
        return 0
    return index.prune(registry.names())


def wire_mcp_index(state: AppState, index: Any) -> list[Any]:
    """把索引交给所有 MCP 分发器，并让注册表按它登记聚合条目。"""
    wired: list[Any] = []
    seen: set[int] = set()
    for tool_type in (ToolType.MCP_TOOLS_LIST, ToolType.MCP_TOOLS_CALL):
        dispatcher = state.tool_gateway.dispatchers.get(tool_type)
        if dispatcher is None or id(dispatcher) in seen:
            continue
        seen.add(id(dispatcher))
        setter = getattr(dispatcher, "set_tool_index", None)
        if callable(setter):
            setter(index)
            wired.append(dispatcher)

    registry = getattr(state.tool_gateway, "tools", None)
    if registry is not None and hasattr(registry, "load_mcp_tools"):
        registry.load_mcp_tools(index)
    return wired


async def start_mcp(state: AppState) -> None:
    """startup 期接线：建池 → 建索引 → 交给分发器 → 起空闲回收器。"""
    pool = build_mcp_pool(state.config)
    state.mcp_pool = pool
    index = build_mcp_tool_index()
    state.mcp_index = index
    # 定义被删掉之后，缓存里那些 `a__b` 不该继续冒充可用工具。daemon 起来
    # 时对一次账（运行期删定义由 `reap()` + 调用时的 not-found 兜住）。
    pruned = prune_mcp_index(index, pool.registry)
    wired = wire_mcp_dispatchers(state, pool)
    wire_mcp_index(state, index)
    # 回收器必须和池子同寿：daemon 关掉时由 close_all() 一起收摊
    state.mcp_reaper = pool.start_reaper(interval=MCP_REAPER_INTERVAL_SECONDS)
    logger.info(
        "mcp_pool_started",
        servers=len(pool.registry.servers()),
        wired=len(wired),
        tools=len(index.entries()),
        pruned=pruned,
        reaper_interval=MCP_REAPER_INTERVAL_SECONDS,
    )


def _core_version() -> str:
    """包版本号 —— `/health`（HTTP 与 IPC 两条路）统一取这里。

    原先 HTTP 路径写死 `0.2.0`、IPC 路径写死 `0.2.1`，与
    `trimum_core.__version__` 三处各说各话。
    """
    try:
        from . import __version__

        return __version__
    except Exception:  # pragma: no cover - 仅防御性兜底
        return "unknown"


def _register_ipc_routes(ipc: IpcHandler, state: AppState) -> None:
    """Register all JSON-RPC methods for the IPC handler."""
    router = ipc.router

    @router.register("health")
    async def rpc_health(params: dict) -> dict:
        return {"status": "ok", "version": _core_version()}

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

    @router.register("mcp.status")
    async def rpc_mcp_status(params: dict) -> list:
        """运行中的 MCP server 状态（只是读状态，不启动任何进程）。"""
        del params
        if state.mcp_pool is None:
            return []
        return await state.mcp_pool.status()

    @router.register("mcp.restart")
    async def rpc_mcp_restart(params: dict) -> dict:
        """重启一个 MCP server（先关再拉），其它 server 不受影响。"""
        from .mcp_client import MCPError

        name = str(params.get("server", "")).strip()
        if not name:
            return {"success": False, "error": "server is required"}
        if state.mcp_pool is None:
            return {"success": False, "server": name, "error": "MCP pool is not initialized"}
        try:
            await state.mcp_pool.restart(name)
        except MCPError as exc:
            return {"success": False, "server": name, "error": str(exc)}
        return {"success": True, "server": name}


def create_app(config: Config) -> FastAPI:
    """Create and configure the FastAPI application."""
    state = AppState(config)

    app = FastAPI(
        title="trimum Core",
        version=_core_version(),
        description="trimum AI Runtime - system-level agent execution engine",
    )

    # Store state
    app.state.trimum = state

    # ─── Routes ────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok", "version": _core_version()}

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

        # 周期性策略学习（BehaviorMonitor → LearningEngine）
        state.learning_task = asyncio.create_task(_learning_loop(state))

        # MCP 连接池（M4）：共享池 + 空闲回收器。接线放在 IPC 之前，这样
        # `trm mcp status` 一连上看到的就是真实状态。接不上也不拦启动。
        try:
            await start_mcp(state)
        except Exception as e:
            logger.warning("mcp_pool_start_failed", error=str(e))

        # Start IPC handler (JSON-RPC over Unix Socket)
        ipc = IpcHandler(
            socket_path=config.socket_path,
            max_conn=config.max_agents,
        )
        _register_ipc_routes(ipc, state)
        state.ipc = ipc
        asyncio.create_task(ipc.start())

        # Start WorkflowEventDriver (bridge between Engine and Agent)
        state.driver = WorkflowEventDriver(
            bus=state.event_bus,
            agent_manager=state.agent_manager,
            driver_host=config.host,
            driver_port=getattr(config, "driver_port", 0) or 0,
            confirm_timeout=getattr(config, "confirm_timeout", 300.0) or 300.0,
        )
        # Start WorkflowEventDriver in background (don't block startup)
        async def _delay_start():
            try:
                await asyncio.wait_for(state.driver.start(), timeout=10.0)
                logger.info("workflow_event_driver_started")
            except asyncio.TimeoutError:
                logger.warning("workflow_event_driver_startup_timeout")
            except Exception as e:
                logger.warning("workflow_event_driver_startup_failed", error=str(e))
        asyncio.create_task(_delay_start())

        logger.info("trimum_core_started", host=config.host, port=config.port)


    @app.post("/api/security/allow_once")
    async def security_allow_once(req: dict):
        """签发一次性授权令牌（JIT）。

        Body:
            agent_id: 目标 agent
            tool: 工具名（如 shell / file_io）
            command: 允许执行的命令
            ttl: 有效期秒数（默认 300）
        """
        agent_id = req.get("agent_id", "")
        tool_str = req.get("tool", "")
        command = req.get("command", "")
        ttl = float(req.get("ttl", 300))

        if not agent_id or not tool_str:
            raise HTTPException(status_code=400, detail="agent_id and tool are required")

        try:
            from .models import ToolType
            tool = ToolType(tool_str)
        except ValueError:
            tool = ToolType.SHELL

        token = state.tool_gateway.issue_jit_token(
            agent_id=agent_id,
            tool=tool,
            command=command,
            ttl=ttl,
        )
        return {"success": True, "data": token.model_dump(), "message": "JIT token issued"}

    @app.post("/api/security/learn")
    async def security_learn(req: dict | None = None):
        """立即执行一次策略学习分析。

        Body:
            inject: true 时把学到的规则注入当前 PolicyEngine
        """
        payload = req or {}
        summary = state.learning_engine.analyze()
        injected = 0
        if payload.get("inject"):
            injected = state.learning_engine.inject_to_policy(state.policy)
        return {
            "success": True,
            "data": {
                "mode": state.learning_engine.get_mode(),
                "summary": summary,
                "injected": injected,
            },
            "message": "learning analysis complete",
        }

    @app.get("/api/security/learning")
    async def security_learning():
        """查看学习状态：全局摘要 + 各 Agent 画像。"""
        engine = state.learning_engine
        profiles = {
            agent_id: {
                "total_actions": profile.total_actions,
                "deny_count": profile.deny_count,
                "action_types": len(profile.action_counts),
                "learned_rules": len(profile.learned_rules),
                "learning_mode": profile.learning_mode,
            }
            for agent_id, profile in engine.get_profiles().items()
        }
        return {
            "success": True,
            "data": {"summary": engine.get_summary(), "profiles": profiles},
            "message": "ok",
        }

    @app.get("/api/security/tokens")
    async def security_tokens(agent_id: str = ""):
        """列出有效的 JIT 令牌（可选按 agent 过滤）。"""
        tokens = getattr(state.tool_gateway, "_jit_tokens", {})
        result = []
        now = time.time()
        for tok_str, tok in tokens.items():
            if tok.expires_at > 0 and now > tok.expires_at:
                continue
            if agent_id and tok.agent_id != agent_id:
                continue
            d = tok.model_dump()
            d["token"] = tok.token[:8] + "..."
            result.append(d)
        return {"success": True, "data": result}


    @app.on_event("shutdown")
    async def shutdown():
        """Clean up on shutdown."""
        if state.context:
            await state.context.close()
        await state.agent_manager.stop_health_check()
        if state.learning_task:
            state.learning_task.cancel()
        if state.mcp_pool is not None:
            # 池子先停回收器，再逐个关掉 server 子进程
            await state.mcp_pool.close_all()
        if state.driver:
            await state.driver.stop()
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
