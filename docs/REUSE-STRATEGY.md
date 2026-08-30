# 开源项目复用策略（Reuse Strategy）

> 目标：在不违反许可证的前提下，最大化复用已有开源代码，将自研代码量压缩到极致。
>
> 选择标准（优先级从高到低）：
> 1. 极致轻量 — 单文件 / 零依赖 / 可 pip 秒装
> 2. 安全 — 权限模型完善、沙箱支持、审计日志
> 3. 方便 — CLI 设计好、文档清楚、中国大陆可访问
> 4. 可自定义 — YAML 配置驱动、插件化、易 fork

---

## Phase 1 — AI Shell MVP

### 复用 1：LLM 适配器 — 抄 shell_gpt

**项目**：TheR1D/shell_gpt（MIT，⭐12k）
**引用部分**：`sgpt/client.py` 中的 OpenAIClient 适配器模式（~200 行）

**具体用哪些**：
| 文件/类 | 用途 | 改动点 |
|---|---|---|
| `client.OpenAIClient` | API 调用封装（stream/non-stream） | 加自定义 base_url 支持国产模型 |
| `client.ChatMessage` | 消息格式 | 可直接复制 |
| `client.APIError` | 错误处理 | 可直接复制 |

**为什么选它**：
- shell_gpt 在 "CLI + LLM" 类项目中依赖最轻（仅 httpx + click），12k stars 验证过稳定性
- 其他同类：`f/awesome-chatgpt-prompts`（⭐120k）是 prompt 合集，`lencx/ChatGPT`（⭐54k）是 GUI

**引用范围限制**：
- 只取 LLM 适配层（~200 行），不引入整个 shell_gpt
- shell_gpt 没有策略引擎、explain/fix 管道、历史追踪，其余模块需自研

---

### 复用 2：Shell 入口 `ai()` — 照搬 zsh-ai

**项目**：matheusml/zsh-ai（MIT，⭐215）
**引用部分**：zsh-ai 的 `ai()` Shell 函数定义（~50 行）

**具体用哪些**：
| 行范围 | 用途 | 改动点 |
|---|---|---|
| 整个 `ai()` 函数 | 终端入口 | 后端从 curl OpenAI 改为调用本地 trm |
| 管道模式 | stdin 传递 | 保留设计，加 explain 模式的特殊处理 |

**为什么选它**：
- zsh-ai 是 Shell AI 集成里核心逻辑最少的（50 行，零依赖），且 MIT 许可
- 其他同类：`withlogicco/autopilot`（⭐50）仅 2 个 release，`auth-xyz/ai-cli`（⭐9）无社区

---

### 设计概念参考：3 步确认 UI（非代码复用）

以下项目不复制代码，但交互设计值得在实现时参考：

| 来源 | 参考内容 | 落地场景 |
|---|---|---|
| `wuyuyu1024/shell_ai`（⭐0，无许可证） | 解释 -> 确认 -> 执行 三步流程 | Phase 1 executor.py 的用户确认交互 |
| Warp 终端（闭源，6.4w⭐） | agentic 模式：自然语言 -> 命令预览 -> 一键执行 | Phase 1 planner.py 的命令预览设计 |
| Windows Terminal `ai` 命令（闭源） | 单行自然语言原地转换为命令，免切上下文 | Phase 1 cli.py 的内联模式 |

---

### 复用 3：策略 YAML 格式 — 抄 shellfirm

**项目**：kaplanelad/shellfirm（Apache-2.0，⭐926）
**引用部分**：shellfirm 的 `rules.yaml` 配置格式设计

**具体用哪些**：
| 配置段 | 说明 | 改造方式 |
|---|---|---|
| `allowed` 分组 | 按风险级别分组（low/high/critical） | 保留，加 medium 级别 |
| `pattern` 字段 | 正则匹配命令 | 保留 |
| `require_captcha` 字段 | 高风险确认标志 | 改为 `require_confirm` |
| 默认行为 | 未匹配命令的处理策略 | 改为默认 `confirm`（shellfirm 默认拦截） |

**为什么选它**：
- shellfirm 是目前唯一针对"终端命令安全"的策略引擎，格式简洁干净（单个 YAML 文件）
- 其他同类：`sottlmarek/DevSecOps`（⭐4k）是资料汇总，`palantir/policy-bot`（⭐2.2k）领域不同

---

## Phase 2 — trimum Core

### 复用 4：历史 SQLite 表结构 — 抄 atuin

**项目**：atuinsh/atuin（MIT，⭐31k）
**引用部分**：`crates/atuin-common/src/database.rs` 中的历史记录表 Schema（8 字段）

