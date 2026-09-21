# STATUS — 当前进度

> 最后更新：2026-09-21（W1 workflow 执行语义 → **EventBus 通信审计** → **根目录文档合并与清理：删除 `PRD.md`、`ARCH.md` 去重后移入 `docs/`** → **P0 安全响应链步骤 1/3：`security.monitor_result` 载荷契约扁平化**；2026-09-20 的 M4 / M4.5 / E4 / W1 进度见文末各节）
>
> 当前阶段：Phase 3 收尾**已完成** —— P0/P1 阻断项全部清零并在真机 Ubuntu 验证通过。
> 原「下一阶段 P0 = CLI-Anything 接入」经调研**已否决**（见 `docs/CLI-ANYTHING-RESEARCH.md`）：CLI-Anything 的 `browser` 依赖 Node.js + DOMShell，且 `browser-cdp` 并不存在；浏览器能力继续用自研 CDP 工具。
> 当前方向：**生态四层**（`docs/ECOSYSTEM-STRATEGY.md`）—— L1 MCP 已完成 **M0/M1/M2/M3/M4** 与**远端工具聚合**（`<server>__<tool>` 进 `ToolRegistry`），
> E4 三个导入器已落地，W1 workflow 执行语义已闭环（真机 48/0）。
> **P0 安全响应链接线已开工**（2026-09-20 只读审计新立：`tool_gateway.py:715` 的 L4 只拦不报，剧本在真机上永远不会被自动触发）：
> **步骤 1/3（`security.monitor_result` 载荷契约扁平化）2026-09-21 完成**，剩 步骤 2（L4 改走 `_dispatch`）与 步骤 3（定 `workflow.trigger` 归属）；
> 之后是 **E5 官方分发渠道**；P2 杂项（daemon 部署形态 / 桌面确认通道 / SDK 测试 / SonarQube 重扫）随时穿插。
> 真机验收记录（Ubuntu，`guzhujushi@100.115.86.48`）：M4 隔离 daemon **16 PASS / 0 FAIL**（全量 827/11/2）；
> E4 `scripts/accept_e4.py` **43 PASS / 0 FAIL**；W1 `scripts/accept_w1.py` **48 PASS / 0 FAIL**（另 `test_workflow_runtime.py` 69 passed）。
> 失败项均为既有宿主状态基线（Windows 沙箱 / PATH 缺 `python.exe` / LLM 断网），与本轮各次开工前同名同数，无回归。

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

### 优先级判断

**P0 安全链接线 > E5 官方分发渠道**：安全响应是 trimum 的招牌能力，「拦截」能跑而「响应 / 审计 / 通知」是空的，
等于 16 条剧本 + `SecExecutor` 全是摆设；分发渠道再顺，发的也是链条断的产品。改动点只有 3 处（统一 payload 契约 /
L4 走 `_dispatch` / 定 `workflow.trigger` 归属），工作量可控。总线硬化是它的配套（`_safe_call` 静默是排障黑洞）。

---

## E4 广接入（✅ 已完成，2026-09-20）

> 计划与设计：`docs/E4-PLAN.md`；明细见文末「E4 广接入：生态导入器（2026-09-20）」。
> 提交：计划 `fdee6d5` / S1+S2+S5 `be5198d` / S3 `861126e` / S4 `05bb1ee` / S6 文档 `be604e8` / S7 验收 `b5b2121`。
> 遗留「`to_workflow_definition()` 不搬运 `instruction`」→ 已由 **W1** 修掉（见文末「W1 Workflow 执行语义」）。

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

> 2026-09-20 二次重写：E4 / W1 闭环 + EventBus 审计之后，按「哪个缺口让已有能力变成摆设」重排。
> 更早的 2026-09-01 旧清单里多数项已完成或已废弃 —— SafeMind 红蓝对抗（仓库内无 `safe_lab.py` / `red_team.py`，从未动工）、
> OpenCLI 桥接（已弃用）、CLI 流式输出（已实现）、`tmp/` 清理（已完成）、`src/trimum-mvp/`（已删除）、
> 「296/297 pass 修 AuditEvent 导出」（已被本地 1156 passed 取代）。

