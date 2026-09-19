# STATUS — 当前进度

> 最后更新：2026-09-19（P0 + P1 收尾）
>
> 当前阶段：Phase 3 收尾 — **P0/P1 阻断项已全部清零**，仅余 P2（桌面确认通道 / SDK 测试 / SonarQube 重扫）

---

## 任务清单

### Phase 0 — 基础环境建设 ✅
- [x] 项目 README（定位、架构、路线图）
- [x] 架构文档（ARCHITECTURE.md v2.0）
- [x] 开发路线解读（DEVELOPMENT-ROADMAP.md）
- [x] 技术选型 BOM（TECHNICAL-BOM.md）
- [x] 参考项目调研（REFERENCE-PROJECTS.md）
- [x] 开源复用策略（REUSE-STRATEGY.md v2）
- [x] 配置文件骨架（config/trimum.yaml, config/policy.yaml）
- [x] Phase 1 详细开发计划（docs/PHASE1-PLAN.md）
- [x] STATUS.md 三文件工作流就绪 + 密钥配置写入 README
- [x] AGENTS.md 更新（API 频率限制 + 代理配置）
- [x] 项目名定稿：trimum（CLI 命令 trm）
- [x] 开发环境方案变更：放弃虚拟机，Phase 1 直接在 Windows 开发

### Phase 1 — AI Shell MVP（Python）✅
- [x] 第 1~7 步全部完成（项目脚手架 → LLM 适配器 → 策略引擎 → 命令规划器 → 执行器 → CLI → Shell 集成 → 验证）
- [x] 代码审查 & 修复（2 critical / 3 high / 6 medium / 9 low 全部修复）
- [x] 39 个测试用例全部通过

### Phase 1.5 — 桌面预设 + 安装脚本 ✅
- [x] Hyprland 5 套主题预设（tokyo-night / catppuccin / gruvbox / nord / rose-pine）
- [x] 主题切换器 scripts/trimum-theme（list / set / preview）
- [x] Btrfs + Snapper 自动配置
- [x] 安装脚本 desktop/install.sh（纯 bash）

### Phase 2 — trimum Core（Python + FastAPI）✅
- [x] Agent Registry + Agent Router（agent_registry.py / agent_router.py）
- [x] Tool Gateway 重构（ToolRegistry + Agent 权限双层检查 + 11 Dispatchers）
  - FileDispatcher / GitDispatcher / HttpDispatcher / ProcessDispatcher
  - SystemDispatcher / ShellDispatcher / EnvDispatcher / KnowledgeDispatcher
  - NotificationDispatcher / MCPDispatcher / CustomDispatcher
- [x] Planner Agent（planner_agent.py，~500 行）
- [x] API Server 框架（api_server.py）
- [x] Policy Engine（policy_engine.py，正则规则引擎）
- [x] Event Bus（event_bus.py，异步 pub/sub）
- [x] Context Manager（context_manager.py，SQLite 持久化）
- [x] IPC Handler（ipc_handler.py，JSON-RPC 2.0 over Unix Socket）
- [x] Models（models.py，全部 Pydantic 模型）
- [x] Config（config.py，YAML 配置加载）
- [x] 测试覆盖 ~120 个测试用例 → 全部通过
- [x] SonarQube 扫描：181 issues 待评估（多为 CSS/C语言假阳性/Cognitive Complexity 等低风险项）
  - 已修复 3 个真实 bug（空 f-string / 未用变量 / 重复字面量常量化）
  - 已配置排除（图片 / Waybar CSS / 源文件编码）
- [x] README.md 重写（亮点前置表格 + 架构图 + 组件表 + 开发状态 + 快速开始）

### Phase 3 — Agent SDK & 通信架构（进行中）
- [x] **Agent Socket**（agent_socket.py）— Unix Socket Server/Client，JSON-RPC 帧协议
  - AgentSocketServer：监听 Socket，接收子 Agent 连接，收发 start/stop/status 信号
  - AgentSocketClient：子 Agent 端连接 Runtime 的客户端
- [x] **Agent Runtime**（agent_runtime.py）— 子 Agent 进程生命周期管理
  - start_agent / stop_agent / get_status / list_agents
  - 通过 Event Bus 广播状态变更（agent.started / agent.stopped）
  - 最大 Agent 数限制，发布/订阅事件循环
