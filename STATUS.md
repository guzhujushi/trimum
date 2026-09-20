# STATUS — 当前进度

> 最后更新：2026-09-20（E2 MCP 接入完成 + 收尾校验）
>
> 当前阶段：Phase 3 收尾**已完成** —— P0/P1 阻断项全部清零并在真机 Ubuntu 验证通过。
> 原「下一阶段 P0 = CLI-Anything 接入」经调研**已否决**（见 `docs/CLI-ANYTHING-RESEARCH.md`）：CLI-Anything 的 `browser` 依赖 Node.js + DOMShell，且 `browser-cdp` 并不存在；浏览器能力继续用自研 CDP 工具。
> 当前方向：**生态四层**（`docs/ECOSYSTEM-STRATEGY.md`）—— L1 MCP 已完成 **M0/M1/M2**（E2，2026-09-20），下一项是 **M3 策展导入器**（`docs/MCP-INTEGRATION-PLAN.md` §6）；其余为 P2（daemon 部署形态 / 桌面确认通道 / SDK 测试 / SonarQube 重扫）。

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
- [x] Agent SDK 封装（`src/agent-sdk/trimum_agent.py` 已实现；未走 openai-agents-python 路线，`planner_agent.py` 可选集成）
- [ ] 预设 Agent + Workflow 模板
- [ ] Tool + Agent 鉴权的全链路集成测试（现有覆盖分散在 `test_jit_auth.py` / `test_tool_gateway_security_rule.py`）
- [ ] `src/agent-sdk` 端到端测试与打包验证（P2，2026-09-20 核实 `tests/` 仍无覆盖）

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
- [x] Security Agent ↔ Tool Gateway 集成（Layer 2.5 `SecurityRule.can_execute()`，2026-09-19 完成）
- [ ] Security Agent ↔ Agent Router 全链路集成
- [ ] 弹窗确认的 UI / API 入口（CLI `LiveConsole.confirm` 可用，缺桌面/WebSocket 通道）

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

> 2026-09-20 重写：此节原为 2026-09-01 的旧清单，多数项已完成或已废弃。历史遗留说明：
> SafeMind 红蓝对抗（仓库内无 `safe_lab.py` / `red_team.py`，从未动工）、OpenCLI 桥接（已弃用）、
> CLI 流式输出（已实现）、`tmp/` 清理（已完成）、`src/trimum-mvp/`（已删除）、
> 「296/297 pass 修 AuditEvent 导出」（已被本地 482 passed 取代）。

1. 🔴 **MCP 接入 M3 策展导入器** —— `tmp/research/awesome-README.md`（4,117 条）→ `config/mcp-catalog.yaml` 候选清单（人工审核后才启用）；解析规则见 `docs/MCP-INTEGRATION-PLAN.md` §3，红线：优先 `uvx` / `pip install` / 单二进制，`npx` 派系默认不收（M0/M1/M2 已于 E2 完成）
2. 🔴 **桌面/WebSocket 确认通道**（P2）—— `SecurityAgent.confirm()` 目前只有 CLI 交付手段
3. 🟡 **`trm security revoke <token_id>`** —— security 命令组最后一块缺口
4. 🟡 **`trm ask -i` 中断处理** —— `ask.py` 无 `KeyboardInterrupt` / `EOFError` 处理
5. 🟡 **`trm memory import|export`** —— 记忆迁移（CLI 进阶）
6. 🟡 **`src/agent-sdk` 端到端测试与打包验证**（P2）—— `tests/` 无覆盖
7. 🟡 **Policy Engine 升级（正则→LLM 混合）** —— `LlmPolicyEngine` 已有骨架，未接线
8. 🟡 **3.5 confidence 三级分流** —— `transform_agent` 只有 confidence 字段，无「直接执行 / 确认 / 转 Planner」分流
9. 🟢 **SonarQube 重扫** —— 确认修复效果，无回归
10. 🟢 **daemon 部署形态二选一** —— `trmd.service`（root）或用户态路径

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
- [x] Phase B：`status/health/doctor/memory` 命令增强（2026-09-19 已完成，见下文 Phase B 章节）
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
- [x] 子 Agent 进程真实 spawn 后，把 `apply_cgroup(pid)` 接到真实 PID（2026-09-19 完成：`agent_launcher.py` 真实 `create_subprocess_exec` + 真实 PID 绑定）
- [ ] `trm ask` 的 SSE 流式在 `--json/--quiet` 下自动关闭（已实现，**待 Ubuntu 开机后 TTY 验证**）
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

