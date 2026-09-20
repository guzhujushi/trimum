# ARCH — trimum

## 技术选型

- 语言：Python 3.12+
- Web 框架：FastAPI
- 数据模型：Pydantic v2
- 工具插件：`~/.trimum/tools/<name>/{tool.json5,main.py}`

完整架构文档见 `docs/ARCHITECTURE.md` 与 `docs/ARCH.md`。

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


## MCP 接入（规划，2026-09-20）

> 完整方案见 `docs/MCP-INTEGRATION-PLAN.md`。现状核实：`MCPDispatcher`
> （`src/trimum_core/tool_dispatchers.py:716`）为占位实现，固定返回 `MCP bridging not yet available`。

- **模块**：`mcp_client.py`（`stdio` / `streamable-http` 传输）、`mcp_registry.py`
  （`~/.trimum/mcp/<name>.json5` 定义 + 懒启动/空闲回收）、`mcp_bridge.py`
  （远端工具映射进 `ToolRegistry`，命名 `<server>__<tool>`）。
- **鉴权**：MCP 调用统一走 `ToolGateway.execute()` 既有分层（Layer 1 Policy → Layer 2 Agent 权限 →
  Layer 2.5 SecurityRule → Layer 3 JIT），不新开旁路；`trust: cloud` 的 server 默认对写类工具强制 confirm。
- **审计**：每次调用记 `mcp.call` 事件（server / tool / 耗时 / 状态）入 `audit.jsonl`，
  并广播 `task.audit.mcp_call`。
- **约束**：deny-by-default（server 定义默认 `enabled: false`）；子进程输出落日志文件而非 PIPE
  （沿用 `agent_launcher.py` 的既有约定）；Linux 上 `apply_cgroup(pid)`；返回内容经 `ContextCompactor` 限长。
- **策展**：`awesome-mcp-servers` 仅作目录参考，经导入器生成 `config/mcp-catalog.yaml` 候选清单，
  人工审核后才写入 `~/.trimum/mcp/`；优先 `uvx` / `pip install` / 单二进制，`npx` 派系默认不收。

## 浏览器工具（2026-09-20 调研结论）

- `~/.trimum/tools/browser/`（`main.py` + `_cdp.py`）是**自研纯 Python CDP 实现**，19 个 action，
  默认 CDP 后端（连 `--remote-debugging-port=9222` 的 Chrome，保留登录态），DOMShell 仅作可选后端。
- CLI-Anything 的 `browser`（`cli-anything-browser`）依赖 Node.js + npx + DOMShell 扩展，**不引入**；
  `browser-cdp` 在该仓库中并不存在。证据见 `docs/CLI-ANYTHING-RESEARCH.md`。
- 仅借鉴其约定：工具自带 SKILL.md、registry 的 `requires` 依赖前置声明字段、能力矩阵（`cli-hub can <task>`）
  与 Workflow TARL 匹配的同构关系。
## 生态四层（规划，2026-09-20）

> 完整战略见 `docs/ECOSYSTEM-STRATEGY.md`。核心判断：**做生态集成器，不做生态复制品**。

| 层 | 内容 | 对接现有代码 |
|---|---|---|
| **L0 环境清单** | `trm env inventory`（pacman/apt/mise/winget/PATH 探测）、`trm env install` 调系统包管理器 | 新模块，不自建包仓库 |
| **L1 协议（MCP）** | MCP client + `~/.trimum/mcp/*.json5` + 工具聚合 | 见上一节与 `docs/MCP-INTEGRATION-PLAN.md` |
| **L2 知识（Agent Skills）** | `trm skill list/import`；技能符号链接进 `~/.claude/skills`、`~/.codex/skills`、`~/.agents/skills` | 复用 `~/.trimum/skills/` |
| **L3 目录（workflow）** | `workflows/*.yaml`（Warp 式低门槛格式）→ 编译进 Workflow / TARL 引擎 | 复用 `workflow_engine.py` |

- **统一底座**：四层产出的能力注册进同一张生态表，带 `trust` / `risk` / `requires` / `source_url` 元数据，
  一律经 ToolGateway 分层与审计；第三方来源默认 `enabled: false`。
- **自描述能力面**：`trm commands --all/--json/--check`（对照 Omarchy 的 `# omarchy:` 注释契约），
  让 Agent 运行时枚举全部能力。
- **第三方 harness（如 CLI-Anything）** 只作为可选导入源，不写进默认安装，不改技术栈依赖。

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

## 官方分发渠道（规划，2026-09-20）

- 官网发布官方 Agent / Tool / Workflow；包格式 `.trmpkg` = `tar.gz` + `manifest.json5`
  （含逐文件 sha256）+ `SIGNATURE` + `chain.pem`。
- 校验链：解包 → 逐文件哈希 → **内置官方根证书**（`config/trust/trimum-root.crt`）验链 → 验签 → 检查 `requires`；
  任一步失败即拒绝。等价于发行版软件源签名模型，用户无需选择信任自签证书。
- `trm install <name>`（官方目录）与 `trm install --file <pkg>`（本地包）共用同一校验器；目录索引同样签名。
- **安装 ≠ 授权**：官方包以 `trust: official` 注册，运行仍走 ToolGateway 分层与审计；
  `--allow-untrusted` 仅在显式开启时使用，且标记 `trust: untrusted`、运行期强制 confirm。

## 身份、证书能力与多用户（规划，2026-09-20）

- **三层职责分离**：来源（官方根 + 逐文件哈希，E5）/ 身份（每用户密钥对 + `user_id` + `machine_id`）/
  能力（证书内 capability 清单：`tools` 白名单 + `max_risk` + `expires_at` + `scope`）。
- **现状雏形**：`src/trimum_core/agent_cert.py` 已实现 official / self_signed / none 三档信任，
  自签证书带 `machine_id`，换机器降级为 `CONFIRM`；agent 文件夹自带 `cert.json`
  （`~/.trimum/agents/<name>/cert.json`）把「代码 + 证书 + 记忆 + 经验」打成一体，是迁移 / 隔离的最小单位。
- **合并规则**：证书 capability 与 `security_rule.py`、ToolGateway 分层**取交集**，证书只收紧不放宽；
  `trust: official` 只影响来源判定，不跳过任何一层检查。
- **多用户待决**：`~/.trimum/`（用户私有）vs `/etc/trimum/`（系统公共：根证书 + 公共工具）的边界；
  审计日志补 `user_id` 字段；私钥保护（文件权限 / DPAPI / 系统 keyring）；官方证书多用户共用、自签证书每用户各一份。
- **不假设预装**：`skill_sync.py` 当前硬编码 7 个目标根，需改为**按探测到的宿主动态决定**；
  一个宿主都没有时只落 `~/.trimum/agent-skills`（首启引导 `trm setup` 负责选装 + 生成密钥 + 探测，见 ECOSYSTEM-STRATEGY §7.3）。
