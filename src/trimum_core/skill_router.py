"""Skill Router — route ``skill:<name>`` capabilities to SkillExecutor.

Integration with AgentRouter:
    When AgentRouter receives a capability request (``skill:deploy``),
    this module resolves it to a loaded SkillDefinition and dispatches
    execution via SkillExecutor.

Flow:
    AgentRouter.find_by_capability("skill:deploy")
        → SkillRouter.get_skill("deploy")
        → SkillExecutor.execute(skill, agent_id)
"""

from __future__ import annotations

from typing import Optional

from .skill_loader import SkillLoader, SkillDefinition
from .skill_executor import SkillExecutor, SkillExecutionResult
from .tool_gateway import ToolGateway


class SkillRouter:
    """Routes ``skill:<name>`` capability requests to the right handler.

    Can operate in two modes:
    1. **Direct execution** → ``execute_skill(name)`` runs the skill now.
    2. **Agent match** → ``find_agent_for_skill(name)`` returns an
       agent manifest that claims the ``skill:<name>`` capability
       (future use, for multi-agent dispatch).
    """

    SKILL_PREFIX = "skill:"

    def __init__(
        self,
        skill_loader: SkillLoader,
        gateway: ToolGateway,
        stop_on_failure: bool = True,
    ) -> None:
        self._loader = skill_loader
        self._executor = SkillExecutor(gateway, stop_on_failure=stop_on_failure)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def is_skill_capability(cls, capability: str) -> bool:
        """Check if a capability string is a skill reference (``skill:<name>``)."""
        return capability.startswith(cls.SKILL_PREFIX)

    @classmethod
    def extract_skill_name(cls, capability: str) -> Optional[str]:
        """Extract skill name from ``skill:<name>``, or None."""
        if capability.startswith(cls.SKILL_PREFIX):
            return capability[len(cls.SKILL_PREFIX):]
        return None

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """Get a loaded skill definition by name."""
        return self._loader.get(name)

    def list_skill_capabilities(self) -> list[str]:
        """Return all registered skill capability strings (e.g. ``skill:deploy``)."""
        return [f"{self.SKILL_PREFIX}{name}" for name in self._loader.list_skill_names()]

    async def execute_skill(
        self,
        name: str,
        agent_id: Optional[str] = None,
        extra_args: Optional[dict[str, str]] = None,
    ) -> SkillExecutionResult:
        """Execute a skill by name.

        Args:
            name: Skill name (without ``skill:`` prefix).
            agent_id: Optional agent ID for audit.
            extra_args: Optional template vars for ``{placeholder}`` substitution.

        Returns:
            SkillExecutionResult. Check ``result.success``.

        Raises:
            ValueError: If skill name is not loaded.
        """
        skill = self._loader.get(name)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found (loaded: {self._loader.list_skill_names()})")
        return await self._executor.execute(skill, agent_id=agent_id, extra_args=extra_args)
