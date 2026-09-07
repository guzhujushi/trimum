# TARL — Trimum AI Representation Language

> **Version:** v1.0-draft
> **Status:** Draft specification
> **Scope:** Agent ↔ Agent communication, Agent ↔ Workflow Engine messaging, memory retrieval

TARL (Trimum AI Representation Language) is a **KV-pair line format** designed for AI-to-system communication. It sits between natural language and machine code — structured enough for deterministic parsing, flexible enough for LLM generation.

## 1. Design Principles

| Principle | Rationale |
|---|---|
| **Minimal token cost** | KV lines are ~60% smaller than equivalent JSON |
| **Deterministic parsing** | `split()` + regex — no parser dependency |
| **FTS5-friendly** | Full-text searchable without flattening |
| **AI-generation stable** | No quote matching, no trailing comma issues (~98% correctness) |
| **Human-readable** | Plain text, self-documenting |

## 2. Format Specification

### 2.1 Basic Syntax

```
key:value key2:value2 key3:value3
```

- Fields are separated by **single space**
- Each field is `key:value`
- Keys are **alphanumeric with dots** (e.g., `cmd`, `user`, `workflow.name`)
- Values are **single tokens** — no spaces by default (Scheme B)
- Values may contain: alphanumeric, underscores, hyphens, dots, slashes
- One line = one message/statement
- Multiple lines = multiple messages / a sequence

### 2.2 Value Encoding Rules

| Rule | Example |
|---|---|
| No spaces | `user:guzhu` ✅ |
| Dots OK | `workflow:blog.deploy` ✅ |
| Slashes OK | `path:/var/www/blog` ✅ |
| Hyphens OK | `tool-type:shell` ✅ |
| Colons in value | Use `_` convention: `time:202609011330` ✅ |

### 2.3 Namespace Convention

Keys should use **dot-notation namespaces** to avoid collisions:

| Prefix | Domain | Example |
|---|---|---|
| `cmd` | Command to execute | `cmd:restart_nginx` |
| `user` | User identifier | `user:guzhu` |
| `workflow` | Workflow name | `workflow:blog_deploy` |
| `trigger` | Trigger source | `trigger:file_change` |
| `snapshot` | Context handoff metadata | `snapshot:task_123` |
| `alert` | Alert type | `alert:ram_high` |
| `status` | Task/agent status | `status:completed` |
| `agent` | Agent type | `agent:coding` |
| `tool` | Tool name | `tool:git` |

### 2.4 Extended Syntax (Future — Scheme A)

```
key:"value with spaces" key2:'also works'
```

Quoted values are reserved for cases where spaces are unavoidable (e.g., natural-language messages, Chinese names that may contain spaces). Not yet implemented.

## 3. Parsing Interface

```
parse_line(line: str) -> dict[str, str]
```

Parses a single TARL line into a dict. For duplicate keys, the last value wins by default.

```
parse_multi(text: str) -> list[dict[str, str]]
```

Parses multi-line TARL into a list of dicts.

```
serialize(data: dict[str, str]) -> str
```

Converts a dict back to a TARL line.

## 4. FTS5 Integration

TARL's KV line format works naturally with FTS5:

```sql
-- Create FTS table
CREATE VIRTUAL TABLE tarl_fts USING fts5(
    raw_text,         -- full TARL line
    content=''        -- contentless
);

-- Search: find all lines containing "cmd:restart_nginx"
SELECT raw_text FROM tarl_fts
WHERE raw_text MATCH 'cmd:restart_nginx';

-- Prefix search: find all cmd:* entries
SELECT raw_text FROM tarl_fts
WHERE raw_text MATCH 'cmd:*';

-- Multi-key search: cmd + specific user
SELECT raw_text FROM tarl_fts
WHERE raw_text MATCH 'cmd:restart_nginx AND user:guzhu';
```

This allows the **Context Manager** to store and search TARL messages without any JSON flattening step.

### 4.1 Stored as-is

After Flightweight → TARL transformation, the TARL line is stored directly:
```
cmd:restart_nginx user:guzhu time:202609011330 workflow:blog_deploy
```

The Workflow Engine then:
1. Matches `workflow:blog_deploy` → loads the matching preset
2. Falls back to `cmd:restart_nginx` → direct execution
3. Falls back further → Planner Agent

## 5. Handoff Snapshot (Warp-inspired)

When one Agent passes context to another via TARL, the receiving Agent only gets the **minimum context** required:

```
task:fix_blog_deploy
snapshot:ctx_abc123
workspace:/var/www/blog
error:nginx_502
target:restore_api
permission:project_write
artifacts:logs/nginx_error.log
```

This implements the **Minimum Context Principle**: don't copy history, only pass task context.

## 6. Task State (Warp-inspired)

TARL messages carry state transition metadata:

```
status:created
```
↓
```
status:queued
```
↓
```
status:dispatching
```
↓
```
status:running
```
↓ (normal path)
```
status:completed
```
↓ (error paths)
```
status:failed    reason:connection_timeout
status:timeout   reason:exceeded_120s
status:cancelled reason:user_interrupt
status:blocked   reason:missing_permission
```

## 7. Examples

**User instruction → Transform Agent output:**

Input:
```
帮我重启博客的 nginx
```

Output (TARL):
```
cmd:restart_nginx user:guzhu workflow:blog_deploy trigger:user_input
```

**Workflow → Agent task:**

```
task:fix_blog_deploy agent:coding workspace:/var/www/blog permission:project_write
```

**Agent → Event Bus (completion):**

```
status:completed task:fix_blog_deploy agent:coding result:nginx_restarted
```

**System Monitor → Event Bus (alert):**

```
alert:ram_high value:85% threshold:80% host:blog-server workflow:diagnostic
```

## 8. Implementation Phases

| Phase | Component | File |
|---|---|---|
| 1 | TARL parser + serializer | `trimum_core/tarl_parser.py` |
| 2 | Transform Agent (NL→TARL) | `trimum_core/transform_agent.py` |
| 3 | Workflow Engine match() | `trimum_core/workflow_engine.py` |
| 4 | Security Agent integration | `trimum_core/security_agent.py` |
| 5 | FTS5 storage adapter | `trimum_core/context_manager.py` |
| 6 | Stability testing suite | `tests/test_tarl_stability.py` |