1. 🔴 **P0 安全响应链接线**（2026-09-20 审计新立）—— `tool_gateway.py:715` 的 L4 只拦不报：命中威胁不发 `security.monitor_result`、不调 `SecExecutor`，且生产端 payload（嵌套 `threat`）与 16 条内置剧本条件（扁平 `threat_name`）对不上 → 剧本永不自动触发。三条动作（统一契约 → L4 走 `_dispatch` → 定 `workflow.trigger` 归属）见 `TODO.md`「EventBus 通信缺口」
2. 🔴 **E5 官方分发渠道** —— `.trmpkg`（manifest + 逐文件 sha256 + 签名 + 证书链）→ 内置根验证 → `trm install <name>` / `--file <pkg>`；含 E6 遗留的证书 `capabilities` 运行期合并（设计见 `docs/ECOSYSTEM-STRATEGY.md` §7）
3. 🟠 **总线硬化**（P0 的配套）—— `_safe_call` 别静默吞异常 + 兑现 `TRM-9005`；`EventIndex` 接进 `EventBus`；修 `LiveConsole.subscribe_events` 的订阅 / 比对不匹配；清死订阅与过期文档
4. 🟠 **W1 遗留：`WorkflowListener` / TARL 三段式接线** —— `event.transform.completed` 无生产者、`TransformAgent` 无调用点、`WorkflowListener` 未实例化（要把 TransformAgent 接进 daemon + 决策 + 确认，比 P0 大）；另：运行记录只在内存、内置剧本只有落盘式开关
5. 🟡 **桌面/WebSocket 确认通道**（P2）—— `SecurityAgent.confirm()` 目前只有 CLI 交付手段
6. 🟡 **CLI 小缺口三连** —— `trm security revoke <token_id>` / `trm ask -i` 的中断处理（`ask.py` 无 `KeyboardInterrupt` / `EOFError`）/ `trm memory import|export`
7. 🟡 **引擎侧两个半成品** —— `src/agent-sdk` 端到端测试与打包验证（`tests/` 无覆盖）；Policy Engine 正则→LLM 混合（`LlmPolicyEngine` 骨架未接线）；`transform_agent` 的 confidence 三级分流
8. 🟢 **SonarQube 重扫** / **daemon 部署形态二选一**（`trmd.service` root 或用户态路径）
9. ⏸️ **未开工子系统**（别误判为 bug）—— eBPF 告警 `security.ebpf_alert`、性能熔断 `security.fuse_triggered`、审计断链检测 `security.audit_breach`（`SecAudit.verify_chain()` 已实现但无人调用）
10. 🅿️ **E7 自研 coding Agent** —— 大工程，等前面收口（调研件见 `tmp/research/ecosystem/ecc-*`）

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
| `WorkflowListener` 从未被实例化 | `api_server.py` 只起了 `WorkflowEventDriver`；`workflow.trigger` 事件只发不收 |

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

- **`WorkflowListener` 仍未接线**：Transform TARL 三段式那条链没有实例化；它的 `workflow.trigger`
  事件已能被运行时消费（workflow 写 `trigger.event_type: workflow.trigger` 即可）。
- 运行记录只在内存（环形 200 条），进程重启即丢；`trm workflow status/log` 仍是桩。
- 内置剧本的启用开关只有 `trm workflow enable <id>`（落盘法），没有「原地开关」。
- daemon 只暴露只读端点；`POST /api/workflows/{id}/trigger` 这类执行入口**故意没开**（避免无鉴权执行面）。
- 散文式步骤需要装了 Agent 脚本的 driver 才能真正跑（`trm-agent`），否则节点明确失败。

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
