"""Transform Agent — natural language to TARL tag language.

This Agent pre-translates user input into deterministic KV-line format
so the Workflow Engine can reliably match against preset workflows.

Phase 1: stub (returns TARL comment)
Phase 2+: actual LLM call
"""

from __future__ import annotations

from typing import Any

from trimum_core.tarl_parser import serialize

__all__ = [
    "TransformAgent",
    "build_tarl_response",
]


def build_tarl_response(cmd: str, **kwargs: str) -> str:
    """Build a TARL response string from a command name and optional KV pairs.

    Args:
        cmd: Command name (e.g. ``"restart_nginx"``).
        **kwargs: Additional key=value pairs.

    Returns:
        TARL line string.

    Example::

        >>> build_tarl_response("restart_nginx", user="guzhu", workflow="blog_deploy")
        "cmd:restart_nginx user:guzhu workflow:blog_deploy"
    """
    data: dict[str, str] = {"cmd": cmd}
    data.update(kwargs)
    return serialize(data)


class TransformAgent:
    """Transform natural language instructions into TARL tag language.

    The output must be deterministic: same input always produces same TARL output.
    This ensures the Workflow Engine can reliably match against preset workflows.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    async def execute(
        self,
        instruction: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Convert natural language to TARL.

        Args:
            instruction: Natural language instruction from the user.
            context: Optional context (workflow type, previous commands, etc.).

        Returns:
            Dict with keys:
                - ``tarl``: TARL output string (KV line format)
                - ``confidence``: float 0.0–1.0
                - ``original``: the input instruction
        """
        _ = context  # reserved for Phase 2

        # Phase 1: stub — configurable fallback for known commands
        tarl_output = self._stub_transform(instruction)

        return {
            "tarl": tarl_output,
            "confidence": 1.0 if not tarl_output.startswith("#") else 0.3,
            "original": instruction,
        }

    def _stub_transform(self, instruction: str) -> str:
        """Phase 1 stub: echo instruction as a TARL comment.

        Phase 2 will replace this with an actual LLM call.
        In Phase 3+, this can be extended with deterministic keyword→TARL rules.
        """
        # Safely escape comment value (no spaces allowed in TARL)
        safe = instruction.replace(" ", "_").replace(":", "_")
        return f"#:{safe}"


__all__ = ["TransformAgent", "build_tarl_response"]
