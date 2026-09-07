"""Pydantic models for trimum Core."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field



class TRMErrorCode(str, Enum):
    """Canonical TRM error codes (TRM-XXXX format).

    Category map:
        TRM-1xxx = Runtime
        TRM-2xxx = Security
        TRM-3xxx = Agent
        TRM-4xxx = Tool
        TRM-5xxx = Workflow
        TRM-6xxx = Memory
        TRM-7xxx = Network
        TRM-8xxx = Config
        TRM-9xxx = Internal
    See docs/ERROR-CODE-SPEC.md for full spec.
    """

    # 1xxx — Runtime
    RUNTIME_INIT_FAILED = "TRM-1001"
    RUNTIME_ALREADY_RUNNING = "TRM-1002"
    RUNTIME_SHUTDOWN_FAILED = "TRM-1003"
    IPC_CONNECTION_FAILED = "TRM-1004"
    IPC_PROTOCOL_ERROR = "TRM-1005"
    PROCESS_SPAWN_FAILED = "TRM-1006"
    TIMEOUT_EXCEEDED = "TRM-1007"

    # 2xxx — Security
    POLICY_DENIED = "TRM-2001"
    THREAT_BLOCKED = "TRM-2002"
    AGENT_FREEZE = "TRM-2003"
    AGENT_KILLED = "TRM-2004"
    JIT_TOKEN_EXPIRED = "TRM-2005"
    JIT_TOKEN_INVALID = "TRM-2006"
    CWD_JAIL_VIOLATION = "TRM-2007"
    CREDENTIAL_LEAK_DETECTED = "TRM-2008"
    RESOURCE_LIMIT_EXCEEDED = "TRM-2009"
    HASH_CHAIN_BROKEN = "TRM-2010"
    UNKNOWN_SOURCE_TYPE = "TRM-2011"

    # 3xxx — Agent
    AGENT_NOT_FOUND = "TRM-3001"
    AGENT_TYPE_UNKNOWN = "TRM-3002"
    AGENT_ALREADY_EXISTS = "TRM-3003"
    AGENT_MANIFEST_INVALID = "TRM-3004"
    AGENT_ENTRY_NOT_FOUND = "TRM-3005"
    AGENT_TASK_TIMEOUT = "TRM-3006"
    AGENT_TASK_FAILED = "TRM-3007"
    HANDOFF_SNAPSHOT_FAILED = "TRM-3008"
    DEPENDENCY_MISSING = "TRM-3009"
    CERTIFICATE_INVALID = "TRM-3010"
    PERMISSION_INSUFFICIENT = "TRM-3011"

    # 4xxx — Tool
    TOOL_NOT_FOUND = "TRM-4001"
    TOOL_EXECUTION_FAILED = "TRM-4002"
    TOOL_TIMEOUT = "TRM-4003"
    TOOL_TYPE_UNSUPPORTED = "TRM-4004"
    FILE_NOT_FOUND = "TRM-4005"
    FILE_PERMISSION_DENIED = "TRM-4006"
    MCP_CALL_FAILED = "TRM-4007"
    MCP_SERVER_NOT_FOUND = "TRM-4008"

    # 5xxx — Workflow
    WORKFLOW_PARSE_ERROR = "TRM-5001"
    WORKFLOW_VALIDATION_FAILED = "TRM-5002"
    WORKFLOW_STATE_INVALID = "TRM-5003"
    WORKFLOW_NODE_NOT_FOUND = "TRM-5004"
    WORKFLOW_CIRCULAR_DEPENDENCY = "TRM-5005"
    WORKFLOW_EXECUTION_FAILED = "TRM-5006"
    WORKFLOW_STEP_TIMEOUT = "TRM-5007"

    # 6xxx — Memory
    MEMORY_STORE_FAILED = "TRM-6001"
    MEMORY_RETRIEVAL_FAILED = "TRM-6002"
    MEMORY_NAMESPACE_NOT_FOUND = "TRM-6003"
    FTS5_SEARCH_FAILED = "TRM-6004"
    MEMORY_DB_CONNECTION_FAILED = "TRM-6005"

    # 7xxx — Network
    HTTP_REQUEST_FAILED = "TRM-7001"
    HTTP_TIMEOUT = "TRM-7002"
    DNS_RESOLUTION_FAILED = "TRM-7003"
    CONNECTION_REFUSED = "TRM-7004"
    RATE_LIMIT_EXCEEDED = "TRM-7005"
    LLM_CALL_FAILED = "TRM-7006"
    LLM_RESPONSE_INVALID = "TRM-7007"

    # 8xxx — Config
    CONFIG_FILE_NOT_FOUND = "TRM-8001"
    CONFIG_PARSE_FAILED = "TRM-8002"
    CONFIG_VALIDATION_FAILED = "TRM-8003"
    ENV_VARIABLE_MISSING = "TRM-8004"

    # 9xxx — Internal
    ASSERTION_FAILED = "TRM-9001"
    UNREACHABLE_CODE = "TRM-9002"
    NOT_IMPLEMENTED = "TRM-9003"
    INTERNAL_STATE_CORRUPTED = "TRM-9004"
    EVENT_BUS_DISPATCH_FAILED = "TRM-9005"

    @property
    def category(self) -> str:
        """Return the category name (runtime, security, agent, ...)."""
        digit = self.value[4]  # '1' for TRM-1xxx
        return {
            "1": "runtime",
            "2": "security",
            "3": "agent",
            "4": "tool",
            "5": "workflow",
            "6": "memory",
            "7": "network",
            "8": "config",
            "9": "internal",
        }.get(digit, "unknown")

    @property
    def http_status(self) -> int:
        """Recommended HTTP status code for this error."""
        code = int(self.value[4:])
        if 1001 <= code <= 1999:
            return 500
        if 2001 <= code <= 2999:
            if code in (2005, 2006):
                return 401
            return 403
        if 3001 <= code <= 3999:
            if code in (3001, 3002, 3005):
                return 404
            if code == 3003:
                return 409
            return 400
        if 4001 <= code <= 4999:
            if code in (4005,):
                return 404
            if code == 4006:
                return 403
            return 500
        if 5001 <= code <= 5999:
            return 422
        if 6001 <= code <= 6999:
            return 500
        if 7001 <= code <= 7999:
            if code in (7002,):
                return 504
            return 502
        if 8001 <= code <= 8999:
            return 500
        if 9001 <= code <= 9999:
            return 500
        return 500

    @property
    def log_level(self) -> str:
        """Recommended logging level."""
        code = int(self.value[4:])
        if 1001 <= code <= 1999:
            return "ERROR"
        if 2001 <= code <= 2999:
            if code in (2003, 2004):
                return "CRITICAL"
            return "WARNING"
        if 3001 <= code <= 3999:
            return "ERROR"
        if 4001 <= code <= 4999:
            return "WARNING"
        if 5001 <= code <= 5999:
            return "ERROR"
        if 6001 <= code <= 6999:
            return "WARNING"
        if 7001 <= code <= 7999:
            return "WARNING"
        if 8001 <= code <= 8999:
            return "ERROR"
        if 9001 <= code <= 9999:
            return "CRITICAL"
        return "ERROR"


class TrimumError(Exception):
    """Base exception for all trimum errors with a TRM error code.

    Usage:
        raise TrimumError(TRMErrorCode.AGENT_NOT_FOUND)
        raise TrimumError(TRMErrorCode.AGENT_NOT_FOUND, message="...")
        raise TrimumError(
            TRMErrorCode.TOOL_EXECUTION_FAILED,
            message="git push failed",
            context={"exit_code": 128}
        )
    """

    def __init__(
        self,
        code: TRMErrorCode,
        message: str = "",
        context: dict | None = None,
    ):
        self.code = code if isinstance(code, TRMErrorCode) else TRMErrorCode(code)
        self.message = message or self._default_message()
        self.context = context or {}
        super().__init__(f"[{self.code.value}] {self.message}")

    @property
    def category(self) -> str:
        return self.code.category

    @property
    def http_status(self) -> int:
        return self.code.http_status

    @property
    def log_level(self) -> str:
        return self.code.log_level

    def _default_message(self) -> str:
        """Human-readable default message for each error code."""
        messages = {
            TRMErrorCode.RUNTIME_INIT_FAILED: "Core runtime failed to initialize",
            TRMErrorCode.RUNTIME_ALREADY_RUNNING: "Runtime is already running",
            TRMErrorCode.RUNTIME_SHUTDOWN_FAILED: "Runtime shutdown failed to complete gracefully",
            TRMErrorCode.IPC_CONNECTION_FAILED: "IPC connection failed",
            TRMErrorCode.IPC_PROTOCOL_ERROR: "IPC protocol error",
            TRMErrorCode.PROCESS_SPAWN_FAILED: "Failed to spawn child process",
            TRMErrorCode.TIMEOUT_EXCEEDED: "Operation exceeded configured timeout",
            TRMErrorCode.POLICY_DENIED: "Command explicitly denied by policy engine",
            TRMErrorCode.THREAT_BLOCKED: "Threat matched and blocked by SecMonitor",
            TRMErrorCode.AGENT_FREEZE: "Agent frozen via SIGSTOP by security action",
            TRMErrorCode.AGENT_KILLED: "Agent terminated via SIGKILL by security action",
            TRMErrorCode.JIT_TOKEN_EXPIRED: "JIT authorization token has expired",
            TRMErrorCode.JIT_TOKEN_INVALID: "JIT token is malformed or not found",
            TRMErrorCode.CWD_JAIL_VIOLATION: "Command attempted to access path outside cwd jail",
            TRMErrorCode.CREDENTIAL_LEAK_DETECTED: "Potential credential leak in command output",
            TRMErrorCode.RESOURCE_LIMIT_EXCEEDED: "Agent exceeded CPU/memory/IO quota",
            TRMErrorCode.HASH_CHAIN_BROKEN: "Audit log hash chain integrity check failed",
            TRMErrorCode.UNKNOWN_SOURCE_TYPE: "Operation from unknown/untrusted source type",
            TRMErrorCode.AGENT_NOT_FOUND: "Agent with given ID not found",
            TRMErrorCode.AGENT_TYPE_UNKNOWN: "Unknown agent type in manifest",
            TRMErrorCode.AGENT_ALREADY_EXISTS: "Agent with given ID already registered",
            TRMErrorCode.AGENT_MANIFEST_INVALID: "Agent manifest failed validation",
            TRMErrorCode.AGENT_ENTRY_NOT_FOUND: "Agent entry point not found",
            TRMErrorCode.AGENT_TASK_TIMEOUT: "Agent task exceeded its timeout",
            TRMErrorCode.AGENT_TASK_FAILED: "Agent task completed with failure",
            TRMErrorCode.HANDOFF_SNAPSHOT_FAILED: "Failed to create handoff snapshot",
            TRMErrorCode.DEPENDENCY_MISSING: "Agent's declared dependency is unavailable",
            TRMErrorCode.CERTIFICATE_INVALID: "Agent certificate validation failed",
            TRMErrorCode.PERMISSION_INSUFFICIENT: "Agent lacks declared permission for operation",
            TRMErrorCode.TOOL_NOT_FOUND: "Requested tool is not registered",
            TRMErrorCode.TOOL_EXECUTION_FAILED: "Tool execution returned non-zero exit",
            TRMErrorCode.TOOL_TIMEOUT: "Tool execution exceeded timeout",
            TRMErrorCode.TOOL_TYPE_UNSUPPORTED: "Requested tool type has no handler registered",
            TRMErrorCode.FILE_NOT_FOUND: "File or path does not exist",
            TRMErrorCode.FILE_PERMISSION_DENIED: "Insufficient permissions to access file",
            TRMErrorCode.MCP_CALL_FAILED: "MCP tool call returned error",
            TRMErrorCode.MCP_SERVER_NOT_FOUND: "MCP server not connected or not found",
            TRMErrorCode.WORKFLOW_PARSE_ERROR: "Workflow YAML failed to parse",
            TRMErrorCode.WORKFLOW_VALIDATION_FAILED: "Workflow schema validation failed",
            TRMErrorCode.WORKFLOW_STATE_INVALID: "Workflow state machine transition not allowed",
            TRMErrorCode.WORKFLOW_NODE_NOT_FOUND: "Referenced workflow node does not exist",
            TRMErrorCode.WORKFLOW_CIRCULAR_DEPENDENCY: "Workflow contains circular dependency",
            TRMErrorCode.WORKFLOW_EXECUTION_FAILED: "Workflow execution terminated with error",
            TRMErrorCode.WORKFLOW_STEP_TIMEOUT: "Workflow step exceeded its timeout",
            TRMErrorCode.MEMORY_STORE_FAILED: "Failed to store entry in context memory",
            TRMErrorCode.MEMORY_RETRIEVAL_FAILED: "Failed to retrieve entry from context memory",
            TRMErrorCode.MEMORY_NAMESPACE_NOT_FOUND: "Requested memory namespace does not exist",
            TRMErrorCode.FTS5_SEARCH_FAILED: "Full-text search query failed",
            TRMErrorCode.MEMORY_DB_CONNECTION_FAILED: "Failed to connect to memory database",
            TRMErrorCode.HTTP_REQUEST_FAILED: "HTTP request returned non-2xx status",
            TRMErrorCode.HTTP_TIMEOUT: "HTTP request exceeded timeout",
            TRMErrorCode.DNS_RESOLUTION_FAILED: "Failed to resolve hostname",
            TRMErrorCode.CONNECTION_REFUSED: "Remote endpoint refused connection",
            TRMErrorCode.RATE_LIMIT_EXCEEDED: "External API rate limit hit",
            TRMErrorCode.LLM_CALL_FAILED: "LLM API call returned error",
            TRMErrorCode.LLM_RESPONSE_INVALID: "LLM response failed to parse or validate",
            TRMErrorCode.CONFIG_FILE_NOT_FOUND: "Config file not found at expected path",
            TRMErrorCode.CONFIG_PARSE_FAILED: "Config file failed to parse",
            TRMErrorCode.CONFIG_VALIDATION_FAILED: "Config field validation failed",
            TRMErrorCode.ENV_VARIABLE_MISSING: "Required environment variable is not set",
            TRMErrorCode.ASSERTION_FAILED: "Internal invariant assertion failed",
            TRMErrorCode.UNREACHABLE_CODE: "Reached code path that should be unreachable",
            TRMErrorCode.NOT_IMPLEMENTED: "Feature or method not yet implemented",
            TRMErrorCode.INTERNAL_STATE_CORRUPTED: "Internal data structure in an inconsistent state",
            TRMErrorCode.EVENT_BUS_DISPATCH_FAILED: "Failed to dispatch event to registered listeners",
        }
        return messages.get(self.code, f"Unknown error: {self.code}")


class SourceType(str, Enum):
    """流量源类型 — AI Agent、人类、Workflow。"""

    HUMAN = "human"
    AI = "ai"
    WORKFLOW = "workflow"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    """Risk level for a tool/command execution."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Action(str, Enum):
    """Policy action."""

    AUTO = "auto"
    CONFIRM = "confirm"
    DENY = "deny"


