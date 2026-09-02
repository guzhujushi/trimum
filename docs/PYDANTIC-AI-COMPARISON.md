# Pydantic AI vs trimum Agent SDK 对比分析

> 调研时间：2026-09-02
> 来源：pydantic.dev/docs/ai/ 官方文档（Pydantic AI v0.x, Pydantic AI Harness v0.x）
> 项目地址：https://github.com/pydantic/pydantic-ai（⭐ 29,000+）

---

## 一、定位不同：两个完全不同的项目

**Pydantic AI** = Python AI Agent **SDK**
- 一个库（`pip install pydantic-ai`），让你写 Agent
- 核心：typed agent loop、任意 LLM 一字符串切换、结构化输出、Function Tool、实时语音
- Harness 是上层：围绕 agent loop 的 50+ 能力插件（Capability），**Coder/Researcher 是它产品化的旗舰**

**trimum** = Linux **AI Process Runtime**
- 一个守护进程（`trmd`），把 Agent 当操作系统级资源管理
- 核心：Agent 生命周期、权限沙箱、Event Bus 通信、Workflow 编排、Tool Gateway
- Agent SDK 是 Harness Core 的一个子模块——**不是 trimum 的产品，是它的内部实现手段**

> 💡 **一句话**：Pydantic AI 是做 Agent 的**工具**，trimum 是跑 Agent 的**平台**。

---

## 二、关键能力逐项对比

### 2.1 Agent 定义与执行

| 维度 | Pydantic AI | trimum (当前 Phase 3) |
|---|---|---|
| Agent 定义 | Python 类 + `Agent(model, instructions, tools)` | 文件化 `~/.trimum/agents/<name>/agent.json5 + main.py` |
| LLM 绑定 | 一字符串切换任意模型（openai/anthropic/google/ollama/...） | 未实现 Agent 级模型配置（当前通过 config/trimum.yaml） |
| 结构化输出 | Pydantic model 作为 `output_type`，强类型保证 | 无结构化输出的原生支持（Planer Agent 直接返回字符串） |
| 执行入口 | `agent.run_sync()` / `agent.run()` / CLI `clai` | `trm "..."` → Transform → Workflow → Dispatch |
| IDE/类型检查 | 全类型注解，IDE 实时检查 | Python 代码未做 SDK 级类型导出 |

**trimum 差距**：
- ❌ **缺少 Agent 级结构化输出**：当前 Planner Agent 的 plan_with_llm() 返回的是原始字符串
- ❌ **Agent SDK 封装未开始**：`src/agent-sdk/` 是空目录，尚未集成 openai-agents-python

### 2.2 Sub-Agent 与委派

| 维度 | Pydantic AI | trimum (当前 Phase 3) |
|---|---|---|
| 子 Agent 定义 | `SubAgent(Agent(...))`，可设独立的 usage_limits/timeout | Agent Runtime：spawn/kill/status + Agent Socket JSON-RPC |
| 委派方式 | `delegate_task(agent_name, task)` tool，同步 | Event Bus 发布 TASK_ASSIGNED → Agent Runtime spawn |
| 上下文隔离 | 自有 message history，不混 parent 上下文 | 自有上下文（Context Manager 三重记忆） |
| 预算控制 | 每个 SubAgent 独立 usage_limits / max_calls / timeout | Agent Runtime 有最大 Agent 数限制，无独立 token 预算 |
| 事件流 | event_stream_handler 传递模型流 | 只有 Agent 生命周期事件（started/stopped/failed） |

**trimum 差距**：
- ❌ **子 Agent 缺少 token 预算/调用配额控制**——当前只有进程数限制
- ❌ **子 Agent 运行事件不包含模型流输出**，只有状态变更事件
- ⚠️ trimum 的架构（Event Bus + Socket 通信）支持更自由的编排，但**没有 Pydantic AI 的同步委派 API 那么简单直接**

### 2.3 安全与权限

| 维度 | Pydantic AI | trimum (当前 Phase 3) |
|---|---|---|
| 工具白名单 | Shell(allowed_commands=[...]) 命令级白名单 | Tool Gateway 命令级 + 路径级双层检查 |
| 凭据脱敏 | 内置 denied_env_patterns（LLM_API_KEY_ENV_PATTERNS） | 未实现 secrets redaction |
| 输入护栏 | InputGuardrail：block/replace/retry | 无输入护栏（当前无 Transform Agent 以外的输入处理） |
| 输出护栏 | OutputGuardrail：检查模型输出 | 无输出护栏 |
| 行为监控 | 无（由工具级白名单兜底） | Security Agent + Behavior Monitor（滑动窗口 300s，8 大类 22 小类） |
| Policy 学习 | 无 | 未实现（已计划，见 TODO.md #14.6） |
| 弹窗确认 | 无（approve 是 Guardrail outcome 但无独立弹窗） | SecurityAgent.confirm() 已定义接口但无 UI |

