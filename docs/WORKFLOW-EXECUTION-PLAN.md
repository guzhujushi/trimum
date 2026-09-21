# W1 — Workflow 执行语义（监听 Event Bus → 驱动执行）

> 立项：2026-09-20，紧接 E4。E4 遗留原文：「`WorkflowDefV2.to_workflow_definition()` 不搬运
> `instruction`，编译出来的 workflow 在 `trm workflow run` 下不会真的执行命令 —— 留给
> 「workflow 执行语义」一轮」。本轮就是那一轮。

## 1. 现状勘察（动工前的事实）

| 事实 | 证据 |
|---|---|
| 引擎只有 `run(definition)` 一个入口，**没有任何触发器** | `workflow_engine.py`：`run` / `_execute_dag` / `_execute_single_node` |
| 引擎曾经想过触发器，但实现是坏的 | 模块级 `async def start_v2(self, engine, ...)`（`self` 无人传入、`eval()` 裸用、订阅 `"*"` 后从不退订、`task.assigned` 全库无消费者） |
| v2→v1 转换丢执行信息 | `to_workflow_definition()` 只搬 `agent_type` → `handler`，`instruction` 掉地上 |
| `load_from_dir()` 尾部有一段死代码 | `workflow_engine.py:1085-1117`（`return` 之后的重复函数体） |
| 唯一预设工作流是「数据」不是「能力」 | `threat_workflows.THREAT_WORKFLOWS`（16 条威胁响应剧本），全库只有定义 + 两个查询函数，零调用点 |
| 工作流目录默认是空的 | `WorkflowDefV2.load_from_dir(None)` → `~/.trimum/workflows/`；仓库内无 workflow YAML 资产 |
| ~~`WorkflowListener` 从未被实例化~~ ✅ **2026-09-21 已接线**（穿插项步骤 C） | 当时 `api_server.py` 只起了 `WorkflowEventDriver`；`workflow.trigger` 事件只发不收（2026-09-21 起连唯一的生产者也没了：威胁剧本改由 `security.monitor_result` 驱动，见 `docs/SECURITY-DEFENSE-PLAN.md` §三「触发归属」） |
| shell 执行路径只有两条 | `trm exec`（人，ToolGateway）与 `shell` dispatcher；引擎侧没有 |

**结论**：workflow 这条线是「定义齐全、执行缺席」——本轮补的就是执行。

## 2. 目标与非目标

### 目标
1. **v2 定义可执行**：`agent_type: shell` + `instruction` 真的落到节点上并真的跑起来。
2. **常驻监听**：运行时订阅 Event Bus，按 `steps[].trigger` 命中即驱动执行。
3. **不绕安全层**：所有 shell 任务走 `ToolGateway`（策略 / 风险 / 审计 / 脱敏 / cwd jail），
   引擎与运行时都不直接 `subprocess`。
4. **预设可见可控**：威胁剧本成为 builtin（可列、可手动跑、默认**不**自动触发）。
5. **可观测**：每次运行落 `WorkflowRunRecord`（内存环形），发 `workflow.triggered` /
   `workflow.finished` 事件。
6. CLI 能一次性验证整条链路：`trm workflow run <id> --event <type> --payload <json>`。

### 非目标（本轮不做，记录在 TODO）
- ~~`WorkflowListener` 接进 daemon~~ ✅ **2026-09-21 完成**（穿插项步骤 C）：`submit()` 当生产者、daemon 启动即装配、CLI 入口 `trm workflow submit`（要 TransformAgent / PlannerAgent 接线，与本轮正交，故当时不做）。
- `task.assigned` / `agent_runtime` 的 Agent 执行链（driver 之外的路径）。
- 运行状态持久化（`workflow status/log` 仍是桩）。
- workflow 的远程目录 / 订阅更新（E5）。
- IPC / HTTP 暴露（`workflows.list` / `workflows.trigger`）。

## 3. 设计

### 3.1 语义决策（关键）
| 决策 | 选择 | 理由 |
|---|---|---|
| step 之间 | **各自常驻监听**，互不串行等待 | 「监听器→执行组」的字面语义；串行等待会让第 2 个 step 的触发器在第 1 个跑完前失效（事件是转瞬的） |
| 需要串行 | 写在同一个 `execute` 组里（组内串行 DAG） | 引擎本来就是串行 DAG |
| `trigger.event_type` 为空 | 只能手动跑（`run_now`） | 「没声明触发条件 = 不参与事件分发」，避免雾里执行 |
| 重复触发 | 同一 workflow+step 已有在跑 → 跳过并记 `skipped` 事件 | 防止「事件风暴 / 自我触发」把循环跑成死循环 |
| 事件环路 | 同一 workflow 每 10s 最多自动跑 20 次，超限发 `workflow.throttled` 并跳过（手动不受限） | 「同一 step 不并发」拦不住 `A.finished → B → A` 这种环；`workflow.finished` 又在仍算「在跑」时发出，所以自我续命也走不出第二步 |
| builtin 威胁剧本 | **取证类武装、处置类不武装**：`auto_trigger` 数据位说了算 | 处置剧本里有 `kill` / `firewall-cmd`，自动执行等于把确认环节删掉；且自动触发的运行里非取证步骤一律 `skipped`（不派子 Agent）—— 细节见 `docs/SECURITY-DEFENSE-PLAN.md` §三「自动触发按剧本性质分档」 |
| 条件表达式 | 受限 `eval`（空 `__builtins__`，命名空间只有 `payload` / `event` / `true` / `false`） | 沿用引擎既有约定；YAML 是本地文本，等价于本地配置 |
| 事件类型匹配 | 精确 → 去命名空间前缀（`event.` / `task.` 等）→ `fnmatch` 通配 | 触发器写 `security.monitor_result`，总线上的实际类型是 `event.security.monitor_result` |

