# trimum — 未完成待办清单

> 最后更新：2026-09-12 20:11（v15 — 全面待办重构 + 状态修正）
> Phase 3 核心 + Security Agent 全链路 + 四想法 X4 + OpenCLI Bridge 已完成 ✅
> 当前焦点：Phase 3 收尾（#15 真机部署 + #11 LLM 混合策略）+ 网卡修复

---

## ✅ 已完成（Phase 3 + Security Agent + 工具 + 杂项）

### Phase 3 核心 ✅
- #1 TARL-SPEC — TARL v1.0 完整规范 ✅
- #2 TARL Parser — 246 行 KV 行 parser + Serializer ✅
- #3.3 凭据脱敏 — `_redact_credentials()` 完整实现 ✅
- #3.4 cwd Jail — `_check_cwd_jail()` 路径白名单 ✅
- #3.5 AI/人类流量标签 — SourceType + PolicyEngine source 过滤 + 7 测试 ✅
- #3.6 JIT 一次性授权 — `_check_jit_auth` + `issue_jit_token` + `grant_jit_token` ✅
- #3.8 审计日志 — `_record_audit()` JSON 到 logger + AuditEvent ✅
- #6 Agent File 化 — agent.json5 + AGENT.md + main.py ✅
- #7 Security TARL — TARL 安全规则 ✅
- #8 Transform Agent — 274 行 LLM 调用 + confidence + TransformResult ✅
- #8.5 confidence — TransformResult 含 is_certain/needs_confirmation/needs_planner ✅
- #12 Router/Planner — AgentRouter 已删除，AgentRegistry 承载 ✅
- #19 Workflow 文件化加载 — load_yaml / load_from_dir + 2 示例 ✅
- #20 记忆文件放到 Agent 文件夹 — ContextManager db_path→db_dir ✅
- #21 Certs 移到 Agent 文件夹 — Agent 文件夹 cert.json 优先级 ✅
- #22 Agent depends_on — check_dependencies() + 12 测试 ✅

### Security Agent 全链路（原 P3-new #30-#34）✅
- #9 SecurityRule ↔ ToolGateway 全链路集成 — execute() Layer 4 调 sec_monitor.scan_command() ✅
- #9 测试 — `test_gateway_security_rule_allows_safe_command` + `test_gateway_security_rule_with_rule_allows` ✅
- #30 SecurityRule Layer 4 — sec_monitor 已集成进 ToolGateway.execute() ✅
- #31 sec_monitor.py — ThreatMatcher + OpContextClassifier + AuditChainVerifier + SecMonitor（440 行）✅
- #32 sec_executor.py — SecBlocker/SecAudit/SecNotif/SecExecutor（200 行）✅
- #33 内置安全工作流 — threat_workflows.py（216 行）✅
- #34 监听器注册机制 — workflow_listener.py（282 行）✅
- #3.3 `_redact_credentials()` 完整实现 + execute() 末尾调用 ✅

### 工具文件化 ✅
- Scraper Tool (`~/.trimum/tools/scraper/main.py`) — Scrapling 0.4.15 Fetcher + StealthyFetcher，反爬突破（豆瓣/百度/知乎）✅
- DocParser Tool (`~/.trimum/tools/docparser/main.py`) — PDF/DOCX/PPTX/XLSX/MD 5 种格式 ✅
- 工具依赖注册头 `__dependencies__` ✅

### 杂项 ✅
- X4 证书体系 — agent_cert.py 官方/自签/无证三档 + 机器指纹 ✅
- #18 json5 依赖 — `pyproject.toml` 已加 `"json5>=0.9"` ✅
- docs/SECURITY-DEFENSE-PLAN.md — 825 行 / 36KB ✅
- src/trimum_core/security_agent_agenda.md — 8050 字节 ✅
- **全量测试 296/297 pass** ✅（仅 skip 1：Windows 下 nonexistent_dep 测试）
- **`__init__.py` 修复** — AuditEvent export bug 已修 ✅
- **STATUS.md v14** — 更新 SafeMind TODO + OpenCLI Bridge 状态 ✅

---

## 快速定位（最新层级）

