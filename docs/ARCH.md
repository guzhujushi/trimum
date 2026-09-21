# ARCH — trimum 架构

> **架构单一事实源**（2026-09-21 由根目录 `ARCH.md` 移入 `docs/`；同时删掉与 `docs/` 专题文档重复的规划快照，根目录不再保留 `PRD.md` / `ARCH.md`）。
> 需求与生态方案见 `docs/ECOSYSTEM-STRATEGY.md` / `docs/MCP-INTEGRATION-PLAN.md`，运维见 `docs/OPERATIONS.md`；进度与待办见 `STATUS.md` / `TODO.md`。

## 技术选型

- 语言：Python 3.12+
- Web 框架：FastAPI
- 数据模型：Pydantic v2
- 工具插件：`~/.trimum/tools/<name>/{tool.json5,main.py}`

## browser 路由设计

1. `models.ToolType` 新增 `BROWSER = "browser"`，使 `ExecuteRequest.tool` 接受
   `"browser"`。
2. `ToolGateway.execute()` 以 `request.tool.value`（即 `"browser"`）查询
   `ToolRegistry`，命中文件工具定义后调用 `ToolRegistry.get_executor("browser")`。
3. `tool_file_loader.TOOL_KINDS` 增加 `"browser" -> ToolType.BROWSER` 映射。
4. `ToolGateway._check_cwd_jail()` 将 `ToolType.BROWSER` 加入免 cwd 校验集合，
   与 `CUSTOM` 等无文件系统路径依赖的工具一致。
5. CDP 地址解析优先级：`cdp` 请求参数 > `CLI_ANYTHING_CDP_URL` > `http://localhost:9222`。

## `trm` CLI 设计

### 目录结构

- `src/trimum_core/cli/__init__.py`：`main(argv)` 入口，分发到 handler。
- `src/trimum_core/cli/__main__.py`：支持 `python -m trimum_core.cli`。
- `src/trimum_core/cli/parser.py`：构建根 parser 与全局 `--json`/`--version`。
- `src/trimum_core/cli/_utils.py`：版本、JSON 输出、RPC/HTTP 探测、daemon 状态等公共能力。
- `src/trimum_core/cli/commands/`：每个命令模块导出 `add_subparsers()`。

### 关键规则

- `commands.register_all()` 使用 `pkgutil` 动态导入命令模块，跳过私有模块。
- 每个子命令通过 `parser.set_defaults(handler=handler)` 绑定 `def handler(args) -> int`。
- 全局 `--json` 递归注入所有子 parser，使用 `argparse.SUPPRESS` 避免覆盖根参数。
- 不引入 click/typer；daemon 交互优先 JSON-RPC，HTTP API 作为 fallback。

## Tool Gateway 分层（2026-09-19 更新）

`ToolGateway.execute()` 的检查顺序：

1. **Layer 0 — cwd Jail**：工作目录白名单（`ToolType.BROWSER/CUSTOM` 等免检）。
2. **Layer 1 — PolicyEngine**：`config/policy.yaml` 正则规则，带 `source_type` 感知；
   `interactive=True` 时对 confirm 直接弹窗。可叠加 `LlmPolicyEngine` 增强判定。
3. **Layer 2 — Agent 权限**：`AgentManifest` 声明的 exec/deny_exec/read/write。
4. **Layer 2.5 — SecurityRule（弹性沙箱决策中心）**：`can_execute()` 合并
   PolicyEngine + BehaviorMonitor + 资源阈值，返回 allow/confirm/deny。
   - deny → `status=denied`，审计事件 `security_blocked`
   - confirm → 升级为 `Action.CONFIRM`（interactive 时弹窗，用户确认后回落 AUTO）
   - `TrimumError(RESOURCE_LIMIT_EXCEEDED)` → deny；其他异常 fail-open 并记日志
   - 网关默认自建 SecurityRule，并关闭其内部资源阈值检查
     （`enforce_resource_limits=False`）：网关是单条命令粒度，拿不到 Agent cgroup
     上下文，配额由 `AgentManager` / `CgroupV2Controller` 负责
5. **Layer 4 — SecMonitor**：威胁特征匹配（DENY 直接拦截）。
6. **Layer 3 — JIT 授权**：高风险操作需要一次性令牌。
7. **执行**：文件工具 `main.py` 优先，其次 DispatcherRegistry；随后凭据脱敏 + 审计。

**决策合并（`_merge_decision`）**：各层结论与工具自报结果按「网关优先」合并 ——

- 工具自报 `status in ("", "allowed")` 视为「未表态」，最终 `status` 以网关为准；
- 网关 `action` 为 `DENY` / `CONFIRM` 时覆盖工具默认的 `AUTO`（否则 Layer 1 的 confirm
  会被文件工具返回的 `allowed/AUTO` 吞掉）；
- 两组结果都带风险等级时取更高者（`_RISK_RANK`）。

## IPC 监听与 daemon 运行要点

- **监听 socket 必须非阻塞**：`IpcHandler._start_unix_socket()` / `_start_tcp_fallback()`
  都调用 `sock.setblocking(False)`。`loop.sock_accept()` 只在 debug 模式下校验非阻塞标志，
  阻塞 socket 会让 `accept()` 直接卡在事件循环线程里 —— 表现为「daemon 起来了但整体假死、
  测试挂住」。Windows 走 `unix_socket_skipped_windows` 分支，所以只有 Linux 会踩到。
- **配置决定 socket 路径**：daemon 的 cwd 决定加载哪份 config（`/opt/trimum/config.yaml`
  用 `/run/trimum/trimum.sock` 这类系统路径，普通用户运行会 `unix_socket_start_failed`，
  此时 `trm` 自动退回 HTTP API，功能可用但 RPC 不可用）。
- **启动协程必须定义在模块级**：曾把 `_learning_loop` 定义在 `startup()` 内部却在定义前
  `create_task(_learning_loop(...))`，局部名未绑定 → daemon 启动即
  `UnboundLocalError` + `Application startup failed`。`tests/test_api_server_startup.py`
  直接跑一遍 startup handler 兜住这类问题。

## 上下文窗口管理（`context_compactor.py`）

`AgentLoop` 不再把历史 JSON 硬截断，改为 `ContextCompactor.build(history)`：

- **单条输出限长**：2400 字符（头 1600 / 尾 800，中间折叠为「已省略 N 字符」）
- **滑窗**：最近 5 步保留原文
- **早期步骤摘要**：每步一行（名称 + 命令 + 状态 + 输出摘要，≤160 字符）
- **总预算**：3000 字符，超预算时按「最新优先」丢弃，并标注省略数量

