"""trimum Core."""

from trimum_core.agent_registry import AgentRegistry
from trimum_core.tool_file_loader import scan_tools, parse_tool_manifest
from trimum_core.agent_router import AgentRouter, RouteEntry
from trimum_core.agent_runtime import AgentRuntime
from trimum_core.agent_socket import AgentSocketServer, AgentSocketClient, SocketMessage
from trimum_core.behavior_monitor import BehaviorMonitor
from trimum_core.memory_bridge import MemoryBridge
from trimum_core.planner_agent import PlannerAgent
from trimum_core.security_rule import SecurityRule, DecisionResult
from trimum_core.system_monitor import SystemMonitor
from trimum_core.models import (
    Action,
    AgentEvents,
    AgentInfo,
    AgentManifest,
    AgentPermissions,
    AgentStatus,
    AgentTask,
    AgentTaskResult,
    ContextEntry,
    EventSeverity,
    ExecuteRequest,
    ExecuteResponse,
    PolicyRule,
    RiskLevel,
    SpawnRequest,
    SpawnResponse,
    SystemEvent,
    ToolDefinition,
    ToolType,
)
from trimum_core.tool_dispatchers import (
    DispatcherRegistry,
    FileDispatcher,
    GitDispatcher,
    HttpDispatcher,
    ProcessDispatcher,
    SystemDispatcher,
    ShellDispatcher,
    EnvDispatcher,
    KnowledgeDispatcher,
    NotificationDispatcher,
    MCPDispatcher,
    CustomDispatcher,
)
from trimum_core.workflow_engine import (
    EdgeDefinition,
    NodeDefinition,
    NodeStatus,
    WorkflowDefinition,
    WorkflowDefV2,
    WorkflowEngine,
    WorkflowResult,
    WorkflowStatus,
    WorkflowStep,
    WorkflowStepCondition,
)

__version__ = "0.4.0"

__all__ = [
    "Action",
    "AgentEvents",
    "AgentInfo",
    "AgentManifest",
    "AgentPermissions",
    "AgentRegistry",
    "AgentRouter",
    "AgentRuntime",
    "AgentSocketClient",
    "AgentSocketServer",
    "AgentStatus",
    "AgentTask",
    "AgentTaskResult",
    "BehaviorMonitor",
    "ContextEntry",
    "MemoryBridge",
    "CustomDispatcher",
    "DispatcherRegistry",
    "EdgeDefinition",
    "EnvDispatcher",
    "EventSeverity",
    "ExecuteRequest",
    "ExecuteResponse",
    "FileDispatcher",
    "GitDispatcher",
    "HttpDispatcher",
    "KnowledgeDispatcher",
    "MCPDispatcher",
    "NodeDefinition",
    "NodeStatus",
    "NotificationDispatcher",
    "PlannerAgent",
    "PolicyRule",
    "ProcessDispatcher",
    "RiskLevel",
    "RouteEntry",
    "ShellDispatcher",
    "SystemDispatcher",
    "ToolDefinition",
    "ToolFileLoader",
    "parse_tool_manifest",
    "scan_tools",
    "SpawnRequest",
    "SpawnResponse",
    "SocketMessage",
    "SystemEvent",
    "SystemMonitor",
    "DecisionResult",
    "SecurityRule",  # 注意：是 SecurityRule 类，\_\_all\_\_ 列出实际类名
    "ToolType",
    "WorkflowDefinition",
    "WorkflowDefV2",
    "WorkflowEngine",
    "WorkflowResult",
    "WorkflowStatus",
    "WorkflowStep",
    "WorkflowStepCondition",
]
