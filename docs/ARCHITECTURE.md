# trimum — 架构文档

版本：v2.0（2026-08-28）

## 1. 项目定位

### 1.1 它不是

- ❌ 一个新的 Linux 发行版（不碰 Kernel、不换 init、不自造包管理）
- ❌ 一个 AI 聊天助手
- ❌ 一个简单的 Agent 框架
- ❌ 一个桌面美化 dotfiles 项目

### 1.2 它是

**一个以 Arch Linux 为底座、Hyprland 为桌面、trimum 为 AI 基础设施的 Linux 桌面环境。**

目标用户：想用 Linux 但不想折腾的青少年 / 初学者 / 轻度用户。

让计算机从「我要学命令」变成「我描述意图，系统执行」。

### 1.3 与 Omarchy 的关系

Omarchy（basecamp/omarchy, MIT, 31.7k stars）是 DHH 做的开发者开箱即用 Arch 桌面——预装 IDE/Docker/Git，目标是「拿到就能写代码」。

本项目在 Omarchy 的思路基础上加入 AI 层：

| 能力 | Omarchy | 本项目 |
|---|---|---|
| 桌面预设 | ✅ | ✅ + AI 辅助切换 |
| 开发工具 | ✅ | 可选 |
| 自然语言操作 | ❌ | ✅ AI Shell |
| 自动维护 | ❌ | ✅ System Healthy Agent |
| 防滚挂 | ❌ | ✅ Btrfs + Snapper |
| 渣机友好 | ❌ | ✅ 云端 AI |

### 1.4 三层架构（核心创新）

```
 trimum Core        Agent SDK           Retrieval Tool
─────────────────  ─────────────────   ──────────────────
  Runtime            Intelligence         Information
  ────────           ────────────         ───────────
  生命周期             Prompt 模板          语义检索
  权限策略            推理循环              关键词搜索
  工具网关            上下文管理             文档解析
  事件总线            任务规划              向量搜索
  资源管理            Tool 编排             Metadata 过滤
─────────────────  ─────────────────   ──────────────────
  不包含业务逻辑      不拥有系统权限         不参与决策/调度
```

### 1.5 三层关系

```
Agent SDK
    │
    ├── 通过 HTTP API 请求 trimum Core 执行工具
    │      └── trimum Core 判断权限 → 允许/拒绝/询问
    │
    └── imports Retrieval Tool 获取上下文
           └── 返回文本片段 → Agent 自行决策如何使用

trimum Core 不知道 Agent 在想什么。
Agent SDK 不能绕过权限系统。
Retrieval Tool 不能主动推送信息。
```

## 2. 防滚挂体系（Distro-Proof Design）

Arch Linux 滚动更新是整个系统的弱点——但也是一个可以提前设计的工程问题，不是无解的风险。

### 2.1 核心机制：Btrfs + Snapper

```
用户触发更新（trm update / pacman -Syu）
    ↓
Snapper pre-snapshot（更新前系统状态）
    ↓
执行更新
    ↓
System Healthy Agent 全面检查
    ├── 全部检查通过 → 标记快照为 "OK"，保留备用
    └── 检查失败 >= 2 项 → 自动 Snapper rollback
                               ↓
                          用户收到通知：
                          「本次更新有问题，已自动回滚。
                           失败项：xxx」
```

### 2.2 快照策略

| 触发条件 | 动作 | 保留数 |
|---|---|---|
| 每次 `pacman -Syu` 前 | pre/post snapshot | 最新 10 组 |
| 每 24 小时 | 定时快照 | 最新 7 组 |
| AI Agent 重要操作前 | 手动调用 `trm save-state` | 用户指定 |
| 用户手动触发 | `trm snapshot` | 用户指定 |

### 2.3 System Healthy Agent 检查项

预装的默认检查器，每次更新后自动运行：

1. 所有 systemd 服务是否 active（重点关注 dbus / NetworkManager / pipewire）
2. 磁盘可用空间 > 总容量 10%
3. 空闲内存 > 512MB
4. 关键服务端口是否可达（检查 SSH / HTTP 等）
5. 能否连接 AI API（云端 LLM 可达性）
6. /var/log 无大量 ERROR/CRITICAL 日志
7. 内核 `dmesg` 无 OOM / panic / 驱动崩溃
8. 应用层检查：trimum Core API 是否正常返回

若失败数 >= 2 → 自动回滚 + 桌面通知。

## 3. trimum Core 设计

