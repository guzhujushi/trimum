# trimum

> Arch Linux + Hyprland + trimum = 一个面向 Linux 的 AI Agent 运行时

## 一句话定位

**一个面向 Linux 的 AI Agent 运行时**——将 Event Bus、Workflow Engine 和 Agent Runtime 三大核心模块结合，使 AI Agent 像操作系统进程一样被调度、隔离和协作。底座是 Arch Linux + Hyprland 桌面。

不需要记住命令参数，不需要手动配置桌面，不需要担心 Arch 滚挂了。

## 借鉴的开源项目

| 项目 | 借鉴内容 |
|---|---|
| [Omarchy](https://github.com/omacom/omarchy) | 22 套 Hyprland 主题色板、壁纸、锁屏资产；Snapper 配置脚本参考 |
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | Agent SDK 架构设计、Tool/Guardrail 模式 |
| [DHH/omakub](https://github.com/dhh/omakub) | 一键安装脚本设计理念 |
| [obra/superpowers](https://github.com/obra/superpowers) | MCP 服务器管理、Agent 生态编排思路 |
| [mattpocock/skills](https://github.com/mattpocock/skills) | Skill 系统的轻量模块化设计 |

> trimum 的核心价值不是「又一个 Hyprland 发行版」，而是**将 AI Agent 深度集成到操作系统层面**——对标 iOS 的安全体系、Android 的 Runtime 设计、Coze 的智能体生态、Workbuddy 的多智能体协作架构。

## 系统架构

trimum Core 由三大核心模块组成：

```
                         trimum Core
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
   Event Bus         Workflow Engine      Agent Runtime
  （神经系统）        （任务逻辑）         （进程管理）
  只传递，不思考       成熟经验固化       生命周期+权限+隔离
                            │
        ┌───────────────────┼───────────────────┐
        │     Policy Engine  │  Tool Gateway     │
        │     Agent Router   │  Context Manager  │
        │     Planner Agent ★  （唯一LLM组件）  │
        └───────────────────┴───────────────────┘
                            │
                    Agent Pool（插件化）
                            │
                    Tool Gateway（双层权限）
                            │
                        System
```

### 数据流示例

```
用户请求 "帮我优化服务器"
  │
Agent Runtime 决定：是否有已固化 workflow？
  ├── 有 → Workflow Engine 直接执行 server_optimize.workflow
  │         ↓ Event Bus 分发 task.optimize.* 事件
  │         ↓ 各 Agent 按订阅执行
  │
  └── 无 → Planner Agent（按需启动）
            ↓ LLM 拆解 → 写入新 workflow
            ↓ Workflow Engine 执行

Agent 通信全程通过 Event Bus：
  Agent A → Event Bus → Agent B
  Agent → Tool Gateway ← Policy Engine 权限检查
```

### 与传统 Agent 框架的区别

| 维度 | 传统 Agent | Trimum |
|------|-----------|--------|
| 任务 | 临时生成 | Workflow 复用 |
| 通信 | Agent 直接调用 Agent | Event Bus 解耦 |
| 运行 | 脚本执行 | Runtime 管理 |
| 权限 | 依赖 Prompt | 系统级限制 |
| 安全 | 靠模型自我约束 | Landlock/Seccomp/Docker |
| 扩展 | 添加工具 | 注册 Agent |
| 稳定性 | 依赖模型稳定性 | 依赖 Runtime 稳定性 |

## 三大核心模块

### 1. Event Bus（事件总线）

AI Runtime 的神经系统。负责所有组件之间的信息传递，**不负责思考，不负责执行**。

- 任何组件可发布事件、按 topic 订阅
- 三层命名空间：`task.*`（工作流步骤）/ `event.*`（告警通知）/ `system.*`（Runtime 状态）
- Task 状态同步：created → running → completed/failed
- 类比：Linux D-Bus / Android Binder / Kubernetes Event

### 2. Workflow Engine（工作流引擎）

AI Runtime 的任务逻辑。复杂任务的步骤编排与复用。

- Task 拆解、流程控制（顺序/条件/并行/人工确认）
- Workflow 复用——成熟经验不走 Planner，直接执行
- DAG 有向无环图执行器
- 失败处理：重试/降级/回滚
- 类比：Kubernetes Operator / GitHub Actions / Airflow

### 3. Agent Runtime（智能体运行时）

AI Runtime 的进程管理器。Agent 的启动/运行/销毁、权限隔离、工具访问。

- Agent 生命周期管理（spawn → execute → destroy）
- 资源管理（CPU/内存/超时限制）
- 权限隔离（Landlock/Seccomp/Docker/Namespace）
- Tool 管理（Agent → Tool Gateway → Policy 检查 → 执行）
- Agent 注册表（agent.json 声明身份/能力/权限/订阅）
- **Planner Agent**：唯一含 LLM 智能的组件，按需启动，理解新请求→LLM 拆解→固化到 Workflow

## Agent 插件化规范

每个 Agent 通过 `agent.json` 声明身份、能力和权限：

```json
{
  "identity": {
    "name": "system-monitor",
    "display_name": "系统监控助手",
    "version": "1.0.0",
    "description": "持续监控系统健康状态"
  },
  "capabilities": ["system.monitor", "system.diagnose"],
  "lifecycle": {
    "is_hot": true,
    "timeout_seconds": 30,
    "memory_limit_mb": 512
  },
  "allowed_tools": ["shell", "file.read"],
  "permissions": {
    "exec": ["ps", "df", "free", "uptime", "top"],
    "read": ["/proc/**", "/sys/**"]
  },
  "communication": {
    "subscribed_topics": ["task.monitor.*", "event.system.*"],
    "publish_topics": ["event.system.alert"]
  },
  "execution": {
    "entry": "agent.py",
    "risk_level": "low"
  }
}
```

Agent manifest 存于 `~/.trimum/agents/<name>/agent.json`，由 Agent Registry 自动加载。

## 开箱即用清单

### 锁定（必装）

| 类别 | 组件 | 用途 |
|---|---|---|
| 语言 | Python 3.12+ + uv | Runtime 自身依赖 |
| 版本控制 | Git | 代码管理 / AI 修改记录 |
| 容器 | Docker | Agent 沙箱 / 工具链回滚 |
| 系统工具 | ripgrep / fd / jq / btop/htop | 系统监控与搜索 |
| 文件系统 | Btrfs + Snapper | 快照回滚（防滚挂核心） |
| 安全 | Landlock + Seccomp + nftables | 沙箱执行与防火墙 |

### 可选（三档安装模式）

| 模式 | 内容摘要 | 磁盘 |
|---|---|---|
| 🌟 普通模式 | trimum + AI Desktop + Cloud AI + 浏览器 | ~10-20GB |
| 🚀 开发者模式 | 普通模式 + Git/Docker/Cursor/AI编码/Shell增强/数据库 | ~40-60GB |
| 🧪 AI Engineer | 开发者模式 + 本地模型/GPU/RAG/多Agent/DevOps | 100GB+ |

### 预装 Agent

| Agent | 默认启用 | 说明 |
|---|---|---|
| AI Shell | ✅ | 自然语言→安全执行 |
| System Healthy | ✅ | 防滚挂自检 + 更新后检查 |
| Theme Manager | ✅ | AI 辅助切换桌面主题 |
| Security Agent | ✅ | Landlock Hook + 高危操作拦截 |
| Knowledge Agent | ✅ | 长期记忆 + 语义检索（Phase 5 启用） |
| File Ops | ❌ | 可选安装 |
| Coding Agent | ❌ | 由 Codex CLI / Claude Code 替代 |

### 可选软件完整清单

| 类别 | 组件 | 默认模式 |
|---|---|---|
| 编辑器 | VS Code / Cursor | 开发者+ |
| AI 编码 | Codex CLI / Claude Code | 开发者+ |
| 浏览器 | Firefox / Chromium | 普通+ |
| 网络代理 | Clash / V2ray | 开发者+ |
| 文本编辑器 | Neovim | 开发者+ |
| Shell 增强 | zsh / oh-my-zsh / starship / tmux / fzf / zoxide / eza | 开发者+ |
| 数据库 | PostgreSQL + pgvector / MySQL / Redis | AI Engineer |
| 本地 AI | Ollama / llama.cpp / GPU CUDA / ROCm | AI Engineer |
| 系统增强 | Timeshift / Ansible | AI Engineer |

## Shell 深度绑定

| 模式 | 命令 | 场景 | 阶段 |
|---|---|---|---|
| `ai` 统一入口 | `ai "检查docker为什么启动失败"` | 自然语言→执行 | Phase 1 |
| `explain` 管道原语 | `cat server.py \| explain` | 像 grep/awk 一样解释输入 | Phase 3 |
| `fix` 诊断修复 | 命令失败后输入 `fix` | 自动诊断修复 | Phase 3 |

**设计原则**：AI 增强 Shell，不替代 Shell。

## 防滚挂机制

```
更新触发
    ↓
Snapper pre-snapshot
    ↓
System Healthy Agent 检查
    ├── 通过 → 保留新快照
    └── 失败 >= 2 项 → 自动回滚 + 通知用户
```

## 资源占用

| 组件 | 空闲内存 | 说明 |
|---|---|---|
| Python trmd daemon | ~20-40MB | 系统级守护进程 |
| Python Agent Runtime | ~50-100MB | 按需惰性加载 |
| Embedding 模型 | ~0-500MB | 云端 AI 时 0MB |
| Hyprland 桌面 | ~500-800MB | 含 Waybar/通知/壁纸 |
| **合计（典型）** | **~0.8-1.5GB** | |

## 密钥配置

所有 API Key 通过 `~/.trimum/env` 文件管理，**不写入代码**。

```bash
# ~/.trimum/env
OPENAI_API_KEY=***
# DEEPSEEK_API_KEY=***    # 注释即禁用
OPENAI_BASE_URL=https://api.openai.com/v1
```

**规则**：
- 文件权限 `600`
- `trm` / `trmd` 启动时自动加载
- 注释 `#` 即禁用该密钥

## 项目结构

```
trimum/
├── README.md
├── LICENSE
├── .gitignore
├── STATUS.md
├── docs/
│   ├── ARCHITECTURE.md          # 架构文档 v3.0
│   ├── DEVELOPMENT-ROADMAP.md   # 开发路线
│   ├── TECHNICAL-BOM.md         # 技术选型
│   ├── PHASE1-PLAN.md           # Phase 1 历史
│   ├── REFERENCE-PROJECTS.md
│   ├── REUSE-STRATEGY.md
│   └── omarchy-ref/
├── src/
│   └── trimum_core/              # trimum Core（当前开发）
│       ├── __init__.py
│       ├── api_server.py
│       ├── agent_registry.py
│       ├── agent_router.py
│       ├── config.py
│       ├── context_manager.py
│       ├── event_bus.py
│       ├── ipc_handler.py
│       ├── logger.py
│       ├── main.py
│       ├── models.py
│       ├── policy_engine.py
│       ├── tool_gateway.py
│       └── ...（更多模块）
├── config/
│   ├── trimum.yaml
│   └── policy.yaml
├── desktop/
│   ├── themes/           # 22 套预设主题
│   ├── zsh-ai.sh
│   └── ai.ps1
└── scripts/
    └── setup-btrfs-snapper.sh
```

## 开发路线

| Phase | 产出 | 状态 |
|---|---|---|
| 0 | 基础环境 | ✅ 已完成 |
| 1 | AI Shell MVP | ✅ 已完成 |
| 1.5 | 桌面预设 + Btrfs/Snapper | ✅ 已完成 |
| **2** | **trimum Core Runtime** | **🏗️ 当前开发** |
| 3 | Agent SDK | 🔲 |
| 4 | Security Runtime | 🔲 |
| 5 | Memory Layer | 🔲 |
| 6 | ISO | 🔲 |

## 快速开始

### Phase 1 — AI Shell（已完成）

```bash
pip install -e src/trimum-mvp/
echo 'OPENAI_API_KEY=***' > ~/.trimum/env
trm "查看磁盘空间"
```

### Phase 2 — trimum Core（当前开发）

```bash
pip install -e .
trmd                           # 启动 Runtime 守护进程
```

## 许可

MIT License — 详见 [LICENSE](LICENSE)

Copyright (c) 2026 guzhujushi

---

> ✨ trimum — 让 AI Agent 像操作系统进程一样被调度、隔离和协作。
