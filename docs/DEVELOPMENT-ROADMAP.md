# 开发路线详解

> 从零到 AI Native trimum 的逐步工程路线。

## Phase 0：基础环境建设（1-2 天）

### 目标
建立可用于开发的 Arch Linux 工作站。

### 安装清单

#### 锁定（必装）
```bash
# 语言与核心
pacman -S base-devel rustup python python-pip git docker
rustup default stable

# Python 包管理
pip install uv
uv python install 3.12

# Docker 服务
systemctl enable --now docker

# 系统工具
pacman -S btop htop jq ripgrep fd
```

#### 可选（安装界面勾选，默认全选）
```bash
# 编辑器
# VS Code
pacman -S code
# 或 Cursor（AUR）
yay -S cursor-bin

# AI 编码工具
# Codex CLI（npm 全局）
npm install -g @openai/codex
# Claude Code（npm 全局）
npm install -g @anthropic-ai/claude-code

# 浏览器
pacman -S firefox

# 网络代理
# Clash Meta（AUR）
yay -S clash-meta
# 或 V2ray
yay -S v2raya-bin

# 编辑器（受终端用户）
pacman -S neovim

# 桌面组件（Waybar 属桌面层基础依赖）
pacman -S waybar cronie

# Landlock Hook（Harness Security Agent 依赖）
# Harness 安装脚本自动配置
```

### 验证
```bash
rustc --version
python --version
docker --version
```

## Phase 1：AI Shell MVP（1-2 周）

### 目标
实现「中文意图 → 命令规划 → 风险判断 → 安全执行」闭环。

### 技术栈
- **语言**：Python
- **CLI 框架**：Typer
- **终端 UI**：Rich
- **LLM**：Ollama（本地）/ OpenAI / Claude（通过 LiteLLM）

### 架构（单进程，无需 trimum Core）

```
User Input (自然语言)
    │
    ▼
Intent Parser (LLM)
    │ 提取：意图类型 + 参数 + 风险预估
    ▼
Command Planner (LLM)
    │ 生成：{plan: [步骤], commands: [...], risk: "low|medium|high"}
    ▼
Policy Check (YAML 规则匹配)
    │ 判断：自动执行 / 确认 / 拒绝
    ▼
User Confirm (如需)
    │
    ▼
Executor (subprocess)
    │
    ▼
Output (Rich 格式化)
```

### 文件结构

```
src/trimum-mvp/
├── cli.py                 # Typer 入口
├── intent.py              # 意图解析
├── planner.py             # 命令规划
├── policy.py              # YAML 策略引擎
├── executor.py            # 命令执行
├── llm.py                 # LLM 接口封装
├── config.yaml            # 默认配置
├── policy.yaml            # 权限规则
└── pyproject.toml
```

### 交付标准
```bash
# 安装
pip install trm

# 使用
trm "查看磁盘最大的三个目录"
# → 生成计划：du -h / | sort -rh | head -3
# → 风险：低，自动执行
# → 输出：/home  45G / var  12G ...

trm "删除 node_modules 缓存"
# → 生成计划
# → 风险：中，确认后执行
# → 用户：确认？[y/N]
```

### 策略文件示例

```yaml
# policy.yaml
rules:
  - pattern: "ls|cat|head|tail|find|grep|df|du|ps|pwd|whoami"
    risk: low
    action: auto

  - pattern: "rm|chmod|chown|mv.*/etc|dd"
    risk: high
    action: confirm

  - pattern: "rm -rf /|:(){ :\|:& };:|> /dev/sda"
    risk: critical
    action: deny

# 未匹配的命令
default: confirm
```

### 验证测试

```bash
# 正常流程
trm "查看内存使用"
# 输出：自动执行

# 风险拦截
trm "清除所有日志"
# 输出：确认？[y/N]

# 拒绝
trm "删除系统配置"
# 输出：❌ 该操作已被策略禁止
```

## Phase 1.5：桌面预设 + 安装脚本（1 周）

### 目标
在一台干净的 Arch 上，运行一个脚本即可拥有完整的 AI Linux 桌面体验。

### 输出

```bash
curl -fsSL https://ai-arch.trimum.sh/install | bash
# 或
git clone https://github.com/guzhujushi/ai-native-arch-linux
cd ai-native-arch-linux && ./install.sh
```

