# trimum — 待办清单

> 最后更新：2026-09-20（真机 Ubuntu 验证通过）
> 当前阶段：Phase 3 收尾 — **P0/P1 阻断项已清零并通过真机验证**；下一阶段 P0 为 CLI-Anything 接入，剩余 P2（桌面确认通道 / SDK 测试 / SonarQube 重扫）
> 测试：本地 **482 passed**；真机 Ubuntu **483 passed**（11 failed 与同机 `git archive HEAD` 基线逐条一致，均为宿主环境缺失，无回归）
> 当前工作分支：`server`；Phase 3 P0/P1 提交已推送四分支（server `3af9e07` / main `26d52f5` / ubuntu `4768820` / arch-linux `b540f36`）

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
| **P0**（下一阶段） | **OpenCLI 弃用 → CLI-Anything 接入** | opencli 引入 Node.js，不符合轻量化初衷，已在宿主改名 `tool.json5.disabled`；CLI-Anything 为 Python 编写、生态完善、可拓展 | 落地 `browser` / `browser-cdp` / `clibrowser` 工具（`docs/INTEGRATION-PLAN-BROWSER.md`），补集成测试 |
| **P2** | **daemon 部署形态未定** | 普通用户手工起 daemon：IPC 绑定 `/run/trimum/trimum.sock` 失败（退回 HTTP）、`apply_cgroup` 无权限降级 | 用 `trmd.service` 以 root/系统权限运行，或改用户态路径 |
| **P2** | **确认 UI 只有 CLI，无桌面/WebSocket 通道** | `LiveConsole.confirm` 可用，`SecurityAgent.confirm` 无桌面交付 | WebSocket 通知 / 桌面弹窗 |
| **P2** | **Agent SDK 无端到端测试与打包验证** | `src/agent-sdk` 已写代码但 `tests/` 无覆盖 | 补 SDK 测试 + `pyproject` 打包验证 |
| **P2** | **SonarQube 重扫 / 真机 Arch Linux 验证** | docs P3-19/P3-20，仓库内无结果 | 收尾执行一次重扫 + 真机 smoke |

> 说明：P0/P1 已全部闭环（2026-09-19），并于 2026-09-20 在真机 Ubuntu 上验证通过；下一阶段 P0 为 CLI-Anything 接入，剩余 P2 可随 Phase 4 启动并行推进。

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
- [ ] **F1. CLI 单元测试**
  - `tests/test_cli.py`：每个子命令的参数解析、返回值
  - Mock daemon/RPC 层，不依赖真实服务
- [ ] **F2. 集成测试**
  - 真实起 daemon 后 `trm status` / `trm health` 连通性
  - `trm ask` 端到端流程
- [x] **F3. 打包验证**（`pyproject.toml` 入口 `trm = trimum_core.cli:main` 正确）
  - 确认 `pyproject.toml` 中 `trm` 入口正确
  - 编写 README 完整 CLI 使用文档

---

## 🟡 后续方向（CLI 完成后）

### CLI 进阶
- [ ] `trm ask` 墨迹/屏幕截图输入支持
- [ ] `trm memory import` / `export`（记忆迁移）
- [ ] CLI 别名自定义（`.trimumrc` 配置文件）
- [ ] 自动补全脚本（bash/zsh/fish）

### 其他待办（承接之前）
- [x] **#3.8 Browser Tool 后端收尾**：opencli 已真正弃用（`tool.json5.disabled` + 加载器只认 manifest，2026-09-19 验证不再报 module_failed）
- [ ] **真机 `/opt/trimum/tests` 与 `/opt/trimum/scripts` 仍为旧内容**（root 属主）：有空时在真机执行 `sudo bash /tmp/sync_opt_tests.sh`；不影响已部署的 `/opt/trimum/src` 运行
- [ ] **daemon 部署形态**（P2）：普通用户手工起 daemon 时 `/run/trimum/trimum.sock` 绑定失败退回 HTTP、`apply_cgroup` 无权限降级；改为 `trmd.service` 以 root 运行，或改用用户态路径
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
| 本地全量测试 | 482 passed / 8 failed / 4 skipped (2026-09-20) |
| 真机 Ubuntu 全量测试 | 483 passed / 11 failed (2026-09-20)，11 项与同机 `git archive HEAD` 基线逐条一致，无回归 |
| 新增覆盖 | `test_tool_gateway_security_rule.py`（11）、`test_context_compactor.py`（13）、`test_audit_store.py`（15）、`test_source_type_flow.py`（6）、`test_learning_feedback.py`（11）、`test_agent_spawn.py`（12）、`test_api_server_startup.py`（3）、`test_ipc_listener.py`（3）、`test_cli_commands.py::TestSecurityLearningCommand`（3） |

---

## 克隆/分支同步

| 分支 | 状态 | 备注 |
|------|------|------|
| `server` | ✅ 已同步 | 当前工作分支，Phase 3 P0/P1 已 push（`3af9e07`） |
| `main` | ✅ 已同步 | Phase 3 P0/P1 已 push（`26d52f5`） |
| `ubuntu` | ✅ 已同步 | Phase 3 P0/P1 已 push（`4768820`） |
| `arch-linux` | ✅ 已同步 | Phase 3 P0/P1 已 push（`b540f36`） |
