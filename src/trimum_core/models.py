"""Pydantic models for trimum Core."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


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
