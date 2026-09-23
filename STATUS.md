# STATUS — 当前进度

> 工作流（2026-09-22 起）：本文件 = **常驻区（就地小改）+ 追加日志（只增不改）**。
> - 顶部「当前状态 / 任务清单 / 决策记录 / 下一步」为**常驻区**，随进展就地小改。
> - 底部「## 日志」按日期**从旧到新**；新进展**只追加到文件最末尾**，不回填、不通读全文。
> - 日常只需读「当前状态」+ 最新一条日志即可定位；历史细节按需翻对应日期条目。

## 当前状态（就地更新，只改这几行）

- **阶段**：Phase 3 收尾已完成（P0/P1 阻断项清零，真机 Ubuntu 验证通过）。主线转 **E7 自研编码智能体** + **沙箱**（E7 前置，S1/S2/S3 已落地）。
- **分支**：`server`，**已与 `origin/server` 同步**（`efe2885` ask --image + `01819e9` memory 于 2026-09-22 22:11 推送；本轮文档提交紧随其后）；`main` / `ubuntu` / `arch-linux` 里程碑收尾时同步（推送前先开代理 `127.0.0.1:7993`）。
- **测试基线**：本地 **1664 passed / 6 failed / 23 skipped**（09-22 `trm memory import/export` 之后；6 条失败 = 既有宿主基线，零回归）。
- **沙箱**：S1 系统级加固（真机已 `apply` 在位）/ S2 施加点收口（`sandbox_exec`，7 个 spawn 点，fail-closed）/ S3 seccomp 三档（真机验收 35/0）；**TCP 已收口**（`trm status` → `http: disabled` + `ipc socket: ok`，全机 8321 无监听）。
- **真机访问**：主 = `vscode.dev/tunnel/tianyi`；备 = **T2 Tailscale**（`http://100.115.86.48:8080/`）。两者都已是 **systemd user service**（`trimum-tunnel` / `trimum-web`），`status`=Connected、web=200；域名/frp 方案**已废弃**。另有 `trimum-mihomo`（本机 Clash 核，待机场订阅）。**重启后自启只差 `loginctl enable-linger guzhujushi`（待本人 sudo）**。
- **下一步**：E7 待裁决两条（沙箱是否提前 / 首发是否允许自动改盘+自动跑测试）后开工；沙箱剩真机 4 条命令对照（`docs/SANDBOX-PLAN.md` §10.6，本人 sudo）+ 开发树整树同步。详见「下一步」与 `TODO.md`；本轮已按「模型分工」把待办切成 【Qwen】/【DS】/【本人】 三列（Qwen 任务附提示词）。
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
| 2026-09-22 | `TODO.md` 只留未闭环待办 + 红线；已完成历史进 `STATUS.md`（追加式日志，只增不改） | 两文件曾各自维护「已完成」表，重复且互相漂移 |
| 2026-09-22 | Codex 侧模型分工：【Qwen】交我算（免费，单次小任务）/【DS】deepseek-flash（复杂件）/【本人】需 sudo 或产品决策 | 交我算 10 次/分，Codex 一个 turn 十几次调用必撞 429；跑法与证据见 `docs/CODEX-MODEL-POLICY.md` |
| 2026-09-22 | E7 参考对象由 ECC 改为 **aider** | ECC 不是运行时（自己就是宿主插件，格式对不上 trimum 子 Agent）；可直接复用的只有 `python-unidiff` / `grep-ast` |

---

## 下一步（优先级排序）

> 2026-09-20 二次重写：E4 / W1 闭环 + EventBus 审计之后，按「哪个缺口让已有能力变成摆设」重排。
> 更早的 2026-09-01 旧清单里多数项已完成或已废弃 —— SafeMind 红蓝对抗（仓库内无 `safe_lab.py` / `red_team.py`，从未动工）、
> OpenCLI 桥接（已弃用）、CLI 流式输出（已实现）、`tmp/` 清理（已完成）、`src/trimum-mvp/`（已删除）、
> 「296/297 pass 修 AuditEvent 导出」（已被本地 1156 passed 取代）。

1. ✅ **P0 安全响应链接线**（2026-09-20 审计新立，**2026-09-21 闭环**）—— L4 只拦不报 → 现在「扫描 → 广播（扁平载荷）→ SecExecutor（审计/通知/阻断）→ 网关处置（deny/kill/freeze/isolate → 拒绝，confirm → 确认）→ 剧本被 `security.monitor_result` 驱动」一条链全通，且**任何入口**的网关都过 L4。四个提交（统一契约 `087a476` → L4 走 `inspect()` `d5393a6` → 装配/处置/签名 `dbc411e` → 定 `workflow.trigger` 归属 `f6ecfe4`）见本文件「2026-09-21 P0 步骤 1/3 ~ 3/3」三条日志
2. 🟠 **E5 官方分发渠道**（分发面已闭环，剩第三片）—— 第一片 `9b40be2`（`.trmpkg` 包格式 + 校验器）；第二片 `2aec23b` → `4e29b4e`（`trm pkg` CLI + 真实内置根 + `trmindex/1` 签名目录索引 + `trm install` 接线 + E6 遗留的证书 `capabilities` 运行期交集）。剩：`trm install --remove`（卸载 + 注销登记）、官网服务端与目录托管（`DEFAULT_INDEX_URL` 仍是占位）、多用户边界（`docs/ECOSYSTEM-STRATEGY.md` §7.2）；**第三片三步骤已完工**（步骤 1 卸载 `d7aced2` / 步骤 2 发布方闭环 / 步骤 3 多用户边界，见本文件 2026-09-21 同名日志），剩余项见 `TODO.md`「P2 杂项」
3. ✅ **总线硬化**（2026-09-21 完成，穿插项步骤 B，见上）—— `_safe_call` 不再吞异常（计数 + 广播 `event.eventbus.dispatch_failed` + 严格模式抛 `TRM-9005`）；`EventIndex` 接进 `EventBus.publish`；`LiveConsole.subscribe_events` 改按段匹配并补订 `security.*`；SDK 侧 `publish(...)` 误用改 `emit_event(...)`
4. ✅ **W1 遗留：`WorkflowListener` / TARL 三段式接线**（2026-09-21 完成，穿插项步骤 C）—— `submit()` 成了 `event.transform.completed` 的唯一生产者，daemon 启动即装配，CLI 入口 `trm workflow submit`；确认缺位由「默认放行」改成**拒绝**；另修了两个真 bug（日志器当 structlog 用 / `ExecuteRequest` 字段名全错）。**仍留**：运行记录只在内存（环形 200 条，重启即丢）、内置剧本只有落盘式开关、确认通道目前只有 CLI
5. 🟡 **桌面/WebSocket 确认通道**（P2）—— `SecurityAgent.confirm()` 目前只有 CLI 交付手段
6. 🟡 **CLI 小缺口三连** —— `trm security revoke <token_id>` / `trm ask -i` 的中断处理（`ask.py` 无 `KeyboardInterrupt` / `EOFError`）/ `trm memory import|export`
7. 🟡 **引擎侧两个半成品** —— `src/agent-sdk` 端到端测试与打包验证（`tests/` 无覆盖）；Policy Engine 正则→LLM 混合（`LlmPolicyEngine` 骨架未接线）；`transform_agent` 的 confidence 三级分流
8. 🟢 **SonarQube 重扫** / **daemon 部署形态二选一**（`trmd.service` root 或用户态路径）
9. ⏸️ **未开工子系统**（别误判为 bug）—— eBPF 告警 `security.ebpf_alert`、性能熔断 `security.fuse_triggered`、审计断链检测 `security.audit_breach`（`SecAudit.verify_chain()` 已实现但无人调用）
10. 🅿️ **E7 自研编码智能体** —— 规格与设计已出（`docs/CODING-AGENT-PLAN.md`，2026-09-21），**待裁决两条**（沙箱是否提前 / 首发是否允许自动改盘 + 自动跑测试）后按五步分片落地。前置调研已完成（`docs/CODING-AGENT-REUSE-RESEARCH.md`，2026-09-21）：**ECC 不适合做成 coding Agent**（它不是运行时，自己就是宿主插件；格式对不上 trimum 子 Agent），**参考对象建议改为 aider**，可直接复用的只有 `python-unidiff` / `grep-ast`；调研原始件 `tmp/research/ecosystem/ecc-*` + `tmp/research/coding-agents/`

---


## 日志（追加区：按日期从旧到新，只增不改 —— 新条目加到文件最末尾）
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
- [x] 真机 venv 依赖已齐（2026-09-20：`pytest` / `pytest-asyncio` / `rich` 已在；补装包依赖 `cryptography-50.0.1`，两份 venv 均属 guzhujushi，无需 sudo）
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
- [ ] 待办：`/opt/trimum` 的 sudo 同步（脚本 `scripts/sync_opt_tree.sh` 已投送到真机 `/tmp`，等用户执行）、`trm ask` 真机 TTY 验证、Arch Linux smoke、SonarQube 重扫

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
- [x] `trm setup` 已在 Linux 真机跑通（2026-09-20：33 项测试全绿，含真实 Ed25519 keystore 生成）；手工交互式首启仍未做过

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
- [x] `trm mcp` 已在 Linux 真机跑通测试（2026-09-20：client / registry / dispatcher 共 73 项全绿）；手工 `trm mcp call` 真机冒烟未做；MCP 服务器进程的 cgroup 归属尚无约束

### 文档同步

- `docs/MCP-INTEGRATION-PLAN.md`：新增 §2.1/2.2/2.3（E2 前后对照、M0 决议），M0/M1/M2 标记完成
- `ARCH.md`：新增「MCP 接入（E2）」章节（模块表 / 关键设计 / 审计 / CLI 输出契约）
- `PRD.md`：新增 E2 已交付
- `TODO.md`：E2 与 M0/M1/M2 勾选、遗留（M3/M4）、测试状态改 687、已完成表与覆盖清单
- `docs/ECOSYSTEM-STRATEGY.md`：§3 L1、§4 缺口 3、§5 路线图 E2 标记完成

---

## 2026-09-20 M3：策展导入器（awesome-mcp-servers → `config/mcp-catalog.yaml`）

> 依据：`docs/MCP-INTEGRATION-PLAN.md` §3（条目解析规则）/ §5 姿势 B（策展导入器）/ §6 M3。
> 定位：把 4,118 条上游 README 压成一份**候选清单**，让人只审「能用的那一小撮」；
> 导入器本身不启用任何 server、不写 `~/.trimum/mcp/`、不联网。**纯离线完成，未用真机。**

### 任务清单（全部完成）

- [x] 解析器：README 行 → 条目（repo / url / 语言 / 范围 / 系统 / 官方 / 描述 / 安装线索）
- [x] 分类器：语言 + 分发方式（uvx / uv / pip / go / cargo / docker / npx / …）+ 红线过滤
- [x] 产物：`config/mcp-catalog.yaml`（按分类分组、`reviewed: false`、确定性输出、可复跑）
- [x] CLI：`trm mcp catalog import|list` + 命令元数据（`trm commands --check` 61 条通过）
- [x] 测试：`tests/test_mcp_catalog.py`（52，离线 fixture + 真实快照）
- [x] 文档：`docs/MCP-INTEGRATION-PLAN.md` §5.1/§6、`ARCH.md`、`PRD.md`、`TODO.md`、`docs/ECOSYSTEM-STRATEGY.md` 同步

### 交付

| 文件 | 内容 |
|---|---|
| `src/trimum_core/mcp_catalog.py` | 解析 → 分类 → 红线筛选 → 渲染；`parse_readme` / `select_candidates` / `with_names` / `merge_review_state` / `render_catalog` / `write_catalog` / `load_catalog` / `import_catalog` |
| `config/mcp-catalog.yaml` | 232 条候选 / 39 个分类 / 151 KB；`generated_from` 记相对路径，**无时间戳**（可 diff） |
| `src/trimum_core/cli/commands/mcp.py` | `trm mcp catalog import`（`--dry-run` / `--force` / `--limit` / `--category` / `--include-npx` / `--all-languages` / `--include-unknown-dist`）、`trm mcp catalog list`（`--unreviewed` / `--category` / `--dist` / `--lang`） |
| `tests/test_mcp_catalog.py` | 52 项；`tests/fixtures/awesome-mcp-sample.md` 为离线 fixture |

### 实测数据（2026-09-20 快照）

| 分档 | 条数 |
|---|---|
| 上游 README 条目 | 4,118 |
| **候选** | **232**（uvx 104 / pip 110 / cargo 10 / docker 5 / go 2 / uv 1；本地 170 / 云端 62） |
| 拦下 · 语言 | 2,480（ts 2,219 / unknown 197 / java 29 / csharp 28 / c_cpp 5 / ruby 2） |
| 拦下 · `dist:unknown`（描述里没有安装方式） | 1,356 |
| 拦下 · Node 派系 | 16（npx 14 / npm 2） |
| 拦下 · 其他分发 | 7（brew） |
| 拦下 · 不在 `Server Implementations` 小节 | 27 |

> 不变量：`parsed == candidates + Σ excluded`（4,118 = 232 + 3,886），测试断言。

### 本轮修掉的缺陷（冒烟 / 测试暴露）

| 缺陷 | 处置 |
|---|---|
| **Windows 标记码点写错**：图例里的 🪟 是 U+1FA9F，代码里写成 U+1FAA9 → `systems` 丢 windows、`no-linux` 误判 | 逐图例比对码点后修正（其余 15 个标记核对无误）；断言覆盖 `systems == (macos, windows, linux)` |
| **分类标题解析错位**：真实标题是 `### 🔗 <a name="..."></a>Label`（emoji 在锚点前），只按「锚点在最前」解析时把 `<a name=...>` 当成了标签 | 改为整行搜索锚点，锚点之后的文字才算标签（`_subsection_heading`） |
| **安装线索取到 flag**：`uvx --from git+… pkg` → `uvx --from`；`go install x` → `go x` | 新增 `_package_token`（按分发的 value-flag 表跳过参数）+ 每分发独立渲染（`go install x` / `cargo install x` / `docker run <image>`） |
| CLI `list` 显示绝对路径、长名字撑破表格 | 统一走 `display_path`；显示层截断 30 字符（数据不动） |
| 测试设计陷阱：用「TS + npx」的条目测不出 `dist:npx`（拒绝顺序是 语言 → 分发） | fixture 补一条「python + npx」条目，红线两条各自可独立观察到 |

### 验证

- `python -m pytest tests/test_mcp_catalog.py -q` → **52 passed**
- 全量：`pytest tests -q --basetemp tmp/pytest-tmp -p no:cacheprovider` → **739 passed / 8 failed / 4 skipped**
  （基线 687/8/4，+52 即本轮新增；8 项与基线**同源**：沙箱写 `~/.trimum` 被拒（PermissionError）+ PATH 缺 `python.exe` + LLM 断网，**无回归**）
- `trm commands --check` → `ok: 61 commands checked, no problems`（新增 `mcp catalog`、`mcp catalog import`、`mcp catalog list`）
- 端到端（本机真实快照）：`import --dry-run` 只报数不落盘 → `import` 写出 151 KB → `list --unreviewed --category file-systems --dist uvx` 可筛 → `--json` 输出纯 JSON
- 保护行为：已有清单时 `import` 被拒并提示 `--force`；`--force` 重导入后人工写的 `reviewed` / `note` 仍在（测试断言）

### 遗留

- [x] **M4**：HTTP/SSE 传输、`idle_ttl` 空闲回收、`apply_cgroup(pid)`、`trm mcp status/restart`、`docs/OPERATIONS.md` 补 MCP 章节（见文末「M4 传输与生命周期」）
- [x] **工具聚合**：远端工具注册进 `ToolRegistry`（`<server>__<tool>`），Agent 不必先 `mcp.tools.list` 再 `mcp.tools.call`（M4.5，见文末）
- [ ] **人工审核尚未开始**：232 条候选 `reviewed` 全为 false（设计如此，不是缺陷）；§2.3 的首批「非它不可」用例还没落到 `~/.trimum/mcp/`
- [x] 真机已跑（2026-09-20：739 passed / 11 failed / 2 skipped，11 项为宿主状态基线，无回归；见文末「M3 真机验证 + 两处真实缺陷修复」）

### 文档同步

- `docs/MCP-INTEGRATION-PLAN.md`：新增 **§5.1 导入器用法与审核流程**（含实测分档表）；§6 的 M3 标 ✅
- `ARCH.md`：新增「MCP 策展导入器（M3）」章节（模块 / 关键设计）
- `PRD.md`：新增「已交付（M3）」；修正范围边界里过期的「MCP 只出方案不写实现」
- `TODO.md`：M3 勾选 + 继续指针改为 M4 + 测试状态 739 + 覆盖清单
- `docs/ECOSYSTEM-STRATEGY.md`：L1 与路线图 E2 行补 M3 ✅
---

## M3 真机验证 + 两处真实缺陷修复（2026-09-20）

### 同步与验证
- 打包：`git archive HEAD -o tmp/trimum-sync.tar`（2,078,720 B）→ `scp` 到真机 `/tmp/` →
  `cd /home/guzhujushi/trimum && tar -xf /tmp/trimum-sync.tar`（`src/` 为 root 属主，报 `utime` / 改模式
  的非致命错，内容已逐文件校验落地）
- 真机全量：**739 passed / 11 failed / 2 skipped**（27s）
  - 对照同步前真机 **483 passed / 11 failed**：用例总数 494 → 752 的增量来自补进真机的 E 系列 / M3 测试文件，不是回归
  - 11 项失败与同步前**同一批**宿主状态缺失：`test_depends_on`(1)、`test_llm_integration`(1，无 Key)、
    `test_other_dispatchers::TestEnvDispatcher::test_env_list_sorted`(1，宿主 env 有非 `KEY=VALUE` 行)、
    `test_skill_integration`(7，缺 `~/.trimum/skills/hello-world`)、
    `test_tool_file_loading::test_get_executor_exists`(1，缺 `~/.trimum/tools/mcp`) → **无回归**
- 意义：M2 的 MCP stdio 路径（client / registry / dispatcher 共 73 项）与 M3 导入器（52 项）在 Linux 上全绿；
  `trm setup` 的 33 项（含真实 Ed25519 keystore 生成）也在真机跑通

### 真机暴露并修掉的两个真缺陷

| 现象 | 根因 | 修法 |
|---|---|---|
| `test_setup_wizard::test_dry_run_json` 报 `JSONDecodeError: Extra data` | `cli/commands/setup.py:182` 把「身份步骤被跳过」提示打到 **stdout**，JSON 之后多一行 | 改 `file=sys.stderr`（与 M2「`--json` 只输出 JSON」同一契约）；补回归测试 `test_skipped_identity_note_keeps_stdout_json_clean` |
| `test_mcp_dispatcher::TestAudit` 的「参数值不入审计」断言失败 | 测试拿 `"hi"` 当哨兵，而审计事件里的 `config_path`（tmp_path）含用户名 `guzhujushi` —— `s…h-i` 撞串 | 哨兵改为 `argument-value-must-not-be-audited`（不会撞路径） |
| 另有 6 项 `TestIdentity` 失败 | 包依赖 `cryptography`（`pyproject.toml` 已声明）在真机 venv 缺失，身份步骤返回 `skipped` | 两份 venv（`.venv`、`/opt/trimum/venv`）补装 `cryptography-50.0.1`（属主是 guzhujushi，无需 sudo） |

### 待用户执行（sudo，脚本已投送）
- `/tmp/sync_opt_tree.sh`（仓库副本 `scripts/sync_opt_tree.sh`）：把 `src/ config/ tests/ scripts/` 与顶层文档
  装进 `/opt/trimum`。现状（2026-09-20 实测）：`src/trimum_core` 缺 9 个模块、`cli/commands` 缺 5 个、`config/` 缺 5 个 yaml、`tests/` 少 9 个文件；
  `/opt/trimum/{config,tests,scripts}`、`src/trimum_core` 为 root:root，`tar` 直解会被拒
- 同步后以 guzhujushi 身份跑 `bash /home/guzhujushi/trimum/scripts/restart_trmd.sh`
  （**不要**用 sudo 起 daemon，否则 `~/.trimum` 会被 root 写脏）
- daemon 现状：PID 1359 以 guzhujushi 运行，`/run/trimum` 不存在 → IPC / `apply_cgroup` 降级（P2 项，未变）

### 部署期发现的运维问题（sudo 修复脚本已投送）
- `trmd.service` 处于崩溃重启循环：与手工 daemon 抢 `127.0.0.1:8321` → 每 5s 一次 `exit 3`（`[Errno 98] address already in use`），
  journal `NRestarts` 到 97；`pgrep` 因此会间歇看到第二个 `trimum_core.main` 进程。
- 连带的隐性故障：短命进程启动时会 unlink+bind `/run/user/1000/trimum.sock`，把运行中 daemon 的 RPC socket
  抢走再自杀 → `trm` 静默退回 HTTP（`trm status` 的 `source: http` 就是它）。
- 修复入口：`scripts/fix_trmd_loop.sh`（已 scp 到真机 `/tmp`）
  - `sudo bash /tmp/fix_trmd_loop.sh --check` 只看现状
  - `sudo bash /tmp/fix_trmd_loop.sh` 停用 systemd 单元、保留手工 daemon（之后以 guzhujushi 身份
    跑 `bash /home/guzhujushi/trimum/scripts/restart_trmd.sh` 拿回 socket）
  - `sudo bash /tmp/fix_trmd_loop.sh --use-systemd` 反过来：停手工 daemon，改由 systemd 托管

#### 处置结果（2026-09-20，已执行方案A）
- `trmd`：`disabled` + `inactive`，`NRestarts=0`，journal 停在 `Stopped trmd.service`；15:53 之后 `Errno 98` 计数 **0**
- daemon：单实例 PID 10429（手工起，以 guzhujushi 运行），同时持有 TCP `127.0.0.1:8321` 与 `/run/user/1000/trimum.sock`
- `trm status` 回到 **`source: rpc`**（RPC 通道恢复，之前静默降级成 http）
- smoke 全绿：`health` / `agent list` / `workflow list` / `mcp list` / `version` / `log audit --json`（90 行）/ `exec`（exit=0、输出回显、审计落盘）
- `/opt/trimum` 也补齐了：`src/agent-sdk/` 到位、`pyproject.toml` 含 `cryptography>=42`、`config/` 5 个 yaml

#### 代码侧加固（2026-09-20，TODO 里 4 条 P1）

| 问题 | 修复 | 回归测试 |
|---|---|---|
| 端口被占只抛 uvicorn `[Errno 98] address already in use`（systemd `Restart=always` 下变成每 5s 的崩溃循环） | `main.check_tcp_port()`（connect + bind 双探测）启动前预检；被占则打印「启动中止 —— TCP 127.0.0.1:8321 已被占用」并 `exit 3` | `tests/test_daemon_singleton.py::TestPortPrecheck` |
| `ipc_handler._start_unix_socket()` 先 `unlink` 再 `bind`，短命进程抢走运行中 daemon 的 socket（RPC 静默降级 HTTP 的根因） | 新增 `ipc_handler.socket_is_live()` 探针（`connect` 成功才算活）：有人在听则 `socket_held_by_other=True` 退让，不 unlink、不 bind；只有无人监听的 stale 文件才清理 | `test_ipc_listener.py::TestSocketTakeoverGuard` |
| `config.py` 把 socket 写死 `/run/user/1000/trimum.sock`（假设 uid=1000），客户端走 `XDG_RUNTIME_DIR` → 换 uid 两端对不上 | `config.default_socket_path()`：`XDG_RUNTIME_DIR` → `/run/user/<uid>` → 数据目录；`trimum_client.socket_candidates()` 与 daemon 同序，都不存在时返回 runtime dir 候选（不再退到数据目录） | `tests/test_socket_path_consistency.py` |
| `/health` 版本号自相矛盾：HTTP `0.2.0`（L203）vs IPC `0.2.1`（L122） | `api_server._core_version()` 统一取 `trimum_core.__version__`（0.5.0），HTTP / IPC / FastAPI metadata 三处同源 | `test_api_server_startup.py::TestHealthVersion` |
| （顺带）`Config.__init__` 只做 `dict(DEFAULT_CONFIG)` 浅拷贝，`set()` / yaml 合并会污染全局默认值，进程内后续 `Config()` 继承别人写的 `socket_path` | 改为 `copy.deepcopy(DEFAULT_CONFIG)` | `test_socket_path_consistency.py::test_config_instance_does_not_pollute_global_defaults` |

真机验证（Ubuntu 100.115.86.48，`/home/guzhujushi/trimum`）：

- **失败清单逐条比对**：回退到修复前（HEAD 版本）`11 failed / 739 passed / 2 skipped`，装回修复后 `11 failed / 755 passed / 2 skipped`，两个方向 `comm` 差异均为空 → 无回归（新增 16 项通过）
- **端口被占**：`trmd` → `exit=3`、`TCP 127.0.0.1:8321 已被占用（已有服务在监听）`（不再抛 `[Errno 98]`）
- **socket 被占**：`trmd --port 8322` → `exit=3`、`IPC socket /run/user/1000/trimum.sock 已被其它进程监听`；生产 daemon socket 的 `stat`（inode/mtime/size）前后完全一致 → **没被抢占**，daemon PID 10429 存活，`trm status` 仍 `source: rpc`
- **独立实例**：`8322 + 独立 socket/db` 正常启停；`/health` 的 HTTP 与 IPC 两条路都返回 `0.5.0`；SIGTERM 退出时清理自己的 socket
- 提交：server `2f6adbb` / main `2a80fb9` / ubuntu `9ecf111` / arch-linux `fe05347`（同一提交 cherry-pick，四分支内容一致）

**已部署 + 验收（2026-09-20 16:49，用户 sudo 执行）**：`sudo bash /tmp/sync_opt_singleton_fix.sh` → 补丁进 `/opt/trimum`（src + tests），daemon 以 guzhujushi 身份重启（PID 12271）。验收脚本 `/tmp/accept_singleton_fix.sh`：**9 PASS / 0 FAIL**

