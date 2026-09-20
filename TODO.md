# trimum — 待办清单

> 最后更新：2026-09-20（E1 命令面 / Skills → E6 选装模型 + 首启引导 → E3 环境层 `trm env` → E2 MCP 接入 M0/M1/M2 → M3 策展导入器 → **M4 传输与生命周期**）
> 当前阶段：Phase 3 收尾已完成。**生态战略已推进到 E2 + M4**：不做「生态复制品」，做「生态集成器」——四层 = 环境清单（Omarchy 式）+ MCP + Agent Skills + workflow 目录（`docs/ECOSYSTEM-STRATEGY.md`）；CLI-Anything 降级为可选导入源；E4 / E5 / E7 与 MCP 的「工具聚合」待做
> 测试：本地 **825 passed / 8 failed / 7 skipped**（8 项为 Windows 沙箱写 `~/.trimum` 被拒 + PATH 缺 `python.exe` + LLM 断网，与既有基线逐条一致，无回归）；真机 Ubuntu **827 passed / 11 failed / 2 skipped**（11 项全是宿主状态缺失、与同步前同一批，无回归）
> 当前工作分支：`server`；E1/E6/清理/E3/E2/M3/单实例加固 均已推送四分支（M3：server `e7a30f5` / main `74b563f` / ubuntu `5200b99` / arch-linux `1ef88fa`；单实例加固：server `2f6adbb` / main `2a80fb9` / ubuntu `9ecf111` / arch-linux `fe05347`）；**M4 已开发完、真机验收（`scripts/accept_m4.py` 16 PASS / 0 FAIL）并推送四分支（server `20ce9d2`+`19561e0` / main `f813fc8`+`8778a40` / ubuntu `2480869`+`76a2dee` / arch-linux `117e85b`+`5ff33b9`）。**
> ⏳ **等用户执行（需要 sudo，脚本已 scp 到真机 `/tmp`）**：`sudo bash /tmp/sync_opt_m4.sh --check` 先看差异，确认后 `sudo bash /tmp/sync_opt_m4.sh` 把 M4（6 src + 6 tests）装进 `/opt/trimum`；装完以 guzhujushi 身份跑 `bash /home/guzhujushi/trimum/scripts/restart_trmd.sh`（别用 sudo 起 daemon），再 `trm mcp status` 看 `source: daemon`。
> ▶ **下次继续从这里开始（2026-09-20 M4 收尾）**：M4 代码/文档/真机验收都已完成，接下来是 **① 四分支提交与推送 ② 工具聚合** —— 把远端工具以 `<server>__<tool>` 聚合进 `ToolRegistry`，Agent 不必先 `mcp.tools.list` 再 `mcp.tools.call`；再往后是 E4 / E5 / E7。审核入口（人工、非阻塞）：`trm mcp catalog list --unreviewed`。

---

## 核心理念

**trimum 不是一次性代码冲刺，是长期成长的项目。** 以下清单按"下一步最有价值"排序。

---

## 🧭 Phase 3 收尾差距审计（对照 docs 与现有实现）

> 基准文档：`docs/PHASE3-4-PLAN.md`、`docs/REFERENCE-AUDIT.md`、`docs/PYDANTIC-AI-COMPARISON.md`
> 审计时间：2026-09-19

### ✅ 已闭环（docs 已过期，实测代码已实现）

| 项目 | 现状 |
|---|---|
| Agent SDK | `src/agent-sdk/trimum_agent.py` 已实现，`planner_agent.py` 可选集成 |
| cwd Jail | `tool_gateway._check_cwd_jail()` + `EnableRequest.skip_cwd_check` |
| 凭据脱敏 | `tool_gateway._redact_credentials()` + `logger` 全局脱敏 |
| JIT 一次性授权 | `tool_gateway.issue_jit_token()` + `/api/security/allow_once` + `trm security` |
| AI/人类流量模型 | `SourceType.HUMAN/AI/UNKNOWN` + PolicyEngine source-aware |
| 资源配额 | `CgroupV2Controller` + `AgentManager` 注入 set/apply limits |
| Token 追踪 | `TokenUsageTracker` + `AgentLoop` 实记录 |
| 流式 CLI | `AgentLoop._chat_completion()` SSE 流式输出 |
| Workflow TARL | `WorkflowEngine.register_tarl_workflow/match_workflow_by_tarl` |
| Security Agent TARL | `SecurityRule.can_execute_tarl()` |
| Transform Agent 测试 | `tests/test_transform_agent.py` 覆盖 confidence |
| **SecurityRule → ToolGateway** | `tool_gateway` Layer 2.5 + 默认构造 SecurityRule（P0，2026-09-19 完成） |
| **上下文窗口管理 / Compaction** | `context_compactor.py`：输出限长 + 滑窗 + 早期步骤摘要（P0，2026-09-19 完成） |
| **opencli 弃用** | 加载器只加载有 `tool.json5` 的目录，`tool.json5.disabled` 目录不再 import |

