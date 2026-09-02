# trimum — 未完成待办清单

> 最后更新：2026-09-02
> Phase 3 高优 7 项已全部完成（#1 TARL-SPEC ~ #7 Security TARL）。**Pydantic AI Harness 对比调研完成**（`docs/PYDANTIC-AI-COMPARISON.md`），识别 6 项关键差距。

---

## 🔴 Phase 3 高优剩余（新评估：Agent SDK 是第一优先）

### #3 (reprioritized) Agent SDK 封装 — 集成 openai-agents-python
> **原 #3 — 从下一步的第 3 位升至第 1 位**
> **当前状态**：`src/agent-sdk/` 是**空目录**，没有任何代码。这是 Phase 3 最大的未完成项。

- 底层：直接集成 openai-agents-python 作为 Agent SDK
- 上层：包装 Tool Gateway 权限层 + Security Agent 安全检查
- 通信层：通过 Event Bus 发布 Agent 生命周期事件
- 参考：Pydantic AI Harness 的 SubAgents 设计（`docs/PYDANTIC-AI-COMPARISON.md` §2.2）
- **不重写 wheel**——trimum 的价值在 Runtime/沙箱，不是再造一个 Agent SDK

### #3.1 上下文窗口管理
> **新发现的高优项（Pydantic AI Harness 对比启发）**
> 当前无任何上下文控制，长期运行 Agent 必然 token 爆炸

- 工具输出限制（Tool Output Limits）：巨大返回截断/外溢到文件
- 滑动窗口 Context 压缩
- 上下文使用警告（Warn Near Limits）
- 参见 `docs/PYDANTIC-AI-COMPARISON.md` §4.2 #2

### #3.2 可观测性基座
> **新发现的高优项**

- LLM 调用封装加入 token 计数 + 成本追踪
- 结构化日志（管道到 disk/Event Bus）
- 最低可行方案：在 LLM adapter 层加入 usage 统计

### #3.3 凭据脱敏（Secrets Redaction）
> **新发现的中优项**

- Tool Gateway 执行前扫描命令中的 API key/token/密码模式
- Policy Engine 中增加 secrets_patterns 配置
- 审计日志写入前脱敏

### #3.4 cwd Jail 工作目录隔离（REFERENCE-PROJECTS 审计发现）
> **来源**：hardened-terminal-mcp 的 cwd jail 实践
> **严重度**：🟡 中 — 没有这个，Agent 可以 cd 到系统任意路径操作

- Tool Gateway 为每个工具分配 `work_dir` 字段
- ProcessDispatcher/ShellDispatcher 执行前验证路径合法性
- 拒绝 cd 到 `work_dir` 之外的路径
- 参见 `docs/REFERENCE-AUDIT.md` §G3

### #3.5 AI/人类流量区分标签（REFERENCE-PROJECTS 审计发现）
> **来源**：shellfirm 的 AI Agent 识别能力
> **严重度**：🟡 中 — 没有标签，日志里分不清谁发的命令

- Transform Agent 输出增加 `origin:` 标签（ai/human/workflow）
- Event Bus 事件携带 `source_type` 字段
- Policy Engine 可根据 origin 选择不同策略（如 ai origin 永远不能执行 rm）
- 参见 `docs/REFERENCE-AUDIT.md` §G5

### #3.6 JIT 一次性授权模式（REFERENCE-PROJECTS 审计发现）
> **来源**：eshu-gateway 的 Just-In-Time approval
> **严重度**：🟡 中 — 当前只有永久 allow/block，缺少"本次通过、下次不通过"的一次性规则

- SecurityAgent 增加 `allow_once` 参数
- 授权后加入 expire 机制（运行一次后自动撤销）
- 参见 `docs/REFERENCE-AUDIT.md` §G8

### #3.7 子 Agent 资源配额（REFERENCE-PROJECTS 审计发现）
> **来源**：agent-code-sandbox 的沙箱实现
> **严重度**：🟢 低 — 非立即阻塞

- Agent Runtime 的 spawn 参数增加 CPU/mem/IO 配额
- 使用 psutil 实时监控超限行为
- 超限时通过 Event Bus 发布 `security.alert`
- 参见 `docs/REFERENCE-AUDIT.md` §G6

### #3.8 结构化审计日志（REFERENCE-PROJECTS 审计发现）
> **来源**：agent-code-sandbox 的审计轨迹设计
> **严重度**：🟢 低 — 非立即阻塞

- Policy Engine 每次决策输出 JSON 格式审计事件到 Event Bus
- 审计事件包含：时间/Agent/工具/决策/规则名/duration
- 订阅 `security.alert` / `tool.denied` 事件持久化到审计文件
- 参见 `docs/REFERENCE-AUDIT.md` §G7

### #3.9 流式 CLI 输出（REFERENCE-PROJECTS 审计发现）
> **来源**：shell_gpt 的流式终端体验
> **严重度**：🟢 低 — 体验优化

- trimum CLI (`trm`) 增加流式输出模式（typer + rich）
- 参见 `docs/REFERENCE-AUDIT.md` §G9

