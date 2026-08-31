# 技术选型 BOM（Bill of Materials）

> 根据 v3.0 架构冻结的技术选型。如无充分理由，不更改。

---

## 1. 系统层

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| OS | Arch Linux | 极简、透明、滚动更新跟进 AI 生态 | Fedora / NixOS |
| Kernel | Linux 6.x+ | Landlock(5.13+) / Seccomp / Namespace 支持 | 自编译内核（不需要）|
| Init | systemd | trmd 作为 systemd 服务管理 | OpenRC |
| 文件系统 | Btrfs | 快照回滚（防滚挂核心） | ext4 / ZFS |
| 开发容器 | Docker | 项目隔离、Agent 沙箱 | Podman |

---

## 2. Runtime 层（trimum Core）

> 2026-08-29 决策：**全程 Python**。原 Rust 计划取消。

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| **语言** | Python 3.12+ | AI 生态事实标准、全栈统一 | — |
| 异步框架 | asyncio | Python 原生异步 | — |
| HTTP 框架 | FastAPI | REST API + 文档自动生成 | aiohttp / Starlette |
| 序列化 | Pydantic v2 + JSON | 类型安全、与 Agent SDK 统一 | msgspec |
| 日志 | structlog | 结构化日志 | loguru |
| 轻量数据库 | SQLite | 原型快速存储 | — |
| 扩展数据库 | PostgreSQL | Phase 3+ 持久化 | MySQL |
| 缓存 | Redis | Context 缓存、Task Queue（可选）| — |
| 规则解析 | PyYAML + Pydantic | Policy Engine 配置 | toml / JSON |
| 进程管理 | systemd | trmd 作为 systemd 服务 | — |

### Event Bus
| 组件 | 选择 | 原因 |
|---|---|---|
| 消息模式 | asyncio.Queue + pub/sub | 原生异步、零依赖 |
| 命名空间 | 自研三层（task/event/system） | 无需消息队列中间件 |
| 持久化 | 可选（SQLite）| 默认不持久，高性能 |

### Workflow Engine
| 组件 | 选择 | 原因 |
|---|---|---|
| 执行模型 | DAG 有向无环图 | 简单可靠 |
| 实现 | 自研（轻量 ~500 行） | 不需要 Airflow/Prefect 的复杂度 |
| 状态存储 | SQLite | 重启可恢复 |

### Agent Runtime
| 组件 | 选择 | 原因 |
|---|---|---|
| 进程管理 | asyncio.create_subprocess_exec | 原生异步 |
| Agent 隔离 | subprocess（不同进程） | 天然隔离 |
| 热 Agent | asyncio.create_task（协程） | 轻量常驻 |
| 资源限制 | asyncio.timeout + psutil | 简单有效 |

---

## 3. Intelligence 层（Planner + Agent SDK）

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| 语言 | Python 3.12+ | AI 生态事实标准 | — |
| 包管理 | uv | 极快、替代 pip+venv | Poetry / PDM |
| 数据验证 | Pydantic v2 | 类型定义 | msgspec |
| HTTP 客户端 | httpx | Core API 调用 | aiohttp |
| 模型抽象 | 直接 OpenAI 兼容 API | 统一 DeepSeek/Kimi/OpenAI | LiteLLM |
| CLI 框架 | Typer | 已有 Phase 1 代码 | Click |
| 终端 UI | Rich | 格式化输出 | textual |

---

## 4. Information 层（Retrieval Tool / Phase 5）

| 组件 | 选择 | 原因 | 备选 |
|---|---|---|---|
| 语言 | Python 3.12+ | — | — |
| 向量数据库 | PostgreSQL + pgvector | 少维护，一个 DB 解决 | Qdrant / Chroma |
| Embedding 模型 | BGE-small / BGE-base | 中文优秀、本地可跑 | E5 / GTE |
| 文档解析 | PyMuPDF / python-docx / BeautifulSoup | — | — |
| 检索编排 | 自研（轻量 200 行） | Phase 5 不需要 LlamaIndex 复杂度 | LlamaIndex |
| 关键字搜索 | SQLite FTS5 / PostgreSQL tsvector | — | — |

---

## 5. 安全层

