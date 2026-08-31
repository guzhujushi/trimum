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

from .event_bus import EventBus


# ── 节点状态 ──────────────────────────────────────────────

class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── 数据结构 ──────────────────────────────────────────────

class NodeDefinition(BaseModel):
    """工作流中的单个节点定义."""

    id: str
    label: str = ""
    handler: str = ""
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
    status: NodeStatus = NodeStatus.PENDING
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
            n.id: NodeRuntime(id=n.id) for n in workflow.nodes
        }
        node_map: dict[str, NodeDefinition] = {n.id: n for n in workflow.nodes}
        edge_to_target: dict[str, list[EdgeDefinition]] = {n.id: [] for n in workflow.nodes}
        predecessors: dict[str, list[str]] = {n.id: [] for n in workflow.nodes}

        for edge in workflow.edges:
            edge_to_target.setdefault(edge.target, []).append(edge)
            predecessors[edge.target].append(edge.source)

        topo_order = self.topological_sort(workflow)
        started_at = time.time()

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

        ready_queue: list[str] = [
            nid for nid in topo_order if not predecessors[nid]
        ]

        while ready_queue and not cancel.is_set():
            nid = ready_queue.pop(0)
            node = node_map[nid]
            runtime = node_runtimes[nid]

            # ── 检查前驱是否都完成 ──
            all_pred_done = all(
                node_runtimes[pred].status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
                for pred in predecessors[nid]
            )
            if not all_pred_done:
                runtime.status = NodeStatus.SKIPPED
                await self._bus.emit_task("node.skipped", {
                    "workflow_id": workflow_id, "node_id": nid,
                    "reason": "predecessors_not_complete",
                })
                completed_nodes.add(nid)
                self._add_ready_successors(nid, ready_queue, completed_nodes,
                                           edge_to_target, predecessors, node_runtimes)
                continue

            # ── 检查入边条件 ──
            edges_into = edge_to_target.get(nid, [])
            should_skip = False
            skip_reason = ""
            for edge in edges_into:
                pred_runtime = node_runtimes.get(edge.source)
                if not pred_runtime:
                    continue
                ok, reason = self._evaluate_condition(edge.condition, pred_runtime)
                if not ok:
                    should_skip = True
                    skip_reason = reason
                    break

            if should_skip:
                runtime.status = NodeStatus.SKIPPED
                await self._bus.emit_task("node.skipped", {
                    "workflow_id": workflow_id, "node_id": nid,
                    "reason": skip_reason,
                })
                completed_nodes.add(nid)
                self._add_ready_successors(nid, ready_queue, completed_nodes,
                                           edge_to_target, predecessors, node_runtimes)
                continue

            # ── 执行节点 ──
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

                await self._bus.emit_task("node.completed", {
                    "workflow_id": workflow_id, "node_id": nid,
                    "duration": runtime.completed_at - runtime.started_at,
                    "result_summary": str(result)[:200],
                })

                completed_nodes.add(nid)
                self._add_ready_successors(nid, ready_queue, completed_nodes,
                                           edge_to_target, predecessors, node_runtimes)

            except asyncio.TimeoutError:
                runtime.status = NodeStatus.TIMEOUT
                runtime.error = f"超时 {node.timeout_seconds}s"
                await self._bus.emit_task("node.timeout", {
                    "workflow_id": workflow_id, "node_id": nid,
                    "timeout": node.timeout_seconds,
                })
                if runtime.attempts < node.retry_count:
                    await asyncio.sleep(node.retry_delay)
                    ready_queue.insert(0, nid)
                else:
                    completed_nodes.add(nid)
                    self._add_ready_successors(nid, ready_queue, completed_nodes,
                                               edge_to_target, predecessors, node_runtimes)

            except Exception as e:
                runtime.status = NodeStatus.FAILED
                runtime.error = str(e)
                runtime.completed_at = time.time()
                runtime.attempts += 1

                await self._bus.emit_task("node.failed", {
                    "workflow_id": workflow_id, "node_id": nid,
                    "error": str(e), "attempt": runtime.attempts,
                })
                if runtime.attempts <= node.retry_count:
                    await asyncio.sleep(node.retry_delay)
                    ready_queue.insert(0, nid)
                else:
                    completed_nodes.add(nid)
                    self._add_ready_successors(nid, ready_queue, completed_nodes,
                                               edge_to_target, predecessors, node_runtimes)

            if cancel.is_set():
                workflow_status = WorkflowStatus.CANCELLED
                break

        # ── 最终状态判定 ──
        if cancel.is_set():
            workflow_status = WorkflowStatus.CANCELLED
        else:
            all_done = all(
                rt.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
                for rt in node_runtimes.values()
            )
            any_failed = any(rt.status == NodeStatus.FAILED for rt in node_runtimes.values())
            workflow_status = WorkflowStatus.FAILED if any_failed else (
                WorkflowStatus.COMPLETED if all_done else WorkflowStatus.COMPLETED
            )

        duration = time.time() - started_at

        await self._bus.emit_task("workflow.completed", {
            "workflow_id": workflow_id,
            "status": workflow_status.value,
            "duration": duration,
            "node_count": len(node_runtimes),
            "completed": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.COMPLETED),
            "failed": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.FAILED),
            "skipped": sum(1 for rt in node_runtimes.values() if rt.status == NodeStatus.SKIPPED),
        })

        return WorkflowResult(
            workflow_id=workflow_id,
            status=workflow_status,
            duration=duration,
            node_results=node_runtimes,
        )

    @staticmethod
    def _add_ready_successors(
        nid: str,
        ready_queue: list[str],
        completed: set[str],
        edge_to_target: dict[str, list[EdgeDefinition]],
        predecessors: dict[str, list[str]],
        runtimes: dict[str, NodeRuntime],
    ) -> None:
        """当 nid 完成后, 检查其后继是否已全部就绪."""
        for successor_nid, preds in predecessors.items():
            if successor_nid in completed or successor_nid in ready_queue:
                continue
            # 检查 successor 的所有前驱是否已完成
            all_preds_done = all(
                runtimes[p].status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
                for p in preds
            )
            if all_preds_done and successor_nid not in ready_queue and successor_nid not in completed:
                ready_queue.append(successor_nid)