### #8 Transform Agent 输出稳定性测试
- 验证 tarl_parser + transform_agent 在不同 NL 输入下的 TARL 生成正确率
- 当前：tarl_parser 有 12 个测试通过，transform_agent 仅有骨架 stub
- 产出：一份正确率报告 + 边界 case 的修复

### #8.5 Transform Agent confidence 字段（来自 DeepSeek 建议）
- TARL intent 块增加 `confidence:` 字段（浮点数 0~1）
- 低于阈值（如 `< 0.7`）时触发澄清流程而非直接执行
- 参见 `docs/DEEPSEEK-ADVICE-REVIEW.md`
- 优先级：#8.5 建议与 #8 一起做（同属 transform_agent 改造）

---

## 🟡 Phase 3 中优（Agent 体系 + 集成）

### 9. Security Agent ↔ Agent Router / Tool Gateway 全链路集成
- 将 security_agent.can_execute() / can_access() 挂到 ToolGateway 实际调用路径上
- 当前：SecurityAgent 类已实现但未被 Agent Router 和 Tool Gateway 调用
- 验收：Agent 调用工具时会经过安全检查，拒绝的调用返回明确错误

### 10. 弹窗确认的 UI / API 入口
- SecurityAgent.confirm() 需要实际用户确认界面
- 当前：方法已定义但无确认实际交付给用户的通道
- 方案：CLI stdin 输入 / API endpoint / 桌面通知 + 输入
- 参考：**fast-agent** 的 `Agent.request_input()` 设计（Agent 可请求人工输入获取额外上下文），以及 `eshu-gateway` 的 JIT approval 模式

### 11. Policy Engine 升级：正则 → 混合（LLM + 规则）
- 当前：PolicyEngine 是纯正则规则匹配
- 目标：Security Agent 能调用 LLM 辅助评估运行时行为
- 注意：可选，不应引入不必要的 LLM 调用

### 12. Router/Planner 概念明确
- 当前 AgentRouter 包含 route() 和 plan_with_llm()，但 Plan→Dispatch 两步边界模糊
- 需要明确：Router 负责按能力匹配 Agent，Planner 负责 LLM 兜底规划

### 13. 弹性沙箱 — AI 辅助策略评估 + 行为追踪
- BehaviorMonitor 已有基础框架（滑动窗口、分类、异常检测）
- 扩展：新操作类型学习的反馈闭环

### 14. Landlock 预设兜底（Phase 4 预备）
- 预留接口已放 policy_engine.py / security_agent.py
- 待 Arch Linux 真机验证时实现

### 14.5 TRM 错误码体系（来自 DeepSeek 建议）
- 新建 `docs/ERROR-CODE-SPEC.md`，定义三段式错误码
  - TRM-1xxx Runtime / 2xxx Security / 3xxx Agent / 4xxx Tool
- `models.py` 增加 `TrimumError(Exception)` + 错误码协议
- 参见 `docs/DEEPSEEK-ADVICE-REVIEW.md`

### 14.6 Policy Engine 学习模式（来自 DeepSeek 建议）
- Behavior Monitor 已有操作历史追踪和异常检测
- 延伸：观察用户行为模式 → 动态生成 Policy Engine 的 allow ruleset
- 新人严格模式、老司机自动化模式
- 与 #12 弹性沙箱 AI 辅助策略评估整合
- 参见 `docs/DEEPSEEK-ADVICE-REVIEW.md`

---

## 🟢 低优（体验 + 维护）

### 15. 真机 Arch Linux 验证 trmd 启动
- 还没在 Arch Linux 上跑过完整的守护进程
- 需要验证：Unix Socket IPC、Systemd 服务单元、Hyprland 集成