**具体用哪些**：
| 字段 | 类型 | 来源 | 用途 |
|---|---|---|---|
| `id` | TEXT (UUID) | atuin | 命令记录唯一标识 |
| `command` | TEXT | atuin | 执行的命令文本 |
| `cwd` | TEXT | atuin | 工作目录 |
| `exit_code` | INTEGER | atuin | 退出码 |
| `session` | TEXT | atuin | 会话 ID |
| `hostname` | TEXT | atuin | 主机名 |
| `duration` | INTEGER (ms) | atuin | 执行耗时 |
| `timestamp` | TEXT (ISO8601) | atuin | 执行时间 |

**为什么选它**：
- atuin 的 Schema 字段覆盖全面（8 个，含 session/duration/hostname），同类 `zsh-history-substring-search`（⭐18k）只搜索不持久化

---

### 复用 5：子进程管理器 — 直接引入 Supervisor

**项目**：Supervisor/supervisor（BSD，⭐9.1k）
**引用方式**：`pip install supervisor`，作为 Phase 2 Agent Manager 的子进程管理引擎

**具体用哪些**：
| 功能 | 说明 |
|---|---|
| 进程 spawn/destroy/restart | Supervisor 原生支持 autorestart + backoff 策略 |
| 日志管理 | 内置 stdout/stderr 重定向 + logrotate |
| 进程通信 | XML-RPC API 可用 Python 客户端调用 |

**为什么选它，不自研**：
- Supervisor 是 Python 进程管理领域 20 年的标准方案
- 自己写 crash handler + signal handler + autorestart 至少要 500 行 Python 代码，且边界情况比想象的多（僵尸进程 / 竞态 / SIGHUP 传播）

---

### 复用 6：系统度量 — 直接引入 psutil

**项目**：giampaolo/psutil（BSD，⭐11k）
**引用方式**：`pip install psutil`，替代 System Healthy Agent 中的 shell 子进程调用

**直接用哪些**：
| 原本方式（替换前） | 替换为 |
|---|---|
| `subprocess.run(["df"])` 查磁盘 | `psutil.disk_usage()` |
| `subprocess.run(["free"])` 查内存 | `psutil.virtual_memory()` |
| `subprocess.run(["systemctl", "status"])` 查服务 | `psutil.process_iter()` 遍历 + `systemctl` 仅关键服务 |

---

## Phase 3 — Agent SDK

### 复用 7：Agent 运行时框架 — 直接引入 openai-agents-python

**项目**：openai/openai-agents-python（MIT，⭐29k）
**引用方式**：`pip install openai-agents`，直接作为 Phase 3 的 Agent SDK 主体

**具体用哪些**：
| 模块 | 用途 | 改动点 |
|---|---|---|
| `agents.Agent` | Agent 基类 | 继承后编写 HarnessAgent |
| `agents.runner.Runner` | Agent 执行循环 | 直接使用 |
| `agents.tool.Tool` | 工具注册基类 | 编写 shell_execute / snapper_snapshot 等自定义 Tool |
| `agents.guardrail.Guardrail` | 执行前/后拦截 | 编写 risk_level_check / user_confirm_guardrail |
| `agents.handoff.Handoff` | Agent 间通信 | 多 Agent 协作时使用 |

**为什么选它**：
| 对比项目 | ⭐ | 不选原因 |
|---|---|---|
| langchain-ai/langchain | 101k | 200+ 依赖，pip 安装 50MB+，对桌面场景过重 |
| crewAIInc/crewAI | 27k | 底层依赖 langchain，同样过重 |
| microsoft/autogen | 39k | 需 .NET 或复杂配置 |
| HKUDS/nanobot | 47k | 底层依赖 transformers + torch，安装 2GB+ |
| **openai-agents-python** | 29k | 仅 pydantic + httpx，pip < 5MB，3 行启动 |

---

### 复用 8：通知渠道 — 直接引入 apprise

**项目**：caronc/apprise（MIT，⭐12k）
**引用方式**：`pip install apprise`，作为所有 Agent 的统一通知引擎

**用途**：
- System Healthy Agent 更新失败通知（桌面弹窗 / Telegram / 微信）
- Security Agent 高危操作告警
- 用户偏好的一次性配置，覆盖 100+ 通知渠道

---

### 复用 9：安全设计概念 — 抄 hardened-terminal-mcp

**项目**：Asaad-Suliman/hardened-terminal-mcp（MIT，⭐0）
**引用方式**：只抄 3 个设计概念，不拉代码

