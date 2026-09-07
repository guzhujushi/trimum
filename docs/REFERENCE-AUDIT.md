# REFERENCE-PROJECTS 对照分析 — Phase 3 差距审计

> 调研时间：2026-09-02
> 对照基准：`docs/REFERENCE-PROJECTS.md`（2026-08-29 调研）vs trimum Phase 3 实际状态
> 目的：逐个检查参考项目中提出的"可借鉴"点，看看哪些已落地、哪些未落地

---

## 1. 审查方法

REFERENCE-PROJECTS.md 共调研了约 15 个直接相关的开源项目。其中 Phase 3 安全引擎（shellfirm / hardened-terminal-mcp / agent-code-sandbox / eshu-gateway）和 Phase 4 Agent SDK（openai-agents-python / langchain / nanobot）与 Phase 3 最相关。

本文逐项审查：**该项目提了什么 "可借鉴" → trimum 做了没有 → 差距有多严重**。

---

## 2. Phase 3 安全引擎 — 核心参考项目审计

### 2.1 shellfirm (926⭐) — 命令安全守卫

**借鉴点** | **trimum 状态** | **差距**
:--|:--|:--
Allowlist 配置文件格式（YAML 按命令分组） | ✅ Policy Engine 已有 YAML 规则引擎 | 无差距
高风险命令的交互式确认 | ⚠️ SecurityAgent.confirm() 已有接口但**无 UI 入口** | 中 — 接口定义好了但实际用户收不到弹窗
对 AI Agent 的自动拦截模式 | ❌ 未实现 | 高 — AI 起源的调用和人类输入当前无区分

**trimum 缺少的 shellfirm 实践**：
- **高风险命令的 captcha/验证确认**（shellfirm 最独特的功能）
- **AI Agent 和人类操作的流量区分**（shellfirm 可以识别由 Cline/Codex 生成的命令）

---

### 2.2 hardened-terminal-mcp (0⭐) — 安全 MCP 服务器

**借鉴点** | **trimum 状态** | **差距**
:--|:--|:--
deny-by-default 策略模型 | ✅ Policy Engine 已有 | 无差距
cwd jail 隔离 | ❌ 未实现 | 中 — Agent 当前可访问全文件系统
secret redaction（审计脱敏） | ❌ 未实现 | **高** — 本文已有凭据脱敏 TODO #3.3

**trimum 缺少的 hardened-terminal-mcp 实践**：
- **cwd jail**：限制 Agent 的工作目录，禁止 cd 到授权外路径
- **秘钥输出脱敏**：命令执行结果中如果含有密码/token，在返回给 Agent 前替换掉

---

### 2.3 agent-code-sandbox (0⭐) — 沙箱执行引擎

**借鉴点** | **trimum 状态** | **差距**
:--|:--|:--
Python + subprocess 的沙箱实现 | ❌ 未实现（当前 Tool Gateway 的 ProcessDispatcher 直接 subprocess.Popen） | 低 — subprocess 本身足够，trimum 当前需要的是权限层而非隔离层
资源限制方案 | ❌ 未实现 | 中 — 子 Agent 无 CPU/内存/IO 配额
审计轨迹设计 | ⚠️ 未实现结构化审计日志 | 中 — 只有 print 日志，无查询接口

---

### 2.4 eshu-gateway (0⭐) — 人类在环 SSH 命令网关

**借鉴点** | **trimum 状态** | **差距**
:--|:--|:--
allowlist/blocklist/JIT approval 三层策略 | ✅ JIT approval 对应 SecurityAgent.confirm() | 接口已有但 UI 未实现
一次性命令授权（JIT模式） | ❌ 未实现 | 中 — 当前只有黑白名单，没有"本次通过、下次不通过"的一次性授权

**trimum 缺少的 eshu-gateway 实践**：
- **JIT（Just-In-Time）一次性授权**：每次执行高风险命令都弹窗，不记住——不是永久 allow
- **安全问题**：当前只有黑白名单 + 学习模式计划，缺了 JIT 这个中间带

