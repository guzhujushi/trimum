# trimum

> Arch Linux + Hyprland + trimum = 开箱即用、AI 维护、自然语言操作的 Linux 桌面

## 一句话定位

**一个以 Arch Linux 为底座、Hyprland 为桌面、trimum 为 AI 基础设施的 Linux 桌面环境**。让 Linux 对普通人也可用——自然语言操作、AI 自动维护、开箱即用不折腾。

不需要记住命令参数，不需要手动配置桌面，不需要担心 Arch 滚挂了。

## 与 Omarchy 的区别

Omarchy 是 DHH 打造的"开发者开箱即用 Arch"——装了 IDE、Docker、Git 等开发工具链。

本项目在 Omarchy 的思路基础上再往前推一步：**加入 AI 层**。

| 能力 | Omarchy | 本项目 |
|---|---|---|
| 桌面预设 | ✅ Hyprland | ✅ Hyprland 预设主题包 |
| 开发工具 | ✅ 开箱即用 | ✅ 开箱即用（安装界面可选增减） |
| 自然语言操作 | ❌ | ✅ AI Shell |
| 自动维护 | ❌ | ✅ System Healthy Agent |
| 防滚挂 | ❌ | ✅ Btrfs + Snapper 自动快照 |
| 渣机友好 | ❌ | ✅ 云端 AI，本地零计算负载 |

## 系统架构

```
                    ┌──────────────────┐
                    │  AI Linux Desktop│  ← 你看到的东西
                    │  (Hyprland 预设   │
                    │   + 主题包       │
                    │   + Waybar AI    │
                    │   + AI Launcher) │
                    └────────┬─────────┘
                             │
                    ┌────────┴────────────────────────┐
                    │  Interface Layer   ★新增  ★     │
                    │  CLI ── fix / explain / ai      │
                    │  Socket ── Unix (内部进程通信)  │
                    │  HTTP API ── 外部插件接入      │
                    └────────┬────────────────────────┘
                             │
                    ┌────────┴────────────────────────┐
                    │  trimum Core                   │
                    │  ┌───────────────────────────┐  │
                    │  │ Agent Manager │ Event Bus │  │
                    │  ├───────────────────────────┤  │
                    │  │ Policy Engine │ Tool GW   │  │
                    │  │   ├── Shell Adapter  ★   │  │
                    │  │   ├── Git Adapter        │  │
                    │  │   └── Docker Adapter     │  │
                    │  └───────────────────────────┘  │
                    └────────┬────────────────────────┘
                             │
                    ┌────────┴────────────────────────┐
                    │  Agent SDK + Memory Layer       │
                    │  ├── AI Shell (fix/explain/ai)  │
                    │  ├── System Healthy Agent       │
                    │  ├── Theme / File Ops Agent     │
                    │  └── 长期记忆 + Knowledge 检索 │
                    └────────┬────────────────────────┘
                             │
                    ┌────────┴────────────────────────┐
                    │  Security Layer                 │
                    │  ├── Landlock + Seccomp         │
                    │  └── Docker 沙箱（高风险）     │
                    ├─────────────────────────────────┤
                    │  Reliability Layer              │
                    │  └── Btrfs + Snapper + 健康检查  │
                    └────────┬────────────────────────┘
                             │
                    ┌────────┴────────────────────────┐
                    │  Arch Linux（底座 + 防滚挂）    │
                    └─────────────────────────────────┘
```

## 核心模块

| 层 | 模块 | 职责 | Phase |
|---|---|---|---|
| **桌面** | Hyprland 预设 + 主题包 | 开箱即用、美观、一致 | 1.5 |
| **Interface** | CLI / Unix Socket / HTTP API | 让任何程序都能调用 AI 能力 | 2+ |
| **Core** | trimum Core (Python) | Agent 生命周期、权限策略、工具网关（含 Shell Adapter） | 2 |
| **Agent SDK** | Agent SDK (Python) | AI Shell (fix/explain/ai)、System Healthy、文件操作、主题切换 | 1+ |
| **Memory** | 长期记忆 + Knowledge Store | Agent 间共享状态 + 语义检索 | 5 |
| **Security** | Landlock + Seccomp + Docker | 权限隔离 + 沙箱执行 | 4 |
| **Reliability** | Snapper + Landlock | 快照回滚 + 健康检查 | 1.5

## 开发路线

```
Phase 0 ── 基础环境
  └── Arch + Rust + Python + Docker + Git

Phase 1 ── AI Shell MVP
  └── 自然语言 → 安全执行
  └── 产出：trm 命令行工具

Phase 1.5 ── 桌面预设 + 安装脚本（新）
  └── 5-8 套 Hyprland 主题预设
  └── Btrfs + Snapper 自动配置
  └── 一键安装脚本

Phase 2 ── trimum Core (Python)
  └── Event Bus + Tool Gateway + Policy Engine

Phase 3 ── Agent SDK
  └── AI Shell + System Healthy Agent

Phase 4 ── Security Runtime
  └── Landlock + Namespace + Sandbox

Phase 5 ── Knowledge Layer
  └── 个人知识库

Phase 6 ── ISO / 安装镜像
  └── 一键安装盘
```