### 🔴 Phase 3 收尾阻断项（按优先级）

| 优先级 | 缺口 | 依据 / 现状 | 建议动作 |
|---|---|---|---|
| ~~**P0**~~ ✅ | ~~**SecurityRule/SecurityAgent 未接入 ToolGateway**~~ | 已完成：Layer 2.5 插入 `can_execute()`，deny → `security_blocked` 审计；默认构造 SecurityRule（`enforce_resource_limits=False`，配额仍归 cgroup 层） | 见 `tests/test_tool_gateway_security_rule.py` |
| ~~**P0**~~ ✅ | ~~**上下文窗口管理/Compaction 缺失**~~ | 已完成：`src/trimum_core/context_compactor.py`（输出限长 2400 字符 + 滑窗 5 步 + 早期步骤摘要 + 总预算 3000 字符） | 见 `tests/test_context_compactor.py` |
| ~~**P1**~~ ✅ | ~~**审计日志未上 EventBus / 不可查询**~~ | 已完成：`audit_store.py`（JSONL）+ `task.audit.*` 广播 + `trm log audit --event-type/--agent/--risk` 结构化查询 |
| ~~**P1**~~ ✅ | ~~**子 Agent 真实 spawn + cgroup PID**~~ | 已完成：`agent_launcher.py`（真实 `create_subprocess_exec`）+ 真实 PID `apply_cgroup` + `scripts/agent-template/` |
| ~~**P1**~~ ✅ | ~~**AI/人类流量标记未统一**~~ | 已完成：`trm exec` → `SourceType.HUMAN`，`SecurityRule.can_execute` 透传 `source_type` |
| ~~**P1**~~ ✅ | ~~**Policy 学习模式未接线**~~ | 已完成：`BehaviorMonitor.record_command` 喂数 + deny 计数 + 周期 analyze + `PolicyEngine` 注入（含置信度归一化修复） |
| ~~**P1**~~ ✅ | ~~**Layer 1 confirm 被工具默认值吞掉**~~ | 已完成：`_merge_decision` 让网关决策优先于工具自报的 `allowed/AUTO` |
| ~~**P0**~~ ❌ | ~~**OpenCLI 弃用 → CLI-Anything 接入**~~ | **2026-09-20 调研否决**（`docs/CLI-ANYTHING-RESEARCH.md`）：`browser-cdp` 在 CLI-Anything 中不存在；其 `browser` 依赖 Node.js + npx + DOMShell 扩展，与「去 Node」初衷冲突；trimum 已有自研 CDP 工具（`~/.trimum/tools/browser/`，19 个 action） | 浏览器能力继续自研；只借鉴其 harness / SKILL.md / registry 约定（生态定位见 `docs/ECOSYSTEM-STRATEGY.md`） |
| **P1**（新立项） | **MCP 接入** | `MCPDispatcher` 为占位实现，固定返回 `MCP bridging not yet available`；无 server 定义、无鉴权接线、无审计 | 按 `docs/MCP-INTEGRATION-PLAN.md` 推进 M0→M4 |
| **P2** | **daemon 部署形态未定** | 普通用户手工起 daemon：IPC 绑定 `/run/trimum/trimum.sock` 失败（退回 HTTP）、`apply_cgroup` 无权限降级 | 用 `trmd.service` 以 root/系统权限运行，或改用户态路径 |
| **P2** | **确认 UI 只有 CLI，无桌面/WebSocket 通道** | `LiveConsole.confirm` 可用，`SecurityAgent.confirm` 无桌面交付 | WebSocket 通知 / 桌面弹窗 |
| **P2** | **Agent SDK 无端到端测试与打包验证** | `src/agent-sdk` 已写代码但 `tests/` 无覆盖 | 补 SDK 测试 + `pyproject` 打包验证 |
| **P2** | **SonarQube 重扫 / 真机 Arch Linux 验证** | docs P3-19/P3-20，仓库内无结果 | 收尾执行一次重扫 + 真机 smoke |

> 说明：P0/P1 已全部闭环（2026-09-19），并于 2026-09-20 在真机 Ubuntu 上验证通过；「CLI-Anything 接入」经调研否决，新方向为 **MCP 接入**（见 `docs/MCP-INTEGRATION-PLAN.md`）。

---

## 🎯 当前主线：trimum CLI（`trm` 命令）

> 目标：根据 README.md 的 CLI 规划，构建完整、统一的 `trm` 命令行接口。
> 参考：README 中已列出 CLI 全部子命令，`main.py` 已有 `cli_dispatch()` 骨架。