- 版本统一：HTTP `/health` = IPC `health` = `trimum_core.__version__` = `0.5.0`（`trm status` 亦从 `0.2.1` 变 `0.5.0`）
- `trmd`（同端口）→ `exit 3`「TCP 127.0.0.1:8321 已被占用（已有服务在监听）」；`trmd --port 8322` → `exit 3`「IPC socket /run/user/1000/trimum.sock 已被其它进程监听」；两次输出都不含裸 `Errno 98`
- socket `stat`（inode/mtime/size）前后一致 → 未被抢占；daemon 仍单实例，`trm status` 仍 `source: rpc`
- 冒烟：`health` / `version`（`trimum v0.5.0`）/ `agent list` / `workflow list` / `mcp list` / `log audit --json` / `exec`（回显 `trimum-acceptance-ok`）全通
- 故障复发检查：`trmd.service` `disabled` + `inactive`、`NRestarts=0`、daemon 起来后 `[Errno 98]` 计数 0
- 备注：`trm health` 打印的 `[MISSING] env API_KEY` 属本地宿主检查（该 shell 未导出 key），与本次改动无关

### 提交与分支
- server `209c98e` / main `e0ad16f` / ubuntu `3040b00` / arch-linux `9925c19`（同一提交 cherry-pick）

---

## M4 传输与生命周期（2026-09-20）

### 交付内容

| 子项 | 落点 | 测试 |
|---|---|---|
| `streamable-http` 传输 | `mcp_client.MCPHttpTransport` + `parse_sse_messages()`：JSON / SSE / 202 无回包 / 404 会话过期 / 超时 / 断连分类，`Mcp-Session-Id` 复用与协议版本回写 | `tests/test_mcp_http_transport.py`（29） |
| 空闲回收 | `MCPServerPool.reap/start_reaper/stop_reaper`，`idle_ttl` 默认 300s、`0` = 常驻，`clock` 可注入 | `tests/test_mcp_lifecycle.py`（18） |
| cgroup 绑定 | `_bind_cgroup()` + `_verify_cgroup()`（读回 `assigned_pids` 再报状态，不把「没报错」当成功）；`ResourceController.assigned_pids()` 默认实现 | 同上 |
| daemon 常驻池 | `api_server.build_mcp_pool()/wire_mcp_dispatchers()/start_mcp()`；`AppState.mcp_pool`/`mcp_reaper`；shutdown `close_all()`；IPC `mcp.status`/`mcp.restart` | `tests/test_mcp_daemon.py`（24） |
| CLI | `trm mcp status`（daemon 在线走 IPC，否则本地读定义）、`trm mcp restart <server>`（无 daemon 时「起一次验证再关掉」） | 同上 |
| 运维文档 | `docs/OPERATIONS.md` 新增「MCP server 运维（M4）」；`scripts/sync_opt_m4.sh`（sudo，sha256 校验）；`scripts/accept_m4.py` | — |

新增 71 项测试（29 + 18 + 24）。本地 **825 passed / 8 failed / 7 skipped**，8 项与既有基线逐条一致；
真机 Ubuntu **827 passed / 11 failed / 2 skipped**，11 项与同步前同一批（宿主状态缺失），**无回归**。

### 真机验收（`scripts/accept_m4.py`，隔离 daemon：8323 端口 + 独立 socket/db/日志）

**16 PASS / 0 FAIL**（开发树与部署树 `/opt/trimum` 各跑一次，两次都是 16/0）

- 接线后 `mcp.status` 的 `source=daemon`、`running=0`（不会提前拉起任何 server）
- `mcp.restart demo` → pid 14091，再 restart → 14095（真的停旧起新）
- `idle_ttl=5` 的 demo 被后台回收器回收；`idle_ttl=300` 的 httpdemo 不受影响
- `streamable-http` 定义在真机完成真实协议往返（列出 7 个工具），`transport=http`
- cgroup 状态 `unavailable (not bound: needs root + cgroup v2 on Linux)` —— 非 root 降级，调用不受影响
- 不存在的 server 报 `not found`，不是静默成功

### 真机暴露并修掉的两个真缺陷

| 现象 | 根因 | 修法 |
|---|---|---|
| `trm --config X mcp status` 报 `source: cli`，隔离 daemon 被完全绕过（首轮验收 7 条断言全崩） | `cli/commands/mcp.py::_daemon_config()` 写死 `Config()`，问的是默认 socket 上的**另一个** daemon；拿不到就静默退回本地一次性路径 | 改走 `load_config(args)`（与其它命令同一口径）；回归 `test_the_daemon_call_honours_config` / `test_restart_command_also_honours_config` |
| daemon 启动后新放进 `~/.trimum/mcp/` 的定义一直报 `not found` | `MCPRegistry` 只靠 `_loaded` 缓存，常驻进程里永不失效 —— M4 之前每个 `trm mcp call` 都是新进程，所以看不出来 | `_ensure_fresh()` 按目录指纹（名字 / mtime / 大小）重读；回归 `TestDropInDefinitions`（含「运行中的池也能看到后加的定义」） |
| 生产 daemon 冒烟时删掉 `~/.trimum/mcp/demo-echo.json5`，已在跑的子进程 45s 后仍在（要等 `DEFAULT_IDLE_TTL`=300s） | `reap()` 对「定义已消失」的 server 退回默认 TTL 兜底；但定义没了之后 dispatcher 也查不到它，这个进程已经不可达 | `reap()` 对 `registry.get(name) is None` 直接回收；回归 `test_a_deleted_definition_closes_the_running_client` |

### 部署状态

- `/opt/trimum` **已装 M4**（2026-09-20 17:33，用户 sudo 执行）；daemon 17:35 重启后 IPC `mcp.status` 返回 `[]`（新代码在跑）。
- 生产 daemon 冒烟全通：热插 `demo-echo.json5` → `trm mcp status` 立刻可见（`source: daemon`）→
  `trm mcp restart demo-echo` 拉起真进程（pid 18797，cgroup 记为 `unavailable (not bound: needs root + cgroup v2 on Linux)`）→
  `trm mcp tools demo-echo` 列出 4 个工具 → 删掉定义后 `status` 不再列出它。
- 验收后又修了 `reap()` 的「定义消失即时回收」（缺陷 3），所以 `/opt/trimum` 值得再装一次：
  `sudo bash /tmp/sync_opt_m4.sh --check` → `sudo bash /tmp/sync_opt_m4.sh`（新 sha `a146fb41…`，只会动 1 个文件），
  再以 guzhujushi 身份 `bash /home/guzhujushi/trimum/scripts/restart_trmd.sh`。
- `/home/guzhujushi/trimum`（开发树）已同步，跑过全量测试与隔离验收。

### 提交与分支

| 内容 | server | main | ubuntu | arch-linux |
|---|---|---|---|---|
| M4 代码 + 测试 | `20ce9d2` | `f813fc8` | `2480869` | `117e85b` |
| M4 文档 + 验收脚本 | `19561e0` | `8778a40` | `76a2dee` | `5ff33b9` |

四分支 cherry-pick 后 `git diff --name-status <target>..server` 均为空，已推送。

## M4.5 远端工具聚合（2026-09-20）

> E2 差距表第 ③ 项（`docs/MCP-INTEGRATION-PLAN.md` §2.2）：让远端工具以 `<server>__<tool>`
> 进 `ToolRegistry`，Agent 从一张表里就能看到「本地 + 远端」全部工具。

### 交付内容

| 子项 | 落点 |
|---|---|
| 命名 / 指纹 / 缓存 | `src/trimum_core/mcp_bridge.py`（新增）：`flat_name` / `split_name`（按**第一个** `__` 切）、`fingerprint`（只取 `env` / `headers` 键名）、`MCPToolIndex`（原子写、坏文件当空缓存、`record` / `forget` / `prune`） |
| 注册表 | `tool_gateway.py`：`ToolRegistry(mcp_index=…)` + `load_mcp_tools()` / `mcp_binding()` / `list_mcp_tools()`；`register()` / `unregister()` 撤掉同名聚合来源；同名冲突时本地工具优先 |
| 分发器 | `tool_dispatchers.py`：`MCPDispatcher(tool_index=…)` + `tool_index` 属性、`_list_tools()` 成功后 `record()`、`_split_call()` 让聚合名与经典两参数等价 |
| daemon | `api_server.py`：`build_mcp_tool_index()` / `prune_mcp_index()` / `wire_mcp_index()` + `AppState.mcp_index`；`start_mcp()` 把**一个**实例同时交给 dispatcher（写）与注册表（读） |
| CLI | `cli/commands/tool.py`：`trm tool list [--mcp]` 标注 `source: local\|mcp` 与 `mcp.{server,tool,transport,trust}`；`trm tool info` 同理 |
| 测试隔离 | `tests/conftest.py`（新增）：`TRIMUM_HOME` 指到临时目录，整套测试不再写真实 `~/.trimum` |
| 运维文档 | `docs/OPERATIONS.md` 新增「工具聚合与缓存（M4.5）」；`ARCH.md` / `docs/MCP-INTEGRATION-PLAN.md`（§2.2 ③ 转 ✅ + §6.2）同步 |

### 验证

- 新增 `tests/test_mcp_bridge.py`（**87 项**）：命名 / 指纹（含「密钥不落盘」）/ 缓存读写与损坏容错 /
  `forget` + `prune` / 注册表注册与刷新 / 同名冲突 / 两种调用写法等价 / 审计里的 server + tool /
  `trm tool list --mcp` 的来源标注 / daemon 接线（含 `prune_mcp_index` 的目录护栏）。
- 本地全量 `pytest tests -q --basetemp tmp/pytest-tmp -p no:cacheprovider` → **915 passed / 5 failed / 7 skipped**。
  本轮前基线是 825/8/7：新增 87 项，另 **3 项由红转绿** —— `test_depends_on` 1 项 + `test_integration` 2 项
  长期失败的原因正是「往真实 `~/.trimum` 写被沙箱拒绝」，`tests/conftest.py` 的隔离把病根去掉了。
  剩余 5 项是既有基线（Windows 沙箱 + LLM 断网），逐条未变，**无回归**。
- 本轮踩到的坑（提交前已修）：`start_mcp()` 里 `prune_mcp_index()` 抛异常会被 daemon 的
  `try/except` 吞成一条 warning，现象是「池子没接上线但 daemon 照常起来」，靠
  `test_mcp_daemon.py::TestDaemonPoolInUse` 两项由绿转红才暴露。**加在 `start_mcp()` 里的步骤必须能被
  这两项看见** —— 这条教训值得记住。

### 真机（Ubuntu）

- 开发树 `/home/guzhujushi/trimum` 全量 `pytest tests -q -p no:cacheprovider` →
  **914 passed / 11 failed / 2 skipped**。同机对照基线（`git archive 889e538~1` →
  `/tmp/trimum_m4base`，即 M4 终态）→ **827 passed / 11 failed / 2 skipped**，
  **失败名单逐条相同**：`test_skill_integration` 7 项（宿主 `~/.trimum/skills` 缺失）+
  `test_tool_file_loading::test_get_executor_exists`（宿主 `~/.trimum/tools/mcp` 缺失）+
  `test_other_dispatchers::test_env_list_sorted`（宿主 env 顺序）+ `test_depends_on` 1 项 +
  `test_llm_integration` 1 项（断网）。+87 全绿 → **无回归**。
- 端到端冒烟（开发树 + `TRIMUM_MCP_DIR` / `TRIMUM_MCP_INDEX` 指向 `/tmp`，真实 MCP 子进程，
  不碰生产 daemon）：

  1. `trm mcp tools demo-echo` → 起 server 列出 4 个工具，并写下 `mcp-tools.json`（1305 bytes）；
  2. `trm --json tool list --mcp` → 4 条 `source=mcp`，名字为 `demo-echo__<tool>`；
  3. `trm --json mcp call demo-echo__echo '{"text":"hi"}' --yes` 与
     `trm --json mcp call demo-echo echo '{"text":"hi"}' --yes` 返回**同一份 JSON**
     （`server=demo-echo`、`tool=echo`、`text="echo: hi"`）；不带 JSON 的聚合名也能调通；
  4. 把定义的 `command` 改成 `/nonexistent/binary` 后，`tool list --mcp` 仍列 4 条
     （读缓存不启动进程），而调用立刻报 `MCP server ...` —— 证明调用真的走到了 server，
     注册表里那 4 条不是一份自欺欺人的名单。
- 冒烟时暴露并修掉的两个 CLI 缺陷（都在 `trm mcp call` 这条路上，见 commit 说明）：
  1. 聚合名没法单独用：`tool` 是必填位置参数，而工具本身可能不要参数
     （`trm mcp call filesystem__list_dir`）→ 改 `nargs="?"`；
  2. `_confirm()` 的 docstring 写着「piped run 不提示」，实现只挡 `EOFError`：stdin 是
     **仍然打开**的管道时（`ssh host 'trm mcp call …'`、CI、包装脚本）`input()` 一直等下去
     —— 本轮实测挂死两次。现在先看 `isatty()`，无人值守只认 `--yes`。

### 部署状态

- `/opt/trimum`：已用**全树同步**（`sudo bash /tmp/sync_opt_tree.sh`，2026-09-20 20:52）落地并**逐文件核对**：
  `mcp_bridge.py` = `f503f505…`、`mcp_registry.py` = `86447a65…`、`tool_gateway.py` = `47d8a205…`，
  三者与本地 HEAD 全部一致 —— M4 遗留的 `reap()` 修复（同步前部署树是 `fe0166cd…`）随全树同步进树。
  部署树的 `[4b/5]` 自检通过。`/opt/trimum/venv` 是 editable 安装
  （`__editable__.trimum_core-0.5.0.pth`），加载的正是 `/opt/trimum/src/trimum_core/`；
  文件 20:52:17 落盘、daemon 20:52:27 启动 → 运行中的就是新代码。
- 真机聚合实测：`trm --json tool list --mcp` 返回 4 条 `source=mcp` 的聚合条目
  （`echo__echo` / `echo__fail` / `echo__slow` / …），日志 `tool_registry.mcp_tools_loaded count=4`，
  `trm tool list` 总数 17 条（13 本地 + 4 远端）。
- `/home/guzhujushi/trimum`（开发树）：本轮已同步，复测结果见上。
- **「8321 已被占用」的真因**：生产 daemon 由 systemd 单元 `trmd.service` 托管
  （`Restart=always` / `RestartSec=5`，单元 `disabled` 但 `active`）。`restart_trmd.sh` 的 `kill` 让 systemd
  在 5 秒后把它复活并先绑上 8321，脚本自己起的实例反而失败 —— 日志里只留 `[Errno 98]`，看起来像端口被外人占了。
  判断依据：`ss -ltnp` 里占端口的 PID 其 `fd1`/`fd2` 指向 `/run/systemd/journal/stdout`（日志进 journal，
  不写 `/tmp/trmd.out`）。已给脚本加守卫，并在 `docs/OPERATIONS.md` 新增「daemon 托管与重启（systemd）」。
- **幽灵缓存已清 + 语义已收口**（2026-09-20 21:03 起）：`~/.trimum/mcp-tools.json` 备份到 `/tmp/mcp-tools.json.bak-20260920` 后删除 —— 清后 `trm tool list --mcp` 为 **0 条**、`trm tool list` 总数从 17 回到 **13**。
  随后把「二选一」改成了**第三种更精确的解法**：原护栏把「一个 server 都没配」和「不知道有哪些 server」混成了一件事。新增 `mcp_registry.definitions_readable()`：
  **目录不存在 = 一个都没配**（可清，否则留下幽灵条目）；**目录在但列不出来**（权限 / IO / 指到一个文件）= 不知道（不动缓存，记 `mcp_index.prune_skipped`）。
  测试：`tests/test_mcp_bridge.py` 87 → **93**（+5 `TestDefinitionsReadable`，旧的「读不到就不清」用例拆成「目录消失 → 清」与「列不出来 → 不清」两条）；本地全量 915 → **921 passed** / 5 failed / 7 skipped（失败名单与基线一致，+6 即新增用例）。
- **daemon 托管形态改判**（2026-09-20 晚）：`trmd.service` 现为 **`enabled + active`**（`Restart=always` / `RestartSec=5` / `User=guzhujushi`），重启一律 `sudo systemctl restart trmd`。历史：当天曾先选「纯手工 daemon」，但单元被重新拉起后与手工进程互抢 8321（journal `NRestarts` 已到 2150）。`scripts/restart_trmd.sh` 已加守卫；切换工具仍为 `scripts/fix_trmd_loop.sh`。`trm status` 实测 `source: rpc`（socket `/run/user/1000/trimum.sock` 正常）。
- **开发树 `.venv/bin/trm` 修复**：脚本仍指向已消失的 `trimum_core.main.cli_dispatch`，改成 `trimum_core.cli:main` 后 `trm --version` 与 `trm commands --check`（63 条）正常。部署树 `/opt/trimum/venv/bin/trm` 一直是好的。

### 提交与分支

| 内容 | server | main | ubuntu | arch-linux |
|---|---|---|---|---|
| M4.5 代码 + 测试 | `889e538` | `0e0d54b` | `1f537f6` | `754038c` |
| M4.5 文档 + 运维记录 | `5718407` | `682d01e` | `6d81617` | `8d80cc4` |
| 同步脚本加 M4.5 聚合自检 | `d1039ef` | `ec4e3aa` | `f56fbc5` | `b605e2c` |
| daemon 重启脚本加 systemd 守卫 | `f752482` | `bdddfc5` | `fa6715f` | `c9f767b` |
| M4.5 真机收尾 + TODO/STATUS 对齐 | `59951be` | `8c663ef` | `c4426e2` | `7949d6a` |
| 幽灵聚合条目（清缓存 + `definitions_readable`） | `9e63a81` | `8437694` | `af9c731` | `c6e7ba9` |
| 无人值守确认不挂死 + 安装失败报原因 | `d34054a` | `07d43a3` | `0494adb` | `4ed51b1` |
| `trm install` 向导非交互跳过可选步骤 | `bd00990` | `303f9ee` | `a8a16be` | `2ce3f3d` |


---

## 收口小项（2026-09-20 晚，M4.5 之后）

### `trm env install` 真机验证（E3 遗留）

真机（guzhujushi，apt 2.7.14，25 条 catalog）实测四条路径：

1. `trm env install neovim --dry-run` → 计划正确（`sudo apt-get install -y neovim`），exit 0；
2. `trm env install ripgrep`（已装）→ `already installed: ripgrep` / `nothing to install`，exit 0
   （幂等、不弹确认、不执行命令）；
3. **修掉的缺陷一**：stdin 是「开着但没内容」的管道时（FIFO、`ssh host 'trm env install x'`、CI）
   `_confirm()` 只挡 `EOFError`，`input()` **永久阻塞** —— 实测挂死。修法与 `trm mcp call` 同一处：
   先看 `sys.stdin.isatty()`，无人值守只认 `--yes`。修后同一场景 **1 秒**返回 exit=1
   （`aborted (use --yes for non-interactive runs)`）；
4. **修掉的缺陷二**：非 root 无密码时只打印 `[exit=1] sudo apt-get install -y neovim`，
   没有原因 → 现在补一行 stderr 末行（实测 `sudo: 需要密码`）。

顺带：`ToolGateway._prompt_confirm()`（Layer 1 终端确认）有同一处挂死风险 —— 改成非 TTY
一律 **fail closed**，并在 stderr 说明「请走 JIT 令牌 / 策略白名单」；开着的确认会把整条 agent
流程卡死在一个等人输入的行上。

- 测试：`test_env_toolchain.py` 34 → **37**、`test_tool_gateway_security_rule.py` +2；本地全量 **925 passed** /
  5 failed / 7 skipped（失败名单与基线一致）。
- 仍待用户执行：`sudo bash /tmp/trm_env_install_real.sh`（root 下的真执行路径，全是已装包、幂等）。
- 同类最后一处也已修：`install_fn.py` 安装向导的 `prompt()`（见下）。

### 非交互挂死的最后一处：`trm install` 向导（2026-09-20）

`install_fn.install()` 的 `prompt()` 只挡 `EOFError` → 管道开着但不给数据时永久阻塞（本轮先复现再修）。
拆出 `_interactive()` / `_read_yes_no()`：**非 TTY 不提问**，LLM key / 开机自启 / 立即启动三个可选步骤
一律跳过并打一行「非交互模式，跳过」；`_read_yes_no` 顺带补挡 `OSError`。

- 新增 `tests/test_install_fn.py`（**14 项**）：`isatty` 三态、默认值回落、EOF / 中断 / IO 错误、
  「管道里 `input()` 绝不被调用」（真挂死即测试失败）、交互态答 n 不碰 systemctl、答 y 经 getpass 写 `.env`。
- 实测：管道场景 **1.1s 退出**（修前挂死）；本地全量 **940 passed** / 5 failed / 7 skipped
  （失败名单与基线逐条一致，+14 即新增用例）。
- `docs/OPERATIONS.md` 新增「同一类挂死的三处」汇总表（env / mcp / 网关 Layer 1 / install 向导）。

### 浏览器工具备选 `bb-browser` 评估（调研，无代码变更）

结论：**维持自研 CDP 工具，不引入依赖**。四条硬理由：本体是 Node/TS（与「去 Node」冲突）；
MCP server 源码不在公开仓库（与它自己 `PRIVACY.md` 的「可审计」矛盾）；`site` 适配器在**页面上下文
`eval` 第三方 JS**，绕开 `ToolGateway` / 策略 / 审计；上游 4 个月无 push（最后 push 2026-05-29）。

值得借鉴的两点已落文档：适配器自带 `example / domain`、`snapshot -i` 的 `@N` 稳定元素编号
（`docs/TOOL-DEVELOPER-GUIDE.md` §11 + `TODO.md`）。完整报告：`docs/BB-BROWSER-EVALUATION.md`。

### 真机核验与待办（2026-09-20 21:33）

- 开发树 `/home/guzhujushi/trimum` 已用新 tar 同步（`src/trimum_core/install_fn.py` = `2ce5e92e…`、
  `mcp_registry.py` = `2d86a39d…`，与本地 HEAD 一致；`tests/test_install_fn.py` 落树）。
  全量 `pytest tests -q` → **939 passed / 11 failed / 2 skipped**，失败名单与真机基线**逐条相同**
  （`test_skill_integration` 7 + `test_tool_file_loading` 1 + `test_other_dispatchers` 1 +
  `test_depends_on` 1 + `test_llm_integration` 1）→ **无回归**。
- **待用户执行两条 sudo**：
  1. `sudo bash /tmp/sync_opt_tree.sh` —— 把本轮修复同步进部署树 `/opt/trimum`
     （开发树已单独同步过，所以**不需要** `--fix-home`）；
  2. `sudo bash /tmp/trm_env_install_real.sh` —— `trm env install` 的 root 真执行路径（全是已装包、幂等）。
- **临时物已清**：真机 `/tmp` 147 → 46 项（只留上面两个脚本 + `trimum-sync.tar` + 缓存备份
  `mcp-tools.json.bak-20260920`；systemd / snap 私有目录不动）；本地删掉 `tmp/m45/` 整目录与
  `tmp/commit-msg*.txt`。清理脚本一次一用，不入库。

## E4 广接入（✅ 已完成，2026-09-20）

> 计划与设计：`docs/E4-PLAN.md`；明细见文末「E4 广接入：生态导入器（2026-09-20）」。
> 提交：计划 `fdee6d5` / S1+S2+S5 `be5198d` / S3 `861126e` / S4 `05bb1ee` / S6 文档 `be604e8` / S7 验收 `b5b2121`。
> 遗留「`to_workflow_definition()` 不搬运 `instruction`」→ 已由 **W1** 修掉（见文末「W1 Workflow 执行语义」）。

---

## E4 广接入：生态导入器（2026-09-20）

> 计划与切分：`docs/E4-PLAN.md`；设计：`ARCH.md` §「广接入：生态导入器（E4）」；
> 运维：`docs/OPERATIONS.md` §「生态导入」。缺口表 #4 / #6 / #7 与 E3 顺延的 `trm skill import`
> 一起在这一轮收口（`docs/ECOSYSTEM-STRATEGY.md`）。

### 交付内容

| 片 | 内容 | 提交 |
|---|---|---|
| S1 | `ecosystem.py`：`EcosystemEntry` 统一 schema + `assess_risk` 分级器（动词表 + 理由，无证据兜底 medium）+ 校验器 + 共用 `ImportRefused` | `be5198d` |
| S2 | `cli_adapter.py` + `trm tool import-cli`：`--help` 探测 → 解析 → 定级 → `tool.json5` + 薄壳 `main.py`；`generic_executor` 运行时再兜一层白名单 | `be5198d` |
| S5 | `enabled` 开关：`tool_file_loader` 的 `load_manifest` / `manifest_enabled` / `set_manifest_enabled`（逐行就地改，保留 JSON5 注释）/ `list_manifests`；`tool_gateway.load_all()` 只 import 启用的工具；`trm tool enable|disable`、`trm tool list --all` | `be5198d` |
| S3 | `workflow_catalog.py` + `trm workflow import`：Warp 式目录 YAML → 逐条校验 → 编译 `WorkflowDefV2` → `~/.trimum/workflows/<id>/workflow.yaml` | `861126e` |
| S4 | `skill_import.py` + `trm skill import`：本地目录 / git URL（`git clone --depth 1` 到临时目录）→ frontmatter 校验 → `~/.trimum/skills/` | `05bb1ee` |
| S6 | 文档：`ARCH.md` / `docs/OPERATIONS.md` / `docs/ECOSYSTEM-STRATEGY.md` / `TODO.md` | `be604e8` |
| S7 | 真机验证 + 验收入口 `scripts/accept_e4.py` | 本提交 |

新增测试 **159 项**：`tests/test_ecosystem.py`(29) + `tests/test_cli_adapter.py`(42) +
`tests/test_workflow_catalog.py`(48) + `tests/test_skill_import.py`(40)；`trm commands --check` → **68 条**无问题。

### 六条红线（写进代码与测试）

