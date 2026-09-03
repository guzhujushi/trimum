# trimum — 未完成待办清单

> 最后更新：2026-09-03 18:54
> Phase 3 核心 7 项已全部完成（#1 TARL-SPEC ~ #7 Security TARL）✅
> **Agent SDK 封装已就绪**：TrimumAgent 283 行 + 3 测试通过 ✅
> **上下文窗口管理不单独做**：ContextManager 三重记忆 + FTS5 已覆盖 ✅
> **UI/弹窗弹窗**：归入 Phase 6（桌面深度融合），当前不做 ✅
> **X4 证书体系已落地**：agent_cert.py 官方/自签/无证三档 + 机器指纹 + ConfirmEntry 预留 ✅
> **#3.5 AI/人类流量标签已落地**：SourceType 枚举 + PolicyEngine source 过滤 + TransformAgent origin 标签 ✅
> 审计分析：`docs/REFERENCE-AUDIT.md`（G1-G12）、`docs/PYDANTIC-AI-COMPARISON.md`
> 测试：120 pass 1 fail（已知缓存问题）

---

## 快速定位

| 批次 | 范围 | 优先级 |
|---|---|---|
| **P3-1** | #8 Transform Agent 稳定性 + #8.5 confidence | 🔴 当前最高 |
| **P3-2** | #9-#14 全链路集成 + Agent 体系收尾 | 🟡 立即 |
| **P3-3** | #3.3/G4 凭据脱敏 · #3.4/G3 cwd Jail · #3.5/G5 流量标签 · #3.6/G8 JIT 授权 · #3.7/G6 资源配额 · #3.8/G7 审计日志 · #3.9/G9 流式输出 | 🟡 安全体系 |
| **P3.5** | X1 Skill 层 · X2 ExperienceLearner · X4 证书体系 | 🟡 Phase 3 收尾 |
| **P4+** | Landlock/Seccomp/Docker 沙箱 · Guardrail · X3 自优化 · CLI 流式 | 🟢 远期 |

---

## 🔴 P3-1（当前最高优）

### #8 Transform Agent 稳定性测试
> Transform Agent 当前仅有骨架 stub（tarl_parser 12 测试通过）

- 验证 tarl_parser + transform_agent 在不同 NL 输入下的 TARL 生成正确率
- 边界 case：特殊符号（中日韩文混排）、空输入、超长输入、多意图输入
- 产出：一份正确率报告 + 修复方案

### #8.5 Transform Agent confidence 字段（DeepSeek 建议 ✅ 采纳）
- TARL intent 块增加 `confidence:` 字段（浮点数 0~1）
- 低于阈值（如 `< 0.7`）时触发澄清流程而非直接执行
- 与 #8 一起做

---

## 🟡 P3-2（Agent 体系 + 全链路集成）

### #9 Security Agent ↔ Agent Router / Tool Gateway 全链路集成
- 将 security_agent.can_execute() / can_access() 挂到 ToolGateway 实际调用路径上
- 当前：SecurityAgent 类已实现但未被 Agent Router 和 Tool Gateway 调用
- 验收：Agent 调用工具时会经过安全检查，拒绝的调用返回明确错误

### #11 Policy Engine 升级：正则 → 混合（LLM + 规则）
- 当前：PolicyEngine 是纯正则规则匹配
- 目标：Security Agent 能调用 LLM 辅助评估运行时行为
- 注意：可选，不应引入不必要的 LLM 调用

### #12 Router/Planner 概念明确
- 当前 AgentRouter 包含 route() 和 plan_with_llm()，但 Plan→Dispatch 两步边界模糊
- 需要明确：Router 负责按能力匹配 Agent，Planner 负责 LLM 兜底规划

### #13 弹性沙箱 — AI 辅助策略评估 + 行为追踪
- BehaviorMonitor 已有基础框架（滑动窗口、分类、异常检测）
- 扩展：新操作类型学习的反馈闭环

### #14 Landlock 预设兜底（Phase 4 预备）
- 预留接口已放 policy_engine.py / security_agent.py 中
- 待 Arch Linux 真机验证时实现