### 📋 CLI 完整命令规划

```
trm                                # 查看帮助（默认显示可用子命令）
trm version                        # 显示 trimum 版本
trm health                         # 快速健康检查（不需要 daemon）
trm status                         # 查看当前 Agent 运行状态 / 资源占用
trm doctor                         # 检查环境依赖 / 配置完整性

trm ask "<自然语言指令>"            # 单次提问（LLM 规划并执行）
trm ask -i 或 --interactive        # 交互式多轮对话（流式输出）
trm ask ... --agent shell          # 指定 agent
trm ask ... --agent plan           # 指定 planner agent

trm memory list                    # 列出所有记忆分类（domain + category）
trm memory get <key>               # 取某条记忆
trm memory set <key> <value>       # 写入一条记忆（自动分类）
trm memory search "<关键词>"       # 按内容搜索记忆
trm memory stats                   # 查看记忆数量统计

trm security status                # 查看安全策略状态
trm security allow-once <agent_id> [--tool shell] [--cmd "ls -la"] [--ttl 300]
                                   # 签发一次性临时授权 token
trm security tokens                # 列出当前有效 token

trm daemon start                   # 以守护进程模式运行（默认）
trm daemon stop                    # 停止 daemon
trm daemon restart                 # 重启 daemon
trm daemon status                  # 查看 daemon 状态

trm log tail                       # 实时 tail 运行日志
trm log --audit                    # 只显示结构化审计日志（JSON 行）
trm log --since 1h                 # 按时间过滤日志

trm tool list                      # 列出已注册的所有工具
trm tool info <tool_name>          # 查看工具详情

trm agent list                     # 列出所有 agent
trm agent info <agent_id>          # 查看 agent 详情
trm agent spawn <agent_id>         # 启动新 agent

trm workflow list                  # 列出所有 workflow
trm workflow run <workflow_name>   # 运行 workflow
trm workflow status <run_id>       # 查看 workflow 运行状态

trm config show                    # 显示当前配置
trm config set <key> <value>       # 设置配置项
```

### 🗂️ 实施步骤（建议顺序）

#### Phase A：CLI 框架重构（P0）
- [x] **A1. 引入 argparse 子命令结构** refactor `cli_dispatch()`
  - 从 `sys.argv` 手动判断改为规范的 `argparse` 子解析器
  - 建立 `trm` 顶层命令 → 子命令 → 子子命令的三层结构
  - 实现 `--help` 输出 README 中所列命令的完整帮助信息
- [x] **A2. 创建 `src/trimum_core/cli/` 模块包**
  - 按功能拆分为独立模块：`cli/commands/*.py`
  - 减少 `main.py` 的臃肿，`main.py` 仅保留入口转发
- [x] **A3. 统一输出格式化**
  - 普通输出 / `--json` 模式（机器可读）
  - 颜色高亮（有 TTY 时）
  - 支持 `--quiet` 静默模式

#### Phase B：核心命令完善（P1）
- [x] **B1. `trm status` / `trm health` 增强**
  - 显示 daemon 运行状态 PID、端口、uptime
  - 显示资源占用（内存/CPU，可复用 ResourceController 数据）
  - 检查各核心模块加载状态（每项 ✓/✗）
- [x] **B2. `trm doctor` 环境检查**
  - Python 版本要求检查（>= 3.12）
  - 依赖包完整性检查（requests, httpx, rich 等）
  - `~/.trimum/` 目录结构检查（agents/ tools/ memory/ logs/ config.yaml）
  - API Key 配置检查（DEEPSEEK_API_KEY 等，只报告存在与否，不泄露）
  - 网络连接测试（到 API 端点的连通性）
- [x] **B3. `trm memory` 命令组**
  - 对接现有 `MemoryClassifier` + SQLite 存储
  - `list`：按 domain/category 分类展示
  - `get <key>`：取单条
  - `set <key> <value>`：写入并自动分类
  - `search <query>`：调用 `memory_search` 语义检索
  - `stats`：显示各分类记忆数量统计
- [ ] **B4. `trm security` 命令组扩展**（部分完成：`status`/`tokens` 已实现，`revoke` 待做）
  - 现有 `allow-once` 保留
  - [x] 新增 `status`（策略状态）
  - [x] 新增 `tokens`（列出有效 token）
  - [ ] 新增 `revoke <token_id>`（撤销 token）

#### Phase C：Agent 交互命令（P2）
- [x] **C1. `trm ask` 体验优化**
  - 单次提问模式：`trm ask "..."` → SSE 流式输出 → 显示 token 统计
  - `--interactive` 模式：Rich prompt 多轮循环（未引入 prompt_toolkit）
  - [ ] Ctrl+C 中断处理
  - 会话记忆挂载（`ContextManager.register_session/update_session`）