class ToolType(str, Enum):
    """Supported tool types."""

    SHELL = "shell"          # Raw shell command execution
    FILE_READ = "file.read"   # Read file contents
    FILE_WRITE = "file.write"  # Write file contents
    FILE_DELETE = "file.delete"
    FILE_LIST = "file.list"   # List directory contents
    FILE_MOVE = "file.move"
    FILE_COPY = "file.copy"
    FILE_SEARCH = "file.search"  # grep/rg search in files
    GIT = "git"               # Generic git operations
    GIT_STATUS = "git.status"
    GIT_DIFF = "git.diff"
    GIT_LOG = "git.log"
    GIT_COMMIT = "git.commit"
    GIT_PUSH = "git.push"
    GIT_PULL = "git.pull"
    GIT_BRANCH = "git.branch"
    HTTP = "http"             # Generic HTTP
    HTTP_GET = "http.get"
    HTTP_POST = "http.post"
    PROCESS = "process"       # Generic process operations
    PROCESS_LIST = "process.list"
    PROCESS_KILL = "process.kill"
    SYSTEM = "system"         # Generic system info
    SYSTEM_INFO = "system.info"
    SYSTEM_DISK = "system.disk"
    SYSTEM_MEMORY = "system.memory"
    KNOWLEDGE_SEARCH = "knowledge.search"
    KNOWLEDGE_STORE = "knowledge.store"
    NOTIFICATION = "notification"
    NOTIFICATION_SEND = "notification.send"
    MCP_TOOLS_LIST = "mcp.tools.list"
    MCP_TOOLS_CALL = "mcp.tools.call"
    ENV_GET = "env.get"
    ENV_LIST = "env.list"
    CUSTOM = "custom"


