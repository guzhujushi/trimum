# trimum — AI Process Runtime

> **把 AI Agent 变成操作系统级能力。**
> 一个跑在 Linux 上的 AI 基础设施，Agent 文件化、Tool 插件化、Workflow 可编排、随用随启不占资源。

---

## ✨ 亮点速览

| 亮点 | 一句话 |
|---|---|
| **Agent 文件化** | Agent = 一个目录 + `trimum-agent.toml`，ls 发现所有资源，cp 即安装 |
| **Tool 插件化** | 工具注册/发现/调用统一管理，Shell/Git/HTTP/文件/系统信息，即插即用 |
| **Workflow 可编排** | DAG 任务编排，Agent 链式/并行协作，替代大量固定 Agent |
| **AI Runtime 随用随启** | 守护进程常驻不占资源，Agent 按需启动用完即释放 |
| **多 Agent 协作新范式** | Event Bus 标准化通信层，Agent 间 pub/sub 零耦合 |
| **CLI 命令绑定** | `trm "查看磁盘"` — 自然语言直接绑定系统操作 |
| **弹性沙箱** | Policy Engine + Landlock 双层兜底，最小权力准则 |
| **Event Bus 标准化通信** | Agent/Workflow/Runtime 统一事件总线，异步 pub/sub |
| **系统级 Harness** | Agent 生命周期/权限/资源分配全由 Runtime 管理，与内核深度绑定 |
| **长期记忆** | SQLite/FTS 持久化，Agent 间共享上下文 |
| **全套开发者工具链** | Agent Registry、Router、Workflow Engine、CLI client 开箱即用 |
| **开箱即用的桌面** | 22 套 Hyprland 主题预设 + 主题切换器 + 一键安装脚本 |
| **机制轻量化** | 能不用 Agent 就不用——纯执行走 Tool，有决策才用 Agent，拒绝过度设计 |
| **新生态** | Agent/Tool/Workflow 全部文件化，第三方扩展即拷即用 |

---

## 核心架构

```
┌─────────────────────────────────────────────────────┐
│                   AI Native Desktop                  │
│              面向普通 Linux 用户的统一 AI 桌面体验    │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────────┐
│                  Harness Runtime                     │
│           AI 进程运行时：管理 Agent 生命周期、权限、资源 │
└─────────────────────┬───────────────────────────────┘
                      │
┌──────────┬──────────┼──────────┬──────────┬─────────┐
│          │          │          │          │         │
│  Agent   │  Event   │ Workflow │   Tool   │ Security│
│  Router  │   Bus    │  Engine  │  Gateway │ Runtime │
│ Agent 调度│ AI 系统  │ 可复用   │ AI 能力  │ AI 权限 │
│ 与路由   │ 事件总线  │ 任务编排  │ 接口层   │ 与安全  │
│ 按任务选 │ Agent/   │ 替代大量  │ 统一管理  │ Landlock│
│ 择/创建  │ Workflow │ 固定     │ Shell/   │ Sandbox │
│ 分配Agent│ 通信     │ Agent    │ Git/Mem  │ Policy  │
│          │          │          │ Knowled. │ 人类确认 │
└─────┬────┴─────┬────┴────┬────┴────┬────┴───┬─────┘
      │          │         │         │        │
┌─────┴────┐ ┌──┴───┐ ┌───┴────┐ ┌─┴────┐ ┌─┴────────┐
│  Memory  │ │Agent │ │ Rollback││ AI   │ │  Agent   │
│   Tool   │ │Ecosys│ │ System ││Native │ │Ecosystem │
│轻量本地   │ │第三方│ │Linux稳 ││Desktop│ │第三方Agent│
│长期记忆   │ │Agent │ │定性保障 ││       │ │ Tool     │
│SQLite/FTS│ │Tool  │ │快照检测 ││       │ │ Wkflow   │
│          │ │扩展  │ │自动恢复 ││       │ │ 扩展生态  │
└──────────┘ └──────┘ └────────┘ └──────┘ └──────────┘
```

---

## 核心组件