纯规则实现，不调用 LLM；策略由 `CompactionPolicy` 注入，便于按模型上下文窗口调整。

## 审计与可观测性（`audit_store.py`）

- **落盘**：`AuditStore` 以 JSONL 追加写入 `Path(Config().log_path).parent/"audit.jsonl"`，
  单文件超过 5MB 轮转为 `audit.jsonl.1`（只保留一代）。
- **健壮性**：追加失败只记日志不抛异常（审计不能影响主流程）；读取时整行 JSON 解析失败则跳过。
- **广播**：`ToolGateway._publish_audit()` 把同一条事件以 `task.audit.<event_type>` 发到
  `EventBus`；`policy_denied` / `security_blocked` / `cwd_jail` / `jit_auth` 用 WARNING 级别。
  无运行中的事件循环时静默跳过（CLI 单次执行场景）。用 `create_task` 并持引用避免任务被回收。
- **查询**：`trm log audit [--event-type X] [--agent Y] [--risk Z] [--since 1h]` 直读结构化文件；
  文件不存在时回退到旧的主日志文本过滤，保证兼容。
- **学习旁路**：行为采样（`_observe_behavior`）在 `_record_audit()` 开头执行、先于 `enable_audit`
  早退，因此学习不依赖审计开关。

## 策略学习反馈环

```
命令执行/被拒  ->  BehaviorMonitor.record_command()/record_deny()
                       |
        （60s 周期）   v
             LearningEngine.analyze()  ->  generate_ruleset()
                       |
                  inject_to_policy(source="learned", 去重)
                       v
                 PolicyEngine（仅 auto 模式自动注入）
```

- `behavior_monitor.py` 维护 `ACTION_TYPE_COMMANDS` 单一数据源，`classify_command()` 查表；
  `pattern_for_action_type()` 反向生成命令正则（`^(cat|less|...)\b`），供学习规则直接使用。
- `learning_engine.py` 的规则 pattern 必须是**真实命令正则**（早期版本写的是操作类型名，
  永远匹配不到命令行）；置信度按 `raw/0.8` 归一化后才与阈值（默认 0.85）比较。
- 对外：`GET /api/security/learning` 查画像，`POST /api/security/learn {"inject": bool}` 触发分析，
  CLI 对应 `trm security learning` / `trm security learn [--inject]`。

## 子 Agent 启动器（`agent_launcher.py`）

- **脚本布局**：`agents_root()/ <agent_id>/main.py`；Linux 为
  `~/.local/share/trimum/agents`，Windows 存在 `~/.trimum/agents` 时回退到该目录。
- **环境变量契约**：`TRIMUM_AGENT_ID` / `TRIMUM_AGENT_TYPE` / `TRIMUM_SOCKET_PATH`。
- **进程**：`create_subprocess_exec(sys.executable, <脚本绝对路径>, agent_id, cwd=脚本目录)`；
  启动后 `STARTUP_GRACE_SECONDS`(0.15s) 内退出则判为失败，返回带日志尾部的
  `error`，避免「假 RUNNING」。
- **输出落日志**：子进程 stdout/stderr 追加写入
  `<agents_root>/../agent-logs/<agent_id>.log`，**不用 PIPE** —— 没人读的管道写满
  64KB 会把 Agent 卡死，短命的 CLI 进程退出时还会抛 asyncio "Event loop is closed"。
  秒退诊断只读本次启动写入的区间（记录启动前文件偏移），同 id 反复启动不会串台。
- **cgroup 绑定**：spawn 成功后立刻 `apply_cgroup(agent_id, pid, limits)` ——
  Linux 走 `CgroupV2Controller`，Windows 走 `PsutilController`。
- `terminate_process()` 负责 SIGTERM/结束，`stop_agent()` 先终止进程再删记录。
- 无脚本时保持旧语义（`INITIALIZED`，不报错），便于渐进接入。
- 部署模板见 `scripts/agent-template/main.py`。


## 生态四层（L0–L3）

> 战略、竞品对比与路线图（E0–E7）见 `docs/ECOSYSTEM-STRATEGY.md`。核心判断：**做生态集成器，不做生态复制品**。

| 层 | 内容 | 落点 |
|---|---|---|
| **L0 环境清单** | `trm env inventory` / `trm env install`（探测 + 显式安装；不自建包仓库） | `env_toolchain.py`（见「环境层与工具链安装（E3）」） |
| **L1 协议（MCP）** | MCP client + `~/.trimum/mcp/*.json5` + 远端工具聚合 | `mcp_client.py` / `mcp_registry.py` / `mcp_bridge.py` |
| **L2 知识（Agent Skills）** | `trm skill list/import/sync`，`SKILL.md` 分发进各宿主技能目录 | `skill_sync.py`（见「命令面契约与技能分发（E1）」） |
| **L3 目录（workflow）** | `workflows/*.yaml`（Warp 式）→ 编译进 Workflow / TARL 引擎 | `workflow_catalog.py` / `workflow_runtime.py`（见「Workflow 执行语义（W1）」） |

- **统一底座**：四层产出的能力注册进同一张生态表（`trust` / `risk` / `requires` / `source_url` 元数据），
  一律经 ToolGateway 分层与审计；第三方来源默认 `enabled: false`。
- **自描述能力面**：`trm commands --all/--json/--check`，让 Agent 运行时枚举全部能力。
- **第三方 harness 只作可选导入源**，不写进默认安装，不改技术栈依赖。

## 浏览器工具（2026-09-20 调研结论）

- `~/.trimum/tools/browser/`（`main.py` + `_cdp.py`）是**自研纯 Python CDP 实现**，19 个 action，
  默认 CDP 后端（连 `--remote-debugging-port=9222` 的 Chrome，保留登录态），DOMShell 仅作可选后端。
- CLI-Anything 的 `browser`（`cli-anything-browser`）依赖 Node.js + npx + DOMShell 扩展，**不引入**；
  `browser-cdp` 在该仓库中并不存在。证据见 `docs/CLI-ANYTHING-RESEARCH.md`。
- 仅借鉴其约定：工具自带 SKILL.md、registry 的 `requires` 依赖前置声明字段、能力矩阵（`cli-hub can <task>`）
  与 Workflow TARL 匹配的同构关系。