### 验证结果（真机 Ubuntu，2026-09-19 ~ 09-20）
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
- [x] 代码提交已落库并推送四分支：`server` `3af9e07`、`main` `26d52f5`、`ubuntu` `4768820`、`arch-linux` `b540f36`（同一提交 cherry-pick）
- [x] 文档收尾提交：本次 `STATUS.md` / `TODO.md` 修订随后同批 cherry-pick 到四分支并 push
- [ ] `/opt/trimum/tests` 与 `/opt/trimum/scripts` 属 root，需按 `scripts/sync_opt_tests.sh` 用 sudo 补齐
- [ ] cgroup PID 绑定需 root 才能写 `/sys/fs/cgroup/trimum`，真机以普通用户跑时 `apply_cgroup` 会降级告警（P2：装 `trmd.service` 以 root 运行，或加 sudo 授权）
- [ ] `/opt/trimum/config.yaml` 指向 `/run/trimum/trimum.sock`、`/var/log/trimum/`、`/var/lib/trimum/` 等 root 路径；以普通用户手工起 daemon 时 IPC 绑定失败、`trm` 退回 HTTP（P2：统一「systemd 服务 + root」或「用户态路径」二选一）
- [ ] **P0（下一阶段）：CLI-Anything 接入** —— opencli 已弃用（Node 依赖不符合轻量化初衷），改用 CLI-Anything（Python、生态完善），落地 `browser` / `browser-cdp` / `clibrowser` 工具（见 `docs/INTEGRATION-PLAN-BROWSER.md`）
- [ ] P2：桌面/WebSocket 确认通道、`src/agent-sdk` 端到端测试与打包验证、SonarQube 重扫

> 本轮改动**已 commit 并 push**：`server` `3af9e07`、`main` `26d52f5`、`ubuntu` `4768820`、`arch-linux` `b540f36`（cherry-pick 同一提交，均已推 origin）。文档收尾（本文件与 `TODO.md`）随后同批同步到四分支。

---

## 2026-09-20 文档一致性修订 + CLI-Anything / MCP 调研

### 文档修订
- [x] `STATUS.md`：重写过期的「下一步（优先级排序）」（原为 2026-09-01 清单）；修正 Phase 3 清单与 Phase A/C 待办中与实际实现矛盾的勾选状态
- [x] `TODO.md`：修正 F1 勾选与 Phase 3 审计表中 CLI-Anything 的表述，新增「MCP 接入」章节
- [x] `docs/INTEGRATION-PLAN-BROWSER.md`：顶部加调研修正（`browser-cdp` 不存在、`browser` 依赖 Node）
- [x] `HANDOFF.md`：加过期提示（该文件含 `trinum` 错拼，仅存历史价值）
- [x] 校验：tracked 文件无 `trinum` / `trumim` 错拼（仅 `AGENTS.md` 的规则句本身命中）

### 调研产物
- [x] `docs/CLI-ANYTHING-RESEARCH.md` —— `HKUDS/CLI-Anything`（49.6k★ / Apache-2.0）核实结果
- [x] `docs/MCP-INTEGRATION-PLAN.md` —— MCP 接入方案（基于 `punkpeye/awesome-mcp-servers` 快照）
- [x] 原始件落 `tmp/research/`（已 gitignore）：仓库元数据、文件树、`registry.json`、浏览器 harness 文档、awesome 列表 README

### 关键结论

| 结论 | 依据 |
|---|---|
| `browser-cdp` 在 CLI-Anything 中不存在 | `registry.json` web 分类仅有 `browser` / `clibrowser` |
| CLI-Anything `browser` 依赖 Node.js + npx + DOMShell 扩展 | 官方 README / HARNESS.md；与本项目「去 Node」决策冲突 |
| trimum 已有等价自研 CDP 工具 | `~/.trimum/tools/browser/`：19 个 action，纯 Python CDP |
| trimum 目前无任何真实 MCP 能力 | `MCPDispatcher` 为占位，固定返回 `MCP bridging not yet available` |
| MCP 生态 TS/npx 占比高（2,271 / 626） | awesome-mcp-servers 快照统计；策展需限定 Python / 单二进制 |
| **CLI-Anything 不是生态最优解** | Omarchy 靠「拥有环境 + 自描述命令面 + skills 分发」，Warp 靠「低门槛 YAML 目录 + 社区 PR」；CLI-Anything 只是 79 个逐应用包装器 |
| Agent Skills 才是最大生态 | nthropics/skills 177,179★，零运行时依赖；长尾适配应写文档而非写包装器 |

