# STATUS — 当前进度

> 最后更新：2026-09-01（v12 — Security Agent + Behavior Monitor + Phase 3 架构组件）
>
> 当前阶段：Phase 3 进行中（Communication Architecture + Security）

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

1. 🔴 **Agent SDK 封装** — 集成 openai-agents-python 作为底层，在其上包装 Tool Gateway + Security Agent 权限层（当前 `src/agent-sdk/` 是空目录，是最关键的未完成项）
2. 🔴 **上下文窗口管理** — 复刻 Pydantic AI Harness 的 Compaction 模式：工具输出截断 + 滑动窗口。当前无任何上下文控制，长期运行 Agent 必然 token 爆炸
3. 🟡 **全链路集成** — Security Agent ↔ Agent Router / Tool Gateway / API Server 连接起来
4. 🟡 **可观测性基座** — LLM 调用封装 + Token 计数 + 结构化日志（管道到 disk/
5. 🟡 **凭据脱敏** — Tool Gateway 执行前扫描 API key/token 模式，替换为 `***`
6. 🟡 **弹窗确认的 API/UI 入口** — 用户如何收到弹窗、如何确认
7. 🟢 **Transform Agent 稳定性测试** — 不同输入生成 TARL 正确率验证（含 #8.5 confidence 字段）
8. 🟢 **Workflow Engine TARL 接入** — match() 用 KV 前缀索引替代正则
9. 🟢 **Security Agent TARL 接入** — `cmd:` 前缀直接映射策略规则
10. 🟢 **Policy Engine 学习模式** — Behavior Monitor 观察→动态生成 allow ruleset
11. 🟢 **SonarQube 重扫** — 确认修复效果，无回归
