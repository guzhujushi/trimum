# trimum — 未完成待办清单

> 最后更新：2026-09-04 22:19
> Phase 3 核心 7 项已全部完成（#1 TARL-SPEC ~ #7 Security TARL）✅
> **Agent SDK 封装已就绪**：TrimumAgent 283 行 + 3 测试通过 ✅
> **上下文窗口管理不单独做**：ContextManager 三重记忆 + FTS5 已覆盖 ✅
> **UI/弹窗**：归入 Phase 6（桌面深度融合），当前不做 ✅
> **X4 证书体系已落地**：agent_cert.py 官方/自签/无证三档 + 机器指纹 + ConfirmEntry 预留 ✅
> **#3.3 凭据脱敏**：_redact_credentials() 完整实现 + execute() 末尾调用 ✅
> **#3.4 cwd Jail 工作目录隔离**：_check_cwd_jail() 完整实现 + Layer 0 调用 ✅
> **#3.5 AI/人类流量标签**：SourceType 枚举 + PolicyEngine source 过滤 + TransformAgent origin 标签 ✅
> **#3.6 JIT 一次性授权**：_check_jit_auth() + issue_jit_token() + grant_jit_token() 完整实现 + Layer 3 调用 ✅
> **#8 Transform Agent**：274 行实质代码（LLM 调用/ _parse_llm_output / confidence / TransformResult）✅
> **#8.5 confidence**：TransformResult 含 confidence + is_certain/needs_confirmation/needs_planner 属性 ✅
> **#12 Router/Planner**：AgentRouter 已删除，AgentRegistry 承载 ✅
> **#19 Workflow 文件化加载**：load_yaml / load_from_dir + 2 示例 workflow ✅
> **#20 记忆文件放到 Agent 文件夹**：ContextManager db_path->db_dir + 全局 CRUD + FTS5 ✅
> **#21 Certs 移到 Agent 文件夹**：Agent 文件夹 cert.json 优先级 + cp 即走 ✅
> **#22 Agent depends_on 依赖声明**：models.py 字段 + check_dependencies() + 12 测试 ✅
> **security_agent_agenda.md**：8050 字节，5 大威胁域 + 30+ 攻击手法 + 三层决策 ✅
> **SECURITY-DEFENSE-PLAN.md**：825 行 / 36KB，12 章完整防御方案 ✅
> 测试：202 pass ✅（含 transform_agent 32 测试 + tarl_parser 12 测试 + workflow_files 14 测试 + depends_on 12 测试）

---

## 快速定位

| 批次 | 范围 | 优先级 |
|---|---|---|
| P3-2 | #9-#14 全链路集成 | 🟡 立即 |
| P3-3 | #3.7/#3.8/#3.9 安全剩余 | 🟡 安全体系 |
| P3.5 | X1 Skill / X2 Experience | 🟡 Phase 3 收尾 |
| P3-new | #30-#34 Security Agent 接入 | 🟡 新任务 |
| P4+ | Landlock/Seccomp/Docker/Guardrail/X3/CLI | 🟢 远期 |

---

## 🟡 P3-2（Agent 体系 + 全链路集成）

### #9 Security Agent ↔ Tool Gateway 全链路集成
- 将 SecurityRule.can_execute() / can_access() 挂到 ToolGateway.execute() 路径
- 当前：SecurityRule 已被 import、tool_gateway.py 有 self.security_rule 但 execute() 从未调用
- 验收：Agent 调用工具时经过 SecurityRule 检查，拒绝返回明确错误

### #11 Policy Engine 升级：正则 → 混合（LLM + 规则）
- 当前：PolicyEngine 是纯正则规则匹配
- 目标：Security Rule 能调用 LLM 辅助评估运行时行为
- 注意：智能模式（仅 L1 未命中 + L2 可疑时触发）

### #13 弹性沙箱 — AI 辅助策略评估 + 行为追踪
- BehaviorMonitor 已有基础框架（滑动窗口、分类、异常检测）
- 扩展：新操作类型学习的反馈闭环

### #14 Landlock 预设兜底（Phase 4 预备）
- 预留接口已放 policy_engine.py / security_rule.py 中
- 待 Arch Linux 真机验证时实现

### #14.5 TRM 错误码体系（DeepSeek 建议 ✅ 采纳）
- 新建 docs/ERROR-CODE-SPEC.md，三段式错误码：TRM-1xxx Runtime / 2xxx Security / 3xxx Agent / 4xxx Tool
- models.py 增加 TrimumError(Exception) + 错误码协议

---

## 🟡 P3-3（安全体系剩余）

### #3.7 / G6 子 Agent 资源配额
- Agent Runtime spawn 参数增加 CPU/mem/IO 配额
- 使用 psutil 实时监控超限
- 超限时 Event Bus 发布 security.alert

### #3.8 / G7 结构化审计日志
- Policy Engine 每次决策输出 JSON 格式审计事件到 Event Bus
- 审计事件：时间/Agent/工具/决策/规则名/duration
- 订阅 security.alert / tool.denied 持久化到审计文件

### #3.9 / G9 流式 CLI 输出
- trimum CLI (trm) 增加流式输出模式（typer + rich）

---

## 🆕 P3-new — Security Agent 接入 + 监听器/执行器

### #30 SecurityRule 挂到 ToolGateway.execute()（Layer 4）
- ToolGateway.execute() 增加 Layer 4：执行前调用 self.security_rule.can_execute()
- 接入 BehaviorMonitor 频率检测 + 操作序列检测
- 接入 PolicyEngine.check_landlock() 接口
- 验证：ToolGateway -> PolicyEngine -> BehaviorMonitor -> SecurityRule 全链路