| 优先级 | # | 任务 | 环境 |
|--------|---|------|------|
| 🔴 立即 | 1 | **#15 真机部署 trmd** — 目标 Ubuntu 上部署并验证 end-to-end | ✅ 本机 & Ubuntu 均可做 |
| 🔴 立即 | 2 | **#11 LLM 混合策略** — PolicyEngine 纯正则→正则+LLM 双模式 | ✅ 本机可做 |
| 🟡 中优 | 3 | **#3.9 CLI 流式输出** — trm CLI 加 typer/rich 流式渲染 | ✅ 本机可做 |
| 🟡 中优 | 4 | **#3.7 Cgroup 资源接口层** — ResourceController 基类 + mock 测试 | ✅ 本机可做 |
| 🟡 中优 | 5 | **X1 Skill 集成** — AgentRegistry ↔ SkillRouter 运行时连接 | ✅ 本机可做 |
| 🟡 中优 | 6 | **#13 BehaviorMonitor 闭环** — 检测结果反馈→行为基线更新 | ✅ 本机可做 |
| 🟡 中优 | 7 | **#16 清理** — D:\	rimum\	mp/ 68 files + src/trimum-mvp/ | ✅ 本机可做 |
| 🟢 等真机 | 8 | **#14 Landlock** — Landlock/Seccomp 沙箱（Phase 4） | ❌ 需 Linux |
| 🟢 低优 | 9 | **DKMS 编译 AIC8800** — 一劳永逸 | ❌ 需目标 Ubuntu |
| 🟢 低优 | 10 | **server/arch-linux 分支同步** | 🔲 后续重建 |
| 🔵 远期 | 11 | **SafeMind 对抗加固** — safe_lab.py + red_team.py + verifier.py | Phase 4 |
| 🔵 远期 | 12 | **Agent SDK 封装** — src/agent-sdk/ 空目录 | Phase 4+ |

---

## 🔴 立即（真机前可做）

### 1️⃣ #15 真机部署 trmd（Phase 3 收尾硬目标）
- **目标**：目标 Ubuntu 上完成 `trm health` 全模块导入检查 + `trmd` daemon 启动验证
- **前置**：OpenCLI 1.8.7 ✅，网卡修复 ✅，环境已就绪 ✅
- **步骤**：
  1. 上传源码到 `/home/guzhujushi/trimum/`
  2. `pip install -e .` 或 `uv pip install -e .`
  3. `python -m trimum_core.main --version`
  4. `python -m trimum_core.main health`
  5. 修复 Linux-only 导入失败（Unix socket 等）
  6. 启动 `trmd` 验证 API Server 可达
- **验收**：`trm health` 全部 ok，`curl http://127.0.0.1:8321/health` 返回 200

### 2️⃣ #11 LLM 混合策略（PolicyEngine 核心短板）
- **当前**：纯正则匹配，无 LLM 辅助分析
- **升级**：新增 `LlmPolicyEngine` wrapper
  - 正则命中高风险/疑似 → 调 LLM 二次确认
  - LLM 不可用时回退正则决策
  - 结果缓存（同指令 5 分钟内复用）
- **验收**：高风险走 LLM，低风险直通正则

### 3️⃣ 修复记录 + 网卡 DKMS（跟踪项）
- ✅ 网卡已修复（内核回退 6.8.0-41 + 锁定）
- ✅ OpenCLI Bridge 代码完成 + 部署 + 实测通过
- ✅ X1 Skill 层已实现（50 个 skill/experience 测试通过）
- ✅ X2 ExperienceLearner 已实现（508 行完整实现）
- ✅ 目标 Ubuntu 环境已就绪
- [ ] DKMS 编译 AIC8800 驱动（一劳永逸适配未来内核）

---

## 🟡 中优（真机前可做）