### 生态战略（`docs/ECOSYSTEM-STRATEGY.md`）
- [x] 调研 Omarchy（`omacom/omarchy`，42,147★，MIT，分支 `quattro`）：459 个 `bin/omarchy-*` 脚本 + `commands --json --check` 自描述命令面 + 命令元数据注释 + `agents/skills` 符号链接分发到各宿主 + mise 懒加载启动器
- [x] 调研 Warp（`warpdotdev/warp`，65,103★）：`warpdotdev/workflows`（853★，Apache-2.0）用 `specs/**/*.yaml` 极简格式 + 社区 PR 分发
- [x] 结论：**做「生态集成器」而非「生态复制品」**，四层 = L0 环境清单（包管理器）/ L1 MCP / L2 Agent Skills / L3 workflow 目录；统一底座 = 生态注册表 + ToolGateway 分层 + 审计
- [ ] E0-E7 路线图见 `TODO.md` 的「🌐 生态战略」章节（E1 已完成；E5 官方分发 / E6 选装与首启引导 / E7 自研 coding Agent 为本轮新增）
### E1 实现（2026-09-20）
- [x] `src/trimum_core/cli/registry.py`：命令元数据契约（`__command_meta__`）+ 从 argparse 树推导命令面 + `check_commands()` 校验规则
- [x] `trm commands [--all] [--json] [--check]`：49 条命令 / 9 个组；argparse 别名折叠（`ask` ↔ `run`）
- [x] `src/trimum_core/skill_sync.py`：Agent Skills 发现 + 分发（symlink → Windows junction → copy 回退）、冲突检测、`--prune` 清理悬空链接
- [x] `trm skill list / sync / paths`；官方技能 `skills/trm-cli/SKILL.md`（教外部 agent 正确使用 trm）
- [x] 测试：`tests/test_cli_commands_meta.py`（15）+ `tests/test_skill_sync.py`（22）

**验证结果**
- 全量：`pytest tests -q --basetemp tmp/pytest-tmp -p no:cacheprovider` → **519 passed / 8 failed / 4 skipped**；
  8 项失败与 `git archive HEAD` 纯净副本逐条一致（Windows `~/.trimum` 权限 + LLM 断网），**无回归**（基线 482 passed，+37 为新增用例）
- smoke：`trm commands --check` → `ok: 49 commands checked, no problems`；`trm skill list` / `paths` / `sync --dry-run` 输出正常
- `--check` 首跑即抓出真问题：`ask` 的 argparse 别名 `run` 在 `_choices_actions` 中无摘要 → 已用「别名折叠 + 校验规则」修复

### 待办
- [ ] 生态战略 M0/E0：确认四层定位 + 首批 3 个用例
- [ ] MCP 接入 M0：确认真实用例 +「自研 client vs 复用 openai-agents MCP」取舍
- [ ] 待 Ubuntu 开机：`/opt/trimum/{tests,scripts}` 的 sudo 同步、`trm ask` 真机 TTY 验证、Arch Linux smoke、SonarQube 重扫

### 文档修正（2026-09-20，用户两点提示）

> 提示一：这些软件以后是**用户选装**的；将来要集成**全套开发者工具链**（大部分选装，第一次安装引导会问）；
> trimum 将来可能参考 ECC 自研 coding Agent，所以**实际可能一个第三方 agent 都没装、也没用**。
> 提示二：证书会包含安全相关内容（比如**可以动用哪些工具**）；**自签证书只有自己能用，别人想用需再次自签**，
> 因此未来会有**用户体系 / 多用户体系**（`agent_cert.py` 的机器指纹绑定就是雏形）。

- [x] `docs/ECOSYSTEM-STRATEGY.md`：新增 §1.3 ECC 调研（262,999★，903 个 `SKILL.md` / 68 agent / 94 command / 30+ 宿主目录）；
  §2 加 ECC 对照行；§7 改名「官方分发渠道与信任模型」并新增 §7.1 证书 = 来源 + 身份 + 能力、§7.2 多用户前瞻、§7.3 选装模型与 `trm setup`；
  §4 缺口加第 8/9 项；§5 路线图加 E6/E7；§6 风险加第 7/8 项；§8 原始件表补 `ecc-*`