| 红线 | 落点 |
|---|---|
| 导入不执行 | 适配器只跑 `--help`；workflow / skill 只读文本、只写文本，绝不 import / 执行导入物 |
| `--dry-run` 不落盘 | 三个导入器同一条规则，测试逐条断言目标目录没有新增 |
| 非交互要 `--yes` | 非 TTY 直接 abort（`cli/_ask.py`），退出码 1 |
| 第三方默认不启用 | 工具产物 `enabled: false`；workflow / skill 是惰性文本（`enabled: true`，不 `run` 就不发生任何事） |
| 不覆盖已有 | 目标存在即拒绝，除非显式 `--force`；**先全量检查再写**，不做半截导入 |
| 不引入新依赖 | YAML 用已有 PyYAML；git 源走系统 `git clone`，失败即报错 |

### 本轮修掉的真实缺陷（4 个）

1. **`subprocess.run(capture_output=True)` 在 Windows 上永久挂死**：被探测 CLI 留下的后台孙进程持有
   管道继承写句柄，而 Windows 上 `subprocess.run` 超时后会 `kill()` 再**无超时地** `communicate()`
   一次 → `trm tool import-cli git` 挂住不返回（实测 + faulthandler 取到栈）。
   修法：探测输出走**临时文件**（`cli_adapter.default_runner`），`stdin=DEVNULL` 防分页器等输入；
   回归测试 `TestDefaultRunner` 用一个"泄漏孙进程"的假 CLI 顶住这条（守护线程兜底，不会把套件挂死）。
2. **三处默认根写死 `Path.home()/".trimum"`**，绕开 `TRIMUM_HOME` → 「导入了却看不见」：
   `tool_file_loader.list_manifests`、`WorkflowDefV2.load_from_dir`、`skill_sync.default_source_roots`
   统一改走 `paths.trimum_path(...)`。
3. **skill 导入：本地裸仓库路径（`.../repo.git`）被当成 URL**，把路径写进 `source_url` 导致校验失败。
   现在 `source_url` 只收真 URL，来源另记 `origin`（本地 `.git` 路径仍会走 `git clone`，只是不联网）。
4. **plan 与写盘之间源目录会变**：`write_skills` 现在在写入前**重算文件清单**（`--force` 确认要等人，
   源目录也可能变），并且仍然先全量检查再写。

### 本地验证

- 全量：**1099 passed / 5 failed / 7 skipped**（E4 前 940 passed；+159 用例）。5 项失败 = 既有基线
  （Windows 沙箱 + PATH 缺 `python.exe` + LLM 断网），名单与基线逐条相同。
- `trm commands --check`：68 条无问题。
- 端到端手测（临时 `TRIMUM_HOME`）：`import-cli git` → `list`（不含）→ `enable` → `list`（含）→
  `disable`；`--dry-run` 不落盘；重复导入被拒；workflow 声明 `risk: low` 被命令里的 `prune` / `rm`
  顶成 `high` 并给出理由；skill 复制 `.git` 不入副本。

### 真机验证（Ubuntu 开发树 `/home/guzhujushi/trimum`，2026-09-20）

- 同步：`git archive HEAD` → `/tmp/trimum-sync.tar` → 开发树 `tar -xf`（开发树已归 `guzhujushi`
  属主，**不需要 sudo**；新文件 `ecosystem.py` / `cli_adapter.py` / `workflow_catalog.py` /
  `skill_import.py` 逐个核对落地）。
- 全量：**1098 passed / 11 failed / 2 skipped**。
- **基线对照（严格）**：`git archive cfafc21`（E4 之前）解到 `/tmp/trimum_pre_e4`，
  `PYTHONPATH=/tmp/trimum_pre_e4/src .venv/bin/python -m pytest /tmp/trimum_pre_e4/tests -q`
  → 失败集合归一化后 `diff` = **IDENTICAL_11_of_11**（两条看起来可疑的
  `test_tool_file_loading::test_get_executor_exists` 与 `test_other_dispatchers::TestEnvDispatcher`
  在基线里同样失败 → 不是 E4 引入）。
- 验收：`scripts/accept_e4.py`（已入库，跑法见其 docstring）→ **43 passed / 0 failed**：
  - A 通用 CLI 适配器 8 项：探测到子命令、默认 `enabled=false`、`trust=third-party`、分级有理由、
    manifest（JSON5）可解析、`--force` 没进白名单；
  - B/C/D 启停 7 项：未启用不在注册表、`list --all` 看得到、enable 后进注册表、disable 后退出且不删文件；
  - E 运行时白名单 3 项：白名单外旗标与未探测子命令**在 spawn 之前**就被拒（exit_code 2），
    白名单内的 `--version` 真跑通（`git version 2.43.0`）；
  - F workflow 7+3 项：dry-run 不落盘、声明 low 被 `rm` 顶成 high、理由点名触发词、真导入后
    `workflow list` 可见、重复导入被拒；
  - G/H skill 8+3 项：dry-run 不落盘、`SKILL.md` 逐字节一致、附件一起搬、`skill list` 可见、
    重复导入被拒；**git 源真 `git clone` 本地裸仓库**（含 `<repo>/skills/<name>/` 一层嵌套布局）、
    克隆临时目录不留残渣；
  - I 全局 3 项：`commands --check` 无问题、`trm --version` 可用；
  - **红线哨兵**：每条导入命令里都写着 `rm -f /tmp/TRM-E4-MUST-NOT-EXIST`，整轮验收后该文件
    始终不存在（F6/F9/G7/I3 四处断言）→ 「导入不执行」在真机上成立。

### 提交与分支

> 分支纪律见 `AGENTS.md`（2026-09-20 改判）：**日常只推 `server`**，`main` / `ubuntu` /
> `arch-linux` 只在收尾阶段统一同步推送。

| 内容 | server |
|---|---|
| E4 计划与设计 | `fdee6d5` |
| E4 S1/S2/S5（ecosystem + CLI 适配器 + 启停） | `be5198d` |
| E4 S3（workflow 目录 + `trm workflow import`） | `861126e` |
| E4 S4（`trm skill import`） | `05bb1ee` |
| E4 S6 文档 | `be604e8` |
| E4 S7 真机验收 + `scripts/accept_e4.py` | 本提交 |

### 待用户执行（sudo，脚本已在远端 `/tmp`）

1. `sudo bash /tmp/sync_opt_tree.sh` —— 部署树 `/opt/trimum` 同步到 E4 树
   （默认源就是 `/tmp/trimum-sync.tar`，已是本轮 `git archive` 的 E4 内容）。
   同步完记得重启 daemon：`sudo systemctl restart trmd`。
2. `sudo bash /tmp/trm_env_install_real.sh` —— E3 遗留的 `trm env install` root 侧真执行验证（仍在）。

### E4 遗留

- ~~**`WorkflowDefV2.to_workflow_definition()` 不搬运 `instruction`**~~：**W1 已修**（2026-09-20），
  见本文末「W1 Workflow 执行语义」。
- `tests/test_cli_adapter.py` 的 `parse_help` 用的是抽象帮助文本；可选硬化：把 `git --help` 的真实
  输出做成 fixture。
- 证书 `capabilities` 与 ToolGateway / `security_rule.py` 的运行时合并仍未接线（`TODO.md` 有记录）。

---

## W1 Workflow 执行语义（已完成，2026-09-20）

> 立项依据：E4 遗留「`WorkflowDefV2.to_workflow_definition()` 不搬运 `instruction`，导入的 workflow
> 在 `trm workflow run` 下不会真执行」。计划与语义决策：`docs/WORKFLOW-EXECUTION-PLAN.md`。
> 用户诉求原文：「补全 workflow 的执行能力，使 workflow 能开始监听 Event Bus，可以驱动执行」。

### 动工前的勘察（先看代码得到的结论）

| 事实 | 证据 |
|---|---|
| 引擎只有 `run(definition)`，**没有任何触发器** | `workflow_engine.py` 的 `run` / `_execute_dag` / `_execute_single_node` |
| 曾经想过触发器，但实现是坏的 | 模块级 `async def start_v2(self, engine, ...)`：`self` 无人传入、裸 `eval`、订阅 `"*"` 从不退订、`task.assigned` 全库无消费者 |
| v2→v1 转换丢执行信息 | 只搬 `agent_type` → `handler`，`instruction` 掉地上 |
| `load_from_dir()` 尾部有死代码 | `workflow_engine.py:1085-1117`（`return` 之后的重复函数体） |
| 唯一「预设 workflow」是数据不是能力 | `threat_workflows.THREAT_WORKFLOWS`（16 条威胁响应剧本），全库零调用点 |
| 工作流目录默认空 | `~/.trimum/workflows/`；仓库内无 workflow YAML 资产（本机另有 2 份手写的 `blog-deploy` / `daily-check`） |
| ~~`WorkflowListener` 从未被实例化~~ ✅ **2026-09-21 已接线**（穿插项步骤 C） | 当时 `api_server.py` 只起了 `WorkflowEventDriver`；`workflow.trigger` 事件只发不收。现已装配 + 给了 `trm workflow submit` 入口 |

### 交付

- [x] `workflow_engine.py`：`to_workflow_definition()` 搬运 `instruction` / `agent_type` / `input_data` /
      `trigger_event`；删掉 `return` 之后的死代码与坏掉的 `start_v2`；agent 节点缺 driver 时给可行动的错误
- [x] `workflow_runtime.py`（新，866 行）：`WorkflowRuntime` = 注册表 + Event Bus 触发器 + 驱动执行 +
      运行记录；`agent_type: shell` 处理器走 ToolGateway
- [x] `threat_workflows.py`：`builtin_workflows()` 把 16 条剧本编译成 `WorkflowDefV2`
      （命令式步骤 `shell`、散文式步骤 `trm-agent`），登记为 `source=builtin`、默认 `enabled: false`
- [x] `api_server.py`：daemon startup 建运行时 + `start()`；`GET /api/workflows` 与
      `GET /api/workflows/runs`（只读，不开放执行端点）
- [x] `cli/commands/workflow.py`：`list --all` / `run [--input --event --payload --timeout --dry-run]` /
      `enable`（内置剧本落盘成用户自己的文件）
- [x] 测试：`tests/test_workflow_runtime.py`（55 例）+ `tests/test_api_server_startup.py`（+2 例）
- [x] 文档：`ARCH.md`（新章节）、`docs/WORKFLOW-EXECUTION-PLAN.md`、`docs/OPERATIONS.md`、`TODO.md`

### 语义与红线（细节见 ARCH）

- **step 之间不串行等待**：每个 step 各自常驻监听；要串行就把任务放进同一个 `execute` 组。
- **同一 step 已在跑 → 跳过**（`event.workflow.skipped`，`reason=already_running`）；另有事件环路熔断：
  同一 workflow 每 10s 最多自动跑 20 次，超限发 `event.workflow.throttled`（`run_now` 不受限）。
  `workflow.finished` 在运行仍算「在跑」时发出，因此「监听自己 finished」的 workflow 不会自我续命。
- **空触发器 = 只能手动跑**；触发器匹配：精确 → 去命名空间前缀（`event.` / `task.`）→ `fnmatch` 通配。
- **一律走 ToolGateway**：策略 / 风险 / SecurityRule / 审计 / 脱敏 / 行为基线照常，流量标记
  `SourceType.WORKFLOW`；工作流不持有任何执行旁路。
- **失败不伪装**：拒绝 / 非零退出 / 缺 `instruction` → 节点 FAILED、workflow failed。
- **内置剧本默认不自动触发**：剧本里有 `kill` / `firewall-cmd`，自动跑等于删掉确认环节。
- **事件是广播的，但命令只对点名的那份负责**：一次事件可能顺带触发同 root 下别的 workflow；
  `trm workflow run <id> --event ...` 的退出码只看 `<id>` 自己的运行，其余的进 `other_triggered`
  如实汇报。若事件来了却唯独没命中点名的那份 → 退出码 1 并说明「触发到的其实是哪些」。
  （验收时发现：旧实现拿**所有**被触发的运行算退出码，别人的失败会算到本条命令头上。）

### 验证

- 本地全量：**1156 passed / 5 failed / 7 skipped**（W1 前 1099 / 5 / 7；+57 = 本轮新用例，
  5 项失败与 W1 前同名同数，无回归）。
- 真机（`guzhujushi@100.115.86.48`, Ubuntu, `/home/guzhujushi/trimum`）：`scripts/accept_w1.py`
  → **48 passed / 0 failed**；`pytest tests/test_workflow_runtime.py tests/test_workflow_files.py`
  → **69 passed**。
- 提交：`62ae2f8 feat(workflow): W1 workflow 执行语义 —— 监听 Event Bus 并驱动执行`（已推 `origin/server`）。
- 冒烟（本机 Windows）：
  - `trm workflow list --all` → 18 条（2 文件 + 16 内置），内置全部 `disabled`；
  - `trm workflow run demo --root tmp/w1root --dry-run` → 只打印节点，不执行；
  - `trm workflow run demo --root tmp/w1root` → 两个 shell 节点 `completed`，
    审计里有 `gateway.audit ... agent_id=trm-workflow tool=shell`；
  - `trm workflow run demo --root tmp/w1root --event security.monitor_result --payload {...}`
    → `triggered_by=event`，条件命中并执行；
  - `--event nope.event --timeout 1` → 退出码 1，提示「no run triggered ... (this workflow listens for: ...)」；
  - 同一 root 下两份 workflow 听同一事件 → 点名的跑成即退出码 0，另一份进 `other_triggered`；
    点名的那份没被触发而别的被触发 → 退出码 1 并列出「触发到的其实是哪些」；
  - `trm workflow run threat-cron-audit --dry-run` → 4 步（2 命令 + 2 散文）。

### W1 遗留

- ~~**`WorkflowListener` 仍未接线**~~ ✅ **2026-09-21 已接线**（穿插项步骤 C）：`submit()` 当生产者、
  daemon 启动即装配、CLI 入口 `trm workflow submit`；`workflow.trigger` 事件本来就能被运行时消费
  （workflow 写 `trigger.event_type: workflow.trigger` 即可），现在真有人发它了。
- 运行记录只在内存（环形 200 条），进程重启即丢；`trm workflow status/log` 仍是桩。
- 内置剧本的启用开关只有 `trm workflow enable <id>`（落盘法），没有「原地开关」。
- daemon 只暴露只读端点；`POST /api/workflows/{id}/trigger` 这类执行入口**故意没开**（避免无鉴权执行面）。
- 散文式步骤需要装了 Agent 脚本的 driver 才能真正跑（`trm-agent`），否则节点明确失败。

---

## EventBus 通信审计（2026-09-20，只读分析）

> 用户诉求原文：「请阅读一下 docs 文件夹里的文件，分析有关 EventBus 的通信，还有哪些没完成」。
> 方法：通读 `docs/` 里与事件相关的文档（`SECURITY-DEFENSE-PLAN.md` §11、`security-agent-implementation-plan.md` §2/§3、
> `TARL-SPEC.md` §7、`SYSTEM-MONITOR.md`、`ERROR-CODE-SPEC.md`、`WORKFLOW-EXECUTION-PLAN.md`），
> 再对 `src/` 全量扫**生产者**（`emit_event` / `emit_task` / `SystemEvent(event_type=...)`）与**订阅者**（`subscribe`）逐条对照。
> **本轮只读，未改任何代码**；完整清单与优先级落在 `TODO.md`「EventBus 通信缺口」（避免两处各写一份互相漂移）。

### 一句话结论

总线骨架是通的（pub/sub + `*` 通配 + 100 条环形历史 + replay），**缺的是生产端** —— daemon 里真正在跑的订阅者只有
`SecMonitor` / `WorkflowEventDriver` / W1 `WorkflowRuntime`，而多个关键事件「有订阅没生产」。

### P0：安全响应链未接线（拦得住，但不会响应 / 记录 / 通知）

| 事实 | 证据 |
|---|---|
| L4 命中威胁只 `logger.warning` + 返回 denied，**不发 `security.monitor_result`、不调 SecExecutor** | `tool_gateway.py:715` |
| `security.monitor_result` 唯一生产者 `SecMonitor._dispatch()` 只被 `_on_executing()` 调用，而 `agent.executing` **全库无生产者** | `sec_monitor.py:418 / 457 / 487` |
| payload 契约不符：生产端嵌套 `{"threat": {...}, "original_event": {...}}`，16 条内置剧本条件是扁平 `payload.get('threat_name')` | 实测 `builtin_workflows()` 的 condition |
| **后果** | 16 条威胁响应剧本永不自动触发（只能手动 `trm workflow run --event`）；`security.blocked` / `security.alert` 从不出现；`SecExecutor` 从未真正执行 |

### 其余缺环（速览，明细见 TODO）

- **零生产零消费**：`security.ebpf_alert` / `security.fuse_triggered` / `security.audit_breach`（子系统未开工）、`workflow.threat_response`（文档称「已有事件」，代码里没有）。
- **有生产没消费**：`planner.*`、`agent.status_changed`（`agent_runtime` 只在测试里被实例化）。
- **有订阅没生产**：`agent.executing` / `.executed`（SecMonitor 死订阅）、`memory.*`（MemoryBridge 未实例化）、`system.alert`（SystemMonitor 未实例化）、`event.transform.completed`（WorkflowListener 未实例化）。
- **总线自身**：`_safe_call` 静默吞异常 + `TRM-9005` 从未 raise；`event_index.EventIndex` 没接进 `EventBus`；`LiveConsole.subscribe_events` 订阅 `task.*` 却全等比对 `task.started`（永远不亮）；SDK `trimum_agent.py:167` 的 `publish("tool.executing", {...})` 签名与事件名都错（异常被吞）。
- **文档过期**：`docs/SYSTEM-MONITOR.md` 的示例用 `event_bus.emit()`（该 API 不存在）；旧 STATUS 表里 `TASK_ASSIGNED` 标 ✅，但 `task.assigned` 从未落地。

> **修复进度（2026-09-21 回填）**：上列「总线自身」四项由穿插项**步骤 B** 全部落地；
> 「有订阅没生产」里的 `event.transform.completed`、「有生产没消费」里的 `planner.*`、以及无处安放的 `workflow.trigger`，
> 由穿插项**步骤 C** 接线（`WorkflowListener.submit()` 当生产者 + daemon 装配 + `trm workflow submit`）。
> 仍未动的：`memory.*`（MemoryBridge 未实例化）、`system.alert` / `system.heartbeat`（SystemMonitor 未实例化）、
> `agent.status_changed`、`task.assigned`、三个未开工子系统。

### 优先级判断

**P0 安全链接线 > E5 官方分发渠道**：安全响应是 trimum 的招牌能力，「拦截」能跑而「响应 / 审计 / 通知」是空的，
等于 16 条剧本 + `SecExecutor` 全是摆设；分发渠道再顺，发的也是链条断的产品。改动点只有 3 处（统一 payload 契约 /
L4 走 `_dispatch` / 定 `workflow.trigger` 归属），工作量可控。总线硬化是它的配套（`_safe_call` 静默是排障黑洞）。

---

## 2026-09-21 根目录文档合并与清理（PRD / ARCH → `docs/`，tmp 清空）
>
> 提交：`9096e9a`（server 分支）。

> 诉求：核对 `PRD.md` / `ARCH.md` 与 `TODO.md` / `STATUS.md` 的重复度，重复则合并清除，并清理临时文件与过期文件。
> 结论：**`PRD.md` 重复度 ≈ 95%（直接删除）；`ARCH.md` 约 1/3 是与 `docs/` 专题文档重复的规划快照，去重后移入 `docs/ARCH.md`。**
> ⚠️ 本文档历史记录里出现的 `ARCH.md` 一律指现在的 `docs/ARCH.md`。

### 为什么删 PRD.md

| PRD.md 章节 | 内容已存在于 |
|---|---|
| 产品目标 / 用户场景 | `README.md`（本次把用户场景并入 README「典型场景」） |
| 功能需求（已交付 Phase1-3 / E1 / E6 / E3 / E2 / M3） | `STATUS.md` 各里程碑小节 + `TODO.md`「已完成」 |
| 功能需求（规划中） | `docs/ECOSYSTEM-STRATEGY.md` §7 / §7.1 / §7.2 / §7.3 |
| 范围边界 / 验收标准 | 移入 `docs/ARCH.md`「范围边界与验收（生态轮）」 |

### ARCH.md → `docs/ARCH.md`（去重后）

- **搬移**：根 `ARCH.md` → `docs/ARCH.md`。架构文档按 `AGENTS.md` 的文档纪律归 `docs/`，根目录不再保留 `PRD.md` / `ARCH.md`。
- **删除的小节**（与 `docs/` 专题重复的规划快照，共约 70 行）：
  `MCP 接入（规划）`（已被 E2 / M4.5 小节取代）、`生态四层（规划）`（并入新的「生态四层（L0–L3）」速查表 + `docs/ECOSYSTEM-STRATEGY.md` §3）、
  `官方分发渠道（规划）` 与 `身份、证书能力与多用户（规划）`（`docs/ECOSYSTEM-STRATEGY.md` §7 / §7.1 / §7.2 全文覆盖）。
- **新增**：`范围边界与验收（生态轮）`（来自 PRD.md）。

### 引用同步（tracked）

| 文件 | 改动 |
|---|---|
| `scripts/sync_opt_tree.sh` | 顶层文件同步去掉 `ARCH.md` / `PRD.md`，改为 `docs/ARCH.md` → `/opt/trimum/ARCH.md` |
| `docs/OPERATIONS.md` | W1 语义细节引用 `ARCH.md` → `docs/ARCH.md` |
| `TODO.md` | 「已完成」表新增本行；Phase 3 审计的「基准文档」补注（那 3 份文档已于 2026-09-20 删除）；`ARCH.md` 引用改 `docs/ARCH.md` |
| `README.md` | 删除过期口径（`cli-anything-browser-cdp` 已否决 → 自研 CDP 19 action）；修正过期的组件行（Event Index 未接线 / Token 显示 / 结构化审计 / 流式输出）与 Phase 3.5 状态；并入 PRD 的「典型场景」 |
| `AGENTS.md` | 新增「文档地图」小节 |

### 清理的临时 / 过期文件

| 路径 | 处置 |
|---|---|
| `tmp/`（476 个文件 / 14.4 MB：本轮各次调研脚本、`*.tar` 快照、`e4home*` / `w1root` / `sk_repo*` 试验目录、`pytest-tmp`） | 清空；**保留 `tmp/research/`** —— `docs/` 多处引用的原始件，且是 `trm mcp catalog import` 的默认输入（`tmp/research/awesome-README.md`，也是 `tests/test_mcp_catalog.py` 的快照比对源） |
| `.pytest_cache/`、`**/__pycache__/` | 删除（可再生） |
| `.sonar/`（2026-09-01 扫描残留） | 删除（重扫时重建） |
| `memory/2026-09-08.md` | 删除（工作区早已删掉的遗留条目，本次随清理提交） |

---

## 2026-09-21 P0 步骤 1/3：`security.monitor_result` 载荷契约统一（扁平）
>
> 提交：`087a476`（server 分支）。

> 来源：2026-09-20 只读审计的 P0「安全响应链接线」三条动作，本日**只做第 1 条（契约）**，不接线。
> 完整缺口清单见 `TODO.md`「EventBus 通信缺口」。

### 事实（复述审计）

- 生产端 `SecMonitor._dispatch()` 发的是**嵌套**载荷 `{"threat": ThreatMatch, "original_event": SystemEvent}`；
- 消费端 15 条内置剧本的条件是**扁平** `payload.get("threat_name") == "..."`（`threat_workflows.trigger_condition()`）；
- 两边对不上 → 即使把 L4 接到 `_dispatch`，剧本依然不会触发（「接上也不响」）。

### 改动

| 位置 | 改动 |
|---|---|
| `src/trimum_core/sec_monitor.py` | 新增 `MONITOR_RESULT_CONTEXT_KEYS` + `monitor_result_payload(threat, event)`：载荷 = `ThreatMatch.model_dump()`（威胁本体）+ 触发上下文扁平拷贝（`agent_id` / `command` / `pid` / `sandbox` / `layer_hit`）+ `source_event_type`；`_dispatch()` 改用它，**不再嵌套** `threat` / `original_event` |
| `tests/test_sec_monitor.py` | **新建（11 项）**：载荷形状 / 上下文透传与缺省 / JSON 可序列化 / `_dispatch` 发的就是这个载荷且仍交 SecExecutor / **每条内置剧本的条件都能被生产端载荷命中**（生产端↔消费端契约锁）/ 签名 `trigger_workflow` 与剧本名一一对应 |
| `docs/SECURITY-DEFENSE-PLAN.md` §三 | 新增「`security.monitor_result` 载荷契约（扁平）」表：键 → 来源 → 缺省 |
| `docs/security-agent-implementation-plan.md` §3 | 修掉当初造成漂移的样例（`payload={"threat": threat.dict(), ...}` → 扁平），并标注契约已冻结 |

### 验证

- `python -m pytest tests/test_sec_monitor.py -q` → **11 passed**
- 端到端（测试内）：真命令 `echo 'x' >> /etc/ld.so.preload` → 真威胁 `ld_preload` → 发出的扁平载荷命中 `threat-prelink-check` 的条件，威胁同时交给 `SecExecutor`
- 全量：`python -m pytest tests -q` → **1167 passed / 5 failed / 7 skipped**（+11 为本轮新增；5 项失败与既有基线逐条一致：
  PATH 缺 `python.exe` + 沙箱写 `~/.trimum/learning/learning_data.json` 被拒 ×3 + LLM 断网）

### 顺带发现（未修，记进 `TODO.md`）

- 16 条内置剧本里 **3 条没有威胁源**：`threat-ransomware-response` / `threat-btrfs-snapshot-protect`（`threat_name: ransomware`）、
  `threat-persistence-sweep`（`persistence`）—— `ThreatMatcher` 里没有这两个签名，它们的生产者应是**尚未开工**的 `BehaviorMonitor`；
  另 1 条 `threat-audit-integrity-check` 的 trigger 是 `cron`（定时，不是事件）。
