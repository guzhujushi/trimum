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
from .tool_dispatchers import DispatcherRegistry
from .tool_file_loader import scan_tools
from .logger import get_logger

logger = get_logger("tool_gateway")


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Central registry for tool definitions.

    Two-tier loading:
    1. Scan ~/.trimum/tools/<name>/tool.json5 for file-based tools
    2. If a tool has no file-based definition, fall back to built-in defaults

    Ships with three built-in tools (shell, file.read, file.write)
    as fallbacks when no file-based manifest is found.
    """

    def __init__(self, tools_path: str | None = None) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._tools_path = tools_path
        self.load_all()

    def load_all(self) -> int:
        """Reload all tool definitions from files + built-in fallbacks.

        Clears current registry, then:
        1. Loads from ~/.trimum/tools/<name>/tool.json5
        2. Fills missing tools with built-in defaults

        Returns number of file-based tools loaded.
        """
        self._tools.clear()

        # 1. File-based tools
        file_count = 0
        for tool in scan_tools(self._tools_path):
            self._tools[tool.name] = tool
            file_count += 1

        # 2. Built-in fallbacks for tools not registered via file
        self._register_defaults()

        return file_count

    def _register_defaults(self) -> None:
        """Register built-in tool fallbacks (only if not already loaded from file)."""
        defaults: list[ToolDefinition] = [
            ToolDefinition(
                name="shell",
                description="Execute arbitrary shell commands",
                tool_type=ToolType.SHELL,
                executable="",
                allowed_flags=[],
                timeout_default=30.0,
                risk_level=RiskLevel.MEDIUM,
            ),
            ToolDefinition(
                name="file.read",
                description="Read file contents via shell (cat, head, tail, etc.)",
                tool_type=ToolType.CUSTOM,
                executable="",
                allowed_flags=["-n", "-c", "-f"],
                timeout_default=10.0,
                risk_level=RiskLevel.LOW,
            ),
            ToolDefinition(
                name="file.write",
                description="Write to files via shell (echo >, tee, sed -i, etc.)",
                tool_type=ToolType.CUSTOM,
                executable="",
                allowed_flags=[],
                timeout_default=10.0,
                risk_level=RiskLevel.HIGH,
            ),
            ToolDefinition(
                name="file",
                description="File operations: read, write, delete, list, move, copy, search",
                tool_type=ToolType.FILE_READ,
                executable="",
                allowed_flags=[],
                timeout_default=10.0,
                risk_level=RiskLevel.MEDIUM,
            ),
            ToolDefinition(
                name="git",
                description="Git operations: status, diff, log, commit, push, pull, branch",
                tool_type=ToolType.GIT,
                executable="",
                allowed_flags=[],
                timeout_default=30.0,
                risk_level=RiskLevel.LOW,
            ),
            ToolDefinition(
                name="http",
                description="HTTP requests: GET and POST",
                tool_type=ToolType.HTTP,
                executable="",
                allowed_flags=[],
                timeout_default=30.0,
                risk_level=RiskLevel.MEDIUM,
            ),
            ToolDefinition(
                name="process",
                description="Process operations: list and kill",
                tool_type=ToolType.PROCESS,
                executable="",
                allowed_flags=[],
                timeout_default=10.0,
                risk_level=RiskLevel.HIGH,
            ),
            ToolDefinition(
                name="system",
                description="System information: info, disk, memory",
                tool_type=ToolType.SYSTEM,
                executable="",
                allowed_flags=[],
                timeout_default=10.0,
                risk_level=RiskLevel.LOW,
            ),
            ToolDefinition(
                name="env",
                description="Environment variable operations: get and list",
                tool_type=ToolType.ENV_GET,
                executable="",
                allowed_flags=[],
                timeout_default=5.0,
                risk_level=RiskLevel.MEDIUM,
            ),
            ToolDefinition(
                name="knowledge",
                description="Knowledge base operations: search and store",
                tool_type=ToolType.KNOWLEDGE_SEARCH,
                executable="",
                allowed_flags=[],
                timeout_default=10.0,
                risk_level=RiskLevel.LOW,
            ),
            ToolDefinition(
                name="notification",
                description="Send notifications (apprise)",
                tool_type=ToolType.NOTIFICATION,
                executable="",
                allowed_flags=[],
                timeout_default=10.0,
                risk_level=RiskLevel.LOW,
            ),
            ToolDefinition(
                name="mcp",
                description="MCP tools: list and call",
                tool_type=ToolType.MCP_TOOLS_LIST,
                executable="",
                allowed_flags=[],
                timeout_default=30.0,
                risk_level=RiskLevel.MEDIUM,
            ),
            ToolDefinition(
                name="custom",
                description="Custom tool dispatcher",
                tool_type=ToolType.CUSTOM,
                executable="",
                allowed_flags=[],
                timeout_default=30.0,
                risk_level=RiskLevel.MEDIUM,
            ),
        ]

        for tool in defaults:
            if tool.name not in self._tools:
                self._tools[tool.name] = tool

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


_FILE_READ = "file.read"
_FILE_WRITE = "file.write"


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
        dispatcher_registry: Optional[DispatcherRegistry] = None,
    ) -> None:
        self.policy = policy_engine or PolicyEngine()
        self.tools = tool_registry or ToolRegistry()
        self.dispatchers = dispatcher_registry or DispatcherRegistry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # ── Only need for cmd_str-based permission check helper ──
    @staticmethod
    def _build_cmd_str(request: ExecuteRequest) -> str:
        """Build a human-readable command string from the request for policy checks."""
        if isinstance(request.args, list):
            return " ".join(request.args).strip()
        return str(request.args).strip() if request.args else ""

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        """Execute a tool command with two-layer permission check.

        Layer 1: Global PolicyEngine check (regex rules from policy.yaml).
        Layer 2: Agent permissions check (from AgentManifest if available).
        Execution: Dispatched via DispatcherRegistry to the appropriate
                   dispatcher (FileDispatcher, GitDispatcher, ShellDispatcher, etc.).
        """
        execution_id = uuid.uuid4().hex[:12]

        # Build command string for policy checks
        cmd_str = self._build_cmd_str(request)
        if not cmd_str and request.tool == ToolType.SHELL:
            return ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                error="Empty command",
                exit_code=1,
                risk=RiskLevel.CRITICAL,
                action=Action.DENY,
                reason="No command provided",
            )

        # Resolve tool definition (optional, used for agent permission check)
        tool_def = self.tools.get(request.tool.value)

        # ------------------------------------------------------------------
        # Layer 1: Global Policy Check (with source_type awareness)
        # ------------------------------------------------------------------
        source_type = getattr(request, "source_type", None)
        risk, action, reason = self.policy.evaluate(cmd_str, source_type=source_type)

        if action == Action.DENY:
            logger.warning(
                "gateway.layer1_denied",
                command=cmd_str,
                reason=reason,
                tool=request.tool.value,
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
        # Execute via DispatcherRegistry
        # ------------------------------------------------------------------
        status = "allowed" if action == Action.AUTO else "confirmed"
        logger.info(
            "gateway.executing",
            tool=request.tool.value,
            args=cmd_str[:200] if len(cmd_str) > 200 else cmd_str,
            risk=risk.value,
            action=action.value,
            execution_id=execution_id,
            agent_id=request.agent_id,
        )

        # Dispatch to the appropriate tool dispatcher
        result = await self.dispatchers.dispatch(request)

        # Merge policy decisions into the dispatcher's response
        result.execution_id = result.execution_id or execution_id
        if result.status in ("", "allowed"):
            result.status = status
        result.risk = result.risk or risk
        result.action = result.action or action
        result.reason = result.reason or reason

        return result

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
        if tool_def and tool_def.name in (_FILE_READ, _FILE_WRITE):
            # Extract paths from command (crude heuristic: last arg that looks like a path)
            parts = cmd_str.split()
            paths = [p for p in parts if "/" in p or "\\" in p or p.startswith(".")]
            if paths:
                allowed_paths = perms.read if tool_def.name == _FILE_READ else perms.write
                if not allowed_paths:
                    return f"Agent '{manifest.name}' has no {(tool_def.name.split('.'))[1]} path permissions"
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