## 开箱即用清单

安装时通过三步安装界面（联网 → API Key → 软件勾选），决定权在用户手上。

### 锁定（默认必装，不可取消）

| 类别 | 组件 | 用途 |
|---|---|---|
| **语言** | Python 3.12+ + uv | Harness 自身依赖 |
| **语言** | Rust (rustup) | 可选，Phase 4 Landlock 绑定需要 |
| **版本控制** | Git | 代码管理 / AI 修改记录 |
| **容器** | Docker | Agent 沙箱 / 工具链回滚保障 |
| **系统工具** | ripgrep / fd / jq / btop/htop | 系统监控与搜索 |
| **文件系统** | Btrfs + Snapper | 快照回滚（防滚挂核心） |
| **安全** | Landlock + Seccomp + nftables | 沙箱执行与防火墙 |

### 可选（安装模式或手动勾选）

> 为降低选择焦虑，安装界面提供**三档预设模式**，选中后仍可微调。

#### 三档安装模式

| 模式 | 内容摘要 | 磁盘占用 | 适合人群 |
|---|---|---|---|
| 🌟 **普通模式** | Harness + AI Desktop + Cloud AI + 浏览器 | ~10-20GB | 日常使用 |
| 🚀 **开发者模式** | 普通模式 + Git/Docker/Cursor/AI编码工具/Shell增强/数据库 | ~40-60GB | 写代码 |
| 🧪 **AI Engineer** | 开发者模式 + 本地模型/GPU环境/RAG/多Agent/DevOps工具 | 100GB+ | 深度 AI 开发 |

#### 可选软件完整清单

| 类别 | 组件 | 默认模式 |
|---|---|---|
| **编辑器** | VS Code / Cursor | 开发者+ |
| **AI 编码** | Codex CLI / Claude Code | 开发者+ |
| **浏览器** | Firefox / Chromium | 普通+ |
| **网络代理** | V2ray / Clash | 开发者+ |
| **文本编辑器** | Neovim | 开发者+ |
| **Shell 增强** | zsh / oh-my-zsh / starship / tmux / fzf / zoxide / eza | 开发者+ |
| **数据库** | PostgreSQL + pgvector / MySQL / Redis | AI Engineer |
| **本地 AI** | Ollama / llama.cpp / GPU CUDA / ROCm | AI Engineer |
| **Agent 扩展** | Research / DevOps / Teaching Agent | AI Engineer |
| **系统增强** | Timeshift（快照替代）/ Ansible（批量部署） | AI Engineer |
| **桌面组件** | Waybar、Cron、Landlock Hook 等 | 普通+ |

> 可选软件可以安装后通过 `ai "安装 xxx"` 命令随时增删。

## Shell 深度绑定（Interface Layer）

Harness 不是桌面 AI 窗口，而是进入 Shell 生命周期的系统级 AI 服务。

### 三种入口模式

| 模式 | 命令 | 场景 | 阶段 |
|---|---|---|---|
| **`ai` 统一入口** | `ai "检查docker为什么启动失败"` | 自然语言→执行 | Phase 1 |
| **`explain` 管道原语** | `cat server.py \| explain` | 像 grep/awk 一样解释任何输出 | Phase 3 |
| **`fix` 诊断修复** | `python main.py` 报错后输入 `fix` | 自动捕获 stdout/stderr/exit code，调 Coding Agent 诊断 | Phase 3 |

> **设计原则**：AI 增强 Shell，不替代 Shell。类似 vim 没有消灭键盘、Copilot 没有消灭代码。

### 系统集成

```
trimum
      │
  Interface Layer
      │
  ┌───┴───┬─────┬──────┐
CLI    Socket  HTTP   SDK
│       │      │      │
Shell  Neovim 插件  Waybar  Cron
```

## 资源占用

| 组件 | 空闲内存 | 说明 |
|---|---|---|
| Python trmd daemon | ~20-40MB | 系统级守护进程 |
| Python Agent SDK（常驻） | ~50-100MB | 按需惰性加载 |
| Embedding 模型 | ~0-500MB | 云端 AI 时 0MB；本地按需加载 |
| Hyprland 桌面环境 | ~500-800MB | Waybar + 通知 + 壁纸等 |
| **合计（典型）** | **~0.8-1.5GB** | 含 Hyprland 桌面全开 |

> 云端 AI 是本机零计算负载的关键。对比：Windows 11 空闲 3-5GB、Apple Intelligence 需 16GB RAM。

## 快速开始（Phase 1）

```bash
# 在已有 Arch 上安装
pip install trm

# 用法
trm "查看磁盘空间"
trm "帮我清理缓存，确认后执行"
trm "换个护眼主题"    # Phase 1.5 后
```

