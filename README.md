# trimum — AI Process Runtime

> **把 AI Agent 变成操作系统级能力。**
> 一个跑在 Linux 上的 AI 基础设施，Agent 文件化、Tool 插件化、Workflow 可编排、随用随启不占资源。

---

## 生态位置

**trimum 是目前唯一用 Python 写的 AI 进程运行时（Harness）。**

市面上已有的类似框架——SemaClaw (TS, 83★)、skelm (TS, 0★)、Sandcastle (TS, 7780★)——全部使用 TypeScript。LangChain / CrewAI 虽是 Python，但它们不是 Harness（是 Agent 框架/编排层）。Python 生态里没有人在做 **"Agent 的操作系统内核"** 这个层级的产品。

详细分析：`docs/ECOSYSTEM-COMPARISON.md`

---

## ✨ 亮点速览

| 亮点 | 一句话 |
|---|---|
| **极致轻量化** | 能不用 Agent 就不用——纯执行走 Tool，有决策才用 Agent，拒绝过度设计 |
| **Transform 预翻译** | 自然语言 → 标准化标签语言，所有入口统一归一化，Workflow 可监督 |
| **Workflow 先于 LLM** | 优先查预置 workflow（80% 重复操作），未命中才调 LLM Router |
| **弹性沙箱** | Security Agent 决策 + Behavior Monitor + Policy Engine，可选硬性/弹性/智能 |
| **三重记忆体系** | Agent 私有记忆 / 项目共享上下文 / Planner 全局上下文，FTS5 全文检索 |
| **System Monitor** | CPU/GPU/Disk/RAM 实时监听，异常发 Event Bus 通知 |
| **Agent 文件化** | Agent = 一个目录 + `trimum-agent.toml`，ls 发现所有资源，cp 即安装 |
| **Tool 插件化** | 工具注册/发现/调用统一管理，14 种原生 Dispatcher |
| **Event Bus 标准化通信** | Agent/Workflow/Runtime/Security 统一事件总线，异步 pub/sub |
| **AI Runtime 随用随启** | 守护进程常驻不占资源，Agent 按需启动用完即释放 |
| **CLI 命令绑定** | `trm "查看磁盘"` — 自然语言直接绑定系统操作 |
| **开箱即用的桌面** | 22 套 Hyprland 主题预设 + 主题切换器 + 一键安装脚本 |
| **全套开发者工具链** | Agent Registry、Router、Workflow Engine、CLI client 开箱即用 |
| **新生态** | Agent/Tool/Workflow 全部文件化，第三方扩展即拷即用 |

---

## 核心架构