### 包含内容

#### 1. Hyprland 桌面预设（5-8 套主题）

每套主题包含完整版：

- Hyprland 配置（窗口/动画/边框）
- Waybar 配置（顶部状态栏 + 系统托盘 + AI 状态）
- Alacritty 配色
- Wofi/Fuzzel 配色
- 壁纸 + 锁屏壁纸
- GTK/QT 主题
- 图标主题

预设列表（社区精选）：

| 主题 | 色调 | 风格 |
|---|---|---|
| Catppuccin Mocha | 暖紫 | 暗色 |
| Tokyo Night Storm | 蓝紫 | 暗色 |
| Nord | 蓝灰 | 暗色/亮色 |
| Gruvbox Dark | 暖黄 | 暗色 |
| Rosé Pine | 粉紫 | 暗色 |
| Everforest | 绿色 | 暗色 |
| Dracula | 紫红 | 暗色 |

AI 辅助切换：

```bash
trm theme "换个护眼的"
# → AI 推荐 Everforest 或 Nord
trm theme set everforest
```

#### 2. Btrfs + Snapper 自动配置

```bash
# 安装脚本自动配置：
# - 创建 Btrfs 子卷布局（@ / @home / @snapshots）
# - 安装配置 Snapper
# - 设置定时快照（每 24h）
# - 设置 pacman hook（每次更新前自动快照）
```

#### 3. 三步安装界面设计

安装脚本运行后进入交互式 TUI（终端界面）。为降低选择焦虑，Step 3 提供**三档预设模式**，选中后仍可进入详细勾选微调。

```
═══════════════════════════════════════
 trimum — 安装程序
═══════════════════════════════════════

 Step 1/3: 联网配置
 ─────────────────────────────────────
 检测到有线网络 ✓
 Wi-Fi 网络： [扫描可用网络...]
   选择：  [Wi-Fi 名称]  ☐ 自动连接

 [下一步 →]

═══════════════════════════════════════

 Step 2/3: AI API Key
 ─────────────────────────────────────
 LLM Provider：
   ○ DeepSeek（推荐，国内直连）
   ○ OpenAI
   ○ 自定义（兼容 OpenAI 协议）

 API Key：  [________________________]

 [测试连接] → 连接成功 ✓

 [下一步 →]

═══════════════════════════════════════

 Step 3/3: 安装模式
 ─────────────────────────────────────

 [🌟 普通模式]    推荐  日常使用
   Harness + AI Desktop + Cloud AI + 浏览器
   磁盘：~10-20GB

 [🚀 开发者模式]        写代码
   普通模式 + Cursor + AI编码 + Shell增强
   + 数据库 + Docker + 网络代理
   磁盘：~40-60GB

 [🧪 AI Engineer]       深度 AI 开发
   开发者模式 + 本地模型 + GPU + RAG
   + 多 Agent + DevOps 工具
   磁盘：100GB+

 [⚙️ 自定义]           手动勾选

 必装（不可取消）：
   Python 3.12 / Rust / Git / Docker
   Snapper / Landlock / Seccomp / Systemd

 预装 Agent：
   ☑ AI Shell     ☑ System Healthy
   ☑ Theme        ☑ Security Agent
   ☑ Knowledge    ☐ File Ops

 [取消]          [下一步：详细勾选]          [直接安装]
```

选择"自定义"或"下一步：详细勾选"后，进入详细软件清单：

```
 Step 3/3: 详细勾选（安装模式：[🌟 普通模式]）
 ─────────────────────────────────────

 编辑器：
   ☐ VS Code                 ☐ Cursor
   ☐ Neovim

 AI 编码工具：
   ☐ Codex CLI               ☐ Claude Code

 浏览器：
   ☑ Firefox

 网络代理：
   ☐ Clash                   ☐ V2ray

 Shell 增强：
   ☐ zsh + oh-my-zsh         ☐ starship
   ☐ tmux                    ☐ fzf
   ☐ zoxide                  ☐ eza

 数据库：
   ☐ PostgreSQL + pgvector   ☐ MySQL
   ☐ Redis

 本地 AI：
   ☐ Ollama / llama.cpp      ☐ GPU CUDA / ROCm

 系统增强：
   ☐ Timeshift               ☐ Ansible

 桌面组件：
   ☑ Waybar                  ☑ Cron
   ☑ Landlock Hook

 Agent 扩展：
   ☐ Research Agent          ☐ DevOps Agent
   ☐ Teaching Agent

 总计磁盘占用：~10-20GB

 [返回模式选择]     [安装]
```

