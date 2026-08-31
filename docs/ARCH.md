# ARCH — trimum Core（Phase 2，已完结）

> 最后更新：2026-08-31。Phase 2 Core 17 个模块全部完成，33 项测试通过。

## 项目结构

```
D:\trimum-phase2\src\trimum_core\
├── __init__.py              # v0.3.0，27 个导出
├── main.py                  # FastAPI 入口 + 启动逻辑
├── config.py                # YAML/环境变量配置加载
├── models.py                # Pydantic 数据模型（含 AgentManifest, ToolDefinition 等）
├── api_server.py            # FastAPI 路由（HTTP + SSE）
├── ipc_handler.py           # JSON-RPC 2.0 over Unix Socket + TCP fallback
├── tool_gateway.py          # Tool Registry + Agent 权限感知（双栈检查）
├── policy_engine.py         # 权限策略引擎
├── event_bus.py             # 异步 pub/sub 事件系统
├── agent_registry.py        # Agent 类型注册表（内存）
├── agent_router.py          # 能力路由 + 管道构建
├── agent_manager.py         # Agent 进程生命周期管理
├── planner_agent.py         # Planner Agent（唯一 LLM 组件，~500 行）
├── workflow_engine.py       # DAG 任务编排引擎（~600 行）
├── context_manager.py       # SQLite 上下文持久化
├── logger.py                # structlog 结构化日志
└── trimum_client.py         # CLI 客户端
```

## 模块依赖图

```
main.py
   │
   ├── config.py ──────────── 配置加载
   │
   ├── api_server.py ──────── HTTP API 路由
   │   ├── tool_gateway.py ── 工具执行
   │   │   ├── policy_engine.py  权限检查
   │   │   └── agent_manager.py  Agent 管理
   │   ├── event_bus.py ──── 事件发布
   │   ├── agent_registry.py    类型注册
   │   ├── agent_router.py      能力路由
   │   ├── workflow_engine.py   工作流执行
   │   ├── planner_agent.py     Planner（LLM）
   │   └── context_manager.py   上下文
   │
   ├── ipc_handler.py ────── Socket 接口
   │
   ├── logger.py ─────────── 日志
   │
   └── models.py ─────────── 所有模块共享的数据模型
```

## 技术选型

| 项 | 选择 | 原因 |
|---|---|---|
| 语言 | Python 3.12+ | AI 生态标准、全栈统一 |
| HTTP 框架 | FastAPI + uvicorn | 异步、类型安全、自动文档 |
| 序列化 | Pydantic v2 | 类型安全、与 Agent SDK 统一 |
| 日志 | structlog | 结构化日志 |
| 数据库 | SQLite (aiosqlite) | 轻量、零配置 |
| YAML | PyYAML | 配置驱动 |
| 进程管理 | psutil | 稳定的进程树管理 |

## API 接口

### POST /api/execute
执行工具命令。
```json
{
  "tool": "shell",
  "args": ["df", "-h"],
  "agent_id": "ai-shell",
  "agent_manifest": { ... }
}
```

### GET/POST /api/workflow/run|list|{name}
工作流编排。

### GET/POST /api/planner/plan|plan-and-run
Planner Agent（LLM 规划+执行）。

### GET /api/agents
Agent 列表。

### POST /api/agents/spawn
启动 Agent。

### GET /api/events
SSE 流——实时事件推送。

## 测试覆盖

| 测试集 | 用例数 | 结果 |
|---|---|---|
| Agent Registry + Router | 10 | ✅ 全部通过 |
| Tool Registry + Permission | 23 | ✅ 全部通过 |
| **合计** | **33** | **全部通过** |

## 部署

```
systemd 服务：/etc/systemd/system/trimum-core.service
用户级运行：systemctl --user start trimum-core
监听端口：8321（HTTP API）
Socket：/run/user/1000/trimum.sock（0700 权限）
配置：~/.config/trimum/config.yaml
数据库：~/.local/share/trimum/context.db
```

## 历史 commit

```
3845a8f — merge: accept local Phase 2 complete over remote
d93b3ac — feat: merge Phase 2 complete (Agent Registry, Router, Planner, Workflow Engine, Tool Gateway)
b393c2c — feat: Tool Gateway overhaul (Tool Registry + agent-aware permissions)
c239d56 — feat: Agent Registry + Agent Router
8b3f45e — feat: IPC layer (JSON-RPC) + trimum-client CLI
183129c — feat: Phase 2 Core - 11 modules, 1366 lines
...
```
