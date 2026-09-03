# trimum — 系统架构

版本：v5.0（2026-09-01）

---

## 0. 核心定位

**AI 进程运行时**——一个运行在 Arch Linux 上的 AI 基础设施，将 Agent（AI 程序）视为操作系统级资源来管理。

不同于：
- ❌ 聊天助手（ChatGPT / Claude Web）
- ❌ Agent 框架（LangChain / CrewAI）
- ❌ 桌面美化（dotfiles / Hyprland 预设）
- ❌ Linux 发行版

它是 **Agent 的操作系统内核**：生命周期、权限、通信、编排、扩展。

---

## 1. 宏观架构

```
                    ┌─────────────────────────────────────┐
                    │          AI Native Desktop           │
                    │   CLI / WebChat / TUI / API 入口      │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────┴──────────────────────┐
                    │         Transform Agent              │
                    │  自然语言 → 标准化指令（标签语言）     │
                    │  预翻译层：所有入口统一归一化           │
                    │  输出格式：key:value key:value         │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────┴──────────────────────┐
                    │      Workflow Engine (+ Listener)    │
                    │  监听 Event Bus，匹配预置 workflow     │
                    │  优先走 workflow（避免 LLM 调用）       │
                    │  未命中 → 转 Router/Planner           │
                    └──────────────┬──────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
    ┌────┴─────┐            ┌─────┴──────┐           ┌──────┴─────┐
    │ Workflow │            │   Agent    │           │  External  │
    │ 缓存层   │            │  Routing   │           │ Ecosystem  │
    │          │            │            │           │            │
    │ 成功→    │            │  Router →  │           │ 3rd Agent  │
    │ 直接执行  │            │  Planner   │           │ 3rd Tool   │
    │ 失败→    │            │  SE Agent  │           │ 3rd Wkflow │
    │ Planner  │            │  路由      │           │            │
    └────┬─────┘            └─────┬──────┘           └──────┬─────┘
         │                         │                         │
         └─────────────────────────┼─────────────────────────┘
                                   │
                    ┌──────────────┴──────────────────────┐
                    │         Harness Runtime              │
                    │                                     │
                    │  ┌────────────┐  ┌────────────────┐ │
                    │  │Event Bus   │  │ Tool Gateway   │ │
                    │  │pub/sub     │  │ Registry       │ │
                    │  │Agent通信   │  │ Shell/Git/...  │ │
                    │  │系统事件    │  │ Memory/Knowledge│ │
                    │  └────────────┘  └────────────────┘ │
                    │  ┌────────────┐  ┌──────────────────────┐ │
                    │  │Agent Mgr   │  │ Security Agent       │ │
                    │  │生命周期    │  │ 弹性沙箱决策中心       │ │
                    │  │Spawn/Destroy│  │ 可选：硬性/弹性/智能   │ │
                    │  │Socket通信  │  │ Policy Engine 规则     │ │
                    │  └────────────┘  │ Behavior Monitor 行为   │ │
                    │  ┌────────────┐  │ Landlock 文件权限(P4)   │ │
                    │  │Context Mgr │  │ 弹窗确认接口           │ │
                    │  │三重记忆     │  └──────────────────────┘ │
                    │  │  Agent私有  │  ┌──────────────────────┐ │
                    │  │  项目共享   │  │ System Monitor       │ │
                    │  │  全局(Planner)│ │ HW监听 + Event Bus通知 │
                    │  │ FTS5 全文搜索│ │ CPU/GPU/Disk/RAM      │ │
                    │  │ SQLite持久化│  │ 阈值告警 + 异常发布    │ │
                    │  └────────────┘  └──────────────────────┘ │
                    │  ┌──────────────────┐                     │
                    │  │ Tool Gateway     │                     │
                    │  │ 工具注册/发现 + 权限                     │
                    │  │ Shell/Git/HTTP/Process/System/Env     │
                    │  │ Knowledge/Notification/MCP/自定义      │
                    │  └──────────────────┘                     │
                    └─────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────────────┐
                    │          Linux 底座                  │
                    │   Arch Linux · Btrfs · Systemd      │
                    │   Landlock · Seccomp · Python 3.12+ │
                    └─────────────────────────────────────┘
```

---

## 2. 核心组件详细设计

### 2.1 Harness Runtime

系统级常驻守护进程（trmd）。**不含 AI 智能**，只管理 Agent 的运行和权限。