- [x] **C2. `trm agent` 命令组**
  - `list`：列出所有注册 agent
  - `info <id>`：显示 agent 详情
  - `spawn <id>`：启动新 agent 实例
  - `kill <id>`：停止 agent 实例

#### Phase D：Workflow & 工具命令（P3）
- [x] **D1. `trm workflow` 命令组**（2026-09-19 核对：`cli/commands/workflow.py` 已实现 list/run/status/log）
  - `list`：列出所有 workflow 定义
  - `run <name>`：执行 workflow
  - `status <run_id>`：查看运行状态/结果
  - `log <run_id>`：查看运行日志
- [x] **D2. `trm tool` 命令组**（已实现：`cli/commands/tool.py` list/info）
  - `list`：列出所有已注册工具（Tool Registry）
  - `info <name>`：查看工具详情（参数、权限等级）

#### Phase E：配置与日志（P4）
- [x] **E1. `trm config` 命令组**（已实现：`show`/`set`/`path`；`get` 用 `show` + `--json` 代替）
  - `show`：显示当前生效配置
  - `set <key> <value>`：设置配置项
  - `get <key>`：查询单项配置
- [x] **E2. `trm log` 命令组**（已实现：`tail`/`audit`/`--since`；审计仍是日志文本过滤，结构化查询见 P1）
  - `tail`：实时 tail 日志（支持 `-f`）
  - `--audit`：审计日志过滤
  - `--since <duration>`：时间过滤
- [x] **E3. `trm` 默认行为**（已实现：`cli/__init__.py` 无参数时 print_help + daemon 状态）
  - 无参数时打印帮助 + 当前 daemon 状态
  - 美化 banner/help 输出

#### Phase F：测试与发布（P4）
- [x] **F1. CLI 单元测试**（2026-09-20 核实已完成：`tests/test_cli.py` 32 项 + `tests/test_cli_commands.py`）
  - `tests/test_cli.py`：每个子命令的参数解析、返回值
  - Mock daemon/RPC 层，不依赖真实服务
- [ ] **F2. 集成测试**（待补 CLI↔daemon 端到端）
  - `tests/test_integration.py` 目前只覆盖 gateway / workflow / event_bus，无 CLI 侧用例
  - 真实起 daemon 后 `trm status` / `trm health` 连通性
  - `trm ask` 端到端流程
- [x] **F3. 打包验证**（`pyproject.toml` 入口 `trm = trimum_core.cli:main` 正确）
  - 确认 `pyproject.toml` 中 `trm` 入口正确
  - 编写 README 完整 CLI 使用文档

---

## 🌐 生态战略（E0-E7，2026-09-20 立项）

> 方案见 `docs/ECOSYSTEM-STRATEGY.md`。结论：**不做「生态复制品」，做「生态集成器」**；
> CLI-Anything 降级为可选导入源，主通道是 Agent Skills（长尾）+ MCP（服务）。
> 灵感源：Omarchy（拥有环境 + 自描述命令面 + skills 分发）、Warp（低门槛目录 + 社区 PR）、ECC（一套技能分发进 30+ 宿主）。

- [x] **E0. 冻结战略**（2026-09-20 完成）：四层定位见 `docs/ECOSYSTEM-STRATEGY.md` §3；首批 3 个「非它不可」用例见 `docs/MCP-INTEGRATION-PLAN.md` §2.3
- [x] **E1. 自描述能力面**（2026-09-20 完成）：命令元数据契约（`cli/registry.py`）+ `trm commands [--all|--json|--check]`；`trm skill list/sync/paths` + `skill_sync.py`（symlink → Windows junction → copy 回退）
  - 测试：`tests/test_cli_commands_meta.py`（15）+ `tests/test_skill_sync.py`（22）；`trm commands --check` 检出并修掉 `ask` 的 `run` 别名无摘要问题
- [x] **E2. MCP 接入**（2026-09-20 完成 M0/M1/M2）：`mcp_client.py` + `mcp_registry.py` + `MCPDispatcher` 实装 + `trm mcp`；见下方「MCP 接入」章节（M3/M4 待做）
- [x] **E3. 环境层**（2026-09-20 完成）：`src/trimum_core/env_toolchain.py` + `trm env inventory|install`
  - [x] 9 个包管理器探测（pacman / apt / dnf / zypper / apk / brew / winget / scoop / mise）+ 已装包解析 + 目录覆盖清单
  - [x] 计划与执行分离：`plan_install` → `commands_for`（winget 一包一条）→ `run_install`；`--dry-run` 只打印
  - [x] 红线：不自建包仓库 / 清单只读（risk: low）/ 安装必须显式确认（`--yes` 或交互）/ 已装幂等（退出码 0）
  - [x] 测试：`tests/test_env_toolchain.py`（34）；`trm commands --check` → 53 条通过
  - 遗留：`trm skill import`（生态导入）未做，顺延到 E4；`trm env install` 未在 Linux 真机实跑（等 Ubuntu 开机）