### #14.5 TRM 错误码体系（DeepSeek 建议 ✅ 采纳）
- 新建 `docs/ERROR-CODE-SPEC.md`，定义三段式错误码
  - TRM-1xxx Runtime / 2xxx Security / 3xxx Agent / 4xxx Tool
- `models.py` 增加 `TrimumError(Exception)` + 错误码协议
- 参见 `docs/DEEPSEEK-ADVICE-REVIEW.md`

### #14.6 Policy Engine 学习模式（DeepSeek 建议 ✅ 采纳）
- Behavior Monitor 已有操作历史追踪和异常检测
- 延伸：观察用户行为模式 → 动态生成 Policy Engine 的 allow ruleset
- 新人严格模式、老司机自动化模式
- 与 #13 弹性沙箱 AI 辅助策略评估整合
- 参见 `docs/DEEPSEEK-ADVICE-REVIEW.md`

---

## 🟡 P3-3（安全体系 — 来自参考项目审计）

> 完整审计见 `docs/REFERENCE-AUDIT.md`（G1-G12）

### #3.3 / G4 凭据脱敏（Secrets Redaction）
- Tool Gateway 执行前扫描命令中的 API key/token/密码模式
- Policy Engine 中增加 secrets_patterns 配置
- 审计日志写入前脱敏
- **来源**：hardened-terminal-mcp 实践

### #3.4 / G3 cwd Jail 工作目录隔离
- Tool Gateway 为每个工具分配 `work_dir` 字段
- ProcessDispatcher / ShellDispatcher 执行前验证路径合法性
- 拒绝 cd 到 `work_dir` 之外的路径
- **来源**：hardened-terminal-mcp 实践

### #3.5 / G5 AI/人类流量区分标签 ✅
> 2026-09-03 已落地 — 120 pass
- SourceType 枚举加到 models.py（human/ai/workflow/system/unknown）
- ExecuteRequest 和 SystemEvent 增加了 `source_type` 字段
- PolicyEngine.evaluate() 支持 `source` 过滤规则（YAML 规则中增加 `source:` 字段）
  - 未指定 source 的规则是全局规则，优先匹配
  - 指定 source 的规则只有当 source_type 匹配时才触发
- Transform Agent 输出自动加 `origin:ai` 标签到 TARL
- ToolGateway 将 request.source_type 传递到 PolicyEngine
- 测试 7 个覆盖：不同 source 下 rm/ls 的不同策略

### #3.6 / G8 JIT 一次性授权模式
- SecurityAgent 增加 `allow_once` 参数
- 授权后加入 expire 机制（运行一次后自动撤销）
- **来源**：eshu-gateway JIT approval

### #3.7 / G6 子 Agent 资源配额
- Agent Runtime 的 spawn 参数增加 CPU/mem/IO 配额
- 使用 psutil 实时监控超限行为
- 超限时通过 Event Bus 发布 `security.alert`
- **来源**：agent-code-sandbox 沙箱实现

### #3.8 / G7 结构化审计日志
- Policy Engine 每次决策输出 JSON 格式审计事件到 Event Bus
- 审计事件包含：时间/Agent/工具/决策/规则名/duration
- 订阅 `security.alert` / `tool.denied` 事件持久化到审计文件
- **来源**：agent-code-sandbox 审计轨迹设计

### #3.9 / G9 流式 CLI 输出
> **经验优化**，不影响功能完整性
- trimum CLI (`trm`) 增加流式输出模式（typer + rich）
- **来源**：shell_gpt 的流式终端体验

---

## 🟢 低优（体验 + 维护）

### #15 真机 Arch Linux 验证 trmd 启动
- 还没在 Arch Linux 上跑过完整的守护进程
- 需要验证：Unix Socket IPC、Systemd 服务单元、Hyprland 集成

