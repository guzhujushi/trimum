# 开发路线详解

> 从零到 AI Native trimum 的逐步工程路线。

---

## Phase 0：基础环境建设

### 状态：✅ 已完成

### 目标
建立可用于开发的 Arch Linux 工作站。

### 锁定（必装）
```bash
pacman -S base-devel rustup python python-pip git docker
rustup default stable
pip install uv
systemctl enable --now docker
pacman -S btop htop jq ripgrep fd
```

### 可选
```bash
# 编辑器
pacman -S code
yay -S cursor-bin

# AI 编码
npm install -g @openai/codex

# 浏览器
pacman -S firefox

# Shell 增强
pacman -S zsh neovim tmux fzf
```

---

## Phase 1：AI Shell MVP

### 状态：✅ 已完成

### 目标
实现「中文意图→命令规划→风险判断→安全执行」闭环。

### 技术栈
Python + Typer + Rich + LLM（OpenAI 兼容 API）

### 架构（单进程）
```
User Input → Intent Parser (LLM) → Command Planner (LLM)
  → Policy Check (YAML) → User Confirm → Executor → Output
```

### 文件结构
```
src/trimum-mvp/
├── cli.py           # Typer 入口
├── llm.py           # LLM 接口封装
├── planner.py       # 命令规划
├── policy.py        # YAML 策略引擎
├── executor.py      # 命令执行
├── output.py        # Rich 格式化
├── config.yaml
├── policy.yaml
└── pyproject.toml
```

### 验收示例
```bash
trm "查看磁盘空间"
# → 自动执行 df -h
trm "删除 node_modules 缓存"
# → 中风险，确认后执行
trm "rm -rf /"
# → 直接拒绝
```

---

## Phase 1.5：桌面预设 + 安装脚本

### 状态：✅ 已完成

### 目标
在一台干净的 Arch 上，运行一个脚本即可拥有完整的 AI Linux 桌面体验。

### 输出
- Hyprland 桌面预设（5 套主题：tokyo-night / catppuccin / gruvbox / nord / rose-pine）
- Btrfs + Snapper 自动配置
- 一键安装脚本 `desktop/install.sh`（bash + pacstrap + chroot + zsh）

### 主题预设每套包含
- Hyprland 配置（窗口/动画/边框）
- Waybar 配置（顶部状态栏 + 系统托盘）
- Kitty 配色
- 壁纸 + 锁屏壁纸

---

## Phase 2：trimum Core Runtime

### 状态：🏗️ 当前开发

### 目标
实现三大核心模块：Event Bus、Workflow Engine、Agent Runtime。

### 技术栈
| 组件 | 选择 | 原因 |
|------|------|------|
| 语言 | Python 3.12+ | AI 生态事实标准、全栈统一 |
| 异步框架 | asyncio + FastAPI | 原生异步 + REST API |
| 序列化 | Pydantic v2 + JSON | 类型安全 |
| 日志 | structlog | 结构化日志 |
| 数据库 | SQLite（原型）→ PostgreSQL（扩展）| 轻量起步 |
| 配置 | PyYAML + Pydantic | 规则引擎 |
| 进程管理 | systemd | trmd 作为守护进程 |

### 子 Phase 分解

#### Phase 2a：Event Bus
- 实现 asyncio 消息队列 + pub/sub 模式
- 三层命名空间：`task.*` / `event.*` / `system.*`
- 事件序列化与持久化（可选）
- 预估：3-5 天

#### Phase 2b：Agent Runtime
- Agent 生命周期管理（spawn/destroy/restart）
- Agent 注册表（`~/.trimum/agents/*/agent.json`）
- 资源限制（内存/CPU/超时）
- 热 Agent 支持（常驻进程）
- 预估：5-7 天

#### Phase 2c：Workflow Engine
- DAG 有向无环图执行器
- Task 拆解与编排
- 顺序/条件/并行/人工确认节点
- Workflow 固化与复用
- 失败处理（重试/降级/回滚）
- 预估：5-7 天

#### Phase 2d：Planner Agent
- LLM 集成（OpenAI 兼容 API）
- 意图理解 → 步骤拆解
- 自动固化到 Workflow Engine
- 按需启动不常驻
- 预估：3-5 天

#### Phase 2e：Interface Layer
- HTTP API（FastAPI 已有框架）
- Unix Domain Socket IPC
- CLI 入口（trm 升级版）
- 预估：3-5 天