- [ ] **E4. 广接入**：通用 CLI 适配器（`--help` → 工具条目 + 风险分级）、workflow 目录格式 + `trm workflow import`

> 排序理由：Skills 层近乎零成本 → MCP 成本中等 → CLI 适配器 → workflow 目录。

- [ ] **E5. 官方分发渠道**（2026-09-20 需求确认）：官网提供官方 Agent / Tool / Workflow，下载即用；
  官方根证书内置（`config/trust/trimum-root.crt`），用户无需信任自签证书；
  `.trmpkg` 包（manifest + 逐文件 sha256 + 签名 + 证书链）→ 内置根验证 → `trm install <name>` / `--file <pkg>`
  设计见 `docs/ECOSYSTEM-STRATEGY.md` 第 7 节；安装 ≠ 授权，运行时仍走 ToolGateway 分层
  - 子项：身份与能力模型 —— 证书携带**能力清单**（可动用工具 / 风险上限 / 有效期），运行期与内置策略取交集（只收紧）
  - 子项：自签证书**仅本机本用户**可用（绑 `machine_id` + 用户 keystore）；他人使用需重新自签（`agent_cert.py` 已有雏形）
  - 子项：多用户前瞻 —— `~/.trimum/`（用户私有）vs `/etc/trimum/`（系统公共）边界、审计日志 `user_id` 归属、私钥保护方案
- [x] **E6. 选装模型 + 首次安装引导**（2026-09-20 完成）：全套开发者工具链大部分为**选装**，引导逐项询问，默认全不装
  - [x] `src/trimum_core/hosts.py`：14 个已知宿主 + 三路探测（`TRIMUM_HOSTS*` 环境变量 / 配置目录 / PATH 上的 CLI）
  - [x] `src/trimum_core/paths.py`：`TRIMUM_HOME` 统一数据根（给多用户 / `/etc/trimum` 预留单一改点）
  - [x] `src/trimum_core/identity.py`：Ed25519 用户密钥对 + 自签身份证书（绑 `machine_id` + user；`max_risk` 只能收紧）
  - [x] `src/trimum_core/setup_wizard.py` + `config/setup-catalog.yaml`（7 组 25 项）+ `trm setup [--dry-run|--yes|--tools|--all-hosts|--skip|--max-risk]`
  - [x] `skill_sync.default_target_roots()` 改为**按探测结果决定**，`--all-hosts` 保留全量模式；`trm install --setup` 复用同一向导
  - [x] 测试：`tests/test_hosts.py`（13）+ `tests/test_setup_wizard.py`（29）+ `TestDynamicTargets`（5）
  - 硬约束（已满足）：**零预装可跑** —— 不依赖 `claude` / `codex` / `opencode` 等第三方 coding agent，也不假设它们会被实际使用
  - [x] 官方 Agent 证书：`cert_type=official` + `capabilities` 能力块；`discover_bundled_agents()` / `ensure_official_certs()`；
    向导新增 `official` 步骤（trimum 自研 Agent 全部免确认；用户自签 `scope=local` 不被覆盖）
  - 遗留：证书 `capabilities` 与 ToolGateway / `security_rule.py` 的**运行时合并尚未接线**（当前证书只是身份锚点 + 登记，不参与执行判定）
- [ ] **E7. 自研 coding Agent（候选）**：参考 `affaan-m/ECC`（262,999★，agent harness operating system，903 个 `SKILL.md` / 30+ 宿主目录）
  设计 trimum 自己的 coding Agent；调研原始件 `tmp/research/ecosystem/ecc-*`（已 gitignore）

> 统一底座：四层产出的能力都注册进同一张表，一律经 ToolGateway 分层 + 审计。

## 🔌 MCP 接入（P1，2026-09-20 立项）

> 方案见 `docs/MCP-INTEGRATION-PLAN.md`。现状：`MCPDispatcher` 是占位实现（`src/trimum_core/tool_dispatchers.py:716`），
> trimum 目前**无任何真实 MCP 能力**。