| 概念 | 说明 | 落地方式 |
|---|---|---|
| **deny-by-default** | 未明确允许的命令全部拒绝 | policy.yaml 默认设为 confirm，未匹配命令需显式规则 |
| **cwd jail** | 限制命令的工作目录范围 | Phase 2 executor.py 用 `subprocess.Popen(cwd=)` 限制 |
| **secret redaction** | 审计日志中替换 API Key/密码为 *** | Phase 2 Logger 模块实现正则匹配替换 |

---

## Phase 5 — Memory Layer

### 复用 10：嵌入式向量数据库 — 直接引入 chroma

**项目**：chroma-core/chroma（Apache-2.0，⭐29k）
**引用方式**：`pip install chromadb`，直接替代原计划的 PostgreSQL + pgvector

**为什么替代 PostgreSQL + pgvector**：
| 对比 | PostgreSQL + pgvector | chroma |
|---|---|---|
| 安装复杂度 | 需安装 PostgreSQL 服务 + 创建数据库 + 启用扩展 | pip 秒装，默认嵌入式运行 |
| 桌面场景匹配 | 需要服务管理（启动/停止/备份） | 随 Python 进程启动，免维护 |
| 存储位置 | 数据库文件在 /var/lib/postgresql/ | 默认 ~/.chroma/，用户目录下 |

**什么场景需要切换回 pgvector**：
- 向量规模超过 10 万条
- 需要多用户并发查询（桌面场景不需要）
- 需要与其他应用共享同一 PostgreSQL（桌面场景不需要）

---

## Phase 6 — 安装/自动化

### 复用 11：自动化安装引擎 — 直接引入 pyinfra

**项目**：pyinfra-dev/pyinfra（MIT，⭐5.9k）
**引用方式**：`pip install pyinfra`，直接作为安装脚本执行引擎

**具体用哪些**：
| 模块 | 用途 |
|---|---|
| `pyinfra.api.connect` | SSH/本地连接 |
| `pyinfra.modules.files` | 文件操作（复制模板、修改配置） |
| `pyinfra.modules.systemd` | 服务管理 |

> 需要为 pacman 编写自定义模块（pyinfra 默认只带 apt/yum/dnf）。

---

## 设计理念参考（闭源产品）

| 产品 | 可借鉴的设计 | 对应模块 |
|---|---|---|
| Warp 终端（闭源） | agentic 自然语言 -> 命令预览 -> 一键执行 | Phase 1 planner.py 命令预览交互 |
| Windows Terminal `ai` 命令（闭源） | 内联自然语言命令转换，免切上下文 | Phase 1 cli.py 内联模式 |
| Cursor IDE（闭源） | codebase indexing + 增量语义检索 | Phase 5 Knowledge Store 索引策略 |

> 以上不涉及代码复制，仅作为产品交互设计参考。

---

## 完全不引用的项目及原因

| 项目 | ⭐ | License | 不引用原因 |
|---|---|---|---|
| nushell/nushell | 40k | MIT | Rust + 40k 行，对 Python Core 无直接可用代码 |
| fabric/fabric | 15k | BSD | pyinfra 同作者前作，但 fabric 面向远程 SSH |
| picodotdev/alis | 842 | GPL-3.0 | GPL 传染性强，分区逻辑自研不超过 200 行 |
| wuyuyu1024/shell_ai | 0 | NONE | 无许可证，仅参考交互流程 |
| manyu-lnmiit/agent-code-sandbox | 0 | NONE | 同上 |
| HKUDS/nanobot | 47k | MIT | 依赖 pytorch 2GB+，过重 |
| dylanaraps/pywal | 9k | MIT | Phase 1 用不到，Phase 1.5 评估 |
| sxyazi/yazi | 27k | MIT | 终端文件管理器，Phase 6 再评估 |

---

## 总结：自研 vs 开源复用占比

```
Phase 1  AI Shell       ████████░░░░  80% 自研（入口+策略+执行） + 20% 复用（适配器+格式）
Phase 2  trimum Core   ████████░░░░  75% 自研（FastAPI daemon） + 25% 复用（atuin+Supervisor+psutil）
Phase 3  Agent SDK      ██░░░░░░░░░░  15% 自研（Tool+Guardrail） + 85% pip（openai-agents+apprise）
Phase 4  Security       ██████████░░  85% 自研 + 15% 设计概念借鉴
Phase 5  Memory         ████░░░░░░░░  40% 自研 + 60% chroma 直接引入
Phase 6  Install        ██████░░░░░░  60% 自研 + 40% pyinfra 驱动

全项目：约 50% 自研 + 50% 开源复用
```

> 相比纯自研方案，这个策略节省约 40-45% 的总开发时间。所有引用的项目均为 MIT/BSD/Apache-2.0 许可。