#### 4. 安装后首体验

装完重启后自动触发：
- Harness daemon 启动（systemd）
- Hyprland 桌面自动进入（SDDM 自动登录）
- Waybar 显示 AI 状态
- `ai` 命令已就绪，按 `Super+Space` 打开 AI 输入

#### 5. 多桌面可选（当前仅 Hyprland）

下游可扩展支持 KDE / GNOME。当前仅 Hyprland。

---

## Phase 2：trimum Core（1-2 月）

### 目标
将 CLI MVP 中的核心逻辑抽取为独立守护进程。

### 技术栈
- **语言**：Python 3.12+（原 Rust 计划已取消）
- **异步**：asyncio + aiohttp
- **HTTP**：aiohttp / FastAPI
- **序列化**：Pydantic v2 + JSON
- **数据库**：SQLite（轻量）→ PostgreSQL（扩展）
- **存储**：SQLite（轻量）/ PostgreSQL（扩展）
- **进程管理**：systemd

### 语言选择说明

> 原计划 Rust → 实际落地 Python。理由：Rust 国内企业生态不足、AI 编程助手对 Rust 训练数据覆盖差、vibe coding 报错 AI 难修。Core 瓶颈在 LLM API 延迟（秒级），Python 运行效率（毫秒级）不是问题。Agent SDK 本身是 Python，全栈统一降低维护成本。

### 架构

```
┌──────────────┐
│  trmd    │
│  (Python)    │
│              │
│  ┌────────┐  │     HTTP API
│  │ API    │◄─┼──────────── Agent SDK
│  │ Server │  │
│  └───┬────┘  │
│      │       │
│  ┌───┴────┐  │
│  │ Router │  │
│  └───┬────┘  │
│      │       │
│  ┌───┴────┐  │  ┌──────────┐  ┌──────────┐
│  │ Policy │  │  │  Event   │  │  Tool    │
│  │ Engine │  │  │  Bus     │  │  Gateway │
│  └────────┘  │  └──────────┘  └──────────┘
│              │
│  ┌────────┐  │  ┌──────────┐
│  │ Agent  │  │  │ Context  │
│  │Manager │  │  │ Manager  │
│  └────────┘  │  └──────────┘
└──────────────┘
```

### 模块说明

| 模块 | 职责 | 实现 |
|---|---|---|
| API Server | HTTP 接口，接收 Agent 请求 | aiohttp / FastAPI |
| Router | 请求类型分发 | asyncio.Queue |
| Policy Engine | YAML 规则匹配 + 风险评级 | 自研规则引擎 |
| Event Bus | 系统事件发布/订阅 | asyncio.Event / 消息队列 |
| Tool Gateway | 工具调用封装（Shell/Git/Docker） | asyncio.subprocess |
| Agent Manager | Agent 进程生命周期 | asyncio.create_task |
| Context Manager | Agent 上下文持久化 | SQLite / Redis |

### 依赖清单

```
# requirements.txt
trimum>=0.1.0
aiohttp>=3.9
pydantic>=2.0
pyyaml>=6.0
structlog>=24.0
aiosqlite>=0.20
redis>=5.0
```

### 任务拆解

1. **Week 1**：API Server 框架 + Tool Gateway（Shell 执行）
2. **Week 2**：Policy Engine（YAML 解析 + 规则匹配）
3. **Week 3**：Agent Manager（进程 spawn/destroy）
4. **Week 4**：Event Bus（asyncio）
5. **Week 5**：Context Manager（SQLite 持久化）
6. **Week 6**：集成测试 + 文档

## Phase 3：Agent SDK（1 月）

### 目标
提供 Python Agent 开发框架，让第三方开发者可以快速编写 Agent。

### 技术栈
- Python 3.12+
- Pydantic v2
- httpx（与 trimum Core 通信）
- LiteLLM（模型接口抽象）

