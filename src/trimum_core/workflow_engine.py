"""Workflow Engine — DAG 执行器（节点/边/状态机）.

职责:
- 定义 Workflow / Node / Edge 数据结构 (Pydantic)
- DAG 拓扑排序 + 循环检测
- 节点状态机: pending → running → completed | failed | skipped
- 支持条件边 (condition) 和超时/重试
- 事件驱动: 每完成一个节点 emit event, 驱动下一个
"""

from __future__ import annotations

import asyncio
import time
import uuid
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

import yaml
from pathlib import Path

from .event_bus import EventBus
from .models import AgentTask


# ── 节点状态（Phase 3: Task State Machine）───────────────

class NodeStatus(str, Enum):
    """Task/节点状态机.

    Phase 3 扩展自 Warp 设计:
    CREATED  → QUEUED → DISPATCHING → RUNNING → COMPLETED | FAILED
                                                   → TIMEOUT | CANCELLED | BLOCKED
    """
    CREATED = "created"           # 任务已创建（初始状态）
    QUEUED = "queued"             # 任务已入队等待
    DISPATCHING = "dispatching"    # 正在分派给 Agent
    RUNNING = "running"           # Agent 正在执行
    COMPLETED = "completed"       # 执行成功
    FAILED = "failed"             # 执行失败
    SKIPPED = "skipped"           # 条件不满足跳过
    TIMEOUT = "timeout"           # 超时
    CANCELLED = "cancelled"       # 用户/系统取消
    BLOCKED = "blocked"           # 权限/资源阻塞


class WorkflowStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


# ── 数据结构 ──────────────────────────────────────────────

class NodeMode(str, Enum):
    """节点执行模式."""
    SEQUENTIAL = "sequential"     # 默认：顺序执行
    PARALLEL = "parallel"         # 并行组：同层节点同时执行
    FAN_OUT = "fan_out"           # 扇出：一个输入分发给多个子节点
    FAN_IN = "fan_in"             # 扇入：等待多个子节点完成后汇总


class NodeDefinition(BaseModel):
    """工作流中的单个节点定义.

    扩展:
    - mode: 执行模式
    - input_from: 从哪些前驱节点获取输入（默认取所有直接前驱）
    - input_map: 输入字段映射 {"本地字段": "前驱节点ID.输出字段"}
    - uses_tool: 直接调用的工具名（不走 Agent，纯 Tool 执行）
    """

    id: str
    label: str = ""
    handler: str = ""  # Agent capability 或 tool 名
    mode: NodeMode = NodeMode.SEQUENTIAL
    input_from: list[str] = Field(default_factory=list)  # 显式声明依赖哪些前驱
    input_map: dict[str, str] = Field(default_factory=dict)  # 输入映射
    uses_tool: str = ""  # 如 "shell.exec"、"file.read"，不走 Agent 直接调 Tool
    config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 120.0
    retry_count: int = 0
    retry_delay: float = 2.0


class EdgeCondition(BaseModel):
    """边的条件表达式."""

    type: str = "always"
    """条件类型: always / on_complete / on_fail / expression"""
    expression: str = ""


class EdgeDefinition(BaseModel):
    """工作流中的有向边."""

    source: str
    target: str
    condition: EdgeCondition = Field(default_factory=EdgeCondition)


class NodeRuntime(BaseModel):
    """节点的运行时状态."""

    id: str
    status: NodeStatus = NodeStatus.CREATED
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    outputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    """完整工作流定义 (可序列化为 YAML/JSON)."""

    id: str = ""
    name: str = ""
    description: str = ""
    nodes: list[NodeDefinition] = Field(default_factory=list)
    edges: list[EdgeDefinition] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowResult(BaseModel):
    """工作流执行结果."""

    workflow_id: str
    status: WorkflowStatus
    duration: float
    node_results: dict[str, NodeRuntime] = Field(default_factory=dict)


# ── 处理器类型 ────────────────────────────────────────────

NodeHandler = Callable[[str, NodeDefinition, dict[str, Any]], Awaitable[Any]]
"""节点处理器签名: (工作流ID, 节点定义, 上下文) → 任意结果."""