| 组件 | 选择 | 原因 | 前提 |
|---|---|---|---|
| LSM | Landlock（Rust landlock crate） | 文件系统访问限制 | Linux 5.13+ |
| Syscall 过滤 | Seccomp | 限制 Agent 系统调用 | — |
| 隔离 | Namespace (User/Mount) | 轻量进程隔离 | — |
| 沙箱 | Docker | 高风险任务完整隔离 | 已装 Docker |
| 防火墙 | nftables | 网络访问控制 | — |

---

## 6. 开箱工具清单

### 锁定（必装）

| 工具 | 来源 | 用途 |
|---|---|---|
| systemd | 默认 | 服务生命周期管理 |
| Python | 3.12+ (uv 管理) | Agent SDK / Core |
| Docker | 最新 | Agent 沙箱 |
| Git | 最新 | 版本控制 |
| ripgrep (rg) | pacman | 代码搜索 |
| fd | pacman | 文件查找 |
| jq | pacman | JSON 处理 |
| btop / htop | pacman | 系统监控 |
| Snapper | pacman | Btrfs 快照管理 |
| Landlock (内核) | Linux 5.13+ | 文件系统安全 |
| Seccomp (内核) | 默认启用 | 系统调用过滤 |
| nftables | pacman | 网络防火墙 |

### 可选（三档模式）

| 模式 | 内容 | 磁盘 |
|---|---|---|
| 🌟 普通模式 | 浏览器 + 桌面组件 | ~10-20GB |
| 🚀 开发者模式 | 普通 + 编辑器/AI编码/Shell增强/数据库/代理 | ~40-60GB |
| 🧪 AI Engineer | 开发者 + 本地模型/GPU/RAG/多Agent/DevOps | 100GB+ |

### 预装 Agent

| Agent | 默认启用 | 说明 |
|---|---|---|
| AI Shell | ✅ | 自然语言→安全执行 |
| System Healthy | ✅ | 防滚挂自检 |
| Theme Manager | ✅ | AI 辅助切换桌面主题 |
| Security Agent | ✅ | Landlock Hook |
| Knowledge Agent | ✅ | Phase 5 启用 |
| File Ops | ❌ | 可选 |
| Coding Agent | ❌ | 由 Codex 替代 |

---

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

---

## 8. 不采用的方案及原因

| 方案 | 不采用原因 |
|---|---|
| 自研 Agent 框架替代 LangChain | 用户需要现成的 AI 生态，不是造轮子 |
| PocketFlow 作为编排核心 | 社区太小，维护风险 |
| Desktop 原生应用 (Electron/Tauri) | Phase 6 之前不需要 GUI |
| CrewAI / AutoGen 作为 Agent 编排 | trimum 的 Event Bus + Workflow Engine 是更底层的编排方案，不在 Agent 层面做编排 |
| LangChain 作为 Agent 框架 | 过度抽象，核心功能 trimum 自研足够 |
| Kubernetes | 个人单机场景，过度配置 |
| 全自研 RAG（不依赖 LlamaIndex）| 前期检索逻辑简单，可自研；后续可引入 LlamaIndex |
| 外部消息队列（RabbitMQ/Kafka）| 单机场景不需要分布式消息队列，asyncio.Queue 足够 |

---

## 9. 技术选型原则

1. **最少依赖原则**：能少装一个包就少装一个
2. **社区成熟优先**：不选小众框架，除非有压倒性理由
3. **延迟决定**：不到那一步，不决定技术细节
4. **可替换**：每个组件应该有备选方案
5. **自研核心，复用外围**：Event Bus / Workflow Engine / Agent Runtime 自研；LLM / 数据库 / 安全复用成熟方案

---

## 10. 时间线

| Phase | 内容 | 状态 | 预估 |
|---|---|---|---|
| 0 | 基础环境 | ✅ 已完成 | 1-2 天 |
| 1 | AI Shell MVP | ✅ 已完成 | 1-2 周 |
| 1.5 | 桌面预设 | ✅ 已完成 | 1 周 |
| **2** | **trimum Core Runtime** | **🏗️ 当前** | **3-4 周** |
| 3 | Agent SDK | 🔲 待开始 | 2-3 周 |
| 4 | Security Runtime | 🔲 待开始 | 2-3 周 |
| 5 | Memory Layer | 🔲 待开始 | 2-3 周 |
| 6 | ISO | 🔲 待开始 | 视需要 |