| 子模块 | 职责 | 状态 |
|---|---|---|
| Agent Manager | Agent 进程生命周期（spawn/destroy/restart） | ✅ |
| Agent Runtime | Task 执行器（Task → AgentProcess → Result） | ✅ |
| Event Bus | 异步 pub/sub 系统事件通信 | ✅ |
| Context Manager | SQLite 持久化上下文 + FTS5 全文搜索 | ✅ |
| Memory Bridge | Event Bus → ContextManager 桥接（memory.* 事件） | ✅ |
| Policy Engine | YAML 规则匹配 + Risk Level 评估 + source_type 过滤 | ✅ |
| Security Rule | 三层沙箱模式（硬性/弹性/智能）| ✅ |
| Behavior Monitor | 行为基线 + 事件记录 + 偏离度检测 | ✅ |
| System Monitor | 硬件采集 + 阈值告警（CPU/内存/磁盘/网络）| ✅ |
| Tool Gateway | 工具注册/发现 + Agent 权限感知 + 11 Dispatchers | ✅（v2） |
| API Server | FastAPI HTTP 接口 + SSE 流 | ✅ |
| IPC Handler | JSON-RPC over Unix Socket | ✅ |
| Agent Socket | Unix Socket Server + Client（双向通信）| ✅ |
| Logger | structlog 结构化日志 | ✅ |

### 2.2 Event Bus

AI 系统事件总线，负责 Runtime / Agent / Workflow 之间的通信。

> **Phase 3+ 可选：虚拟文件接口**（来自 DeepSeek 建议）
> Event Bus 可暴露 `/run/trimum/events/` 目录作为可选的文件接口展示层：
> ```
> /run/trimum/events/
> ├── agent.log        # Agent 生命周期事件（近似 dmesg 的作用）
> ├── workflow.log     # Workflow 执行流水
> └── security.log     # 安全事件审计流
> ```
> 类似 Linux /proc、/sys——不是它们存储系统状态，只是展示接口。
> **当前阶段不做 FUSE 实现**，备选方案：Unix Socket dump + 尾部滚动文件。

```
事件类型：
├── agent.spawned       Agent 启动
├── agent.completed     Agent 任务完成
├── agent.error         Agent 异常
├── workflow.started    工作流开始
├── workflow.completed  工作流完成
├── workflow.error      工作流异常
├── tool.executing      工具调用中
├── tool.completed      工具执行完成
├── tool.denied         工具被拒绝
├── security.alert      安全告警
├── security.risk       风险操作
├── system.heartbeat    系统心跳
├── system.update       系统更新
└── user.notify         用户通知
```

订阅者可以监听特定事件类型，实现解耦。

### 2.3 Agent Router

Agent 调度与路由。接收任务 → 按能力匹配 Agent → 构建执行管道。

```
输入：任务描述（自然语言）
   │
   ▼
Router.match(task)
   ├── 从 Registry 查找能力匹配的 Agent
   ├── 按风险等级/资源占用排序
   └── 返回候选 Agent 列表
   │
   ▼
Router.build_pipeline(capabilities)
   ├── 构建多 Agent 管道
   ├── 依赖链：A → B → C
   └── 返回 Pipeline
   │
   ▼
输出：Agent 或 Pipeline
```

### 2.4 Workflow Engine

可复用任务编排引擎。支持 DAG 定义、依赖链、并行执行。

```python
# 示例：检查→诊断→修复 工作流
workflow = WorkflowDefinition(
    nodes=[
        NodeDefinition(id="check", agent="system-healthy", depends_on=[]),
        NodeDefinition(id="diagnose", agent="coding-agent", depends_on=["check"]),
        NodeDefinition(id="fix", agent="tool-agent", depends_on=["diagnose"]),
    ],
    edges=[
        EdgeDefinition(from_node="check", to_node="diagnose"),
        EdgeDefinition(from_node="diagnose", to_node="fix"),
    ]
)
```

### 2.5 Tool Gateway

AI 能力接口层。统一注册/发现/调用所有工具。

| 功能 | 说明 |
|---|---|
| **Tool Registry** | 工具注册表，支持内置 + 自定义工具 |
| **Agent 权限感知** | 双层检查：deny_exec 黑名单优先，exec 白名单二次校验 |
| **路径模式匹配** | 文件读写按 glob 模式限制访问路径 |
| **向后兼容** | 空权限/unset manifest 时完全放行 |
| **内置工具** | shell, file.read, file.write |

### 2.6 Security Runtime

AI 权限与安全控制。分三层：

```
Level 0 ── 直接执行
  低风险命令（ls, df, ps, echo）
  不额外隔离

Level 1 ── 弹窗确认
  中风险命令（rm, pacman -S, docker build）
  用户确认 → AI 评估 + 审计日志

Level 2 ── 拒绝
  高风险命令（rm -rf /, dd, mkfs）
  直接拒绝 + 审计

未来（Phase 4）：
  Landlock：限制文件系统访问范围
  Seccomp：限制系统调用
  Namespace：轻量进程隔离
  Docker：高风险任务完整沙箱
```

### 2.7 Rollback System

Linux 稳定性保障：

```
更新触发
    ↓
Snapper pre-snapshot
    ↓
System Healthy Agent 检查 8 项
    ├── 全部通过 → 保留快照
    └── 失败 ≥ 2 项 → 自动回滚 + 通知用户
```

### 2.8 Memory Tool

Agent 间共享的轻量长期记忆：

| 能力 | 实现 |
|---|---|
| 键值存储 | SQLite key-value |
| 上下文持久化 | Agent 间共享状态 |
| 关键字搜索 | SQLite FTS5 |