## 命令面契约与技能分发（E1，2026-09-20 已实现）

### 命令元数据契约（`src/trimum_core/cli/registry.py`）

- 命令面**从 argparse 树推导**（单一事实源，不会漂移），命令模块可选声明
  `__command_meta__ = {"<group> <command>": {summary/args/examples/aliases/hidden/requires_sudo/risk/tags}}`
  补充 argparse 表达不了的信息。
- 别名折叠：`add_parser(name, aliases=[...])` 会把同一 parser 注册成多个 choice，
  采集时按 parser 身份归并，别名只出现在 `aliases` 字段，不重复计入命令面。
- `check_commands()` 校验：未知元数据键、元数据指向不存在的命令、leaf 缺摘要或缺 handler、
  `risk` 取值非法、别名遮蔽既有命令。`trm commands --check` 退出码非零即失败，
  测试 `tests/test_cli_commands_meta.py` 复用同一套规则，元数据无法腐化。

### 技能分发（`src/trimum_core/skill_sync.py`）

- 两层技能严格分离：**Agent Skills**（`SKILL.md`，给 Claude Code / Codex / Gemini CLI 等读）
  会被分发；**trimum 技能**（`skill.yaml`，由 `SkillExecutor` 执行）只登记不分发。
- 源根：`~/.trimum/skills` → `$TRIMUM_SKILLS_DIR` → 仓库 `skills/`（源码布局），先命中者胜。
- 目标根：`~/.agents/skills`、`~/.claude/skills`、`~/.codex/skills`、`~/.pi/agent/skills`、
  `~/.gemini/config/skills`、`~/.hermes/skills`、`~/.trimum/agent-skills`；可用 `$TRIMUM_SKILL_TARGETS` 覆盖。
- 链接策略 `auto`：symlink → Windows junction（`mklink /J`，无需管理员）→ 目录复制；
  冲突（目标已存在且不是指向本源的链接）默认拒绝，`--force` 才替换；`--prune` 清理悬空链接。
- 判断链接需同时看 `is_symlink()` 与 `os.path.isjunction()`（Windows 上 junction 不是 symlink）。

## 宿主探测与首启引导（E6，2026-09-20 已实现）

- **不假设预装**：`src/trimum_core/hosts.py` 维护 14 个已知宿主（`.agents` / `.claude` / `.codex` / `.pi` /
  `.gemini` / `.hermes` / `.cursor` / `.opencode` / `.kimi` / `.qwen` / `.zed` / `.kiro` / `.trae` / `.openclaw`），
  证据三路：`TRIMUM_HOSTS` 强制、配置目录存在、PATH 上的 CLI（`TRIMUM_HOSTS_DISABLE` 反向排除）。
- **分发目标由探测决定**：`skill_sync.default_target_roots()` 默认只返回「已存在宿主」的技能根 + trimum 自己的
  `~/.trimum/agent-skills`（永远存在，保证零预装可跑）；`all_hosts=True` / `--all-hosts` 恢复全量预置模式。
- **数据根单一入口**：`src/trimum_core/paths.py` 的 `trimum_home()`（`TRIMUM_HOME` 可覆盖）为将来多用户
  「每用户一份 root」与 `/etc/trimum` 系统公共层预留唯一改点；本轮只在新模块使用，不重构既有调用点。
- **身份**：`src/trimum_core/identity.py` 生成 Ed25519 密钥对（`~/.trimum/identity/identity-ed25519.key`，POSIX 下 0600）
  与自签身份文档 `identity.json`（`schema` / `user` / `machine_id` / `public_key_fingerprint` /
  `capabilities: {tools, max_risk, expires_at, scope}`）。`cryptography` 为**可选依赖**：缺失时状态 `skipped`，
  不写半成品；`max_risk` 非法值直接报错（能力只收紧）。
- **向导**：`src/trimum_core/setup_wizard.py`（步骤 `hosts` / `identity` / `toolchain` / `skills`，可 `--skip`）
  + `trm setup` 命令；选装清单 `config/setup-catalog.yaml`（7 组 25 项，含 pacman / apt / winget 包名，
  **只登记不安装**，实际安装留给 E3 的 `trm env install`）。状态落 `~/.trimum/config/setup.json5`。
- **与旧向导的关系**：`trm install` 保持原有 systemd / API Key 引导，`trm install --setup` 复用新向导；
  `trm install <name>`（官方包安装，E5）留给将来，不与向导抢名称。
- 测试：`tests/test_hosts.py`、`tests/test_setup_wizard.py`、`tests/test_skill_sync.py::TestDynamicTargets`。

## MCP 接入（E2，2026-09-20 已实现：M0/M1/M2）

> 生态四层的 **L1**（`docs/ECOSYSTEM-STRATEGY.md` §3）。方案与阶段划分见 `docs/MCP-INTEGRATION-PLAN.md`；
> M4（HTTP/SSE + 空闲回收 + cgroup + 常驻池）与 M4.5（远端工具聚合）见下节。

### 模块

| 模块 | 职责 |
|---|---|
| `src/trimum_core/mcp_client.py` | 协议层：stdio 子进程 + JSON-RPC 2.0 换行分帧；`connect` / `initialize` / `list_tools` / `call_tool` / `ping` / `close` |
| `src/trimum_core/mcp_registry.py` | 定义与生命周期：`~/.trimum/mcp/<name>.json5` → `MCPServerDefinition`；`MCPRegistry` 加载并上报坏文件；`MCPServerPool` 懒启动 / 按名复用 / 坏连接重建 |
| `tool_dispatchers.MCPDispatcher` | 翻译层：`mcp.tools.list` / `mcp.tools.call` → MCP 调用 → JSON 输出 + `mcp_call` 审计 |
| `cli/commands/mcp.py` | `trm mcp list/tools/call/paths`，与网关共用同一个 dispatcher（不是第二套实现） |

### 关键设计（M0 冻结）

- **自研最小 client，不引入 SDK / Node**：MCP 的 stdio 分帧就是「一行一个 JSON-RPC 2.0」（与 LSP 同款），
  `create_subprocess_exec` + `readline()` 足够；将来若 coding Agent 走 openai-agents，可只替换 transport，
  `MCPClient` 接口不变。
- **stderr 落日志文件**（`mcp-<name>.log`），不用 PIPE：避免写满 64KB 管道卡死，以及短命进程在事件循环关闭后
  flush 报错 —— 与 `agent_launcher.py` 同一约定。