- [x] `PRD.md`：官方分发渠道条目拆细（来源 / 身份 / 能力、自签仅本机本用户、多用户前瞻、选装 + 首启引导、不得假设预装第三方 agent）
- [x] `ARCH.md`：新增「身份、证书能力与多用户（规划）」章节（三层职责、`agent_cert.py` 雏形、证书 capability 与 `security_rule.py` 取交集、
  `~/.trimum` vs `/etc/trimum` 边界、`skill_sync` 目标根改为按探测决定）
- [x] `TODO.md`：E5 补三个子项；新增 E6（选装模型 + 首次安装引导 + 宿主探测）、E7（自研 coding Agent，参考 ECC）；
  章节标题改为 E0-E7 并补灵感源说明

**本轮结论**：证书从「来源证明」升级为**来源 + 身份 + 能力**三层；「选装 + 首启引导 + 零预装可跑」写进 L0/L2 与硬约束；
ECC 作为第三个灵感源入库（只借格式与分发思路，不引入其代码）。

---

## 2026-09-20 E6：选装模型 + 首次安装引导（宿主探测 / 身份证书 / 工具链目录）

> 承接同日两点提示：软件是**用户选装**（首次引导询问）、证书要携带**安全内容**（可动用哪些工具）、
> 自签证书**只有自己能用**（他人需再次自签）、未来有**多用户体系**。E6 把这三条落成可跑的代码。

### 交付

- [x] `src/trimum_core/paths.py`：数据根单一入口 `trimum_home()`（`TRIMUM_HOME` 可覆盖），
  子目录清单含 `identity` / `agent-skills`；为多用户「每用户一份 root」与 `/etc/trimum` 预留改点
- [x] `src/trimum_core/hosts.py`：14 个已知宿主 + 三路探测（`TRIMUM_HOSTS` / `TRIMUM_HOSTS_DISABLE` 强制与排除、
  配置目录 `~/.claude` 等存在、PATH 上的 CLI）；`TRIMUM_HOSTS_HOME` 可重定向扫描根（测试 / 镜像构建用）
- [x] `src/trimum_core/identity.py`：Ed25519 用户密钥对 + 自签身份文档（绑 `machine_id` + user，
  `capabilities = {tools, max_risk, expires_at, scope}`，`max_risk` 只能收紧）；`cryptography` 缺失时
  `status=skipped` 且不写半成品；`agent_cert.machine_id()` 作为公开取用口
- [x] `src/trimum_core/setup_wizard.py`：四步向导 `hosts / identity / toolchain / skills`，
  `--dry-run` 不落盘、非交互不提示、状态写 `~/.trimum/config/setup.json5`
- [x] `config/setup-catalog.yaml`：选装工具链目录（7 组 25 项，含 pacman / apt / winget 包名；
  第三方 coding agent 标 `kind: agent`，注明「trimum 不依赖」）；**只登记不安装**，安装留给 E3
- [x] `trm setup` 命令（`--dry-run|--yes|--tools a,b|--all-hosts|--skip STEP|--max-risk|--catalog|--force-identity`）；
  `trm install --setup` 复用同一向导，`trm install <name>` 的官方包语义留给 E5
- [x] `skill_sync.default_target_roots()`：目标根**按探测结果决定**（不再硬编码 7 个），
  `~/.trimum/agent-skills` 恒为兜底；`trm skill list/sync/paths` 新增 `--all-hosts`（全量预置模式）
- [x] 测试：`tests/test_hosts.py`（13）+ `tests/test_setup_wizard.py`（29）+ `TestDynamicTargets`（5）

### 验证

- 全量：`pytest tests -q --basetemp tmp/pytest-tmp -p no:cacheprovider` → **566 passed / 8 failed / 4 skipped**；
  8 项失败与既有基线逐条一致（Windows `~/.trimum` 权限 + LLM 断网），**无回归**（上一轮 519 passed，+47 为本轮新增）
- smoke：`trm commands --check` → `ok: 50 commands checked, no problems`（新增 `setup`）；
  `trm setup --dry-run --yes --json` 各步输出正常且**未落盘**；沙箱真实跑（`TRIMUM_HOME` + `TRIMUM_HOSTS_HOME` 指向临时目录）
  生成身份密钥对 / 身份文档 / 状态文件，并把技能链接进「探测到的宿主 + 自己的根」