### API 设计

```python
from trimum_sdk import Agent, Tool, Context

class CodingAgent(Agent):
    """自动代码 Agent"""

    def __init__(self):
        super().__init__(name="coding-agent")
        # 注册可用工具
        self.register_tool(Tool(
            name="git",
            command="git",
            risk="low"
        ))
        self.register_tool(Tool(
            name="shell",
            command="sh",
            risk="medium"  # 需要通过 Harness 确认
        ))
        # 注册模型
        self.set_model("deepseek-chat")

    def reasoning_loop(self, task: str, ctx: Context) -> str:
        # 1. 获取 Context（项目历史、知识检索）
        # 2. 规划步骤
        # 3. 请求工具（通过 trimum Core）
        # 4. 分析结果
        # 5. 返回

        plan = self.plan(task, ctx)
        for step in plan:
            result = self.execute_tool(step.tool, step.args)
            if result.status == "denied":
                return f"权限不足：{result.reason}"
            step.analysis = self.analyze(result.output)
        return self.summarize(plan)
```

### 交付

```bash
pip install trimum-sdk
```

## Phase 4：Security Runtime（2-3 周）

### 目标
用 Linux 内核安全机制加固 Agent 执行环境。

### 实现路径

```
Level 0：直接执行（低风险）
  └── 不额外隔离

Level 1：轻量隔离（中风险）
  ├── Landlock：限制文件系统访问范围
  ├── Seccomp：限制系统调用
  └── Namespace（User/Mount）：伪隔离

Level 2：沙箱隔离（高风险）
  └── Docker Container：完整虚拟化
```

### 依赖
- Linux 内核 5.13+（Landlock）
- `landlock` Rust crate
- Docker（Sandbox 模式）

## Phase 5：Knowledge Layer（2-3 周）

### 目标
将 Agreement 14（Retrieval Tool）落地为可用的知识检索功能。

### 技术栈
- PostgreSQL 16+ + pgvector
- BGE-small 或 E5（本地 Embedding）
- LlamaIndex（检索编排，可选）

### 实现

```python
# retrieval-tool/src/knowledge_store.py
class KnowledgeStore:
    def __init__(self, db_url, model_name="BAAI/bge-small-zh-v1.5"):
        self.db = create_engine(db_url)
        self.embedder = AutoModel.from_pretrained(model_name)

    def add_document(self, path, content):
        chunks = self.chunk(content)
        embeddings = self.embedder.encode(chunks)
        self.db.insert(chunks, embeddings, metadata={"path": path})

    def search(self, query, top_k=5):
        q_vec = self.embedder.encode([query])
        results = self.db.query(q_vec, top_k)
        return self.rerank(query, results)

    def search_by_keyword(self, keyword, project=None):
        return self.db.keyword_search(keyword, metadata_filter={"project": project})
```

### 重大优化前置说明（新手依然先上PostgreSQL+pgvector）

| 实现 | 部署复杂度 | 召回质量 | 个人项目推荐 |
|---|---|---|---|
| PostgreSQL + pgvector | ⭐ (极低) | 一般 | ⭐ Phase 5 首选 |
| SQLite + sqlite-vec | 低 | 基本 | 验证可行 |
| Qdrant | 中等 | 优秀 | Phase 5+ |
| Chroma | 低 | 一般 | 实验可用 |

## Phase 6：Desktop Integration（视需要）

### 目标
整合 Hyprland 桌面环境。

### 组件
- AI Launcher: Wofi/Fuzzel 调起 trmd API
- Waybar 插件: 显示 Agent 运行状态
- 快捷键: Super+Space → Harness 输入

### 前提
只有 Phase 2-3 稳定运行后才进入此阶段。

## 附：时间线预期

| 阶段 | 时间 | 状态 |
|---|---|---|
| Phase 0 | 1-2 天 | 未开始 |
| Phase 1 | 1-2 周 | **当前目标** |
| Phase 2 | 1-2 月 | 待定 |
| Phase 3 | 1 月 | 待定 |
| Phase 4 | 2-3 周 | 待定 |
| Phase 5 | 2-3 周 | 待定 |
| Phase 6 | 视需要 | 待定 |

每个阶段独立可交付。不依赖后续阶段。