### #31 新建 sec_monitor.py — ThreatMatcher 威胁匹配引擎
- 实现 SECURITY-DEFENSE-PLAN.md 第二、三章设计的威胁匹配
- 输入：(agent_id, command, context) -> 输出：(threat_name, defense_actions)
- 上下文追踪：DOWNLOAD_THEN_EXEC / WRITE_THEN_EXEC / SUID_STORM 等
- 对接 Event Bus 订阅 agent.executing 事件

### #32 新建 sec_executor.py — SecBlocker/SecAudit/SecNotif
- SecBlocker：DENY 命令 / SIGSTOP 冻结 / SIGKILL 杀进程 / 网络隔离
- SecAudit：JSON 格式审计事件持久化
- SecNotif：Event Bus 发布 security.alert / security.blocked

### #33 新建内置安全工作流（threat-*）
- 每个威胁带一个应对工作流（YAML）
- 优先级：threat-prelink-check, threat-ebpf-scan, threat-ransomware-response
- 自动 Event Bus 触发，无 LLM 参与

### #34 内置监听器注册机制
- suspend/block 事件到 Event Bus 批量处理
- 通知 WorkflowListener 触发对应工作流

---

## 🆕 Phase 3.5 — 四想法

### X1 Skill 层 — 🟡 中优
轻量 YAML 能力包，Agent 声明 skill:xxx 即用。
- src/trimum_core/skill_loader.py + skill_executor.py
- ~/.trimum/skills/<name>/skill.yaml + SKILL.md
- 验收：yaml 可加载；capability 调用；至少一个 demo 能跑

### X2 ExperienceLearner — 🟡 中优
Event Bus 失败事件 -> LLM 分析 -> 写入 Agent memory/experience.db
- src/trimum_core/experience_learner.py
- 监听 *.failed 事件；仅在失败时触发 LLM

### X3 Agent 自优化 — 🟢 低优
Agent 可优化自己的 prompt/示例/工具策略（不可改权限/安全边界）
- 改进建议写入 memory/pending-improvements.json
- trm agent improve/apply 命令管理

---

## 🟢 低优（体验 + 维护）

### #15 真机 Arch Linux 验证 trmd 启动
- Unix Socket IPC、Systemd 服务单元、Hyprland 集成

### #16 Codex 结果审查与遗留清理
- D:\trimum\tmp\ 遗留文件清理

### #17 SonarQube 重扫
- 确认 181 issues 无回归

### #18 json5 依赖加入 pyproject.toml

---

## ✅ 已完成知识

### P3-1 Transform Agent ✅
- transform_agent.py: 274 行, LLM 调用 + _parse_llm_output + confidence + TransformResult
- tarl_parser.py: 246 行, KV 行 parser + Serializer
- 测试: 32 (含 CallLlm 限流/超时/500 + EdgeCases)

### P3-3 安全体系 ✅
- #3.3 凭据脱敏: _redact_credentials() 正则脱敏 output + error
- #3.4 cwd Jail: _check_cwd_jail() 路径白名单 + work_dir 解析
- #3.5 AI/人类流量标签: SourceType + PolicyEngine source 过滤 + 7 测试
- #3.6 JIT 授权: _check_jit_auth + issue_jit_token + grant_jit_token + expire
- #3.8 审计日志: _record_audit() JSON 到 logger + AuditEvent

### P3.5 ✅
- X4 证书体系: agent_cert.py 官方/自签/无证 + 机器指纹
- #22 depends_on: check_dependencies() + 12 测试

### 文档 ✅
- docs/SECURITY-DEFENSE-PLAN.md: 825 行 / 36KB, 12 章节
- src/trimum_core/security_agent_agenda.md: 8050 字节

---

## 📋 DeepSeek 建议审核状态

| 建议 | 结论 | 状态 |
|---|---|---|
| Transform Agent confidence 字段 | ✅ 采纳 | 已完成 |
| TRM 错误码体系 | ✅ 采纳 | #14.5 待做 |
| Policy Engine 学习模式 | ✅ 采纳 | #13 延续 |
| Event Bus 虚拟文件接口 | ⚠️ 远期 | ARCHITECTURE.md |
| Memory SQLite->sqlite-vec | ⚠️ 知识记录 | ARCHITECTURE.md |
| usearch | ❌ 不采纳 | 量级不匹配 |
| Agent Marketplace | ❌ 不采纳 | 太早 |

---

## Phase 路线图

```
Phase 3 ── Agent SDK + 安全体系（收尾中）
  P3-2   #9-#14 全链路集成 ─────── 🟡
  P3-3   #3.7/#3.8/#3.9 安全剩余 ── 🟡
  P3-new #30-#34 Security Agent ── 🟡
  P3.5   X1 Skill / X2 Experience ─ 🟡

Phase 4 ── Security Runtime（Landlock/Seccomp/Namespace）
  ├── SandboxProvider 抽象
  ├── Per-step 权限声明
  ├── 控制流操作符 parallel/forEach/branch/loop
  └── Hash-chain 审计日志 + KV Store

Phase 5 ── Memory Layer（chroma 向量库扩展）
  ├── 三重记忆 + FTS5 ✅
  └── Guardrail 模式

Phase 6 ── 桌面融合 + 一键安装
  ├── Tray 弹窗 UI ↔ SecurityAgent.confirm()
  ├── CLI 流式输出 (rich/typer)
  ├── Plugin Marketplace
  ├── ISO / 一键安装
  └── 语言演进 (PyO3 / TS / Rust)

Phase 7+ ── 长期
  └── Agentic Wiki、多通道、Agent 自优化 X3
```

