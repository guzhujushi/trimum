"""Agent Router for trimum Core.

Maps task/request → agent(s) and orchestrates multi-agent collaboration.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from trimum_core.agent_registry import AgentRegistry
from trimum_core.event_bus import EventBus
from trimum_core.models import AgentManifest


class RouteEntry(BaseModel):
    """A single route binding a capability to an agent with priority."""

    capability: str
    agent_name: str
    priority: int = 0


class AgentRouter:
    """Routes task capability requests to registered agents.

    Features:
    - ``route(capability)`` — find the single best agent
    - ``route_multi(task_type)`` — find all candidates for a task type
    - ``build_pipeline([c1, c2, c3])`` — build a processing pipeline
    - ``build_routes()`` — rebuild internal route table from registry
    """

    def __init__(self, registry: AgentRegistry, event_bus: EventBus) -> None:
        self.registry = registry
        self.event_bus = event_bus
        # capability -> ordered list of RouteEntry (highest priority first)
        self._routes: dict[str, list[RouteEntry]] = {}

    # ------------------------------------------------------------------
    # Route building
    # ------------------------------------------------------------------

    def build_routes(self) -> None:
        """Rebuild the internal route table from the current registry.

        Should be called after new agents are registered or loaded.
        """
        self._routes.clear()

        for manifest in self.registry.list_agents():
            for cap in manifest.capabilities:
                entry = RouteEntry(
                    capability=cap,
                    agent_name=manifest.name,
                    priority=1,  # default priority; configurable in future
                )
                self._routes.setdefault(cap, []).append(entry)

        # Sort each route list by priority descending
        for cap in self._routes:
            self._routes[cap].sort(key=lambda e: e.priority, reverse=True)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route(self, capability: str) -> Optional[AgentManifest]:
        """Find the best single agent for a capability.

        Returns the agent with the highest priority that matches.
        Falls back to the first matching agent if no priority info found.
        """
        # Direct route match
        if capability in self._routes and self._routes[capability]:
            return self.registry.get_agent(self._routes[capability][0].agent_name)

        # Fallback: query registry for capability
        candidates = self.registry.find_by_capability(capability)
        if candidates:
            return candidates[0]

        return None

    def route_multi(self, task_type: str) -> list[AgentManifest]:
        """Return all agents that can handle a task type.

        Uses capability matching via the registry to find agents whose
        capabilities overlap with ``task_type``.
        """
        return self.registry.find_by_capability(task_type)

    def build_pipeline(self, capabilities: list[str]) -> list[AgentManifest]:
        """Build a processing pipeline from an ordered list of capabilities.

        Returns agents in pipeline order: first matching ``capabilities[0]``,
        then ``capabilities[1]``, etc. If no agent matches a step, the step
        is skipped with ``None`` in the result list.
        """
        pipeline: list[AgentManifest] = []
        for cap in capabilities:
            agent = self.route(cap)
            if agent is not None:
                pipeline.append(agent)
        return pipeline

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def route_with_event(
        self, capability: str, event_source: str = "router"
    ) -> Optional[AgentManifest]:
        """Route a capability and emit a routing event.

        Same semantics as ``route()``, but also publishes a
        ``router.routed`` event via the event bus.
        """
        agent = self.route(capability)
        if agent is not None:
            self.event_bus.publish(
                self._make_event(
                    event_type="router.routed",
                    source=event_source,
                    payload={
                        "capability": capability,
                        "agent": agent.name,
                    },
                )
            )
        return agent

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _make_event(
        event_type: str,
        source: str,
        payload: dict,
    ) -> object:
        """Create a SystemEvent for the event bus."""
        # Late import to avoid circular dependency at module level
        from trimum_core.models import SystemEvent

        return SystemEvent(event_type=event_type, source=source, payload=payload)


__all__ = ["AgentRouter", "RouteEntry"]