- **一次一个在途请求**（每客户端一把锁）：顺序答复的服务器不会被并发打乱；超时 / 非法 JSON / 提前 EOF 一律标记
  broken，由 pool 丢弃并重建，不允许「半死不活的流」继续用。
- **deny-by-default**：`enabled` 缺省 `false`；`allow_tools` / `deny_tools` 为 glob 白黑名单（**deny 优先**）；
  `trust: cloud` 额外继承默认 deny 模式（`*delete*` `*exec*` `*shell*` `*eval*` …），远端 server 不能靠改名拿到破坏性本地工具。
- **不新开旁路**：MCP 调用与内置工具走**同一层** ToolGateway 分层（Policy → Agent 权限 → SecurityRule → JIT）+
  审计 + 凭据脱敏；MCP 类型本就在 `_check_cwd_jail` 的跳过表里（它不碰工作目录）。
- **审计**：每次调用记 `mcp_call` 事件（server / tool / transport / trust / 耗时 / 结果 / 参数**键名**），
  **参数值绝不入审计**；`ToolGateway` 构造完成后把 `audit_store` / `event_bus` 回填给 dispatcher（`bind_audit`），
  事件以 `task.audit.mcp_call` 广播。被策略拦下的调用同样留痕（duration 0，action denied）。
- **参数与输出**：`mcp.tools.list [server]`（空 = 所有已启用）、`mcp.tools.call <server> <tool> [json-arguments]`；
  输出一律 JSON，Agent 可直接消费。
- **CLI 输出纯净**：`cli.main()` 现在把 structlog 诊断路由到 **stderr**（`logger.setup_cli_logging()`），
  否则 `trm --json ...` 的 stdout 会混进 `mcp.started` 这类 INFO 行（本轮实测到的既有缺陷，已修）。
- 测试：`tests/fixtures/mcp_echo_server.py` 是**真协议** stdio server（不是 mock），
  `tests/test_mcp_client.py`（16）+ `tests/test_mcp_registry.py`（27）+ `tests/test_mcp_dispatcher.py`（30）。

## MCP 策展导入器（M3，2026-09-20 已实现）

> 生态四层 **L1 的入口**（姿势 B，`docs/MCP-INTEGRATION-PLAN.md` §5/§5.1）：把上游 4,000+ 条
> `awesome-mcp-servers` 压成一份**候选清单**，让人只审「能用的那一小撮」。

### 模块

| 模块 | 职责 |
|---|---|
| `src/trimum_core/mcp_catalog.py` | 解析 README 快照 → 条目分类（语言 / 范围 / 系统 / 官方 / 分发）→ 红线筛选 → 渲染候选清单；只读输入、离线、确定性输出 |
| `config/mcp-catalog.yaml` | 产物（tracked）：232 条候选，按分类分组，条目一律 `reviewed: false` |
| `cli/commands/mcp.py` | `trm mcp catalog import [--dry-run\|--force\|--limit\|--category …]`、`trm mcp catalog list [--unreviewed\|--category\|--dist\|--lang]` |

### 关键设计

- **候选 ≠ 生效**：导入器**不写** `~/.trimum/mcp/`、不启动任何 server、不联网；产物里每条都是 `reviewed: false`，
  启用仍走 §4.2 的文件化注册（deny-by-default 不破）。
- **红线可解释**：拒绝原因按 `section:*` / `language:*` / `dist:*` 计数写进产物摘要 —— 4,118 条 → 232 条候选的
  差额逐项可查（ts 2,219 / 描述无安装方式 1,356 / npx+npm 16 / brew 7 / 非 server 小节 27 …），不静默丢弃。
- **确定性**：无时间戳、稳定排序（官方 → 本地 → 分类 → repo），同输入同字节；`--force` 重导入按 `repo`
  保留人工写下的 `reviewed` / `name` / `note`，审核成果不会被下一次刷新冲掉。
- **名称直接可用**：`name` 满足 `^[a-z0-9][a-z0-9_-]{0,63}$`（与 `mcp_registry.NAME_PATTERN` 同规则），
  重名自动退避（`mcp-server` → `other-mcp-server` → `…-2`），条目可原样落成 `<name>.json5`。
- **写入策略**：默认拒绝覆盖已存在的清单，`--force` 才写（写前先读旧文件做 carry-over）；落盘强制 LF
  （tracked 文件，Windows 检出不得变 CRLF）。
- 测试：`tests/test_mcp_catalog.py`（52）—— 离线 fixture（`tests/fixtures/awesome-mcp-sample.md`）
  + 真实快照（`tmp/research/awesome-README.md`，缺失时自动 skip）。
## MCP 远端工具聚合（M4.5，2026-09-20 已实现）

> E2 差距表（`docs/MCP-INTEGRATION-PLAN.md` §2.2）里的第 ③ 项：远端工具以 `<server>__<tool>`
> 并进 `ToolRegistry`，Agent 从一张表里就能看到「本地 + 远端」全部工具，不必先 `mcp.tools.list`
> 再照抄参数去 `mcp.tools.call`。

### 模块

| 模块 | 职责 |
|---|---|
| `src/trimum_core/mcp_bridge.py` | 命名（`flat_name` / `split_name`）、定义指纹（`fingerprint`）、缓存（`MCPToolIndex`：`load` / `record` / `entries` / `forget` / `prune`，原子写） |
| `tool_gateway.ToolRegistry` | `load_mcp_tools()` 读缓存并把聚合条目注册成 `ToolType.MCP_TOOLS_CALL` 定义；`mcp_binding()` / `list_mcp_tools()` 给出处；`register()` / `unregister()` 会撤掉同名的聚合来源 |
| `tool_dispatchers.MCPDispatcher` | 每次成功 `tools/list` 顺手 `record()`；`mcp.tools.call` 接受聚合名（`_split_call`） |
| `api_server.start_mcp()` | **一个** `MCPToolIndex` 实例同时交给 dispatcher（写）与 `ToolRegistry`（读）；启动时 `prune_mcp_index()` 对一次账 |
| `mcp_registry.definitions_readable()` | 清缓存前分清「目录不存在」（= 一个都没配，可清）与「目录在但列不出来」（= 不知道，别动） |
| `cli/commands/tool.py` | `trm tool list [--mcp]` 标注 `source: local\|mcp` 与 `mcp.{server,tool,transport,trust}` |

### 关键设计

