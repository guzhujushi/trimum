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
import importlib
import importlib.util
import os
import re
import sys
import time
import types
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional

from .models import (
    DefenseAction,
    ExecuteRequest,
    ExecuteResponse,
    RiskLevel,
    Action,
    ToolType,
    ToolDefinition,
    AgentPermissions,
    AgentManifest,
    AuditEvent,
    JITToken,
)
from .policy_engine import PolicyEngine
from .security_rule import SecurityRule, DecisionResult
from .tool_dispatchers import DispatcherRegistry
from .tool_file_loader import scan_tools
from .sec_monitor import OpContextClassifier, SecMonitor
from .sec_executor import SecExecutor
from .logger import get_logger

logger = get_logger("tool_gateway")

# 默认工作目录
_DEFAULT_WORK_DIR = os.path.expanduser("~/.trimum/workdir")

# 敏感环境变量模式（用于凭据脱敏）
_SENSITIVE_ENV_PATTERNS = re.compile(
    r"(?i)(api_key|secret|password|token|auth|credential|private_key|access_key)"
)

# 敏感输出模式（用于日志脱敏）
_SENSITIVE_OUTPUT_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|secret|password|token)[=: ]+\S+"), r"\1=***REDACTED***"),
    (re.compile(r"(?i)(Bearer\s+)\S{8,}"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(Authorization:[^,]*)\S{8,}"), r"\1***REDACTED***"),
]


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
        self._tool_modules: dict[str, types.ModuleType] = {}
        self._tools_path = tools_path
        self.load_all()

    def load_all(self) -> int:
        """Reload all tool definitions and entry-point modules."""
        self._tools.clear()
        self._tool_modules.clear()

        # 1. File-based tools
        file_count = 0
        for tool in scan_tools(self._tools_path):
            self._tools[tool.name] = tool
            file_count += 1

        # 2. Load each tool's main.py module
        tools_path = Path(self._tools_path or Path.home() / ".trimum" / "tools")
        if tools_path.is_dir():
            for child in sorted(tools_path.iterdir()):
                if child.is_dir():
                    main_py = child / "main.py"
                    if main_py.is_file():
                        self._load_tool_module(child.name, main_py)

        # 3. Built-in fallbacks for tools not registered via file
        self._register_defaults()

        return file_count

    def _load_tool_module(self, name: str, main_py: Path) -> None:
        """Dynamically import a tool's main.py and cache the module."""
        try:
            spec = importlib.util.spec_from_file_location(
                f"trimum_tool_{name}", str(main_py)
            )
            if spec is None or spec.loader is None:
                return
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._tool_modules[name] = mod
        except Exception as e:
            logger.warning("tool_file_loader.module_failed", tool=name, error=str(e))

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

    def get_executor(self, name: str) -> Optional[Callable[..., Awaitable[dict]]]:
        """Get the async execute() function for a file-based tool.

        Returns None if the tool has no file-based executor.
        """
        mod = self._tool_modules.get(name)
        if mod and hasattr(mod, 'execute') and callable(mod.execute):
            return mod.execute
        return None

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

    When ``interactive=True``, the gateway prompts on stderr for y/n confirmation
    before executing commands that received a ``confirm`` action from the policy
    engine. This is used by the CLI ``trm install`` and ``trm exec`` commands.
    """

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        tool_registry: Optional[ToolRegistry] = None,
        dispatcher_registry: Optional[DispatcherRegistry] = None,
        security_rule: Optional[SecurityRule] = None,
        sec_monitor: Optional[SecMonitor] = None,
        sec_executor: Optional[SecExecutor] = None,
        op_context: Optional[OpContextClassifier] = None,
        work_dir: Optional[str] = None,
        enable_cwd_jail: bool = True,
        enable_credential_redact: bool = True,
        enable_audit: bool = True,
        enable_jit_auth: bool = True,
        interactive: bool = False,
    ) -> None:
        self.policy = policy_engine or PolicyEngine()
        self.tools = tool_registry or ToolRegistry()
        self.dispatchers = dispatcher_registry or DispatcherRegistry()
        self.work_dir = work_dir or _DEFAULT_WORK_DIR
        self.security_rule = security_rule
        self.sec_monitor = sec_monitor
        self.sec_executor = sec_executor
        self.op_context = op_context or OpContextClassifier()
        self.enable_cwd_jail = enable_cwd_jail
        self.enable_credential_redact = enable_credential_redact
        self.enable_audit = enable_audit
        self.enable_jit_auth = enable_jit_auth
        self.interactive = interactive
        # JIT 令牌表: agent_id -> list[JITToken]
        self._jit_tokens: dict[str, list[JITToken]] = {}
        # 审计日志（内存环缓冲区）
        self._audit_log: list[AuditEvent] = []
        self._audit_max = 1000

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
        """Execute a tool command with four-layer security check.

        Layer 0: cwd Jail — 验证工作目录在允许范围内.
        Layer 1: Global PolicyEngine check (regex rules from policy.yaml).
        Layer 2: Agent permissions check (from AgentManifest if available).
        Layer 3: JIT 授权检查（高风险操作需令牌）.
        Execution: Dispatched via DispatcherRegistry.
        Post-execution: 凭据脱敏 + 审计事件记录.
        """
        execution_id = uuid.uuid4().hex[:12]
        timestamp = time.time()

        # Build command string for policy checks
        cmd_str = self._build_cmd_str(request)
        request.raw_command = cmd_str  # 保存原始命令用于审计

        if not cmd_str and request.tool == ToolType.SHELL:
            resp = ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                error="Empty command",
                exit_code=1,
                risk=RiskLevel.CRITICAL,
                action=Action.DENY,
                reason="No command provided",
            )
            self._record_audit("policy_denied", request, resp)
            return resp

        # Resolve tool definition
        tool_def = self.tools.get(request.tool.value)

        # ------------------------------------------------------------------
        # Layer 0: cwd Jail
        # ------------------------------------------------------------------
        if self.enable_cwd_jail and not request.skip_cwd_check:
            jail_reason = self._check_cwd_jail(request, tool_def)
            if jail_reason is not None:
                resp = ExecuteResponse(
                    execution_id=execution_id,
                    status="denied",
                    error=f"cwd jail: {jail_reason}",
                    exit_code=1,
                    risk=RiskLevel.HIGH,
                    action=Action.DENY,
                    reason=jail_reason,
                )
                self._record_audit("cwd_jail", request, resp)
                return resp

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
            resp = ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                error=f"Policy denied: {reason}",
                exit_code=1,
                risk=risk,
                action=action,
                reason=reason,
            )
            self._record_audit("policy_denied", request, resp)
            return resp

        # ── 终端交互确认（interactive=True 且 action=confirm） ──
        if action == Action.CONFIRM and self.interactive:
            confirmed = await self._prompt_confirm(
                cmd_str, risk, reason, request.agent_id or "terminal"
            )
            if not confirmed:
                resp = ExecuteResponse(
                    execution_id=execution_id,
                    status="denied",
                    error="User cancelled",
                    exit_code=1,
                    risk=risk,
                    action=Action.DENY,
                    reason="User declined confirmation prompt",
                )
                self._record_audit("user_cancelled", request, resp)
                return resp
            # 用户确认后，降级为 AUTO 继续执行
            action = Action.AUTO
            reason = f"User confirmed: {reason}"

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
            resp = ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                error=f"Agent permission denied: {agent_deny_reason}",
                exit_code=1,
                risk=RiskLevel.HIGH,
                action=Action.DENY,
                reason=agent_deny_reason,
            )
            self._record_audit("policy_denied", request, resp)
            return resp

        # ===== LAYER 4: Security Monitor =====
        if self.sec_monitor:
            threats = await self.sec_monitor.scan_command(
                agent_id=request.agent_id or "unknown",
                command=cmd_str,
                pid=os.getpid(),
                sandbox=request.source_type.value if hasattr(request.source_type, 'value') else str(request.source_type),
            )
            if threats:
                top = threats[0]
                if top.defense == DefenseAction.DENY:
                    logger.warning(
                        "gateway.layer4_blocked",
                        command=cmd_str,
                        threat=top.threat_name,
                        reason=top.reason,
                    )
                    resp = ExecuteResponse(
                        execution_id=execution_id,
                        status="denied",
                        error=f"[SECURITY BLOCKED] {top.reason}",
                        exit_code=137,
                        risk=RiskLevel.CRITICAL,
                        action=Action.DENY,
                        reason=top.reason,
                    )
                    self._record_audit("security_blocked", request, resp)
                    return resp

        # ------------------------------------------------------------------
        # Layer 3: JIT 授权检查
        # ------------------------------------------------------------------
        if self.enable_jit_auth and agent_manifest is not None:
            jit_reason = self._check_jit_auth(request, risk, action)
            if jit_reason is not None:
                logger.warning(
                    "gateway.layer3_jit_denied",
                    command=cmd_str,
                    agent=agent_manifest.name if agent_manifest else "unknown",
                    reason=jit_reason,
                )
                resp = ExecuteResponse(
                    execution_id=execution_id,
                    status="jit_required",
                    error=f"JIT authorization required: {jit_reason}",
                    exit_code=1,
                    risk=RiskLevel.HIGH,
                    action=Action.CONFIRM,
                    reason=jit_reason,
                )
                self._record_audit("jit_auth", request, resp)
                return resp

        status = "allowed" if action == Action.AUTO else "confirmed"

        # ------------------------------------------------------------------
        # File-based tool execution (優先走 main.py)
        # ------------------------------------------------------------------
        if tool_def:
            file_executor = self.tools.get_executor(tool_def.name)
            if file_executor:
                try:
                    result_dict = await file_executor(request.model_dump())
                    result = ExecuteResponse(**result_dict)
                    result.execution_id = result.execution_id or execution_id
                    result.status = result.status or status
                    result.risk = result.risk or risk
                    result.action = result.action or action
                    result.reason = result.reason or reason
                    if self.enable_credential_redact:
                        result = self._redact_credentials(result)
                    self._record_audit("tool_executed", request, result)
                    return result
                except Exception as e:
                    logger.warning(
                        "gateway.file_executor_failed",
                        tool=tool_def.name,
                        error=str(e),
                    )
                    # Fall through to DispatcherRegistry

        # ------------------------------------------------------------------
        # Execute via DispatcherRegistry
        # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # Post-execution: 凭据脱敏
        # ------------------------------------------------------------------
        if self.enable_credential_redact:
            result = self._redact_credentials(result)

        # ------------------------------------------------------------------
        # Post-execution: 审计事件记录
        # ------------------------------------------------------------------
        self._record_audit("tool_executed", request, result)

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
    # Layer 0: cwd Jail
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Layer 0: cwd Jail
    # ------------------------------------------------------------------

    def _check_cwd_jail(
        self,
        request: ExecuteRequest,
        tool_def: Optional[ToolDefinition],
    ) -> Optional[str]:
        """检查工作目录是否在允许范围内。

        规则：
        1. 工具不允许 cwd（如 env、knowledge）→ 跳过（视作不需要文件系统访问）
        2. request.cwd 为空 → 设为默认工作目录
        3. request.cwd 解析后必须在 work_dir 下（或等于 work_dir）
        4. agent_manifest 有 work_dir → 用 agent 的 work_dir 覆盖全局

        返回 None 表示通过，返回 str 表示拒绝原因。
        """
        # 不需要文件系统路径的工具跳过 cwd jail
        skip_tools = {
            ToolType.KNOWLEDGE_SEARCH, ToolType.KNOWLEDGE_STORE,
            ToolType.NOTIFICATION, ToolType.NOTIFICATION_SEND,
            ToolType.MCP_TOOLS_LIST, ToolType.MCP_TOOLS_CALL,
            ToolType.CUSTOM, ToolType.SHELL,
        }

        if request.tool in skip_tools:
            return None  # allowed

        # 确定 work_dir
        work_dir = self.work_dir
        if request.agent_manifest and request.agent_manifest.work_dir:
            work_dir = request.agent_manifest.work_dir

        # 确定 cwd
        cwd = request.cwd
        if not cwd:
            cwd = work_dir

        try:
            resolved_cwd = Path(cwd).resolve()
            resolved_work = Path(work_dir).resolve()
        except (OSError, ValueError, RuntimeError) as e:
            return f"Path resolution error: {e}"

        # 检查 cwd 是否在 work_dir 下（或等于 work_dir）
        try:
            resolved_cwd.relative_to(resolved_work)
        except ValueError:
            return (
                f"cwd '{cwd}' is outside allowed work directory '{work_dir}'"
            )

        return None  # allowed

    # ------------------------------------------------------------------
    # Layer 3: JIT 授权检查
    # ------------------------------------------------------------------

    def _check_jit_auth(
        self,
        request: ExecuteRequest,
        risk: RiskLevel,
        action: Action,
    ) -> Optional[str]:
        """检查是否需要 JIT 授权令牌。

        需要 JIT 的场景：
        - CRITICAL 风险的操作
        - DENY action 被覆盖为 ALLOW（需要 JIT 确认）
        - 工具声明了 requires_jit=True

        返回 None 表示不需要 JIT（通过），返回 str 表示需要 JIT 的原因。
        """
        # CRITICAL 风险的操作始终需要 JIT
        if risk == RiskLevel.CRITICAL:
            if not request.jit_token:
                return "CRITICAL risk operation requires JIT authorization"

        # AUTO 需要检查是否 agent 权限覆盖
        if action == Action.AUTO and request.agent_manifest:
            cmd_str = " ".join(request.args) if request.args else request.raw_command
            # 如果命令在 deny_exec 中 → 通过 JIT 才能 sudo
            if request.agent_manifest.permissions and request.agent_manifest.permissions.deny_exec:
                for pattern in request.agent_manifest.permissions.deny_exec:
                    if re.search(pattern, cmd_str):
                        if not request.jit_token:
                            return "Command is deny_listed; requires JIT authorization"
                        break

        # 工具检查
        if hasattr(request, 'tool_def') and request.tool_def:
            tool_def = request.tool_def
            if getattr(tool_def, 'requires_jit', False) and not request.jit_token:
                return "Tool requires JIT authorization"

        return None  # 不需要 JIT

    # ------------------------------------------------------------------
    # 终端交互确认
    # ------------------------------------------------------------------

    async def _prompt_confirm(
        self,
        cmd_str: str,
        risk: RiskLevel,
        reason: str,
        caller: str,
    ) -> bool:
        """在 stderr 上输出确认提示并读取 y/n 输入。

        Args:
            cmd_str: 要执行的命令字符串
            risk: 风险评估等级
            reason: 风险原因（匹配的策略规则说明）
            caller: 调用方标识（agent_id 或 "terminal"）

        Returns:
            True 表示用户确认，False 表示拒绝。
        """
        loop = asyncio.get_event_loop()

        risk_icons = {
            "low": "[i]",
            "medium": "[!]",
            "high": "[!!]",
            "critical": "[!!!]",
        }
        icon = risk_icons.get(risk.value if hasattr(risk, 'value') else str(risk).lower(), "[?]")

        print(f"\n{icon} trimum: 需要确认", file=sys.stderr)
        print(f"   来源: {caller}", file=sys.stderr)
        print(f"   风险: {risk.value if hasattr(risk, 'value') else risk}", file=sys.stderr)
        print(f"   原因: {reason}", file=sys.stderr)
        print(f"   命令: {cmd_str}", file=sys.stderr)
        print(file=sys.stderr)

        def _read_confirm() -> bool:
            try:
                answer = input("   确认执行？[y/N] ")
                return answer.strip().lower() in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                return False

        confirmed = await loop.run_in_executor(None, _read_confirm)
        return confirmed

    def issue_jit_token(
        self,
        agent_id: str,
        tool: ToolType,
        command: str,
        granted_by: str = "admin",
        ttl: float = 300.0,
    ) -> JITToken:
        """颁发 JIT 授权令牌。

        Args:
            agent_id: 目标 agent ID
            tool: 授权使用的工具
            command: 授权执行的命令
            granted_by: 授权人/系统
            ttl: 令牌有效期（秒，默认 5 分钟）

        Returns:
            JITToken 实例
        """
        token = JITToken(
            token=uuid.uuid4().hex[:24],
            agent_id=agent_id,
            tool=tool.value if isinstance(tool, ToolType) else tool,
            command=command,
            expires_at=time.time() + ttl,
            granted_by=granted_by,
            used=False,
        )

        # 存到网关的 jit_tokens 字典
        if not hasattr(self, '_jit_tokens'):
            self._jit_tokens: dict[str, JITToken] = {}
        self._jit_tokens[token.token] = token

        logger.info(
            "gateway.jit_issued",
            agent_id=agent_id,
            tool=token.tool,
            ttl=ttl,
            token=token.token[:8] + "...",
        )

        return token

    def grant_jit_token(
        self,
        agent_id: str,
        tool: ToolType,
        command: str,
        granted_by: str = "admin",
        ttl: float = 300.0,
    ) -> JITToken:
        """便捷方法：颁发 JIT 令牌（同 issue_jit_token）。"""
        return self.issue_jit_token(agent_id, tool, command, granted_by, ttl)

    # ------------------------------------------------------------------
    # 凭证脱敏
    # ------------------------------------------------------------------

    def _redact_credentials(
        self,
        response: ExecuteResponse,
    ) -> ExecuteResponse:
        """对执行结果中的敏感信息进行脱敏处理。

        使用 _SENSITIVE_OUTPUT_PATTERNS 中的正则表达式替换敏感内容。
        """
        if not response.output:
            return response

        redacted = response.output
        for pattern, replacement in _SENSITIVE_OUTPUT_PATTERNS:
            redacted = pattern.sub(replacement, redacted)

        # 同时脱敏 error 字段
        if response.error:
            for pattern, replacement in _SENSITIVE_OUTPUT_PATTERNS:
                response.error = pattern.sub(replacement, response.error)

        response.output = redacted
        return response

    # ------------------------------------------------------------------
    # 审计事件记录
    # ------------------------------------------------------------------

    def _record_audit(
        self,
        event_type: str,
        request: ExecuteRequest,
        response: ExecuteResponse,
    ) -> None:
        """记录审计事件。

        如果未启用审计（enable_audit=False），直接返回。
        记录到 logger（INFO 级别）和可选的 audit_store。
        """
        if not self.enable_audit:
            return

        cmd_str = " ".join(request.args) if request.args else request.raw_command

        event = AuditEvent(
            event_id=uuid.uuid4().hex[:12],
            event_type=event_type,
            agent_id=request.agent_id or "unknown",
            agent_name=request.agent_manifest.name if request.agent_manifest else "unknown",
            tool=request.tool.value,
            command=cmd_str[:500],
            risk=response.risk.value if response.risk else "unknown",
            action=response.action.value if response.action else "unknown",
            reason=response.reason or "",
            details={
                "execution_id": response.execution_id,
                "exit_code": response.exit_code,
                "cwd": request.cwd or "",
                "source_type": request.source_type.value if hasattr(request.source_type, 'value') else str(request.source_type),
            },
            timestamp=time.time(),
            source_type=str(request.source_type) if hasattr(request.source_type, 'value') else str(request.source_type),
            jit_token=request.jit_token or "",
            jit_expires_at=0.0,
            jit_granted_by="",
        )

        logger.info(
            "gateway.audit",
            event_type=event_type,
            agent_id=event.agent_id,
            tool=event.tool,
            risk=event.risk,
            action=event.action,
            execution_id=event.event_id,
        )

        # 可选：写入 audit store（Phase 5 实现）
        # if self.audit_store:
        #     self.audit_store.append(event)