- [x] **M0. 冻结设计**（2026-09-20）：自研最小 stdio client（不引 SDK/Node）；3 个用例 = 本机能力接入 / 远程 SaaS 受管通道 / 一行文件零代码扩能力；决议见 `docs/MCP-INTEGRATION-PLAN.md` §2.3
- [x] **M1. stdio 客户端**（2026-09-20）：`src/trimum_core/mcp_client.py`（JSON-RPC 2.0 换行分帧、stderr 落文件、超时/EOF 标记坏连接）+ `tests/test_mcp_client.py`（16 项，真协议 fixture server）
- [x] **M2. 注册与鉴权**（2026-09-20）：`mcp_registry.py`（`~/.trimum/mcp/<name>.json5`，deny-by-default + glob 白黑名单 + 连接池）+ `MCPDispatcher` 实装 + `ToolGateway` 回填审计 + `mcp_call` 事件 + `trm mcp list/tools/call/paths`；`tests/test_mcp_registry.py`（27）/ `tests/test_mcp_dispatcher.py`（30）
  - 顺带修掉：`trm --json` 的 stdout 被 INFO 日志污染（CLI 诊断改走 stderr）；连接池 `refresh` 泄漏旧客户端
- [x] **M3. 策展导入器**（2026-09-20 完成）：`mcp_catalog.py` + `trm mcp catalog import/list` → `config/mcp-catalog.yaml`（4,118 条 → **232 条候选**，`reviewed: false`，人工审核后才启用）；离线、确定性输出、拒绝覆盖已存在清单（`--force` 保留人工 `reviewed`/`name`/`note`）；`tests/test_mcp_catalog.py`（52）
- [ ] **M4. HTTP/SSE + 生命周期**：空闲回收、cgroup 绑定、`trm mcp list/status/restart`、运维文档

策展红线：优先 `uvx` / `pip install` / 单二进制（Go/Rust），`npx` 派系默认不收。
（2026-09-20 快照：awesome 列表 4,117 条中 `npx` 626、`pip install` 127、`uvx` 108。）

## 🟡 后续方向（CLI 完成后）

### CLI 进阶
- [ ] `trm ask` 墨迹/屏幕截图输入支持
- [ ] `trm memory import` / `export`（记忆迁移）
- [ ] CLI 别名自定义（`.trimumrc` 配置文件）
- [ ] 自动补全脚本（bash/zsh/fish）

### 其他待办（承接之前）
- [ ] **浏览器工具备选（2026-09-20 调研）**：`epiral/bb-browser`（6,222★，CLI + MCP，用本机登录态控制 Chrome）已获用户认可，可作为自研 CDP 工具的补充/对照，待评估接入
- [x] **#3.8 Browser Tool 后端收尾**：opencli 已真正弃用（`tool.json5.disabled` + 加载器只认 manifest，2026-09-19 验证不再报 module_failed）
- [ ] **真机 `/opt/trimum` 仍是旧树**（2026-09-20 实测）：`src/trimum_core` 缺 9 个模块（`mcp_client` / `mcp_registry` / `mcp_catalog` / `env_toolchain` / `hosts` / `identity` / `paths` / `skill_sync` / `setup_wizard`）、`cli/commands` 缺 5 个（`commands` / `mcp` / `env` / `setup` / `skill`）、`config/` 缺 5 个 yaml（含 `mcp-catalog.yaml`）、`tests/` 少 9 个文件；`config` / `tests` / `scripts` / `src/trimum_core` 为 root 属主，`tar` 直解会被拒 → 已投送 `sudo bash /tmp/sync_opt_tree.sh`（等用户执行），同步后重启 daemon；不影响 daemon 当前运行
- [ ] **daemon 部署形态**（P2）：`apply_cgroup` 仍需 root，普通用户跑时降级；**2026-09-20 已二选一：走「纯手工 daemon」** —— `trmd.service` 已 `disable --now`，daemon 由 `scripts/restart_trmd.sh` 以 guzhujushi 身份管理；要改回 systemd 托管用 `sudo bash scripts/fix_trmd_loop.sh --use-systemd`
- [ ] **daemon 单实例与 socket 加固（2026-09-20 真机发现，P1；运维侧已闭环）**：
  - [x] 运维处置：`trmd.service`（enabled + `Restart=always`）与手工 daemon 抢 `127.0.0.1:8321`，单元每 5s `exit 3`（`NRestarts` 到 117）→ `scripts/fix_trmd_loop.sh`；执行方案A后 `trmd` 为 disabled/inactive、`Errno 98` 归零、`trm status` 回到 `source: rpc`
  - [x] 端口冲突应 fail-fast：端口/socket 被占时在触碰 socket 之前退出，并提示「已有 daemon 在跑」（现在只会抛 uvicorn 的 `[Errno 98]`）
  - [x] `ipc_handler._start_unix_socket()` 先 `unlink` 再 `bind`：短命进程会**抢走运行中 daemon 的 unix socket**，死后留下无人监听的 socket 文件 —— 这是 RPC 静默降级成 HTTP 的根因；应先探测是否有人监听再决定 unlink
  - [x] `config.py:24` 把 socket 路径写死 `/run/user/1000/trimum.sock`（假设 uid=1000），而客户端 `trimum_client.discover_socket()` 走 `XDG_RUNTIME_DIR` → 换 uid 就客户端/服务端对不上
  - [x] `api_server.py` 的 `/health` 版本号自相矛盾：IPC 路径 `"0.2.1"`（L122）vs HTTP 路径 `"0.2.0"`（L203），应统一取 `trimum_core.__version__`（0.5.0）
  - **代码侧闭环（2026-09-20，server `2f6adbb` / main `2a80fb9` / ubuntu `9ecf111` / arch-linux `fe05347`）**：启动预检 fail-fast（`main.check_tcp_port()` connect+bind 双探测 → 端口被占 `exit 3`；`ipc_handler.socket_is_live()` 探到别人在听也 `exit 3`）；`_start_unix_socket()` 改为「先探测再决定 unlink」，有人在听则退让（`socket_held_by_other`）、只有 stale 文件才清理，`stop()` 不再 unlink 别人的 socket；`config.default_socket_path()` 跟随 `XDG_RUNTIME_DIR` → `/run/user/<uid>` → 数据目录（客户端 `socket_candidates()` 同序）；`/health` 统一取 `trimum_core.__version__`；顺带修 `Config.__init__` 浅拷贝污染全局 `DEFAULT_CONFIG`。回归测试：`tests/test_daemon_singleton.py`、`tests/test_socket_path_consistency.py`、`test_ipc_listener.py::TestSocketTakeoverGuard`、`test_api_server_startup.py::TestHealthVersion`
  - [x] **/opt 部署 + 真机验收（2026-09-20 16:49 完成）**：`sudo bash /tmp/sync_opt_singleton_fix.sh` 已执行（补丁进 `/opt/trimum`），daemon 以 guzhujushi 身份重启（PID 12271）；`trm status` → `source: rpc` + `version: 0.5.0`（原 `0.2.1`）；验收脚本 `/tmp/accept_singleton_fix.sh` **9 PASS / 0 FAIL**（版本统一、两种启动冲突都 exit 3、socket 未被抢占、冒烟全通、`trmd.service` 仍 disabled/inactive 且 `NRestarts=0`）
  - 运维侧已备 `scripts/fix_trmd_loop.sh`（`--check` / 默认停用单元 / `--use-systemd` 改 systemd 托管）