**trimum 优势**：
- ✅ **Behavior Monitor**（行为异常检测）——Pydantic AI 完全没有这个能力
- ✅ **Security Agent**（三层沙箱决策）——远超 Pydantic AI 的安全深度
- ✅ **Policy Engine**（YAML 规则引擎）——Pydantic AI 没有规则引擎概念

**trimum 差距**：
- ❌ **凭据脱敏**（secret redaction）——Pydantic AI 内置了 API key/token 自动脱敏，我们没做
- ❌ **输入/输出护栏**——Guardrail 模式 Pydantic AI 有成熟实现，我们还没开始
- ⚠️ Shell 白名单 + 环境变量过滤 Pydantic AI 已直接解决，trimum 的 Tool Gateway 还在自己手写

### 2.4 上下文与记忆

| 维度 | Pydantic AI | trimum (当前 Phase 3) |
|---|---|---|
| 记忆持久化 | Memory(FileStore/PostgresStore) 跨会话 | Context Manager SQLite（三重：Agent私有/项目共享/Planner全局） |
| Context 压缩 | Compaction（tool clear / sliding window / LLM summary） | 未实现（当前不控制上下文窗口） |
| 工具输出控制 | ToolOutputLimits（截断/外溢/摘要） | 未实现（当工具输出巨大时直接进上下文） |
| 技能/指令 | Skills（SKILL.md 按需加载） + Repo Context（AGENTS.md） | 未实现 |

**trimum 差距**：
- ❌ **没有 Context 窗口管理**——这是长期运行 Agent 的最大问题，Pydantic AI Harness 有成熟的方案
- ❌ **没有 Skills/指令注入机制**——Pydantic AI 的 SKILL.md 动态加载可直接复用
- ❌ **不控制工具输出大小**——大工具返回内容直接膨胀上下文

### 2.5 模型与适配器

| 维度 | Pydantic AI | trimum |
|---|---|---|
| 模型支持数量 | 30+ provider，字符串切换 | 2 个（config.yaml 配置 LLM） |
| 模型类型 | 纯文本 + 实时语音 + Embedding + 图像生成 | 纯文本（openai-compatible） |
| 测试模型 | 内置 `Agent('test')` 无需 LLM 运行 | 这里要 mock LLM 调用 |
| 多 Provider 编排 | 无（但可通过 Gateway 做 failover） | 无 |
| 思考/Reasoning | Thinking 能力插件（配置 effort 级别） | 无 |

**trimum 差距**：
- ❌ **内置 `test` 模型**——写测试时 mock LLM 调用很不方便
- ❌ **极少的 provider 支持**——trimum 当前只做了 openai-compatible 一个适配器

### 2.6 可观测性

| 维度 | Pydantic AI | trimum |
|---|---|---|
| 遥测 | 原生 OpenTelemetry + Pydantic Logfire 集成 | 无（只有 print 级别的日志） |
| Token 追踪 | 内置 usage API，追踪每次调用的 token 消耗 | 无 |
| 成本监控 | 通过 genai-prices 库自动算钱 | 无 |
| Evals | Pydantic Evals：像 pytest 测试代码一样测 Agent | 无 |

**trimum 差距（大）**：
- ❌ 完全没有可观测性基础设施
- Pydantic AI 的 OTel/Logfire 集成是非常成熟的方案

---

## 三、本质差异：哲学不同

```
Pydantic AI 哲学：
  "Agent 就是你写的一个 Python 对象，在 IDE 里编，在 Python 里跑。"

trimum 哲学：
  "Agent 是你文件系统里的一个目录，trmd 管它，Event Bus 叫它，Policy Engine 拦住它。"
```

| 维度 | Pydantic AI | trimum |
|---|---|---|
| 用户 | Python 开发者 | Linux 桌面用户 |
| 部署 | `pip install`，import 即用 | 安装脚本 `install.sh`，systemd 守护进程 |
| Agent 共享 | 代码/包管理 | `cp` 即安装，`ls` 即发现 |
| 安全模型 | 库级别的工具白名单 | 操作系统级别的三层沙箱 |
| 扩展方式 | pip 安装 + import | 文件目录 + Event Bus 事件订阅 |
| Workflow | Pydantic Graph（图论） | Workflow Engine（DAG + Listener/Trigger） |

---

## 四、对我们 Phase 3 的影响分析

### 4.1 当前已做了什么