### 3.2 模块
- **`workflow_engine.py`（改）**：修 `to_workflow_definition()`（搬 `instruction` /
  `agent_type` / `input_data` / `input_from`）、删死代码、删坏的 `start_v2`。
- **`workflow_runtime.py`（新）**：`WorkflowRuntime` = 注册表 + 事件分发 + 执行 + 运行记录；
  `shell` 处理器走 ToolGateway。
- **`threat_workflows.py`（改）**：`to_workflow_def_v2()` / `builtin_workflows()`。
- **`api_server.py`（改）**：daemon 启动时建运行时并 `start()`。
- **`cli/commands/workflow.py`（改）**：`list --all` / `run --event --payload` / `enable`
  / `run --dry-run`。

### 3.3 执行路径
```
Event Bus ──(event_type + condition 命中)──> WorkflowRuntime
                                              │  编译 step → Node/Edge
                                              ▼
                                        WorkflowEngine.run()
                                              │
                        handler = "shell" ────┴──── handler 含 agent_type
                                │                          │
                        ToolGateway.execute()      WorkflowEventDriver
                    （策略/风险/审计/脱敏/jail）           （Agent 进程）
```
**红线**：运行时和引擎都不持有「执行 shell」的旁路；`shell` 处理器只构造
`ExecuteRequest(tool=ToolType.SHELL, source_type=SourceType.WORKFLOW)` 交给网关。

## 4. 测试与验收
- 单元：`tests/test_workflow_runtime.py`（匹配 / 条件 / 命名空间 / 通配 / 跳过 / 记录 /
  红线 / 内置剧本编译 / CLI）。
- 引擎：v2→v1 转换后 `instruction`、`agent_type`、`input_data` 都在（扩展
  `tests/test_workflow_files.py`）。
- 红线用例：用一个假网关断言「shell 节点一定经过 `gateway.execute`」，并断言
  网关拒绝时节点状态是 `failed` 而不是「悄悄成功」。
- 端到端（本地）：`trm workflow run <id> --event security.monitor_result --payload ...`。
- 真机：E4 的 `scripts/accept_e4.py` 之外，本轮补 workflow 冒烟（导入 → 列 → 触发）。

## 5. 实施结果（2026-09-20 收口）

| 计划项 | 状态 |
|---|---|
| 修 `to_workflow_definition()`、删死代码与坏 `start_v2` | 完成（`workflow_engine.py`） |
| `workflow_runtime.py`（监听 + 驱动 + 记账 + shell 走网关） | 完成；`WorkflowEngine` 的 `agent_type` 节点仍走 driver |
| 内置威胁剧本编译与登记 | 完成：16 条，`source=builtin`、默认 `enabled: false` |
| daemon 接线 + 只读端点 | 完成：`WorkflowRuntime` 随 startup 启动；`GET /api/workflows`、`GET /api/workflows/runs` |
| CLI | 完成：`list --all` / `run [--event --payload --timeout --dry-run]` / `enable` |
| 测试 | `tests/test_workflow_runtime.py`（55 例）+ `tests/test_api_server_startup.py`（+2 例） |
| 文档 | ARCH / STATUS / TODO / OPERATIONS 同步 |

本地全量：**1156 passed / 5 failed / 7 skipped**（5 项为既有宿主基线，与 W1 前同名同数，无回归）。
真机验收：`scripts/accept_w1.py` → **48 passed / 0 failed**。

## 5.1 验收时改掉的一条语义（D6 → D10/D11）

首轮真机验收 D6 红了：事件路径退出码 1，但 JSON 里点名的那份明明是 `completed`。
根因不是触发链，而是**退出码口径**：`wait_for_runs` 返回的是「这次事件引发的所有运行」，
而 CLI 拿 `all(record.ok for record in records)` 一刀切 —— 同 root 下另一份听同一事件的
workflow 失败了，锅却算到点名的这份头上（验收脚本自己也踩了这个坑：三份 workflow 都听
`security.monitor_result`）。

改法：

- `_handle_run` 按 `workflow_id` 把运行分成「点名的」与「顺带跑掉的」；
- 退出码只看点名的那些；顺带的进 `other_triggered`（JSON）与人读输出（`(the same event also triggered: ...)`）；
- 事件来了但**唯独没命中点名的** → 退出码 1，`'<event>' fired but <id> was not triggered (triggered instead: ...)`；
- 验收脚本随之把三份 workflow 的事件拆开（`security.dry_result` / `security.agent_result`），
  并新增 D9（红线：同一 root 下别的 workflow 不被顺手触发）、D10（广播语义 + `other_triggered`）、
  D11（点名的那份没被触发就明说）。

## 6. 遗留（本轮已知边界）
- ~~`WorkflowListener`（Transform TARL 三段式）仍未接线~~ ✅ **2026-09-21 已接线**（穿插项步骤 C）：
  `WorkflowListener.submit(instruction)` 是 `event.transform.completed` 的唯一生产者，daemon 启动即装配，
  CLI 入口 `trm workflow submit`；`workflow.trigger` 事件因此真正有人发（归属口径不变：意图驱动走 Listener，
  威胁剧本走 `security.monitor_result`，见 P0 步骤 3）。
- 内置威胁剧本里「散文式步骤」（如「比对上次 hash 基线」）编译为 `agent_type: trm-agent`，
  没有 driver / 没装 Agent 脚本时节点会明确失败——这是设计选择，不是 bug。
- 运行记录只存内存，进程重启即丢。
