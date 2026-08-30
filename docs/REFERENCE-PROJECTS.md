# 参考开源项目调研（Reference Projects）

> 为 trimum 各 Phase 提供设计参考。调研时间：2026-08-29，来源：GitHub API。
> 标记（⭐）为星标数，标记（📦）为直接可用/可 fork，标记（📖）为设计模式参考。

---

## Phase 1：AI Shell MVP（Python）

### 📖 shell_gpt — AI Shell CLI 标杆

| 属性 | 值 |
|---|---|
| 仓库 | TheR1D/shell_gpt |
| ⭐ | 12,262 |
| 语言 | Python |
| License | MIT |
| 标签 | chatgpt, cheat-sheet, cli, commands |
| 链接 | https://github.com/TheR1D/shell_gpt |

**架构**：CLI 入口 → 单次 LLM 调用 → 命令预览 → 用户确认执行。一个 Python 模块 + Click CLI + OpenAIClient 适配器。

**可借鉴**：
- `sgpt` 子命令实现："我只需要一个按空格就执行的东西"
- LLM Client 适配器模式（OpenAI/Local 切换）
- 流式输出 + Rich 渲染的终端交互
- 执行前确认的安全流程

**不借鉴**：
- 单次请求模式（我们的 Shell Adapter 需要带历史/上下文）
- 无安全策略引擎

### 📦 matheusml/zsh-ai — 极简 Zsh 集成

| 属性 | 值 |
|---|---|
| 仓库 | matheusml/zsh-ai |
| ⭐ | 215 |
| 语言 | Shell |
| License | MIT |
| 链接 | https://github.com/matheusml/zsh-ai |

**架构**：一个 Zsh 函数 `ai()`，调 OpenAI API → 返回命令。单文件，零依赖。

**可借鉴**：
- 安装方式：`source <(...)` 一行命令安装
- `ai` 命令入口的设计哲学：自然语言输入→用户按回车执行

### 📦 wuyuyu1024/shell_ai

| 属性 | 值 |
|---|---|
| ⭐ | 0 |
| 语言 | Python |
| License | NO LICENSE |
| 链接 | https://github.com/wuyuyu1024/shell_ai |

**架构**：本地 Shell Agent，解释+确认+执行三步走。

**可借鉴**：
- Python + Click CLI 的指令模式
- 3 步确认流程的 UI 设计

---

## Phase 2：IPC/Socket 接口（Python → 可选 Rust）

### 📖 nushell/nushell — 结构化数据管道

| 属性 | 值 |
|---|---|
| ⭐ | 40,365 |
| 语言 | Rust |
| License | MIT |
| 链接 | https://github.com/nushell/nushell |

**架构**：Shell + 结构化数据引擎。数据在管道中以结构化的 `Value` 传递，而非纯文本。所有命令以 JSON-like 格式处理输入输出。

**借鉴思路**：
- 结构化管道理念：Harness IPC 的数据格式也应该是结构化的，而非纯文本流
- socket 端点之间的消息格式：序列化 Value 树

### 📖 atuinsh/atuin — Shell 历史同步与模糊搜索

| 属性 | 值 |
|---|---|
| ⭐ | 31,454 |
| 语言 | Rust |
| License | MIT |
| 链接 | https://github.com/atuinsh/atuin |

**架构**：daemon + CLI + SQLite 历史数据库 + 基于 fzf 的模糊搜索界面。支持加密同步。

**借鉴思路**：
- 历史数据库 Schema（command string + cwd + exit_code + session_id + hostname + duration）
- Daemon 自动追踪 shell 交互的设计模式
- 模糊搜索 UI 的集成方式（通过 FZF / skim）

### 📖 suhaibbinyounis/LocalGhost — Localhost 授权守护进程

| 属性 | 值 |
|---|---|
| ⭐ | 1 |
| 语言 | Python + FastAPI |
| License | MIT |
| 链接 | https://github.com/suhaibbinyounis/LocalGhost |

**架构**：FastAPI WebSocket 服务 + system tray 权限弹窗。跨平台（Win/Mac/Linux）。

**可借鉴**：
- 本地 daemon 的授权/弹窗模式
- 跨平台系统 tray 图标实现
- FastAPI 作为 daemon 的基础框架（已验证移值）

---

## Phase 3：安全策略引擎（Python）

### 📖 kaplanelad/shellfirm — 命令安全守卫

| 属性 | 值 |
|---|---|
| ⭐ | 926 |
| 语言 | Rust |
| License | Apache-2.0 |
| 标签 | agent, ai, captcha, devops |
| 链接 | https://github.com/kaplanelad/shellfirm |

**架构**：终端命令拦截器 → allowlist/blocklist/regex pattern matching → 高风险命令需要人机验证（captcha）。AI Agent 定制模式。