- 本机实测探测结果：`agents, claude, codex, gemini, cursor, openclaw` 六个宿主存在
  （`~/.pi`、`~/.hermes`、`~/.opencode` 等未装 → 不再被写入）

### 遗留

- [ ] 证书 `capabilities` 与 ToolGateway / `security_rule.py` 的**运行时合并尚未接线**：当前身份证书只作身份锚点 + 登记，
  不参与执行判定（属 E5 范畴，接线前不要对外宣称「证书限制工具」已生效）
- [ ] `trm env inventory` / `trm env install`（E3）仍缺：目录已备好，但「探测已装软件 + 调包管理器装」未实现
- [ ] `trm setup` 尚未在 Linux 真机上跑过（等 Ubuntu 开机）

---

## 2026-09-20 文档清理（过期 / 重复 / 垃圾）

> 原则：**STATUS.md 保留全部历史**（开发流程有纪念意义），只清除其它过期与重复内容；
> 删除的正文仍可从 `git log` 取回。

### 已删除（tracked）

| 文件 | 原因 |
|---|---|
| `docs/ARCH.md` | 与根 `ARCH.md` 重复，且旧 |
| `docs/STATUS.md` | 与根 `STATUS.md` 重复，且旧 |
| `docs/ARCHITECTURE.md` | 旧版整体架构（v5.0，2026-09-01），已被根 `ARCH.md` 取代 |
| `docs/DEVELOPMENT-ROADMAP.md` | 旧路线图（2026-09-02），已被 `TODO.md` / `STATUS.md` 取代 |
| `docs/PHASE3-4-PLAN.md` | Phase 3 已收尾，计划过期 |
| `docs/ECOSYSTEM-COMPARISON.md` | 竞品分析（2026-09-01），已被 `docs/ECOSYSTEM-STRATEGY.md` 取代 |
| `docs/REFERENCE-PROJECTS.md` / `docs/REFERENCE-AUDIT.md` | 早期参考项目调研与对照审计，结论已落地 |
| `docs/REUSE-STRATEGY.md` | Phase 2 状况快照，过期 |
| `docs/PYDANTIC-AI-COMPARISON.md` | 早期对比调研，选型已定 |
| `docs/DEEPSEEK-ADVICE-REVIEW.md` / `docs/建议_原始.md` | 外部建议审核稿，原始件已无追溯价值 |
| `docs/TECHNICAL-BOM.md` | 技术选型 BOM，已被 `ARCH.md`「技术选型」+ `pyproject.toml` 取代 |
| `docs/INTEGRATION-PLAN-BROWSER.md` | CLI-Anything `browser` 方案已被调研否决；有效结论移入 `docs/CLI-ANYTHING-RESEARCH.md` 与 `ARCH.md`「浏览器工具」 |

### 已删除（未跟踪 / 垃圾）

`HANDOFF.md`（含错拼、已过期）、`codex_out_memory.log`、`codex-tasks/browser-tool-debug/` 下的
`boot.log` / `runtime.log` / `stderr.log` / `stdout.log` / `__pycache__`（保留 `FINDINGS.md` 与 `patched-home/*.py`）。

### 同时修正

- `ARCH.md` 顶部悬空引用（原指向已删除的 `docs/ARCHITECTURE.md` / `docs/ARCH.md`）
- `PRD.md` 验收标准中的 `docs/INTEGRATION-PLAN-BROWSER.md` 引用改为 `docs/ECOSYSTEM-STRATEGY.md`
- `pyproject.toml`：`cryptography>=42` 转为正式依赖（身份密钥对与未来签名校验都要用；缺失时的优雅降级与测试保留）

### 追加（同日）：官方 Agent 证书 + 依赖

- [x] **trimum 自己开发的 Agent 全部是官方 Agent** → 一律走官方证书（`cert_type=official` / `issued_by=trimum` /
  `scope=official`），**免用户确认**；`agent_cert.discover_bundled_agents()` 从 `<repo>/agents` + `/opt/trimum/agents`
  发现官方 Agent（不含 `~/.trimum/agents`，那里是用户拷入的第三方 Agent），`ensure_official_certs()` 幂等签发
- [x] `AgentCert` 新增 `capabilities`（`{tools, max_risk, expires_at, scope}`）—— 证书携带「可以动用哪些工具」，
  旧证书缺字段按空处理（向后兼容，有测试）
