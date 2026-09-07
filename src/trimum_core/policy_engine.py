"""Policy Engine — permission evaluation for tool execution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .models import RiskLevel, Action, SourceType
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

    def evaluate(
        self,
        command: str,
        source_type: SourceType | None = None,
    ) -> tuple[RiskLevel, Action, str]:
        """Evaluate a command string and return (risk, action, reason).

        Args:
            command: The command string to evaluate.
            source_type: Optional source type indicator. When set, rules
                with a ``source`` filter are matched first. For example,
                an AI-originated ``rm`` can be blocked while human-originated
                is allowed.

        Rules are iterated in order; the first match wins.
        If no rule matches, defaults to (medium, confirm).

        Source-aware rules in YAML:
            patterns:
              - pattern: "rm"
                source: ai          # 只有 AI 发的 rm 才匹配
                action: deny
              - pattern: "rm"
                source: human        # 人类发的 rm 只需确认
                risk: high
                action: confirm
        """
        cmd_normalized = self._normalize_command(command)

        for rule in self._rules:
            pattern = rule.get("pattern", "")
            if not pattern:
                continue
            if not re.search(pattern, cmd_normalized, re.IGNORECASE):
                continue

            # Check source_type filter (if present in rule)
            rule_source = rule.get("source", None)
            if rule_source is not None and source_type is not None:
                # rule has a source filter AND we have a source_type
                # — only match if they match
                if rule_source != source_type.value:
                    continue

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
            return risk, action, f"Matched rule: {pattern} (src={source_type.value if source_type else 'none'})"

        # No match → default (respect source_type for stricter default)
        if source_type == SourceType.AI:
            return RiskLevel.MEDIUM, Action.CONFIRM, "No rule matched, AI default"
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