### 模块关系图
```
trimum Core (Python)
│
├── Event Bus         系统事件通信（三层命名空间）
├── Workflow Engine   DAG 任务编排与复用
│
├── Agent Runtime     进程生命周期管理
│   ├── Agent Registry     agent.json 注册表
│   ├── Agent Router       能力匹配路由
│   ├── Policy Engine      YAML 策略引擎
│   ├── Tool Gateway       工具调用网关
│   ├── Context Manager    上下文持久化（SQLite）
│   └── Planner Agent      LLM 智能（按需启动）
│
├── Interface Layer   HTTP API / Socket IPC / CLI
└── Logger            审计日志
```

### 当前代码结构
```
src/trimum_core/          # Phase 2 核心包
├── __init__.py
├── api_server.py         # FastAPI 服务
├── agent_registry.py     # Agent 注册表（已实现）
├── agent_router.py       # Agent 路由（已实现）
├── config.py             # 配置管理
├── context_manager.py    # 上下文管理器（已实现）
├── event_bus.py          # (待实现)
├── workflow_engine.py    # (待实现)
├── agent_runtime.py      # (待实现)
├── planner_agent.py      # (待实现)
├── ipc_handler.py        # IPC 处理器（已实现）
├── logger.py             # 日志（已实现）
├── main.py               # 入口
├── models.py             # 数据模型（已实现）
├── policy_engine.py      # 策略引擎（已实现）
├── tool_gateway.py       # 工具网关（已实现）
└── tests/                # 单元测试
```

---

## Phase 3：Agent SDK

### 状态：🔲 待开始

### 目标
提供 Python Agent 开发框架，让第三方开发者可以快速编写 Agent。

### API 设计
```python
from trimum_sdk import BaseAgent, Tool, Context

class MyAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="my_agent")
        self.register_tool(Tool("shell", risk_level="low"))

    def reasoning_loop(self, task: str, ctx: Context) -> str:
        plan = self.plan(task, ctx)
        for step in plan:
            result = self.execute_tool(step.tool, step.args)
        return self.summarize(plan)
```

### 预装 Agent
| Agent | 职责 |
|---|---|
| AI Shell | 自然语言→命令→安全执行（使用已有 trimum-mvp） |
| System Healthy | 系统健康检查 + 更新后自检 |
| Theme Manager | AI 辅助切换桌面主题 |
| File Ops | 自然语言文件管理 |
| Translator | 用户意图→终端命令翻译 |

---

## Phase 4：Security Runtime

### 状态：🔲 待开始

### 实现路径
```
Level 0：直接执行（低风险）——不额外隔离
Level 1：Landlock + Seccomp（中风险）——限制文件/系统调用
Level 2：Docker Container（高风险）——完整沙箱
```

### 依赖
- Linux 内核 5.13+（Landlock）
- Docker（Sandbox 模式）

---

## Phase 5：Knowledge + Memory Layer

### 状态：🔲 待开始

### 目标
长期记忆 + 文档语义检索。

### 技术栈
| 组件 | 选择 |
|---|---|
| 向量数据库 | PostgreSQL + pgvector |
| Embedding 模型 | BGE-small / BGE-base |
| 关键字搜索 | SQLite FTS5 / PostgreSQL tsvector |
| 检索编排 | 自研（轻量）|

### 实现
```python
class MemoryStore:
    def record(self, key, value): ...
    def recall(self, key): ...

class KnowledgeStore:
    def search(self, query, top_k=5): ...
    def add_document(self, path, content): ...
```

---

## Phase 6：ISO / 安装镜像

### 状态：🔲 待开始

### 目标
一键安装盘，Arch Linux + trimum + Hyprland 全自动安装。

### 前提
Phase 2-3 稳定运行后进入此阶段。

---

## 时间线

| Phase | 内容 | 状态 | 预估 |
|---|---|---|---|
| 0 | 基础环境 | ✅ 已完成 | 1-2 天 |
| 1 | AI Shell MVP | ✅ 已完成 | 1-2 周 |
| 1.5 | 桌面预设 + 安装脚本 | ✅ 已完成 | 1 周 |
| **2** | **trimum Core Runtime** | **🏗️ 当前** | **3-4 周** |
| 3 | Agent SDK | 🔲 待开始 | 2-3 周 |
| 4 | Security Runtime | 🔲 待开始 | 2-3 周 |
| 5 | Knowledge + Memory | 🔲 待开始 | 2-3 周 |
| 6 | ISO | 🔲 待开始 | 视需要 |

每个阶段独立可交付。不依赖后续阶段。
