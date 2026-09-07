# TRM Error Code Specification

> **Status:** Draft · **Last updated:** 2026-09-07
> **Adopted from:** DeepSeek Review Suggestion ✅

---

## 1. Format

All trimum error codes follow a **three-part format**:

```
TRM-<Category><Number>
```

- **`TRM`** — Fixed prefix identifying trimum system errors
- **`<Category>`** — Single digit: error domain
- **`<Number>`** — Three digits: unique error within category

**Examples:** `TRM-1001`, `TRM-2005`, `TRM-3003`

---

## 2. Category Map

| Code Range | Category | Description |
|-----------|----------|-------------|
| TRM-1xxx | Runtime | Core runtime, process, IPC, startup/shutdown |
| TRM-2xxx | Security | Policy engine, access control, audit, threat match |
| TRM-3xxx | Agent | Agent lifecycle, manifest, task execution, handoff |
| TRM-4xxx | Tool | Tool gateway, tool execution, MCP, file operations |
| TRM-5xxx | Workflow | Workflow engine, YAML parsing, state machine |
| TRM-6xxx | Memory | Context manager, FTS5, persistence |
| TRM-7xxx | Network | HTTP requests, external API calls |
| TRM-8xxx | Config | Configuration loading, validation, environment |
| TRM-9xxx | Internal | Assertion failures, invariants, unreachable code |

---

## 3. Error Code Listing

### 1xxx — Runtime

| Code | Name | Description |
|------|------|-------------|
| TRM-1001 | RuntimeInitFailed | Core runtime failed to initialize |
| TRM-1002 | RuntimeAlreadyRunning | Attempted to start runtime that is already running |
| TRM-1003 | RuntimeShutdownFailed | Runtime shutdown failed to complete gracefully |
| TRM-1004 | IPCConnectionFailed | IPC (Unix socket / named pipe) connection failed |
| TRM-1005 | IPCProtocolError | IPC message format or sequence violation |
| TRM-1006 | ProcessSpawnFailed | Failed to spawn child process |
| TRM-1007 | TimeoutExceeded | Operation exceeded configured timeout |

### 2xxx — Security

| Code | Name | Description |
|------|------|-------------|
| TRM-2001 | PolicyDenied | Command explicitly denied by policy engine |
| TRM-2002 | ThreatBlocked | Threat matched and blocked by SecMonitor |
| TRM-2003 | AgentFreeze | Agent frozen via SIGSTOP by security action |
| TRM-2004 | AgentKilled | Agent terminated via SIGKILL by security action |
| TRM-2005 | JITTokenExpired | JIT authorization token has expired |
| TRM-2006 | JITTokenInvalid | JIT token is malformed or not found |
| TRM-2007 | CwdJailViolation | Command attempted to access path outside cwd jail |
| TRM-2008 | CredentialLeakDetected | Potential credential leak in command output |
| TRM-2009 | ResourceLimitExceeded | Agent exceeded CPU/memory/IO quota |
| TRM-2010 | HashChainBroken | Audit log hash chain integrity check failed |
| TRM-2011 | UnknownSourceType | Operation from unknown/untrusted source type |

### 3xxx — Agent

| Code | Name | Description |
|------|------|-------------|
| TRM-3001 | AgentNotFound | Agent with given ID not found |
| TRM-3002 | AgentTypeUnknown | Unknown agent type in manifest |
| TRM-3003 | AgentAlreadyExists | Agent with given ID already registered |
| TRM-3004 | AgentManifestInvalid | Agent manifest (agent.json5) failed validation |
| TRM-3005 | AgentEntryNotFound | Agent entry point (main.py) not found |
| TRM-3006 | AgentTaskTimeout | Agent task exceeded its timeout |
| TRM-3007 | AgentTaskFailed | Agent task completed with failure |
| TRM-3008 | HandoffSnapshotFailed | Failed to create handoff snapshot between agents |
| TRM-3009 | DependencyMissing | Agent's declared dependency (CLI/MCP tool) is unavailable |
| TRM-3010 | CertificateInvalid | Agent certificate validation failed |
| TRM-3011 | PermissionInsufficient | Agent lacks declared permission for operation |

### 4xxx — Tool

| Code | Name | Description |
|------|------|-------------|
| TRM-4001 | ToolNotFound | Requested tool is not registered |
| TRM-4002 | ToolExecutionFailed | Tool execution returned non-zero exit |
| TRM-4003 | ToolTimeout | Tool execution exceeded timeout |
| TRM-4004 | ToolTypeUnsupported | Requested tool type has no handler registered |
| TRM-4005 | FileNotFound | File or path does not exist |
| TRM-4006 | FilePermissionDenied | Insufficient permissions to access file |
| TRM-4007 | MCPCallFailed | MCP tool call returned error |
| TRM-4008 | McpServerNotFound | MCP server not connected or not found |

### 5xxx — Workflow

| Code | Name | Description |
|------|------|-------------|
| TRM-5001 | WorkflowParseError | YAML workflow file failed to parse |
| TRM-5002 | WorkflowValidationFailed | Workflow schema validation failed |
| TRM-5003 | WorkflowStateInvalid | Workflow state machine transition not allowed |
| TRM-5004 | WorkflowNodeNotFound | Referenced workflow node does not exist |
| TRM-5005 | WorkflowCircularDependency | Workflow contains circular dependency |
| TRM-5006 | WorkflowExecutionFailed | Workflow execution terminated with error |
| TRM-5007 | WorkflowStepTimeout | Workflow step exceeded its timeout |

### 6xxx — Memory