- [x] **Workflow v2 格式**（workflow_engine.py 扩展）
  - WorkflowStep / WorkflowStepCondition / WorkflowDefV2
  - 监听器→执行组格式（trigger: event_type + condition, execute: [AgentTask]）
  - start_v2()：等待事件触发 → 通过 Event Bus 派发任务 → 监听完成 → 进入下一步
  - 向后兼容旧 Node/Edge/WorkflowDefinition 格式
- [x] **Context Manager 扩展**（context_manager.py）
  - 项目上下文接口（set/get/list_project_context）
  - `requires_confirmation()` — 判断读取是否需要弹窗确认
  - 规则：子 Agent 读自己记忆不需要确认，读项目公共上下文需要确认
- [x] **Landlock 接口预留**（policy_engine.py / security_agent.py）
  - check_landlock() / get_landlock_ruleset() — Phase 4 实现
- [x] **Event Bus 扩展**（event_bus.py）
  - Agent 消息类型常量：TASK_ASSIGNED / TASK_STARTED / TASK_COMPLETED / TASK_FAILED / AGENT_STATUS_CHANGED
- [ ] Agent SDK 封装（openai-agents-python 集成）
- [ ] 预设 Agent + Workflow 模板
- [ ] Tool + Agent 鉴权的全链路集成测试

- [x] **TokenStatusPanel**（live_console.py）— Rich token/resource 实时面板（token/CPU/memory/calls 进度条 + `__all__` 导出）

#### 弹性沙箱体系（新，2026-09-01）
- [x] **Security Agent**（security_agent.py）— 弹性沙箱决策中心
  - 跨 Agent/工具访问决策（can_access / can_execute）
  - 跨沙箱 / 同一沙箱不同工具的访问规则
  - 资源阈值检查（CPU / 内存 / 写入频率等）
  - 弹窗确认接口（confirm()）
  - 防溢出风险评估（get_escape_risks）
  - 工作流白名单（register_workflow_peers）
- [x] **Behavior Monitor**（behavior_monitor.py）— 行为基线 + 异常检测
  - 操作历史追踪（滑动窗口 300 秒）
  - 命令分类（文件 / 网络 / 进程 / 容器 / VCS 等 8 大类 22 小类）
  - 突发高频检测（按操作类型阈值）
  - 跨沙箱操作检测
  - 新操作类型检测
- [ ] Security Agent ↔ Agent Router / Tool Gateway 的全链路集成
- [ ] 弹窗确认的 UI / API 入口

### Phase 4 — Security Runtime（计划中）
- [ ] Landlock LSM 集成（os.landlock / ctypes）
- [ ] ML 行为基线模型
- [ ] 权限审计日志

### Phase 5 — Memory Layer（计划中）
### Phase 6 — ISO / 安装镜像（计划中）

---

## 决策记录

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-08-29 | Phase 2 改用 Python + FastAPI，放弃 Rust | Rust 编译卡关是 vibe coding 最大风险 |
| 2026-08-29 | 全项目 Python 主栈 | 统一语言栈降低维护成本 |
| 2026-08-29 | 引入 openai-agents-python | 替代自研 Agent SDK |
| 2026-08-29 | 引入 Supervisor / psutil / apprise / chroma | 替代自研进程管理/系统度量/通知/向量库 |
| 2026-08-29 | Phase 5 用 chroma 替代 PostgreSQL+pgvector | 桌面场景不需要服务级数据库 |
| 2026-08-30 | 项目名定稿：trimum / trm | 原名 Harness 太土，改为 trimum |
| 2026-08-30 | 放弃虚拟机，Phase 1 直接在 Windows 开发 | AI Shell 核心逻辑跨平台，在 Windows 写好验证后再部署 Linux |
| 2026-08-30 | Hyprland 主题包采用标准 .conf，不复用 omarchy Lua 预设 | .conf 更贴近原生 Hyprland，可被 hyprctl reload 热重载 |
| 2026-09-01 | Phase 3 通信架构：Workflow Engine→Socket→Agent Runtime→Socket→子Agent；所有业务走Event Bus | Workflow Engine 做决策，Agent Runtime 只启停，Event Bus 纯消息通道 |
| 2026-09-01 | 弹性沙箱 = Security Agent 决策 + Behavior Monitor 异常检测 + Policy Engine 规则匹配 | 三层分离：规则→行为→决策，互不耦合 |
| 2026-09-01 | 跨工具互访需 Security Agent 确认（即使同一沙箱在 Docker 内） | 开发者工具互相隔离，防信息泄露和权限提升 |
| 2026-09-01 | 安全 = Core 的职责，不是独立 Agent | 安全是基础设施，不交由子 Agent 管理 |
| 2026-09-02 | DeepSeek 建议审核入档 | `docs/DEEPSEEK-ADVICE-REVIEW.md` — 3 采纳 / 3 部分采纳 / 2 不采纳 |
| 2026-09-02 | Pydantic AI Harness 对比调研 | `docs/PYDANTIC-AI-COMPARISON.md` — 定位不同，不是竞品；发现 6 项 trimum Phase 3 差距 |
| 2026-09-02 | REFERENCE-PROJECTS 审计 | `docs/REFERENCE-AUDIT.md` — 7 项目逐项对照，发现 35% 借鉴点未落地，新增 7 项差距（G3-G9）|
| 2026-09-02 | Phase 5-7 规划扩展 | `docs/DEVELOPMENT-ROADMAP.md` 重写 — Phase 5 记忆+工具链 / Phase 6 ISO+包管理 / Phase 7 前端+生态市场 |