- [x] `trm setup` 步骤变为 `hosts → identity → official → toolchain → skills`；`--skip official` 可跳过
- [x] `agent_cert` 的 `certs/` `agents/` 目录改走 `paths.trimum_home()`（`TRIMUM_HOME` 可覆盖，默认 `~/.trimum` 不变）
- [x] `pyproject.toml`：**`cryptography>=42` 转为正式依赖**（身份密钥对 + 未来签名校验都需要；缺失时的优雅降级路径与测试保留）
- 测试：`tests/test_agent_cert.py` 新增 `TestCapabilities` / `TestOfficialAgents`（11 项），
  `tests/test_setup_wizard.py` 新增 `TestOfficialStep`（4 项）
---

## 2026-09-20 E3：环境层（`trm env` —— 选装工具链的清单 / 计划 / 安装）

> 生态四层的 **L0**（`docs/ECOSYSTEM-STRATEGY.md` §3）。定位：**软件生态交给发行版** ——
> trimum 不自建包仓库，只回答「机器上有什么 / 能不能装 / 装的时候会执行什么」。
> 与 E6 的分工：`trm setup` **只登记选装**，安装是显式动作（`trm env install`），两者共用 `config/setup-catalog.yaml`。

### 交付

- [x] `src/trimum_core/env_toolchain.py`：9 个已知包管理器（pacman / apt / dnf / zypper / apk / brew / winget / scoop / mise），
  每个声明「探测 / 列举已装 / 安装」三条命令 + 是否需要 sudo + 适用平台；`mise` 只探测登记、**不代装**（运行时版本管理交给它自己）
- [x] 只读探测链：`detect_managers()`（`which` + `--version`，探针异常不致命）→ `query_installed()` → `parse_installed()` →
  `inventory()`（管理器现状 + 目录覆盖 + `trm setup` 的选装记录）
- [x] 计划与执行分离：`plan_install()` 产出**确切命令**与 `already_installed` / `unavailable` / `unknown` 三类清单；
  `commands_for()` 决定调用次数（winget 一包一条）；`run_install()` 是唯一执行点
- [x] `trm env inventory [--manager] [--catalog]`（**risk: low**，只读）与
  `trm env install <name>... [--manager|--dry-run|--yes|--catalog]`（**risk: high，requires_sudo**）
- [x] 测试：`tests/test_env_toolchain.py`（34 项：探测 / 解析 / 计划 / 执行 / 清单 / CLI）

### 本轮修掉的问题（测试暴露 → 代码修正）

| 问题 | 处置 |
|---|---|
| winget 列表用 `split()[1]` 取 ID → 包名含空格时取到版本号 | 改为**按列对齐切分**（列间 ≥2 空格）取 `Id` 列 |
| `sudo` 前缀依赖 `os.name == "posix"` → Windows 上计划里没有 sudo，跨平台行为不一致 | 改为「管理器需要 sudo 且当前不是 root」；显式 `use_sudo=` 优先 |
| `trm env install` 先探测一次、`inventory()` 内部再探测一次（同一命令探测两遍） | `inventory(statuses=...)` 复用调用方结果；新增测试断言只探测一次 |
| 已装条目仍会弹「将执行 0 条命令，确定继续？」 | 无待执行命令时不再询问；已装 → **幂等成功**（退出码 0） |
| 测试自身两处 bug：CLI 用例没请求 `fake_env` fixture（打到了真实环境）；apt 探针写 `which_only("apt")`（实际二进制是 `apt-get`） | 修正测试，不改代码语义 |

### 验证

- `python -m pytest tests/test_env_toolchain.py -q --basetemp tmp/pytest-tmp -p no:cacheprovider` → **34 passed**
- 全量：`pytest tests -q --basetemp tmp/pytest-tmp -p no:cacheprovider` → **614 passed / 8 failed / 4 skipped**；
  8 项失败与既有基线逐条一致（Windows 沙箱写 `C:\Users\...\.trimum` 被拒 + LLM 断网），**无回归**（上一轮 580 passed，+34 为本轮新增）
- `trm commands --check` → `ok: 53 commands checked, no problems`（新增 `env` / `env inventory` / `env install`）
- 本机（Windows）实测：`trm env inventory` 正常列出 9 个管理器现状与 25 项目录覆盖
  （本机无包管理器 → 全部 `not installed`，符合预期）

### 遗留