- 12 个威胁签名 → 12 个剧本的映射是**一一对应**的（已加测试锁住）。

### 剩余（P0 步骤 2 / 3）

2. **L4 改走 `_dispatch`** —— `tool_gateway.py:716` 命中威胁时发事件 + 调 `SecExecutor`（顺带决定 `agent.executing` 死订阅的去留）。
3. **定 `workflow.trigger` 归属** —— 现在一边扁平带 `workflow_name`（`sec_executor.py`），一边（旧文档）嵌套带 `threat`；不要两套并存。

---

## 2026-09-21 P0 步骤 2/3：L4 改走 `SecMonitor.inspect()`（拦截 + 响应 + 记录 + 通知）
>
> 提交：`d5393a6`（server 分支）。

> 来源：2026-09-20 只读审计 P0 第 2 条。步骤 1（载荷契约）见上一节；
> 本次把「L4 只拦不报」接成「一条命令完成扫描 → 广播 → 执行 → 由网关决定拒绝」。

### 改动

| 位置 | 改动 |
|---|---|
| `src/trimum_core/sec_monitor.py` | 新增 `inspect(event) -> list[ThreatMatch]`（唯一扫描入口）：`scan_command()` + 命中则 `_dispatch()`（发 `security.monitor_result` + 调 SecExecutor），返回威胁列表给网关自行处置；**删除** `_on_executing` / `_on_executed` 与对应订阅，`start()` 只剩幂等生命周期钩子；模块 docstring 同步 |
| `src/trimum_core/tool_gateway.py` | L4 由旁路 `scan_command()` 改为 `sec_monitor.inspect(SystemEvent(...))`，载荷带 `agent_id` / `command` / `sandbox` / `layer_hit: "L4"`；`DENY` 分支行为不变（`status=denied` / `exit_code=137` / `security_blocked` 审计），但这次事件与 SecExecutor 都会真的跑 |
| `src/trimum_core/tool_gateway.py` | **修掉一颗地雷**：L4 原先传 `pid=os.getpid()`（daemon 自己的 PID）。接上 SecExecutor 之后，`FREEZE` / `KILL` 类威胁会 `SIGSTOP`/`SIGKILL` **daemon 自身** → 改为 `pid=0`（执行前闸门没有子进程），`SecBlocker` 对 `pid<=0` 已有 guard |
| `tests/test_gateway_layer4.py` | **新建（9 项）**：DENY 命令被拦（status/exit_code/action）+ 扁平 `monitor_result` 带对上下文（`pid=0`、`layer_hit=L4`）+ SecExecutor 真的落了审计（临时文件）、发了 `security.blocked`、发了 `workflow.trigger`（`threat-prelink-check`）+ 载荷满足内置剧本条件；非 DENY（`supply_chain` / CONFIRM）只响应不拦（锁住当前取舍）；干净命令全程静默；没装监控的网关没有 L4（缺口陈述） |
| `tests/test_sec_monitor.py` | `agent.executing` 发布驱动的用例改为 `inspect()` 直调；新增 2 项：干净命令不发任何事件 / 往总线发 `agent.executing` 不再触发扫描（锁住死订阅已删） |
| `docs/SECURITY-DEFENSE-PLAN.md` §三、§11.2 | 扫描入口改写为「L4 直连 `inspect()`、不订阅事件、pid 传 0 的理由」；EventSnoop 一行标注未启用及原因 |

### 验证

- `python -m pytest tests/test_gateway_layer4.py tests/test_sec_monitor.py -q` → **20 passed**
- 全量：`python -m pytest tests -q` → **1176 passed / 5 failed / 7 skipped**（+9 为本轮新增；5 项与既有基线逐条一致）
- 关键断言（真链路，不是 mock）：`cat /etc/ld.so.preload` → `ld_preload` → `status=denied` + `security.monitor_result`（`threat_name=ld_preload`、`pid=0`、`layer_hit=L4`）+ `security.blocked` + `workflow.trigger(workflow_name=threat-prelink-check)` + 审计文件含 `ld_preload` / `deny`

### 顺带发现（未修，记进 `TODO.md`）

- **非 DENY 威胁今天只响应不拦**：`KILL` / `FREEZE` / `ISOLATE` / `CONFIRM` 类威胁在 L4 会被广播 + 交 SecExecutor，但网关仍放行（与改动前一致）。要真拦，需要「威胁等级 → 网关动作」的映射取舍，以及**执行后**拿到子进程 PID 才能做 FREEZE/KILL。
- **只有 daemon 的网关挂了 sec_monitor**：`agent_loop.py:112`（`trm ask`）与 `workflow_runtime.py:823`（workflow 执行）各自 `ToolGateway(...)` 都没注入 → 那两条路上的命令不经过 L4。
- `SecAudit()` 默认写 `~/.trimum/audit/security.log`（硬编码 `~`，不走 `TRIMUM_HOME` / `paths.trimum_home()`）；测试里必须显式传 `audit_path`，否则会写开发者真实家目录。
- 设计里的 LLM 深度判断兜底（旧 `security.alert` + `needs_llm=True`）随本次删除失去唯一生产者，仍未开工。

### 剩余（P0 步骤 3）

3. **定 `workflow.trigger` 归属** —— 现在 `sec_executor.py` 扁平发 `workflow_name` + `threat_name`，
   `workflow_listener` 未实例化；剧本要么听 `workflow.trigger`，要么直接听 `security.monitor_result`，**不要两套并存**。

---

## 2026-09-21 P0 步骤 2 补丁：L4 装配统一 + 处置映射 + 签名收敛

> 提交：`dbc411e`（server 分支）。
> 来源：步骤 2 收尾时记下的两条缺口（「非 DENY 威胁只响应不拦」「只有 daemon 的网关有 L4」）
> + 一件前置（L4 要常开，签名就不能误报）。**P0 步骤 2 至此真正闭环**，只剩步骤 3。

### 问题 → 方案

| # | 问题 | 根因 | 处置 |
|---|---|---|---|
| G1 | `trm ask` / `trm exec` / workflow 兜底网关没有 L4 | L4 是「谁记得注入 `sec_monitor` 谁才有」的可选依赖 | `SecurityRuntime`（`daemon()` / `local()`）一处装配；`ToolGateway` 默认自建 `local()`，`layer4=False` 才关 |
| G2 | `KILL` / `FREEZE` / `ISOLATE` 类威胁只广播、不拦 | 网关只对 `defense == deny` 拒绝 | `layer4_gateway_action()`：deny/kill/freeze/isolate → `Action.DENY`；confirm → `Action.CONFIRM` |
| G3 | 签名误报（`crontab -l`、`systemctl status`、裸 `.ko`、裸 `~/.ssh/`） | 模式只抓关键词，不分「动手 / 看看」 | 收敛为「动手才拦」；真阳/真阴表见 `tests/test_threat_signatures.py` |

### 改动

| 位置 | 改动 |
|---|---|
| `src/trimum_core/sec_executor.py` | 新增 `SecurityRuntime`（`daemon()` / `local()` / `attach()`）：L4 全链路只在这一处装配；`SecAudit(audit_path=None)` = 不落盘（裸 CLI 不碰 `~/.trimum`），默认路径仍是 `~/.trimum/audit/security.log` |
| `src/trimum_core/sec_monitor.py` | `SecMonitor.executor` 允许 `None`（只广播、不产生副作用）；6 组签名收敛（见 G3） |
| `src/trimum_core/tool_gateway.py` | 新增 `layer4: bool = True`：没被注入监控时自建 `SecurityRuntime.local()`；新增 `layer4_gateway_action()`；L4 命中块按映射处置（`confirm` 走 `_prompt_confirm`） |
| `src/trimum_core/main.py` | `init_security()` 改用 `SecurityRuntime.daemon()` + `attach()`，不再手写属性注入 |
| `tests/test_threat_signatures.py` | **新建（28 项）**：17 条真阳 + 11 条只读/自查命令必须零命中（内置剧本自己要跑的那几条也在表里） |
| `tests/test_gateway_layer4.py` | +4（默认网关自带 L4 + 广播 / 不写家目录审计 / `layer4=False` 关闭 / workflow 兜底网关也带 L4）+3（KILL / FREEZE / ISOLATE 执行前拒绝）；必拦样例改成**写** `ld.so.preload`（`cat` 它不再算劫持） |
| `docs/SECURITY-DEFENSE-PLAN.md` §三 | 新增「装配：L4 不是可选依赖」「网关处置：`defense` → 网关动作」「签名收敛：动手才拦，看看不算」三节 |

### 验证

- `python -m pytest tests/test_gateway_layer4.py tests/test_sec_monitor.py tests/test_threat_signatures.py -q` → **54 passed**
- 全量：`python -m pytest tests -q` → **1210 passed / 5 failed / 7 skipped**（+34 为本轮新增；5 项与既有基线逐条一致，无回归）

### 明确不做（取舍）

- **执行后闸门**：真要 `FREEZE` / `KILL` 得等 spawn 后拿到子进程 PID 再扫一次；今天契约里 `pid=0` 的语义就是「没有可动手的进程」，`SecBlocker` 对 `pid<=0` 直接返回。
- **检测与处置分离**（宽签名只上报、窄签名才拦）：今天用「收敛签名」替代 —— 签名宽就只会上报、窄就直接拦，先把误报压到零；真需要宽检测时再拆字段。
---

## 2026-09-21 P0 步骤 3/3：定 `workflow.trigger` 归属（剧本只走 `security.monitor_result`）

> 提交：`f6ecfe4`（server 分支）。**P0 安全响应链至此闭环**（四个提交：`087a476` → `d5393a6` → `dbc411e` → `f6ecfe4`）。

### 问题

两套约定并存：剧本监听 `security.monitor_result`（L4 真发、扁平载荷），而 `SecExecutor` 又
另发一条 `workflow.trigger`（键是 `workflow_name`，与 `WorkflowListener` 的 `cmd` / `tarl` /
`decision` 不同，且当前无人消费）→ 将来只要有人写 `trigger.event_type: workflow.trigger` 的
workflow，同一次威胁就会被两条链各跑一遍。

### 裁决（写进代码 + 文档 + 测试）

| 触发方式 | 事件 / 入口 | 生产者 | 消费者 |
|---|---|---|---|
| **自动（事实）** | `security.monitor_result` | L4 `SecMonitor._dispatch`（唯一） | 内置剧本 + W1 `WorkflowRuntime` |
| 自动（定时） | `cron` | 定时器 | `threat-audit-integrity-check` |
| 意图驱动 | `workflow.trigger` | `WorkflowListener`（TARL 三段式；2026-09-21 步骤 C 起真有人发） | 写了该 trigger 的 workflow（`trm workflow submit` 那条链） |
| 手动 | `runtime.trigger()` / `run_now()` / `trm workflow run <id>` | 人 | `WorkflowRuntime` |

### 改动

| 位置 | 改动 |
|---|---|
| `src/trimum_core/sec_executor.py` | 删掉 `workflow.trigger` 发布（含 import 与常量引用）；模块 docstring 新增「触发归属」；`SecurityRuntime` docstring 的事件清单校正为 `monitor_result` / `alert` / `blocked` |
| `src/trimum_core/workflow_runtime.py` | 模块 docstring 补「触发归属」（谁写什么 trigger 就听什么，运行时不做裁判）；`register_builtin()` 注明触发器是 `security.monitor_result` |
| `src/trimum_core/threat_workflows.py` | 模块 docstring 的旧口径（「通过 `workflow.trigger` 触发」）改为「监听 `security.monitor_result`」 |
| `tests/test_gateway_layer4.py` | **+1 端到端**：L4 拦下命令的同时，总线上的 `monitor_result` 真把注册好的剧本跑起来（1 条运行记录 / `triggered_by=event` / 步骤经网关执行）；两处「发了 `workflow.trigger`」改为断言**不再发**（剧本名改从 `monitor_result` 载荷取） |
| `tests/test_workflow_runtime.py` | **+1**：内置剧本的触发器只有 `security.monitor_result`(15) / `cron`(1)，**没有**任何剧本监听 `workflow.trigger` |
| `docs/SECURITY-DEFENSE-PLAN.md` | §三 新增「触发归属」表；§4.3（SecNotif 不负责触发工作流）与 §五 口径修正 |
| `docs/WORKFLOW-EXECUTION-PLAN.md` | 「`workflow.trigger` 只发不收」与 §6 遗留口径更新为「归属已定、今天无生产者」 |

### 验证

- `python -m pytest tests/test_workflow_runtime.py tests/test_gateway_layer4.py tests/test_sec_monitor.py tests/test_threat_signatures.py -q` → **111 passed**
- 全量：`python -m pytest tests -q` → **1212 passed / 5 failed / 7 skipped**（5 项既有基线，无回归）
- 关键断言（真链路）：`echo evil >> /etc/ld.so.preload` → L4 `status=denied` + `security.monitor_result`
  → `WorkflowRuntime` 命中条件 → shell 步骤经 `ToolGateway` 执行 → `WorkflowRunRecord(status=completed)`

### 仍留一个策略取舍（下一步决定）

内置剧本 `config.enabled = False` 未动：剧本里有 `kill` / `firewall-cmd`，自动触发等于删掉确认环节。
要不要给「只读自查」子集（`threat-cron-audit` / `threat-systemd-audit` / `threat-prelink-check` …）
开自动触发，属于策略决定，记在 `TODO.md`。
---

## 2026-09-21 E5 第一片：`.trmpkg` 包格式 + 打包/校验器

> 提交：`9b40be2`（server 分支）。E5「官方分发渠道」的第一片 —— 先把信任基座做出来，
> 网络与 CLI 留到下一片。

### 做了什么

| 位置 | 内容 |
|---|---|
| `src/trimum_core/trmpkg.py` | **新建**：`build_manifest()` / `create_package()` / `verify_package()` / `extract_package()` / `read_manifest()` + 根与签名者证书工具（`make_root` / `make_signer_cert`） |
| 包结构 | `manifest.json5`（`format` / `name` / `type` / `version` / `requires` / `entry` / `capabilities` / `files{路径: sha256}`）+ `SIGNATURE` + `chain.json` + 载荷 |
| 签名覆盖 | 签名者签 **manifest 的规范字节**；manifest 覆盖每个载荷文件的 sha256 → 改包（含改 manifest 自己）都验不过 |
| 信任链 | 内置根（`config/trust/trimum-root.crt`，只有公钥）→ 根签发签名者证书（`issuer_signature`）→ 签名者签 manifest；证书 `expires_at` 也查 |
| 解包安全 | 拒绝绝对路径 / `..` / 符号链接 / 硬链接 / 设备文件；`extract_package()` 校验不过就不落地 |
| `tests/test_trmpkg.py` | **新建 16 项**：往返 + 能力清单透传 + 四类拒绝（载荷被改 / manifest 被改 / 多带文件 / 换根）+ 路径越界 + 符号链接 + 非 tar 包 |
| `models.py` / `docs/ERROR-CODE-SPEC.md` | 新增 `TRM-4009 PKG_INVALID` / `TRM-4010 PKG_VERIFY_FAILED`（`test_error_codes` 计数同步 65 → 67） |
| `config/trust/README.md` | 只提交公钥证书；根私钥属发布方，永不进仓库；运行态查找顺序 `TRIMUM_TRUST_ROOT` → `~/.trimum/trust/` → 仓库 |
| `docs/ECOSYSTEM-STRATEGY.md` §7.4 | 落地口径 + 两处与早先文档的**有意差异**（`chain.json` 而非 `chain.pem`；只签 manifest 不逐文件签） |

### 验证

- `python -m pytest tests/test_trmpkg.py -q` → **16 passed**
- 全量：`python -m pytest tests -q` → **1228 passed / 5 failed / 7 skipped**（5 项既有基线，无回归）
- 关键拒绝路径（真包，不是 mock）：改 `main.py` 一个字节 → `哈希不符`；改 manifest 版本号 →
  `manifest 签名验证失败`；多塞一个 `backdoor.sh` → `额外文件`；换一把同名根 → `不是本机内置根`
  + `签名者证书不是内置根签发的`；`../evil.sh` → `路径越界`（且拒绝解包）

### 这一片没做（E5 下一片）

`trm pkg verify|create|root-init` CLI、内置根的实际生成与提交（仓库 `config/trust/` 目前只有 README，
所以 `verify_package()` 会明确报「找不到内置根证书」而不是「验过了」）、
`trm install <name>` / `--file <pkg>` 接线、`--allow-untrusted` 降级路径
（装成 `trust: untrusted` + 运行期强制 confirm）、证书 `capabilities` 与 `security_rule.py`
的**运行期交集**（E6 遗留，与本节同源，建议与 `trm install` 一起做）。

---

## 2026-09-21 E5 第二片：`trm pkg` + 真实内置根 + 签名目录索引 + `trm install` + 能力交集

> 提交（server）：`2aec23b` CLI → `5c836e1` 真实官方根 → `2c091c4` 索引 + 安装 → `784992c` 能力交集 →
> `4e29b4e` 文档口径 + requires 探测。E5「官方分发渠道」的**分发面已闭环**：用户侧 `trm install <name>`
> 与发布方 `trm pkg create` 走同一条信任链，信任锚是真的（不再是占位）。

### 做了什么

| 位置 | 内容 |
|---|---|
| `cli/commands/pkg.py` | **新建**：`trm pkg {verify,info,create,extract,root-init,signer-init}`（发布方 3 条 + 使用者 3 条）；`test_cli_pkg.py` 25 项 |
| `config/trust/trimum-root.crt` | **真实官方根**（Ed25519，key_id `sha256:65da4663…`）：只有公钥进仓库，私钥在发布方 `~/.trimum/trust/`；`README.md` 重写，3 项内置根测试 |
| `src/trimum_core/pkg_index.py` | **新建**：目录索引 `trmindex/1`，容器 `{document, signature, chain}`，签名覆盖 document 规范字节，证书链与包**共用** `verify_chain()` |
| `src/trimum_core/pkg_install.py` | **新建**：校验 → 按 `TYPE_ROOTS` 落地（agents / tools / workflows / skills）→ 登记 `~/.trimum/config/installed.json5`；agent 包写 `cert.json`（official → TRUSTED / untrusted → CONFIRM） |
| `src/trimum_core/capability.py` | **新建**（E6 遗留）：能力交集 `evaluate()` / `tighten()`，多来源取最严，只收紧不放宽；`test_capability.py` 20 项 |
| `tool_gateway.py` Layer 2.6 | L2.5 之后、L4 之前 `_check_capabilities()`：deny → `capability_denied` 审计并拒绝；confirm → `Action.CONFIRM`；三处重复弹窗收敛为 `_confirm_interactively()` |
| `models.py` / `docs/ERROR-CODE-SPEC.md` | 新增 `TRM-4011 PACKAGE_NOT_FOUND`（总数 67 → **68**） |

### 关键设计（写进代码与测试）

- **索引也是签名文档**：索引回答「去哪拿这个包」，所以它没有豁免 —— 索引与包对「什么算可信」不可能有两种解释。
- **索引条目的 `sha256` 是承诺**：下载后先比哈希再进校验，不一致直接拒，不进解包流程。
- **安装三动作**：校验 → 落地 → 登记（trust / 签名者与根指纹 / 包哈希 / 来源 / requires / 能力块）。
- **`--allow-untrusted` 只放宽「来源」**：包的证书链与索引签名放宽，运行期额外强制逐条 confirm；
  但包内绝对路径 / `..` / 符号链接 / 硬链接 / 设备文件**照挡**。
- **`requires` 只探测不判死**：缺依赖只警告（与 `AgentRegistry.check_dependencies` 同口径）——
  装不装得到是环境的事，不是包的问题。
- **风险取管线判定值**：Layer 2.6 用的是 PolicyEngine / LLM 策略给出的 `risk`，不是执行后的观测值 ——
  `max_risk` 挡的是「策略认为有多危险」，不是「实际有多危险」。
- **私钥红线**：`root-init` / `signer-init` 拒绝把私钥写进 git 工作树（除非 `--insecure-key-output`），落盘 0600。

### 验证

- 新增测试：`test_cli_pkg.py`（25）、`test_pkg_install.py`（28）、`test_capability.py`（20）、`test_trmpkg.py`（16）→ 四文件 **89 passed**
- 全量：`python -m pytest tests -q` → **1301 passed / 5 failed / 8 skipped**（5 项既有宿主基线，无回归）
- 命令面：`trm commands --check` → **76 commands, no problems**
- 关键路径（真包 / 真根 / 真索引，非 mock）：用真实签名者打的包 `trm pkg verify` **不带任何参数即通过**；
  载荷改一字节 / 改 manifest / 换根 / 索引 sha256 不符 / 相对 url 越界，逐条拒绝；
  `trm install --list --json` 能回读登记，缺依赖走警告而非拒装。

### 这一片没做（E5 第三片）

`trm install --remove`（卸载 + 注销登记 + 删 agent 证书）、官网服务端与目录托管
（`DEFAULT_INDEX_URL = https://trimum.dev/packages/index.json5` 仍是占位；发布流程可先用 `trm pkg create`
+ 本地索引跑通）、多用户边界（`/etc/trimum` vs `~/.trimum`，`docs/ECOSYSTEM-STRATEGY.md` §7.2）、
`requires` 只探测不解决（缺依赖仅警告）。

## E5 第三片（✅ 步骤 1 卸载 + 步骤 2 发布方闭环 + 步骤 3 多用户边界，2026-09-21）

> 计划与红线：`TODO.md`「🚚 E5 第三片实施计划」；口径：`docs/ECOSYSTEM-STRATEGY.md` §7.6、
> 模块与红线：`docs/ARCH.md`「官方分发渠道（E5）」。
> 提交：步骤 1 `d7aced2`（`trm install --remove`）、步骤 2 `fcecbfe`（`trm pkg index`）、步骤 3（纯文档，见下表）。

**做了什么**：`trm install --remove <name>` —— 与 `--list` 对称，不新增顶层命令（命令面仍是 76）。
两个动作成对：删掉 **ledger 指名的**落地目录 + 划掉登记行，不留「目录没了但还登记着」的半截状态。

**两条红线（越界就一个字节都不删，报 `TRM-4009`）**

| 红线 | 为什么 | 怎么判 |
|---|---|---|
| 登记路径越界即拒 | `installed.json5` 是可手改的文本，「登记里的 path」不作数 | 只有恰好等于 `<TRIMUM_HOME>/<TYPE_ROOTS[type]>/<name>` 才动手（比「落在类型根下」更严） |
| 内置 agent 名字即拒 | `install_package(force=True)` 可能覆盖过内置 agent 目录，登记里没记「装之前 dest 在不在」 | 命中 `discover_bundled_agents()` 的 agent 包即拒并提示手工处理；**只管 agent**，同名 tool 可卸 |

**确认口径**（沿用 `trm env install`）：交互式问一句；非交互必须 `--yes`（`ask_confirm` 在非 TTY 直接答 no，
不挂住），否则 abort → 退出码 1；`--dry-run` 恒不执行，但**红线照查**（干跑说「可以删」之后真删却被拒，比不干跑更糟）；
`--remove` 与 `--file` 互斥；`--yes` / `--dry-run` 只作用于包渠道，不影响无参数的旧向导路径。

**边界与联动**：卸载**不看** `trust`（不是授权动作），但删掉降级安装的包之后 `untrusted_names()`
（`capability.py` 运行期读的就是这张表）同步不再含它；名字没登记过 → `TRM-4011` + 退出码 1（连删两次，
第二次明确报错，不静默 0）；登记目录已不在 → 当**过期登记**划账并回报 `path_missing`，不崩在 `rmtree` 上；
不碰 `certs/` / `audit/` / `memory/`（agent 证书就是包目录里的 `cert.json`，随目录一起走）。
错误码**复用 `TRM-4011`，不新增**。

**测试**：`tests/test_pkg_install.py` 28 → **42**（`TestRemove` 14 项：越界 ledger 两种 / 内置 agent 拒删 /
同名 tool 可卸 / 干跑不动盘不动账 / 幂等连删 / 非交互 abort / `--file` 互斥 / 缺名字 / 过期登记 / 运行期联动）。
全量 **1315 passed / 5 failed / 8 skipped**（5 项 = 既有宿主基线：沙箱写 `~/.trimum` 被拒 ×4 + LLM 断网 ×1，无回归）。

### 步骤 2 — 发布方闭环（`trm pkg index`）

**做了什么**：`trm pkg index <dir> -o index.json5 --signer-cert … --key …` —— 发布方闭环的最后一步：
扫目录里的 `.trmpkg` → 生成 `trmindex/1` document → 用签名者签 → 落盘（命令面 76 → **77**，
新码在 `pkg_index.entries_from_directory()`，CLI 只做接线）。四条口径：

| 口径 | 为什么 |
|---|---|
| 只收录**验得过**的包，一个不过就整体失败并逐条列原因、**不写索引** | 「悄悄少一个包」比「报错」危险得多 |
| 字段取自**校验过的 manifest**，不是文件名 | 文件叫什么 ≠ 包里写的是什么 |
| `url` **相对索引位置**（`/` 分隔，支持子目录） | 索引与包同目录即可离线安装（`resolve_url` 解析） |
| **写完自检**：刚签出来的索引就地验一遍（签名 + 证书链） | 否则「签名」只是自我安慰 |

`--force` 才能覆盖已存在的索引；**改一个包就要重签索引**（条目里的 `sha256` 是索引对包的承诺）。

**验收（按计划原样达成）**：`trm pkg index dist/` → `TRIMUM_PKG_INDEX=dist/index.json5 trm install <name>`
一条链跑通 —— `tests/test_pkg_install.py::TestInstallFromIndex::test_an_index_built_by_the_cli_installs_end_to_end`
（发布方用 CLI 造索引 → 使用者用该索引装包 → 落地并登记）。

**官网服务端仍不做**（域名 / 托管 / CI 属产品决策）：本步骤交付的是**可离线复现的发布闭环 + 运维手册**
`docs/PACKAGE-CHANNEL-OPS.md`（造根 → 建签名者 → 打包 → 建索引 → 上线 → **轮换根**（换根 = 旧包全部作废）→
内网镜像（`--index` 指过去，镜像不需要被信任）→ 出问题对照表 → 边界）。

