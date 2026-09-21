# trimum — AI Process Runtime

> **把 AI Agent 变成操作系统级能力。**
> 一个跑在 Linux 上的 AI 基础设施，Agent 文件化、Tool 插件化、Workflow 可编排、随用随启不占资源。

---

## 是什么

trimum 是纯 Python 写的 AI Agent 运行基础设施（Harness）——常驻守护进程 + 可插拔 Agent + 统一 Tool Gateway + 安全沙箱 + 记忆分类索引。

与 TypeScript 生态的 SemaClaw / skelm / Sandcastle 不同，trimum 用 Python 构建，面向 Linux 服务器场景。

### 典型场景

- 开发者用 `trm ask` / `trm exec` 让 AI 在本机执行命令，高风险操作被拦截或要求确认。
- 子 Agent 在受限配额下并行跑长任务，全部动作可审计、可回溯。
- 通过 `~/.trimum/mcp/` 启用第三方 MCP server，其工具与内置工具享受同一套策略与审计。

---

## 🚀 快速开始：CLI 用法

安装后，直接使用 `trm` 命令。

### 基础命令

```bash
trm                           # 查看帮助（默认显示可用子命令）
trm version                   # 显示 trimum 版本
trm health                    # 快速健康检查（不需要 daemon）
trm status                    # 查看当前 Agent 运行状态 / 资源占用
```

### 与 Agent 对话

```bash
# 单次提问（LLM 会规划并执行）
trm ask "查看 /tmp 下有哪些大文件"

# 交互式多轮对话（流式输出，Ctrl+C 退出）
trm ask -i                    # 或 trm ask --interactive

# 指定 Agent
trm ask "..." --agent shell   # 用 shell agent
trm ask "..." --agent plan    # 用 planner agent
```

### 记忆管理

```bash
trm memory list                # 列出所有记忆分类（domain + category）
trm memory get <key>           # 取某条记忆
trm memory set <key> <value>   # 写入一条记忆（自动分类）
trm memory search "关键词"     # 按分类/内容搜索记忆
trm memory stats               # 查看记忆数量统计
```

### 安全与授权

```bash
trm security status            # 查看安全策略状态
trm security allow-once <agent_id> [--tool shell] [--cmd "ls -la"] [--ttl 300]
                               # 签发一次性临时授权 token
trm security tokens            # 列出当前有效 token
```

### 日志与审计

```bash
trm log tail                   # 实时 tail 运行日志
trm log --audit                # 只显示结构化审计日志（JSON 行）
trm log --since 1h             # 最近 1 小时日志
```

### 系统运维

```bash
trm daemon start               # 以守护进程模式运行（默认）
trm daemon stop                # 停止 daemon
trm daemon restart             # 重启
trm doctor                     # 检查环境依赖 / 配置完整性
```

### 示例：完整对话流程

```bash
$ trm ask "备份 nginx 配置"
```

1. Transform Agent 将自然语言转换为标准标签
2. Workflow Engine 在预置 workflow 中匹配"备份配置"流程
3. Tool Gateway 调用 `tar` 命令（低风险自动执行）
4. 执行完成后显示摘要 + Token 消耗

---

## 核心架构

```
用户入口 (CLI / WebChat / TUI)
        │
        ▼
Transform Agent (自然语言 → 标准标签)
        │
        ▼
Workflow Engine (+ Listener)  ← 监听 Event Bus
        │
   ┌────┴────┐
   ▼         ▼
Router    Planner (兜底规划)
   │
   ▼
Security Agent (弹性沙箱决策)
   │
   ▼
Tool Gateway (14+ 原生 Tool)
   │
   ▼
Shell / Git / HTTP / Process / System / Env / File / Knowledge / Notification
```

## 核心组件

