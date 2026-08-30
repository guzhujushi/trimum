"""Policy Engine — permission evaluation for tool execution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .models import RiskLevel, Action
from .config import PolicyLoader


class PolicyEngine:
    """Evaluate command/operation risk against YAML-defined rules."""

    def __init__(self, policy_path: Optional[Path] = None):
        self._loader = PolicyLoader(policy_path)
        self._rules: list[dict] = []
        self.reload()

    def reload(self) -> None:
        """Reload policy rules from YAML file."""
        self._rules = self._loader.load()

    def evaluate(self, command: str) -> tuple[RiskLevel, Action, str]:
        """Evaluate a command string and return (risk, action, reason).

        Iterates rules in order, returns first match.
        If no rule matches, defaults to (medium, confirm).
        """
        cmd_normalized = self._normalize_command(command)

        for rule in self._rules:
            pattern = rule.get("pattern", "")
            if not pattern:
                continue
            if re.search(pattern, cmd_normalized, re.IGNORECASE):
                risk_str = rule.get("risk", "medium")
                action_str = rule.get("action", "confirm")
                try:
                    risk = RiskLevel(risk_str)
                except ValueError:
                    risk = RiskLevel.MEDIUM
                try:
                    action = Action(action_str)
                except ValueError:
                    action = Action.CONFIRM
                return risk, action, f"Matched rule: {pattern}"

        # No match → default
        return RiskLevel.MEDIUM, Action.CONFIRM, "No rule matched, default"

    def evaluate_args(self, args: list[str]) -> tuple[RiskLevel, Action, str]:
        """Evaluate a list of command arguments."""
        return self.evaluate(" ".join(args))

    @staticmethod
    def _normalize_command(cmd: str) -> str:
        """Normalize command string for pattern matching.

        - Lowercase
        - Collapse whitespace
        - Remove leading/trailing whitespace
        """
        return " ".join(cmd.lower().split())