| 组件 | 职责 | 状态 |
|---|---|---|
| **Harness Runtime** | AI 进程运行时。管理 Agent 生命周期、权限、资源分配。系统级常驻守护进程。 | ✅ Phase 2 |
| **Agent Router** | Agent 调度与路由。根据任务类型、能力匹配选择/创建/分配 Agent，支持管道构建。 | ✅ Phase 2 |
| **Event Bus** | AI 系统事件总线。Agent、Workflow、Runtime 之间的 pub/sub 通信。 | ✅ Phase 2 |
| **Workflow Engine** | 可复用任务编排。DAG 节点定义、依赖链、并行/串行执行，替代大量固定 Agent。 | ✅ Phase 2 |
| **Tool Gateway** | AI 能力接口层。统一管理 Shell、Git、HTTP、文件、系统信息等工具的注册、发现、调用。 | ✅ Phase 2.5 |
| **Security Runtime** | AI 权限与安全控制。Policy Engine + Landlock + Sandbox + 人类确认弹窗。 | ⏳ Policy Engine 完成 |
| **Memory Tool** | 轻量本地长期记忆。SQLite/FTS 实现，Agent 间共享状态。 | ⏳ 基础 Context Manager |
| **Agent Ecosystem** | 第三方 Agent、Tool、Workflow 扩展生态。文件化注册（一切皆文件）。 | 📝 设计完成 |
| **AI Native Desktop** | 面向普通 Linux 用户的统一 AI 桌面体验。Hyprland 22 套主题 + 主题切换器。 | ✅ Phase 1.5 |

---

## 设计哲学

| 问题 | 方案 |
|---|---|
| 每个 Agent 都要自己管理权限 | Security Runtime 统一策略 |
| 想编排多个 Agent 协作 | Workflow Engine DAG 编排 |
| Agent 间没法通信 | Event Bus pub/sub |
| 不知道哪个 Agent 能干什么 | Agent Router 能力路由 |
| 每个 Agent 都要自己写工具调用 | Tool Gateway 统一注册/发现 |
| 系统滚挂了没人管 | Rollback System 自动快照+回滚 |
| 没法记住用户偏好 | Memory Tool 持久化 |
| Agent 太臃肿 | 一切皆文件，ls 发现全部，随用随启 |

---

## 开发状态

| Phase | 内容 | 状态 |
|---|---|---|
| **Phase 0** | 基础环境（Arch + Python + Docker） | ✅ |
| **Phase 1** | AI Shell MVP（自然语言→安全执行） | ✅ |
| **Phase 1.5** | 桌面预设（22 套 Hyprland 主题 + 安装脚本） | ✅ |
| **Phase 2** | **Harness Runtime Core** — 17 模块，4282+ 行，99 测试全过 | ✅ |
| **Phase 2.5** | **Tool Dispatcher 重构** — 11 个原生 Dispatcher，统一注册/发现 | ✅ |
| **Phase 3** | Agent SDK（openai-agents-python 封装 + 预装 Agent） | 📝 待开始 |
| **Phase 4** | Security Runtime（Landlock + Namespace + Sandbox） | 📝 设计 |
| **Phase 5** | Memory Layer（长期记忆 + Knowledge Store） | 📝 设计 |
| **Phase 6** | ISO / 一键安装镜像 | ⏳ |

---

## 项目结构

```
trimum/
├── README.md
├── LICENSE
├── STATUS.md
├── src/trimum_core/     # Core Runtime（17 个模块）
│   ├── agent_registry.py   Agent 类型注册表
│   ├── agent_router.py     Agent 能力路由 + 管道
│   ├── planner_agent.py    含 LLM 智能的规划 Agent
│   ├── workflow_engine.py   DAG 任务编排引擎
│   ├── tool_gateway.py      工具注册/发现/权限校验
│   ├── tool_dispatchers.py   11 个原生 Dispatcher
│   ├── event_bus.py         异步 pub/sub 事件总线
│   ├── agent_manager.py     Agent 生命周期管理
│   ├── context_manager.py   SQLite 持久化上下文
│   ├── policy_engine.py     正则策略引擎
│   ├── api_server.py        FastAPI HTTP 接口
│   ├── ipc_handler.py       JSON-RPC over Unix Socket
│   ├── main.py              守护进程入口
│   ├── trimum_client.py     CLI 客户端
│   ├── models.py            Pydantic 数据模型
│   ├── config.py            YAML 配置加载
│   └── logger.py            结构化日志
├── desktop/themes/        # 22 套 Hyprland 主题预设
├── docs/                  # 架构/路线图文档
└── scripts/               # 安装/运维脚本
```

---

## 快速开始

### 已有 Arch 系统

```bash
pip install trimum-core
systemctl --user start trimum-core
trm "查看磁盘空间"
```

### 全新安装

```bash
curl -fsSL https://get.trimum.sh | bash
```

（需 Arch Linux，自动配置 Hyprland 桌面 + trimum Core）

---

## 许可

MIT License — Copyright (c) 2026 guzhujushi
