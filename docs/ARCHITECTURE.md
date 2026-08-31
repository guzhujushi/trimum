# trimum — 系统架构

版本：v3.0（2026-08-31）

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
                    │   Hyprland 预设 · Waybar AI · 主题包  │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────┴──────────────────────┐
                    │         Interface Layer              │
                    │  CLI / Unix Socket / HTTP API / SDK  │
                    └──────────────┬──────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
    ┌────┴─────┐            ┌─────┴──────┐           ┌──────┴─────┐
    │ Service  │            │   Agent    │           │  External  │
    │  Layer   │            │  Routing   │           │ Ecosystem  │
    │          │            │            │           │            │
    │  Rollback│            │  Router →  │           │ 3rd Agent  │
    │  System  │            │  Planner   │           │ 3rd Tool   │
    │  Health  │            │  Workflow  │           │ 3rd Wkflow │
    │  Check   │            │  Engine    │           │            │
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
                    │  ┌────────────┐  ┌────────────────┐ │
                    │  │Agent Mgr   │  │ Security       │ │
                    │  │生命周期    │  │ Policy Engine  │ │
                    │  │Spawn/Destroy│  │ Permission     │ │
                    │  │资源分配    │  │ Risk Eval      │ │
                    │  └────────────┘  └────────────────┘ │
                    │  ┌────────────┐  ┌────────────────┐ │
                    │  │Context Mgr │  │ Memory Tool    │ │
                    │  │SQLite持久化│  │ 长期记忆       │ │
                    │  │Agent状态   │  │ FTS 检索       │ │
                    │  └────────────┘  └────────────────┘ │
                    │                                     │
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
| Event Bus | 异步 pub/sub 系统事件通信 | ✅ |
| Context Manager | SQLite 持久化上下文 | ✅ |
| Policy Engine | YAML 规则匹配 + Risk Level 评估 | ✅ |
| Tool Gateway | 工具注册/发现 + Agent 权限感知 | ✅（重构后） |
| API Server | FastAPI HTTP 接口 | ✅ |
| IPC Handler | JSON-RPC over Unix Socket | ✅ |
| Logger | structlog 结构化日志 | ✅ |

### 2.2 Event Bus

AI 系统事件总线，负责 Runtime / Agent / Workflow 之间的通信。

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

### 2.9 Agent Ecosystem

一切皆文件的设计理念：

```
~/.trimum/
├── agents/           # Agent 注册（目录 + manifest）
│   ├── ai-shell/
│   ├── system-healthy/
│   └── theme-mgr/
├── tools/            # 可执行工具
│   ├── shell
│   ├── git
│   └── docker
├── workflows/        # 预装工作流
│   ├── system-update.yaml
│   └── daily-check.yaml
└── env               # API Key 统一管理
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

## 4. 设计原则

1. **Harness 不含 AI**：只管生命周期、权限、通信。Agent 负责智能。
2. **Agent 不能绕过权限**：所有工具调用必须经过 Tool Gateway 的权限检查。
3. **能不启动 Agent 就不启动**：低风险命令直接走 Tool Gateway，不经过 Agent 推理循环。
4. **Agent 文件化**：Agent/Tool/Workflow 都是文件，`ls` 就能发现全部资源。
5. **最少依赖**：Python 全栈统一，不引入重量级框架。
6. **云端 AI 优先**：本地不做推理，省资源。本地模型按需加载。
