# 技术选型 BOM（Bill of Materials）

> 根据 v1.1 架构冻结的技术选型。如无充分理由，不更改。

## 1. 系统层

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| OS | Arch Linux | 极简、透明、滚动更新跟进 AI 生态 | Fedora / NixOS |
| Kernel | Linux 6.x+ | Landlock(5.13+) / Seccomp / Namespace 支持 | 自编译内核（不需要） |
| Init | systemd | trmd 作为 systemd 服务管理 | OpenRC |
| 文件系统 | Btrfs | 快照回滚（防止滚动更新炸机） | ext4 / ZFS |
| 开发容器 | Docker | 项目隔离、Agent 沙箱 | Podman |

## 2. Runtime 层（trimum Core）

> 2026-08-29 决策：**全程 Python**。原 Rust 计划取消。理由：Rust 国内企业生态不足、AI 编程助手训练数据覆盖差、vibe coding 报错 AI 难修。Core 瓶颈在 LLM API 延迟（秒级），Python 效率（毫秒级）不影响。全栈统一 Python 降低维护成本。

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| **语言** | Python 3.12+ | AI 生态事实标准、全栈统一 | — |
| 异步框架 | asyncio + aiohttp | Python 原生异步 | FastAPI (ASGI) |
| HTTP 框架 | aiohttp / FastAPI | REST API + WebSocket | Starlette |
| 序列化 | Pydantic v2 + json | 类型安全、与 Agent SDK 统一 | msgspec |
| 日志 | structlog | 结构化日志 | loguru |
| 轻量数据库 | SQLite | Phase 2 原型快速存储 | — |
| 扩展数据库 | PostgreSQL | Phase 3+ 持久化 | MySQL |
| 缓存 | Redis | Context 缓存、Task Queue（可选） | — |
| 规则解析 | PyYAML + Pydantic | Policy Engine 配置 | toml / json |
| 进程管理 | systemd | trmd 作为 systemd 服务 | — |

## 3. Intelligence 层（Agent SDK）

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| 语言 | Python 3.12+ | AI 生态事实标准 | — |
| 包管理 | uv | 极快、替代 pip+venv | Poetry / PDM |
| 数据验证 | Pydantic v2 | Agent SDK 的 Tool/Context 类型定义 | msgspec |
| HTTP 客户端 | httpx | trimum Core API 调用 | aiohttp |
| 模型抽象 | LiteLLM | 统一 OpenAI/Claude/Ollama/DeepSeek 接口 | direct API |
| CLI 框架 | Typer | Phase 1 CLI | Click |
| 终端 UI | Rich | 格式化工具有效输出 | textual |
| Runtime 基础 | BaseAgent (自研) | 提供 reasoning_loop + tool 注册基底 | LangChain |

## 4. Information 层（Retrieval Tool）

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| 语言 | Python 3.12+ | — | — |
| 向量数据库 | PostgreSQL + pgvector | 少维护，一个 DB 解决 | Qdrant / Chroma |
| Embedding 模型 | BGE-small / BGE-base | 中文优秀、本地可跑 | E5 / GTE |
| 文档解析 | PyMuPDF (PDF) / python-docx (Word) / BeautifulSoup (HTML) | — | — |
| 检索编排 | 自研（轻量 200 行） | Phase 5 不需要 LlamaIndex 的复杂度 | LlamaIndex |
| 关键字搜索 | SQLite FTS5 / PostgreSQL tsvector | — | — |

## 5. 安全层

| 组件 | 选择 | 原因 | 前提 |
|---|---|---|---|
| LSM | Landlock (Rust landlock crate) | 文件系统访问限制 | Linux 5.13+ |
| Syscall 过滤 | Seccomp | 限制 Agent 系统调用 | — |
| 隔离 | Namespace (User/Mount) | 轻量进程隔离 | — |
| 沙箱 | Docker | 高风险任务完整隔离 | 已装 Docker |
| 防火墙 | nftables | 网络访问控制 | — |

## 6. 开箱工具清单

### 锁定（必装）

| 工具 | 版本/来源 | 用途 |
|---|---|---|
| Systemd | 默认 | 服务生命周期管理 |
| Rust | rustup stable | 可选——非 Harness 所需，供其他 Rust 项目使用 |
| Python | 3.12+ (uv 管理) | Agent SDK / Retrieval Tool |
| Docker | 最新 | Agent 沙箱 + 工具链回滚保障 |
| Git | 最新 | 版本控制 / AI 修改记录 |
| ripgrep (rg) | pacman | 快速代码搜索 |
| fd | pacman | 快速文件查找 |
| jq | pacman | JSON 处理 |
| btop / htop | pacman | 系统监控 |
| Snapper | pacman | Btrfs 快照管理 |
| Landlock (内核) | Linux 5.13+ | 文件系统安全限制 |
| Seccomp (内核) | 默认启用 | 系统调用过滤 |
| nftables | pacman | 网络防火墙 |