---

## 3. Phase 4 参考 — 但实际 Phase 3 就该关注的项目

### 3.1 openai-agents-python (29,053⭐) — OpenAI Agents SDK

参考文件中说：*"可能直接集成为 Phase 4 的 Agent 运行时"*

**结果**：2026-08-29 决策已决定集成，但**至今 `src/agent-sdk/` 是空目录**。这是 Phase 3 **最大的未完成项**。

参见 `docs/PYDANTIC-AI-COMPARISON.md` 的完整分析。

---

### 3.2 shell_gpt (12,262⭐) — AI Shell CLI 标杆

**借鉴点** | **trimum 状态** | **差距**
:--|:--|:--
LLM Client 适配器模式 | ✅ 已实现 | 无差距
流式输出 + Rich 渲染 | ❌ 未实现 | 中 — trimum CLI 当前是纯文本输出，无流式体验
执行前确认的安全流程 | ⚠️ 部分实现（Tool Gateway 策略） | 低 — 模式对了，细节待完善

---

### 3.3 LocalGhost (1⭐) — 授权守护进程

**借鉴点** | **trimum 状态** | **差距**
:--|:--|:--
FastAPI daemon + 系统 tray 弹窗 | ⚠️ trimum 已有 API Server（FastAPI）| 无差距，但 tray 弹窗没做
弹窗/ui 实现方式 | ❌ 未实现 | **高** — SecurityAgent.confirm() 的对应 UI 通道不存在

---

### 3.4 atuin (31,454⭐) — Shell 历史同步

**借鉴点** | **trimum 状态** | **差距**
:--|:--|:--
历史数据库 Schema | ✅ Context Manager SQLite 已有类似设计 | 无差距
Daemon 自动追踪 | ❌ 未实现 | 低 — trimum 的 daemon 模式自动启用时需要考虑
模糊搜索 UI | ❌ 未实现 | 低 — 非 Phase 3 必需

---

## 4. 差距汇总（按严重度排序）

### 🔴 高严重度（阻塞长期运行 / 安全）

| # | 差距 | 来源项目 | 根因 | 建议方案 |
|---|---|---|---|---|
| **G1** | **Agent SDK 封装未开始** | openai-agents-python | 计划集成但 de-prioritized 了 | `src/agent-sdk/` 从空目录实现，集成 openai-agents-python 作底层 |
| **G2** | **无 UI 弹窗确认通道** | LocalGhost / eshu-gateway / shellfirm | SecurityAgent.confirm() 有接口无交付 | CLI stdin 输入 / WebSocket 通知 / 桌面通知 |
| **G3** | **无 cwd jail 工作目录隔离** | hardened-terminal-mcp | 未实现 | Tool Gateway 增加工作目录限制配置 |
| **G4** | **无凭据输出脱敏** | hardened-terminal-mcp | 未实现 | Tool Gateway 返回前扫描模式替换（已计划 #3.3） |
| **G5** | **无 AI/人类流量区分** | shellfirm | 未实现 | Transform Agent 输出标记 origin_type:human/ai |

### 🟡 中严重度（影响体验 / 运维）

| # | 差距 | 来源项目 | 建议方案 |
|---|---|---|---|
| **G6** | **无资源配额（CPU/内存/IO）** | agent-code-sandbox | Agent Runtime spawn 时加 psutil 资源限制 |
| **G7** | **无结构化审计日志** | agent-code-sandbox | Policy Engine + Event Bus 输出结构化审计事件 |
| **G8** | **无 JIT 一次性授权模式** | eshu-gateway | SecurityAgent 增加 allow_once 模式 |
| **G9** | **无流式 CLI 输出** | shell_gpt | typer + rich 实现流式渲染 |

### 🟢 低严重度（可推迟）

| # | 差距 | 来源项目 |
|---|---|---|
| **G10** | 无 shell 历史模糊搜索 | atuin |
| **G11** | 无 daemon 自动追踪 | atuin |
| **G12** | 无 captcha 人机验证 | shellfirm |