class ExecuteRequest(BaseModel):
    """Request to execute a tool via Tool Gateway."""

    tool: ToolType = ToolType.SHELL
    args: list[str] = Field(default_factory=list)
    agent_id: Optional[str] = None
    agent_manifest: Optional[AgentManifest] = None
    timeout_seconds: float = 30.0
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    source_type: SourceType = SourceType.UNKNOWN
    # JIT 授权令牌
    jit_token: Optional[str] = None
    # 原始命令（执行前保留，用于审计/脱敏）
    raw_command: str = ""
    # 是否跳过 cwd jail 检查（默认不跳过）
    skip_cwd_check: bool = False


class ExecuteResponse(BaseModel):
    """Response from Tool Gateway."""

    execution_id: str = ""
    status: str = ""  # allowed | confirmed | denied
    output: str = ""
    error: str = ""
    exit_code: int = 0
    risk: RiskLevel = RiskLevel.LOW
    action: Action = Action.AUTO
    reason: str = ""


class AgentStatus(str, Enum):
    """Agent lifecycle status."""

    INITIALIZED = "initialized"
    RUNNING = "running"
    WAITING_TOOL = "waiting_tool"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class AgentInfo(BaseModel):
    """Agent information."""

    agent_id: str
    agent_type: str
    status: AgentStatus = AgentStatus.INITIALIZED
    pid: Optional[int] = None
    uptime: float = 0.0
    config: dict[str, Any] = Field(default_factory=dict)