**测试**：新增 11 项（`tests/test_cli_pkg.py::TestIndex` 10：条目承诺 / 改 url 验不过 / manifest 说了算 /
子目录相对 url / 验不过的包拒收 / 空目录拒收 / `--force` / 缺签名材料 / 跨根签名者 / 人读输出；
外加上述端到端 1 项）。全量 **1326 passed / 5 failed / 8 skipped**（5 项 = 既有宿主基线，无回归）。

### 步骤 3 — 多用户边界（调研 + 设计，**不改代码**）

**交付**：`docs/MULTI-USER-BOUNDARY.md`（现状对照表 / 三个问题各带方案 / 六条不变量 / 实现顺序与风险）；
`docs/ECOSYSTEM-STRATEGY.md` §7.2 改为定稿指针并新增 §7.8；`docs/ARCH.md` 与 `AGENTS.md` 文档地图同步。

**复核结论：现有设计没有硬伤，因此不动代码。** 「每用户一份」在这个仓库里是**结构上成立**的 ——
每个关注点都只有一个改点，不是散落的路径拼接：

| 关注点 | 唯一改点 | 多用户下会怎样 |
|---|---|---|
| 用户数据根 | `paths.trimum_home()`（`TRIMUM_HOME` 可覆盖） | 家目录天然每用户一份 ✓ |
| 身份私钥 | `identity.py`（POSIX 0600） | POSIX 够用；**Windows 上 `chmod` 不产生 ACL** |
| 配置 / 策略 | `config.py` 的 XDG 路径（`--config /etc/trimum/config.yaml` 已能用） | 缺「系统默认 → 用户覆盖」的合并规则 |
| 审计 | `audit_store.default_audit_path()` | **`AuditEvent` 没有 `user_id`**：分不清是谁做的 |
| 运行时 socket | `config.default_socket_path()`（按 uid） | **已经 per-uid**，这层不用重做（好先例） |

三个问题的方案（明细见文档 §2 / §3 / §4）：

1. **`/etc/trimum/` 只放公开物**：官方信任根 / 系统策略基线 / 系统配置基线 / 可选共享包；带私钥或带个人数据的
   一律只能进用户层。查找顺序 = `~/.trimum/<type>/` → `/etc/trimum/<type>/` → 内置，同名以**用户层为准**；
   公共层只读（用户进程不写），共享安装需要第二张账 `/etc/trimum/config/installed.json5`。**迁移成本低**：
   新增 `paths.system_home()` + 三处查找改成有序列表，**写入路径一个都不动**。
2. **审计 `user_id` + `machine_id` 三步**：加字段（纯增、向后兼容）→ 允许配置指向共享审计文件（默认仍写自己
   的）→ 系统模式下用 `SO_PEERCRED` / 命名管道 SID 交叉校验。**不整体搬去 `/var/log`** —— 那会破坏
   「审计是旁路、写失败不影响执行」这条既有取舍。
3. **私钥保护三档**：A 现状 + 告警 / B 文件权限收紧（Windows 用 ACL）/ C keyring·DPAPI。建议先 **B**、
   **C 作可选后端**；红线不变（私钥不进公共层 / 仓库 / 日志）。

**为什么不改代码**：计划写的是「除非发现现有设计有硬伤，否则不动代码」。逐条查下来，socket 已按 uid 分目录、
`agents/<name>/cert.json` 已把「来源 + 证书 + 版本 + 登记」捆在最小单位、`installed.json5` 每用户一份够用 ——
没有一条是「现在就必须拆」的。多用户真正缺的是**产品决策**（账号体系 / 团队共享）与**系统公共层**，
两者都不该在没有需求时先写实现。

**测试**：本轮只加文档，全量仍 **1326 passed / 5 failed / 8 skipped**（5 项 = 既有宿主基线，逐条相同，无回归）。

### 提交与分支

> 分支纪律见 `AGENTS.md`：**日常只推 `server`**，`main` / `ubuntu` / `arch-linux` 只在收尾阶段同步。

| 内容 | server |
|---|---|
| E5 第三片 步骤 1（`trm install --remove` + `TestRemove` + 文档 §7.6） | `d7aced2` |
| E5 第三片 步骤 2（`trm pkg index` + `TestIndex` + `docs/PACKAGE-CHANNEL-OPS.md` + 文档 §7.7） | `fcecbfe` |
| E5 第三片 步骤 3（多用户边界：调研 + 设计，**不改代码**；`docs/MULTI-USER-BOUNDARY.md` + 生态战略 §7.2/§7.8 + ARCH / AGENTS 指向） | `8646fe7` |
| 穿插项 步骤 A（剧本自动触发策略：取证 8 条武装 / 处置 8 条不武装 / 自动触发不派子 Agent） | `d5d4b02` |
| 穿插项 步骤 B（总线硬化：索引接线 / 失败可观测 / 严格模式 / 订阅修正） | `dd3c0a2` |
| 穿插项 步骤 C（`WorkflowListener` 接线：`submit()` 当生产者 + daemon 装配 + `trm workflow submit`）+ 两个真 bug | `f51b86d` |

---

## 2026-09-21 穿插项步骤 A：剧本自动触发策略（✅ 已完成）

> 计划：`TODO.md`「🔧 穿插项实施计划」步骤 A。问题源头：P0 把「L4 → 总线 → 剧本」接通了，
> 但 16 条内置剧本 `config.enabled=False` + `register_builtin(enabled=False)` 双重压死 ——
> **一条剧本都没武装**，真机上仍然不会自动响应。

**查代码得到的关键事实**：剧本步骤是「命令 + 散文」混合的 —— 命令式步骤（`cat /etc/ld.so.preload`）
走网关，散文式步骤（「比对上次 hash 基线」/「kill 对应 PID」）**派子 Agent**。子 Agent 会干什么
不由剧本决定，**所以「只读剧本」不等于「只读运行」**，自动触发必须按步骤放行。

**裁决三条**

| 裁决 | 落地 |
|---|---|
| 取证类 8 条武装（prelink / ebpf / kernel / crypto / ssh / cron / systemd / memfd） | 数据位 `auto_trigger: True` → `config.enabled` 跟着它 |
| 处置类 8 条不武装（revshell / ransomware / btrfs / persistence / supply-chain / prompt-injection / audit-integrity / pipe-download） | `auto_trigger: False`：处置要人点，不做「半自动处置」（会制造「已经响应了」的错觉） |
| 自动触发不派子 Agent | 事件运行里非取证步骤 `skipped`（`task.node.skipped`，`reason=auto_run_blocked:<kind>`）；人工 `run` 不受限 |

**判据**（`threat_workflows.step_kind()`）：`auto`（**只读取证白名单命令**，白名单外一律不自动跑）/
`review`（要判断的散文）/ `action`（处置：散文含处置动词，或命令不在白名单 / 带 `-delete`·`>`）；
**看不懂的散文一律当 `action`**（保守）。红线：`enabled` 只决定「事件要不要跑」，**不能**放宽步骤闸门。

**改动面**：`threat_workflows.py`（16 条数据位 + 三分类 + 编译时把 `step_kind`/`auto_run` 写进节点 config）、
`workflow_runtime.py`（`register_builtin(enabled=None)` / `register_all(builtin_enabled=None)` 改按剧本自己的位；
运行上下文补 `triggered_by`）、`workflow_engine.py`（`_auto_run_block()` 闸门，`auto_run` 缺省 True）。

**测试**：新增 `tests/test_playbook_auto_trigger.py`（40 项：三分类参数化 / 数据位与步骤性质双向一致 /
武装剧本无处置步骤 / 节点带闸门 / 事件运行只跑取证 / 处置剧本事件不唤醒 / 人工运行不受限 / 强制全关全开）；
改 3 处旧断言（`test_workflow_runtime.py` 两条 + `test_api_server_startup.py` 一条 —— 它们锁的正是旧口径），
`test_gateway_layer4.py` 的端到端步骤改成取证命令。全量 **1365 passed / 5 failed / 8 skipped**（5 项 = 既有基线）。

---

## 2026-09-21 穿插项步骤 B：总线硬化（✅ 已完成）

> 计划：`TODO.md`「🔧 穿插项实施计划」步骤 B。问题源头：2026-09-20 的只读总线审计 ——
> `_safe_call` 静默吞订阅者异常（`TRM-9005` 全库无人 raise）、`EventIndex` 没接进 `publish`、
> `LiveConsole.subscribe_events` 订阅与比对不匹配（进度永远不亮）。

| 缺口 | 落地 |
|---|---|
| 订阅者异常静默 | 记 `WARNING` 日志（订阅者名 + 事件类型 + 堆栈）+ `dispatch_failures` 计数 + `last_failure` 快照 + 广播 `event.eventbus.dispatch_failed`（它自己再失败只记不播，防转圈） |
| `TRM-9005` 没人 raise | 严格模式（`TRIMUM_BUS_STRICT=1` 或 `EventBus(strict=True)`）抛 `TrimumError(TRM-9005)`，由 `await bus.wait_for_handlers()` 收集（`publish` 是 fire-and-forget，异常得有地方收）；默认关 |
| `EventIndex` 没接线 | `publish` 走首段分桶索引；通配匹配实现收敛到 `event_index.matches()` 一处（`EventBus._matches` / `EventIndex._matches` 都转发它）。**workflow 触发器口径仍故意分开**（剥 `event.`/`task.` 前缀 + `fnmatch`），两条都由测试钉住 |
| `LiveConsole` 不亮 | 改按**段**匹配（`task.node.started` / `task.workflow.started` 都算 `started`）；同一步骤的重复事件去重（直接调用与事件订阅会撞车）；**补订 `security.*`** —— 告警分支以前从没被喂到过 |
| SDK 侧错用法 | `src/agent-sdk/trimum_agent.py`：`publish("tool.executing", {...})` → `emit_event("tool.executing", "agent-sdk", {...})`；异常从 `pass` 改成记日志 |

**观测面**（排障用）：`bus.stats()`（patterns / subscribers / history / in_flight / dispatch_failures / strict）
与 `await bus.wait_for_handlers(timeout=...)`。

**测试**：新增 `tests/test_event_bus.py`（103 项：通配口径三处一致 + 索引与旧「整表扫描」逐条等价 +
失败可观测 / 严格模式 / 退订同步索引 / `stats`）+ `tests/test_live_console.py`（7 项：进度按段点亮 / 重复去重 /
告警两种前缀 / 退订停订 / 无总线只告警）。全量 **1475 passed / 5 failed / 8 skipped**（5 项 = 既有宿主基线）。
文档：`docs/ARCH.md` 新增「事件总线（`event_bus.py`，2026-09-21 硬化）」一节；`docs/ERROR-CODE-SPEC.md` 的
`TRM-9005` 补接线说明。

---

## 2026-09-21 穿插项步骤 C：`WorkflowListener` 接线（✅ 已完成）

> 计划：`TODO.md`「🔧 穿插项实施计划」步骤 C。问题源头：W1 遗留 —— `WorkflowListener` 从未被实例化，
> `event.transform.completed` 没有生产者，`workflow.trigger` 没有生产者，整条「意图驱动」链是摆设。

### 做了什么

| 位置 | 改动 |
|---|---|
| `workflow_listener.py` | 新增 `async def submit(instruction) -> TransformResult`：变换 Agent 翻译 → `emit_event("transform.completed", ...)` 发回**同一条总线**（不搞旁路），成为该事件的唯一生产者 |
| 同上 | 删掉拼错的死订阅（`task.task.completed` / `task.task.failed` —— 前缀多了一个 `task.`）+ 两个孤儿处理函数 + `_pending_sub_tasks`；订阅表只剩真类型 |
| 同上 | **红线**：`_request_confirm()` 从「没有确认回调就默认放行」改为**拒绝**（`listener.no_confirm_callback_denied`）—— 没装确认通道不能悄悄变成自动批准 |
| `api_server.py` | 启动时装配（失败只记 `workflow_listener_start_failed`，不带崩 daemon）、停机先于 workflow 运行时收；状态挂 `ServerState.workflow_listener` |
| `workflow_runtime.py` | 新增公开属性 `gateway`（listener 复用**同一**网关，不新建第二条执行通道） |
| `cli/commands/workflow.py` | 新增 `trm workflow submit "<指令>"`（`--root` / `--timeout` / `--yes`），命令面 77 → **78**；非交互必须 `--yes` 才自动确认中匹配 |

### 顺手修的两个真 bug（测试跑出来的，不是猜的）

| bug | 后果 | 修法 |
|---|---|---|
| 日志器用错：`logging.getLogger(...)` 被当 structlog 用 | 每次 `log.info("x", k=v)` 都抛 `TypeError`，又被总线当时静默的 `_safe_call` 吞掉 —— 这个文件等于从不记日志 | 改用 `logger.get_logger` |
| `_execute_shell()` 的 `ExecuteRequest(tool_type=..., command=..., raw_input=...)` 字段名全错 | 真字段是 `tool` / `args` / `raw_command`，pydantic 默认忽略多余字段 → 命令**静默变空** | 按真字段构造（`args=[shell_cmd]` + `raw_command`），并补 `SourceType` |

另：`PlannerAgent` 默认剧本目录是 `Path.home()/.trimum/workflows`（**不看 `TRIMUM_HOME`**，会踩沙箱 / 多用户），
daemon 与 CLI 都显式传 `trimum_path("workflows")`；低匹配转 Planner 那条路（`planner.task_created` → `workflow.trigger`）随之真正有人听。

### 三段式（写进测试）

| confidence | 行为 |
|---|---|
| ≥ 0.7 高 | 发 `workflow.trigger`（`decision=high`）→ 运行时唤起写了该 trigger 的剧本 |
| 0.4 ~ 0.7 中 | 有回调且同意 → `decision=confirmed` 触发；无回调 → **不发**；拒绝 → **不发** |
| < 0.4 低 | 转 Planner（`decision=planner`）；没有 Planner 时只留 `transform.completed`，不假装触发 |
| `output_type=shell` | 直接走 `ToolGateway`（`args=[命令]` + `raw_command`），被拒时另发 `shell.denied` |

**测试**：新增 `tests/test_workflow_listener.py`（12 项，含**端到端**：一句自然语言 → 变换 → `workflow.trigger`
→ 文件剧本真的跑起来，节点 ok 且网关收到命令）+ `test_api_server_startup.py` 一条（daemon 装配 Listener）
+ `test_cli.py` 一条（`workflow submit` 解析出 handler）。
全量 **1489 passed / 5 failed / 8 skipped**（5 项 = 既有宿主基线）。文档：`docs/ARCH.md`、
`docs/WORKFLOW-EXECUTION-PLAN.md`、`docs/SECURITY-DEFENSE-PLAN.md`（触发归属表）。

---

## 2026-09-21 E7 规格与设计：自研编码智能体（草案，待裁决）

> 提交：`36fedb7`（server 分支）。立项依据：`TODO.md`「🌐 生态战略」E7 项；本轮**只写文档，不改代码**。
> 产物：`docs/CODING-AGENT-PLAN.md`（规格 + 设计 + 五步分片计划）。
> 同轮修正一处口径冲突：`docs/ECOSYSTEM-STRATEGY.md` §5 的 **E7** 原写作「身份与多用户」，
> 那份内容已由 E5 第三片（能力清单运行期交集）+ E6（官方 Agent 证书）+ `docs/MULTI-USER-BOUNDARY.md` 落地，
> 故 E7 让位给「自研编码智能体」（修订说明写进该文档）。

### 结论：缺的不是引擎，是编码专用的三块拼图

| 缺口 | 现状（查代码得到） | 要补 |
|---|---|---|
| 编辑原语 | `file.write` 只能整文件覆盖 / 追加（`mode=w` / `a`）；全库无 `difflib`、无补丁应用 | 锚点替换 + 统一差异应用 + 会话级快照与回滚 |
| 验证闭环 | 没有「跑测试 / 构建 / 检查并解析结果」的一等抽象，循环只拿到原始标准输出 | 结构化「红 / 绿 + 失败清单」回灌循环 |
| 技能与规则运行时 | `SKILL.md` 只被分发到别的宿主；`skill.yaml`（旧）与 Agent Skills（新）两套互不相干 | 命中才注入上下文 + 工具事件上的检查（钩子） |

外加第四块：`agent_runtime` 的 spawn 仍是空壳、`task.assigned` 至今没有生产者 ——子 Agent 委派做实。

### 参考对象 ECC 的事实（不是印象）

快照 2026-09-20（262,999★，MIT）：仓库 5,026 条目、`SKILL.md` **903** 个、`rules/` 144 个文件、
斜杠命令 94、宿主适配目录 `.claude-plugin` / `.codex` / `.opencode` / `.cursor` / `.kiro` / `.agents` 等、文档 2,141 个。
**关键判断：ECC 没有自己的模型循环**（循环与工具执行由宿主提供），它卖的是内容分层 + 工具事件钩子 + 安装适配 + 学习记忆。
抄：按需加载省上下文 / 工具事件上的检查 / 跨宿主记忆交接 / 内容与运行时分离；
不抄：903 个技能的内容农场、Node 适配层、钩子以特权脚本裸跑（trimum 的等价物是总线订阅 + 经网关的动作）。

### 红线（拟，写进后续代码与测试）

一切经 `ToolGateway`（不新增旁路）／改动必须能回滚（无差异不算成功）／保护路径直接拒／
不自动提交版本库／测试不过不许声称完成／子 Agent 取权限交集且受限预算／技能是数据不是代码／没有模型就说没有。

### 五步分片（每片独立可验收）

1. 编辑原语与会话留痕（`patch_ops.py`，含 `--dry-run` 差异预览与回滚）
2. 验证闭环（`verifier.py`，含「被网关拒时结论必须是 unknown 而非 green」）
3. 技能与规则运行时（`instruction_loader.py` + 总线式钩子，首批三条流程：测试驱动 / 代码审阅 / 排障）
4. 子 Agent 委派做实（spawn + `task.assigned` + 权限交集 + 预算 + 审计）
5. 命令行入口与真机验收（`trm code`，命令面 78 → 79；`scripts/accept_e7.py` 五组）

**裁决（更新）**：① 沙箱（Landlock / Seccomp）是否提到编码智能体之前 —— **已定为「是」**，见本文「2026-09-21 沙箱前置片」与 `docs/SANDBOX-PLAN.md`（新增四条待裁决在该文 §9）；
② 首发是否允许自动改盘 + 自动跑测试 —— **仍未定**（草案建议：默认出差异 + 跑只读验证，写盘要确认，`--yes` 才自动落盘）。

---

## 2026-09-21 编码智能体调研：ECC 适合吗？（✅ 已完成，**只调研不改代码**）

> 用户提问：① ECC 如何做成一个 coding Agent；② 参考 `~/.trimum/agents/` 别的 Agent 的文件格式；③ 还有没有其他可直接复用的开源项目；④ **先想 ECC 适合吗**。
> 产出：`docs/CODING-AGENT-REUSE-RESEARCH.md`。事实层材料 `tmp/research/coding-agents/`（19 个仓库快照 + aider 源码 30 件 + 两份事实草稿，均已 gitignore）。

**结论：ECC 不适合做成 coding Agent。** 它没有可复用的执行体 —— 68 个 `agents/*.md` 是提示词、292 个技能是文本、
hooks 是「宿主事件 + node 命令」，**ECC 自己就是 Claude Code / Codex 的插件包**（`.claude-plugin/plugin.json`、`.codex-plugin/plugin.json` 都在树里）。
三条路径逐条算过账（该文 §2）：包成 trimum 子 Agent → **空壳**（`AgentManifest` 里只有 `name`/`description` 对得上，
`entry`/`capabilities`/`permissions`/`events`/`risk_level` 全无对应，且 `system_prompt_path` 在代码里**零消费者**）；
当内容注入 → **唯一成立的用法**（正对 E7 步骤 3）；接它的代码 → 只换来 Node + Rust 依赖。

**三处数字修正（原文档虚高，勿再引用）**：`SKILL.md`「903」是重复计数 → 真实 **292**（另有 `docs/` 译本 518 + 宿主目录副本 93）；
「30+ 宿主」是**另一个项目 rulesync** 的自述，ECC 自述 **7 个 harness**；`docs/` 2,141 个文件大半是译本。
star:watcher = 194.8，与同类同区间（superpowers 267.8 / rulesync 728.0 / anthropics-skills 157.3）→ **「刷星」这条不成立**，如实记录。

**另一件已经做完的事**：ECC 的核心分发机制 trimum 早已实现 —— `skill_sync.py` + `hosts.py` 的 **14 个已知宿主**（覆盖 ECC 全部宿主目录）
+ 探测 + 符号链接/junction，代码注释写着 *"the wider set of ECC-style harnesses"*。**这块不用再学第二遍，差的只是内容。**

**可直接复用的清单（很短）**：`python-unidiff`（统一差异解析，MIT、活跃、只 parse 不 apply → 可直接依赖）；
`grep-ast`（代码感知检索；366★、约 16.5 个月未推、带 tree-sitter 两个依赖）；其余**抄设计**（aider / gptme / cline / crush / opencode）。
不建议接：Roo-Code（已 archived）、continue（自称 read-only）、python-patch（4 年 8 个月未动 + 无许可）、SWE-agent（官方指向 mini-swe-agent）、
codex / goose（README 无部件级信息）、bubblewrap / nsjail（Linux 内核特性，Windows 无对应）。

**对 E7 的建议（待裁决）**：参考对象由 ECC 换成 **aider**（13 种编辑格式、`max_reflections=3` 的错误回灌、
`search_replace.py:438-439` 唯一性检查被注释掉的设计张力、`auto_commit` 早于 `confirm_ask` 的红线冲突）；`TODO.md` E7 条目已同步改口径。**本轮未改任何代码。**

---
## 2026-09-21 沙箱前置片：把内核级边界提到 E7 之前（调研 + 真机实测 + 脚本，✅ 方向已定）

> 裁决落地：原「**沙箱是否提到编码智能体之前**」**已定为「是」** —— 编码智能体会大量写盘、跑测试，
> 没有内核级边界就不敢让它自己动手。本轮**只写文档与脚本，未改代码、未装任何包、未重启任何服务**。
> 产物：`docs/SANDBOX-PLAN.md`（10 节）、`scripts/setup_ubuntu_toolchain.sh`、`scripts/check_sandbox_caps{,_root}.sh`。
> 原始材料：`tmp/research/sandbox/`（143 份一手材料 + `draft-C-sandbox.md` 651 行）。

### 四个问题的答案

| 问题 | 答案 |
|---|---|
| 主流沙箱怎么做 | **三层收敛**：① **策略层**（谁能做什么 —— K8s Pod Security Standards 的 Restricted 档要求 `seccompProfile: RuntimeDefault`、`capabilities.drop: [ALL]`、`allowPrivilegeEscalation: false`，且明确标注 **Linux-only**）；② **内核层**（Landlock LSM / seccomp-bpf / AppArmor / namespace / cgroup v2）；③ **边界层**（换运行时拿更强边界：OCI 容器 → gVisor `runsc` → microVM Firecracker）。**接口收敛在 OCI runtime-spec**（namespace / seccomp / cgroup / maskedPaths 都是可移植字段）；所谓「沙箱」多数 = 内核层机制组合 + 一份默认 profile（Docker 默认 seccomp 是 `SCMP_ACT_ERRNO` 白名单，300+ syscall 里默认挡掉约 44 个） |
| 需不需要 Docker | **不进主干**：① 粒度不匹配 —— 要的是**每次工具调用**的边界，Docker 给的是**整容器**的边界（每次 spawn 一个容器太慢）；② 会成**第二条执行通道**，与「一切动作经 `ToolGateway`」红线冲突；③ 真机已装（29.8.1）但**本地 0 个镜像**，用一次就要拉网。**留作 Phase 5**：隔离不可信第三方 Agent 包 |
| 真机能不能做 | **能，而且不需要 root**：Landlock **ABI=4** 已实测可拦（40 行 ctypes PoC）；seccomp 走自带 `libseccomp 2.5.5`（ctypes 可加载）；资源边界走 systemd 用户级 cgroup 委派 |
| 还需装什么 | 沙箱主干（Landlock + seccomp + systemd 用户级 + cgroup）**几乎零新依赖**；要装的是「把 C/BPF 侧做扎实」与「写脚本 / 排障」那批（清单见 `docs/SANDBOX-PLAN.md` §7.1，core 档 13 项真机已装 3 项、待装 10 项） |

### 真机实测（Ubuntu 24.04.1 / kernel 6.8.0-41-generic / systemd 255 / 8 核 7.4G / 854G 可用）

| 结论 | 依据 |
|---|---|
| Landlock **非特权可拦** | 纯 ctypes 三个 syscall（444/445/446）+ `prctl(PR_SET_NO_NEW_PRIVS)`：`/` 只读 + 一个目录全权限 → 允许路径可写、**写 `$HOME` 得 `EACCES`**、只读路径可读不可写、**跨 `execve` 继承**（子进程也被拒）、只能收紧不可逆 |
| systemd 用户级**真生效** | `NoNewPrivileges`（`NoNewPrivs: 1`）、`SystemCallFilter`（`Seccomp: 2`、`Seccomp_filters: 3`）、`MemoryMax` / `CPUQuota`（单元内 `memory.max=33554432`）、`PrivateUsers=true`（userns inode 变化、`CapEff: 0`） |
| systemd 用户级**静默 no-op**（决定性） | `ProtectSystem=strict` / `ProtectHome=read-only` / `PrivateTmp=yes`：三类单元（单独 / 组合 / 加 `PrivateUsers=true`）的 `/proc/self/mountinfo` **条目数全是 47 = 宿主** —— **根本没建 mount namespace**；`$HOME` 照写成功、宿主能看到单元写进 `/tmp` 的文件 |
| 非特权 userns 被禁 | `kernel.apparmor_restrict_unprivileged_userns=1` → `unshare --user/-m/-n` 与 `bwrap`（`setting up uid map: Permission denied`）全拒 → bubblewrap / rootless 容器 / podman / nsjail 当前**都不可用** |
| eBPF 非特权不可用 | `kernel.unprivileged_bpf_disabled=2` → `security.ebpf_alert` 在 daemon 当前运行方式（`User=guzhujushi`）下**不可能工作**，**校正** `docs/SECURITY-DEFENSE-PLAN.md` 把 eBPF 当常规手段的前提 |
| cgroup v2 统一层级 | 用户 slice 委派 `cpu memory pids`；普通用户**不能**直写 `/sys/fs/cgroup` |
| daemon 现状 | `/etc/systemd/system/trmd.service` **零加固**（只有 `User=guzhujushi` + `WorkingDirectory=/opt/trimum`）；`/run/trimum` 不存在 → RPC 走 HTTP 回退 |