- [ ] **Safety**: Landlock / Seccomp 沙箱（Phase 4）
- [ ] **3.5 确定性字段 confidence 分级**：三级分流（直接执行 / 确认窗口 / 转 Planner）
- [ ] **API Key Manager**：统一管理所有需要 API Key 的点

---

## ✅ 已完成（2026-09-19 确认）

| 任务 | 状态 |
|---|---|
| **#3.8 Browser Tool (CLI-Anything) 集成** | ✅ General → Browser 路由问题已修复，355 tests pass |
| **CLI-Anything 排查（Chrome/CDP/Python）** | ✅ 所有 4 个问题已解决 |
| **Phase 3 收尾 P0/P1 清零 + 真机 Ubuntu 验证** | ✅ 已提交并推送四分支（server `3af9e07` / main `26d52f5` / ubuntu `4768820` / arch-linux `b540f36`） |
| **2026-09-20 文档一致性修订 + CLI-Anything / MCP 调研** | ✅ 新增 `docs/CLI-ANYTHING-RESEARCH.md` / `docs/MCP-INTEGRATION-PLAN.md`；修正 STATUS / TODO / browser 方案口径 |
| **2026-09-20 生态四层 E1 / E6 / E3** | ✅ E1 命令面 + Skills 分发；E6 选装模型 + 首启引导（宿主探测 / 身份证书 / 官方 Agent 证书）；E3 环境层 `trm env`（详见 `STATUS.md`、`ARCH.md`） |
| **2026-09-20 收尾校验 + 下次继续指针** | ✅ 全量测试 687/8/4（与基线逐条一致，无回归）+ `trm commands --check` 58 条 + `trm mcp call` 端到端冒烟 stdout 纯 JSON；TODO 记 M3 输入/输出/红线，STATUS / ARCH 修正过期口径；四分支同步 |
| **2026-09-20 E2 MCP 接入（M0/M1/M2）** | ✅ stdio 客户端 + 文件化注册（deny-by-default）+ `MCPDispatcher` 实装 + `mcp_call` 审计 + `trm mcp`；73 项新测试 |
| **2026-09-20 M3 MCP 策展导入器** | ✅ `mcp_catalog.py` + `trm mcp catalog import/list` + `config/mcp-catalog.yaml`（4,118 → 232 条候选，红线逐条计数可查）；52 项新测试 |
| **2026-09-20 M3 真机验证 + 两处真实缺陷修复** | ✅ 真机 739/11/2（11 项宿主基线，无回归）；修 `trm setup --json` 的 stdout 污染（提示改走 stderr）+ 审计测试哨兵撞用户名；真机补装 `cryptography`；新增 `scripts/sync_opt_tree.sh`（`/opt/trimum` 全树 sudo 同步） |

