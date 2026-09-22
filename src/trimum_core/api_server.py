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
from .ipc_handler import IpcHandler, IpcUnavailableError
from .workflow_event_driver import WorkflowEventDriver
from .workflow_runtime import WorkflowRuntime

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
        # W1：workflow 常驻运行时（监听 Event Bus → 驱动执行）
        self.workflow_runtime: Optional[WorkflowRuntime] = None
        # 意图驱动链的监听器（Transform Agent → 三段式决策 → workflow.trigger）
        self.workflow_listener: Optional[Any] = None
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

    「定义已经不存在」也包括**整个目录被删掉**：那种情况下缓存里每一条都指着
    不存在的 server，留着只会让 `trm tool list` 列出一批调用必然失败的幽灵
    工具。只有「目录在、但列不出来」（权限 / IO）才算「不知道有哪些 server」，
    那时不动缓存 —— 判定见 `mcp_registry.definitions_readable()`。
    """
    from .mcp_registry import definitions_readable

    directory = getattr(registry, "directory", None)
    if directory is None:
        return 0
    if not definitions_readable(directory):
        logger.info(
            "mcp_index.prune_skipped",
            directory=str(directory),
            reason="unreadable",
        )
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


#: daemon 进程的启动时刻。`health` 自报 uptime 用。
_STARTED_AT = time.time()


def _health_payload(config: Config, state: AppState | None = None) -> dict:
    """`health` 的唯一口径（HTTP `/health` 与 IPC `health` 共用一份）。

    必须把 `pid` / `uptime` 带上：`trm status` 原先靠 psutil 扫
    `127.0.0.1:8321` 的监听者拿 pid（`cli/commands/status.py::_find_daemon_pid`），
    TCP 面一关就扫不到了，只能由 daemon 自报。`ipc` / `http` 同理：这两个字段
    直接回答「socket 到底起没起来」「TCP 面还开不开」。
    """
    payload: dict[str, Any] = {
        "status": "ok",
        "version": _core_version(),
        "pid": os.getpid(),
        "uptime": round(time.time() - _STARTED_AT, 1),
        "socket": config.socket_path,
        "http": bool(config.http_enabled),
    }
    ipc = state.ipc if state is not None else None
    if ipc is not None:
        payload["ipc"] = ipc.listening
    return payload


def _jit_tokens(state: AppState, agent_id: str = "") -> list[dict]:
    """有效的 JIT 令牌（可选按 agent 过滤）；令牌本体只露前 8 位。"""
    tokens = getattr(state.tool_gateway, "_jit_tokens", {})
    result: list[dict] = []
    now = time.time()
    for token in tokens.values():
        if token.expires_at > 0 and now > token.expires_at:
            continue
        if agent_id and token.agent_id != agent_id:
            continue
        entry = token.model_dump()
        entry["token"] = token.token[:8] + "..."
        result.append(entry)
    return result


def _revoke_jit_token(state: AppState, token_str: str) -> dict:
    """撤销一个 JIT 令牌（按完整串或前缀匹配）。

    前缀至少 4 位，避免误伤；匹配到多个也拒绝（要更精确的前缀）。
    """
    if not token_str or len(token_str) < 4:
        return {"revoked": False, "error": "token_id too short (need >= 4 chars)"}

    prefix = token_str.rstrip(".")
    tokens = getattr(state.tool_gateway, "_jit_tokens", {})
    matches = [full for full in tokens if full.startswith(prefix)]
    if not matches:
        return {"revoked": False, "error": "token not found (expired, used, or already revoked)"}
    if len(matches) > 1:
        return {
            "revoked": False,
            "error": f"ambiguous prefix: {len(matches)} tokens match",
        }
    state.tool_gateway.revoke_jit_token(matches[0])
    return {"revoked": True, "token": matches[0][:8] + "..."}


def _learning_status(state: AppState) -> dict:
    """学习状态：全局摘要 + 各 Agent 画像。"""
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
    return {"summary": engine.get_summary(), "profiles": profiles}


def _run_learning(state: AppState, inject: bool = False) -> dict:
    """立即跑一次策略学习；inject=True 时把学到的规则注入当前 PolicyEngine。"""
    summary = state.learning_engine.analyze()
    injected = state.learning_engine.inject_to_policy(state.policy) if inject else 0
    return {
        "mode": state.learning_engine.get_mode(),
        "summary": summary,
        "injected": injected,
    }


def _register_ipc_routes(ipc: IpcHandler, state: AppState) -> None:
    """Register all JSON-RPC methods for the IPC handler."""
    router = ipc.router

    @router.register("health")
    async def rpc_health(params: dict) -> dict:
        return _health_payload(state.config, state)

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

    # ── 安全面（JIT 令牌 / 策略学习）───────────────────────────
    # `trm security tokens|learning|learn` 原先只走 HTTP，是 TCP 面关掉之后
    # 唯一会直接坏掉的命令面；这三个 RPC 把它们的腿补上。同一份实现
    # （_jit_tokens / _learning_status / _run_learning）HTTP 与 IPC 共用。

    @router.register("security.tokens")
    async def rpc_security_tokens(params: dict) -> dict:
        return {"tokens": _jit_tokens(state, str(params.get("agent_id", "")))}

    @router.register("security.learning")
    async def rpc_security_learning(params: dict) -> dict:
        del params
        return _learning_status(state)

    @router.register("security.learn")
    async def rpc_security_learn(params: dict) -> dict:
        return _run_learning(state, bool(params.get("inject")))

    @router.register("security.revoke")
    async def rpc_security_revoke(params: dict) -> dict:
        return _revoke_jit_token(state, str(params.get("token_id", "")))


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
        """Health check endpoint（与 IPC `health` 同一份口径）。"""
        return _health_payload(config, state)

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
        # 必须 await：create_task 会把「socket 起不来」这一整类失败吞进后台任务，
        # daemon 照样报 active，而 IPC 通道其实不存在（真机上就是这么坏的）。
        await ipc.start()
        if ipc.socket_start_error:
            logger.error(
                "ipc_socket_unavailable",
                socket=config.socket_path,
                error=ipc.socket_start_error,
                detail="IPC 通道不可用，客户端只剩 HTTP 可走（同机谁都能连）",
            )
            if not config.http_enabled:
                # 两条路都断了：HTTP 被关、socket 又没起来。这个 daemon 什么都不
                # 提供，却会被 systemd 记成 active —— 必须当场起不来，不能装活着。
                raise IpcUnavailableError(
                    f"socket={config.socket_path} error={ipc.socket_start_error}"
                )

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

        # W1：workflow 常驻运行时。文件目录（E4 导入产物）+ 内置威胁剧本一起注册，
        # 然后开始监听 Event Bus —— 命中的 workflow 由 WorkflowEngine 执行，
        # shell 任务走上面那个共享的 ToolGateway（策略 / 审计 / 行为基线都在这条线上）。
        try:
            runtime = WorkflowRuntime(
                event_bus=state.event_bus,
                gateway=state.tool_gateway,
                driver=state.driver,
            )
            counts = runtime.register_all()
            await runtime.start()
            state.workflow_runtime = runtime
            logger.info(
                "workflow_runtime_started",
                file=len(counts["file"]),
                builtin=len(counts["builtin"]),
            )
        except Exception as e:
            logger.warning("workflow_runtime_start_failed", error=str(e))

        # 意图驱动那条链（W1 遗留的接线）：``event.transform.completed`` 以前没有生产者，
        # 于是 WorkflowListener 从未被实例化、``workflow.trigger`` 也从不出现。这里装上它，
        # 与常驻 runtime 共用同一个总线、网关与 workflow 目录；入口是 ``trm workflow submit``。
        try:
            from .paths import trimum_path
            from .planner_agent import PlannerAgent
            from .transform_agent import TransformAgent
            from .workflow_listener import WorkflowListener

            # Planner 的 workflow_dir 必须显式给：它默认落在真实 ~/.trimum，
            # 不看 TRIMUM_HOME（沙箱与多用户场景都会踩）。
            state.workflow_listener = WorkflowListener(
                event_bus=state.event_bus,
                transform_agent=TransformAgent(),
                tool_gateway=state.tool_gateway,
                planner_agent=PlannerAgent(
                    state.event_bus, workflow_dir=trimum_path("workflows")
                ),
            )
            await state.workflow_listener.start()
            logger.info("workflow_listener_started")
        except Exception as e:
            logger.warning("workflow_listener_start_failed", error=str(e))

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
        return {
            "success": True,
            "data": _run_learning(state, bool(payload.get("inject"))),
            "message": "learning analysis complete",
        }

    @app.get("/api/security/learning")
    async def security_learning():
        """查看学习状态：全局摘要 + 各 Agent 画像。"""
        return {
            "success": True,
            "data": _learning_status(state),
            "message": "ok",
        }

    @app.get("/api/security/tokens")
    async def security_tokens(agent_id: str = ""):
        """列出有效的 JIT 令牌（可选按 agent 过滤）。"""
        return {"success": True, "data": _jit_tokens(state, agent_id)}


    @app.get("/api/workflows")
    async def workflows(include_disabled: bool = True):
        """列出常驻运行时里的 workflow（文件 + 内置剧本）。"""
        runtime = state.workflow_runtime
        if runtime is None:
            return {"success": False, "data": [], "message": "workflow runtime not started"}
        items = runtime.list_workflows(include_disabled=include_disabled)
        return {"success": True, "data": items, "count": len(items)}

    @app.get("/api/workflows/runs")
    async def workflow_runs(workflow_id: str = "", limit: int = 20):
        """最近的 workflow 运行记录（内存环形，进程重启即丢）。"""
        runtime = state.workflow_runtime
        if runtime is None:
            return {"success": False, "data": [], "message": "workflow runtime not started"}
        runs = [
            record.to_dict()
            for record in runtime.runs(workflow_id or None, limit=limit)
        ]
        return {"success": True, "data": runs, "count": len(runs)}

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
        if state.workflow_listener is not None:
            await state.workflow_listener.stop()
        if state.workflow_runtime:
            await state.workflow_runtime.stop()
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