# ── DAG 执行器 ────────────────────────────────────────────

class WorkflowEngine:
    """DAG 工作流执行器.

    职责:
    - 接收 WorkflowDefinition → 校验 DAG → 拓扑排序
    - 按序/条件执行节点
    - 事件驱动: 每完成节点 emit system/workflow.* 和 task.node.*
    - 超时/重试/取消
    """

    def __init__(
        self,
        event_bus: EventBus,
        default_handler: Optional[NodeHandler] = None,
    ) -> None:
        self._bus = event_bus
        self._default_handler = default_handler
        self._handlers: dict[str, NodeHandler] = {}
        self._active_workflows: dict[str, asyncio.Task] = {}

    # ── 处理器注册 ────────────────────────────────────────

    def register_handler(self, name: str, handler: NodeHandler) -> None:
        self._handlers[name] = handler

    def set_default_handler(self, handler: NodeHandler) -> None:
        self._default_handler = handler

    async def _resolve_handler(self, node: NodeDefinition) -> NodeHandler:
        if node.handler and node.handler in self._handlers:
            return self._handlers[node.handler]
        if node.handler and "." in node.handler:
            provider, action = node.handler.split(".", 1)
            key = f"{provider}.{action}"
            if key in self._handlers:
                return self._handlers[key]
        if self._default_handler:
            return self._default_handler
        raise RuntimeError(f"没有处理器能处理节点 '{node.id}' (handler={node.handler})")

    # ── DAG 校验 ──────────────────────────────────────────

    @staticmethod
    def validate_dag(workflow: WorkflowDefinition) -> None:
        """校验 DAG: 节点存在性 + 无环."""
        node_ids = {n.id for n in workflow.nodes}

        for edge in workflow.edges:
            if edge.source not in node_ids:
                raise ValueError(f"边引用不存在的源节点: {edge.source}")
            if edge.target not in node_ids:
                raise ValueError(f"边引用不存在的目标节点: {edge.target}")

        # Kahn 拓扑排序 + 环检测
        in_degree: dict[str, int] = {n.id: 0 for n in workflow.nodes}
        adj: dict[str, list[str]] = {n.id: [] for n in workflow.nodes}

        for edge in workflow.edges:
            adj[edge.source].append(edge.target)
            in_degree[edge.target] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited = 0

        while queue:
            nid = queue.pop(0)
            visited += 1
            for neighbor in adj[nid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(workflow.nodes):
            raise ValueError("DAG 中存在环")

    @staticmethod
    def topological_sort(workflow: WorkflowDefinition) -> list[str]:
        """返回拓扑排序后的节点 ID 列表."""
        in_degree: dict[str, int] = {n.id: 0 for n in workflow.nodes}
        adj: dict[str, list[str]] = {n.id: [] for n in workflow.nodes}

        for edge in workflow.edges:
            adj[edge.source].append(edge.target)
            in_degree[edge.target] += 1

        predecessors: dict[str, list[str]] = {n.id: [] for n in workflow.nodes}
        for edge in workflow.edges:
            predecessors[edge.target].append(edge.source)

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            queue.sort()
            nid = queue.pop(0)
            result.append(nid)
            for neighbor in adj[nid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    # ── 条件评估 ──────────────────────────────────────────

    @staticmethod
    def _evaluate_condition(
        condition: EdgeCondition,
        source_runtime: NodeRuntime,
    ) -> tuple[bool, str]:
        """评估边条件是否满足. 返回 (通过?, 原因)."""
        if condition.type == "always":
            return True, ""
        if condition.type == "on_complete":
            return source_runtime.status == NodeStatus.COMPLETED, "source_not_completed"
        if condition.type == "on_fail":
            return source_runtime.status in (NodeStatus.FAILED, NodeStatus.TIMEOUT), "source_not_failed"
        if condition.type == "expression":
            try:
                # 简单 eval, 节点结果在 source_runtime.result 中
                ctx = {"result": source_runtime.result, "status": source_runtime.status.value}
                outcome = bool(eval(condition.expression, {"__builtins__": {}}, ctx))
                return outcome, f"expression_false: {condition.expression}" if not outcome else ""
            except Exception as e:
                return False, f"eval_error: {e}"
        return True, ""

    # ── 执行入口 ──────────────────────────────────────────

    async def run(
        self,
        workflow: WorkflowDefinition,
        context: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> WorkflowResult:
        """执行完整工作流.

        返回 WorkflowResult (非阻塞).
        """
        self.validate_dag(workflow)

        workflow_id = workflow.id or f"wf-{uuid.uuid4().hex[:12]}"
        context = context or {}
        cancel = cancel_event or asyncio.Event()

        node_runtimes: dict[str, NodeRuntime] = {
            n.id: NodeRuntime(id=n.id, status=NodeStatus.CREATED) for n in workflow.nodes
        }
        node_map: dict[str, NodeDefinition] = {n.id: n for n in workflow.nodes}
        edge_to_target: dict[str, list[EdgeDefinition]] = {n.id: [] for n in workflow.nodes}
        predecessors: dict[str, list[str]] = {n.id: [] for n in workflow.nodes}

        for edge in workflow.edges:
            edge_to_target.setdefault(edge.target, []).append(edge)
            predecessors[edge.target].append(edge.source)

        topo_order = self.topological_sort(workflow)
        started_at = time.time()

        # 初始状态: 所有节点 CREATED，入队前切换为 QUEUED
        for n in workflow.nodes:
            await self._bus.emit_task("node.created", {
                "workflow_id": workflow_id, "node_id": n.id,
                "label": n.label, "handler": n.handler,
            })

        await self._bus.emit_task("workflow.started", {
            "workflow_id": workflow_id,
            "name": workflow.name,
            "node_count": len(workflow.nodes),
        })

        result = await self._execute_dag(
            workflow_id=workflow_id,
            node_map=node_map,
            node_runtimes=node_runtimes,
            edge_to_target=edge_to_target,
            predecessors=predecessors,
            topo_order=topo_order,
            context=context,
            cancel=cancel,
            started_at=started_at,
        )
        return result

    async def _execute_dag(
        self,
        workflow_id: str,
        node_map: dict[str, NodeDefinition],
        node_runtimes: dict[str, NodeRuntime],
        edge_to_target: dict[str, list[EdgeDefinition]],
        predecessors: dict[str, list[str]],
        topo_order: list[str],
        context: dict[str, Any],
        cancel: asyncio.Event,
        started_at: float,
    ) -> WorkflowResult:
        completed_nodes: set[str] = set()
        workflow_status = WorkflowStatus.RUNNING

        # 初始入队: 无前驱的节点 QUEUED
        ready_queue: list[str] = []
        for nid in topo_order:
            if not predecessors[nid]:
                node_runtimes[nid].status = NodeStatus.QUEUED
                await self._bus.emit_task("node.queued", {
                    "workflow_id": workflow_id, "node_id": nid,
                })
                ready_queue.append(nid)

        while ready_queue and not cancel.is_set():
            # ── 识别并行组 ──
            # 从 ready_queue 头部取出所有 mode=parallel 的节点组成并行组
            # 如果第一个节点就是 parallel, 取连续的所有 ready+
            parallel_group: list[str] = []
            while ready_queue and node_map[ready_queue[0]].mode == NodeMode.PARALLEL:
                nid = ready_queue.pop(0)
                if self._is_node_ready(nid, predecessors, node_runtimes):
                    parallel_group.append(nid)

            if parallel_group:
                # DISPATCHING 信号
                for nid in parallel_group:
                    node_runtimes[nid].status = NodeStatus.DISPATCHING
                    await self._bus.emit_task("node.dispatching", {
                        "workflow_id": workflow_id, "node_id": nid,
                    })

                # 并行执行全部就绪节点
                tasks = {
                    nid: asyncio.create_task(
                        self._execute_single_node(
                            workflow_id, nid, node_map, node_runtimes,
                            predecessors, edge_to_target, context, cancel,
                        )
                    )
                    for nid in parallel_group
                }
                await asyncio.gather(*tasks.values(), return_exceptions=True)

                for nid in parallel_group:
                    completed_nodes.add(nid)
                    await self._add_ready_successors(
                        nid, ready_queue, completed_nodes,
                        edge_to_target, predecessors, node_runtimes,
                        workflow_id=workflow_id,
                    )
                continue

            # ── 单个顺序节点 ──
            nid = ready_queue.pop(0)
            runtime = node_runtimes[nid]
            if not self._is_node_ready(nid, predecessors, node_runtimes):
                # 前驱未完成 → BLOCKED（资源/条件阻塞）
                runtime.status = NodeStatus.BLOCKED
                await self._bus.emit_task("node.blocked", {
                    "workflow_id": workflow_id, "node_id": nid,
                    "reason": "predecessors_not_complete",
                }, severity="warning")
                completed_nodes.add(nid)
                await self._add_ready_successors(nid, ready_queue, completed_nodes,
                                                 edge_to_target, predecessors, node_runtimes,
                                                 workflow_id=workflow_id)
                continue

            # DISPATCHING → RUNNING
            runtime.status = NodeStatus.DISPATCHING
            await self._bus.emit_task("node.dispatching", {
                "workflow_id": workflow_id, "node_id": nid,
            })

            await self._execute_single_node(
                workflow_id, nid, node_map, node_runtimes,
                predecessors, edge_to_target, context, cancel,
            )
            completed_nodes.add(nid)
            await self._add_ready_successors(
                nid, ready_queue, completed_nodes,
                edge_to_target, predecessors, node_runtimes,
                workflow_id=workflow_id,
            )

            if cancel.is_set():
                workflow_status = WorkflowStatus.CANCELLED
                break

        # ── 最终状态判定 ──
        if cancel.is_set():
            workflow_status = WorkflowStatus.CANCELLED
        else:
            terminal_ok = {NodeStatus.COMPLETED, NodeStatus.SKIPPED}
            terminal_fail = {NodeStatus.FAILED, NodeStatus.TIMEOUT, NodeStatus.CANCELLED, NodeStatus.BLOCKED}
            all_terminal = all(
                rt.status in terminal_ok | terminal_fail
                for rt in node_runtimes.values()
            )
            any_failed = any(rt.status in terminal_fail for rt in node_runtimes.values())
            any_blocked = any(rt.status == NodeStatus.BLOCKED for rt in node_runtimes.values())

            if any_blocked:
                workflow_status = WorkflowStatus.BLOCKED
            elif any_failed:
                workflow_status = WorkflowStatus.FAILED
            elif all_terminal:
                workflow_status = WorkflowStatus.COMPLETED
            else:
                workflow_status = WorkflowStatus.RUNNING

        duration = time.time() - started_at

        await self._bus.emit_task("workflow.completed", {
            "workflow_id": workflow_id,
            "status": workflow_status.value,
            "duration": duration,
            "node_count": len(node_runtimes),
            "created": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.CREATED),
            "queued": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.QUEUED),
            "dispatching": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.DISPATCHING),
            "running": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.RUNNING),
            "completed": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.COMPLETED),
            "failed": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.FAILED),
            "skipped": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.SKIPPED),
            "timeout": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.TIMEOUT),
            "cancelled": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.CANCELLED),
            "blocked": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.BLOCKED),
        })

        return WorkflowResult(
            workflow_id=workflow_id,
            status=workflow_status,
            duration=duration,
            node_results=node_runtimes,
        )

    # ── 单节点执行 ────────────────────────────────────────

    async def _execute_single_node(
        self,
        workflow_id: str,
        nid: str,
        node_map: dict[str, NodeDefinition],
        node_runtimes: dict[str, NodeRuntime],
        predecessors: dict[str, list[str]],
        edge_to_target: dict[str, list[EdgeDefinition]],
        context: dict[str, Any],
        cancel: asyncio.Event,
    ) -> None:
        """执行单个节点（含条件检查、输入聚合、超时/重试）。

        Node 状态机 transform（由 caller 设置 DISPATCHING 后调用）:
        DISPATCHING → RUNNING → COMPLETED | FAILED | TIMEOUT | CANCELLED
        """
        node = node_map[nid]
        runtime = node_runtimes[nid]

        # ── 检查取消信号 ──
        if cancel.is_set():
            runtime.status = NodeStatus.CANCELLED
            runtime.completed_at = time.time()
            await self._bus.emit_task("node.cancelled", {
                "workflow_id": workflow_id, "node_id": nid,
                "reason": "workflow_cancelled",
            }, severity="warning")
            return

        # ── 检查入边条件 ──
        edges_into = edge_to_target.get(nid, [])
        for edge in edges_into:
            pred_runtime = node_runtimes.get(edge.source)
            if not pred_runtime:
                continue
            ok, reason = self._evaluate_condition(edge.condition, pred_runtime)
            if not ok:
                if pred_runtime.status in (NodeStatus.CANCELLED, NodeStatus.BLOCKED):
                    runtime.status = NodeStatus.BLOCKED
                    await self._bus.emit_task("node.blocked", {
                        "workflow_id": workflow_id, "node_id": nid, "reason": reason,
                    }, severity="warning")
                else:
                    runtime.status = NodeStatus.SKIPPED
                    await self._bus.emit_task("node.skipped", {
                        "workflow_id": workflow_id, "node_id": nid, "reason": reason,
                    })
                return

        # ── 聚合前驱输入 ──
        merged_input = self._merge_node_input(nid, node, predecessors, node_runtimes)
        if merged_input:
            context["_input"] = merged_input

        # ── 执行 ──
        runtime.status = NodeStatus.RUNNING
        runtime.started_at = time.time()

        await self._bus.emit_task("node.started", {
            "workflow_id": workflow_id, "node_id": nid,
            "node_label": node.label,
        })

        try:
            handler = await self._resolve_handler(node)
            result = await asyncio.wait_for(
                handler(workflow_id, node, context),
                timeout=node.timeout_seconds,
            )

            runtime.status = NodeStatus.COMPLETED
            runtime.result = result
            runtime.completed_at = time.time()
            runtime.attempts += 1

            # 结构化输出：存入 outputs 供下游消费
            if isinstance(result, dict):
                runtime.outputs.update(result)

            await self._bus.emit_task("node.completed", {
                "workflow_id": workflow_id, "node_id": nid,
                "duration": runtime.completed_at - runtime.started_at,
                "result_summary": str(result)[:200],
            })

        except asyncio.TimeoutError:
            runtime.status = NodeStatus.TIMEOUT
            runtime.error = f"timeout {node.timeout_seconds}s"
            runtime.completed_at = time.time()
            await self._bus.emit_task("node.timeout", {
                "workflow_id": workflow_id, "node_id": nid,
                "timeout": node.timeout_seconds,
            }, severity="warning")
            if runtime.attempts < node.retry_count:
                await asyncio.sleep(node.retry_delay)

        except asyncio.CancelledError:
            runtime.status = NodeStatus.CANCELLED
            runtime.completed_at = time.time()
            await self._bus.emit_task("node.cancelled", {
                "workflow_id": workflow_id, "node_id": nid,
                "reason": "task_cancelled",
            }, severity="warning")

        except Exception as e:
            runtime.status = NodeStatus.FAILED
            runtime.error = str(e)
            runtime.completed_at = time.time()
            runtime.attempts += 1

            await self._bus.emit_task("node.failed", {
                "workflow_id": workflow_id, "node_id": nid,
                "error": str(e), "attempt": runtime.attempts,
            }, severity="warning")
            if runtime.attempts <= node.retry_count:
                await asyncio.sleep(node.retry_delay)

    # ── 输入聚合 ──────────────────────────────────────────

    def _merge_node_input(
        self,
        nid: str,
        node: NodeDefinition,
        predecessors: dict[str, list[str]],
        runtimes: dict[str, NodeRuntime],
    ) -> dict[str, Any]:
        """聚合前驱节点输出作为本节点输入.

        策略:
        1. 如果 node.input_from 为空, 取所有直接前驱的 outputs
        2. 如果 node.input_map 有映射, 按映射选取
        3. 每个前驱的输出以 {前驱ID: {输出}} 形式合并
        """
        merged: dict[str, Any] = {}

        source_ids = node.input_from or predecessors.get(nid, [])
        if not source_ids:
            return {}

        for sid in source_ids:
            sr = runtimes.get(sid)
            if sr is None or sr.status not in (NodeStatus.COMPLETED, NodeStatus.SKIPPED):
                continue
            if sr.outputs:
                if node.input_map:
                    # input_map: {"本地字段": "前驱ID.输出字段"}
                    for local_key, remote_ref in node.input_map.items():
                        parts = remote_ref.split(".", 1)
                        if parts[0] == sid and len(parts) > 1:
                            merged[local_key] = sr.outputs.get(parts[1])
                        elif parts[0] == sid:
                            merged[local_key] = sr.result
                else:
                    # 默认: 以 {前驱ID: 全部输出} 合并
                    merged[sid] = dict(sr.outputs) if sr.outputs else sr.result

        return merged

    @staticmethod
    def _is_node_ready(
        nid: str,
        predecessors: dict[str, list[str]],
        runtimes: dict[str, NodeRuntime],
    ) -> bool:
        """检查节点的所有前驱是否都已就绪."""
        preds = predecessors.get(nid, [])
        if not preds:
            return True
        return all(
            runtimes[p].status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
            for p in preds
        )

    async def _add_ready_successors(
        self,
        nid: str,
        ready_queue: list[str],
        completed: set[str],
        edge_to_target: dict[str, list[EdgeDefinition]],
        predecessors: dict[str, list[str]],
        runtimes: dict[str, NodeRuntime],
        workflow_id: str = "",
    ) -> None:
        """当 nid 完成后, 检查其后继是否已全部就绪并标记 QUEUED."""
        for successor_nid, preds in predecessors.items():
            if successor_nid in completed or successor_nid in ready_queue:
                continue
            all_preds_done = all(
                runtimes[p].status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
                for p in preds
            )
            if all_preds_done and successor_nid not in ready_queue and successor_nid not in completed:
                # 后继所有前驱已就绪 → QUEUED
                if successor_nid in runtimes and runtimes[successor_nid].status == NodeStatus.CREATED:
                    runtimes[successor_nid].status = NodeStatus.QUEUED
                    if workflow_id:
                        await self._bus.emit_task("node.queued", {
                            "workflow_id": workflow_id, "node_id": successor_nid,
                        })
                ready_queue.append(successor_nid)

    # ── TARL Workflow Matching ───────────────────────────

    def register_tarl_workflow(
        self,
        tarl_pattern: str,
        workflow: WorkflowDefinition,
    ) -> None:
        """Register a workflow to be matched by TARL key-value pattern.

        The *tarl_pattern* is a TARL line defining which keys must match
        for the workflow to fire.  Keys support exact match or prefix
        matching via trailing ``.*``.

        Examples::

            # Exact cmd match
            register_tarl_workflow("cmd:restart_nginx", restart_wf)

            # Prefix match: any cmd starting with "blog_"
            register_tarl_workflow("cmd.*", blog_wf)

            # Multi-key match
            register_tarl_workflow("cmd:deploy target:blog", deploy_wf)
        """
        if not hasattr(self, "_tarl_workflows"):
            self._tarl_workflows: list[tuple[dict[str, str | None], WorkflowDefinition]] = []

        # Parse the TARL pattern into {key: value_or_None} dict
        #   None  = prefix match (key.*)
        #   str   = exact value match
        from .tarl_parser import parse_line

        parsed = parse_line(tarl_pattern)
        rules: dict[str, str | None] = {}
        from .tarl_parser import extract_prefix

        for key, value in parsed.items():
            if key.endswith(".*"):
                rules[key[:-2]] = None  # prefix match
            else:
                rules[key] = value
        self._tarl_workflows.append((rules, workflow))

    def match_workflow_by_tarl(self, tarl_line: str) -> WorkflowDefinition | None:
        """Match a TARL line against registered workflows using KV prefix index.

        Returns the best-matching WorkflowDefinition or ``None``.

        Matching rules:
        1. All keys in the registered pattern must be present in *tarl_line*
        2. Exact-value keys must match exactly
        3. Prefix-match keys (value=None) match if key prefix exists
        4. If multiple workflows match, the one with the most keys wins
           (most specific match)
        """
        if not hasattr(self, "_tarl_workflows") or not self._tarl_workflows:
            return None

        from .tarl_parser import extract_prefix, parse_line

        line_kvs = parse_line(tarl_line)
        best_match: tuple[int, WorkflowDefinition | None] = (0, None)

        for rules, workflow in self._tarl_workflows:
            matched_keys = 0
            all_match = True

            for key, expected_value in rules.items():
                if expected_value is None:
                    # Prefix match: key.* → check if any key starts with key
                    found = extract_prefix(tarl_line, key)
                    if not found:
                        all_match = False
                        break
                    matched_keys += 1
                else:
                    # Exact match
                    if line_kvs.get(key) == expected_value:
                        matched_keys += 1
                    else:
                        all_match = False
                        break

            if all_match and matched_keys > best_match[0]:
                best_match = (matched_keys, workflow)

        return best_match[1]