| Code | Name | Description |
|------|------|-------------|
| TRM-6001 | MemoryStoreFailed | Failed to store entry in context memory |
| TRM-6002 | MemoryRetrievalFailed | Failed to retrieve entry from context memory |
| TRM-6003 | MemoryNamespaceNotFound | Requested memory namespace does not exist |
| TRM-6004 | FTS5SearchFailed | Full-text search query failed |
| TRM-6005 | MemoryDbConnectionFailed | Failed to connect to memory SQLite database |

### 7xxx — Network

| Code | Name | Description |
|------|------|-------------|
| TRM-7001 | HTTPRequestFailed | HTTP request returned non-2xx status |
| TRM-7002 | HTTPTimeout | HTTP request exceeded timeout |
| TRM-7003 | DNSResolutionFailed | Failed to resolve hostname |
| TRM-7004 | ConnectionRefused | Remote endpoint refused connection |
| TRM-7005 | RateLimitExceeded | External API rate limit hit |
| TRM-7006 | LLMCallFailed | LLM API call returned error |
| TRM-7007 | LLMResponseInvalid | LLM response failed to parse or validate |

### 8xxx — Config

| Code | Name | Description |
|------|------|-------------|
| TRM-8001 | ConfigFileNotFound | Configuration file not found at expected path |
| TRM-8002 | ConfigParseFailed | Configuration file failed to parse |
| TRM-8003 | ConfigValidationFailed | Configuration field validation failed |
| TRM-8004 | EnvironmentVariableMissing | Required environment variable is not set |

### 9xxx — Internal

| Code | Name | Description |
|------|------|-------------|
| TRM-9001 | AssertionFailed | Internal invariant assertion failed |
| TRM-9002 | UnreachableCode | Reached code path that should be unreachable |
| TRM-9003 | NotImplemented | Feature or method not yet implemented |
| TRM-9004 | InternalStateCorrupted | Internal data structure in an inconsistent state |
| TRM-9005 | EventBusDispatchFailed | Failed to dispatch event to registered listeners |

---

## 4. Usage in Python Code

### Raising Errors

```python
from trimum_core.models import TrimumError, ErrorCode

# With default message
raise TrimumError(ErrorCode.AGENT_NOT_FOUND)

# With custom message
raise TrimumError(
    ErrorCode.AGENT_NOT_FOUND,
    message=f"Agent '{agent_id}' not found in registry"
)

# With both message and context
raise TrimumError(
    ErrorCode.TOOL_EXECUTION_FAILED,
    message="git push returned exit code 128",
    context={"tool": "git", "exit_code": 128, "stderr": "..."}
)
```

### Catching Errors

```python
from trimum_core.models import TrimumError, ErrorCode

try:
    agent_registry.get("non_existent")
except TrimumError as e:
    print(f"[{e.code}] {e.message}")   # [TRM-3001] ...
    print(f"Category: {e.category}")   # agent
    print(f"HTTP-like: {e.http_status}")  # 404
```

### In Agent Manifest

```yaml
# agent.json5
{
  name: "my-agent",
  permissions: {
    read: ["/tmp/allowed"],
  },
  errors: ["TRM-3001", "TRM-3002", "TRM-4001"]
  // declares which errors this agent can handle
}
```

---

## 5. HTTP Status Mapping

| Error Category | Recommended HTTP Status | When to Use |
|---------------|------------------------|-------------|
| 1xxx Runtime | 500 Internal Server Error | Unexpected runtime failures |
| 2xxx Security | 403 Forbidden | Policy denial, threat blocked |
| 2xxx Security (auth) | 401 Unauthorized | JIT token expired/invalid |
| 3xxx Agent (not found) | 404 Not Found | Agent or manifest not found |
| 3xxx Agent (exists) | 409 Conflict | Duplicate agent registration |
| 4xxx Tool (not found) | 404 Not Found | Tool not registered |
| 4xxx Tool (perm) | 403 Forbidden | File permission denied |
| 5xxx Workflow | 422 Unprocessable Entity | Workflow parse/validation failure |
| 6xxx Memory | 500 Internal Server Error | Memory store/retrieval failure |
| 7xxx Network | 502 Bad Gateway | External service unreachable |
| 7xxx Network (timeout) | 504 Gateway Timeout | External service timeout |
| 8xxx Config | 500 Internal Server Error | Config loading failure |
| 9xxx Internal | 500 Internal Server Error | Internal invariant failure |

---

## 6. Error Code Registry (source of truth)

The canonical registry of all error codes lives in:

- **Python enum:** `src/trimum_core/models.py` — `class ErrorCode(str, Enum)`
- **This document:** `docs/ERROR-CODE-SPEC.md` — human reference

When adding new error codes:
1. Add the enum member in `models.py`
2. Add the listing in this document
3. Add corresponding test in `tests/test_error_codes.py`

---

## 7. Logging Convention

All `TrimumError` instances should be logged at the appropriate level:

| Code Range | Log Level | Example |
|-----------|-----------|---------|
| 1xxx | `ERROR` | Runtime failure, process spawn fail |
| 2xxx | `WARNING` | Policy denial (non-critical) |
| 2xxx (kill/freeze) | `CRITICAL` | Agent kill/freeze by security |
| 3xxx | `ERROR` | Agent not found, task failed |
| 4xxx | `WARNING` | Tool not found, file not found |
| 5xxx | `ERROR` | Workflow parse/execution fail |
| 6xxx | `WARNING` | Memory store failure |
| 7xxx | `WARNING` | Network/LLM call failure |
| 8xxx | `ERROR` | Config load failure |
| 9xxx | `CRITICAL` | Unreachable code, corrupted state |

```python
import logging
logger = logging.getLogger("trimum")

try:
    ...
except TrimumError as e:
    logger.log(e.log_level, "[%s] %s", e.code, e.message)
```