---

## 今日进度（2026-09-01）

| 完成项 | 状态 | 备注 |
|---|---|---|
| SonarQube 3 个 bug 修复 + 排除配置 | ✅ | 空 f-string / 未用变量 / 重复字面量常数化 |
| README.md 重写 + .gitignore 精简 | ✅ | 亮点前置表格 + 整洁结构 |
| Agent Socket + Agent Runtime | ✅ | 新增 2 文件（~390 行）|
| Workflow v2 格式（监听器→执行组） | ✅ | WorkflowDefV2 / WorkflowStep / start_v2() |
| Context Manager 扩展（项目上下文/记忆/确认） | ✅ | set/get/list_project_context + requires_confirmation() |
| Event Bus Agent 消息类型 | ✅ | TASK_ASSIGNED / STARTED / COMPLETED / FAILED / STATUS_CHANGED |
| **Security Agent + Behavior Monitor** | ✅ | 新增 2 文件（~620 行），完整的弹性沙箱决策体系 |
| **Agent 文件化** | ✅ | `~/.trimum/agents/` 扫描 + auto-load |
| **工具文件化（11 tools）** | ✅ | `~/.trimum/tools/<name>/tool.json5 + main.py` |
| **TARL-SPEC.md** | ✅ | KV 行格式规范 v1.0（Scheme B）|
| **tarl_parser.py** | ✅ | parse_line / parse_multi / serialize / match_prefix / 12 测试通过 |
| **transform_agent.py** | ✅ | Transform Agent 骨架（NL→TARL 输出 Phase 1 stub）|
| **docs/PHASE1-PLAN.md 删除** | ✅ | 内容已合并到 ARCHITECTURE.md + TARL-SPEC.md |
| **GitHub 推送** | ✅ | 6 commits 已推：bf9c7b4 → 51ba21d |
| 版本升级 | ✅ | v0.3.1 → v0.4.0 |
| **Phase 3 高优全部完成**（#1-#7） | ✅ | Task State Machine / TARL 匹配 / Handoff Snapshot / Security TARL |
| **测试 98 pass 0 fail** | ✅ | 1 deselected（AgentRegistry auto-load）|
| **开源调研分析文档** | ✅ | `docs/ECOSYSTEM-COMPARISON.md` — SemaClaw/skelm/Sandcastle 完整分析 |
| **README.md 生态位+致谢段** | ✅ | 新增「生态位置」+「开源参考与致谢」两个段 |
| **代码审查（Codex SIGKILL）** | ❌ | 90s 超时被杀，需 split scope 重试 |

---

## 下一步（优先级排序）

