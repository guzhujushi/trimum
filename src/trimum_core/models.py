"""Pydantic models for trimum Core."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


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

    SHELL = "shell"
    GIT = "git"
    DOCKER = "docker"
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
    permissions: AgentPermissions
    events: AgentEvents
    entry: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    # 长期提示词文件路径（类 AGENTS.md），减少每次调用注入的 tokens
    system_prompt_path: str = ""
    system_prompt: str = ""


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


class AgentTaskResult(BaseModel):
    """Agent → Workflow Engine 的任务结果。

    通过 Event Bus 的 task.node.completed / task.node.failed 事件传递。
    """

    task_id: str = ""
    workflow_id: str = ""
    node_id: str = ""
    source: str = ""  # Agent 名称
    status: str = "completed"  # completed | failed | skipped
    output: Any = None
    output_data: dict[str, Any] = Field(default_factory=dict)  # 结构化输出，供下游节点消费
    error: str = ""
    duration: float = 0.0
    token_estimate: int = 0  # 本次任务消耗的 token 估算
