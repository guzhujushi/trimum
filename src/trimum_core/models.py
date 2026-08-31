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