**可借鉴**：
- Allowlist 的配置文件格式（YAML，按命令分组）
- 高风险命令的交互式确认（captcha 是一种极端，我们的版要轻量）
- 对 AI Agent（Cline/Codex CLI）的自动拦截模式

### 📖 Asaad-Suliman/hardened-terminal-mcp — 安全 MCP 服务器

| 属性 | 值 |
|---|---|
| ⭐ | 0 |
| 语言 | Python |
| License | MIT |
| 标签 | ai-agents, least-privilege, audit-logging |
| 链接 | https://github.com/Asaad-Suliman/hardened-terminal-mcp |

**架构**：MCP Server，deny-by-default 策略引擎，cwd jail，secret redaction，fail-closed audit log。

**可借鉴**：
- MCP 协议的 Server 实现范例
- deny-by-default 策略模型的设计
- secret redaction（写入审计日志前脱敏）
- cwd jail 隔离实现（限制命令的工作目录）

### 📖 manyu-lnmiit/agent-code-sandbox — 沙箱执行引擎

| 属性 | 值 |
|---|---|
| ⭐ | 0 |
| 语言 | Python |
| License | MIT |
| 链接 | https://github.com/manyu-lnmiit/agent-code-sandbox |

**可借鉴**：
- Python + subprocess 的沙箱实现
- 资源限制方案
- 审计轨迹设计

### 📖 fruitsky/eshu-gateway — 人类在环 SSH 命令网关

| 属性 | 值 |
|---|---|
| ⭐ | 0 |
| 语言 | Python |
| License | MIT |
| 链接 | https://github.com/fruitsky/eshu-gateway |

**可借鉴**：
- 命令的 allowlist/blocklist/JIT approval 三层策略
- 人工审批 JIT 模式下的一次性命令授权

---

## Phase 4：Agent SDK 集成（Python）

### 📖 langchain-ai/langchain — Agent 开发框架

| 属性 | 值 |
|---|---|
| ⭐ | 145,236 |
| 语言 | Python |
| License | MIT |
| 链接 | https://github.com/langchain-ai/langchain |

**评估**：过于重量级（依赖巨多）。Phase 4 前不引入。架构模式可借鉴（Tool 抽象、Agent 编排）。

**可借鉴**：
- Agent 间 Tool 共享的模式
- 多轮对话的记忆管理架构
- Vector Store 集成标准

### 📖 openai/openai-agents-python — OpenAI Agents SDK

| 属性 | 值 |
|---|---|
| ⭐ | 29,053 |
| 语言 | Python |
| License | MIT |
| 链接 | https://github.com/openai/openai-agents-python |

**架构**：轻量级 Agent 框架，支持 tool calling + handoff + guardrails。一个 Python 库，依赖少。

**可借鉴**：
- 极简设计、依赖干净的架构风格
- Guardrail 的工作机制（Pre/Post execution 拦截）
- Handoff/多 Agent 间通信模式
- **可能直接集成**为 Phase 4 的 Agent 运行时

### 📖 HKUDS/nanobot — 超轻量个人 Agent 框架

| 属性 | 值 |
|---|---|
| ⭐ | 47,519 |
| 语言 | Python |
| License | MIT |
| 链接 | https://github.com/HKUDS/nanobot |

**架构**：单进程 WebUI + 多 Agent + MCP 支持。自称为"3 行代码起一个 AI Agent"。

**可借鉴**：
- 轻量化架构（对比 LangChain 来说）
- MCP 集成方式
- WebUI 实现方案

---

## Phase 5-6：快照/回滚 + 自动安装

### 📖 picodotdev/alis — Arch Linux 无人值守安装

| 属性 | 值 |
|---|---|
| ⭐ | 842 |
| 语言 | Shell |
| License | GPL-3.0 |
| 链接 | https://github.com/picodotdev/alis |

**架构**：交互式 Shell 脚本 → Archiso + arch-chroot 自动安装。支持配置化（分区/包/用户）。

**可借鉴**：
- 分区自动布局方案
- 无人值守配置文件的格式设计
- 安装流程的日志记录

### 📖 pyinfra-dev/pyinfra — Python 基础设施自动化

| 属性 | 值 |
|---|---|
| ⭐ | 5,972 |
| 语言 | Python |
| License | MIT |
| 链接 | https://github.com/pyinfra-dev/pyinfra |

**对比**：比 Ansible 轻、纯 Python、性能好。Phase 6 安装脚本的理想基座。

**评估**：Phase 1 就引入 Python 体验，可以顺便引入 pyinfra 处理安装任务。

### 📖 ansible/ansible — 通用 IT 自动化