### #16 Codex 结果审查与遗留清理
- `D:\trimum\tmp\` 下有遗留 prompt 文件等，或可清理
- Codex review SIGKILL（90s 超时）待重试

### #17 SonarQube 重扫
- 确认 181 issues 无回归

### #18 `json5` 依赖加入 pyproject.toml
- 当前 AgentRegistry 已支持 JSON5 解析，但依赖未声明

### #19 Workflow 文件化加载 ✅
> 2026-09-04 已落地 — 14 测试通过
- WorkflowDefV2.load_yaml(path) — 从 YAML 加载
- WorkflowDefV2.load_from_dir(dir) — 扫描目录（支持 .yaml / .yml）
- 目录结构：`~/.trimum/workflows/<name>/workflow.yaml`
- 已创建两个示例：blog-deploy（3步部署）和 daily-check（系统巡检）
- 文件化体系完整：Agent / Tool / Certs / Workflow 四层全部可 `ls` 发现

### #20 记忆文件（前两级）放到 Agent 文件夹
- 当前记忆全在 `~/.trimum/memory/` 的全局 namespace 下
- 需要：每个 Agent 文件夹自带 `memory/` 子目录
  - `~/.trimum/agents/<name>/memory/agent.db` — Agent 私有记忆（前两级）
  - `~/.trimum/agents/<name>/memory/experience.db` — 经验教训
- 项目共享放到 `~/.trimum/memory/projects/<id>.db`
- 全局放到 `~/.trimum/memory/global.db`

### #21 Certs 移到 Agent 文件夹
- 当前：certs 在 `~/.trimum/certs/` 根下
- 需要：每个 Agent 文件夹自带证书
  - `~/.trimum/agents/<name>/cert.json` — 该 Agent 的证书
  - 同时在 `~/.trimum/certs/` 保留索引作为快捷发现
- 这样 Agent 目录 cp 即走：复制 Agent 文件夹就等于复制了它的证书+记忆+代码

---

## 🆕 Phase 3.5 — 四想法（2026-09-03 凌晨脑暴）

> 完整分析见 OpenClaw 工作区 `memory/2026-09-03.md`

### X1 Skill 层 — 🟡 中优
轻量 YAML 能力包，Agent 声明 `skill:xxx` 即用。

文件：
- `src/trimum_core/skill_loader.py` — 加载 skill.yaml
- `src/trimum_core/skill_executor.py` — 按步骤执行
- `~/.trimum/skills/<name>/skill.yaml + SKILL.md`

验收：skill.yaml 可加载；Agent 通过 capability 调用；至少一个 demo skill 能跑通。

### X2 ExperienceLearner — 🟡 中优
Event Bus 失败事件 → LLM 分析 → 写入 Agent memory/experience.db。

文件：
- `src/trimum_core/experience_learner.py`

验收：监听 `*.failed` 事件；调用 LLM 分析原因；不消耗 token（只在失败时触发）。

### X3 Agent 自优化 — 🟢 低优
Agent 可优化自己的 prompt/示例/工具策略，但不可改权限/安全边界。

需人工确认：改进建议写入 `memory/pending-improvements.json`，`trm agent improve/apply` 命令管理。

### X4 证书体系 — 🟡 中优 ✅
> 2026-09-03 已落地 — 15 测试通过
- agent_cert.py 完整模块：CertificateType / CertTrustLevel / AgentCert 类
- 官方证书 → TRUSTED（拷入 `certs/official/` 即用，跨机信任）
- 自签证书 → 同机 TRUSTED（绑定 machine_id），跨机 CONFIRM（允许用户决定）
- 无证 → CONFIRM（弹确认入口，Phase 6 接入 UI）
- ConfirmEntry 预留确认接口（当前 stub 返回 True，供 Phase 6 替换）
- 集成 AgentRegistry.register() — reg 时自动校验证书，无证弹出确认
- 测试 15 个覆盖：创建/序列化/加载/验证/同机/跨机/确认/目录

---

## ✅ 已完成（Phase 3 核心）

### #1 TARL-SPEC + FTS5 适配 ✅
- `docs/TARL-SPEC.md` — KV 行格式规范
- 解析器接口定义

### #2 tarl_parser.py ✅
- KV 行 parser + Serializer
- 12 测试通过

### #3 Agent SDK 封装 ~ TrimumAgent ✅
> 2026-09-02 commit `31fe736` — 283 行 Python
- `src/agent-sdk/src/agent_sdk/trimum_agent.py`
- 包装 openai-agents-python 作为底层
- Tool Gateway 安全工具检查 + auto_confirm
- `run()` / `run_sync()` / `execute_tool()`
- 装饰器 `@tool` / `@tool_plain`
- 3 测试通过（init/repr/run_sync_basic）

### #3.1 上下文窗口管理 ✅
> 由 ContextManager 三重记忆 + FTS5 全文检索覆盖，不单独实现
- ContextManager 24 方法：set/get/search/delete/list_namespace
- Agent 私有 → `agent_memory` namespace
- 项目共享 → `project_ctx` namespace
- 全局 → `global_ctx` namespace
- FTS5 统一索引（`context_fts.db`）
- 记忆搜索默认返回 Top-N 条，避免 Token 爆炸

### #3.2 可观测性基座 ✅
> 非独立模块——CLI/桌面深度集成留待 Phase 6

### #4 Handoff Snapshot（Warp 借鉴）✅
- TARL snapshot: 元信息传递上下文
- Minimum Context Principle

### #5 Warp Run State → Task State Machine ✅
- 10 态：CREATED / QUEUED / DISPATCHING / RUNNING / COMPLETED / FAILED / TIMEOUT / CANCELLED / BLOCKED / ARCHIVED

### #6 Workflow Engine TARL 匹配 ✅
- KV 前缀索引匹配 workflow
- 匹配失败 → transform agent → 直接执行 → Planner 兜底

### #7 Security Agent TARL 接入 ✅
- cmd: 前缀映射策略规则
- TARL 格式与 Policy Engine 集成

### 弹窗 UI / API 入口 ✅
> 归入 Phase 6 一键安装（桌面深度融合），当前不实现

### Pydantic AI Harness 对比调研 ✅
- `docs/PYDANTIC-AI-COMPARISON.md` — 6 项关键差距识别
- `docs/REFERENCE-AUDIT.md` — G1-G12 差距审计
- 决策：直接集成 openai-agents-python（已落地 #3）

---

## 📋 DeepSeek 建议审核状态

> 完整分析见 `docs/DEEPSEEK-ADVICE-REVIEW.md`

| 建议 | 结论 | 状态 |
|---|---|---|
| Transform Agent confidence 字段 | ✅ 采纳 | #8.5 待做 |
| TRM 错误码体系 | ✅ 采纳 | #14.5 待做 |
| Policy Engine 学习模式 | ✅ 采纳 | #14.6 待做 |
| Event Bus 虚拟文件接口 | ⚠️ 远期采纳 | ARCHITECTURE.md 注释 |
| Memory 渐进方案 SQLite→sqlite-vec | ⚠️ 知识记录 | ARCHITECTURE.md 注释 |
| usearch | ❌ 不采纳 | 当前量级不匹配 |
| Agent Marketplace | ❌ 不采纳 | 已确认太早 |

---

## Phase 路线图

```
Phase 3 ── Agent SDK + 安全体系（收尾中）
  P3-1   #8 Transform Agent 稳定性 ──── 🔴 当前最高
  P3-2   #9-#14 全链路集成 ─────────── 🟡
  P3-3   #3.3~#3.9 安全审计项 ─────── 🟡
  P3.5   X1 Skill / X2 Experience / X4 证书 ── 🟡

Phase 4 ── Security Runtime（Landlock / Seccomp / Namespace）
  ├── SandboxProvider 抽象
  ├── Per-step 权限声明
  ├── 控制流操作符 parallel/forEach/branch/loop
  └── Hash-chain 审计日志 + 持久化 KV Store

Phase 5 ── Memory Layer（chroma 向量库扩展）
  ├── 三重记忆 + FTS5 ✅ 已存在
  └── Guardrail 模式（输入/输出护栏）

Phase 6 ── 桌面融合 + 一键安装
  ├── Tray 弹窗 UI ↔ SecurityAgent.confirm()
  ├── CLI 流式输出（rich/typer）
  ├── Plugin Marketplace
  ├── ISO / 一键安装脚本
  └── 语言演进（PyO3 / TS / Rust 重写可选）

Phase 7+ ── 长期
  └── Agentic Wiki、多通道、Agent 自优化 X3
```