---

## 🧭 收尾流程（长期）

- 分支同步：先 `git diff --name-status <target>..<source>`，再 cherry-pick，禁止无脑 merge。
- GitHub push：走 `http://127.0.0.1:7993`，使用 `.env` 的 `GITHUB_TOKEN`。
- 真机同步：`guzhujushi@100.115.86.48`；源码同步 `/home/guzhujushi/trimum` 和 `/opt/trimum`。
- sudo 操作：写成脚本 scp 到真机 `/tmp/`，例如 `scripts/sync_opt_tests.sh`，并告知用户执行位置。
- 临时文件：根目录 `tmp_*` 一律移入 `tmp/`；`.env` 永不提交。
- 详细流程：见 `docs/OPERATIONS.md`；项目级 Codex 指令见 `AGENTS.md`。

## 🧪 测试状态

| 项目 | 状态 |
|------|------|
| 本地全量测试 | 740 passed / 8 failed / 4 skipped (2026-09-20，M3 + 真机修复轮；+53)。8 项与基线**同源**：沙箱写 `~/.trimum` 被拒（PermissionError）+ PATH 缺 `python.exe` + LLM 断网，**无回归** |
| 真机 Ubuntu 全量测试 | **739 passed / 11 failed / 2 skipped** (2026-09-20，M3 同步后，27s)。11 项 = 同步前基线的同一批宿主状态缺失（`~/.trimum/skills`、`~/.trimum/tools/mcp`、LLM 断网、宿主 env 顺序），**无回归**；同步后新暴露的 8 项失败（`test_setup_wizard` 7 + `test_mcp_dispatcher` 1）已全部修掉 |
| 新增覆盖（2026-09-20 生态轮） | `test_cli_commands_meta.py`（15）、`test_skill_sync.py`（27）、`test_hosts.py`（13）、`test_setup_wizard.py`（33）、`test_agent_cert.py` 增补（11）、`test_env_toolchain.py`（34）、`test_mcp_client.py`（16）、`test_mcp_registry.py`（27）、`test_mcp_dispatcher.py`（30） |
| 新增覆盖（2026-09-20 M3） | `test_mcp_catalog.py`（52）：解析/分类/红线/命名/渲染 IO/CLI + 真实快照比对 |
| 新增覆盖（2026-09-20 真机修复轮） | `test_setup_wizard.py::TestSetupCommand::test_skipped_identity_note_keeps_stdout_json_clean`（1，`--json` 契约回归）；`test_mcp_dispatcher.py` 审计哨兵改成不撞路径的串 |
| 新增覆盖（Phase 3 收尾） | `test_tool_gateway_security_rule.py`（11）、`test_context_compactor.py`（13）、`test_audit_store.py`（15）、`test_source_type_flow.py`（6）、`test_learning_feedback.py`（11）、`test_agent_spawn.py`（12）、`test_api_server_startup.py`（3）、`test_ipc_listener.py`（3）、`test_cli_commands.py::TestSecurityLearningCommand`（3） |

---

## 克隆/分支同步

| 分支 | 状态 | 备注 |
|------|------|------|
| `server` | ✅ 已同步 | 当前工作分支；E1 `779c0e0` / E6 `ab26edf` / 清理+证书 `1456aba` / E3 `4331437` / E2 `634e62a` / **M3 `e7a30f5`** / **真机修复轮 `209c98e`** |
| `main` | ✅ 已同步 | E1 `49b2ef4` / E6 `e0e8f0b` / 清理+证书 `2b88561` / E3 `2b4e9b2` / E2 `8af7d5d` / **M3 `74b563f`** / **真机修复轮 `e0ad16f`** |
| `ubuntu` | ✅ 已同步 | E1 `ba3ebe7` / E6 `e335db6` / 清理+证书 `c0885a8` / E3 `a5c6ad5` / E2 `166841d` / **M3 `5200b99`** / **真机修复轮 `3040b00`** |
| `arch-linux` | ✅ 已同步 | E1 `1f58b7c` / E6 `417b9cc` / 清理+证书 `18f88c8` / E3 `98c8ccd` / E2 `c68ce85` / **M3 `1ef88fa`** / **真机修复轮 `9925c19`** |

> 收尾文档提交（2026-09-20，`docs:` 校验结果 + M3 继续指针）：server `7346ee6` / main `a7cd2db` / ubuntu `fbd6b0f` / arch-linux `0b6e1ac`