**踩坑（已写进纪律）**：第一轮用 `systemd-run --user -p ...`（**不带 `--wait`**）测沙箱，因竞态误判成「拦住了」。
**唯一可信口径是 `systemd-run --wait --pipe`。**

### 三个脚本（未装任何包；真机 `sudo` 需要密码，root 那个只能本人跑）

| 脚本 | 需要 sudo | 真机状态 |
|---|---|---|
| `scripts/setup_ubuntu_toolchain.sh` | 是（默认 dry-run；`--apply` 才装；`--tier` 选 core / ops / optional / all） | 已传 `/tmp/`（sha256 与本地逐字一致）；dry-run 跑通：**tier=core 13 项已装 3、待装 10** |
| `scripts/check_sandbox_caps.sh` | 否 | 已跑通 **PASS=8 WARN=6 FAIL=0** |
| `scripts/check_sandbox_caps_root.sh` | 是 | **本轮核实：上一轮其实没传上去**，本轮已补传（sha256 与本地一致）；**未跑** —— 真机 `sudo` 需要密码 |

### 设计要点（`docs/SANDBOX-PLAN.md` §6 / §8）

- 新增**内核层**（Layer K），与既有四层网关**串联不并列**：内核层只做「施加 + 如实记录」，不做决策；**fail-closed**（沙箱没装上就不许执行）。
- 六个 spawn 点必须收口到新封装 `sandbox_exec`：`tool_dispatchers.py:641,389,502,507,525,530` + `agent_launcher.py:132`。
- 三档档案 `readonly` / `workspace-write`（默认）/ `strict`，声明在 `agent.json5` 的 `sandbox` 段（既有设计已有 `seccomp_profile` / `extra_syscalls` / `extra_block`，加 `fs_read` / `fs_write` 即可）；`AuditRecord.sandbox` 字段已存在（`models.py:749`）。
- **Windows 降级**：明确报 `unsupported`，绝不允许「不知道就放行」。
- 分片：**S1** daemon 加固 → **S2** 施加点收口（Landlock）→ **S3** seccomp 三档 → **S4** 子 Agent 走 systemd transient → **S5** 可选档（等裁决）。

### 待裁决四条 —— **已于同日全部裁决**（见上一节「S1：daemon 系统级加固」）

1. eBPF 提权 → **CAP_BPF + root helper**；2. 非特权 userns → **不全局放开**，定向给 `bwrap` 写 profile；
3. Docker 档 → **Phase 5**；4. daemon → **保持非特权 + 加特权 helper**。
新增待裁决三条见 `docs/SANDBOX-PLAN.md` §9.2（HTTP 端口收口 / `@debug` 取舍 / `ReadOnlyPaths` 是否保留）。

---

## 2026-09-21 S1：daemon 系统级加固（脚本就绪 + 冒烟 + 自动回滚，**未 apply**）

> 裁决已定（见下表），S1 是沙箱前置片的第一片。本轮**未安装任何包、未重启任何服务、未改动运行中的单元**；
> 生产 daemon 还是原来的零加固状态，等你跑 `sudo bash /tmp/harden_trmd_unit.sh --apply`。
> 产物：`scripts/harden_trmd_unit.sh` + `docs/SANDBOX-PLAN.md` §6.6/§6.7/§9（口径、helper 设计、裁决）。

### 六条裁决（2026-09-21）

| # | 问题 | 裁决 |
|---|---|---|
| 1 | eBPF 监控要不要提权 | **要，走 `CAP_BPF` + root helper**（daemon 不加能力，也不把 eBPF 摘出方案） |
| 2 | 要不要放开非特权 user namespace | **不全局放开**，将来需要时**定向**给 `bwrap` 写 AppArmor profile |
| 3 | Docker 档放哪 | **Phase 5**（不可信第三方 Agent 包），不进 E7 主干 |
| 4 | daemon 非特权 vs 加特权 helper | **加特权 helper**，daemon 本身仍非特权 |
| 5 | 沙箱是否提到 E7 之前 | **是** |
| 6 | E7 首发是否允许自动改盘 + 跑测试 | **默认只出差异 + 跑只读验证**，写盘要确认，`--yes` 才自动落盘 |

另：E7 入口定为 **`trm exec --code`**（不新开 `trm code`）；`skill.yaml` 与 `SKILL.md` **不合并**（同批裁决记在 `docs/CODING-AGENT-PLAN.md` §8.1）。

### 实做中推翻的三处原设想（都是真机实测逼出来的）