| 属性 | 值 |
|---|---|
| ⭐ | 70,493 |
| 语言 | Python |
| License | GPL-3.0 |
| 链接 | https://github.com/ansible/ansible |

**不推荐**：太重。提及但不用。

---

## 间接相关 / 设计参考

### 终端 UI 框架

| 项目 | ⭐ | 用途 |
|---|---|---|
| Textualize/textual | 37,079 | Python TUI 框架，可选 |
| Textualize/rich | 57,272 | Rich 终端格式，CLI 输出必用 |
| charmbracelet/gum | 24,301 | Shell 脚本 UI 组件，可参考设计 |
| tiangolo/typer | 19,934 | Python CLI 框架，Phase 1 主力 CLI |

### Shell / 终端工具

| 项目 | ⭐ | 用途 |
|---|---|---|
| eza-community/eza | 23,071 | `ls` 替换，开箱工具清单 |
| sharkdp/bat | 60,294 | `cat` 增强，开箱工具清单 |
| sharkdp/fd | 44,239 | `find` 替换，开箱工具清单 |
| BurntSushi/ripgrep | 67,688 | `grep` 替换，已锁定 |
| jqlang/jq | 35,507 | JSON 处理器，已锁定 |
| ClementTsang/bottom | 13,946 | `top` 替换（btop 同类），已锁定 |
| dandavison/delta | 31,925 | `diff` 增强，开箱可选 |

### 命令执行 / 自动化（替代参考）

| 项目 | ⭐ | 用途 |
|---|---|---|
| fabric/fabric | 15,487 | Python 远程执行，轻量可用 |
| google/zx | 45,710 | JS shell 脚本，不引入 |
| pyinvoke/invoke | 4,770 | Python 任务执行，参考 |

### 配置管理（AI 自我配置参考）

| 项目 | ⭐ | 用途 |
|---|---|---|
| nixos/nixpkgs | 确定性配置管理，设计理念参考 |
| home-manager | NixOS 用户配置，可参考声明式模式 |

### 安全相关

| 项目 | ⭐ | 用途 |
|---|---|---|
| koalaman/shellcheck | 39,956 | Shell 静态分析，政策引擎可内置 |
| hadolint/hadolint | 12,379 | Dockerfile linter，参考策略模型 |
| 0xelitesystem/agent-sandbox-linter | 0 | allowlist 安全漏洞分析，概念参考 |

---

## 新发现补遗（2026-08-29 第二轮搜索）

### 系统健康监控（System Health Agent）

| 项目 | ⭐ | 用途 |
|---|---|---|
| **aristocratos/btop** | 39,342 | C++ 系统监控仪表板，已锁定为开箱工具 |
| **nicolargo/glances** | 28,562 | Python 跨平台系统监控，可参考 metric 架构 |
| **giampaolo/psutil** | 11,270 | Python 系统/进程/网络 API，Phase 2 daemon 必引入 |

### 通知 / 告警（Notification Agent）

| 项目 | ⭐ | 用途 |
|---|---|---|
| **caronc/apprise** | 17,208 | Python 统一通知库（100+ 服务）。单 pip install，依赖轻。Phase 3 直接引入 |
| **binwiederhier/ntfy** | 33,838 | Go pub-sub 推送通知，理念参考 |
| **containrrr/shoutrrr** | 1,662 | Go 通知库，apprise 竞品，不引入 |

### Vector DB / RAG（Knowledge Agent / Phase 5）

| 项目 | ⭐ | 用途 |
|---|---|---|
| **chroma-core/chroma** | 29,180 | 嵌入式向量数据库，pip install。Phase 5 首选 |
| weaviate/weaviate | 16,759 | Go 向量数据库，太重要 Docker |
| qdrant/qdrant | 34,255 | Rust 向量数据库，太重 |
| milvus-io/milvus | 45,873 | Go 向量数据库，太重 |

**决策**：Phase 5 优先评估 chroma（pip 秒装、Python 原生）。如果 embedding 规模 < 10 万条，甚至连 chroma 都不需要，直接用 SQLite + numpy cosine similarity。

### TUI 交互模式（Phase 1-2 UI）

| 项目 | ⭐ | 用途 |
|---|---|---|
| **junegunn/fzf** | 82,712 | Go 模糊搜索，FZF 集成进 Phase 2 shell 历史搜索 |
| **peco/peco** | 7,910 | Go 简化版 fzf，理念参考 |
| **antonmedv/fx** | 20,607 | Go 终端 JSON 查看器 |
| **mikefarah/yq** | 14,200 | YAML/JSON/XML 处理器，加入开箱工具（可选） |
| **Wilfred/difftastic** | 25,000 | 结构化 diff 工具，开箱可选 |

### Theme / 壁纸（Theme Manager Agent）

