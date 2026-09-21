"""Workflow Runtime —— 让 workflow 真的监听 Event Bus 并驱动执行（W1）。

引擎（``workflow_engine.py``）只会执行「已经拿在手里的 DAG」；本模块补的是它缺的前半截：
**谁来决定什么时候跑**。

::

    Event Bus ──(event_type + condition 命中)──> WorkflowRuntime
                                                  │ 编译 step → Node/Edge
                                                  ▼
                                            WorkflowEngine.run()
                                                  │
                            handler="shell" ──────┴──── handler 带 agent_type
                                    │                          │
                            ToolGateway.execute()      WorkflowEventDriver
                        （策略/风险/审计/脱敏/cwd jail）      （子 Agent 进程）

语义（详见 ``docs/WORKFLOW-EXECUTION-PLAN.md`` §3.1）：

- 一个 step = 一个触发器 + 一组任务；**step 之间互不等待**，各自常驻监听。
  需要串行的流程写在同一个 step 的 ``execute`` 组里（组内按顺序执行）。
- ``trigger.event_type`` 为空 = 只能手动 ``run_now()``，不参与事件分发。
- 同一个 workflow+step 已在跑时再次触发 → 跳过并发 ``workflow.skipped`` 事件，
  防止「事件风暴 / 自我触发」滚成死循环。
- shell 任务一律走 ToolGateway：运行时不持有任何绕过策略与审计的旁路。
- 条件表达式：受限 ``eval``（空 ``__builtins__``，命名空间只有 ``payload`` /
  ``event`` / ``true`` / ``false``），求值失败按「不通过」处理。
- **触发归属**（2026-09-21 定）：内置威胁剧本监听 ``security.monitor_result``（L4 的
  事实事件，唯一自动链）；``workflow.trigger`` 是「意图驱动」（TARL 三段式 →
  ``workflow_listener.py``，未接线）那条链的事件，运行时对两者一视同仁 —— 谁在
  ``trigger.event_type`` 里写了什么，就听什么。

运行记录只存内存（环形，进程重启即丢），持久化留给后续的 `trm workflow status/log`。
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
import uuid
from collections import deque
from typing import Any, Coroutine

from pydantic import BaseModel, Field

from .event_bus import EventBus
from .models import (
    ExecuteRequest,
    SourceType,
    SystemEvent,
    ToolType,
    TRMErrorCode,
    TrimumError,
)
from .workflow_engine import (
    NodeDefinition,
    WorkflowDefV2,
    WorkflowDefinition,
    WorkflowEngine,
)

log = logging.getLogger("trimum_core.workflow_runtime")

#: ``agent_type`` 取这些值时按「本地命令」处理（走 ToolGateway）
SHELL_AGENT_ALIASES = ("shell", "bash", "sh", "zsh", "terminal")

#: 需要 Agent 判断（而不是本地命令）的步骤编译成这个 agent 类型
REVIEW_AGENT = "trm-agent"

#: 运行记录保留条数（内存环形）
DEFAULT_MAX_RUNS = 200

#: 判定「节点失败」用的终态
FAILED_NODE_STATUSES = ("failed", "timeout", "blocked", "cancelled")

#: 事件驱动下的熔断窗口 / 上限：同一 workflow 在 RUN_WINDOW_SECONDS 内最多自动跑
#: 这么多次。防的是**事件环路**——A 的 `workflow.finished` 触发 B、B 的又触发 A 这种
#: 环（「同一 step 不并发」拦不住它）。手动 `run_now()` / `trigger()` 不受限：那是人点的。
RUN_WINDOW_SECONDS = 10.0
MAX_RUNS_PER_WINDOW = 20


def _clip(value: Any, limit: int) -> Any:
    """截断过长的结果（运行记录是给人和 CLI 看的，不要塞进整段日志）。"""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return f"{value[:limit]}...(+{len(value) - limit})"
    if isinstance(value, dict):
        return {key: _clip(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip(item, limit) for item in value]
    return value


def workflow_enabled(workflow: WorkflowDefV2) -> bool:
    """读启用位。

    文件里的写法可以是 ``config.enabled``，也可以是 E4 导入产物那种
    ``config.ecosystem.enabled``（工具清单同一套约定）；都没有就是启用。
    """
    config = workflow.config or {}
    if "enabled" in config:
        return bool(config["enabled"])
    ecosystem = config.get("ecosystem")
    if isinstance(ecosystem, dict) and "enabled" in ecosystem:
        return bool(ecosystem["enabled"])
    return True


class NodeRunRecord(BaseModel):
    """单个节点的运行结果（引擎 ``NodeRuntime`` 的投影）。"""

    node_id: str
    handler: str = ""
    status: str = "created"
    duration: float = 0.0
    error: str = ""
    result: Any = None

    def to_dict(self, *, limit: int = 400) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "handler": self.handler,
            "status": self.status,
            "duration": round(self.duration, 4),
            "error": self.error,
            "result": _clip(self.result, limit),
        }


class WorkflowRunRecord(BaseModel):
    """一次 workflow 运行的记录。"""

    run_id: str
    workflow_id: str
    workflow_name: str = ""
    source: str = "file"
    step_index: int = -1
    """命中的 step 序号；``run_now()``（手动跑全流程）为 -1。"""
    trigger_event: str = ""
    triggered_by: str = "manual"
    """manual（人/CLI） | event（Event Bus）"""
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "running"
    error: str = ""
    started_at: float = 0.0
    duration: float = 0.0
    nodes: list[NodeRunRecord] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    def failed_nodes(self) -> list[str]:
        return [n.node_id for n in self.nodes if n.status in FAILED_NODE_STATUSES]

    def to_dict(self, *, limit: int = 400) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "source": self.source,
            "step_index": self.step_index,
            "trigger_event": self.trigger_event,
            "triggered_by": self.triggered_by,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at,
            "duration": round(self.duration, 4),
            "failed_nodes": self.failed_nodes(),
            "nodes": [node.to_dict(limit=limit) for node in self.nodes],
        }


class RegisteredWorkflow(BaseModel):
    """注册表条目：定义 + 来源 + 是否参与事件分发。"""

    workflow: WorkflowDefV2
    source: str = "file"
    """file | builtin | inline"""
    enabled: bool = True

    @property
    def id(self) -> str:
        return self.workflow.id

    def triggers(self) -> list[str]:
        return [
            step.trigger.event_type
            for step in self.workflow.steps
            if step.trigger.event_type
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.workflow.id,
            "name": self.workflow.name,
            "description": self.workflow.description,
            "source": self.source,
            "enabled": self.enabled,
            "triggers": self.triggers(),
            "steps": len(self.workflow.steps),
            "tasks": sum(len(step.execute) for step in self.workflow.steps),
        }


class WorkflowRuntime:
    """常驻工作流运行时：注册 → 监听 Event Bus → 驱动执行 → 记账。

    启动方式::

        runtime = WorkflowRuntime(event_bus, gateway=gateway, driver=driver)
        runtime.register_all()          # ~/.trimum/workflows + 内置剧本
        await runtime.start()           # 开始监听
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        gateway: Any = None,
        driver: Any = None,
        engine: WorkflowEngine | None = None,
        agent_id: str = "trm-workflow",
        source_type: SourceType = SourceType.WORKFLOW,
        max_runs: int = DEFAULT_MAX_RUNS,
        allow_concurrent_same_step: bool = False,
        run_window_seconds: float = RUN_WINDOW_SECONDS,
        max_runs_per_window: int = MAX_RUNS_PER_WINDOW,
    ) -> None:
        self._bus = event_bus
        self._gateway = gateway
        self._driver = driver
        self._engine = engine or WorkflowEngine(event_bus, driver=driver)
        self._agent_id = agent_id
        self._source_type = source_type
        self._max_runs = max(1, int(max_runs))
        self._allow_concurrent = allow_concurrent_same_step
        self._run_window = max(0.0, float(run_window_seconds))
        self._max_runs_per_window = max(1, int(max_runs_per_window))
        self._run_times: dict[str, deque[float]] = {}

        self._workflows: dict[str, RegisteredWorkflow] = {}
        self._runs: deque[WorkflowRunRecord] = deque(maxlen=self._max_runs)
        self._run_count = 0
        self._tasks: set[asyncio.Task[Any]] = set()
        self._active_keys: set[tuple[str, int]] = set()
        self._running = False

        # ``agent_type: shell`` → 本地命令处理器（走 ToolGateway）
        for alias in SHELL_AGENT_ALIASES:
            self._engine.register_handler(alias, self._handle_shell_node)

    # ── 只读属性 ──────────────────────────────────────────

    @property
    def engine(self) -> WorkflowEngine:
        return self._engine

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def running(self) -> bool:
        return self._running

    @property
    def run_count(self) -> int:
        """累计运行次数（给「等新运行」用的基线）。"""
        return self._run_count

    @property
    def in_flight(self) -> int:
        """在途运行数。"""
        return len(self._tasks)

    # ── 注册表 ────────────────────────────────────────────

    def register(
        self,
        workflow: WorkflowDefV2,
        *,
        source: str = "file",
        enabled: bool | None = None,
    ) -> str:
        """收进一份 WorkflowDefV2；返回它的 id。"""
        if not isinstance(workflow, WorkflowDefV2):
            raise TrimumError(
                TRMErrorCode.WORKFLOW_VALIDATION_FAILED,
                message=(
                    "register() expects a WorkflowDefV2, got "
                    f"{type(workflow).__name__}"
                ),
            )
        if not workflow.id:
            workflow.id = f"wf-{uuid.uuid4().hex[:8]}"
        if enabled is None:
            enabled = workflow_enabled(workflow)

        self._workflows[workflow.id] = RegisteredWorkflow(
            workflow=workflow, source=source, enabled=bool(enabled)
        )
        log.info(
            "workflow_runtime.registered id=%s source=%s enabled=%s triggers=%s",
            workflow.id, source, enabled,
            [s.trigger.event_type for s in workflow.steps],
        )
        return workflow.id

    def unregister(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def get(self, workflow_id: str) -> RegisteredWorkflow | None:
        """按 id 或 name 取注册条目。"""
        found = self._workflows.get(workflow_id)
        if found is not None:
            return found
        for item in self._workflows.values():
            if item.workflow.name == workflow_id:
                return item
        return None

    def list_workflows(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        items = [
            item.to_dict()
            for item in sorted(self._workflows.values(), key=lambda item: item.id)
        ]
        if include_disabled:
            return items
        return [item for item in items if item["enabled"]]

    def register_dir(
        self,
        root: str | None = None,
        *,
        source: str = "file",
        enabled: bool | None = None,
    ) -> list[str]:
        """扫描 ``<TRIMUM_HOME>/workflows``（E4 导入产物就落在那儿）并注册。"""
        ids: list[str] = []
        for workflow in WorkflowDefV2.load_from_dir(root):
            ids.append(self.register(workflow, source=source, enabled=enabled))
        return ids

    def register_builtin(self, *, enabled: bool = False) -> list[str]:
        """注册内置威胁响应剧本（触发器 = ``security.monitor_result``，见 ``threat_workflows``）。

        默认 ``enabled=False``：剧本里有 ``kill`` / ``firewall-cmd``，自动触发等于
        把确认环节删掉。手动 ``run_now()`` 不受此限（人已经明确点了）。
        """
        from .threat_workflows import builtin_workflows

        ids: list[str] = []
        for workflow in builtin_workflows():
            ids.append(self.register(workflow, source="builtin", enabled=enabled))
        return ids

    def register_all(
        self,
        root: str | None = None,
        *,
        include_builtin: bool = True,
        builtin_enabled: bool = False,
    ) -> dict[str, list[str]]:
        """文件目录 + 内置剧本一次性注册（daemon 与 CLI 共用这个口径）。

        先内置后文件：**同名时本地文件覆盖内置**（用户把内置剧本 ``enable`` 成
        自己的文件后，那份是生效的那份）。
        """
        result: dict[str, list[str]] = {"builtin": [], "file": []}
        if include_builtin:
            result["builtin"] = self.register_builtin(enabled=builtin_enabled)
        result["file"] = self.register_dir(root)
        return result

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self) -> None:
        """开始监听 Event Bus。

        只订阅一次 ``*``，命中判断在 :meth:`_on_event` 里按每个 workflow 的
        ``steps[].trigger`` 做——workflow 是运行期注册/注销的，逐条 subscribe 会
        让订阅表和注册表互相追着改。
        """
        if self._running:
            return
        self._running = True
        self._bus.subscribe("*", self._on_event)
        log.info("workflow_runtime.started workflows=%d", len(self._workflows))

    async def stop(self, *, cancel_running: bool = True) -> None:
        if not self._running:
            return
        self._running = False
        self._bus.unsubscribe("*", self._on_event)
        if cancel_running and self._tasks:
            pending = list(self._tasks)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        log.info("workflow_runtime.stopped")

    # ── 事件分发 ──────────────────────────────────────────

    async def _on_event(self, event: SystemEvent) -> None:
        if not self._running:
            return
        payload = dict(event.payload or {})
        for registered in list(self._workflows.values()):
            if not registered.enabled:
                continue
            if self._rate_limited(registered.id):
                await self._bus.emit_event("workflow.throttled", "workflow-runtime", {
                    "workflow_id": registered.id,
                    "trigger_event": event.event_type,
                    "window_seconds": self._run_window,
                    "max_runs": self._max_runs_per_window,
                })
                continue
            for index in self._matching_steps(registered.workflow, event):
                if not self._allow_concurrent and self._is_active(registered.id, index):
                    await self._bus.emit_event("workflow.skipped", "workflow-runtime", {
                        "workflow_id": registered.id,
                        "step_index": index,
                        "trigger_event": event.event_type,
                        "reason": "already_running",
                    })
                    continue
                self._spawn(self._run_step(
                    registered,
                    index,
                    payload=payload,
                    triggered_by="event",
                    trigger_event=event.event_type,
                ))

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """把运行挂到后台，并把异常收在自己的日志里（事件回调不能冒泡）。"""

        async def _guard() -> None:
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - 兜底
                log.warning("workflow_runtime.run_crashed error=%s", exc)

        task = asyncio.ensure_future(_guard())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _is_active(self, workflow_id: str, step_index: int) -> bool:
        return (workflow_id, step_index) in self._active_keys

    def _rate_limited(self, workflow_id: str) -> bool:
        """这个 workflow 在窗口内是否已经自动跑满（事件环路熔断）。"""
        if self._run_window <= 0:
            return False
        stamps = self._run_times.get(workflow_id)
        if not stamps:
            return False
        cutoff = time.monotonic() - self._run_window
        while stamps and stamps[0] < cutoff:
            stamps.popleft()
        return len(stamps) >= self._max_runs_per_window

    # ── 触发 ──────────────────────────────────────────────

    async def trigger(
        self,
        workflow_id: str,
        *,
        payload: dict[str, Any] | None = None,
        step_index: int | None = None,
        trigger_event: str = "",
        wait: bool = True,
    ) -> list[WorkflowRunRecord]:
        """手动触发（等价于「它监听的事件来了」）。

        ``step_index`` 省略时触发所有带任务的 step。
        """
        registered = self.get(workflow_id)
        if registered is None:
            raise TrimumError(
                TRMErrorCode.WORKFLOW_VALIDATION_FAILED,
                message=f"unknown workflow: {workflow_id}",
            )
        if step_index is None:
            indices = [
                index for index, step in enumerate(registered.workflow.steps)
                if step.execute
            ]
        else:
            indices = [step_index]

        records: list[WorkflowRunRecord] = []
        for index in indices:
            coro = self._run_step(
                registered,
                index,
                payload=payload or {},
                triggered_by="manual",
                trigger_event=trigger_event or registered.workflow.steps[index].trigger.event_type,
            )
            if wait:
                records.append(await coro)
            else:
                self._spawn(coro)
        return records

    async def run_now(
        self,
        workflow_id: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> WorkflowRunRecord:
        """立刻执行整份 workflow（不看触发器，step 之间按声明顺序串行）。"""
        registered = self.get(workflow_id)
        if registered is None:
            raise TrimumError(
                TRMErrorCode.WORKFLOW_VALIDATION_FAILED,
                message=f"unknown workflow: {workflow_id}",
            )
        return await self._run_definition(
            registered,
            registered.workflow.to_workflow_definition(),
            step_index=-1,
            payload={},
            triggered_by="manual",
            trigger_event="",
            context=context,
        )

    async def wait_for_runs(
        self,
        *,
        since: int = 0,
        timeout: float = 30.0,
        grace: float = 0.25,
    ) -> list[WorkflowRunRecord]:
        """等到 ``since`` 之后产生的运行全部结束，返回这些记录。

        超时不抛异常——调用方按返回条数判断「触发器命中了吗」。``grace`` 是给事件
        派发留的最小观察窗（publish 之后回调是被 ensure_future 拉起来的，
        立刻查会查不到）。
        """
        deadline = time.monotonic() + max(0.0, timeout)
        grace_until = time.monotonic() + max(0.0, grace)
        while True:
            new_runs = self.runs_since(since)
            now = time.monotonic()
            if new_runs and not self._tasks:
                return new_runs
            if now >= deadline:
                return new_runs
            if not new_runs and not self._tasks and now >= grace_until:
                return new_runs
            await asyncio.sleep(0.01)

    def runs_since(self, since: int) -> list[WorkflowRunRecord]:
        delta = self._run_count - int(since)
        if delta <= 0:
            return []
        return list(self._runs)[-delta:]

    def runs(
        self,
        workflow_id: str | None = None,
        *,
        limit: int = 20,
    ) -> list[WorkflowRunRecord]:
        """最近若干次运行（最新在后）。"""
        items = [
            record for record in self._runs
            if workflow_id is None or record.workflow_id == workflow_id
        ]
        return items[-limit:] if limit > 0 else items

    # ── 执行 ──────────────────────────────────────────────

    async def _run_step(
        self,
        registered: RegisteredWorkflow,
        step_index: int,
        *,
        payload: dict[str, Any],
        triggered_by: str,
        trigger_event: str,
    ) -> WorkflowRunRecord:
        definition = self._step_definition(registered.workflow, step_index)
        return await self._run_definition(
            registered,
            definition,
            step_index=step_index,
            payload=payload,
            triggered_by=triggered_by,
            trigger_event=trigger_event,
        )

    async def _run_definition(
        self,
        registered: RegisteredWorkflow,
        definition: WorkflowDefinition,
        *,
        step_index: int,
        payload: dict[str, Any],
        triggered_by: str,
        trigger_event: str,
        context: dict[str, Any] | None = None,
    ) -> WorkflowRunRecord:
        workflow = registered.workflow
        label = "all" if step_index < 0 else str(step_index)
        run_id = f"{workflow.id}#{label}-{uuid.uuid4().hex[:8]}"

        record = WorkflowRunRecord(
            run_id=run_id,
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            source=registered.source,
            step_index=step_index,
            trigger_event=trigger_event,
            triggered_by=triggered_by,
            payload=dict(payload or {}),
            status="running",
            started_at=time.time(),
        )
        self._runs.append(record)
        self._run_count += 1
        self._run_times.setdefault(workflow.id, deque()).append(time.monotonic())
        key = (workflow.id, step_index)
        self._active_keys.add(key)

        await self._bus.emit_event("workflow.triggered", "workflow-runtime", {
            "workflow_id": workflow.id,
            "run_id": run_id,
            "step_index": step_index,
            "triggered_by": triggered_by,
            "trigger_event": trigger_event,
        })

        run_context: dict[str, Any] = dict(context or {})
        run_context.update({
            "workflow_id": workflow.id,
            "run_id": run_id,
            "step_index": step_index,
            "trigger_event": trigger_event,
            "trigger_payload": record.payload,
        })

        cancelled = False
        try:
            result = await self._engine.run(definition, run_context)
            record.status = result.status.value
            record.duration = result.duration
            record.nodes = self._project_nodes(definition, result)
        except asyncio.CancelledError:
            cancelled = True
            record.status = "cancelled"
            record.duration = time.time() - record.started_at
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            record.duration = time.time() - record.started_at
            log.warning(
                "workflow_runtime.run_failed id=%s run=%s error=%s",
                workflow.id, run_id, exc,
            )
        # 收尾事件在「仍然算在跑」的时候发：监听 workflow.finished 的 workflow
        # 会被这一发命中，此时熔断/并发闸门还在，环路走不出第二步。
        try:
            await self._bus.emit_event("workflow.finished", "workflow-runtime", {
                "workflow_id": workflow.id,
                "run_id": run_id,
                "step_index": step_index,
                "triggered_by": triggered_by,
                "trigger_event": trigger_event,
                "status": record.status,
                "duration": record.duration,
                "failed_nodes": record.failed_nodes(),
            })
        finally:
            self._active_keys.discard(key)

        if cancelled:
            raise asyncio.CancelledError()
        return record

    @staticmethod
    def _project_nodes(
        definition: WorkflowDefinition,
        result: Any,
    ) -> list[NodeRunRecord]:
        """把引擎的 ``NodeRuntime`` 投影成运行记录里的节点列表。"""
        projected: list[NodeRunRecord] = []
        node_results = getattr(result, "node_results", {}) or {}
        for node in definition.nodes:
            runtime = node_results.get(node.id)
            if runtime is None:
                continue
            duration = 0.0
            if runtime.started_at and runtime.completed_at:
                duration = runtime.completed_at - runtime.started_at
            projected.append(NodeRunRecord(
                node_id=node.id,
                handler=node.handler,
                status=runtime.status.value,
                duration=duration,
                error=runtime.error or "",
                result=runtime.result,
            ))
        return projected

    @staticmethod
    def _step_definition(
        workflow: WorkflowDefV2,
        step_index: int,
    ) -> WorkflowDefinition:
        """把第 ``step_index`` 个 step 编译成一份独立定义。

        借道 ``WorkflowDefV2.to_workflow_definition()``（一条编译路径，不另写一份），
        再把节点 id 从 ``step_0_task_*`` 改回全局编号，这样运行记录里的
        ``step_<i>_task_<j>`` 和整份 workflow 的编号对得上。
        """
        single = WorkflowDefV2(
            id=f"{workflow.id}#step{step_index}",
            name=workflow.name,
            description=workflow.description,
            steps=[workflow.steps[step_index]],
            config=workflow.config,
        )
        definition = single.to_workflow_definition()

        remap = {
            node.id: f"step_{step_index}_task_{index}"
            for index, node in enumerate(definition.nodes)
        }
        for node in definition.nodes:
            node.id = remap[node.id]
        for edge in definition.edges:
            edge.source = remap.get(edge.source, edge.source)
            edge.target = remap.get(edge.target, edge.target)
        return definition

    # ── 触发器匹配 ────────────────────────────────────────

    @classmethod
    def _matching_steps(
        cls,
        workflow: WorkflowDefV2,
        event: SystemEvent,
    ) -> list[int]:
        payload = dict(event.payload or {})
        hits: list[int] = []
        for index, step in enumerate(workflow.steps):
            trigger = step.trigger
            if not cls.type_matches(trigger.event_type, event.event_type):
                continue
            if not cls.eval_condition(trigger.condition, payload, event):
                continue
            hits.append(index)
        return hits

    @staticmethod
    def type_matches(trigger: str, actual: str) -> bool:
        """触发事件类型匹配：精确 → 去命名空间前缀 → ``fnmatch`` 通配。

        总线上的事件类型带命名空间前缀（``event.`` / ``task.``），而 YAML 里写的
        是人话（``security.monitor_result``）——两种写法都要能命中，否则写
        workflow 的人得先知道 EventBus 的内部约定。

        空触发器 → 永不命中（那是「只能手动跑」的 workflow，见模块 docstring）。
        """
        if not trigger:
            return False
        candidates = {actual}
        if "." in actual:
            candidates.add(actual.split(".", 1)[1])
        return any(fnmatch.fnmatchcase(candidate, trigger) for candidate in candidates)

    @staticmethod
    def eval_condition(
        expression: str,
        payload: dict[str, Any],
        event: SystemEvent | None = None,
    ) -> bool:
        """受限条件求值；表达式为空 = 通过。

        命名空间只有 ``payload`` / ``event`` / ``true`` / ``false``，``__builtins__``
        清空——YAML 是本地配置，但没理由给表达式开全局命名空间。求值出错按
        「不通过」处理：一条写错的条件不该把事件回调炸掉。
        """
        if not expression:
            return True
        severity = getattr(event, "severity", "") if event is not None else ""
        scope: dict[str, Any] = {
            "payload": payload or {},
            "event": {
                "event_type": getattr(event, "event_type", "") if event is not None else "",
                "source": getattr(event, "source", "") if event is not None else "",
                "severity": getattr(severity, "value", severity),
            },
            "true": True,
            "false": False,
        }
        try:
            return bool(eval(expression, {"__builtins__": {}}, scope))  # noqa: S307
        except Exception as exc:
            log.warning(
                "workflow_runtime.condition_error expression=%s error=%s",
                expression, exc,
            )
            return False

    # ── shell 处理器（红线：一律走 ToolGateway）────────────

    def _ensure_gateway(self) -> Any:
        """拿网关：daemon 注入的是共享实例，CLI 一次性执行时按 ``trm exec`` 口径自建。"""
        if self._gateway is None:
            from .audit_store import AuditStore
            from .tool_gateway import ToolGateway

            self._gateway = ToolGateway(
                interactive=False,
                audit_store=AuditStore(),
                event_bus=self._bus,
            )
        return self._gateway

    async def _handle_shell_node(
        self,
        wf_id: str,
        node: NodeDefinition,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """``agent_type: shell`` 节点：命令走 ToolGateway。

        ``instruction`` 整条当命令传给 dispatcher（``args=[command]``，dispatcher 会
        原样 join 回去）——shlex 拆分再拼会吃掉引号，``ssh host "systemctl restart x"``
        这种命令会被拆坏。

        网关拒绝或以非零退出结束 → 抛 ``TOOL_EXECUTION_FAILED``，节点状态是 FAILED。
        「跑失败」绝不能伪装成「跑成功」，否则 workflow 的终态会骗人。
        """
        command = str(node.config.get("instruction") or "").strip()
        if not command:
            raise TrimumError(
                TRMErrorCode.WORKFLOW_VALIDATION_FAILED,
                message=f"shell node '{node.id}' has no instruction (command to run)",
            )

        gateway = self._ensure_gateway()
        request = ExecuteRequest(
            tool=ToolType.SHELL,
            args=[command],
            agent_id=self._agent_id,
            timeout_seconds=node.timeout_seconds,
            source_type=self._source_type,
        )
        response = await gateway.execute(request)

        status = getattr(response, "status", "") or ""
        exit_code = getattr(response, "exit_code", 0)
        if status == "denied" or exit_code != 0:
            error = getattr(response, "error", "") or ""
            reason = getattr(response, "reason", "") or ""
            detail = " ".join(part for part in (error, reason) if part).strip()
            raise TrimumError(
                TRMErrorCode.TOOL_EXECUTION_FAILED,
                message=(
                    f"shell node '{node.id}' failed: {command!r} "
                    f"(status={status or 'unknown'}, exit={exit_code}) {detail}".strip()
                ),
                context={
                    "command": command,
                    "status": status,
                    "exit_code": exit_code,
                    "error": error,
                    "reason": reason,
                },
            )

        return {
            "success": True,
            "command": command,
            "status": status,
            "exit_code": exit_code,
            "output": getattr(response, "output", ""),
            "risk": str(getattr(getattr(response, "risk", ""), "value", getattr(response, "risk", ""))),
            "workflow_id": wf_id,
        }


__all__ = [
    "DEFAULT_MAX_RUNS",
    "NodeRunRecord",
    "REVIEW_AGENT",
    "RegisteredWorkflow",
    "SHELL_AGENT_ALIASES",
    "WorkflowRunRecord",
    "WorkflowRuntime",
    "workflow_enabled",
]