| 原设想 | 实际采用 | 理由（一手事实） |
|---|---|---|
| `ProtectSystem=strict` + `ReadWritePaths` 白名单 | **`ProtectSystem=full`**，不列白名单 | daemon 要在**任意工作区**写盘，白名单**列不全**（列漏 = 运行时才炸）；`full` 盖住 `/usr`/`/boot`/`/efi`/**`/etc`** 的持久化面，工作区粒度交给 S2 的 Landlock |
| `ProtectHome=read-only` | `ProtectHome=no`（显式写出） | `~/.trimum` 与工作区都在 `$HOME` —— 这是**明确放弃**的边界，写进 drop-in 当记录 |
| `SystemCallFilter=@system-service` | **黑名单**（`~`） | 实测 systemd 255 的 `@system-service`（展开 375 条）**不含** `seccomp(2)` 与 `landlock_*`(444/445/446)，且这三个**任何分组里都没有** —— 白名单会**把 S2/S3 自己要装的沙箱挡在门外** |
| `PrivateDevices=yes` | **不开** | 它会建一个**不带 `/dev/shm`** 的 `/dev` → Python `multiprocessing` / 共享内存类工具会挂；对非 root daemon 的收益本来就近于零 |

### 额外两个实测发现（一条改了设计、一条新增待裁决）

1. **daemon 的 IPC socket 之前根本没起来**：默认路径 `/run/user/<uid>/trimum.sock` 下没有文件（系统单元里 `XDG_RUNTIME_DIR` 为空），
   `trm status` 一直显示 **`source: http`**。S1 用 `RuntimeDirectory=trimum` + `Environment=XDG_RUNTIME_DIR=/run/trimum`
   把 socket 落到 `/run/trimum/trimum.sock`（目录 0750 / socket 0700）。
   配套代码改动（唯一一处）：`trimum_client.socket_candidates()` 增加 `/run/trimum/trimum.sock` + 3 个测试 ——
   否则 daemon 绑了 A、客户端去连 B，仍旧静默降级成 HTTP。
2. **HTTP 端口是尚未收口的授权面**：`127.0.0.1:8321` 对**同机任何用户**开放（loopback 不做 uid 检查），背后是完整的工具执行 API。
   systemd 的只读路径指令**管不了 IPC**（文档原文：这类选项「do not affect the ability for programs to connect to」），
   要收口只能从监听面动手 → 列为新增待裁决（`docs/SANDBOX-PLAN.md` §9.2-1，建议只留 unix socket）。

### 加固脚本怎么用（`scripts/harden_trmd_unit.sh`，已传真机 `/tmp/`）

```bash
sudo bash /tmp/harden_trmd_unit.sh            # dry-run：打印现状 + 将要写入的 drop-in（默认行为）
sudo bash /tmp/harden_trmd_unit.sh --apply    # 备份 → 写 drop-in → daemon-reload → 重启 → 冒烟 → 失败自动回滚
sudo bash /tmp/harden_trmd_unit.sh --verify   # 只跑冒烟复查
sudo bash /tmp/harden_trmd_unit.sh --rollback # 还原最近一次备份
```

drop-in 走 `/etc/systemd/system/trmd.service.d/10-hardening.conf`（**不改原单元**），
备份落在 `/var/backups/trimum/harden-<时间戳>/`（含 `unit-before.txt` 与一键 `rollback.sh`）。

**冒烟断言**（任一 FAIL 自动回滚）：`systemctl is-active`；`ProtectSystem=full`；`NoNewPrivileges`/`RestrictNamespaces`/`PrivateTmp`=yes；
`CapabilityBoundingSet` 空；**进程内实测** `/proc/<pid>/status` 的 `NoNewPrivs: 1` 与 `Seccomp: 2`；
`/proc/<pid>/mountinfo` 里 `/usr` 与 `/etc` 是 `ro` 而 `/home` 不是；**`mountinfo` 条目数 > 宿主基线 47**（证明命名空间真建了）；
`/run/trimum/trimum.sock` 存在；以服务用户跑 `trm status` / `trm tool list` 通过；日志无 `unix_socket_start_failed`；
syscall 探针（同一套黑名单下 `landlock_*`/`seccomp`/`prctl` 不被挡、`bpf`/`ptrace`/`mount` 被挡）。

### 真机验证（本轮已跑，全部只读）

| 检查 | 结果 |
|---|---|
| 脚本语法 `bash -n`（3 个 + 本脚本） | 全 OK |
| dry-run | 跑通：现状段正确报出 `mountinfo=47`（= 没有命名空间）、当前评分 **9.2 UNSAFE** |
| `--stage` 渲染 | drop-in 全文正确（含 `ProtectSystem=full`、黑名单、`RuntimeDirectory=trimum`） |
| 黑名单实际拦截效果（用户级复现同一套过滤器） | `bpf`/`ptrace`/`mount`/`init_module`/`kexec_load`/`userfaultfd`/`io_uring_setup`/`process_vm_readv`/`swapon`/`add_key` → **全部 EPERM**；`landlock_create_ruleset`(14)/`landlock_restrict_self`(77)/`seccomp`(22)/`prctl`(22) **未被误伤** |
| `--allow-debug` 变体 | `ptrace` 恢复 `errno=0`，`bpf` 仍 `EPERM`（开关有效） |
| 客户端测试 | `tests/test_socket_path_consistency.py` **11 passed** |

> **未做（要 `sudo` 密码，只能你自己跑）**：`--apply` 安装 + 冒烟；`check_sandbox_caps_root.sh`（系统级能力核对）。

---

## 2026-09-21 S1 试装复盘 + socket 收口（✅ 代码与脚本已改；生产单元仍原样）

**⚠️ 21:09 事故（同日第三轮）**：`sync_opt_socket_patch.sh` 把仓库 **HEAD 的 `api_server.py`** 装进了
`/opt/trimum/src`，而部署树比仓库旧一大截 —— 没有 `workflow_runtime.py`，于是 daemon 一启动就
`ModuleNotFoundError: No module named 'trimum_core.workflow_runtime'`，systemd 每 5s 重启一次（`NRestarts=29`）。
冒烟**正确**判 FAIL 并自动回滚了单元，但**回滚只撤单元、不撤 `src`**，所以循环不止。
两条护栏已落地：① 同步文件集 5 → **4**（去掉 `api_server.py`，代价只有 `await ipc.start()` 这条加固，等整树同步到 HEAD 再补）；
② 装之前先做**导入预演**（`PYTHONPATH=/tmp/.socket-patch-rehearsal` 里 `import trimum_core.main`，并断言 `trimum_core.__file__` 真来自预演目录），不通就一个字都不碰生产。
恢复：`scripts/trmd_hotfix_restore.sh`。详见 `docs/SANDBOX-PLAN.md` §9.3.6。

> 用户口径：*「刚刚回滚了，IPC socket 不存在，之前用 Socket 跑的时候一直出 bug 才暂时用 http 代替，现在改成 Socket 吧，你先看看吧」*
> —— 「先看看」的结论与落地都在 `docs/SANDBOX-PLAN.md` §9.3。

**两次 `--apply`（20:40 / 20:50）都失败并自动回滚；真因不是加固，是冒烟抢跑。**
`smoke()` 只等 `systemctl is-active`，而 uvicorn 还要几百毫秒才 bind、IPC socket 更晚才建；断言跑在就绪之前 →
`[FAIL] IPC socket 不存在` → 回滚。证据：`/tmp/.trm-status.out`（root，20:50）= `[OFFLINE] daemon is not running`
（那一刻 RPC 与 HTTP 都不通），而同一时刻 daemon 日志是 `unix_socket_listening /run/trimum/trimum.sock`；
journal 显示 20:50:01 起、20:50:02 停，只隔 1 秒。

**「IPC socket 不存在」是回滚后的正常现象**：drop-in 撤掉后 daemon 回到 `/run/user/1000/trimum.sock`
（现在是活的：connect 探测返回 `{"status":"ok","version":"0.5.0"}`），`/run/trimum/` 只剩一个 `RuntimeDirectory` 建的空目录。

**socket 历史 bug 坐实三条**（daemon 日志逐行可指）：① 父目录不存在 → bind `ENOENT` → 只 `warning` 一声静默咽掉（daemon 仍报 `active`）；
② 双实例互踩（`unix_socket_in_use` + journal 的 `restart counter` 涨到 **2134**，全是 `TCP 8321 已被占用`）；
③ 客户端按 `exists()` 挑候选 → 选中 SIGKILL 残留的 stale 文件 → 静默退回 HTTP。

**已改**：`config.py`（`TRIMUM_SOCKET` 契约 + `socket_candidates()` / `discover_socket()`）、`trimum_client.py`（按「能连通」挑）、
`ipc_handler.py`（缺父目录自动建；bind 失败 → `logger.error` + stderr + `socket_start_error`）、`api_server.py`（`await ipc.start()`，
不再让 `create_task` 吞失败）、`cli/_utils.py`（`rpc_call` 走候选表）、`scripts/harden_trmd_unit.sh`（`TRIMUM_SOCKET` 取代
`XDG_RUNTIME_DIR` 劫持 + 就绪门 + 失败留证 + 默认 `@debug` / 默认不加只读）。
测试：`tests/test_socket_path_consistency.py` **11 → 20**（本地 18 passed / 2 skipped）。

**未做**（当轮口径；同日第四轮已补上，见下节）：TCP 收口（裁决 1）要先补 RPC 面（`health` 带 pid、
`security.tokens/learning/learn`），顺序见 §9.3.5；生产单元仍未加固；**未安装任何包**。

## 2026-09-21 TCP 收口：先把 socket 侧的腿补齐（✅ 代码已改；生产单元仍未切）

> 用户口径：*「成功，写TCP吧」*（S1 恢复脚本跑通之后）。落地顺序取自 `docs/SANDBOX-PLAN.md` §9.3.5，
> 改法 / 测试 / 真机切换顺序见 §9.3.7。

**四步全部落地。**这四条都是「关 TCP 之前必须先有」的东西，少一条就等于关掉的是 daemon 而不是 TCP：

| # | 改动 | 文件 |
|---|---|---|
| 1 | `health` 由 daemon **自报** `pid` / `uptime` / `http` / `ipc`（HTTP 与 IPC 共用一份 `_health_payload()`）；`trm status` 先认 `health.pid`，再退 pid 文件，最后才是 psutil 扫监听端口 | `api_server.py` / `cli/commands/status.py` |
| 2 | 新增 RPC `security.tokens` / `security.learning` / `security.learn`；实现抽成模块级 `_jit_tokens()` / `_learning_status()` / `_run_learning()`，**HTTP 与 IPC 共用**；`trm security tokens / learning / learn` 改 **RPC 优先、HTTP 兜底** | `api_server.py` / `cli/commands/security.py` |
| 3 | 新开关 `core.http_enabled`（默认 `true`）+ `TRIMUM_HTTP` 覆盖（`0`/`false`/`no`/`off` 关，其余一律当开）。关掉时 **不启 uvicorn**，由 `main._serve_without_http()` 自己驱 `app.router.lifespan_context(app)`（与 uvicorn 内部**同一段 lifespan**）；端口预检也只在开 HTTP 时跑 | `config.py` / `main.py` |
| 4 | 关掉 HTTP 时 socket bind 失败 → `IpcUnavailableError` 从 startup 抛出 → `trmd` 以 `exit 3` 中止；**开着 HTTP 时仍只记 `error`**（那时用户还有路走，不该拦启动） | `ipc_handler.py` / `api_server.py` / `main.py` |

顺带：`IpcHandler.listening` 成了 `health.ipc` 的来源 ——「socket 到底起没起来」从此是 `trm status` 上的一行。

**测试**：新增 `tests/test_ipc_only_mode.py` **14 项**；`test_api_server_startup.py::TestHealthVersion`（health 不再只有
version）与 `test_cli_commands.py`（RPC 优先 + pid 来自 health）同步改。全量 **1519 passed / 2 failed / 10 skipped**
（2 项 = 既有宿主基线：PATH 缺 `python.exe`、LLM 断网；与开工前逐条同名同数）。

**真机验证（隔离环境，2026-09-21 第四轮）**：`scripts/accept_ipc_only.sh` —— 不碰生产 daemon、不碰
`~/.trimum`、不用 sudo，用整棵 HEAD `src` 起一个 `http_enabled: false` 的 daemon，**15 PASS / 0 FAIL**
（status 走 RPC 且 http=false/ipc=true/pid 对得上；`security learning|tokens|learn` 在 HTTP 关闭下全通；
本进程没有任何 HTTP 监听；socket 起不来 → `exit 3`；SIGTERM 干净收摊；`TRIMUM_HTTP=1` 可反向打开）。

**真机抓到两件事**（详见 `docs/SANDBOX-PLAN.md` §9.3.8）：
① **真 bug 已修**：致命路径用 `sys.exit(3)` 会挂住（`timeout 90` 只能 SIGKILL，退出码 124 而不是 3）——
  真因是 `ContextManager` 的 **aiosqlite 非 daemon 线程**，startup 失败时 lifespan 的 `__aexit__` 不会跑、
  连接没人关，解释器停在 `threading._shutdown()`（faulthandler 栈为证）。改用
  `abort_startup(..., hard=True)`（flush + `logging.shutdown()` + `os._exit(3)`），并加子进程回归测试。
  同类风险 uvicorn 路径也有，未动，记进 `TODO.md`。
② **开发树 `~/trimum/src` 也落后 HEAD 一大截**（缺 `SecurityRuntime`）—— 只覆盖「本轮改的几个文件」装不上，
  与 §9.3.6 的部署树问题同源 ⇒ 两棵树都要整体同步；导入预演那条护栏确实有用。

**未做**：真机切换（`http_enabled` 默认仍 `true`，生产单元没动）；两棵树整体同步；S2～S5。**未安装任何包。**

## 2026-09-21 真机切开关（TCP 收口落地）+ LLM 路由 / 限流 / 回退（✅ 真机已验；提交 `9e34ddc`）

**这一轮干了两件事，都在真机上验收过。**

### 1) TCP 收口（沙箱前置片 S0）：从「脚本就绪」到「生产已切」

| 步骤 | 结果 |
|---|---|
| 整树同步 | `sudo bash /tmp/sync_opt_tree.sh --restart` ✅ 部署树 `/opt/trimum/src` **62 → 73 个模块**；备份 `/var/backups/trimum/src-20260921-224003`；重启后 `trm status` 正常 |
| 切开关 | `sudo bash /tmp/switch_ipconly.sh --apply` ✅ **PASS=10 WARN=0 FAIL=0**（证据 `/tmp/switch-ipconly-*.log`） |
| 验收口径 | `trm status` → `http: disabled` + `ipc socket: ok` + `source: rpc`；`ss -ltnp \| grep 8321` **无输出**；daemon 只持有 workflow driver 的临时端口 |

**踩的坑（已进脚本与文档）**：第一次 `--apply` 只做了一半 —— 输出被 `head -32` 截断，写端吃到 **SIGPIPE**
被打死，结果 **drop-in 写了但 `daemon-reload`/`restart` 没跑**（等于什么都没生效）。重跑改成
**`setsid bash … > /tmp/apply.out 2>&1 </dev/null` 脱离会话**执行、再读文件看结论。
更早那条：`fs.protected_regular=2` 下 **root 也不能 O_CREAT 覆盖 `/tmp` 里属主是别人的普通文件**
（`/tmp/.trm-walk.py` 权限不够的真因），所以预演产物一律进「每次运行新建的 mktemp 目录」（§9.3.9）。

一键退：`sudo bash /tmp/switch_ipconly.sh --rollback`；整树退：`sudo bash /tmp/sync_opt_tree.sh --rollback`。

### 2) LLM 路由 / 限流 / 回退：从「5 个调用点各干各的」到「一处策略」

**事实修正（实测，不再靠猜）**：
- 交我算 `GET /api/v1/models` = `minimax, qwen, claw, deepseek-chat, deepseek-reasoner, minimax-m2.7, qwen3.8-27b`
  → 用户口径的「QWEN3.6-27B」真实 id 是 **`qwen3.8-27b`**。
- DeepSeek 官方只有 **`deepseek-flash` / `deepseek-v4-pro`** 两档 —— **`deepseek-chat` 已下架**，
  而项目旧默认值写的正是它（本轮改成 `deepseek-flash`）。

**分工（真机实测路由表）**：

```
policy / planner / transform / experience : 主 qwen3.8-27b @交我算（9 次/分，免费）  备 deepseek-flash
agent（运行时会话 / 多步编排 / 流式）       : 主 deepseek-flash（要能力）            备 qwen3.8-27b
```

**代码（新/改；提交 `9e34ddc`）**

| 文件 | 作用 |
|---|---|
| `src/trimum_core/llm_router.py`（新） | 唯一策略处：`resolve_targets`（选谁）/ 令牌桶（等多久）/ 失败分类 + 冷却（换谁）。**不碰 HTTP**，调用点自己发请求 |
| `src/trimum_core/env_file.py`（新） | `.env` 加载器（此前**全仓没有任何代码读 .env**，install_fn 写进去也没人读）；按 key 叠加、已有环境变量优先 |
| `scripts/llm_env_dropin.sh`（新） | 真机：给 trmd 加 `EnvironmentFile=-/opt/trimum/.env`；`--check / --apply / --smoke / --rollback`，验证只看键名不看键值 |
| `llm_policy` / `planner_agent` / `transform_agent` / `experience_learner` / `agent_loop` | 5 个调用点全部改走路由（各自的降级路径一个没丢） |
| `security_config.DEFAULT_SECURITY_YAML` | `llm:` 段 → 主 Qwen + `fallback:` 子段 deepseek-flash |
| `tests/test_llm_router.py`(新) / `tests/test_env_file.py`(新) | 27 项 + 6 项；`tests/conftest.py` 加**两个**隔离 fixture（重置路由状态 + 快照/还原 `os.environ`）|
| `docs/LLM-ROUTING.md`（新） | 交接文档：分工表 / env 键全表 / 限流与冷却表 / 降级表 / 运维命令 / 待办 |

**真机证据（2026-09-21 22:41）**：`/opt/trimum/.env`(0600 root:guzhujushi) 与 `~/.trimum/.env`(0600) 各 18 键；
daemon 环境里有 `TRIMUM_LLM_*` / `JIAOWOISAN_API_KEY` / `DEEPSEEK_API_KEY`（读 `/proc/PID/environ` 键名）；
网络冒烟 **`OK 走的 target：primary:qwen3.8-27b@models.sjtu.edu.cn 回复：可用`**；
`trm doctor` → `LLM API connectivity: https://models.sjtu.edu.cn/api/v1` + 三个 key env 全 OK。

**顺带修的老 bug**：`planner_agent` 里 `TrimumError/TRMErrorCode` **从没被 import**（那几条分支跑到就 NameError）；
`agent_loop._chat_completion` 之前只认 `DEEPSEEK_API_KEY`（不看配置里的 `api_key`/`api_key_env`）。

**跑测结果**：全量 **1547 passed / 2 failed / 10 skipped**；两条失败都是**环境基线**，非本改动引入
（① 本机沙箱禁网 → 真调 LLM 的那条用例连接被拒；② `test_depends_on` 的 `python.exe` 不在 PATH ——
放行网络后 ① 通过，② 与本次改动无关）。另有一条既有健壮性 bug 未修（不在本轮范围）：
`learning_engine.load()` 用 stdlib logger 传 structlog 风格 kwargs（`profiles=`）→ 特定顺序下 TypeError。

**提交前回归：修掉一处 `.env` 带出来的用例间污染。** `env_file.ensure_loaded()` 只在 CLI/daemon/client 入口调用，
且是**模块级只跑一次** —— 只要全量跑里有一个用例跑了 `cli.main()`，开发机真实的 `~/.trimum/.env` 与仓库根 `.env`
就会留在 `os.environ` 里，**后面所有用例都读到开发机的密钥与模型配置**。全量跑炸两条（**隔离跑都过**）：
`test_transform_agent::test_request_contains_correct_payload`（构造参数的 `http://test.local` 被 `.env` 的
`TRIMUM_LLM_BASE_URL` 顶掉）、`test_other_dispatchers::test_env_list_sorted`（首行变 `163_EMAIL=...`）；
修完又暴露 `test_cli_commands::test_health_json_includes_api_key_presence`（断言「删掉 `GROQ_API_KEY` 就该缺席」，
而 `.env` 里有它 —— 这是用例假定「环境 = `os.environ`」的旧口径，产品行为没错）。
处理：`tests/conftest.py` 新增 `isolate_process_env`（按用例快照/还原 `os.environ` + `env_file.reset_loaded()`）、
`env_file.reset_loaded()`、health 用例显式屏蔽 `.env`。全量回到 **1554 passed / 2 failed / 10 skipped**，
两条失败仍是宿主基线（PATH 缺 `python.exe` + 本机沙箱断网），与本轮改动无关。

**下一步**：① **真机跑 S2 的 4 条命令对照**（`docs/SANDBOX-PLAN.md` §10.6，不需要 `sudo`，**本人跑**）；
② 【DS】S3 seccomp 三档（`readonly` / `workspace-write` / `strict`）。
LLM 侧剩余待办：跨进程限流 / token 维度计量 / `Retry-After` / `trm doctor` 显示路由表 / 成本账本（见 `docs/LLM-ROUTING.md` §8）。

---
## 2026-09-21 Codex 侧模型分工与「限流降级」调研（✅ 已落地；提交 `de619c5`）

**需求**：简单任务用交我算免费的 Qwen、难任务用 deepseek-flash，并希望「像 trimum 一样限流后自动降级」。

**结论**：Codex **自身没有**「限流 → 换 provider」的开关（全二进制扫 `*fallback*` 只有 CodeModeHost / TokenBudget /
models-manager 内部回落 / session 模型不可用回落四种，与限流无关）；能立刻做的是**任务级 profile 切换**（本轮已落地），
要自动降级只能**在 Codex 前面加一层本地路由代理**（`docs/CODEX-MODEL-POLICY.md` §4，**待裁决**）。

**实测事实**：

| 事实 | 证据 |
|---|---|
| `wire_api` 只接受 `responses` | 故意写 `bogus` → 报错 "unknown variant `bogus`, expected `responses`" |
| 交我算 `/api/v1/responses` 可用 | 最小请求 **HTTP 200**（`object:"response"`、`model:"qwen3.8-27b"`、24 tokens；响应带 `_litellm_tpm_reserved_model` ⇒ 后端是 LiteLLM 网关） |
| `codex exec -p qwen` 端到端通 | `model: qwen3.8-27b` / `provider: sjtu-jiaowusuan` / 回复「可以」/ 退出码 **0**（跑两次） |
| profile 不能写在 `config.toml` | 0.151 要求独立文件 `~/.codex/<name>.config.toml`（`sjtu-min.config.toml` 是先例） |
| 次数才是瓶颈 | 一次 `codex exec`（2 字回复）用掉 **14~15k tokens**；交我算 10 次/分 ⇒ 长会话必撞 429，**Qwen 只适合单次小任务** |

**改动**：`scripts/codex-model.ps1`（新：按任务选 profile + 把 trimum `.env` 灌进进程环境；存 UTF-8 **with BOM** ——
PS 5.1 用 `-File` 跑无 BOM 的 UTF-8 会按 GBK 解、中文直接把脚本解析弄挂）、`docs/CODEX-MODEL-POLICY.md`（新）、
`TODO.md`（新增「🤖 Codex 模型分工」一节 + 给 19 条待办打 `【Qwen】` / `【DS】` 标签）。
仓库外：新建 `~/.codex/qwen.config.toml` 与 `~/.codex/ds.config.toml`；`~/.codex/config.toml` 加过 `[profiles.*]` 被 0.151 拒绝，已回滚
（备份 `~/.codex/backups/config.toml.20260921-230249.bak`）。**未改任何 `src/` 与 `tests/`。**

**收尾核对（2026-09-21 23:07）**：真机 `trm status` → `source: rpc` / `http: disabled` / `ipc socket: ok`（pid 27582，uptime 27m）；
`/opt/trimum/src` 与本地 `src` 逐文件哈希：**105/105 在位，唯一差异是 `env_file.py` 少一个测试用 `reset_loaded()`**（daemon 不调用）；
全量测试 **1554 passed / 2 failed / 10 skipped**（两条仍是宿主基线）；`server` = `origin/server`，工作区干净。

---

## 2026-09-22 Codex 模型切换复盘：为什么「qwen3.8-27b / sjtu-jiaowoisan 都不行」（✅ 已修 + 已复验）

**症状**：09-22 早上连开 6 个会话，用 `/model` 依次填 `qwen3.6-27b` → `qwen3.8-27b` → `sjtu-jiaowoisan`，
全部得到同一条报错：`The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed <填的那个>`。

**两个根因（都有 rollout 证据，不是猜的）**：

| # | 根因 | 证据 |
|---|---|---|
| A | `/model` 只改**模型名**，**不改 provider**；会话的 provider 始终是 `deepseek-api` | 6 条 rollout 的 `session_meta.model_provider` 全是 `deepseek-api`，而 `turn_context.model` = 你填的值；报错文本来自 DeepSeek |
| B | `sjtu-jiaowusuan` 是 **provider 名，不是模型名**，写进 `/model` 必然失败 | 同上：`...but you passed sjtu-jiaowoisan` |

⇒ **换 provider 只能重开进程**：`.\scripts\codex-model.ps1 qwen` / `codex -p qwen`（`-p ds` 同理）。另加两个**免记路径**的入口：`scripts\codex-qwen.cmd` / `scripts\codex-ds.cmd`（纯 ASCII 批处理转发，
内部带 `-NoProfile -ExecutionPolicy Bypass`，双击可跑；交互式与 `-Exec` 两种都实测过）。
`qwen3.8-27b` 只存在于 `provider = sjtu-jiaowusuan` 上，单独改模型名没有意义。

**顺带查出 `scripts/codex-model.ps1` 的两个真 bug（昨天落下的，本机已复现）**：

| bug | 现象 | 修法 |
|---|---|---|
| `.env` 候选顺序错 | 候选表把 `~/.trimum/.env`（只剩 `OPENAI_*` 的老 stub）排在仓库 `.env` **之前**，旧实现**只取第一个存在的候选** ⇒ `JIAOWOISAN_API_KEY` / `DEEPSEEK_API_KEY` 一个都没注入（父进程环境里也没有时）；`codex -p qwen` 只得到 `ERROR: Missing environment variable: JIAOWOISAN_API_KEY.` | 低→高优先级依次加载 + 仓库根 `.env` 权威 + 进程原有变量优先；并在起 codex **之前**校验 profile → provider → `env_key` 是否存在，缺了直接给人话报错 |
| PS 5.1 把 codex 的 stderr 当致命错误 | 原生命令写 stderr 的每行被包成 ErrorRecord，配上脚本里的 `$ErrorActionPreference = 'Stop'` ⇒ codex 一启动（总会写 `Reading additional input from stdin...`）就抛错中止，`-Exec` 路径其实一次都没跑成 | 在 `& $codex` 前把偏好放回 `Continue`；成败看 `$LASTEXITCODE` |

**署名改正**：Codex provider `sjtu-jiaowoisan` → **`sjtu-jiaowusuan`**（2026-09-22 定名：先误改为 `jiaowosuan`，经确认最终用 `jiaowusuan`）；
改 `~/.codex/config.toml` 2 处 + `~/.codex/qwen.config.toml` 1 处，
备份 `~/.codex/backups/config.toml.20260922-072948.bak` / `qwen.config.toml.20260922-072948.bak`。

**复验（2026-09-22 07:33，`codex-cli 0.152.0`）**：先**清空进程里的 key**，
再跑 `.\scripts\codex-model.ps1 qwen -Exec "只回复两个字：可以"` →
`provider: sjtu-jiaowusuan` / 回复「可以」/ 退出码 **0**，且脚本自报「注入 33 个变量，.env: ~/.trimum/.env ; D:\trimum\.env」
⇒ key 确实是从仓库 `.env` 注入的。
（昨天那份证据取自 **0.151.0-alpha.7.2**；本机已升 **0.152.0**，profile 机制未变，已重新验证。）

**未做（留给裁决）**：环境变量 `JIAOWOISAN_API_KEY` 本轮**没改名** —— 它同时被 `src/`（`llm_router.py` /
`doctor.py` / `health.py` / `security_config.py`）、`tests/`、`scripts/llm_env_dropin.sh` 和真机 drop-in 引用，
盲改会让真机 daemon 起不来。选项见 `TODO.md` 的「🤖 Codex 模型分工」小节。

---
## 2026-09-22 S2 施加点收口：内核层沙箱落地（✅ 代码已落地 + 本机 A/B 回归 + **真机已验**）

**做了什么**：新增 `src/trimum_core/sandbox_exec.py`（Layer K，923 行）—— Landlock 三个 syscall（444/445/446，
全走 `ctypes`，零依赖、不要 root）+ `prctl(PR_SET_NO_NEW_PRIVS)`，把**全部 7 个 spawn 点**收到一处。

**7 个点**（原设计列 6 个；实做时发现 E4 的 CLI 广接入 `cli_adapter.generic_executor` 也是一条真实派生通道）：

| # | 位置 | 面 |
|---|---|---|
| 1–4 | `tool_dispatchers.py`：`GitDispatcher._run_git` / `ShellDispatcher.execute` / `ProcessDispatcher._list_processes` / `._kill_process` | `git_*` / `shell` / `process list` / `process kill` |
| 5 | `agent_launcher.py:launch_agent` | 子 Agent（施加失败**不启动**） |
| 6 | `cli_adapter.py:generic_executor` | `trm tool import-cli` 装出来的 CLI 工具 |
| 7 | `tool_gateway.py`（dispatch 之前） | 不算派生点：给「file 型工具把 request 重建成新对象」那条路兜底 |

`TestNoBypass` 用静态断言钉住：这两个文件里不许再出现 `create_subprocess*`，且 `plan_for(` 的调用次数被锁死。

**关键口径**：

- 施加在**子进程**（`preexec_fn` 钩子）—— daemon 自己不施（Landlock 只能收紧、不可逆，见 `docs/SANDBOX-PLAN.md` §6.1）；
- 状态词表（审计唯一口径）：`off` / `unsupported` / `readonly|workspace-write|strict` /
  `<mode>:failed`（**命令不跑**，fail-closed）/ `<mode>:degraded`（关掉 fail-closed 才降级放行，且记 ERROR）；
- 两档开关：`TRIMUM_SANDBOX`（默认 `workspace-write`）+ `TRIMUM_SANDBOX_FAIL_CLOSED`（默认 `true`），
  drop-in 写一行即生效、删掉即回滚；优先级 = 内置默认 < `security.yaml` < 环境变量；
- 放宽方向锁死：`agent.json5` 只能往严里收（`_MODE_RANK`），manifest 里的 `write` **一律忽略 + 告警**；
- Windows → 如实报 `unsupported`（不假装已隔离、也不静默放行），且**只告警一次**。

**回归（本机 Windows，两棵树 A/B 对照）**：HEAD `261f452` 干净树 **1548 passed / 6 failed / 12 skipped**；
S2 工作区 **1576 passed / 6 failed / 16 skipped** → **+26 passed（新增用例）/ +6 skipped（Linux 专属）**，
差额精确等于新用例数。**6 条失败两棵树逐条一致**，与 S2 无关：2 条宿主基线（`PATH` 缺 `python.exe`、
连不上 `models.sjtu.edu.cn`）+ 4 条宿主 `~/.trimum` 污染（`--fakehome` 后 41/41 全绿）。
归因脚本 `tmp/cleanrun.py`（剥掉宿主常驻的 21 个脏环境变量再跑）。

**提交**：`92ac32c`（本片：`sandbox_exec` + 7 个接入点 + 32 项测试 + 文档）/ `3276aab`（前一片尾巴：Codex 模型分工脚本与文档）。

**真机修正（2026-09-22 S3 轮补齐，见 `docs/SANDBOX-PLAN.md` §10.5.1）**：

1. **Landlock 只接「目录 + 普通文件」** —— 字符设备（`/dev/null` `/dev/ptmx`…）给权限是 `EINVAL(22)`，
   管道 / 指向管道的符号链接（`/dev/stdout`…）是 `EBADFD(77)`。修法：新增 `_landlockable()` 装置前过滤
   （剩下的记 `sandbox.root_not_landlockable`，debug 级）+ `_file_read_rights()` / `_file_write_rights()`
   （**普通文件不给目录级权限**）+ `EBADFD` **降级为 warning `sandbox.rule_skipped_not_a_file`**（不再 fail-closed）。
2. **`readonly` 档工作区只读** —— 原先工作区同时进了写根，真机实测「`readonly` 档能写工作区」（**隔离失效**）；
   已改 `plan_for`：readonly 时工作区只进读根。

真机复跑（2026-09-22）：`test_sandbox_exec.py` + `test_seccomp_exec.py` **97 passed / 2 skipped / 0 failed**；
原「真机 4 条命令对照」已并入 `scripts/accept_s3.py`（A / C / D 组）。

**未做**：`TaskRegistry.SHELL` 的派生点未收；`trm status` / `doctor` 还没把沙箱状态摆到台面上。

---

## 2026-09-22 S3 seccomp 三档：内核层沙箱的另一半（✅ 代码已落地 + 本机回归 + **真机验收 35 passed / 0 failed**）

**做了什么**：新增 `src/trimum_core/seccomp_exec.py`（733 行）—— 三档**档案**（纯计算 `build_plan`，
resolver / lib / capability 全可注入 ⇒ 逻辑层在 Windows 上也能测）+ **施加**（`apply_current`，libseccomp 走 ctypes）
+ 能力探测 + 独立 CLI（`python -m trimum_core.seccomp_exec --status / --profile`）；
`sandbox_exec` 把它接到 Landlock 那半旁边（**Landlock 先、seccomp 后**）。

**三档**：

| 档 | 内容 | 谁用 |
|---|---|---|
| `off` | 不施加（照旧 exec，**明确不施加**，不再退 126） | 排障 / 一键退 |
| `l1`（**默认**） | `KERNEL_BLOCK` **31** 条危险内核面（内核模块 / eBPF / `ptrace` / `io_uring` / 命名空间 / 挂载 / 块设备 / I/O 端口 / keyring / `open_by_handle_at`） | 常规任务 |
| `strict` | `l1` + `STRICT_BLOCK` 3 条 + **按地址族挡网络 socket**（`AF_INET`/`AF_INET6`/`AF_PACKET`/`AF_NETLINK`），**`AF_UNIX` 放行** | 未知 / 第三方 Agent |

**关键口径**：

- `TRIMUM_SECCOMP`（环境变量 > `security.yaml: sandbox.seccomp` > 默认 `l1`）；与 `TRIMUM_SANDBOX`（Landlock 那半）**互相独立**；
- **施加顺序**：`apply_plan()` 里 **Landlock 先、seccomp 后** —— `seccomp_load()` **不可逆**，必须排在所有可能失败的步骤之后；
- 只收紧不放宽：`agent.json5` 的 `seccomp_profile` 只能更严（`PROFILE_RANK`）；包的 `seccomp_allow` / `extra_syscalls`
  **忽略 + 告警**（`sandbox.manifest_seccomp_allow_ignored`），包的 `seccomp_block` / `extra_block` 可以加；
- `strict` + `seccomp_allow` 非空 ⇒ **白名单模式**（默认动作 `EPERM` + 69 条基线 + 声明放行），此时**不再叠黑名单规则**；
- 审计：`sandbox` 与 `seccomp` **两个字段各记一份**（`off` / `unsupported` / `l1` / `strict` / `<档>:failed`）。

**真机跑出来的四条（`docs/SANDBOX-PLAN.md` §11.3）**：

| # | 事实 | 代价（不修会怎样） |
|---|---|---|
| 1 | 能力口径是 **API level**（`seccomp_api_get()` = 6），不是版本号 —— `seccomp_version()` 走 ctypes 读不出来（`restype` 试 `c_uint`/`c_int`/`c_ulong` 全是垃圾） | 能力判定失真 |
| 2 | 判别器只能选「**不施加时一定会成功**」的 syscall（`ptrace(TRACEME)` / `io_uring_setup`）；`bpf` / `mount` / `setns` 非特权下**本来就失败** | 验收得出「拦住了」的**假结论** |
| 3 | **`SCMP_CMP_EQ` 是 4，不是 0**（`enum scmp_compare` 从 `_SCMP_CMP_MIN = 0` 起算） | `seccomp_rule_add` 返回 `-EINVAL(22)`，「按地址族挡 socket」**整条失效** ⇒ `strict` 档**放行 `AF_INET`** |
| 4 | Landlock 只接「目录 + 普通文件」 | 见下面 S2 小节的真机修正三条 |

探针留在 `tmp/probe_cmp.py`（真机输出：`op=0 → rc=-22`、`op=1..7 → rc=0`、`sizeof(struct scmp_arg_cmp)=24`）。

**回归**：

| 树 | 结果 |
|---|---|
| 本机 Windows（`test_seccomp_exec` + `test_sandbox_exec`） | **86 passed / 13 skipped / 0 failed** |
| 本机 Windows（全量 `tests`） | **1636 passed / 6 failed / 23 skipped**（6 条与 S2 轮逐条同名，与 S3 无关） |
| 真机 `/tmp/trm-s3`（两个文件） | **97 passed / 2 skipped / 0 failed**（首跑 8 条失败 → 3 条 → 0 条） |
| 真机 `/tmp/trm-s3`（全量） | **1645 passed / 16 failed / 4 skipped**（16 条全是宿主 / 合成树产物，归因表见 §11.6） |
| 真机 `scripts/accept_s3.py` | **35 passed / 0 failed** |

**提交**：`5041885`（本片：`seccomp_exec` + 两半联动 + 两个测试文件 + `accept_s3.py` + 三条真机修正）/
`45cd19f`（文档回填：`SANDBOX-PLAN` §10.5.1+§11、`SECURITY-DEFENSE-PLAN` §7.1–§7.3 脚注、`TODO` / `STATUS`）/
`fa2542e`（回填文档提交号）/ `e2046a6` + 本次（`TODO` 的「交给 Qwen 的起手三步」与状态刷新）—— **均已推 `origin/server`**。

**未做**：`TaskRegistry.SHELL` 的派生点仍未收（S2 起挂着）；`trm status` / `doctor` 还没把沙箱状态摆到台面上；
`/opt/trimum` 的整树同步待本人 `sudo`（`/tmp/sync_opt_tree.sh` + `/tmp/trimum-sync.tar` 已就位）；
白名单模式的 `allow` 只给运维（`security.yaml`），不是包口子。

---

## 2026-09-22 S3 收尾交接：起手三步验证（✅ 全过 + 真机合成树重建）

> 按 TODO.md「交给 Qwen：S3 收尾之后的起手三步」逐条执行。

**第 1 步 · 读文档**：STATUS.md S3 小节 + docs/SANDBOX-PLAN.md §11（§11.3 四条真机教训、§11.6 归因表），已读，不重查。

**第 2 步 · 跑测试**（全部通过）：

| 树 | 命令 | 结果 | 基线 | 判定 |
|---|---|---|---|---|
| 本机 Windows 全量 | python tmp/cleanrun.py tests -q --basetemp D:/trimum/tmp/pytest-fresh -p no:cacheprovider | **1642 passed / 0 failed / 23 skipped**（91.8s） | 1636/6/23 | ✅ 通过且优于基线（6 条宿主失败本轮未复现） |
| 真机 /tmp/trm-s3 全量 | cd /tmp/trm-s3 && PYTHONPATH=/tmp/trm-s3/src /home/guzhujushi/trimum/.venv/bin/python -m pytest tests -q | **1645 passed / 16 failed / 4 skipped**（67.3s） | 1645/16/4 | ✅ 逐条吻合 §11.6 归因表（7 skill_integration + 2 tool_file_loading + 4 socket_path_consistency + 1 env_list_sorted + 1 test_depends_on + 1 llm_integration） |
| 真机 ccept_s3.py | 同上 PYTHONPATH | **35 passed / 0 failed** | 35/0 | ✅ 全绿 |

**真机合成树重建**（原 /tmp/trm-s3 已不存在，home 树 /home/guzhujushi/trimum 非 git 仓库且停在 09-20）：

- 从 home 树 tar 出 src / 	ests / scripts / config 到 /tmp/trm-s3；
- 逐文件比对本地开发树，**43 个版本差文件**（P0 / E5 / 穿插 A-B-C / LLM 路由 / S2 / S3 各轮改动）全部同步上去；
- 补 config/trust/（	rimum-root.crt + README.md，原 tar 未含非 .py 文件）与空 skills/ 目录（skill_integration 用例需要）；
- 重建后基线与 §11.6 完全一致 —— 证明合成树现在与本地开发树等价。

**推送**：origin/server 之前停在 dad54c9，本地领先 1 个提交（a72dc5 RAG 调研文档）—— 已开代理推送，四分支纪律不变（日常只推 server）。

**下一项**：S4 子 Agent 资源边界（systemd-run --user transient，见 docs/SANDBOX-PLAN.md §8 S4 行）。

---


## 2026-09-22 RAG 检索能力调研（✅ 调研完成，不改代码；docs/RAG-RESEARCH.md）

> 因 S4（systemd-run --user 子 Agent 资源边界）是完整实现片、超出 10 分钟窗口，本轮改做用户备选：RAG 调研。
> 纯文档，无代码改动，测试基线不变。

- **现状**：ContextManager.search() 已用 **SQLite FTS5**（unicode61）做关键词检索，MemoryClassifier
  做 domain/category 过滤——**但没有语义检索**（无 embedding / 无向量 / 无混合排序）。
- **结论**：trimum 的 RAG = 给现有记忆层补一条「**本地 embedding + sqlite-vec**」语义通道，再 **RRF 混合排序**；
  存储 / 命名空间 / 读确认（project_ctx/global_ctx）/ 审计**全部复用现成**，只加「语义召回」一层，全程离线、只读。
- **推荐路径**：R1（把 FTS5 search() 接进记忆读取路径，零新依赖）→ R2（sqlite-vec + 本地 embedding 走
  llm_router 本地档）→ R3（BM25 + 向量 RRF 融合 + 经 context_compactor 装窗 + 审计留痕）。
- **不做的（YAGNI）**：LangChain / LlamaIndex、长文档 chunking、FAISS / 专用向量库 / 常驻向量服务、云 embedding API。
- **归属**：E7 前置能力切片，**未立项**，等 E7 节奏再排。

## 2026-09-22 零散待办前三项：B4 security revoke + C1 ask Ctrl+C + F2 CLI-daemon 集成测试（✅ 全部完成）

> 按 `TODO.md` 顺序做前三项。全量回归 **1660 passed / 0 failed / 23 skipped**（比上轮 1642 多 18 条新增，零回归）。

### B4：`trm security revoke <token_id>`

- `ToolGateway.revoke_jit_token(token_str)`：幂等，找不到返回 False；找到则删除 + 审计日志。
- `api_server._revoke_jit_token(state, token_str)`：前缀匹配（≥4 位），多个匹配报模糊；新 RPC `security.revoke`。
- CLI `security.py`：`revoke` 子命令（走 RPC，失败返回 exit 1 + 错误信息）。

### C1：`trm ask` Ctrl+C 中断处理

- `ask.py handler`：`asyncio.run(_execute())` 外包 `try/except KeyboardInterrupt`，捕到则打印 `interrupted by user` + 返回 exit code 130（壱明 SIGINT 口径）。

### F2：CLI↔daemon 集成测试（`test_integration.py::TestCliDaemonIntegration`，9 条）

- 真 `create_app` + `TestClient` + 真 `IpcHandler` RPC router（不起真 daemon 进程）。
- 覆盖：health RPC/HTTP 合同一致、`trm status` 在线/离线、`security tokens` RPC（措蔽 + 过滤）、`security revoke` RPC（完整串 / 前缀 / 不存在）。

### 测试新增（18 条）

| 文件 | 新增 |
|---|---|
| `tests/test_cli.py` | 1（`security revoke` 解析） |
| `tests/test_cli_commands.py` | 8（revoke CLI ×4 + Ctrl+C ×1 + gateway ×3） |
| `tests/test_integration.py` | 9（F2 集成全部） |

## 2026-09-22 CLI 进阶第一项：`trm ask --image` 多模态输入（✅ 完成）

> 提交待推。全量 **1660 passed / 6 failed / 23 skipped**（6 条失败为既有宿主基线，零回归）。

### 做了什么

| 位置 | 内容 |
|---|---|
| `src/trimum_core/agent_loop.py` | 新增 `_IMAGE_MIME` / `_image_to_data_url()` / `_build_user_content()`；`run()` 与 `_plan()` 接受 `images` 参数，用户消息按 OpenAI 多模态格式携带 base64 图片 |
| `src/trimum_core/cli/commands/ask.py` | 新增 `--image` / `-I` 参数（`nargs="+"`），透传到 `AgentLoop.run()` |
| `tests/test_agent_loop.py` | 6 条新增：`_image_to_data_url`（有效 / 缺失 / 不支持格式）+ `_build_user_content`（无图 / 多图 / 空列表） |

### 关键设计

- **消息格式**：无图时 user content 保持 `str`（向后兼容）；有图时变为 `[{"type":"text",...}, {"type":"image_url","image_url":{"url":"data:...;base64,..."}}]`
- **支持格式**：png / jpg / jpeg / gif / webp / bmp / tiff
- **LLM 能力依赖**：图片以 OpenAI 兼容多模态格式发送；若 LLM 不支持 vision，API 报错由 `_plan()` 的 `except` 捕获并走 `_fallback_plan()` 降级

---
## 2026-09-22 CLI 进阶第二项：`trm memory import` / `export` 记忆迁移（✅ 完成）

> 全量 **1664 passed / 6 failed / 23 skipped**（6 条失败为既有宿主基线，零回归）。

### 做了什么

| 位置 | 内容 |
|---|---|
| `src/trimum_core/cli/commands/memory.py` | 新增 `export`（JSON v1，支持 `--file` 或 stdout）和 `import`（`--file` 或 stdin）子命令 |
| `tests/test_memory_import_export.py` | 4 条测试：空导出 / 有数据导出 / 导出→导入往返 / 版本校验 |

### 导出格式（JSON v1）

```json
{
  "version": 1,
  "exported_at": "2026-09-22T12:00:00+00:00",
  "global_entries": {"key": "value"},
  "agent_entries": {"agent-id": {"key": "value"}},
  "categories": [{"domain": "...", "category": "...", "description": "..."}]
}
```

### 用法

```
trm memory export -o backup.json
trm memory import -i backup.json
trm memory export | trm memory import   # 管道
```

---

---
## 2026-09-22 文档收尾：TODO / STATUS 校正 + 待办按模型分工（✅ 完成）

> 本轮**只动文档**（`AGENTS.md` / `TODO.md` / `STATUS.md`），零代码改动、零测试影响。

### 修正三处「与仓库现状不符」

| # | 问题 | 改法 |
|---|---|---|
| 1 | `TODO.md` / `STATUS.md` 都写「本地领先 `origin/server` 2 个提交、**未推**」，但 reflog 显示 `01819e9` 已于 **22:11:09** 推送（`git rev-list --count origin/server..server` = 0） | 两处均改为「**已与 `origin/server` 同步**」 |
| 2 | 常驻区「下一步」第 1 条指向 `TODO.md`「EventBus 通信缺口」、第 2 条指向「🚚 E5 第三片实施计划」—— 这两个小节在上一轮 TODO 改写时已删 | 改为指向 `STATUS.md` 自己的 2026-09-21 日志与 `TODO.md`「P2 杂项」 |
| 3 | 上一轮「TODO 只留未闭环」改写时**连带删掉了若干仍未闭环的项** | 全部补回（清单见下） |

### 补回的未闭环项（上一轮误删）

- **沙箱**：`TaskRegistry.SHELL` 派生子进程仍未收口（7 个 spawn 点里的第 8 个）、S4/S5 未做、`trm status` / `doctor` 未露出 Landlock + seccomp 状态。
- **LLM 路由 5 项**（与 `docs/LLM-ROUTING.md` §8 同源）：跨进程限流、token 维度计量、429 `Retry-After`、`doctor` 路由表、成本账本。
- **E7**：另两条未决（是否改用原生工具调用 / 会话记录存哪）、`scripts/accept_e7.py` 待写。
- **P2**：运行记录落盘（环形 200 条重启即丢）、启动失败退出路径（HTTP 开着的 daemon 仍走 uvicorn `sys.exit(3)`，可能被 aiosqlite 非 daemon 线程拖住）、总线历史仅内存 100 条。
- **未开工子系统**：记忆桥零调用点、`SystemMonitor` 从未被实例化、`agent_runtime` spawn 仍是 Stub。
- **新增「安全收尾」一节**：`.git/config` 里明文 GitHub token、本机 `.env` 里的真机 sudo 口令、`~/.trimum/.env` 老 stub。

### 待办按模型分工（本轮主要交付）

- `TODO.md` 每条待办打上 `【Qwen】`（交我算，免费、单次小任务）/`【DS】`（deepseek-flash，复杂件）/`【本人】`（要 sudo 或要拍产品决策）三类标签。
- 新增「🤖 模型分工」一节：标签读法、两个免记命令入口、**为什么不能全靠 Qwen**（10 次/分 vs 一个 turn 十几次调用）、`/model` 只改模型名不改 provider 的坑。
- 新增「Qwen 任务提示词（复制即用）」一节：**11 条**（`.trimumrc` 别名 / 补全脚本 / confidence 三级分流 / API Key Manager / `Retry-After` / doctor 路由表 / 成本账本 / 沙箱状态 / 剧本原地开关 / agent-sdk e2e / SonarQube 重扫），每条含落点 + 要求 + 验收，另附统一前缀（读文档 → 全量回归 → 回填文档 → 只推 `server`）。

### 顺带定下的工作方式（写进 `AGENTS.md` 已有章节，本轮验证）

- **写含中文的文件走 Node REPL 的 `fs.writeFileSync`**（UTF-8 + LF，实测 round-trip 一致、`cr=0`）；PowerShell here-string 会按 GBK 写坏。
- **Git Bash 可用**：`& "C:\Program Files\Git\bin\bash.exe" -lc "<脚本>"`（PATH 上的 `bash` 是别的包装器，别用）；中文内联、here-doc 均无损，行尾保持 LF。**别**把 bash 传成工具自己的 shell 参数 —— 那样 bash 会把 stdin 当脚本读，here-doc 会把后续内容吃掉（实测：文件建成 0 字节 + 卡住）。

## 2026-09-22 Ubuntu 真机纳管：VS Code 隧道 + 双 provider codex + 省电脚本（⏳ 部分完成）

> 目标：把开发整体搬到真机（天逸510S / i3-10100 / 7.4GiB / 机械系统盘 / Ubuntu 24.04.1），做到「随时可访问（含手机）+ 省电常驻」。
> 本轮把 **agent 能做的都做了**；剩下两条卡在【本人】：设备码授权、sudo 口令。

### 已完成（真机实测）

| # | 事项 | 结果 |
|---|---|---|
| 1 | VS Code CLI → `~/.local/bin/code` | 1.138.0，commit `7debcd0e…`，与真机既有 VS Code Server **同一 commit**（避免版本错配） |
| 2 | `~/trimum` 重建为 git 树 | 备份 `~/trimum.bak-202609222325`（21M）→ `git init` + 用 `.env` 的 `GITHUB_TOKEN` 一次性 fetch + `checkout -f -B server FETCH_HEAD` → HEAD `424dc0a` 与本地/origin 一致；remote 已还原为**无 token** 的 https URL |
| 3 | 真机装 Codex CLI + 双 provider | `npm i -g @openai/codex`（**0.155.1**）→ `~/.codex/{config,ds.config,qwen.config}.toml`（0600）、`~/.codex/env`（0600，注 `DEEPSEEK_API_KEY` / `JIAOWOISAN_API_KEY`）、`~/bin/codex-run ds|qwen` |
| 4 | 双 provider 冒烟 | **ds ✅ / qwen ✅**（各 ~9k tokens，输出 `OK`）；`~/bin/codex-smoke` 可复跑 |
| 5 | 省电脚本 | `scripts/ubuntu_slim_desktop.sh`（默认 dry-run / `--apply` / `--rollback` / `--verify`）已 scp 到真机 `/tmp/`，**等本人 sudo 跑** |

### 本轮两个坑（已定位并规避，写进 `docs/OPERATIONS.md`）

- **`codex exec` 会继承 stdin 并等 EOF**：经 SSH 管道跑时 stdin 是不关闭的 pipe，进程 `S (sleeping)`、连 socket 都没建（实测卡 7 分钟）。**必须 `</dev/null`**（再套 `timeout 240` 兜底）。
- **PowerShell 不支持 `<` 重定向**：`ssh host "bash -s" < file` 报 `The '<' operator is reserved for future use`。改走 **`scp` 到 `/tmp/` + 远端 `tr -d '\r' < /tmp/x.sh | bash`**（顺带解决 CRLF）。
- 反向依赖实测红线：真机 `apt-get -s purge ubuntu-desktop gnome-shell gdm3` 干跑结果自相矛盾（报 0 删除），而 `network-manager` 是 `ubuntu-desktop-minimal` 的反向依赖 ⇒ **purge GNOME 会连带拆网络、直接失联**。结论：**只改 target / 只停服务，绝不卸包**。

### 未完成（卡在本人 / 待决策）

- **隧道授权**：`code tunnel --name tianyi` 已在真机后台跑，停在 `https://github.com/login/device` 设备码那一步（23:37 重启后码 = `4C50-0764`）。授权前 `vscode.dev/tunnel/tianyi` 不可用。
- **常驻化**：授权后需 `code tunnel service install`（用户级 systemd）才算 7x24。
- **图形栈收敛**：改 `multi-user.target` + 停 `gdm3` + mask 睡眠 target + 停 fwupd/avahi/cups/cups-browsed/bluetooth/sysstat。收益：内存约省 0.9GiB、idle 30W→20~25W（**不动 `no_turbo`/governor**，编译变慢得不偿失）。
- **真机 `~/trimum` 残留 30 个未跟踪文件**（旧版 `PRD.md` / `ARCH.md` / `docs/*` 旧文档 / `tests_backup_20260919/` / `memory/` / `backup_*.py`），备份已在，等本人点头再清。

## 2026-09-22 夜·真机排障：隧道 Connected + 三个真凶（✅ 完成）

> 触发：本人跑完设备码授权与省电脚本后，真机屏幕黑屏、看起来像「重启卡住」。

### 结论先说：没死机，也没在重启

`uptime` 11:40（12:05 开机至今**没重启过**）、`is-system-running: running`、`systemctl list-jobs` = `No jobs running`、`--failed` 为空、load 0.00、sshd/tailscaled active。**不需要强制关机**。

### 黑屏的真凶：`gdm.service` 与 `getty@tty1` 互斥

`gdm.service` 带 `Conflicts=getty@tty1.service`。停掉 gdm 后 **getty@tty1 不会自动回来** ⇒ 本地显示器既没有图形界面也没有文字登录提示 = 黑屏。`systemctl start getty@tty1` 即可（脚本已补这一步）。

### 省电脚本只生效一半的真凶：**它是在桌面会话的终端里跑的**

`systemctl disable --now gdm3` 把整个桌面会话一起杀掉 ⇒ **脚本自己也被 SIGKILL**。实测残留：`get-default=multi-user.target` ✅、gdm3 已停 ✅，但 mask 睡眠 target ❌、avahi/cups/cups-browsed/sysstat 仍 active+enabled ❌。
⇒ **一律从 SSH 会话里跑**（已写进脚本头部红线）。

### 隧道「又要设备码」的真凶：gnome-keyring 被锁

- `~/.vscode/cli/code_tunnel.json` **只存** `{name,id,cluster}`；**GitHub token 在 gnome-keyring**（`~/.local/share/keyrings/login.keyring`）。
- 桌面会话在时 keyring 由 PAM 解锁，所以 23:40 那次授权能写进去；**gdm3 一停、会话一结束 keyring 就锁了**，SSH（`Type=tty`）里新起的 keyring-daemon 读不到 ⇒ `code tunnel user show` = `not logged in` ⇒ 又发设备码。
- **修复（实测有效）**：`printf '%s' "$USER_PASSWORD" | gnome-keyring-daemon --unlock --replace --components=secrets` → 立刻 `logged in with provider GitHub Account`，**不用重新授权**。
- 随后同会话内 `setsid nohup code tunnel ... < /dev/null &` ⇒ `status` 报 `{"tunnel":"tianyi","tunnel":"Connected","has_editor_link":true}`，`https://vscode.dev/tunnel/tianyi` 可用。

### 真机开发树

已 `fetch` + `merge --ff-only` 到 `6cacd24`；`git clean -fd` 清掉 31 项旧版残留 + 空目录 `tests_backup_20260919`，工作区干净。备份 `~/trimum.bak-202609222325` 仍在。

### 仍未闭环（等拍板）

- **重启后自动恢复**：`code tunnel service install` 需要 `sudo loginctl enable-linger guzhujushi`（本轮 attempt 因拿不到口令而卡死，已杀）。且**开机时 keyring 是锁的**，光装 service 不够，两条路二选一：
  1. **空口令默认 keyring**（备份后重建 `login.keyring`）⇒ 任何会话都能读 token，不在机器上存口令；
  2. **0600 口令文件 + 开机解锁的 user service** ⇒ 保留现有 keyring，但机器上要存登录口令。
- 省电脚本剩余步骤（mask 睡眠 target + 停 avahi/cups/cups-browsed/sysstat）需**从 SSH** 重跑一次 `--apply`。

### 顺带定下的工具纪律

- **PowerShell 内联远程命令一律别用**（`$( )`、`\"`、`| head` 会被 PowerShell 吃掉/报错，本轮连踩三次）⇒ 一律「本地写 `.sh` → `scp /tmp/` → `tr -d '\r' < /tmp/x.sh | bash`」。
- 拉起的后台进程要 `setsid nohup ... < /dev/null &`，否则会随 SSH 会话一起死。

## 2026-09-23 凌晨·平台定位裁决 + 三台盘点（✅ 完成）

### 裁决：GPU 开发留本机，真机不再承接训练类负载

- 本机：**NVIDIA GeForce RTX 5060 Laptop GPU / 8151 MiB / 驱动 592.01**
- 真机（天逸510S）：**只有 Intel UHD630 核显，无 CUDA**
⇒ 原计划「把开发整体搬到真机」在 **GPU 这一块作废**：PyTorch / CUDA / 训练一律留 Windows 侧；
真机定位收窄为「7x24 常驻服务 + 无 GPU 的日常开发（CLI / 后端 / 沙箱 / 隧道）」。

### 三台现状（2026-09-23 实测）

| | 本机（Windows） | 真机（天逸510S） | 阿里云 `8.145.36.108` |
|---|---|---|---|
| 角色 | 主力开发机（含 GPU） | 常驻开发 / 服务 | 公网入口 |
| 关键 | RTX 5060 8G；UniClash 只绑 `127.0.0.1:7993`（已用 portproxy 只对 Tailscale 放开） | `multi-user.target` 无桌面；codex 双 provider；VS Code 扩展已装；隧道 `tianyi` | 2 vCPU / **1.6Gi 内存仅剩 580Mi** / 20G 盘 58% / 已开机 33 天 |
| 服务 | 标准 Windows + UniClash（+ `:53` DNS 劫持）+ steam；另有 `:8080`(python) 与 `:57322`(node `D:\New Folder\node.exe`) **身份待确认** | sshd / tailscaled / getty@tty1；avahi / cups / cups-browsed / sysstat（**待停**） | nginx（5 站点：`code.` / `myblog` / `oc-guzhujushi` / `pan.` / `trm.`）/ frps(7000,7500,8322) / gitea / alist / myblog / caddy / tailscale / fail2ban / 阿里云备份 / **一个 VS Code tunnel** |

### 迁移候选（已进 `TODO.md` 第 9 节）

gitea、alist 可考虑挪真机（阿里云内存太紧）；myblog / frps / nginx / caddy 建议留云端；
阿里云那个 VS Code tunnel 与真机 `tianyi` 重复，可评估关掉。

### 顺带发现（已进 TODO）

- 阿里云 `frps.toml` 的 `auth.token` 偏弱，且**本轮误把该值明文写进 `TODO.md`/`STATUS.md` 并推到公开仓库**，已在新提交里抹掉字面值 ⇒ **按已泄露处理，尽快轮换**（需同步真机的 frpc 配置）。教训：写文档时任何真实密钥只能写「位置 + 形状」，绝不写值。
- 本机 `:8080`（python，绑在 Tailscale IP）与 `:57322`（node）身份不明，非管理员拿不到命令行 ⇒ 待本人确认。
- 真机可用 Clash/Mihomo 客户端（复用现有订阅）**取代** `with-proxy` 那条经笔记本的迂回路径。

## 2026-09-23 凌晨·真机 VS Code 扩展 + 备用网络通道 + 省电脚本实测（✅ 完成）

### 真机 VS Code 扩展（装在 `~/.vscode-server/extensions`，全为 `-linux-x64` 匹配版本）

用服务器自带的 `~/.vscode-server/cli/servers/Stable-7debcd0e…/server/bin/code-server --install-extension` 装：

| 扩展 | 版本 | 用途 |
|---|---|---|
| `openai.chatgpt` | 26.908.40401 | **Codex 扩展** |
| `ms-python.python` | 2026.4.0 | Python |
| `ms-python.vscode-pylance` | 2026.3.1 | 语言服务 |
| `ms-python.debugpy` / `ms-python.vscode-python-envs` | — | 随 python 扩展自动装 |
| `charliermarsh.ruff` | 2026.82.0 | lint / format |
| `tamasfe.even-better-toml` | 0.21.2 | `pyproject.toml` |
| `redhat.vscode-yaml` | 1.24.0 | `workflow.yaml` / 配置 |

原有保留：`github.vscode-pull-request-github`、`ms-ceintl.vscode-language-pack-zh-hans`。**重连 `vscode.dev/tunnel/tianyi` 后重载窗口生效。**

### 备用网络通道：Tailscale → Windows(UniClash)（已打通并实测）

- Windows 侧用 `netsh interface portproxy` 把 `100.124.243.30:7993`（**只绑 Tailscale IP**）转到 `127.0.0.1:7993`，**没有**去开 UniClash 的 Allow LAN ⇒ 不暴露到局域网。
- 真机侧新增 `~/bin/with-proxy <命令>`：按需走代理，**代理不可达自动降级直连**；三条冒烟全过。
- 实测：经代理 github 200 / 3.3–6.0s、npm 200 / 2.6s；直连 200 / 0.74s 与 0.27s；`api.github.com` 经代理 **403**（出口节点限制）。
- 结论：走的是 **DERP 中继（hkg），RTT 150–250ms，慢 4~10 倍** ⇒ 只当应急，不做全局代理。细节与撤销命令见 `docs/OPERATIONS.md`。

### 省电脚本实测（`scripts/ubuntu_slim_desktop.sh --apply` 跑过 3 次）

- ✅ 已生效：`default=multi-user.target`、`graphical/display-manager/gdm3` 全 inactive、`fwupd` + `fwupd-refresh.timer` 停、**`sleep`/`suspend`/`hibernate`/`hybrid-sleep` 全部 masked**。
- ❌ 未生效：`avahi-daemon` / `cups` / `cups-browsed` / `sysstat` 仍 active+enabled —— 三次都断在 `fwupd` 之后，疑中途报错/被中断，待带 sudo 手动复核。
- 内存：`used 714Mi`（瘦身前 966Mi）。本地屏幕：重启后 `getty@tty1` = active，黑屏问题闭环。

### 屏幕关屏的两条路（真机实测）

- `setterm --blank 1 --powerdown 1`（在 tty1 本地终端跑，**非交互 SSH 会话里要带 `TERM=linux`** 且重定向到 `> /dev/tty1`）⇒ 1 分钟无键盘输入自动黑屏，任意键唤醒。**未持久化**。
- 最省事：直接按显示器电源键（主机照常跑）。
- 不可用：`/sys/class/drm/card1-DP-1/dpms` 是 `-r--r--r--` 只读，写 `Off` 报 Permission denied。

## 2026-09-23 手机接入 Tailscale：备用通路改用 T2（VS Code Web over Tailscale）（✅ 完成）

> 触发：手机已连上 Tailscale；本人要求「域名那条废弃、Tailscale 作备选、走 T2」，并报告 `~/bin/tunnel-up` 没跑成。

### 裁决
- **废弃**：code-server + frp + Nginx 反代 `vs.guzhujushi.cn`（要备案 / 证书 / 公网暴露；真机上 `code-server` / `nginx` / `caddy` 本来就没装）。
- **备用通路 = T2**：真机 `code serve-web`，**只绑 Tailscale IP `100.115.86.48:8080`** ⇒ 免域名 / 证书 / 备案 / frp；Tailscale 负责加密与设备身份，tailnet 内仅本人 4 台设备。
- 主路仍是 `vscode.dev/tunnel/tianyi`；T2 取代原先被写成「备用」的域名方案。

### 真机实测
| 项 | 结果 |
|---|---|
| `code serve-web --help` | ✅ 存在（CLI 1.138.0）：`--host` / `--port` / `--without-connection-token` / `--accept-server-license-terms` / `--default-folder` / `--disable-telemetry` |
| 服务 | `~/bin/serve-web-up`（仓库副本 `scripts/serve_web_up.sh`）→ 只监听 `100.115.86.48:8080`（不是 `0.0.0.0`） |
| 首次启动 | 先 HTTP **202**（日志 `Downloading server 7debcd0e…`），下完转 **200** |
| 前端资源 | 由真机本地提供（`workbench.js` 19.3 MB / 200）⇒ 手机浏览器**不依赖境外 CDN**；仅扩展市场走外网（`marketplace.visualstudio.com` 200 / 1.2s） |
| Windows 经 Tailscale | **200 / 0.64s**（须加 `--noproxy "*"`：本机 curl 默认吃 `http_proxy=127.0.0.1:7993`，不加报 `000`；SSH 不受影响） |
| 手机 | `sgt-al50` 已在 tailnet，`tailscale status` 上报 OS = `android`（即 Android 版 Tailscale）；T2 只需浏览器，无需再装 App |

### `tunnel-up` 失败的根因（已定位）
- 非交互执行时拿不到 keyring 口令（无 `~/.config/trimum/tunnel.pw`、非 tty）⇒ `[1/3] 没拿到口令` ⇒ `code tunnel user show` = `not logged in` ⇒ 隧道重启后停在设备码（日志 `74F3-E72F`），**而脚本仍 `exit 0`**，容易被判成「已经跑过」。
- 日志另有一次 `failed to lookup tunnel: authorization error: … github.com/login/device/code` —— 真机直连 GitHub 偶发瞬断（已知）。
- 根治二选一（空口令 keyring / 0600 口令文件）仍待【本人决策】；**T2 通了之后这条不急**。

### 文档与产物
- `docs/OPERATIONS.md`：新增「备用通路 T2：VS Code Web over Tailscale」+「keyring 未解锁时 `tunnel-up` 的假成功」两节；隧道章节里「备用通路 = 域名方案」的说法已改。
- `TODO.md` §8：废弃域名方案、改记 T2；头部日期 → 2026-09-23。
- `scripts/serve_web_up.sh`：T2 启动脚本入库（与 `tunnel_up.sh` / `with_proxy.sh` 同等对待），真机 `~/bin/serve-web-up` 已同步为同一份。

## 2026-09-23 真机三件常驻（T2 / tunnel / mihomo）+ context7 MCP 可用（✅ 完成）

> 本人指令：T2 常驻、tunnel-up 常驻、评估 Clash 核复用订阅的可行性、试 context7 MCP。

### 一、三个用户级 systemd 服务（真机实测）

| 单元 | 结果 |
|---|---|
| `trimum-web.service` | ✅ active+enabled，只监听 `100.115.86.48:8080`，`http=200`；`~/bin/serve-web-up` 已改为 restart 该服务 |
| `trimum-tunnel.service` | ✅ active+enabled，`code tunnel user show` = `logged in`，`status` = `"name":"tianyi"` / `"Connected"` / `has_editor_link:true`；`~/bin/tunnel-up` 同改为 restart |
| `trimum-mihomo.service` | ✅ active+enabled（mihomo v1.19.31，`127.0.0.1:7890` + API `:9090`） |

- **tunnel-up 失败的根治**：采用 TODO §8 方案② —— `~/.config/trimum/tunnel.pw`（**0600**，9 字节）由 `tunnel-run.sh` 读取后 `gnome-keyring-daemon --unlock --replace`；单元里显式 `DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus`，否则 libsecret 找不到 keyring。**代价：登录口令落盘**（想改回不落盘就切方案①「空口令 keyring」）。
- **踩过的坑**：老的 `setsid nohup` 进程会继续占着 8080 / 接管隧道 ⇒ systemd 实例 `activating` 抖动、新服务「Connected to an existing tunnel process」。收编必须 `pkill -f "code serve-web"` + `pkill -f "code tunnel"` 再 `systemctl --user restart`。
- **还差一条 sudo**：`loginctl enable-linger guzhujushi`（现 `Linger=no`）。脚本 `scripts/enable_linger.sh` 已 scp 到真机 `/tmp/`，**待本人跑**。
- 仓库件：`scripts/user-units/{trimum-web,trimum-tunnel,trimum-mihomo}.service` + `{serve-web-run,tunnel-run}.sh`、`scripts/install_user_units.sh`（一键装/重装）、`scripts/serve_web_up.sh` / `scripts/tunnel_up.sh`（v2，优先走 systemd）。

### 二、Clash 核复用订阅：可行，底座已跑通

- 真机 x86_64 / Ubuntu 24.04.1 / 849G 空闲盘，`7890/9090/7993` 全空闲，无任何既有 clash/sing-box。
- 从 `api.github.com` 取 latest（真机直连 GitHub 200 / 0.7s；注意 `raw.githubusercontent.com` **000 超时**，走 api 或 objects 即可）→ 装 `~/bin/mihomo`（22.8 MB，**用户级，无需 sudo**）。
- 链路实测：`curl -x http://127.0.0.1:7890 https://github.com` → **200 / 0.79s**（DIRECT 占位配置；日志见 `[TCP] ... match Match using PROXY[DIRECT]`）。
- **唯一缺口 = 机场订阅链接**：UniClash 的订阅存在不透明存储里（`%APPDATA%\UniClash`、`%LOCALAPPDATA%\UniClash` **均为空目录**，`D:\UniClash\brand.json` = `{"site":"yangfan"}`，HKCU/HKLM 注册表无匹配，`%APPDATA%\org.ikuuu` 是另一个已停用的客户端）⇒ **需本人从 UniClash 界面复制**，写进真机 `~/.config/mihomo/config.yaml` 的 `proxy-providers`（链接**不入仓库**）。
- 风险已在 `docs/OPERATIONS.md` 列全：设备数/IP 并发限制、订阅 UA 校验、流量共享、私有规则集、Windows 侧 `:53` 劫持 vs 真机 DNS。**不上 TUN**（要 root），`mixed-port` + 环境变量足够。

### 三、context7 MCP：**可用**（已注册）

- 原先没配（`~/.codex/config.toml` 只有 `node_repl` enabled、`cua_repl` disabled）。
- 直接拉起来做了真握手：`Context7 Documentation MCP Server v4.1.1`，`initialize` / `tools/list` 正常，工具两个 = `resolve-library-id` + `query-docs`；
  实测 `resolve-library-id("FastAPI")` 返回 4 个库 ID（含 Code Snippets 2377 / Reputation High / Benchmark 84.86），`query-docs` 正常响应（会把 `/fastapi/fastapi` 重定向到 `/websites/fastapi_tiangolo`）。
- 已注册：`codex mcp add context7 -- "D:\New Folder\npx.cmd" -y @upstash/context7-mcp@latest`（**新会话才会加载成工具**）。探针脚本留在 `tmp/ctx7_probe{,2}.mjs`。
- 顺带发现：本机 `node` 实际在 `D:\New Folder\node.exe` —— 与 `STATUS.md` 里那个「身份不明的 `:57322`（node，`D:\New Folder\node.exe`）」是同一来源。

### 四、提交
- `4cd3ce5`（T2 文档与脚本）已**推送** `origin/server`（首次推送时本机代理 7993 未监听而失败，UniClash 起来后重推成功）。
- 本轮 `scripts/user-units/*` + `scripts/install_user_units.sh` + `scripts/install_mihomo.sh` + `scripts/enable_linger.sh` + `docs/OPERATIONS.md` + `TODO.md` + `AGENTS.md` + `STATUS.md` 见下一个提交。
