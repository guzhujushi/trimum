# trimum

> 一句话：**AI 进程运行时**。一个跑在 Arch Linux 上的 AI 基础设施，把 Agent 变成操作系统级能力。

不是聊天助手，不是桌面美化。是让 "想个需求 → AI 自动拆解任务 → 调工具 → 出结果" 这件事，在 Linux 上原生成立。

---

## 核心组件

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
│   Tool   │ │Ecosys│ │ System ││Native│ │Ecosystem │
│轻量本地   │ │第三方│ │Linux稳 ││Desktop││第三方Agent│
│长期记忆   │ │Agent │ │定性保障 ││       ││ Tool     │
│SQLite/FTS│ │Tool  │ │快照检测 ││       ││ Wkflow   │
│          │ │扩展  │ │自动恢复 ││       ││ 扩展生态  │
└──────────┘ └──────┘ └────────┘ └──────┘ └──────────┘
```

### 核心组件详解

| 组件 | 职责 | 实现状态 |
|---|---|---|
| **Harness Runtime** | AI 进程运行时。管理 Agent 生命周期、权限、资源分配。系统级常驻守护进程。 | ✅ Phase 2 Core 完成 |
| **Agent Router** | Agent 调度与路由。根据任务类型、能力匹配选择/创建/分配 Agent，支持管道构建。 | ✅ Phase 2 完成 |
| **Event Bus** | AI 系统事件总线。Agent、Workflow、Runtime 之间的 pub/sub 通信。 | ✅ Phase 2 完成 |
| **Workflow Engine** | 可复用任务编排。DAG 节点定义、依赖链、并行/串行执行，替代大量固定 Agent。 | ✅ Phase 2 完成 |
| **Tool Gateway** | AI 能力接口层。统一管理 Shell、Git、Docker、Memory、Knowledge 等工具的注册、发现、调用。 | ✅ Phase 2 完成（含 Tool Registry） |
| **Security Runtime** | AI 权限与安全控制。Policy Engine + Landlock + Sandbox + 人类确认弹窗。 | ⏳ Policy Engine 完成，Landlock/Sandbox 待实现 |
| **Memory Tool** | 轻量本地长期记忆。SQLite/FTS 实现，Agent 间共享状态。 | ⏳ 基础 Context Manager 完成 |
| **Agent Ecosystem** | 第三方 Agent、Tool、Workflow 扩展生态。文件化注册（一切皆文件）。 | 📝 设计完成，待实现 |
| **Rollback System** | Linux 稳定性保障。Btrfs + Snapper 快照，健康检查，自动回滚。 | 📝 设计完成 |
| **AI Native Desktop** | 面向普通 Linux 用户的统一 AI 桌面体验。Hyprland 预设 + Waybar AI 集成 + 主题切换。 | ✅ Phase 1.5 完成 |

---

## 为什么是这些组件

传统 Linux 桌面对 AI 的支持是割裂的——终端里装个 shell_gpt、浏览器里开个 ChatGPT、IDE 里配个 Copilot。每个 AI 都在自己的孤岛里。

trimum 把这些整合成操作系统级能力：

| 问题 | 方案 |
|---|---|
| 每个 Agent 都要自己管理权限 | Security Runtime 统一策略 |
| 想编排多个 Agent 协作 | Workflow Engine DAG 编排 |
| Agent 间没法通信 | Event Bus pub/sub |
| 不知道哪个 Agent 能干什么 | Agent Router 能力路由 |
| 每个 Agent 都要自己写工具调用 | Tool Gateway 统一注册/发现 |
| 系统滚挂了没人管 | Rollback System 自动快照+回滚 |
| 没法记住用户偏好 | Memory Tool 持久化 |

---

## 开发状态

| Phase | 组件 | 状态 |
|---|---|---|
| **Phase 0** | 基础环境（Arch + Python + Docker） | ✅ |
| **Phase 1** | AI Shell MVP（自然语言→安全执行） | ✅ |
| **Phase 1.5** | 桌面预设（Hyprland 5 套主题 + 安装脚本） | ✅ |
| **Phase 2** | **Harness Runtime**（Agent Router + Event Bus + Workflow Engine + Tool Gateway + Security Policy） | ✅ **17 模块，4282 行代码，33 测试全过** |
| **Phase 3** | Agent SDK（openai-agents-python 封装 + 预装 Agent） | 📝 设计完成 |
| **Phase 4** | Security Runtime（Landlock + Namespace + Sandbox） | 📝 设计完成 |
| **Phase 5** | Memory Layer（长期记忆 + Knowledge Store） | 📝 设计完成 |
| **Phase 6** | ISO / 一键安装镜像 | ⏳ 待开始 |

---

## 快速开始

### 已有 Arch 系统

```bash
# 安装 Core
pip install trimum-core

# 启动守护进程
systemctl --user start trimum-core

# 使用
trm "查看磁盘空间"
trm "帮我清理缓存"
```

### 一键安装

```bash
curl -fsSL https://get.trimum.sh | bash
```

（需 Arch Linux，自动配置 Hyprland 桌面 + trimum Core + AI Shell）

---

## 项目结构

```
trimum/
├── README.md
├── LICENSE
├── STATUS.md
├── docs/
│   ├── ARCH.md              # Phase 2 Core 架构
│   ├── ARCHITECTURE.md       # 全系统架构（v3.0）
│   ├── DEVELOPMENT-ROADMAP.md
│   ├── TECHNICAL-BOM.md
│   ├── PHASE1-PLAN.md
│   ├── REFERENCE-PROJECTS.md
│   └── REUSE-STRATEGY.md
├── src/
│   └── trimum_core/          # Phase 2 Core（17 个模块，4282 行）
│       ├── agent_registry.py
│       ├── agent_router.py
│       ├── planner_agent.py
│       ├── workflow_engine.py
│       ├── tool_gateway.py
│       ├── event_bus.py
│       ├── policy_engine.py
│       ├── agent_manager.py
│       ├── context_manager.py
│       ├── api_server.py
│       ├── ipc_handler.py
│       ├── models.py
│       ├── config.py
│       ├── logger.py
│       ├── main.py
│       └── trimum_client.py
├── desktop/
│   └── themes/               # 22 套预设主题
└── scripts/
    └── setup-btrfs-snapper.sh
```

---

## 许可

MIT License — Copyright (c) 2026 guzhujushi

---

> ✨ trimum — 把 AI Agent 变成操作系统级能力。