- **缓存，不是实时拉取**：M4 之后 MCP server 是懒启动 + 空闲回收的，「列远端工具」若得先把每个
  server 拉起来，就等于把懒启动整个抵消掉。所以 `~/.trimum/mcp-tools.json`（`TRIMUM_MCP_INDEX`
  可覆盖）只记「上一次成功 `tools/list` 的结果」，**读它不启动任何进程**。
- **命名与歧义**：`<server>__<tool>`，`split_name` 按**第一个** `__` 切（工具名里再含 `__` 不影响）。
  服务端名字本身允许 `__`，所以调用时由注册表裁决：`args[0]` 是个真存在的 server 就走经典两参数
  解释，否则当聚合名 —— `mcp.tools.call a__b c` 不会把 `a__b` 误拆成 `a` + `b`。
- **失效**：条目带定义指纹（transport / command / args / env **键名** / url / header 键名 / trust /
  allow_tools / deny_tools / enabled）。`record()` 整份替换该 server（撤掉的工具不会留成僵尸名字），
  `forget()` 清一个 server，`prune()` 清「定义已经不存在」的 server。「不存在」包括**目录整个被删**（那时每一条都是幽灵条目）；只有目录
  在、却列不出来（权限 / IO）才算「不知道有哪些 server」而不动缓存。`reap()` 回收进程时**不动**缓存：
  清单是信息不是许可证，调用仍然走 `mcp.tools.call` 的完整分层与审计。
- **密钥不入盘**：指纹只取 `env` / `headers` 的**键名**，测试断言密钥值不出现在缓存文件里。
- **名字冲突**：聚合名撞上本地工具时本地工具赢（显式注册 > 缓存条目），并记 `skipped` 计数；
  本地工具被一条缓存盖掉属于事故，远端工具少一个入口只是少一个入口。
- **测试隔离**：`tests/conftest.py` 把 `TRIMUM_HOME` 指到临时目录，整套测试不再写真实 `~/.trimum`
  —— 顺带修掉了 3 个长期因沙箱拒绝写宿主 home 而失败的用例。
- 测试：`tests/test_mcp_bridge.py`（93）。

## 环境层与工具链安装（E3，2026-09-20 已实现）

> 生态四层的 **L0**（`docs/ECOSYSTEM-STRATEGY.md` §3）。定位：**软件生态交给发行版** ——
> trimum 不自建包仓库，只回答「机器上有什么 / 能不能装 / 装的时候会执行什么」。

### 模块（`src/trimum_core/env_toolchain.py`）

- **包管理器表**：每个管理器声明探测命令（`probe`）、列举已装（`list_cmd`）、安装命令（`install_cmd`）、
  是否需要 `sudo`、适用平台；`INSTALLABLE_IDS` 决定「trimum 可代装」的集合（`mise` 不在其中）。

| 管理器 | 平台 | 探测 | 列举已装 | 安装 | sudo |
|---|---|---|---|---|---|
| `pacman` | linux | `pacman --version` | `pacman -Qq` | `pacman -S --noconfirm` | 是 |
| `apt` | linux | `apt-get --version` | `dpkg-query -W -f ...` | `apt-get install -y` | 是 |
| `dnf` | linux | `dnf --version` | `rpm -qa` | `dnf install -y` | 是 |
| `zypper` | linux | `zypper --version` | `rpm -qa` | `zypper --non-interactive install` | 是 |
| `apk` | linux | `apk --version` | `apk info` | `apk add` | 是 |
| `brew` | darwin/linux | `brew --version` | `brew list -1` | `brew install` | 否 |
| `winget` | win32 | `winget --version` | `winget list` | `winget install -e --id` | 否 |
| `scoop` | win32 | `scoop --version` | `scoop list` | `scoop install` | 否 |
| `mise` | 全平台 | `mise --version` | `mise ls` | **不代装**（只管运行时版本，只登记） | 否 |

- **顺序即优先级**：`KNOWN_MANAGERS` 的顺序决定 `inventory()` 的 `preferred_manager`
  （pacman → apt → dnf → zypper → apk → brew → winget → scoop）。
- **解析**：`parse_installed()` 按管理器的输出语言解析（dpkg 的 `name:arch` 去后缀；pacman / brew 一行一名；
  **winget 按列对齐切分**取 `Id` 列 —— winget 的 Name 列可能含空格，不能用 `split()[1]`）。
- **单遍探测**：`inventory(statuses=...)` 复用调用方已跑过的探测结果，`trm env install` 因此只探测一遍包管理器
  （有测试断言 `detect_managers` 只被调用一次）。
- **sudo 策略**：`build_command()` 在管理器需要且当前进程**不是 root** 时加 `sudo`；显式 `use_sudo=` 优先
  （跨平台单测依赖这个显式开关）。`commands_for()` 决定调用次数：**winget 一包一条命令**，其余合并成一条。
- **计划与执行分离**：`plan_install()` 只产出「确切命令 + `already_installed` / `unavailable` / `unknown` 三类清单」；
  `run_install()` 是**唯一的执行点**，`dry_run=True` 时连 runner 都不调用。

### 命令（`src/trimum_core/cli/commands/env.py`）

- `trm env inventory [--manager ID] [--catalog PATH]` —— **risk: low**，只读：管理器现状 + 目录覆盖（已装 / 可选 / 选装记录）。
- `trm env install <name>... [--manager ID] [--dry-run] [--yes] [--catalog PATH]` —— **risk: high，requires_sudo**：
  未知条目或该管理器无对应包 → 直接失败；否则打印计划与命令，确认后执行。

### 安装红线（契约，写进代码与测试）

| 红线 | 落点 |
|---|---|
| 不自建包仓库 | 只调系统包管理器；`config/setup-catalog.yaml` 只登记包名 |
| 探测与清单只读 | `detect_managers()` / `inventory()` 不做任何写操作（risk: low） |
| 安装必须显式确认 | 交互确认，或非交互 `--yes`；否则 abort（退出码 1） |
| `--dry-run` 不执行 | `run_install(dry_run=True)` 不调用 runner（有测试） |
| 幂等 | 已装条目不再重装、不弹确认、退出码 0（不算失败） |
| 错误不吞 | 探测失败不致命；安装逐条返回 `returncode` / `error`（含 sudo 无 tty） |
| 与 `trm setup` 的分工 | 向导**只登记选装**、不安装；安装是显式动作，两者共用同一份 `config/setup-catalog.yaml` |

- 测试：`tests/test_env_toolchain.py`（34 项：探测 / 解析 / 计划 / 执行 / 清单 / CLI）。