---

## 5. 已落地的借鉴点（值得肯定的）

| 借鉴点 | 来源 | 对应 trimum 实现 |
|---|---|---|
| Allowlist/blocklist YAML 配置 | shellfirm | config/policy.yaml |
| deny-by-default 策略 | hardened-terminal-mcp | Policy Engine deny 优先 |
| FastAPI daemon 框架 | LocalGhost | api_server.py |
| 三层权限策略（allow/block/approve） | eshu-gateway | Policy Engine + Security Agent |
| LLM Client 适配器模式 | shell_gpt | LLM adapter |
| SQLite 历史/上下文持久化 | atuin | Context Manager |
| Tool 注册/发现/调用 | openai-agents-python | Tool Gateway |

---

## 6. Phase 3 差距与 TODO 同步

| 差距编号 | 对应 TODO | 原 TODO 存在？ | 动作 |
|---|---|---|---|
| G1 | #3 Agent SDK 封装 | ✅ 已有，但排在 3 位 | 已升到第 1 位（本次已改） |
| G2 | #10 弹窗确认 API/UI | ✅ 已有 | 维持原计划 |
| G3 | 新增 | ❌ 无 | 本次新增 |
| G4 | #3.3 凭据脱敏 | ✅ 已有（本次新加） | 维持 |
| G5 | 新增 | ❌ 无 | 本次新增 |
| G6 | 新增 | ❌ 无 | 本次新增 |
| G7 | 新增 | ❌ 无 | 本次新增 |
| G8 | 新增 | ❌ 无 | 本次新增 |
| G9 | 新增 | ❌ 无 | 本次新增 |

---

## 7. 核心结论

### 7.1 七个参考项目，我们只落地了不到一半

在 REFERENCE-PROJECTS.md 列出的 7 个核心参考项目中（shellgpt / shellfirm / hardened-terminal-mcp / agent-code-sandbox / eshu-gateway / LocalGhost / atuin）：
- ✅ 已落地：约 **40%**（YAML 策略、deny-by-default、FastAPI daemon 框架、SQLite 持久化、Tool Gateway）
- ⚠️ 部分落地：约 **25%**（安全弹窗接口、执行前确认模式——但 UI 不对）
- ❌ 未落地：约 **35%**（cwd jail、凭据脱敏、资源配额、结构化审计、JIT 授权、流式输出）

### 7.2 新增 7 项差距（G3-G9）

> 这些原本在 REFERENCE-PROJECTS.md 的"可借鉴"清单里，但未被纳入 TODO。

其中**最紧迫**：
1. **G3 — cwd jail 工作目录隔离**：没有这个，Agent 可以 cd 到系统任意路径操作。安全第一个真正缺口。
2. **G5 — AI/人类流量区分**：没有标签系统，日志和审计里分不清"这是一个 AI Agent 自动跑的命令"还是"用户在终端敲的命令"。
3. **G8 — JIT 一次性授权**：允许一次不可信的未知命令执行，但不创建永久 allow 规则——这是安全设计里缺失的关键一层。

### 7.3 追加行动项

| # | 动作 | 优先级 | 关联 TODO |
|---|---|---|---|
| 1 | **cwd jail**：Tool Gateway 配置中增加 `work_dir` 字段 + 路径合法性校验 | 🟡 中 | 新建 TODO #3.4 |
| 2 | **AI/人类流量区分**：Transform Agent 输出增加 `origin:` 标签；Event Bus 事件携带源信息 | 🟡 中 | 新建 TODO #3.5 |
| 3 | **JIT 一次性授权模式**：SecurityAgent 增加 `allow_once` 参数 + expire 机制 | 🟡 中 | 新建 TODO #3.6 |
| 4 | **资源配额**：Agent Runtime spawn 参数增加 CPU/mem 限制 | 🟢 低 | 新建 TODO #3.7 |
| 5 | **结构化审计日志**：Policy Engine 输出 JSON 审计事件到 Event Bus | 🟢 低 | 新建 TODO #3.8 |