| 组件 | 说明 | 状态 |
|---|---|---|
| **Harness Runtime** | AI 进程运行环境，常驻守护 | ✅ |
| **Transform Agent** | 自然语言 → 标准标签语言 | ✅ |
| **Workflow Engine** | 预置流程匹配执行 | ✅ |
| **Security Agent** | 弹性沙箱决策中心 | ✅ |
| **Tool Gateway** | 统一 Tool 注册/发现/权限校验 | ✅ |
| **Memory Classifier** | 记忆分类索引（domain/category），SQLite 快速检索 | ✅ |
| **Event Index** | 事件流分桶匹配，替代线性扫描 | 🟡 已实现但未接进 `EventBus` |
| **Token 消耗显示** | 对话后显示 token 统计（TokenUsageTracker + LiveConsole 面板） | ✅ |
| **结构化审计日志** | JSON 审计落盘（`audit.jsonl` 轮转）+ `trm log audit` 结构化查询 | ✅ |
| **CLI 流式输出** | LLM 应答实时渲染（SSE 流式） | ✅ |

## 浏览器工具（browser）

`~/.trimum/tools/browser/`（`main.py` + `_cdp.py`）是**自研纯 Python CDP 实现**，19 个 action；
默认连本机 `--remote-debugging-port=9222` 的 Chrome（复用登录态），支持 `page.open` / `page.title` /
`page.snapshot` / `util.text` / `act.click` / `act.type` / `util.screenshot` 等动作。

```bash
# 无头启动（不要传初始 URL，避免 Chrome “Multiple targets” 限制）
chrome --headless=new --remote-debugging-port=9222 --remote-allow-origins=* \
  --user-data-dir="$HOME/.trimum/tools/browser/chrome-profile" \
  --no-first-run --disable-gpu
```

- CDP 地址优先级：`cdp` 请求参数 > `CLI_ANYTHING_CDP_URL` > `http://localhost:9222`。
- 可选后端 `backend: "domshell"`（DOMShell Chrome 扩展 + `DOMSHELL_TOKEN`），只作对照，不是默认。
- CLI-Anything 的 `browser` 方案已**调研否决**（依赖 Node.js + npx + DOMShell，与「去 Node」冲突）；
  证据见 `docs/CLI-ANYTHING-RESEARCH.md`，路由与分层细节见 `docs/ARCH.md`。

## 配置与密钥

### API Key 存放位置

优先级从高到低：

1. **环境变量**（推荐）
   ```bash
   # Linux/macOS
   export DEEPSEEK_API_KEY="sk-xxx"
   
   # Windows PowerShell
   $env:DEEPSEEK_API_KEY="sk-xxx"
   ```

2. **配置文件**：`~/.trimum/.env` 或 `/etc/trimum/.env`
   ```bash
   DEEPSEEK_API_KEY=sk-xxx
   TRIMUM_LLM_BASE_URL=https://api.deepseek.com/v1
   TRIMUM_LLM_MODEL=deepseek-chat
   ```

3. **安装向导**：`trm install` 时交互式输入

---

## 开发状态

| Phase | 内容 | 状态 |
|---|---|---|
| Phase 0 | 基础设施 | ✅ |
| Phase 1 | AI Shell MVP | ✅ |
| Phase 1.5 | 桌面预设（Hyprland 主题） | ✅ |
| Phase 2 | Harness Runtime Core — 23 模块 | ✅ |
| Phase 2.5 | Tool Dispatcher 重构 — 14 种原生 Tool | ✅ |
| Phase 3 | 弹性沙箱体系（Security + Behavior + System Monitor + 三重记忆 + Agent Socket + Workflow v2） | ✅ |
| Phase 3.5 | Token 管理 + 结构化审计 | ✅ |
| 生态四层（E0–E7） | L0 环境清单 `trm env` / L1 MCP / L2 Agent Skills / L3 workflow 目录 | ⏳ E1–E4 + W1 已实现，E5 官方分发渠道待做 |
| Phase 4 | Landlock LSM + Namespace + Seccomp 沙箱 | 📝 设计 |

---

## 许可

MIT License — Copyright (c) 2026 guzhu jushi