# ===================================================================
# Phase 3: WorkflowStep — 新格式（监听器→执行组）
# ===================================================================


class WorkflowStepCondition(BaseModel):
    """Step 触发条件."""
    event_type: str = ""
    condition: str = ""  # 可选的条件表达式


class WorkflowStep(BaseModel):
    """工作流步骤：监听器 + 执行组.

    格式:
    - trigger: 监听什么事件
    - execute: 触发后执行哪些 AgentTask
    """
    trigger: WorkflowStepCondition = Field(default_factory=WorkflowStepCondition)
    execute: list[AgentTask] = Field(default_factory=list)


class WorkflowDefV2(BaseModel):
    """Phase 3 新版工作流定义 (监听器→执行组).

    兼容旧版 WorkflowDefinition (Node/Edge)，但提供新格式.
    """
    id: str = ""
    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # 文件化加载
    # ------------------------------------------------------------------

    @staticmethod
    def load_yaml(path: str | Path) -> "WorkflowDefV2":
        """从 YAML 文件加载 WorkflowDefV2。

        YAML 格式示例（与 Pydantic 字段一一对应）：

        .. code-block:: yaml

            id: blog-deploy
            name: 博客部署
            description: Git push → SSH restart → Health check
            steps:
              - trigger:
                  event_type: workflow.request
                  condition: 'payload.get("action") == "deploy"'
                execute:
                  - agent_type: shell
                    instruction: git push origin main
                    timeout_seconds: 30
                  - agent_type: shell
                    instruction: ssh root@server "systemctl restart blog"
                    timeout_seconds: 10
            config:
              notify_on_failure: true
        """
        with open(str(path), encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid workflow YAML: {path}")
        return WorkflowDefV2(**data)

    @staticmethod
    def load_from_dir(base_path: str | None = None) -> list["WorkflowDefV2"]:
        """扫描目录并加载所有 workflow.yaml / workflow.yml 文件。

        目录结构:
          <base_path>/<name>/workflow.yaml
          <base_path>/<name>/workflow.yml

        Returns:
            加载成功的 WorkflowDefV2 列表。加载失败的会打印警告但不会中断。
        """
        if base_path is None:
            base_path = str(Path.home() / ".trimum" / "workflows")

        workflows_dir = Path(base_path)
        if not workflows_dir.is_dir():
            return []

        result: list[WorkflowDefV2] = []
        for entry in sorted(workflows_dir.iterdir()):
            if not entry.is_dir():
                continue
            for yml_name in ("workflow.yaml", "workflow.yml"):
                yml_path = entry / yml_name
                if yml_path.is_file():
                    try:
                        wf = WorkflowDefV2.load_yaml(yml_path)
                        if not wf.id:
                            wf.id = entry.name
                        result.append(wf)
                    except Exception as e:
                        import logging
                        logging.getLogger("trimum_core.workflow_engine").warning(
                            "Failed to load workflow from %s: %s", yml_path, e
                        )
                    break  # 只加载第一个找到的

        return result
        """Convert v2 format to classic Node/Edge WorkflowDefinition.

        Each step becomes a node. Steps execute sequentially.
        """
        nodes: list[NodeDefinition] = []
        edges: list[EdgeDefinition] = []
        prev_id: str | None = None

        for i, step in enumerate(self.steps):
            for j, task in enumerate(step.execute):
                node_id = f"step_{i}_task_{j}"
                nodes.append(NodeDefinition(
                    id=node_id,
                    label=f"{step.trigger.event_type}:{task.agent_type}",
                    handler=task.agent_type,
                    config=task.config,
                    timeout_seconds=task.timeout_seconds,
                ))
                if prev_id:
                    edges.append(EdgeDefinition(
                        source=prev_id,
                        target=node_id,
                    ))
                prev_id = node_id

        return WorkflowDefinition(
            id=self.id,
            name=self.name,
            description=self.description,
            nodes=nodes,
            edges=edges,
            config=self.config,
        )

    
    def to_workflow_definition(self) -> "WorkflowDefinition":
        """Convert v2 format to classic Node/Edge WorkflowDefinition.
        Each step becomes a node. Steps execute sequentially.
        """
        from .workflow_engine import WorkflowDefinition, NodeDefinition, EdgeDefinition
        nodes: list[NodeDefinition] = []
        edges: list[EdgeDefinition] = []
        prev_id: str | None = None
        for i, step in enumerate(self.steps):
            for j, task in enumerate(step.execute):
                node_id = f"step_{i}_task_{j}"
                nodes.append(NodeDefinition(
                    id=node_id,
                    label=f"{step.trigger.event_type}:{task.agent_type}",
                    handler=task.agent_type,
                    config=task.config,
                    timeout_seconds=task.timeout_seconds,
                ))
                if prev_id:
                    edges.append(EdgeDefinition(source=prev_id, target=node_id))
                prev_id = node_id
        return WorkflowDefinition(
            id=self.id, name=self.name, description=self.description,
            nodes=nodes, edges=edges, config=self.config,
        )
async def start_v2(
        self,
        engine: "WorkflowEngine",
        context: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Start workflow in v2 mode: listen for triggers, dispatch tasks.

        For each step:
        1. Listen for trigger event on Event Bus
        2. When trigger fires, evaluate condition
        3. Execute all AgentTasks in the execute group (via Event Bus)
        4. Wait for completion before moving to next step
        """
        workflow_id = self.id or f"wf-v2-{uuid.uuid4().hex[:12]}"
        context = context or {}

        for i, step in enumerate(self.steps):
            # Listen for trigger event
            trigger_queue: asyncio.Queue = asyncio.Queue()

            async def _trigger_callback(event):
                if step.trigger.event_type and event.event_type != step.trigger.event_type:
                    return
                if step.trigger.condition:
                    ctx = {"payload": event.payload}
                    try:
                        if not eval(step.trigger.condition, {"__builtins__": {}}, ctx):
                            return
                    except Exception:
                        return
                await trigger_queue.put(event)

            engine._bus.subscribe("*", _trigger_callback)

            # Wait for trigger
            await trigger_queue.get()

            # Dispatch all tasks in the execute group
            for task in step.execute:
                task.workflow_id = workflow_id
                task.task_id = f"{workflow_id}_step_{i}_{task.agent_type}"

                # Publish task to Event Bus (Agent Runtime listens)
                await engine._bus.emit_event(
                    event_type="task.assigned",
                    source=f"workflow:{workflow_id}",
                    payload=task.model_dump(),
                )

            engine._bus.unsubscribe("*", _trigger_callback)

        return WorkflowResult(
            workflow_id=workflow_id,
            status=WorkflowStatus.COMPLETED,
            duration=0.0,
        )