### 3.1 定位

系统级常驻守护进程（Python）。不包含 AI 智能，只管理 Agent 的运行和权限。

> **语言选择说明**：原计划 Rust → 实际落地 Python。理由：Rust 国内企业生态不足、AI 编程助手对 Rust 训练数据覆盖差、vibe coding 报错 AI 难修。trimum Core 的核心瓶颈在 LLM API 延迟（秒级），Python 本身的运行效率（毫秒级）不是问题。Agent SDK 本身是 Python，统一语言栈也降低了维护成本。

### 3.2 模块

```
trmd (Python)
├── event_bus       系统事件通信（文件变更、安全告警、Agent 状态）
├── agent_manager   Agent 进程生命周期（spawn/destroy/restart）
├── policy_engine   权限策略评估（YAML 规则 → Risk Level → Action）
├── tool_gateway    工具调用接口（Shell/Git/Docker）
├── context_manager Agent 上下文持久化（短期内存 / 长期 SQLite）
├── logger          审计日志
└── api_server      HTTP API（Agent SDK 通过这里通信）
```

### 3.3 权限模型

Policy Engine 使用 YAML 规则定义权限策略：详见 `config/policy.yaml`。

核心原则：

- **Level 0（低风险）**：自动执行——`ls`, `df`, `ps`, `git status`
- **Level 1（中等风险）**：用户确认——`rm`, `pacman -S`, `docker build`
- **Level 2（高风险）**：强确认 + 审计——系统配置修改
- **Level 3（禁止）**：直接拒绝——`rm -rf /`、读 `/etc/shadow`

### 3.4 Agent 生命周期

```
    Spawn
      ↓
  Initialized（分配 Context）
      ↓
  Running（执行 Task）
      ↓
  Waiting Tool（请求工具网关）
      ↓
  Completed
      ↓
  Destroyed（释放资源）
```

Agent 默认不常驻。每个任务完成后销毁。System Healthy Agent 可配置为热 Agent。

### 3.5 执行优先路径

- 低风险命令（`ls`, `pwd`）→ 直接执行，不走 Agent 循环
- 中高风险 → 启动 Agent → 推理 → 确认 → 执行

## 4. Agent SDK 设计

### 4.1 定位

Python 包，提供 Agent 开发的基础能力。开发者安装 `trimum-sdk` 后即可快速自定义 Agent。

预装 Agent（开箱即用）：

| Agent | 职责 | 风险等级 |
|---|---|---|
| AI Shell | 自然语言 → 命令 → 安全执行 | 按命令 |
| System Healthy | 系统健康检查 + 更新后自检 | 低（只读） |
| Theme Manager | AI 辅助切换桌面主题 | 低 |
| File Ops | 自然语言文件管理 | 中 |

### 4.2 API 设计

```python
from trimum_sdk import BaseAgent, Tool, Context

class MyAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="my_agent")
        self.register_tool(Tool("git", "git diff", risk_level="low"))

    def reasoning_loop(self, task: str, context: Context) -> str:
        # 1. 解析任务
        # 2. 规划步骤
        # 3. 请求工具（通过 trimum Core API）
        # 4. 合成结果
        # 5. 返回
        return result
```

## 5. Memory Layer 设计

### 5.1 定位

Memory Layer 是 trimum 的**信息持久层**，与 Core 同级，不是 Agent SDK 的子模块。包含两个子层：

| 子层 | 职责 | 实现 | 阶段 |
|---|---|---|---|
| **长期记忆** | Agent 间共享状态、历史决策、用户偏好 | SQLite（轻量）→ PostgreSQL（扩展） | Phase 5 |
| **Knowledge Store** | 文档语义检索、关键字搜索、RAG | PostgreSQL + pgvector | Phase 5 |

### 5.2 设计原则

- **Agent 不知道彼此在想什么，但可以读共享记忆**——长期记忆提供持久化的上下文，但不透传 Agent 的完整推理过程
- **Knowledge Store 不主动推送信息**——Agent SDK 按需调用
- **嵌入模型按需加载**——空闲时 ~0MB，搜索时加载 ~300-500MB

### 5.3 API

```python
from trimum_memory import MemoryStore, KnowledgeStore

# 长期记忆（Agent 共享状态）
memory = MemoryStore(db_url="sqlite:///var/lib/trimum/memory.db")
memory.record("user_preference", {"theme": "everforest"})
pref = memory.recall("user_preference")

# 知识检索
knowledge = KnowledgeStore(
    vector_db="postgresql://localhost:5432/knowledge",
    embedding_model="BGE-small"
)
results = knowledge.search("为什么我的网站访问慢？")
```