### 可选（三档模式 + 自定义勾选）

安装界面提供三档预设模式，选中后仍可进入详细勾选微调：

| 模式 | 内容 | 磁盘 |
|---|---|---|
| 🌟 **普通模式** | 浏览器 + 桌面组件 | ~10-20GB |
| 🚀 **开发者模式** | 普通 + 编辑器/AI编码/Shell增强/数据库/代理 | ~40-60GB |
| 🧪 **AI Engineer** | 开发者 + 本地模型/GPU/RAG/多Agent/DevOps | 100GB+ |

#### 完整可选清单

| 类别 | 工具 | 来源 | 默认模式 |
|---|---|---|---|
| **编辑器** | VS Code (code) | pacman | 开发者+ |
| | Cursor | AUR (cursor-bin) | 开发者+ |
| | Neovim | pacman | 开发者+ |
| **AI 编码** | Codex CLI | npm 全局 | 开发者+ |
| | Claude Code | npm 全局 | 开发者+ |
| **浏览器** | Firefox | pacman | 普通+ |
| **网络代理** | Clash Meta | AUR (clash-meta) | 开发者+ |
| | V2rayA | AUR (v2raya-bin) | 开发者+ |
| **Shell 增强** | zsh + oh-my-zsh | pacman / AUR | 开发者+ |
| | starship | pacman | 开发者+ |
| | tmux | pacman | 开发者+ |
| | fzf | pacman | 开发者+ |
| | zoxide | pacman | 开发者+ |
| | eza | pacman | 开发者+ |
| **数据库** | PostgreSQL + pgvector | pacman | AI Engineer |
| | MySQL / MariaDB | pacman | AI Engineer |
| | Redis | pacman | AI Engineer |
| **本地 AI** | Ollama / llama.cpp | pacman / AUR | AI Engineer |
| | GPU CUDA / ROCm | 驱动 | AI Engineer |
| **系统增强** | Timeshift | pacman | AI Engineer |
| | Ansible | pacman | AI Engineer |
| **桌面组件** | Waybar | pacman | 普通+ |
| | Cronie | pacman | 普通+ |
| | Landlock Hook | Harness 自带 | 普通+ |
| **Agent 扩展** | Research Agent | pip | AI Engineer |
| | DevOps Agent | pip | AI Engineer |
| | Teaching Agent | pip | AI Engineer |

### 预装 Agent

| Agent | 默认启用 | 备注 |
|---|---|---|
| AI Shell | ✅ | 自然语言→安全执行 |
| System Healthy | ✅ | 防滚挂自检 + 更新后检查 |
| Theme Manager | ✅ | AI 辅助切换桌面主题 |
| Security Agent | ✅ | Landlock Hook + 高危操作拦截 |
| Knowledge Agent | ✅ | 长期记忆 + 语义检索（Phase 5 启用） |
| File Ops | ❌ | 可选安装 |
| Coding Agent | ❌ | 由 Codex CLI / Claude Code 替代 |

## 7. 硬件需求

### Phase 1-2（仅云端 LLM）

| 组件 | 最低 | 推荐 |
|---|---|---|
| CPU | 4 核 | 8 核 |
| RAM | 8GB | 16GB |
| 存储 | 256GB SSD | 512GB SSD |
| GPU | 不需要 | 不需要 |

### Phase 3+（本地模型）

| 模型大小 | 最低 RAM | 推荐 RAM |
|---|---|---|
| 7B 模型 | 8GB | 16GB |
| 14B 模型 | 16GB | 32GB |
| 32B 模型 | 32GB | 64GB + GPU 24GB VRAM |
| Embedding | 4GB | 8GB |

## 8. 不采用的方案及原因

| 方案 | 不采用原因 |
|---|---|
| 自研 Agent 框架替代 LangChain | 用户需要现成的 AI 生态，不是造轮子 |
| PocketFlow 作为编排核心 | 社区太小，维护风险 |
| Desktop 原生应用 (Electron/Tauri) | Phase 6 之前不需要 GUI |
| 多 Agent 框架 (CrewAI/AutoGen) | 当前阶段不需要复杂协作 |
| Kubernetes | 个人单机场景，过度配置 |
| 全自研 RAG (不依赖 LlamaIndex) | 前期检索逻辑简单，可自研；后续可引入 LlamaIndex |

## 9. 技术选型原则

1. **最少依赖原则**：能少装一个包就少装一个
2. **社区成熟优先**：不选小众框架，除非有压倒性理由
3. **延迟决定**：不到那一步，不决定技术细节
4. **可替换**：每个组件应该有备选方案
