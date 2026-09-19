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