### #3.7 / G6 子 Agent 资源配额
- **当前状态**：`security_rule.py` 中有 `_check_resource_limits()` 进程内软限（psutil 采样），`set_resource_limit()`/`get_resource_limits()` 接口已存在
- **升级方向**：
  1. 先写 `cgroup_controller.py` — Cgroup v2 接口抽象层（读写 `/sys/fs/cgroup/`），提供 `set_cpu_limit()` / `set_memory_limit()` / `set_io_limit()` / `apply()` 方法
  2. `ResourceController` 基类 + `PsutilController`（现有软限回退）+ `CgroupV2Controller`（Linux 真机时激活）
  3. `SecurityRule._check_resource_limits()` 改为调用 `ResourceController.check()`
  4. Agent Runtime spawn 时通过 `cgroup_controller.apply(agent_id, limits)` 注册 cgroup 层级
- 验收：Cgroup v2 接口可创建子 cgroup、可设置 CPU/mem 限、超限触发 Event Bus `security.alert`
- **注意**：Cgroup v2 功能实现需 Linux，但接口层和测试（mock `/sys/fs/cgroup/`）可在 Windows 完成

### #13 BehaviorMonitor 闭环
- BehaviorMonitor 已有基础框架（滑动窗口、分类、异常检测、频率检测）
- 扩展：新操作类型学习的反馈闭环
- 对接 SecMonitor，使检测结果→BehaviorMonitor 更新行为基线

### #3.9 / G9 CLI 流式输出
- ✅ `trm exec <natural language>` 入口已完成（AgentLoop + LiveConsole + Rich）
- **待改进（Phase 3.5）**：
  - [ ] **多步 Agent 循环**：不是一次性计划，而是执行结果→LLM分析→下一步→直到完成
  - [ ] **确认交互增强**：每步展示操作摘要，用户可同意/修改/跳过
  - [ ] **Live 面板**：实时 EventBus 进度面板（Rich Live），不是 print
  - [ ] **Operator 模式**：允许用户在循环中修改 prompt/调整计划

---

## 🟢 低优（等真机或可选）

### #14 Landlock 兜底（Phase 4 预备）
- `policy_engine.py` 和 `security_rule.py` 已有 stub 接口
- 等 Arch Linux 真机时实现

### #15 真机 Arch Linux 验证 trmd 启动
- Unix Socket IPC、Systemd 服务单元、Hyprland 集成
- 需买服务器后验证

### #16 Codex 遗留清理
- `D:\trimum\tmp\` 清理

### #17 SonarQube 重扫
- 确认 181 issues 无回归

### X3 Agent 自优化 — 🟢 低优
- Agent 可优化自己的 prompt/示例/工具策略（不可改权限/安全边界）
- 改进建议写入 memory/pending-improvements.json
- `trm agent improve/apply` 命令管理

---

## 🔵 远期（真机后 / Phase 4+）

### Phase 4 — Security Runtime
- Landlock/Seccomp/Namespace SandboxProvider 抽象
- Per-step 权限声明
- 控制流操作符 parallel/forEach/branch/loop
- Hash-chain 审计日志 + KV Store

### Phase 5 — Memory Layer
- chroma 向量库扩展
- Guardrail 模式

### Phase 6 — 桌面融合 + 一键安装 + 官网
- Tray 弹窗 UI ↔ SecurityAgent.confirm()
- CLI 流式输出 (rich/typer) ⬅️ #3.9 已前置到 🟡 中优
- **`trm install` 一键安装** — Plugin Marketplace（官方 Agent/Tool/Workflow 仓库）
- **trimum 官网** — 展示项目、文档、下载入口
- ISO / 一键安装镜像
- 语言演进 (PyO3 / TS / Rust)

### Phase 7+
- Agentic Wiki、多通道

---

## 📋 已关闭建议（DeepSeek 审核）

| 建议 | 结论 |
|---|---|
| Transform Agent confidence 字段 | ✅ 已采纳并完成 |
| TRM 错误码体系 | ✅ 已采纳，#14.5 |
| Policy Engine 学习模式 | ✅ 已采纳，#13 |
| Event Bus 虚拟文件接口 | ⚠️ 远期记录在 ARCHITECTURE.md |
| Memory SQLite→sqlite-vec | ⚠️ 知识记录在 ARCHITECTURE.md |
| usearch | ❌ 不采纳（量级不匹配） |
| Agent Marketplace | ❌ 不采纳（太早，Phase 6 再议） |