### 16. Codex 结果审查与遗留合并
- `D:\trimum\tmp\` 下有遗留的 prompt 文件等，或可清理
- Codex review SIGKILL（90s 超时）待重试

### 17. SonarQube 重扫
- 确认 181 issues 无回归

### 18. `json5` 依赖加入 pyproject.toml
- 当前 AgentRegistry 已支持 JSON5 解析，但依赖未声明

---

## 📋 DeepSeek 建议审核

> 完整分析见 `docs/DEEPSEEK-ADVICE-REVIEW.md`（2026-09-02）

| 建议 | 结论 | 入文件 |
|---|---|---|
| Transform Agent confidence 字段 | ✅ 采纳 | #8.5，与 #8 一起做 |
| TRM 错误码体系 | ✅ 采纳 | #14.5，低优 |
| Policy Engine 学习模式 | ✅ 采纳 | #14.6，与弹性沙箱集成整合 |
| Event Bus 虚拟文件接口 | ⚠️ 远期采纳 | ARCHITECTURE.md 注释 |
| Memory 渐进方案 SQLite→sqlite-vec | ⚠️ 知识记录 | ARCHITECTURE.md 注释 |
| usearch | ❌ 不采纳 | 当前量级不匹配 |
| Agent Marketplace | ❌ 不采纳 | 已确认太早 |

---

## 🔵 参考项目 & 值得了解的同类项目

### ✅ 高度相关（建议了解）

| 项目 | ★ | 语言 | 定位 | 值得 trimum 关注的点 |
|---|---|---|---|---|
| **fast-agent** (evalstate/fast-agent) | 3,906 | Python | Agent 构建/评估/Workflow 平台 | MCP 原生（含 Sampling/Elicitations）、Agent 可请求人工输入、Skills (SKILL.md) 文件化、CLI-first、ACP 互操作、`@fast.chain()` 链式 Agent |
| **nanobot** (HKUDS/nanobot) | 47,519 | Python | 超轻量个人 AI Agent 框架 | 已在 REFERENCE-PROJECTS.md 中，47K★ 说明路是对的：Python + 轻量 + 自托管 + 桌面优先 |

**fast-agent 可借鉴的具体点**：
1. **Agent 文件化（SKILL.md + AgentCard）** — fast-agent 用声明式 `@fast.agent()` + YAML 配置 + SKILL.md 定义 Agent，与 trimum 的 `agent.json5` 思路一致，可参考它的一等公民设计
2. **MCP Sampling / Elicitations 支持** — fast-agent 自称首个完全端到端支持 MCP Sampling 的框架，trimum 后续 MCP 集成时可参考
3. **`agent.request_input()` 模式** — Agent 可在运行时请求用户输入获取额外上下文，不同于 SecurityAgent.confirm() 的拒绝或确认，这是**正向获取**上下文。trimum 的 Handoff Snapshot + 弹窗确认可以借鉴此模式
4. **ACP 互操作性** — `fast-agent-acp` 可作为子进程嵌入任何 ACP 客户端，trimum 的 Agent Socket 架构可以参考这种"Agent 作为协议端点"的设计

### ⭐⭐ 概念相关（值得浏览）

| 项目 | ★ | 语言 | 定位 | 看点 |
|---|---|---|---|---|
| **Sulala Agent OS** (sulala-labs/sulala) | 2 | TS | 轻量协作微 Agent 平台 ~1MB | 概念最契合 trimum 的"micro-agent"方向。1MB 极轻，TS 但设计理念可参考 |
| **MollyPaw** (MollyPaw/MollyPaw) | 3 | Python | 轻量桌面 AI 客户端 | Python 桌面 Agent 客户端，trimum 桌面集成方向同类 |
| **AgentDock** (AgentDock/AgentDock) | 1,707 | MDX | "Build Anything with AI Agents" | 热度高，但仓库内容似乎是文档/landing page。如果包含有用架构值得看看 |

### ⭐ 可浏览（不优先）

| 项目 | ★ | 语言 | 定位 |
|---|---|---|---|
| **aaspai** (mufeedvh/aaspai) | 2 | TS | Agent CLI 控制面 |
| **PengyAgent** (neuralspaz/PengyAgent) | 1 | Rust | Rust 一站式 Agent |

### ❌ 排除（名字撞车 / not found / 不相关）

- **Vercel Eve** — 可能 closed source 或确实不存在公开仓库
- **deepseek Harness** — `deepseek-ai/Harness` 不存在
- **0xagent** — 红队 CobaltStrike 工具，名字撞车
- **PetalFlow** — 纯 C ML 库，名字撞车

### 📋 已覆盖在 REFERENCE-PROJECTS.md 中、不再重复列出的
- shell_gpt、LocalGhost、shellfirm、hardened-terminal-mcp、OpenAI Agents SDK、chroma、apprise、Supervisor 等 50+ 项目已覆盖

---

## Phase 路线图一览

```
Phase 3 ── 弹性沙箱体系 ✅（高优已完成 #1-#7）
           ├── ✅ TARL-SPEC + tarl_parser + transform_agent
           ├── ✅ Handoff Snapshot（Warp 借鉴）
           ├── ✅ Task State Machine（10 态）
           ├── ✅ Workflow Engine TARL 匹配
           ├── ✅ Security Agent TARL 接入
           └── 🔴 待办：#8 稳定性测试、#9-#14 集成工作

Phase 4 ── Security Runtime（Landlock / Seccomp / Namespace）
           ├── SandboxProvider 抽象（参考 Sandcastle ⭐⭐⭐）
           ├── Per-step 权限声明（参考 skelm ⭐⭐⭐⭐⭐）
           ├── 控制流操作符 parallel/forEach/branch/loop（参考 skelm ⭐⭐⭐⭐⭐）
           └── Hash-chain 审计日志 + 持久化 KV Store（参考 skelm ⭐⭐⭐⭐⭐）

Phase 5 ── Memory Layer（chroma 向量库 + 知识图谱）
           ├── 三重记忆 + FTS5 全文检索已存在 ✅
           └── 扩展向量检索层

Phase 6 ── ISO / 一键安装镜像
           ├── Plugin Marketplace（参考 SemaClaw ⭐⭐⭐⭐）
           ├── Agentic Wiki（参考 SemaClaw ⭐⭐⭐⭐）
           └── 语言演进（Python → PyO3 → TS/Rust 重写可选，见 ECOSYSTEM-COMPARISON.md §五）
```