- [ ] `trm env install` 未在 Linux 真机（pacman / apt）实跑（等 Ubuntu 开机）；winget 列解析有单测但未对真实 `winget list` 输出冒烟
- [ ] 目录条目与包名的对应靠人工维护（`config/setup-catalog.yaml`），未做「装完回读验证该软件真的可用」
- [ ] `trm setup` 选装后不会自动安装（有意为之）；后续可在向导末尾提示「已选 N 项，运行 `trm env install`」
- [ ] `trm skill import`（E3 原定项之一）顺延到 E4（本轮只完成 env 部分）

### 文档同步

- `ARCH.md`：新增「环境层与工具链安装（E3）」章节（包管理器表 / 解析 / 单遍探测 / sudo 策略 / 安装红线）
- `PRD.md`：新增 E3 已交付；范围边界与验收标准改为「生态轮」口径（不再写「本轮只改文档」）
- `TODO.md`：E3 勾选（含遗留）、已完成表、测试状态表（614 passed）、分支同步表
- `docs/ECOSYSTEM-STRATEGY.md`：§4 缺口 1/2/5 标记已完成、§5 路线图标题改 E0-E7 且 E3 标记完成
---

## 2026-09-20 E2：MCP 接入（M0 设计冻结 + M1 stdio 客户端 + M2 注册/分发/审计）

> 生态四层的 **L1**（`docs/ECOSYSTEM-STRATEGY.md` §3）。此前 `MCPDispatcher` 是占位实现，
> 固定返回「MCP bridging not yet available」；本轮把它做成真的：**trimum 第一次有了跨进程的生态接入能力**。
> 方案与阶段划分：`docs/MCP-INTEGRATION-PLAN.md`（§2.3 记 M0 决议）。M3（策展导入器）/ M4（HTTP/SSE + 空闲回收 + cgroup）未做。

### 交付

- [x] `src/trimum_core/mcp_client.py`：stdio MCP 客户端 —— 子进程 + JSON-RPC 2.0 **换行分帧**，
  `connect` / `initialize` / `list_tools` / `call_tool` / `ping` / `close`；
  超时 / 非法 JSON / 提前 EOF 一律标记 broken（坏流不复用）；协议版本协商（服务器给旧版本则记录并告警）
- [x] `src/trimum_core/mcp_registry.py`：`~/.trimum/mcp/<name>.json5` → `MCPServerDefinition`
  （`TRIMUM_MCP_DIR` 可改目录）；`MCPRegistry` 加载并**上报坏文件为 problems**（不炸）；
  `MCPServerPool` 懒启动 / 按名复用 / 坏连接重建 / `close_all`
- [x] `tool_dispatchers.MCPDispatcher` 实装：`mcp.tools.list [server]`（空 = 所有已启用）、
  `mcp.tools.call <server> <tool> [json-arguments]`；输出 JSON；调用失败/工具报错区分（`status=error` 带结构化详情）
- [x] `tool_gateway` 回填审计：构造完成后把 `audit_store` / `event_bus` 交给 MCP 分发器（`bind_audit`），
  其余分发器不受影响
- [x] `trm mcp list/tools/call/paths`（`cli/commands/mcp.py`）：与网关**共用同一个 dispatcher**，不是第二套实现
- [x] 测试：`tests/fixtures/mcp_echo_server.py`（真协议 stdio server）+ `tests/test_mcp_client.py`（16）
  + `tests/test_mcp_registry.py`（27）+ `tests/test_mcp_dispatcher.py`（30）

### M0 决议（摘要，全文见方案 §2.3）

| 问题 | 决议 |
|---|---|
| 自研 client vs 复用 openai-agents MCP | **自研最小 client**：stdio 分帧就是「一行一个 JSON-RPC 2.0」，asyncio 足够；引 SDK 会把 Agent SDK 取舍绑进协议层（接口留好，将来只换 transport） |
| 首批用例 | ① 本机能力接入（uvx 类本地 server）② 远程 SaaS 受控通道（`trust: cloud`）③ 一行文件零代码扩能力 |
| 传输范围 | M2 只做 stdio；`transport: http` 明确报「M4 未实现」，不假装能用 |
| 工具聚合进 `ToolRegistry` | 顺延 M3（`ToolRegistry` 是静态 `ToolDefinition` 表，动态工具需要新机制）；M2 由 `mcp.tools.list` 提供运行时枚举 |
| 安全默认 | deny-by-default（`enabled` 缺省 false）；`allow_tools`/`deny_tools` glob（deny 优先）；`trust: cloud` 额外继承 `*delete*` `*exec*` `*shell*` `*eval*` 等默认黑名单；**参数值不入审计** |

