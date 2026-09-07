"""Memory Bridge — 将 Event Bus 事件桥接到 ContextManager。

MemoryBridge 监听 Event Bus 上的 memory.* 事件，转换为 ContextManager 的 CRUD 调用。
这样 Agent 不需要直接 import ContextManager，只需通过 Event Bus 发布事件即可操作记忆。

三层命名空间：
- agent_memory — Agent 私有（自己读写不需确认）
- project_ctx  — 项目共享（读需弹窗确认）
- global_ctx   — Planner 全局长期记忆
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .event_bus import EventBus
from .context_manager import ContextManager

log = logging.getLogger("trimum_core.memory_bridge")


class MemoryBridge:
    """桥接 Event Bus ↔ ContextManager。

    订阅 memory.* 事件，自动路由到 ContextManager 对应方法。
    结果通过 Event Bus 回复（如果事件包含 reply_topic 字段）。

    用法:
        from trimum_core.memory_bridge import MemoryBridge
        bridge = MemoryBridge(event_bus, context_manager)
        await bridge.start()
    """

    def __init__(
        self,
        event_bus: EventBus,
        context_manager: ContextManager,
    ) -> None:
        self._bus = event_bus
        self._cm = context_manager

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """订阅所有 memory.* 事件。"""
        # 订阅 memory.* 事件（含 event. 前缀，因为 emit_event 会加 NAMESPACE_EVENT）
        prefix = "event.memory"
        self._bus.subscribe(f"{prefix}.agent.set", self._on_agent_set)
        self._bus.subscribe(f"{prefix}.agent.get", self._on_agent_get)
        self._bus.subscribe(f"{prefix}.agent.delete", self._on_agent_delete)
        self._bus.subscribe(f"{prefix}.agent.clear", self._on_agent_clear)
        self._bus.subscribe(f"{prefix}.project.set", self._on_project_set)
        self._bus.subscribe(f"{prefix}.project.get", self._on_project_get)
        self._bus.subscribe(f"{prefix}.project.list", self._on_project_list)
        self._bus.subscribe(f"{prefix}.global.set", self._on_global_set)
        self._bus.subscribe(f"{prefix}.global.get", self._on_global_get)
        self._bus.subscribe(f"{prefix}.global.list", self._on_global_list)
        self._bus.subscribe(f"{prefix}.global.delete", self._on_global_delete)
        self._bus.subscribe(f"{prefix}.search", self._on_search)
        log.info("MemoryBridge started")

    async def stop(self) -> None:
        """取消所有订阅。"""
        prefix = "event.memory"
        self._bus.unsubscribe(f"{prefix}.agent.set", self._on_agent_set)
        self._bus.unsubscribe(f"{prefix}.agent.get", self._on_agent_get)
        self._bus.unsubscribe(f"{prefix}.agent.delete", self._on_agent_delete)
        self._bus.unsubscribe(f"{prefix}.agent.clear", self._on_agent_clear)
        self._bus.unsubscribe(f"{prefix}.project.set", self._on_project_set)
        self._bus.unsubscribe(f"{prefix}.project.get", self._on_project_get)
        self._bus.unsubscribe(f"{prefix}.project.list", self._on_project_list)
        self._bus.unsubscribe(f"{prefix}.global.set", self._on_global_set)
        self._bus.unsubscribe(f"{prefix}.global.get", self._on_global_get)
        self._bus.unsubscribe(f"{prefix}.global.list", self._on_global_list)
        self._bus.unsubscribe(f"{prefix}.global.delete", self._on_global_delete)
        self._bus.unsubscribe(f"{prefix}.search", self._on_search)
        log.info("MemoryBridge stopped")

    # ------------------------------------------------------------------
    # Helper: 回复事件
    # ------------------------------------------------------------------

    async def _reply(self, source_event, result: Any) -> None:
        """如果有 reply_topic，将结果发回。"""
        payload = source_event.payload or {}
        reply_topic = payload.get("reply_topic")
        if reply_topic:
            await self._bus.emit_event(
                reply_topic,
                "memory_bridge",
                {"result": result, "request_id": payload.get("request_id")},
            )

    # ------------------------------------------------------------------
    # Agent 私有记忆
    # ------------------------------------------------------------------

    async def _on_agent_set(self, event) -> None:
        """memory.agent.set → ContextManager.set(namespace=agent_memory)"""
        p = event.payload or {}
        agent_id = p.get("agent_id", "unknown")
        key = p.get("key", "")
        value = p.get("value", "")
        ttl = p.get("ttl_seconds")
        await self._cm.set(agent_id, key, value, namespace="agent_memory", ttl_seconds=ttl)
        await self._reply(event, {"status": "ok"})

    async def _on_agent_get(self, event) -> None:
        """memory.agent.get → ContextManager.get(namespace=agent_memory)"""
        p = event.payload or {}
        agent_id = p.get("agent_id", "unknown")
        key = p.get("key", "")
        value = await self._cm.get(agent_id, key, namespace="agent_memory")
        await self._reply(event, value)

    async def _on_agent_delete(self, event) -> None:
        """memory.agent.delete → ContextManager.delete(namespace=agent_memory)"""
        p = event.payload or {}
        agent_id = p.get("agent_id", "unknown")
        key = p.get("key", "")
        await self._cm.delete(agent_id, key, namespace="agent_memory")
        await self._reply(event, {"status": "ok"})

    async def _on_agent_clear(self, event) -> None:
        """memory.agent.clear → ContextManager.clear_agent()"""
        p = event.payload or {}
        agent_id = p.get("agent_id", "unknown")
        await self._cm.clear_agent(agent_id)
        await self._reply(event, {"status": "ok"})

    # ------------------------------------------------------------------
    # 项目共享上下文
    # ------------------------------------------------------------------

    async def _on_project_set(self, event) -> None:
        """memory.project.set → ContextManager.set_project_context()"""
        p = event.payload or {}
        project_id = p.get("project_id", "")
        key = p.get("key", "")
        value = p.get("value", "")
        ttl = p.get("ttl_seconds")
        await self._cm.set_project_context(project_id, key, value, ttl_seconds=ttl)
        await self._reply(event, {"status": "ok"})

    async def _on_project_get(self, event) -> None:
        """memory.project.get → ContextManager.get_project_context()"""
        p = event.payload or {}
        project_id = p.get("project_id", "")
        key = p.get("key", "")
        value = await self._cm.get_project_context(project_id, key)
        await self._reply(event, value)

    async def _on_project_list(self, event) -> None:
        """memory.project.list → ContextManager.list_project_context()"""
        p = event.payload or {}
        project_id = p.get("project_id", "")
        result = await self._cm.list_project_context(project_id)
        await self._reply(event, result)

    # ------------------------------------------------------------------
    # 全局上下文
    # ------------------------------------------------------------------

    async def _on_global_set(self, event) -> None:
        """memory.global.set → ContextManager.set_global()"""
        p = event.payload or {}
        key = p.get("key", "")
        value = p.get("value", "")
        await self._cm.set_global(key, value)
        await self._reply(event, {"status": "ok"})

    async def _on_global_get(self, event) -> None:
        """memory.global.get → ContextManager.get_global()"""
        p = event.payload or {}
        key = p.get("key", "")
        value = await self._cm.get_global(key)
        await self._reply(event, value)

    async def _on_global_list(self, event) -> None:
        """memory.global.list → ContextManager.list_global()"""
        result = await self._cm.list_global()
        await self._reply(event, result)

    async def _on_global_delete(self, event) -> None:
        """memory.global.delete → ContextManager.delete_global()"""
        p = event.payload or {}
        key = p.get("key", "")
        await self._cm.delete_global(key)
        await self._reply(event, {"status": "ok"})

    # ------------------------------------------------------------------
    # 全文搜索
    # ------------------------------------------------------------------

    async def _on_search(self, event) -> None:
        """memory.search → ContextManager.search() 全文检索"""
        p = event.payload or {}
        query = p.get("query", "")
        limit = p.get("limit", 20)
        results = await self._cm.search(query, limit=limit)
        await self._reply(event, results)


__all__ = ["MemoryBridge"]