class SpawnRequest(BaseModel):
    """Request to spawn a new agent."""

    agent_type: str
    agent_id: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class SpawnResponse(BaseModel):
    """Response from spawning an agent."""

    agent_id: str
    status: AgentStatus
    pid: Optional[int] = None
    message: str = ""


class EventSeverity(str, Enum):
    """Event severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SystemEvent(BaseModel):
    """System event for Event Bus."""

    event_type: str  # e.g. "agent.started", "tool.executed", "policy.denied"
    source: str  # e.g. "agent.healthy", "core"
    source_type: SourceType = SourceType.UNKNOWN
    severity: EventSeverity = EventSeverity.INFO
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[float] = None


class ContextEntry(BaseModel):
    """A single context memory entry."""

    key: str
    value: Any
    namespace: str = "default"
    ttl_seconds: Optional[float] = None  # None = permanent


class PolicyRule(BaseModel):
    """A single policy rule."""

    pattern: str
    risk: RiskLevel = RiskLevel.MEDIUM
    action: Action = Action.CONFIRM
    description: str = ""


class AgentPermissions(BaseModel):
    """Permissions declared by an agent manifest."""

    read: list[str] = []
    write: list[str] = []
    exec: list[str] = []
    deny_exec: list[str] = []


class AgentEvents(BaseModel):
    """Events an agent publishes or subscribes to."""

    publishes: list[str] = []
    subscribes: list[str] = []


class ToolDefinition(BaseModel):
    """A registered tool that can be executed via ToolGateway."""

    name: str
    description: str = ""
    tool_type: ToolType = ToolType.SHELL
    executable: str = ""
    allowed_flags: list[str] = Field(default_factory=list)
    timeout_default: float = 30.0
    risk_level: RiskLevel = RiskLevel.MEDIUM


class AgentManifest(BaseModel):
    """Agent type manifest loaded from agent.json."""

    name: str
    version: str
    description: str = ""
    capabilities: list[str]
    depends_on: list[str] = []  # 依赖的 CLI/MCP 工具列表
    permissions: AgentPermissions
    events: AgentEvents
    entry: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    # 长期提示词文件路径（类 AGENTS.md），减少每次调用注入的 tokens
    system_prompt_path: str = ""
    system_prompt: str = ""
    # 工作目录限制（cwd jail）
    work_dir: str = ""  # 允许访问的工作目录根路径，空=不限制


# ── Agent 任务通信模型 ──────────────────────────────────

class AgentTask(BaseModel):
    """Workflow Engine → Agent 的任务对象（通过 Event Bus 传递）。

    设计原则：
    - 轻量，只包含 Agent 执行所需的最小信息
    - 输入数据通过 input_from 或 input_data 传递
    - 长期提示词通过 AgentManifest.system_prompt 加载
    """

    task_id: str = ""
    workflow_id: str = ""
    node_id: str = ""
    agent_type: str = ""
    instruction: str = ""  # 本次任务的提示词（短，只描述要做什么）
    input_data: dict[str, Any] = Field(default_factory=dict)  # 上层/前驱节点的输出
    input_from: list[str] = Field(default_factory=list)  # 依赖的前驱节点 ID 列表
    config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 120.0


# ── 审计事件模型 ──────────────────────────────────


class AuditEvent(BaseModel):
    """安全审计事件记录。"""

    event_id: str = ""
    event_type: str = ""  # cwd_jail | credential_redact | jit_auth | tool_executed | policy_denied
    agent_id: str = ""
    agent_name: str = ""
    tool: str = ""
    command: str = ""
    risk: str = ""
    action: str = ""
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = 0.0
    source_type: str = ""
    # JIT 授权相关
    jit_token: str = ""
    jit_expires_at: float = 0.0
    jit_granted_by: str = ""  # "auto" | "human"


class JITToken(BaseModel):
    """JIT（Just-In-Time）授权令牌。"""

    token: str = ""
    agent_id: str = ""
    tool: str = ""
    command: str = ""
    expires_at: float = 0.0
    granted_by: str = ""  # "auto" | "human"
    used: bool = False


class AgentTaskResult(BaseModel):
    """Agent → Workflow Engine 的任务结果。

    通过 Event Bus 的 task.node.completed / task.node.failed 事件传递。
    """

    task_id: str = ""


# ═══════════════════════════════════════════════════════════════════
# Security Agent 类型
# ═══════════════════════════════════════════════════════════════════


class ThreatCategory(str, Enum):
    """威胁分类。"""
    PRIV_ESCAPE = "priv_escape"
    MALWARE = "malware"
    DATA_THEFT = "data_theft"
    C2_BOTNET = "c2_botnet"
    SUPPLY_CHAIN = "supply_chain"
    LLM_ATTACK = "llm_attack"


class DefenseAction(str, Enum):
    """防御动作。"""
    DENY = "deny"
    CONFIRM = "confirm"
    ALLOW = "allow"
    FREEZE = "freeze"          # SIGSTOP
    KILL = "kill"               # SIGKILL
    ISOLATE = "isolate"         # 网络/沙箱隔离
    WORKFLOW = "workflow"       # 触发工作流


class OpContext(str, Enum):
    """操作上下文标记。"""
    NORMAL = "normal"
    DOWNLOAD_THEN_EXEC = "download_then_exec"
    WRITE_THEN_EXEC = "write_then_exec"
    WRITE_THEN_ENCRYPT = "write_then_encrypt"
    KEY_STEAL = "key_steal"
    SUID_STORM = "suid_storm"
    CLONE_THEN_BUILD = "clone_then_build"
    FIRST_TIME_OP = "first_time_op"
    COMPILE_THEN_EXEC = "compile_then_exec"


class SecVerdict(str, Enum):
    """安全裁决结果。"""
    ALLOW = "allow"
    BLOCK = "block"
    CONFIRM = "confirm"
    FREEZE = "freeze"


class ThreatMatch(BaseModel):
    """ThreatMatcher 的输出：一个威胁匹配结果。"""

    threat_name: str = ""
    category: ThreatCategory = ThreatCategory.MALWARE
    defense: DefenseAction = DefenseAction.ALLOW
    confidence: float = 0.0
    matched_pattern: str = ""
    workflow_name: str = ""     # 非空则触发对应工作流
    reason: str = ""

    class Config:
        use_enum_values = True


class AuditRecord(BaseModel):
    """安全审计记录（含 hash 链完整性字段）。"""

    timestamp: float = 0.0
    event_id: str = ""
    agent_id: str = ""
    command: str = ""
    threat: str = ""
    verdict: str = ""
    reason: str = ""
    context: str = "normal"
    sandbox: str = "default"
    layer_hit: str = ""
    prev_hash: str = ""
    hmac: str = ""
    workflow_id: str = ""
    node_id: str = ""
    source: str = ""  # Agent 名称
    status: str = "completed"  # completed | failed | skipped
    output: Any = None
    output_data: dict[str, Any] = Field(default_factory=dict)  # 结构化输出，供下游节点消费
    error: str = ""
    duration: float = 0.0
    token_estimate: int = 0  # 本次任务消耗的 token 估算
