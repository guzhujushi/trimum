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

    # ------------------------------------------------------------------
    # Landlock interface (Phase 4 stub)
    # ------------------------------------------------------------------

    async def check_landlock(
        self,
        path: str,
        access_type: str = "read",
    ) -> bool:
        """Check if *path* is accessible with *access_type* under Landlock.

        Args:
            path: Filesystem path to check.
            access_type: One of "read", "write", "execute".

        Returns:
            True if allowed, False if denied.

        Note:
            This is a Phase 4 placeholder. Currently returns True for all
            paths. Actual Landlock enforcement will be implemented when
            the Linux Landlock LSM integration is added.

        Phase 4 implementation plan:
        - Use ``os.landlock`` or ctypes to create a Landlock ruleset
        - Restrict agent processes to their declared path permissions
        - Deny writes to system paths (/etc, /usr, /boot, /sys, /proc)
        - Allow reads to ~/.trimum/ and agent workspace unless blocked
        """
        _ = path, access_type  # unused placeholder
        return True

    async def get_landlock_ruleset(self) -> dict:
        """Return the current Landlock ruleset as a dict (stub)."""
        return {
            "enabled": False,
            "allowed_read": [],
            "allowed_write": [],
            "allowed_exec": [],
            "version": 0,
        }

    @staticmethod
    def _normalize_command(cmd: str) -> str:
        """Normalize command string for pattern matching.

        - Lowercase
        - Collapse whitespace
        - Remove leading/trailing whitespace
        """
        return " ".join(cmd.lower().split())