## 广接入：生态导入器（E4，2026-09-20 已实现）

> 生态四层的入口（`docs/ECOSYSTEM-STRATEGY.md` §4 缺口 4 / 6 / 7）。一句话：**生态的东西都从这三个
> 导入器进来，但一律落到「同一张表 + 同一套策略 + 同一份审计」**，第三方默认不启用。
> 计划与切分见 `docs/E4-PLAN.md`。

### 模块

| 模块 | 职责 |
|---|---|
| `src/trimum_core/ecosystem.py` | 统一条目 schema（`EcosystemEntry`：`trust` / `risk` / `requires` / `source_url` / `author` / `origin` / `enabled`）+ 分级器 `assess_risk` + 校验器 + 三个导入器共用的 `ImportRefused` |
| `src/trimum_core/cli_adapter.py` | 通用 CLI 适配器：`--help` 探测 → 解析 → 定级 → 落 `tool.json5` + 薄壳 `main.py`；薄壳调 `generic_executor` |
| `src/trimum_core/workflow_catalog.py` | Warp 式目录 YAML → 逐条校验 → 编译 `WorkflowDefV2` → `~/.trimum/workflows/<id>/workflow.yaml` |
| `src/trimum_core/skill_import.py` | 技能导入：本地目录 / git URL → 校验 frontmatter → 复制进 `~/.trimum/skills/` |
| `src/trimum_core/tool_file_loader.py`（改） | manifest 支持 `enabled`（缺省 true，兼容既有工具）；`set_manifest_enabled` 逐行就地改（保留 JSON5 注释）；`list_manifests`；`scan_tools(include_disabled=)` |
| `src/trimum_core/tool_gateway.py`（改） | `load_all()` 只 import `enabled` 的 `main.py`，未启用记 `tool_file_loader.skipped_not_enabled` |
| `src/trimum_core/cli/_ask.py` | 唯一的「问人」入口；非 TTY 直接取默认值（无人值守不挂死） |

### 风险分级（`ecosystem.assess_risk`）

输入是「命令里出现的词」，输出是 `(级别, 理由列表)` —— 每条理由写清是哪个词触发，**dry-run 直接展示，
用户能反驳**：

| 级别 | 触发 | 例 |
|---|---|---|
| `critical` | 破坏性形态（子串匹配整段文本） | `mkfs` / `dd if=` / `wipefs` / `rm -rf /` |
| `high` | 变更系统或不可逆 | `install` / `remove` / `rm` / `kill` / `prune` / `push` / `format` / `sudo` |
| `medium` | 有副作用但不破坏 | `run` / `start` / `create` / `set` / `clone` / `apply`；`--force` / `-y` 这类免确认旗标 |
| `low` | 纯读 | `list` / `show` / `status` / `log` / `read` / `diff` |
| 兜底 `medium` | 没有任何证据 —— **不猜低**（猜低会让第三方命令悄悄变成"低风险"），也不夸大成 high | 命令名不在任何动词表里 |

**声明不能降级**：workflow YAML 里写 `risk: low`、命令里有 `prune` 时，导入按 `high` 处理并给出理由
（`max_risk(声明值, 探测值)`）。

### 三个导入器共有的红线（写进代码与测试）

| 红线 | 落点 |
|---|---|
| 导入不执行 | 适配器只跑 `--help`；workflow / skill 只读文本、只写文本，**绝不 import、绝不执行**导入物 |
| `--dry-run` 不落盘 | 三个导入器同一条规则，测试逐条断言目标目录没有新增 |
| 非交互要 `--yes` | 与 `env` / `mcp` / `install` 一致：非 TTY 直接 abort（退出码 1） |
| 第三方默认不启用 | CLI 导入产物 `enabled: false`，要显式 `trm tool enable`；workflow / skill 是**惰性文本**（不点 `run` / 不被 harness 读到就不发生任何事），故 `enabled: true` |
| 不覆盖已有 | 目标已存在即拒绝，除非显式 `--force`；**先全量检查再写**，不做半截导入 |
| 不引入新依赖 | YAML 用已有 PyYAML；git 源走系统 `git clone --depth 1`，失败即报错，不静默降级 |

### 运行期仍然只有一条路

导入进来的东西**不新增执行通道**：工具仍走 `main.py` 契约 → ToolGateway 六层 + SecurityRule + 审计；
`generic_executor` 自己再兜一层白名单（子命令必须在探测集合里、旗标必须在 `allowed_flags` 里、二进制用
`shutil.which` 现算）—— **手改 manifest 也绕不过这一层**。

### 三个真实缺陷（本轮踩到并修掉）

1. **`subprocess.run(capture_output=True)` 在 Windows 上会永久挂死**：被探测 CLI 可能留下仍持有继承写句柄的
   后台孙进程（分页器 / 凭据助手），而 Windows 上 `subprocess.run` 超时后会 `kill()` 再**无超时地**
   `communicate()` 一次，于是永不 EOF 的管道把探测卡死（实测 `trm tool import-cli git` 挂住）。
   修法：输出走**临时文件**，不用管道；`stdin=DEVNULL` 防分页器等输入。
2. **默认根写死 `Path.home()`**：`tool_file_loader.list_manifests` / `WorkflowDefV2.load_from_dir` /
   `skill_sync.default_source_roots` 三处都从 `Path.home()/".trimum"` 起步，会绕开 `TRIMUM_HOME`
   —— 表现为「导入了却看不见」。三处统一走 `paths.trimum_path(...)`。
3. **`--help` 的输出只用来描述能力**：解析不到子命令就**不写**（而不是编一个）。宁可少登记。

### 已知取舍

- **不做 `--help` 的语义理解**：解析是启发式的；`Commands:` / `命令：` 类标题块里才取子命令。
- **CLI 适配器不自动接进 ToolGateway 分发器**：生成的工具走既有 `main.py` 契约，不新增 `ToolType`。
- **不做 workflow 的远程目录**：`import` 只接受本地路径或 git URL，不做「订阅 / 自动更新」（那是 E5 的事）。
- **skill 导入不做依赖解析**：只搬文件 + 校验 frontmatter，技能之间的引用留给后续。
- ~~**`WorkflowDefV2.to_workflow_definition()` 不搬运 `instruction`**~~：E4 只在验收「导入 + 校验 +
  能被 `trm workflow list` 列出」时把这条留给了后续一轮，**W1（2026-09-20）已修**——
  见下一节「Workflow 执行语义（W1）」。