```
┌──────────────────────────────────────────────────┐
│             用户入口 (CLI/WebChat/TUI)            │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────┐
│              Transform Agent (预翻译层)            │
│     自然语言 → 标准化标签语言(key:value key:value)  │
│     所有入口统一归一化，Workflow 可监督匹配          │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────┐
│            Workflow Engine (+ Listener)           │
│  监听 Event Bus，匹配预置 workflow（80% 重复操作）  │
│  命中 → 直接执行（省 LLM 调用）                    │
│  未命中 → 转 Router → Planner                    │
└────┬───────────────┬───────────────┬─────────────┘
     │               │               │
┌────┴─────┐   ┌─────┴──────┐   ┌────┴─────────┐
│  Agent   │   │  Security  │   │  External    │
│  Routing │   │   Agent    │   │  Ecosystem   │
│          │   │            │   │              │
│ Router → │   │ 弹性沙箱    │   │ 3rd Agent    │
│ Planner  │   │ 决策中心    │   │ 3rd Tool     │
│ Agent    │   │ Behavior   │   │ 3rd Workflow │
│ 子Agent  │   │ Monitor    │   │              │
│ 路由     │   │ Landlock   │   │              │
└────┬─────┘   └─────┬──────┘   └──────┬───────┘
     │               │                 │
     └───────────────┼─────────────────┘
                     │
┌────────────────────┴─────────────────────────────┐
│                 Harness Runtime                   │
│                                                   │
│  ┌────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │ Agent Mgr  │  │  Event Bus   │  │ Tool      │ │
│  │ 生命周期   │  │  pub/sub     │  │ Gateway   │ │
│  │ Socket通信 │  │ 系统事件     │  │ 14 种     │ │
│  │ Spawn/     │  │ Agent通信    │  │ Dispatcher│ │
│  │ Destroy    │  │              │  │           │ │
│  └────────────┘  └──────────────┘  └───────────┘ │
│  ┌──────────────────────┐  ┌──────────────────┐  │
│  │ 三重记忆             │  │ System Monitor   │  │
│  │  Agent私有 (no confirm)│  │ CPU/GPU/Disk/RAM │  │
│  │  项目共享 (需确认)    │  │ 阈值告警         │  │
│  │  全局 Planner        │  │ Event Bus 通知   │  │
│  │  SQLite FTS5 全文检索 │  │                  │  │
│  └──────────────────────┘  └──────────────────┘  │
│  ┌──────────────────────────────────────────┐    │
│  │ Shell / Git / HTTP / Process / System   │    │
│  │ Env / File / Knowledge / Notification   │    │
│  │ MCP / Custom / Policy / IPC             │    │
│  └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

---

## 核心组件

| **Harness Runtime** | AI 进程运行时。管理 Agent 生命周期、权限、资源分配。 | ✅ |
| **Transform Agent** | 自然语言 → 标准化标签语言，所有入口统一归一化 | 📝 待实现 |
| **Workflow Engine** | 监听 Event Bus，匹配预置 workflow，优先走缓存省 LLM | ✅ + 扩展 |
| **Agent Router** | 根据任务类型、能力匹配子 Agent，支持管道构建 | ✅ |
| **Planner Agent** | Workflow 未命中时的 LLM 兜底规划 | ✅ |
| **Security Agent** | 弹性沙箱决策中心。可选硬性/弹性/智能模式 | ✅ Phase 3 |
| **Behavior Monitor** | 操作历史追踪、频率异常检测、跨沙箱检测 | ✅ Phase 3 |
| **Event Bus** | Agent/Workflow/Runtime/Security 统一事件总线 | ✅ |
| **Tool Gateway** | 14 种原生 Dispatcher，统一注册/发现/调用 | ✅ |
| **Agent Manager** | Agent 进程生命周期（Socket 通信启停） | ✅ Phase 3 |
| **三重记忆** | Agent 私有 / 项目共享 / 全局 Planner，FTS5 全文检索 | ✅ Phase 3 |
| **System Monitor** | CPU/GPU/Disk/RAM 实时监听 + Event Bus 通知 | ✅ Phase 3 |
| **Policy Engine** | 正则规则匹配，Action.CONFIRM 支持 | ✅ |
| **Context Manager** | SQLite 持久化上下文存储 | ✅ + 扩展 |
| **IPC Handler** | JSON-RPC 2.0 over Unix Socket | ✅ |
| **API Server** | FastAPI HTTP 接口 | ✅ |

---

## 开源参考与致谢

trimum 的设计深受以下开源项目启发：

| 项目 | 借鉴内容 |
|---|---|
| **[SemaClaw](https://github.com/midea-ai/SemaClaw)** — 个人 AI Agent 框架（TS） | DAG Teams 两阶段编排、Plugin Marketplace 概念、三重上下文管理思路 |
| **[skelm](https://github.com/skelm-framework/skelm)** — 安全 Workflow 框架（TS） | Default-Deny 权限模型设计、Per-Agent Workspace 隔离思路、Tamper-Evident Audit 理念 |
| **[Warp](https://github.com/warpdotdev/Warp)** — AI 终端（Rust） | TARL 标签语言理念、Handoff Snapshot 最小上下文原则、Run State 扩展启发 |
| **[Sandcastle](https://github.com/mattpocock/sandcastle)** — 沙箱编码 Agent（TS） | 沙箱隔离设计参考 |

详细对比分析：`docs/ECOSYSTEM-COMPARISON.md`

## 设计哲学

| 问题 | 方案 |
|---|---|
| 不想每次重复操作都调 LLM | Workflow Engine 缓存预置流程，先匹配再 LLM |
| 自然语言翻译不稳定 | Transform Agent 标准化标签语言输出 |
| Agent 互相访问不受控 | Security Agent 决策中心，跨工具需确认 |
| 不知道系统是否正常 | System Monitor 实时采集 + Event Bus 发布 |
| 记忆散落在各个 Agent | 三重记忆体系，FTS5 统一检索 |
| Agent 间没法通信 | Event Bus pub/sub |
| 不知道哪个 Agent 能干什么 | Agent Router 能力路由 |
| 每个 Agent 都要自己管理权限 | Security Agent 统一策略 |
| 想编排多个 Agent 协作 | Workflow Engine |
| 每个 Agent 都要自己写工具调用 | Tool Gateway 统一注册/发现 |
| 系统滚挂了没人管 | Rollback System 自动快照+回滚 |
| Agent 太臃肿 | 一切皆文件，ls 发现全部，随用随启 |

---

## 开发状态

| Phase | 内容 | 状态 |
|---|---|---|
| **Phase 0** | 基础环境 | ✅ |
| **Phase 1** | AI Shell MVP | ✅ |
| **Phase 1.5** | 桌面预设（Hyprland 主题） | ✅ |
| **Phase 2** | **Harness Runtime Core** — 23 模块 | ✅ |
| **Phase 2.5** | **Tool Dispatcher 重构** — 14 种原生 Dispatcher | ✅ |
| **Phase 3** | **弹性沙箱体系**（Security Agent + Behavior Monitor + System Monitor + 三重记忆 + Agent Socket + Workflow v2） | ✅ |
| **Phase 4** | Security Runtime（Landlock LSM + Namespace + Seccomp） | 📝 设计 |
| **Phase 5** | Memory Layer（chroma 向量库 + 知识图谱） | 📝 设计 |
| **Phase 6** | ISO / 一键安装镜像 | ⏳ |

---

## 项目结构

```
trimum/
├── README.md
├── LICENSE
├── STATUS.md
├── src/trimum_core/     # Core Runtime（23 个模块）
│   ├── agent_registry.py     Agent 类型注册表
│   ├── agent_router.py       Agent 能力路由 + 管道
│   ├── agent_runtime.py      子 Agent 进程生命周期管理
│   ├── agent_socket.py       Unix Socket 通信层
│   ├── behavior_monitor.py   行为基线 + 异常检测
│   ├── planner_agent.py      含 LLM 智能的规划 Agent
│   ├── security_agent.py     弹性沙箱决策中心
│   ├── system_monitor.py     CPU/GPU/Disk/RAM 实时监听
│   ├── workflow_engine.py    DAG 任务编排 + v2 监听器→执行组
│   ├── tool_gateway.py       工具注册/发现/权限校验
│   ├── tool_dispatchers.py   14 种原生 Dispatcher
│   ├── event_bus.py          异步 pub/sub 事件总线
│   ├── context_manager.py    三重记忆 + FTS5 全文搜索
│   ├── agent_manager.py      Agent 生命周期管理
│   ├── policy_engine.py      正则策略引擎
│   ├── api_server.py         FastAPI HTTP 接口
│   ├── ipc_handler.py        JSON-RPC over Unix Socket
│   ├── main.py               守护进程入口
│   ├── trimum_client.py      CLI 客户端
│   ├── models.py             Pydantic 数据模型
│   ├── config.py             YAML 配置加载
│   └── logger.py             结构化日志
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