| Phase 3 项 | 状态 | 与 Pydantic AI 的关系 |
|---|---|---|
| Event Bus (pub/sub) | ✅ | trimum 独有的 OS 级事件机制，Pydantic AI 无 | 
| Agent Socket (Unix Socket) | ✅ | 底层通信层，Pydantic AI 无 |
| Agent Runtime (spawn/kill) | ✅ | 进程级管理，Pydantic AI 无 |
| Security Agent | ✅ | trimum 独有的安全深度 |
| Behavior Monitor | ✅ | trimum 独有的异常检测 |
| Policy Engine | ✅ | trimum 独有的规则引擎 |
| Workflow v2 (监听器→执行组) | ✅ | trimum 独有的编排模式 |
| Context Manager 三重记忆 | ✅ | 已实现 |
| Tool Gateway (11 Dispatchers) | ✅ | 已实现 |
| **Agent SDK 封装** | ❌ 空目录 | **最关键的差距** |

### 4.2 最大的不足（按紧迫度排序）

| # | 不足 | 原因 | 建议方案 |
|---|---|---|---|
| **1** | **Agent SDK 封装完全没做** | 当前只是空目录 `src/agent-sdk/` | 直接集成 openai-agents-python 作为 Agent SDK 底层，trimum 在其上包装 Tool Gateway 权限层和 Event Bus 通信层 |
| **2** | **无上下文窗口管理** | 长期运行的 Agent 会 token 爆炸 | Pydantic AI Harness 的 Compaction 机制值得复刻 —— 工具输出截断 + 滑动窗口 + 上下文压缩 |
| **3** | **无可观测性** | 没有 token 计数、成本追踪、Agent 行为追溯 | 最低方案：LLM 调用封装中加入 token 计数和结构化日志；远期：引入 OTel |
| **4** | **无 Skills/指令注入** | Agent 缺少动态加载的上下文指令 | SKILL.md 模式（与 OpenClaw 的 skill 思路完全一致），可以直接借鉴 |
| **5** | **凭据脱敏** | 审计日志/工具输出中可能暴露 API key | Tool Gateway 执行前自动扫描命令中的密码/钥匙模式，替换为 `***` |
| **6** | **输入/输出护栏** | 缺乏 Prompt Injection 防护 | Guardrail 模式（Input/Output/Tool 三层） |

### 4.3 保持做自己的部分（不要学 Pydantic AI）

以下方向 trimum 和 Pydantic AI 定位不同，**不需要对齐**：

- **❌ 不做实时语音/图像生成**——trimum 是 AI Runtime，不是通用 AI SDK
- **❌ 不做 Python 独揽的 Agent 定义**——文件化 Agent（.json5 + main.py）是 trimum 的核心创新
- **❌ 不做 30+ provider 支持**——先做好 2-3 个，够用就好
- **❌ 不做 Graph-based workflow**——trimum 的 Event Bus + Listener + DAG 编排是更灵活的方案

---

## 五、建议行动项

| # | 动作 | 优先级 | 关联 TODO |
|---|---|---|---|
| 1 | Agent SDK 封装：集成 openai-agents-python，在其上包装 Tool Gateway 权限层 | 🔴 #3 | 当前空目录，必须优先 |
| 2 | 上下文窗口管理：Tool Output Limits + Compaction | 🔴 新 | 当前无任何上下文控制 |
| 3 | 凭据脱敏：Tool Gateway 执行前扫描 + Policy Engine 集成 | 🟡 | 新 |
| 4 | LLM 调用封装 + Token 计数 + 结构化日志 | 🟡 | 新 |
| 5 | 输入输出 Guardrail 模式 | 🟢 | 远期 |
| 6 | Skills 机制：按需加载 SKILL.md 指令 | 🟢 | 远期 |

---

## 六、结论

**Pydantic AI Harness 是当前 Python Agent SDK 领域的标杆**，其 Coder/Researcher 的 Capability 组合模式非常成熟。但 trimum 和它**不是竞品**：

- Pydantic AI 解决"怎么写 Agent"——是一个库
- trimum 解决"Agent 在操作系统层面怎么管"——是一个守护进程

**战略上**：Phase 3 的 Agent SDK 应该**直接集成 openai-agents-python** 作为底层、在其上包装安全/权限层（Tool Gateway + Security Agent 调用），而不是重写一个 Agent SDK。这是 2026-08-29 决策"集成 openai-agents-python" 承诺做但至今没做的最重要一件事。

**战术上**：可观测性、上下文管理、凭据脱敏这三个差距会在 Phase 3 全链路集成后成为阻塞因素——不解决这些，Agent 就不能真正长期稳定运行。