## 防滚挂机制

## 密钥配置

所有 API Key 和敏感凭据统一通过 `~/.trimum/env` 文件管理，**不写入代码或配置文件**。

```bash
# ~/.trimum/env — 启动时自动加载
OPENAI_API_KEY=sk-xxx
# DEEPSEEK_API_KEY=sk-xxx       # 注释即禁用，取消注释即可切换
# ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_BASE_URL=https://api.openai.com/v1  # 可更换为国产模型地址

# 通知渠道（可选）
APPRISE_TOKEN=xxx              # Bark / Telegram / 微信等
```

**规则**：
- 文件权限 `600`，仅当前用户可读
- `trm` 和 `trmd` 启动时自动加载此文件
- Agent SDK 提供 `get_secret("OPENAI_API_KEY")` 统一读取
- 注释 `#` 即禁用该密钥，免删除

`#` 是注释符，注释即禁用，取消注释即启用，无需删除密钥行。


```
更新触发
    ↓
Snapper pre-snapshot
    ↓
System Healthy Agent 检查
    ├── 通过 → 保留新快照
    └── 失败 → 自动回滚 + 通知用户
```

## 项目结构

```
trimum/
├── README.md
├── LICENSE
├── .gitignore
├── STATUS.md              # 当前进度一览
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEVELOPMENT-ROADMAP.md
│   ├── TECHNICAL-BOM.md
│   ├── PHASE1-PLAN.md     # Phase 1 详细计划与三文件纪律文档
│   ├── REFERENCE-PROJECTS.md
│   ├── REUSE-STRATEGY.md
│   └── omarchy-ref/       # Omarchy 参考配置文件（只读参考）
├── config/
│   ├── trimum.yaml        # trimum Core 配置
│   └── policy.yaml        # 安全策略规则
├── src/
│   └── trimum-mvp/        # Phase 1 AI Shell MVP（Python）
│       ├── trimum_mvp/    # 核心模块
│       │   ├── cli.py     # 命令行入口（trm）
│       │   ├── llm.py     # LLM 适配器
│       │   ├── planner.py # 离线 fallback 规划器
│       │   ├── executor.py# 执行器
│       │   ├── policy.py  # 策略引擎
│       │   └── output.py  # Rich 格式化输出
│       ├── test_scenarios.py
│       ├── config.yaml
│       ├── policy.yaml
│       └── pyproject.toml
├── desktop/
│   ├── themes/            # 22 套预设主题（来自 Omarchy）
│   │   ├── catppuccin/
│   │   ├── tokyo-night/
│   │   ├── nord/
│   │   ├── gruvbox/
│   │   └── ... (共 22 套)
│   ├── zsh-ai.sh          # Zsh AI Shell 集成
│   └── ai.ps1             # PowerShell AI Shell 集成
├── scripts/
│   └── setup-btrfs-snapper.sh  # Btrfs + Snapper 自动配置
├── tmp/                   # 临时文件（gitignore 已排除）
└── generated/             # 生成文件（gitignore 已排除）
```

## 当前状态

- **Phase 1 (AI Shell MVP)**: ✅ 已完成
- **Phase 1.5 (桌面预设)**: 🏗️ 主题资产已就绪（22 套），安装脚本待写
- **Phase 2 (trimum Core)**: 🔲 未开始
- 详细进度见 [`STATUS.md`](STATUS.md)

## 快速开始

### Phase 1 — AI Shell（实时体验）

```bash
# 1. 克隆仓库
git clone https://github.com/guzhujushi/trimum.git
cd trimum

# 2. 安装依赖
pip install -e src/trimum-mvp/

# 3. 配置 API Key
echo 'OPENAI_API_KEY=sk-xxx' > ~/.trimum/env

# 4. 使用
trm "查看磁盘空间"
trm --dry-run "清理系统缓存"   # 预览不执行
trm "更新系统"              # 策略引擎自动风险评估+确认
```

### 配置环境变量

trimum 通过 `~/.trimum/env` 统一管理所有 API Key，**不写入代码**：

```bash
# ~/.trimum/env
OPENAI_API_KEY=sk-xxx
# DEEPSEEK_API_KEY=sk-xxx    # 注释即禁用
OPENAI_BASE_URL=https://api.openai.com/v1  # 可更换为国产模型
```

文件权限建议 `600`。`trm` 启动时自动加载此文件。

## 贡献指南

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feat/my-feature`
3. 提交变更：`git commit -m 'feat: add new feature'`
4. 推送到分支：`git push origin feat/my-feature`
5. 发起 Pull Request

提交信息格式遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```
feat: 新功能
fix: 修复
chore: 杂项
docs: 文档
refactor: 重构
style: 代码风格
```

## 许可

MIT License — 详见 [LICENSE](LICENSE)

Copyright (c) 2026 guzhujushi

---

> ✨ trimum — 让 Linux 对普通人也可用。  
> 自然语言操作 · AI 自动维护 · 开箱即用不折腾
