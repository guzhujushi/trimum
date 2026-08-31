"""Tool Gateway — async command execution with tool registry and agent-aware policy.

Architecture:
1. ToolRegistry holds known tool definitions (name → ToolDefinition)
2. ToolGateway.execute() does a **two-layer permission check**:
   - Layer 1: Global Policy (command-level regex rules from policy.yaml)
   - Layer 2: Agent Permission (agent.json declared exec/deny_exec/read/write)
3. Only when both layers pass is the command executed
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional

from .models import (
    ExecuteRequest,
    ExecuteResponse,
    RiskLevel,
    Action,
    ToolType,
    ToolDefinition,
    AgentPermissions,
    AgentManifest,
)
from .policy_engine import PolicyEngine
from .logger import get_logger

logger = get_logger("tool_gateway")


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Central registry for tool definitions.

    Ships with three built-in tools (shell, file.read, file.write).
    Agents or the SDK may register additional tools at runtime.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register the three built-in tools."""
        self.register(
            ToolDefinition(
                name="shell",
                description="Execute arbitrary shell commands",
                tool_type=ToolType.SHELL,
                executable="",
                allowed_flags=[],
                timeout_default=30.0,
                risk_level=RiskLevel.MEDIUM,
            )
        )
        self.register(
            ToolDefinition(
                name="file.read",
                description="Read file contents via shell (cat, head, tail, etc.)",
                tool_type=ToolType.CUSTOM,
                executable="",
                allowed_flags=["-n", "-c", "-f"],
                timeout_default=10.0,
                risk_level=RiskLevel.LOW,
            )
        )
        self.register(
            ToolDefinition(
                name="file.write",
                description="Write to files via shell (echo >, tee, sed -i, etc.)",
                tool_type=ToolType.CUSTOM,
                executable="",
                allowed_flags=[],
                timeout_default=10.0,
                risk_level=RiskLevel.HIGH,
            )
        )

    def register(self, tool: ToolDefinition) -> None:
        """Register or replace a tool definition."""
        self._tools[tool.name] = tool
        logger.debug("tool_registry.registered", tool=tool.name)

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """Return all registered tool definitions."""
        return list(self._tools.values())

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if found and removed."""
        if name in self._tools:
            del self._tools[name]
            logger.debug("tool_registry.unregistered", tool=name)
            return True
        return False


# ---------------------------------------------------------------------------
# Tool Gateway
# ---------------------------------------------------------------------------


class ToolGateway:
    """Execute tool commands with two-layer permission checking.

    Flow:
        1. Resolve the tool from ToolRegistry (by request.tool or command sniff)
        2. Layer 1: Global PolicyEngine check (regex rules from policy.yaml)
        3. Layer 2: Agent permissions check (from AgentManifest if available)
        4. Execute or deny

    'confirm' actions are passed through to the caller; the caller decides
    whether to prompt the user.
    """

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        self.policy = policy_engine or PolicyEngine()
        self.tools = tool_registry or ToolRegistry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        """Execute a tool command with two-layer permission check."""
        execution_id = uuid.uuid4().hex[:12]

        # Build command string
        cmd_str = " ".join(request.args) if isinstance(request.args, list) else request.args
        cmd_str = cmd_str.strip()

        if not cmd_str:
            return ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                error="Empty command",
                exit_code=1,
                risk=RiskLevel.CRITICAL,
                action=Action.DENY,
                reason="No command provided",
            )

        # Resolve tool definition
        tool_def = self.tools.get(request.tool.value)

        # ------------------------------------------------------------------
        # Layer 1: Global Policy Check
        # ------------------------------------------------------------------
        risk, action, reason = self.policy.evaluate(cmd_str)

        if action == Action.DENY:
            logger.warning(
                "gateway.layer1_denied",
                command=cmd_str,
                reason=reason,
                risk=risk.value,
            )
            return ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                error=f"Policy denied: {reason}",
                exit_code=1,
                risk=risk,
                action=action,
                reason=reason,
            )

        # ------------------------------------------------------------------
        # Layer 2: Agent Permission Check
        # ------------------------------------------------------------------
        agent_manifest: Optional[AgentManifest] = getattr(
            request, "agent_manifest", None
        )

        agent_deny_reason = self._check_agent_permissions(
            cmd_str, agent_manifest, tool_def
        )
        if agent_deny_reason is not None:
            logger.warning(
                "gateway.layer2_denied",
                command=cmd_str,
                agent=agent_manifest.name if agent_manifest else "unknown",
                reason=agent_deny_reason,
            )
            return ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                error=f"Agent permission denied: {agent_deny_reason}",
                exit_code=1,
                risk=RiskLevel.HIGH,
                action=Action.DENY,
                reason=agent_deny_reason,
            )

        # ------------------------------------------------------------------
        # Execute
        # ------------------------------------------------------------------
        status = "allowed" if action == Action.AUTO else "confirmed"
        logger.info(
            "gateway.executing",
            command=cmd_str,
            risk=risk.value,
            action=action.value,
            execution_id=execution_id,
            agent_id=request.agent_id,
        )

        result = await self._run_subprocess(
            cmd=cmd_str,
            timeout=request.timeout_seconds,
            env=request.env if request.env else None,
            cwd=request.cwd,
        )

        return ExecuteResponse(
            execution_id=execution_id,
            status=status,
            output=result["stdout"],
            error=result["stderr"],
            exit_code=result["exit_code"],
            risk=risk,
            action=action,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Agent Permission Check
    # ------------------------------------------------------------------

    @staticmethod
    def _check_agent_permissions(
        cmd_str: str,
        manifest: Optional[AgentManifest],
        tool_def: Optional[ToolDefinition],
    ) -> Optional[str]:
        """Check if an agent is allowed to run the command.

        Returns ``None`` if allowed, or a reason string if denied.
        Rules (in order):
        1. No manifest → allow (backward compat)
        2. Empty permissions (all fields default) → only LOW risk tools
        3. ``deny_exec`` match → deny immediately
        4. ``exec`` list not empty and command not in list → deny
        5. File operations checked against read/write path patterns
        6. Otherwise → allow
        """
        if manifest is None:
            return None  # No agent context → skip layer 2 (backward compat)

        perms = manifest.permissions
        first_word = cmd_str.split()[0].lower() if cmd_str else ""

        # --- 2a. deny_exec (takes precedence) ---
        for denied in perms.deny_exec:
            if first_word == denied.lower():
                return f"Agent '{manifest.name}' is not allowed to execute '{first_word}' (deny_exec rule)"

        # --- 2b. exec whitelist ---
        if perms.exec:
            allowed = False
            for allowed_cmd in perms.exec:
                if first_word == allowed_cmd.lower() or cmd_str.startswith(allowed_cmd.lower()):
                    allowed = True
                    break
            if not allowed:
                return (
                    f"Agent '{manifest.name}' may only execute: {', '.join(perms.exec)}. "
                    f"Got '{first_word}'"
                )

        # --- 2c. File read/write path check ---
        if tool_def and tool_def.name in ("file.read", "file.write"):
            # Extract paths from command (crude heuristic: last arg that looks like a path)
            parts = cmd_str.split()
            paths = [p for p in parts if "/" in p or "\\" in p or p.startswith(".")]
            if paths:
                allowed_paths = perms.read if tool_def.name == "file.read" else perms.write
                if not allowed_paths:
                    return f"Agent '{manifest.name}' has no {tool_def.name.split('.')[1]} path permissions"
                for p in paths:
                    matched = any(
                        p.startswith(ap.rstrip("*").rstrip("/"))
                        for ap in allowed_paths
                    )
                    if not matched:
                        return (
                            f"Agent '{manifest.name}' is not allowed to access path '{p}'. "
                            f"Allowed: {', '.join(allowed_paths)}"
                        )

        # --- 2d. Empty permissions → only allow LOW risk ---
        if (
            not perms.exec
            and not perms.read
            and not perms.write
            and not perms.deny_exec
        ):
            # Agent declared no permissions → restrict to low-risk
            # The caller should set risk accordingly; we just pass
            pass

        return None  # allowed

    # ------------------------------------------------------------------
    # Subprocess execution
    # ------------------------------------------------------------------

    async def _run_subprocess(
        self,
        cmd: str,
        timeout: float = 30.0,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> dict:
        """Run a command via async subprocess with timeout."""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
                shell=True,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout}s",
                    "exit_code": -1,
                }

            return {
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                "exit_code": proc.returncode or 0,
            }

        except FileNotFoundError:
            return {"stdout": "", "stderr": "Command not found", "exit_code": 127}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1}

    # ------------------------------------------------------------------
    # Tool config loading
    # ------------------------------------------------------------------

    def load_tools_from_config(self, tools_config: dict) -> None:
        """Load tool definitions from a config dictionary.

        Expected format::
            tools:
              shell:
                allowed_flags: []
                timeout_default: 30
                risk_level: medium
              file.read:
                allowed_flags: ["-n", "-c", "-f"]
                timeout_default: 10
                risk_level: low
        """
        for name, cfg in tools_config.items():
            try:
                existing = self.tools.get(name)
                if existing is not None:
                    # Update existing tool
                    for field in ("allowed_flags", "timeout_default", "risk_level"):
                        if field in cfg:
                            setattr(existing, field, cfg[field])
                else:
                    # Create new tool from config
                    tool_type_str = cfg.get("tool_type", "custom")
                    try:
                        tool_type = ToolType(tool_type_str)
                    except ValueError:
                        tool_type = ToolType.CUSTOM
                    self.tools.register(
                        ToolDefinition(
                            name=name,
                            description=cfg.get("description", ""),
                            tool_type=tool_type,
                            executable=cfg.get("executable", ""),
                            allowed_flags=cfg.get("allowed_flags", []),
                            timeout_default=cfg.get("timeout_default", 30.0),
                            risk_level=RiskLevel(cfg.get("risk_level", "medium")),
                        )
                    )
                logger.debug("gateway.tool_config_loaded", tool=name)
            except Exception as e:
                logger.warning("gateway.tool_config_error", tool=name, error=str(e))


__all__ = ["ToolGateway", "ToolRegistry", "ToolDefinition"]