### 本轮修掉的缺陷（测试/实测暴露）

| 缺陷 | 处置 |
|---|---|
| **`trm --json` 的 stdout 被日志污染**：`trm --json mcp call ...` 会把 `mcp_registry.loaded` / `mcp.started` / `mcp.audit` 三行打在 JSON 前面（实测确认），任何「库里有 INFO 日志」的命令都会中招 | CLI 入口把 structlog **诊断路由到 stderr**（`logger.setup_cli_logging()`），stdout 只留载荷；实测重跑后 stdout 为纯 JSON |
| CLI 跑完不关 MCP 服务器：子进程遗留 + Windows 上 `Event loop is closed` 噪声 | CLI 把 `execute` 与 `dispatcher.close()` 放进同一个协程（`_run_once`），实测噪声消失 |
| `MCPServerPool.client(refresh=True)` 泄漏旧客户端（进程不关） | 改为先丢弃旧连接再建新的（测试 `test_refresh_forces_a_new_client` 覆盖） |
| 被策略 deny 的 MCP 调用**没有留痕** | deny 路径补 `mcp_call` 审计（`action=denied`、`duration_ms=0`），且断言不会拉起任何服务器 |
| 测试助手生成的 json5 非法（Python repr 的 `True` / 单引号转义） | 改用 `json.dumps`（JSON 是 JSON5 的子集） |

### 验证

- `python -m pytest tests/test_mcp_client.py tests/test_mcp_registry.py tests/test_mcp_dispatcher.py -q` → **73 passed**
  （真协议 fixture server，覆盖握手 / 工具列表 / 调用 / isError / 远端错误 / 超时 / 服务器秒退 / 命令缺失 /
  带外通知 / stderr 落文件 / 注册加载与坏文件 / 白黑名单 / 连接池复用与重建 / 审计 / CLI）
- 全量：`pytest tests -q --basetemp tmp/pytest-tmp -p no:cacheprovider` → **687 passed / 8 failed / 4 skipped**；
  8 项与既有基线逐条一致（沙箱写 `~/.trimum` 被拒 + LLM 断网），**无回归**（上一轮 614 passed，+73 为本轮新增）
- `trm commands --check` → `ok: 58 commands checked, no problems`（新增 `mcp` / `mcp list` / `mcp tools` / `mcp call` / `mcp paths`）
- 端到端实测（临时 `TRIMUM_MCP_DIR` + 真 fixture server）：`trm mcp list` 显示定义与状态；
  `trm mcp tools echo` 列出 4 个工具；`trm --json mcp call echo echo '{"text": "x"}' --yes` 输出**纯 JSON**（`text: "echo: x"`）

### 遗留

- [ ] **M3 策展导入器**：`tmp/research/awesome-README.md`（4,117 条）→ `config/mcp-catalog.yaml` 候选清单（人工审核后才启用）；
  筛选红线仍待执行：优先 `uvx` / `pip install` / 单二进制，`npx` 派系默认不收（Node 回流风险）
- [ ] **M4 HTTP/SSE 传输 + 空闲回收（`idle_ttl` 已在定义里但未生效）+ cgroup 绑定 + `trm mcp status/restart`**
- [ ] **真实第三方 server 冒烟未做**：本轮用自建 fixture server 覆盖协议；沙箱内无法 `uvx`/联网，未对发布版
  `mcp-server-*` 做端到端验证（等能联网的环境）
- [ ] **工具聚合**（`<server>__<tool>` 注册进 `ToolRegistry`）未做：Agent 目前需先 `mcp.tools.list` 再 `mcp.tools.call`
- [ ] `trm mcp` 未在 Linux 真机验证（等 Ubuntu 开机）；MCP 服务器进程的 cgroup 归属尚无约束

### 文档同步

- `docs/MCP-INTEGRATION-PLAN.md`：新增 §2.1/2.2/2.3（E2 前后对照、M0 决议），M0/M1/M2 标记完成
- `ARCH.md`：新增「MCP 接入（E2）」章节（模块表 / 关键设计 / 审计 / CLI 输出契约）
- `PRD.md`：新增 E2 已交付
- `TODO.md`：E2 与 M0/M1/M2 勾选、遗留（M3/M4）、测试状态改 687、已完成表与覆盖清单
- `docs/ECOSYSTEM-STRATEGY.md`：§3 L1、§4 缺口 3、§5 路线图 E2 标记完成