| 项目 | ⭐ | 用途 |
|---|---|---|
| **dylanaraps/pywal** | 9,074 | Python 壁纸→颜色方案生成。必参考 |
| **themix-project/oomox** | 2,310 | GTK 主题生成器，可配合 pywal |

### 点文件 / 配置管理（Phase 2 Auto-config）

| 项目 | ⭐ | 用途 |
|---|---|---|
| twpayne/chezmoi | 21,359 | Go 点文件管理器（加密/模板），参考设计但不引入 |
| yadm-dev/yadm | 6,408 | Shell 点文件管理（Git 驱动），轻量可选 |
| nix-community/home-manager | 10,296 | Nix 声明式配置，理念参考 |

### 系统工具

| 项目 | ⭐ | 用途 |
|---|---|---|
| **sxyazi/yazi** | 27,200 | Rust 终端文件管理器，File Ops Agent 参考 |
| **jarun/nnn** | 22,000 | C 终端文件管理器，更轻 |
| sindresorhus/trash-cli | 1,412 | JS 安全删除，File Ops Agent 参考 |
| astrand/xclip / kfish/xsel | 1,318 / 410 | C 剪贴板工具 |

### tmux 自动化

| 项目 | ⭐ | 用途 |
|---|---|---|
| tmux-python/tmuxp | 4,570 | Python tmux 会话管理器。Phase 2 Shell Adapter 直接引入 |
| tmux-plugins/tpm | 13,000 | tmux 插件管理器，开箱可选 |
| tmux-plugins/tmux-resurrect | 12,000 | 会话持久化 |

### 任务 / 进程管理（Daemon/Harness 参考）

| 项目 | ⭐ | 用途 |
|---|---|---|
| **Supervisor/supervisor** | 9,110 | Python 进程控制系统。Phase 2 直接引入作为子进程管理器 |
| **agronholm/apscheduler** | 7,617 | Python 任务调度库。Phase 2 daemon 内部任务调度 |
| agronholm/sqlalchemy | 20,000+ | 数据库 ORM，Phase 2 考虑引入（atuin Schema 存储） |

### 未找到成熟开源的项目（确认原创方向）

以下方向 GitHub 上无成熟项目（全是 < 20⭐）：
- AI OS-level daemon（特权+AI 的守护进程）
- Linux 桌面 AI 助手（类似 Copilot for Desktop）
- AI 驱动的 Btrfs 快照管理
- 声明式安全策略 + AI Shell 合成

**结论**：我们选择的创赛道确实还有空白——不是别人做了我们不知道，而是没人做。

### 其他

- **archlinux/archinstall**（8,399⭐, Python）：官方 Arch Linux 安装器，TUI 菜单引导。架构可参考。
- **asheshgoplani/agent-deck**（810⭐, Go）：终端 AI Agent 会话管理器，理念参考。
- **rsteube/carapace-bin**（3,100⭐, Go）：Shell 补全引擎，AI Shell 补全可参考。

---

## 结论

### 第一阶段（Phase 1 MVP）可直接用的

| 项目 | 用途 |
|---|---|
| **tiangolo/typer** | CLI 入口框架 |
| **Textualize/rich** | 终端渲染 |
| **wuyuyu1024/shell_ai** | 3 步确认流程 UI |
| **matheusml/zsh-ai** | `ai` 命令设计参考 |
| **TheR1D/shell_gpt** | LLM 调用适配器模式 |

### 第二阶段（Phase 2 IPC）设计参考

| 项目 | 用途 |
|---|---|
| **suhaibbinyounis/LocalGhost** | FastAPI daemon 实现范例 |
| **atuinsh/atuin** | 历史数据库 Schema + 模糊搜索 UI |
| **nushell/nushell** | 结构化管道理念 |
| **OpenAI Agents SDK** | Python 消息传递模式 |

### 第三阶段（安全引擎）核心参考

| 项目 | 用途 |
|---|---|
| **kaplanelad/shellfirm** | 安全策略配置格式 + 交互确认 |
| **Asaad-Suliman/hardened-terminal-mcp** | MCP 安全服务器 + deny-by-default |
| **manyu-lnmiit/agent-code-sandbox** | Python 沙箱实现 |

### 不需要自己实现的

- **fabric/fabric** 的远程执行 → Phase 6 直接引入 pyinfra
- **openai/openai-agents-python** → Phase 4 可能直接集成
- **HKUDS/nanobot** → MCP 集成方式可参考
- **apprise** → 通知 Agent 直接 pip install
- **psutil** → 系统度量直接 pip install
- **Supervisor** → 子进程管理直接 pip install
- **chroma** → Phase 5 向量存储直接 pip install（或 SQLite + numpy）