## Workflow 执行语义（W1，2026-09-20 已实现）

> 计划与语义决策见 `docs/WORKFLOW-EXECUTION-PLAN.md`。E4 遗留的「v2 定义跑不起来」在这一轮闭环：
> 定义齐全、执行缺席的那条线，现在接上了 Event Bus。

### 模块

| 模块 | 职责 |
|---|---|
| `src/trimum_core/workflow_runtime.py`（新） | `WorkflowRuntime`：注册表 + Event Bus 触发器 + 驱动执行 + 运行记录；`agent_type: shell` 处理器走 ToolGateway |
| `src/trimum_core/workflow_engine.py`（改） | `to_workflow_definition()` 搬运 `instruction` / `input_data` / `trigger_event`；删掉 `return` 之后那段死代码与坏掉的模块级 `start_v2`；agent 节点缺 driver 时给可行动的错误 |
| `src/trimum_core/threat_workflows.py`（改） | 16 条威胁响应剧本 → `WorkflowDefV2`（`builtin_workflows()`）：命令式步骤 `agent_type: shell`，散文式步骤 `trm-agent` |
| `src/trimum_core/api_server.py`（改） | daemon 启动时建运行时并 `start()`；`GET /api/workflows`、`GET /api/workflows/runs` |
| `src/trimum_core/cli/commands/workflow.py`（改） | `list --all` / `run [--event --payload --timeout --dry-run]` / `enable`；`run --event` 只对点名的 workflow 负责 |

### 执行路径

```
Event Bus ──(event_type + condition 命中)──> WorkflowRuntime
                                              │ 编译 step → Node/Edge
                                              ▼
                                        WorkflowEngine.run()
                                              │
                        handler="shell" ──────┴──── handler 带 agent_type
                                │                          │
                        ToolGateway.execute()      WorkflowEventDriver
                    （策略/风险/审计/脱敏/cwd jail）      （子 Agent 进程）
```

### 红线（写进代码与测试）

| 红线 | 落点 |
|---|---|
| 不新增执行通道 | 工作流的 shell 与 `trm exec` 走**同一个** ToolGateway：策略 / 风险分级 / SecurityRule / 审计 / 凭据脱敏 / 行为基线照常；流量标记 `SourceType.WORKFLOW` |
| 失败不伪装 | 网关拒绝、非零退出、缺 `instruction` → 节点 `FAILED`、workflow `failed`；「跑失败」绝不记成成功 |
| 命令不拆分 | `instruction` 整条进 `args=[command]`（dispatcher 原样 join 回去）；shlex 拆分再拼会吃掉引号，`ssh host "systemctl restart x"` 会被拆坏 |
| 触发器不猜 | 空 `trigger.event_type` = 只能手动跑；条件表达式用受限 `eval`（空 `__builtins__`），写错按「不通过」 |
| 事件环路有熔断 | 事件驱动下同一 workflow 每 `RUN_WINDOW_SECONDS`(10s) 最多自动跑 `MAX_RUNS_PER_WINDOW`(20) 次，超限发 `event.workflow.throttled` 并跳过；手动 `run` 不受限 |

### 语义取舍

| 取舍 | 说明 |
|---|---|
| step 之间不串行等待 | 「监听器 → 执行组」的字面语义；要串行就把任务写进同一个 `execute` 组（组内是串行 DAG） |
| 同一 step 已在跑 → 跳过 | 防止「事件风暴 / 自我触发」滚成死循环；跳过时发 `event.workflow.skipped`（`reason=already_running`）。收尾事件 `workflow.finished` 在运行仍算「在跑」时发出，所以「监听自己的 finished」的 workflow 不会自我续命 |
| 内置剧本默认 `enabled: false` | 剧本里有 `kill` / `firewall-cmd`，自动触发等于把确认环节删掉；`trm workflow enable <id>` 落盘成用户自己的文件后才常驻触发，手动 `run` 不受限 |
| 失败节点阻断后继 | 沿用引擎 DAG 语义（后继要求前驱 `completed` / `skipped`）——响应剧本前一步失败时不该继续动手 |
| 运行记录只在内存 | 环形 200 条，进程重启即丢；`trm workflow status/log` 仍是桩，持久化留给后续一轮 |
| 事件广播、退出码收窄 | 一次事件会触发**所有**命中的 workflow（运行时按 workflow 各自判定，不做独占）。但 `trm workflow run <id> --event ...` 的退出码只认 `<id>` 自己的运行，其余进 `other_triggered`；点名的那份没被命中而别的被命中 → 退出码 1 并回报实际触发到的 id |
| 散文式步骤会明确失败 | 内置剧本里「比对上次 hash 基线」这类步骤编译成 `trm-agent`，没有 driver / 没装 Agent 脚本时节点 FAILED 并说明原因，**不假装成功** |

## 官方分发渠道（E5，2026-09-21 已实现）

> 信任模型与落地口径见 `docs/ECOSYSTEM-STRATEGY.md` §7（内置根 / `.trmpkg` 校验链 / 安装 ≠ 授权）、
> §7.1（来源 + 身份 + 能力三层职责）、§7.2（多用户前瞻）、§7.4（包格式）、§7.5（本片）。

### 模块

| 模块 | 职责 |
|---|---|
| `src/trimum_core/trmpkg.py` | 包格式（`manifest.json5` + 逐文件 sha256 + `SIGNATURE` + `chain.json`）、打包、校验、安全解包；`verify_chain()` 与 `verify_document_signature()` 是「什么算可信」的唯一实现 |
| `src/trimum_core/pkg_index.py` | 官方目录索引（`trmindex/1`，容器 `{document, signature, chain}`）：回答「去哪拿这个包」，索引本身也必须签名；`entries_from_directory()` 是发布方的扫描+质检面（只收录验得过的包） |
| `src/trimum_core/pkg_install.py` | 校验 → 按类型落地（`agents/` / `tools/` / `workflows/` / `skills/`）→ 登记 `~/.trimum/config/installed.json5`；`remove_package()` 是逆操作（删登记过的目录 + 划掉登记行） |
| `src/trimum_core/capability.py` | 能力清单的运行期交集（E6 遗留）：多来源取最严，只收紧、不放宽 |
| `src/trimum_core/cli/commands/pkg.py` | `trm pkg {verify,info,create,extract,index,root-init,signer-init}` |
| `src/trimum_core/cli/commands/install.py` | `trm install [name]` / `--file` / `--list` / `--index` / `--allow-untrusted` / `--remove` / `--yes` / `--dry-run`（无参数仍是原向导） |
| `config/trust/trimum-root.crt` | 内置官方根（只有公钥；私钥留在发布方 `~/.trimum/trust/`，仓库外） |

