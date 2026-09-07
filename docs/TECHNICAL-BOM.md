# 技术选型 BOM（Bill of Materials）

> 根据 v1.1 架构总结的技术选型。如无充分理由，不更改。
> 最后更新：2026-09-04（修复 GBK 乱码，同步实际选型）

---

## 1. 系统层

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| OS | Arch Linux | 极简、透明、滚动更新跟上 AI 生态 | Fedora / NixOS |
| Kernel | Linux 6.x+ | Landlock(5.13+) / Seccomp / Namespace 支持 | 自编译内核（不需要） |
| Init | systemd | trmd 用 systemd 服务管理 | OpenRC |
| 文件系统 | Btrfs | 快照/回滚（Snapper） | ext4 / ZFS |
| 容器 | Docker | Agent 沙箱 | Podman |

## 2. Runtime — trimum Core

> 2026-08-29 确定：全程 Python，放弃 Rust。Rust 国内生态不足、AI 编程助手覆盖差。LLM API 调用为主，Python 是自然选择。

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| **语言** | Python 3.12+ | AI 生态标准、全栈统一 | Rust |
| 异步框架 | asyncio | Python 原生异步 | FastAPI (ASGI) |
| HTTP 框架 | FastAPI | REST API + SSE 流 | Starlette |
| **序列化** | Pydantic v2 + JSON | 类型安全，与 Agent SDK 统一 | msgspec |
| 日志 | structlog | 结构化日志 | loguru |
| **数据库** | SQLite (aiosqlite) | 轻量、零配置、Phase 2 够用 | PostgreSQL |
| 进阶数据库 | — | Phase 3+ 再考虑 | MySQL |
| 缓存 | — | Context / Task Queue 目前不需要 | Redis |
| 配置 | PyYAML + Pydantic | Policy Engine 驱动 | toml / json |
| 进程管理 | systemd / psutil | trmd 用 systemd 管理 | supervisor |

## 3. Intelligence — Agent SDK

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| **语言** | Python 3.12+ | AI 生态标准 | Rust |
| 包管理 | uv（或 pip+venv） | 快速 | Poetry / PDM |
| **序列化** | Pydantic v2 | Agent SDK 的 Tool/Context 定义 | msgspec |
| HTTP 客户端 | httpx | trimum Core API 通信 | aiohttp |
| **LLM 网关** | LiteLLM | 统一 OpenAI/Claude/Ollama/DeepSeek | direct API |
| CLI 框架 | Typer | Phase 1 CLI | Click |
| 终端 UI | Rich | 日志美化 | textual |
| **Agent 基类** | BaseAgent（自研） | reasoning_loop + tool call | LangChain |

## 4. Information Retrieval — Tool

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| **语言** | Python 3.12+ | 统一技术栈 | Rust |
| **向量数据库** | PostgreSQL + pgvector | 统一 DB | Qdrant / Chroma |
| Embedding 模型 | BGE-small / BGE-base | 性价比最优 | E5 / GTE |
| 文档解析 | PyMuPDF (PDF) / python-docx (Word) / BeautifulSoup (HTML) | 零外部依赖 | Unstructured |
| RAG 框架 | 自研 ~200 行 | Phase 5 不依赖 LlamaIndex 这类重量级框架 | LlamaIndex |
| 关键字搜索 | SQLite FTS5 / PostgreSQL tsvector | 已有 | Elasticsearch |

## 5. 安全层

| 组件 | 选择 | 依赖 |
|---|---|---|
| LSM | Landlock | Linux 5.13+ |
| Syscall 过滤 | Seccomp | Agent 权限收缩 |
| 隔离 | Namespace (User/Mount) | 轻量隔离 |
| 沙箱 | Docker | 高风险完整隔离 |
| 防火墙 | nftables | 基础防护 |

## 6. 工具链与环境

### 基础依赖

| 依赖 | 安装方式 | 用途 |
|---|---|---|
| systemd | 系统自带 | 服务管理 |
| Python | 3.12+ (uv 管理) | Agent SDK / Runtime |
| Docker | 包管理器 | Agent 沙箱 + 隔离 |
| Git | 包管理器 | 版本控制 / AI 工具链 |
| ripgrep (rg) | pacman | 文件搜索 |
| fd | pacman | 文件查找 |
| jq | pacman | JSON 处理 |
| btop / htop | pacman | 系统监控 |
| Snapper | pacman | Btrfs 快照 |

### 开发与 AI 工具链

| 工具 | 安装方式 | 适用场景 |
|---|---|---|
| VS Code (code) | pacman | 通用编辑器 |
| Cursor | AUR (cursor-bin) | AI 编辑器 |
| Neovim | pacman | 终端编辑器 |
| Codex CLI | npm | AI 编码代理 |
| Claude Code | npm | AI 编码代理 |

### 预装 Agent

| Agent | 用途 | 依赖 |
|---|---|---|
| AI Shell | NL→命令执行 | Harness Runtime |
| System Healthy | 硬件监控 + 告警 | System Monitor |
| Theme Manager | AI 推荐桌面主题 | Hyprland |
| Security Agent | Landlock Hook + 策略 | Security Rule |
| Knowledge Agent | 语义搜索 + RAG | Phase 5 |
| File Ops | 文件读写管理 | Tool Dispatchers |
| Coding Agent | 委派复杂编码 | Codex CLI / Claude Code |

## 7. 硬件需求

### Phase 1-2（仅 LLM API 调用）

| 资源 | 最低 | 推荐 |
|---|---|---|
| CPU | 4 核 | 8 核 |
| RAM | 8GB | 16GB |
| 存储 | 256GB SSD | 512GB SSD |
| GPU | 不需要 | 可选 |

### Phase 3+（本地模型）

| 模型 | 最低 RAM | 推荐 RAM |
|---|---|---|
| 7B 模型 | 8GB | 16GB |
| 14B 模型 | 16GB | 32GB |
| 32B 模型 | 32GB | 64GB + GPU 24GB VRAM |
| Embedding | 4GB | 8GB |

## 8. 不采用清单

| 选项 | 理由 |
|---|---|
| Agent 框架 (LangChain / CrewAI) | 自研更轻量、可控 |
| PocketFlow / 其他 DSL | 自定义 Workflow YAML 已够 |
| Desktop 框架 (Electron/Tauri) | Phase 6 再确定 GUI |
| 多 Agent 框架 (CrewAI/AutoGen) | 自研 Agent Router + Workflow Engine 替代 |
| Kubernetes | 太重，单机场景不需要 |
| 完整 RAG 框架 (LlamaIndex) | Phase 5 自研 ~200 行轻量实现 |

## 9. 核心原则

1. **全程 Python** — 国内生态、AI 编程覆盖、维护简单
2. **自研核心** — Agent Router、Workflow Engine、Tool Gateway 自研
3. **复用基础设施** — psutil/structlog/Pydantic/FastAPI 等
4. **按需加重量** — 不预装，不过度设计