> **渐进路线**（来自 DeepSeek 建议）
> 当前技术选型：Phase 5 引入 chroma（轻量向量库）。
> 如果实际使用中发现语义搜索需求不足（用户需求主要是"找历史/偏好/workflow"而非"找相似文章"），可降级为：
SQLite 直接记忆 → sqlite-vec 向量扩展 → chroma
此方案不需要立即调整 Phase 5 计划，仅作为 future option 记录。
**关键规则**：Memory Tool 只返回 Top-N 条（如 5 条），不加载全部内容给 Agent，避免 Token 爆炸。

### 2.9 Agent Ecosystem

一切皆文件的设计理念：

```
~/.trimum/
├── agents/           # Agent 注册（目录 + agent.json5 + AGENT.md + main.py）
│   ├── planner-agent/
│   ├── transform-agent/
│   ├── behavior-monitor/
│   ├── security-rule/
│   ├── system-monitor/
│   └── workflow-listener/
├── certs/            # 证书索引
│   ├── official/     # 官方证书（拷入即用）
│   ├── trusted/      # 用户签发证书
│   └── pending/      # 待批准
├── tools/            # 可执行工具（tool.json5 + main.py）
│   ├── custom/
│   ├── env/
│   ├── file/
│   ├── git/
│   ├── http/
│   ├── knowledge/
│   ├── mcp/
│   ├── notification/
│   ├── process/
│   ├── shell/
│   └── system/
└── workflows/        # 预装工作流（workflow.yaml）
    ├── blog-deploy/
    └── daily-check/
```

---

## 3. 通信协议

### 统一消息格式（JSON）

```
CLI:
  trm "查看磁盘"
  → trimum Core（HTTP）
  ← { output: "磁盘使用 45%...", risk: "low", action: "auto" }

HTTP:
  POST /api/workflow/run
  { "workflow_id": "system-update" }
  ← { "status": "running", "execution_id": "uuid" }

Socket:
  Unix Domain Socket → /run/user/1000/trimum.sock
  消息格式同 HTTP，更轻量

IPC:
  JSON-RPC 2.0 over Unix Socket（+TCP fallback）
```

---

## 4. Task State Machine

每个 Task（任务）是一个有生命周期的一等对象，而非模糊的消息。

```
CREATED
   │
   ▼
QUEUED
   │
   ▼
DISPATCHING
   │
   ▼
RUNNING
   │
   ├────────────────┐
   │                │
   ▼                ▼
COMPLETED         FAILED
   │
   ▼
ARCHIVED

Error states (from RUNNING):
├── TIMEOUT      — exceeded time limit
├── CANCELLED    — user or system interrupt
└── BLOCKED      — missing permission / resource
```

**状态归谁管**：
- `Workflow Engine` 拥有 Task 状态机，负责状态转换
- `Event Bus` 只负责状态变更事件的发布与投递，不做状态管理
- `Agent Runtime` 负责 Agent 进程 spawn/monitor/kill

## 5. Handoff Snapshot

Agent 间传递上下文时，遵循 **Minimum Context Principle**：Child Agent 只接收完成任务真正需要的最小上下文，不传输整个 Parent History。

```
Parent Context (10000 tokens)
       │
       │ Select — only what child needs
       ▼
Context Snapshot (500 tokens)
       │
       ▼
Child Agent
```

Snapshot 通过 TARL 的 `snapshot:` 元信息字段传递：

```
snapshot:ctx_abc123
workspace:/var/www/blog
error:nginx_502
target:restore_api
permission:project_write
artifacts:logs/nginx_error.log
```

## 6. 两个最小原则

| 原则 | 含义 | 类比 |
|---|---|---|
| **Minimum Context** | Agent 只接收完成任务所需的最小上下文 | 不复制整个 History，只传 Task Context |
| **Minimum Permission** | Agent 只拥有完成任务所需的最小权限 | Least Privilege 原则 |

## 7. Trigger → Workflow

系统自动化不依赖 Agent，而是通过 Event → Trigger → Workflow 链路。

```
File Change / CPU Spike / Git Push
              │
              ▼
          Trigger
              │
              ▼
      Workflow Engine
              │
              ▼
          Runtime
```

支持的触发源（Phase 1）：
| 源 | 描述 |
|---|---|
| Filesystem Event | inotify 文件变化 |
| Process Event | 进程退出/异常 |
| System Event | CPU/RAM 达到阈值 |
| Cron | 定时触发 |
| Webhook | 外部 HTTP 回调 |

## 8. 设计原则

1. **Harness 不含 AI**：只管生命周期、权限、通信。Agent 负责智能。
2. **Agent 不能绕过权限**：所有工具调用必须经过 Tool Gateway 的权限检查。
3. **能不启动 Agent 就不启动**：低风险命令直接走 Tool Gateway，不经过 Agent 推理循环。
4. **Agent 文件化**：Agent/Tool/Workflow 都是文件，`ls` 就能发现全部资源。
5. **最少依赖**：Python 全栈统一，不引入重量级框架。
6. **云端 AI 优先**：本地不做推理，省资源。本地模型按需加载。