### 关键设计

- **信任链**：内置根 → 签名者证书（`issued_by` + `issuer_signature`）→ 签名 manifest 的**规范字节**
  （`sort_keys` + 紧凑分隔符 + UTF-8）→ manifest 的逐文件 sha256 覆盖整个载荷。改一个字节都验不过，
  且校验只依赖包内签名与内置根，不依赖 TLS。
- **索引也是签名文档**：签名覆盖 `document`，`chain` 与包共用 `verify_chain()` —— 索引与包不可能对
  「什么算可信」产生第二种解释；索引条目的 `sha256` 是索引对包的承诺，下载后先比哈希再进校验。
- **安装三动作**：校验 → 落地 → 登记（trust / 签名者与根指纹 / 包哈希 / 来源 / requires / 能力块）。
- **两档 trust**：`official`（链追到内置根）与 `untrusted`（显式 `--allow-untrusted`）。
- **安装 ≠ 授权**：登记只回答「从哪来」；能不能执行仍由 ToolGateway 分层决定，`capability.py` 只收紧。
- **requires**：安装时按 PATH 探测，缺依赖只警告不拒装（与 `AgentRegistry.check_dependencies` 同一口径）。
- **发布方闭环**：`create`（打包签名）→ `index`（扫目录 → 签名索引 → 写完自检）。`trm pkg index` 只收录
  **验得过**的包（一个不过就整体失败并列出原因，不写索引），条目字段取自**校验过的 manifest** 而不是
  文件名，`url` 相对索引位置 —— 索引与包同目录即可离线安装。发布 / 上线 / 轮换流程见 `docs/PACKAGE-CHANNEL-OPS.md`。
- **发布方工具**：`root-init` / `signer-init` 拒绝把私钥写进 git 工作树（除非 `--insecure-key-output`），
  落盘 0600；换根 = 旧包全部作废（见 `config/trust/README.md`）。
- **卸载只删登记过的那个路径**：`trm install --remove <name>` 读 ledger 里的 `path`，只有恰好等于
  `<TRIMUM_HOME>/<TYPE_ROOTS[type]>/<name>` 才动手 —— 手改 `installed.json5` 把路径指到工作区外、
  `certs/`、或兄弟 agent 的目录，一律拒（`TRM-4009`）且一个字节都不删。销账与删目录成对：
  ledger 行划掉后，`--list` 与运行期 `untrusted_names()`（`capability.py` 读的就是它）同时不再认它。
- **卸载是破坏性动作**：交互式问一句，非交互必须 `--yes`（stdin 不是 TTY 时 `ask_confirm` 直接答 no，
  不挂住），`--dry-run` 恒不执行；`--remove` 与 `--file` 互斥。
- **运行期 Layer 2.6**：`ToolGateway` 在 L2.5 之后、L4 之前做能力交集 —— deny → `capability_denied`
  审计并拒绝；confirm → 升级为 `Action.CONFIRM`（interactive 弹窗，非交互交给后续层）。
  风险取管线判定的 risk（PolicyEngine / LLM 策略），不是执行后的观测值。

### 红线（写进代码与测试）

- `--allow-untrusted` 只放宽「来源」：包内绝对路径 / `..` / 符号链接 / 硬链接 / 设备文件一律照挡。
- 私钥永不进仓库：CLI 守卫 + `.gitignore` 的 `*.key` / `*.pem` 双保险。
- 校验不通过就不落地：先校验后解包，不留「先解开再判断」的中间态。
- 能力清单读不懂（缺字段 / `max_risk` 非法）→ confirm，而不是当作无限制。
- 内置（随发行版发布）agent 的目录不可被卸载删掉：名字命中 `discover_bundled_agents()` 的 agent 包即拒
  （`install_package(force=True)` 可能覆盖过内置目录，而登记里没记「装之前 dest 在不在」，还原不回来）。
- 卸载不碰 `certs/` / `audit/` / `memory/` —— 用户数据与安全记录跟包无关；agent 证书就是包目录里的
  `cert.json`，随目录一起走，不单独删。

### 测试

`tests/test_trmpkg.py`（16）、`tests/test_cli_pkg.py`（35）、`tests/test_pkg_install.py`（43）、
`tests/test_capability.py`（20）。

## 范围边界与验收（生态轮）

> 2026-09-21 由已删除的根 `PRD.md` 并入（PRD 的其余章节与 `STATUS.md` / `TODO.md` / `docs/ECOSYSTEM-STRATEGY.md` 重复）。

**范围边界**

- 生态四层只在 trimum 自有模块内新增代码（`src/trimum_core/`），不改既有对外接口语义、不引入 Node 生态依赖。
- 不安装 / 不内嵌 CLI-Anything（需 Node，调研已否决）；第三方 harness 只作**可选导入源**。
- **不自建包仓库**：`trm env install` 只调机器上的系统包管理器（pacman / apt / dnf / zypper / apk / brew / winget / scoop）。
- MCP 按阶段推进：M0/M1/M2（stdio + 注册 + 审计）、M3（策展导入器）、M4/M4.5（传输与生命周期 + 远端工具聚合）已交付。
- 官方分发渠道（E5）只做**分发面**：包格式 + 校验器 + 内置根 + 目录索引 + `trm install`；
  不新增能力来源（四层仍是唯一来源），不自建包仓库，不托管官网服务端。

**验收标准**

- 文档中每一项勾选状态都能对应到代码实现，或明确标注为缺口。
- 调研结论可复现：`docs/CLI-ANYTHING-RESEARCH.md` 每条结论都附证据（registry / README / 本机检查）。
- 生态四层每项交付都能用一条命令复现：`trm commands --json`、`trm env inventory --json`、`trm setup --dry-run --json`、`trm pkg verify <pkg>`、`trm install --list --json`。
- 安装类命令的安全红线可验证：`--dry-run` 不执行、非交互无 `--yes` 必 abort、已装幂等退出 0（`tests/test_env_toolchain.py`）。
- 既有测试基线不回归（本地基线失败项均为宿主环境问题：Windows 沙箱 / PATH 缺 `python.exe` / LLM 断网）。