1. 🔴 **SafeMind 红蓝对抗安全加固** — 隔离实验室环境 (safe_lab.py) + 红队 agent (red_team.py) + 检测规则验证器 (scarecrow/verifier.py)
2. 🔴 **Agent SDK 封装** — 集成 openai-agents-python 作为底层，在其上包装 Tool Gateway + Security Agent 权限层（当前 `src/agent-sdk/` 是空目录，是最关键的未完成项）
3. 🔴 **全链路集成测试通过** — 当前 296/297 pass，修复 AuditEvent 导出 bug
4. 🟡 **普通网络场景工具化** — OpenCLI 桥接适配器按需启用
5. 🟡 **Policy Engine 升级（正则→LLM 混合）** — 当前纯正则，需要在可疑行为时调 LLM
6. 🟡 **BehaviorMonitor 闭环** — 反馈闭环，动态调整行为基线
7. 🟡 **DKMS 编译 AIC8800 网卡驱动** — 一劳永逸，不让内核锁死
8. 🟡 **CLI 流式输出** — trm CLI 加 rich/typer 流式渲染
9. 🟡 **弹窗确认的 API/UI 入口** — 用户如何收到弹窗、如何确认
10. 🟢 **`D:\trimum\tmp\` 清理** — 68 个 codex 临时文件
11. 🟢 **`src/trimum-mvp/` 清理** — 废弃的 MVP 代码
12. 🟢 **SonarQube 重扫** — 确认修复效果，无回归
---

## Ubuntu Deploy 任务进度（2026-09-11）

- [x] config/trimum-ubuntu.yaml — Ubuntu 默认配置（FHS 路径）
- [x] config/policy.yaml — 内容与现有策略保持一致，统一为 LF
- [x] scripts/trm.bash — 	rm CLI bash wrapper，已标记 100755 可执行
- [x] .gitattributes — 增加 *.bash text eol=lf
- [x] scripts/install.sh — Ubuntu 无交互安装脚本（Python 3.12+、venv、用户/目录、systemd、tmpfiles）
- [x] scripts/trmd.service — trimum AI Runtime Daemon 的 systemd unit
- [x] scripts/trm — trm CLI wrapper，已标记 100755 可执行
- [x] .gitattributes — 增加 *.service text eol=lf、scripts/trm text eol=lf

---

## 2026-09-19 browser tool 路由修复

### 任务清单
- [x] `models.ToolType` 增加 `BROWSER = "browser"`
- [x] `tool_file_loader.TOOL_KINDS` 增加 `browser` 映射
- [x] `tool_gateway._check_cwd_jail` 将 `BROWSER` 加入免 cwd 校验集合
- [x] browser `main.py` / `_cdp.py` CDP URL 改为可配置（已提供 patched 副本）
- [x] 编写 `codex-tasks/browser-tool-debug/verify.py` 并验证通过
- [x] 编写 `codex-tasks/browser-tool-debug/FINDINGS.md`

### 验证结果
- `verify.py`：7 项检查全部 PASS
- `tests/test_tool_file_loading.py tests/test_other_dispatchers.py tests/test_jit_auth.py`：74 passed
- `tests/test_integration.py -k "not context_manager"`：31 passed

---

## 2026-09-19 `trm` CLI 实现

### 任务清单
- [x] 读取 `tmp/spec_cli_implementation.md`，按 argparse 子命令方案拆分命令
- [x] 新增 `src/trimum_core/cli/parser.py`、`cli/_utils.py`、`cli/__main__.py`
- [x] 新增 `cli/commands/` 下 version/health/status/ask/exec/install/memory/security/daemon/log/tool/agent/config/workflow/doctor
- [x] 实现 `commands.register_all()` 动态注册，并递归注入全局 `--json`
- [x] `pyproject.toml` 的 `trm` 入口和 `scripts/trm` 对齐到 `trimum_core.cli`
- [x] `trimum_core/__init__.py` 版本对齐 pyproject：`0.5.0`
- [x] `config.Config` 补充 `set()` / `save()`，支撑 `trm config set`
- [x] 新增 `tests/test_cli.py`

### 验证结果
- `python -m trimum_core.cli --help`：正常列出 15 个命令
- `python -m trimum_core.cli version`：输出 `trimum v0.5.0`
- `python -m pytest tests/test_cli.py -q`：23 passed


---

## 2026-09-19 Phase A — CLI 框架重构收口

### 任务清单
- [x] 真机 SSH 调研：`/opt/trimum` 与 `/home/guzhujushi/trimum` 源码 `.py` 一致，`/opt/trimum` 的 daemon 运行中
- [x] `parser.py` 全局参数扩展：`--json/--config/--quiet/--verbose` 递归注入
- [x] `_utils.py` 支持 `quiet/load_config/TTY` 颜色辅助，`emit` 尊重 quiet
- [x] `cli/__init__.py` 顶层异常兜底 + 无命令时 JSON/quiet 状态输出
- [x] 删除 `main.py` 旧 `cli_dispatch/health/security` 入口，`python -m trimum_core.main` 直接走 daemon `run()`
- [x] 扩展 `tests/test_cli.py`：全局参数前后位置、quiet 输出、无效命令退出码 2
- [x] 本地 `python -m pytest tests/test_cli.py -q`：32 passed
- [x] 同步源码到 `/home/guzhujushi/trimum` 与 `/opt/trimum`；`tests/test_cli.py` 同步到 home
- [x] 真机 smoke test：parser-ok / main-quiet-ok / `/opt/trimum/trm version`、`status` 正常

### 待办与说明
- [ ] Phase B：`status/health/doctor/memory` 命令增强
- [ ] 真机 venv 尚未安装 pytest；如需远端跑 pytest 需先安装
- [ ] `/opt/trimum/tests` 当前为 root:root 755，如需同步测试文件需要 sudo


---

## 2026-09-19 Phase B — CLI 核心命令增强

### 任务清单
- [x] `trm status`：增加 host/port/socket、PID、进程 uptime/内存/CPU、主机资源快照
- [x] `trm health`：增加 API key 存在性检查（只报告是否配置，不泄露）
- [x] `trm doctor`：补齐 API key 检查、目录项明细、依赖/磁盘/网络诊断输出
- [x] `trm memory`：`list --domain/--category/--entries/--limit`、`search --limit`、`get` found 状态、人类可读输出
- [x] `_utils.check_env_keys()`：共用环境变量 presence-only 检查
- [x] 新增 `tests/test_cli_commands.py`，覆盖 status/health/doctor/memory

### 验证结果
- `pytest tests/test_cli.py tests/test_cli_commands.py -q`：37 passed
- 本地 smoke：`status` JSON、`health` JSON、`doctor` 人类输出正常
- 待办：`trm security revoke` 仍在 Phase C/后续，未纳入本轮


---

## 2026-09-19 Phase C — Agent 交互体验与可观测性接线

### 任务清单
- [x] `AgentLoop` LLM 调用成功解析 `usage` 并 `token_tracker.record(...)`
- [x] `AgentLoop._chat_completion()` 统一 LLM 调用，支持 SSE 流式输出
- [x] `AgentLoop` 事件发布改用 `EventBus.emit_task`，兼容 `WorkflowEngine` 的 `task.*` 约定
- [x] `LiveConsole.subscribe_events/unsubscribe` 修复订阅句柄，正确退订
- [x] `trm ask -i` 挂载 `ContextManager` session 记忆（register/update）
- [x] `trm ask` JSON 输出增加 `token_usage`，人类模式显示 token 统计
- [x] `trm ask --json/--quiet` 使用静默 console，避免污染机器可读输出
- [x] `AgentManager.spawn` 注入 `ResourceController`，依平台选择 cgroup v2 / psutil，并 set/apply limits
- [x] `resource_controller` 新增 `resource_limits_from_config()` / `create_resource_controller()`
- [x] 新增 `tests/test_agent_loop.py`、`tests/test_agent_manager.py`，扩展 `tests/test_resource_controller.py`

### 验证结果
- `pytest tests/test_resource_controller.py tests/test_agent_loop.py tests/test_agent_manager.py tests/test_cli.py tests/test_cli_commands.py -q`：70 passed
- `pytest tests/test_workflow_files.py -q`：14 passed
- `pytest tests/test_integration.py -q -k "event_bus or unsubscribe or workflow"`：10 passed / 1 已知失败（Windows `~/.trimum` cert 权限，非本轮改动）

### 待办
- [ ] 子 Agent 进程真实 spawn 后，把 `apply_cgroup(pid)` 接到真实 PID（当前仍为 Phase 3 stub）
- [ ] `trm ask` 的 SSE 流式在 `--json/--quiet` 下自动关闭（已实现，需真机 TTY 验证）
- [ ] `trm security revoke` 等 Phase C 后续命令


---

## 2026-09-19 Phase 3 收尾差距审计（对照 docs 与现有实现）

> 基准：`docs/PHASE3-4-PLAN.md`、`docs/REFERENCE-AUDIT.md`、`docs/PYDANTIC-AI-COMPARISON.md`

### 已闭环（docs 已过期，实测代码已实现）

| 项目 | 现状 |
|---|---|
| Agent SDK | `src/agent-sdk/trimum_agent.py` 已实现，`planner_agent.py` 可选集成 |
| cwd Jail | `tool_gateway._check_cwd_jail()` + `ExecuteRequest.skip_cwd_check` |
| 凭据脱敏 | `tool_gateway._redact_credentials()` + `logger` 全局脱敏 |
| JIT 一次性授权 | `tool_gateway.issue_jit_token()` + `/api/security/allow_once` + `trm security` |
| AI/人类流量模型 | `SourceType.HUMAN/AI/UNKNOWN` + PolicyEngine source-aware |
| 资源配额 | `CgroupV2Controller` + `AgentManager` set/apply limits |
| Token 追踪 | `TokenUsageTracker` + `AgentLoop` 实记录 |
| 流式 CLI | `AgentLoop._chat_completion()` SSE 流式输出 |
| Workflow TARL | `WorkflowEngine.register_tarl_workflow/match_workflow_by_tarl` |
| Security Agent TARL | `SecurityRule.can_execute_tarl()` |
| Transform Agent 测试 | `tests/test_transform_agent.py` 覆盖 confidence |

### Phase 3 收尾阻断项

| 优先级 | 缺口 | 依据 / 现状 | 建议动作 |
|---|---|---|---|
| **P0** | **SecurityRule/SecurityAgent 未接入 ToolGateway** | `tool_gateway.py` 仅持有 `self.security_rule`，`execute()` 未调用 `can_execute()` | 在 Layer 2 与 Layer 3 之间插入 `SecurityRule.can_execute()`，失败走 `security_blocked` 审计 |
| **P0** | **上下文窗口管理/Compaction 缺失** | `agent_loop` 仅截断最近 5 步 / 3000 字符，无 Tool Output Limits / 压缩 | 增加 tool 输出截断 + 滑窗 + compaction，复用 `context_manager` 最小上下文 |
| **P1** | **审计日志未上 EventBus / 不可查询** | `_record_audit` 仅 structlog + 内存环 | `AuditEvent` 发 `task.audit.*`，`trm log audit` 走结构化查询 |
| **P1** | **子 Agent 真实 spawn + cgroup PID** | `AgentManager.spawn` / `AgentRuntime.start_agent` 仍是 stub | Phase 3 补 `main.py` 启动并 `apply_cgroup(pid)` |
| **P1** | **AI/人类流量标记未统一** | `AgentLoop` 已设 `SourceType.AI`，`trm exec` 仍用 `UNKNOWN` | `trm exec` 默认 `SourceType.HUMAN` |
| **P1** | **Policy 学习模式未接线** | `learning_engine.py` 已实现但 ToolGateway 未集成 | 接 `LearningEngine` 到 BehaviorMonitor 反馈环 |
| **P2** | **确认 UI 只有 CLI，无桌面/WebSocket 通道** | `LiveConsole.confirm` 可用，`SecurityAgent.confirm` 无桌面交付 | WebSocket 通知 / 桌面弹窗 |
| **P2** | **Agent SDK 无端到端测试与打包验证** | `src/agent-sdk` 已写代码但 `tests/` 无覆盖 | 补 SDK 测试 + `pyproject` 打包验证 |
| **P2** | **SonarQube 重扫 / 真机 Arch Linux 验证** | docs P3-19/P3-20，仓库内无结果 | 收尾执行一次重扫 + 真机 smoke |

---

## 2026-09-19 P0 收尾 — SecurityRule 接入 + 上下文压缩

### 任务清单
- [x] `ToolGateway` 新增 Layer 2.5：Layer 2 与 Layer 3 之间调用 `SecurityRule.can_execute()`
- [x] deny → `status=denied` + `security_blocked` 审计；confirm → 升级 `Action.CONFIRM`（interactive 时弹窗确认）
- [x] `ResourceLimitExceeded`（TrimumError）转 deny，其余异常 fail-open 并记 `gateway.security_rule_failed`
- [x] 未显式注入时由网关按需构造 `SecurityRule`（`enable_security_rule=False` 可整体关闭）
- [x] `SecurityRule` 新增 `enforce_resource_limits`（默认 True 保持原语义）；网关用 False，配额仍归 cgroup 层
- [x] 新增 `_merge_decision()`：工具自报的默认 `action=AUTO` / `status=allowed` 不再吞掉网关决策（Layer 1 confirm 一并修复）
- [x] `_record_audit` 补上内存环写入（`_audit_log` 此前只声明、从未写入，环缓冲形同虚设）
- [x] `api_server` 注入 `BehaviorMonitor`，行为异常走 confirm
- [x] 新增 `src/trimum_core/context_compactor.py`：工具输出限长 + 最近 5 步滑窗 + 早期步骤摘要 + 总预算
- [x] `AgentLoop._plan_single_step()` 改用 `ContextCompactor.build()`（原为 `context[-5:]` + 硬截 3000 字符）
- [x] `ToolRegistry.load_all()` 只加载有 `tool.json5` 的目录，opencli 弃用后不再报 `module_failed`
- [x] `.gitignore` 增加 `codex-tasks/`、`*.bak_*`、`HANDOFF.md`；根目录 `check_req.py` / `TODO.md.bak_previous` 移入 `tmp/`
- [x] 新增 `tests/test_tool_gateway_security_rule.py`（11）、`tests/test_context_compactor.py`（13）

### 验证结果
- `pytest tests/test_tool_gateway_security_rule.py -q`：11 passed
- `pytest tests/test_context_compactor.py -q`：13 passed
- 本地全量 `pytest tests -q`：**407 passed**，8 failed / 22 errors 与纯净副本（`git archive HEAD`）一致，均为既有 Windows 权限与 LLM 断网问题
- smoke：`trm exec "echo p0-smoke"` exit=0；`trm tool list` 不再出现 opencli 加载告警

### 待办
- 上述 P0 遗留的 Layer 1 `Action.CONFIRM` 被吞问题已在 `_merge_decision()` 中一并修复。
- 4 项 P1 见下一节「2026-09-19 P1 收尾」，已全部完成。

---

## 2026-09-19 P1 收尾 — 审计/学习/子 Agent 进程化

### 任务清单
- [x] 新增 `src/trimum_core/audit_store.py`：`AuditStore`（JSONL 追加 / 5MB 轮转保留 `.1` / 坏行跳过 / 写入失败不抛）
- [x] `ToolGateway` 接入 `event_bus` + `audit_store`，每条审计额外广播 `task.audit.<event_type>`（deny 类事件 WARNING 级别）
- [x] `trm log audit` 改为结构化查询，新增 `--event-type` / `--agent` / `--risk` / `--since`；文件缺失时回退旧主日志文本过滤
- [x] `trm exec` 来源标记 `SourceType.HUMAN`；`SecurityRule.can_execute()` 透传 `source_type` 给 `PolicyEngine`
- [x] 学习反馈环：`BehaviorMonitor.classify_command()` / `record_command()` 单一数据源 + `pattern_for_action_type()` 反查命令正则
- [x] `LearningEngine` 规则 pattern 由「操作类型名」改为真实命令正则（原先 `"file_read"` 永不匹配真实命令，学习恒为空转）
- [x] 修正置信度归一化（`raw/0.8`）：原上限 0.78 低于默认阈值 0.85，学习规则永远注入不进策略
- [x] `inject_to_policy` 按 learned 来源去重；`get_profiles()` 暴露学习画像
- [x] `AgentLoop` 步骤状态判定修正：网关返回 `allowed/confirmed/success` 记为 `ok`（原先按 `== "ok"` 判定，成功步骤全被当成失败）
- [x] 子 Agent 真实 spawn：新增 `agent_launcher.py`（`create_subprocess_exec` + 真实 PID + `apply_cgroup(agent_id, pid, limits)`），`AgentManager.spawn()` / `AgentRuntime.start_agent()` 接入
- [x] 新增可部署模板 `scripts/agent-template/main.py`（启动 → 经 AgentSocket 报 started → 等 SIGTERM 退出）
- [x] 子进程输出落 `agent-logs/<agent_id>.log`（真机 smoke 暴露：PIPE 无人读有阻塞风险，CLI 退出时还会抛 asyncio "Event loop is closed"）
- [x] `api_server` 注入 `LearningEngine(monitor=behavior_monitor)`，startup 起 60s 周期学习协程（仅 auto 模式自动注入）；新增 `POST /api/security/learn` / `GET /api/security/learning`
- [x] `trm security learning` / `trm security learn [--inject]` 子命令
- [x] 新增测试：`test_audit_store.py`(15) / `test_source_type_flow.py`(6) / `test_learning_feedback.py`(11) / `test_agent_spawn.py`(12)

### 验证结果（本地）
- 本地全量 `pytest tests -q --basetemp tmp/pytest-tmp`：**475 passed**，8 failed / 1 skipped
- 8 failed 与纯净副本（`git archive HEAD` @ 407f2f4）逐条一致：Windows `~/.trimum` chmod/写权限 + LLM 断网，非本轮回归
- smoke：`trm exec "echo p0-smoke"` exit=0；`trm tool list` 无 opencli 加载告警；`trm security learning` 无 daemon 时优雅提示
- smoke 抓到并修掉两个真 bug：
  - `_check_security_rule()` 引用已删除的局部变量 `source_type` → Layer 2.5 静默 fail-open（改用 `getattr(request, "source_type", None)`）
  - 相对脚本路径 + `cwd=script.parent` → 子 Agent 入口找不到（统一 `resolve()` 绝对路径）

### 验证结果（真机 Ubuntu，2026-09-19）
- 环境：`guzhujushi@100.115.86.48`（Ubuntu / Linux 6.8.0-41 / Python 3.12.3），源码同步到 `/home/guzhujushi/trimum` 与 `/opt/trimum`
- 全量测试：**483 passed / 11 failed**；`/tmp/trimum_baseline`（`git archive HEAD` 纯净副本）同机对照为 **403 passed / 同样的 11 failed** → **无回归**（+80 为本轮新增/修复用例）
- 11 项失败均为宿主环境缺失，与本轮改动无关：缺 `~/.trimum/tools/{mcp,browser,...}`、缺 `~/.trimum/skills`、LLM 断网、`test_env_list_sorted` 依赖宿主 env
- smoke 全部通过：
  - `trm tool list` → 宿主 opencli manifest 改名 `tool.json5.disabled` 后输出 `skipped_disabled`，不再 `module_failed`
  - `trm exec 'echo p1-smoke'` → exit=0，审计 `source_type=human`
  - `trm log audit --json` → 结构化条目（落盘 `~/.local/share/trimum/audit.jsonl`）
  - `trm agent spawn demo` → **真实子进程** `python .../agents/demo/main.py demo-84794655`（pid 20244），日志入 `agent-logs/demo-84794655.log`
- 真机暴露并修掉的问题（4 个真 bug + 1 个环境依赖测试）：
  - 宿主机上**常驻 daemon 仍在跑旧代码**（`agent_manager.spawn` 返回 stub 消息）→ 重启 daemon 后恢复真实 spawn（部署流程需把「重启 daemon」写进步骤）
  - 子进程 PIPE 导致 CLI 退出时报 asyncio `Event loop is closed` → 改为输出落 `agent-logs/<agent_id>.log`
  - **`api_server` 启动即崩**：`_learning_loop` 定义在 `startup()` 内部、却在定义前被 `create_task` 引用 → `UnboundLocalError` + `Application startup failed. Exiting.`（daemon 完全起不来）→ 提到模块级并补 `tests/test_api_server_startup.py`
  - **IPC 监听 socket 未设非阻塞**：`loop.sock_accept()` 直接阻塞事件循环 → Linux 上 daemon 假死、测试挂住（Windows 不走该分支所以没暴露）→ `sock.setblocking(False)` + `tests/test_ipc_listener.py`
  - **`trm security learn` 调用错误**：`http_json()` 的 body 是 keyword-only，却按位置传参 → 改 `json_data=` + CLI 回归测试
  - `tests/test_agent_manager.py::test_spawn_sets_resource_limits` 依赖真实用户 agents 目录（真机装了 `demo` 脚本后翻车）→ 改用 `tmp_path` 作 `agents_root`，并补「有脚本时绑真实 PID」用例
- 修完后的真机复跑：**483 passed / 11 failed**（11 项与同机 HEAD 基线逐条一致），全程 24s 无挂起

### 待办
- [x] 真机验证通过后同步分支（`main` / `ubuntu` / `arch-linux` / `server`）并 push（走代理 `127.0.0.1:7993`）
- [ ] `/opt/trimum/tests` 与 `/opt/trimum/scripts` 属 root，需按 `scripts/sync_opt_tests.sh` 用 sudo 补齐
- [ ] cgroup PID 绑定需 root 才能写 `/sys/fs/cgroup/trimum`，真机以普通用户跑时 `apply_cgroup` 会降级告警（P2：装 `trmd.service` 以 root 运行，或加 sudo 授权）
- [ ] `/opt/trimum/config.yaml` 指向 `/run/trimum/trimum.sock`、`/var/log/trimum/`、`/var/lib/trimum/` 等 root 路径；以普通用户手工起 daemon 时 IPC 绑定失败、`trm` 退回 HTTP（P2：统一「systemd 服务 + root」或「用户态路径」二选一）
- [ ] **P0（下一阶段）：CLI-Anything 接入** —— opencli 已弃用（Node 依赖不符合轻量化初衷），改用 CLI-Anything（Python、生态完善），落地 `browser` / `browser-cdp` / `clibrowser` 工具（见 `docs/INTEGRATION-PLAN-BROWSER.md`）
- [ ] P2：桌面/WebSocket 确认通道、`src/agent-sdk` 端到端测试与打包验证、SonarQube 重扫

> 本轮改动**暂未提交**（用户要求：先不 commit/push，真机测过再统一同步）。