## 6. Interface Layer 设计

### 6.1 定位

Interface Layer 是 Harness 从"一个程序"变成"系统级 AI 服务"的关键。没有它，外部程序/插件/脚本无法与 Harness 交互。

> **与 ChatGPT 的对话反馈**评价：★★★★★——"让 Harness 从 AI 助手推进到 AI 运行时"。

### 6.2 三层接口

| 接口 | 协议 | 用途 | 实现阶段 |
|---|---|---|---|
| **CLI** | stdin/stdout | `trm "查看磁盘"` 作为 Shell 原语 | Phase 1 |
| **Unix Domain Socket** | 内部 IPC | Neovim 插件、Waybar 插件、Cron 任务与 core 通信 | Phase 2 |
| **HTTP API** | REST JSON | 外部工具、SDK 客户端、跨语言调用 | Phase 2 |

### 6.3 Shell 深度绑定（CLI 设计）

三种入口模式，让 Harness 进入 Shell 生命周期：

| 模式 | 设计理念 | 阶段 |
|---|---|---|
| **`ai` 统一入口** | `ai "检查docker为什么启动失败"`——自然语言→执行。最通用的入口 | Phase 1 |
| **`explain` 管道原语** | `cat server.py \| explain`——像 grep/awk 一样成为 Shell 原语，解释任何输入 | Phase 3 |
| **`fix` 诊断修复** | 命令失败后输入 `fix`，自动捕获 stdout/stderr/exit code/env/recent changes → 调 Coding Agent 诊断 → 建议修复 | Phase 3 |

> **设计原则**：AI 增强 Shell，不替代 Shell。类似 vim 没有消灭键盘、Copilot 没有消灭代码。

### 6.4 架构中的位置

```
外部世界
  ───→ CLI (`trm "查看磁盘"`)
  ───→ Neovim 插件 (`:trm explain`)
  ───→ Waybar（AI 状态显示）
  ───→ Cron（定时分析系统日志）
  ───→ Landlock Hook（高危操作阻断 → Socket → Security Agent）
            │
       Interface Layer
            │
       ┌────┴────┬─────┬──────┐
       CLI     Socket  HTTP   SDK
       │         │      │      │
       └─────────┴──┬───┘      │
                    │          │
               trimum Core    │
               (事件/权限/工具) │
                    │          │
               Agent SDK  ←────┘
```

## 7. 通信协议

### 7.1 统一消息格式

所有接口（CLI/Socket/HTTP）统一使用 JSON 请求/响应。

```
CLI:
  trm "查看磁盘"
  → trimum Core（同进程 / Phase 2 后走 Socket）
  → { output: "磁盘使用 45%...", risk: "low", action: "auto" }

HTTP:
  POST /api/execute
  { "tool": "shell", "args": ["df", "-h"] }
  ← { "status": "confirmed", "output": "...", "risk": "low" }

Socket:
  Unix Domain Socket → /run/user/1000/trimum.sock
  消息格式同 HTTP，但更轻量、更低延迟
```

### 7.2 安全

- **CLI**：仅限当前用户执行（Unix 权限控制）
- **Socket**：仅监听 `0700` 权限
- **HTTP**：仅监听 `127.0.0.1`，永不暴露公网

## 8. 开发路线

| Phase | 产出 | 内容 | 预估 |
|---|---|---|---|
| 0 | 基础环境 | Arch + Rust + Python + Docker | 1-2 天 |
| 1 | AI Shell MVP | Python CLI (`ai` 入口)，自然语言→安全执行 | 1-2 周 |
| 1.5 | 桌面预设 | Hyprland 主题包 + Snapper 配置 + 安装脚本 | 1 周 |
| 2 | trimum Core | Rust 守护进程 + Interface Layer（Socket + HTTP） | 1-2 月 |
| 3 | Agent SDK | Python 包 + 预装 Agent（含 `explain`/`fix`） | 1 月 |
| 4 | Security | Landlock + Namespace + Sandbox | 2-3 周 |
| 5 | Memory Layer | 长期记忆 + Knowledge Store（pgvector） | 2-3 周 |
| 6 | ISO | 一键安装镜像 | 视需要 |

每个阶段独立可交付。Phase 1 不依赖 Phase 2-6。
