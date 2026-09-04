# ARCH — trimum Core（Phase 2～3.5，持续更新）

> 最后更新：2026-09-04。28 个模块，9010 行代码，135 项测试通过。

## 项目结构

```
D:\trimum\src\trimum_core\
├── __init__.py              # v0.4.0，大量导出
├── main.py                  # FastAPI 入口 + 启动逻辑
├── config.py                # YAML/环境变量配置加载
├── models.py                # Pydantic 数据模型（AgentManifest, ToolDefinition, SourceType 等）
│
├── event_bus.py             # 异步 pub/sub 事件系统
├── logger.py                # structlog 结构化日志
│
├── agent_registry.py        # Agent 类型注册表（文件化加载）
├── agent_router.py          # 能力路由 + 管道构建
├── agent_manager.py         # Agent 进程生命周期管理
├── agent_runtime.py         # Agent 运行时（Task → 执行 → Result）
├── agent_socket.py          # Unix Socket IPC（Server + Client）
├── agent_cert.py            # 证书体系（Official / Self-Signed / None）
│
├── tool_gateway.py          # Tool Registry + Agent 权限感知（双栈检查）
├── tool_dispatchers.py      # 11 个 Dispatcher（File/Git/Http/Shell 等）
├── tool_file_loader.py      # Tools 文件化加载（tool.json5 → ToolDefinition）
├── policy_engine.py         # 权限策略引擎（含 source_type 过滤）
├── security_rule.py         # SecurityRule 三层沙箱（硬性/弹性/智能）
│
├── planner_agent.py         # Planner Agent（LLM 规划组件，~610 行）
├── transform_agent.py       # Transform Agent（NL → TARL / Shell 指令翻译）
├── workflow_engine.py       # DAG 任务编排引擎 + WorkflowDefV2（~1000 行）
├── workflow_listener.py     # Workflow 事件监听器
├── context_manager.py       # SQLite 上下文持久化 + FTS5 全文搜索（24 方法）
├── memory_bridge.py         # Event Bus → ContextManager 桥接
│
├── behavior_monitor.py      # 行为异常检测（记录/偏离度）
├── system_monitor.py        # 硬件状态采集 + 阈值告警
├── tarl_parser.py           # TARL 指令解析
├── ipc_handler.py           # JSON-RPC 2.0 over Unix Socket + TCP fallback
├── api_server.py            # FastAPI 路由（HTTP + SSE）
└── trimum_client.py         # CLI 客户端
```

## 模块依赖图

```
main.py
   │
   ├── config.py ─────────────── 配置加载
   │
   ├── api_server.py ─────────── HTTP API 路由
   │   ├── tool_gateway.py ───── 工具执行
   │   │   ├── policy_engine.py     权限检查（支持 source_type 过滤）
   │   │   ├── tool_dispatchers.py  11 个 Dispatcher
   │   │   ├── agent_manager.py     Agent 进程管理
   │   │   └── security_rule.py     安全规则（三层沙箱）
   │   ├── event_bus.py ───────── 事件发布/订阅
   │   ├── agent_registry.py ───── Agent 注册（含证书校验）
   │   ├── agent_router.py ─────── 能力路由
   │   ├── agent_runtime.py ────── Agent 运行时
   │   ├── workflow_engine.py ──── 工作流执行 + WorkflowDefV2
   │   ├── workflow_listener.py ── 工作流监听
   │   ├── planner_agent.py ────── Planner（LLM 规划）
   │   ├── transform_agent.py ──── NL→TARL 翻译
   │   ├── context_manager.py ──── 上下文持久化（FTS5）
   │   ├── memory_bridge.py ────── Event Bus ↔ ContextManager
   │   ├── behavior_monitor.py ─── 行为基线 + 异常检测
   │   └── system_monitor.py ───── 硬件采集 + 阈值告警
   │
   ├── ipc_handler.py ─────────── Socket 接口
   ├── agent_socket.py ────────── Unix Socket IPC
   │
   ├── logger.py ──────────────── 日志
   │
   ├── tarl_parser.py ─────────── TARL 指令解析
   │
   ├── agent_cert.py ──────────── Agent 证书（三档信任模型）
   │
   └── models.py ──────────────── 所有模块共享的数据模型
```

## 文件化层（磁盘结构）

```
~/.trimum/
├── agents/              # Agent 文件化（agent.json5 + AGENT.md + main.py）
│   ├── behavior-monitor/
│   ├── planner-agent/
│   ├── security-rule/
│   ├── system-monitor/
│   ├── transform-agent/
│   └── workflow-listener/
├── certs/               # 证书索引（符号链接/索引，指向 agents/<name>/cert.json）
│   ├── planner-agent.cert
│   └── transform-agent.cert
├── tools/               # Tool 文件化（tool.json5 + main.py）
│   ├── custom/env/file/git/http/knowledge/mcp/notification/process/shell/system/
└── workflows/           # Workflow 文件化（workflow.yaml）
    ├── blog-deploy/
    └── daily-check/
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
| IPC | JSON-RPC 2.0 + Unix Socket | 安全、高性能 |

## API 接口

### POST /api/execute
执行工具命令（SourceType 参数可选，缺省为 `system`）。
```json
{
  "tool": "shell",
  "args": ["df", "-h"],
  "agent_id": "ai-shell",
  "agent_manifest": { ... },
  "source_type": "ai"
}
```

### GET/POST /api/workflow/run|list|{name}
工作流编排（v2 格式 + 文件化加载）。

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
| Agent Certificate | 15 | ✅ 全部通过 |
| Policy Engine source 过滤 | 7 | ✅ 全部通过 |
| Workflow 文件化 | 14 | ✅ 全部通过 |
| 集成测试 | ~66 | ✅ 全部通过（1 fail 为已知缓存问题） |
| **合计** | **135** | **✅ 全部通过** |

## 部署

```
本地开发：D:\trimum
监听端口：8321（HTTP API）
Socket：/run/user/1000/trimum.sock（0700 权限，Arch Linux 部署时）
配置：~/.config/trimum/config.yaml
数据库：~/.trimum/memory/ 下各 *.db
```

## 认证/授权体系

```
Agent 请求 → AgentRegistry 查询 → 
  (1) AgentRegistry 检查 Agent 文件夹下 cert.json → 
    ├── type=official → TRUSTED（跨机信任）
    ├── type=self_signed → 同机 TRUSTED/跨机 CONFIRM
    └── type=none → CONFIRM（弹确认入口）
  (2) PolicyEngine 策略匹配 → 
    ├── source_type 过滤
    └── RiskLevel 评估
  (3) SecurityRule 沙箱决策 → 
    ├── 硬性模式：纯规则
    ├── 弹性模式：规则 + 行为监控
    └── 智能模式：规则 + 监控 + LLM 兜底
 → ToolGateway 执行
```
