# trimum — 待办清单

> 最后更新：2026-09-21（E1 命令面 / Skills → E6 选装模型 + 首启引导 → E3 环境层 `trm env` → E2 MCP 接入 M0/M1/M2 → M3 策展导入器 → M4 传输与生命周期 → M4.5 远端工具聚合 → M4.5 收口小项 → E4 广接入 → W1 workflow 执行语义 → **EventBus 通信盘点** → **P0 步骤 1/3 载荷契约扁平化** → **步骤 2/3 L4 改走 `SecMonitor.inspect()`** → **步骤 2 补丁：L4 装配统一 + 处置映射 + 签名收敛** → **步骤 3/3 定 `workflow.trigger` 归属（P0 闭环）** → **E5 第一片：`.trmpkg` 包格式** → **E5 第二片：`trm pkg` CLI + 真实内置根 + 签名索引 + `trm install` + 能力交集** → **E5 第三片步骤 1：`trm install --remove`（卸载与注销）** → **E5 第三片步骤 2：`trm pkg index` 发布方闭环 + `docs/PACKAGE-CHANNEL-OPS.md`** → **E5 第三片步骤 3：多用户边界（调研 + 设计，`docs/MULTI-USER-BOUNDARY.md`，不改代码）**）
> 当前阶段：Phase 3 收尾已完成。**生态战略已推进到 E2 + M4 + M4.5 + E4**：不做「生态复制品」，做「生态集成器」——四层 = 环境清单（Omarchy 式）+ MCP + Agent Skills + workflow 目录（`docs/ECOSYSTEM-STRATEGY.md`）；CLI-Anything 降级为可选导入源；**E4 三个导入器（CLI / workflow / skill）已落地**；**E5 分发面已闭环**（第二片：`trm pkg` + 内置根 + 签名索引 + `trm install` + 能力交集），**E5 第三片步骤 1/2 已落地**（`trm install --remove` 卸载；`trm pkg index` 发布方闭环 + 运维手册），**E5 第三片步骤 3 已定稿**（多用户边界调研 + 设计 → `docs/MULTI-USER-BOUNDARY.md`，复核结论「无硬伤、不改代码」）—— **E5 第三片三步骤全部收口**；剩 官网服务端托管（域名 / 托管 / CI = 产品决策，暂缓）；E7 待做
> 测试：本地 **1326 passed / 5 failed / 8 skipped**（2026-09-21 E5 第三片步骤 3 之后；本轮只加文档、数字未变；5 项失败 = 既有基线：Windows 沙箱写 `~/.trimum` 被拒 + PATH 缺 `python.exe` + LLM 断网）。历史：E4 前 940 → E4 后 1099 → W1 后 1156 → P0 步骤 1 后 1167 → 步骤 2 后 1176 → 步骤 2 补丁 1210 → 步骤 3 后 1212 → E5 第一片 1228 → E5 第二片 1301 → E5 第三片步骤 1 1315 → **步骤 2 1326**；基线由 8 项降到 5 项是 `tests/conftest.py`（`TRIMUM_HOME` 指向临时目录）带来的 —— 那 3 项（`test_depends_on` 1 + `test_integration` 2）长期失败的原因就是「往真实 `~/.trimum` 写被沙箱拒绝」；真机 Ubuntu 开发树 **1098 passed / 11 failed / 2 skipped**（同机对照基线，失败名单逐条相同，无回归）
> 当前工作分支：`server`；E1/E6/清理/E3/E2/M3/单实例加固/M4 均已推送四分支（M4：server `20ce9d2`+`19561e0` / main `f813fc8`+`8778a40` / ubuntu `2480869`+`76a2dee` / arch-linux `117e85b`+`5ff33b9`）；**M4.5 收口小项提交号见 `STATUS.md` 的「提交与分支」表**（幽灵条目 `9e63a81` / env+网关确认 `d34054a` / install 向导 `bd00990`，四分支已同步）。
> ✅ **真机部署已完成（2026-09-20 20:52）**：`sudo bash /tmp/sync_opt_tree.sh` 全树同步落地，`/opt/trimum` 三个关键文件与本地 HEAD 逐文件对上（`mcp_bridge.py` `f503f505…` / `mcp_registry.py` `86447a65…` / `tool_gateway.py` `47d8a205…`），部署树 `[4b/5]` 自检通过；daemon 20:52:27 启动 → 跑的就是新代码（`trm status` 的 `source: rpc`，PID 23850）。真机聚合实测 4 条 `source=mcp`（`echo__echo` / `echo__fail` / `echo__slow` / …），总数 17；幽灵缓存已清（备份 `/tmp/mcp-tools.json.bak-20260920`），清后 `tool list --mcp` 为 0 条、总数 13。
> ▶ **下次继续从这里开始（2026-09-21，E5 第三片步骤 3 之后）**：**步骤 1 ✅**（`d7aced2` `trm install --remove`）、**步骤 2 ✅**（`fcecbfe` `trm pkg index` 发布方闭环 + `docs/PACKAGE-CHANNEL-OPS.md`）、**步骤 3 ✅**（多用户边界：调研 + 设计 → `docs/MULTI-USER-BOUNDARY.md` + 生态战略 §7.8；复核结论「现有设计无硬伤、**不改代码**」，只记了一条「Windows 上 `chmod` 不产生 ACL」的事实）。**E5 第三片三步骤收口**；E5 只剩「官网服务端托管」（域名 / 托管 / CI = 产品决策，本轮不做）。**下一批候选 = E7 自研 coding Agent**（设计层，参考 ECC）；第一片 `9b40be2` / 第二片 `2aec23b`→`4e29b4e` / 第三片 1/3 `d7aced2`、2/3 `fcecbfe` 已落地；
> **逐条实施计划（红线 + 测试清单）见下方「🚚 E5 第三片实施计划」**。穿插候选：**剧本自动触发策略**（内置剧本默认 `enabled=False`，要不要给只读自查子集开自动触发）、总线硬化（P0 配套）、W1 遗留 `WorkflowListener` 接线。
> 📌 更早的指针（2026-09-20 EventBus 审计之后）：W1 已闭环（真机 `accept_w1.py` 48/0）；只读审计发现**安全响应链未接线**——拦得住，但不会响应、不会记录、不会通知（见下方「EventBus 通信缺口」）→ 下一步 = **P0 安全链接线**（三条动作，顺序不能乱）→ 然后 **E5 官方分发渠道**（`.trmpkg` + 内置根证书 + 能力清单）→ **E7 自研 coding Agent**。审核入口（人工、非阻塞）：`trm mcp catalog list --unreviewed`；W1 遗留见 STATUS「W1 遗留」（`WorkflowListener` 未接线 / 运行记录只在内存 / 内置剧本只有落盘式开关）。

---

## 核心理念

**trimum 不是一次性代码冲刺，是长期成长的项目。** 以下清单按"下一步最有价值"排序。

---

## 🧭 Phase 3 收尾差距审计（对照 docs 与现有实现）

> 基准文档：`docs/PHASE3-4-PLAN.md`、`docs/REFERENCE-AUDIT.md`、`docs/PYDANTIC-AI-COMPARISON.md`
> ⚠️ 这三份文档已于 2026-09-20 删除（结论已落地，历史见 `git log`）；本表保留作已完成项的追溯记录。
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

## 🔴 EventBus 通信缺口（2026-09-20 只读审计，按优先级）

> 方法：通读 `docs/` 里与事件相关的文档（`SECURITY-DEFENSE-PLAN.md` §11、`security-agent-implementation-plan.md` §2/§3、
> `TARL-SPEC.md` §7、`SYSTEM-MONITOR.md`、`ERROR-CODE-SPEC.md`、`WORKFLOW-EXECUTION-PLAN.md`），
> 再对 `src/` 全量扫**生产者**（`emit_event` / `emit_task` / `SystemEvent(event_type=...)`）与**订阅者**（`subscribe`）逐条对照。
> 本轮**只读**，未改代码。结论：总线骨架是通的（pub/sub + `*` 通配 + 100 条环形历史 + replay），**缺的是生产端**。

### P0 — 安全响应链未接线（拦得住，但不会响应 / 记录 / 通知）

| 事实 | 证据 |
|---|---|
| L4 命中威胁只 `logger.warning` + 返回 denied，**不发 `security.monitor_result`、不调 SecExecutor** | `tool_gateway.py:715` |
| `security.monitor_result` 唯一生产者 `SecMonitor._dispatch()`，只被 `_on_executing()` 调用；而它订阅的 `agent.executing` **全库无生产者** | `sec_monitor.py:418 / 457 / 487` |
| ~~payload 契约不符~~ ✅ **2026-09-21 已修**：生产端改为扁平 `monitor_result_payload()`，与剧本条件一致 | `sec_monitor.py` + `tests/test_sec_monitor.py`（11 项，锁住生产端↔消费端契约） |
| `SecExecutor`（阻断 / 冻结 / 隔离 + SecAudit + SecNotif）只在这条死链路上被调用 | `sec_executor.py:182` |
| **后果** | 16 条威胁响应剧本在真机上**永远不会被自动触发**（只能手动 `trm workflow run --event`）；`security.blocked` / `security.alert` 从不出现 |

**建议动作（顺序不能乱）**：

1. ✅ **统一 payload 契约**（2026-09-21 完成）—— 选「扁平化生产端」，剧本条件不动；契约表见 `docs/SECURITY-DEFENSE-PLAN.md` §三。
2. **L4 改走 `_dispatch`** —— 一条命令同时完成「发事件 + 调 SecExecutor」（顺带决定 `agent.executing` 的 EventSnoop 路径是补上还是删掉死订阅）。
3. **定 `workflow.trigger` 的归属** —— 要么让 `WorkflowListener` 上线当生产者，要么让剧本直接听 `security.monitor_result`；**不要两套约定并存**（现在一边扁平带 `workflow_name`、一边嵌套带 `threat`）。

### P0 进展（2026-09-21）

- [x] **步骤 1/3 统一 payload 契约** —— `monitor_result_payload()` 扁平化；新增 `tests/test_sec_monitor.py`（11 项），
      其中 `TestBuiltinWorkflowContract` 断言「15 条听 `security.monitor_result` 的内置剧本，条件都能被生产端载荷命中」
      +「签名 `trigger_workflow` 与剧本名一一对应」。全量 `1167 passed / 5 failed / 7 skipped`（5 项为既有基线）。
- [x] **步骤 2/3：L4 改走 `SecMonitor.inspect()`**（2026-09-21 完成）—— 一条命令完成扫描 → 发 `security.monitor_result`
      → 交 SecExecutor（审计 / 通知 / 阻断 / `workflow.trigger`），网关按 `threats[0].defense` 决定拒绝；
      **死订阅直接删掉**（扫描入口只剩直连一条，避免重复扫描/重复阻断）；顺带修掉 L4 传 `pid=os.getpid()`
      的地雷（接上 FREEZE/KILL 会打到 daemon 自己）→ 改 `pid=0`。新增 `tests/test_gateway_layer4.py`（9 项）。
      全量 `1176 passed / 5 failed / 7 skipped`（5 项既有基线）。
- [x] **步骤 3/3：定 `workflow.trigger` 归属**（2026-09-21 完成，`f6ecfe4`）—— 裁决：威胁剧本的**自动触发只走
      `security.monitor_result`**（L4 唯一生产者，条件 = 扁平 `threat_name`）；`workflow.trigger` 归属
      「意图驱动」（TARL 三段式 / `WorkflowListener`，仍未接线），**`SecExecutor` 不再发它**（载荷约定本就不同，
      且无消费者）。测试：`test_gateway_layer4.py` 端到端（L4 广播真把剧本跑起来）+ 断言不再发 `workflow.trigger`；
      `test_workflow_runtime.py` 锁「内置剧本触发器只有 `security.monitor_result`(15) / `cron`(1)」。
- [x] **步骤 2 补丁（2026-09-21，`dbc411e`）** —— 两条缺口 + 一件前置一起收：
      - ✅ 非 DENY 威胁的处置：`layer4_gateway_action()` 把 `kill` / `freeze` / `isolate` 映射成网关 `DENY`
        （执行前没有子进程可冻/杀，「不让它跑」就是等价处置），`confirm` → `Action.CONFIRM`；
      - ✅ **装配统一**：`SecurityRuntime`（`daemon()` / `local()`）一处装配，`ToolGateway` 默认自建 `local()`
        → `trm ask` / `trm exec` / workflow 兜底网关全都过 L4（要关只认显式的 `layer4=False`）；
      - ✅ 签名收敛（L4 常开的前提）：`cat /etc/ld.so.preload`、`crontab -l`、`systemctl status`、
        `ls -la ~/.ssh/`、`ls /proc/self/fd/` 等只读命令不再命中 —— 它们也是内置剧本自己要跑的命令；
        真阳/真阴表 `tests/test_threat_signatures.py`（28 项）。
      - ⏳ `SecAudit()` 默认路径仍硬编码 `~/.trimum/audit/security.log`（不走 `TRIMUM_HOME` / `paths.trimum_home()`）；
        现在裸 CLI 走 `audit_path=None`（不落盘），只有 daemon 落盘，风险已降但硬编码仍在。
      - 设计里的 LLM 兜底（旧 `security.alert` + `needs_llm=True`）随本次删除失去唯一生产者。
- 🆕 **步骤 1 顺带发现（未修）**：`threat-ransomware-response` / `threat-btrfs-snapshot-protect`（`ransomware`）、
      `threat-persistence-sweep`（`persistence`）**没有对应威胁签名** —— 生产者应是尚未开工的 `BehaviorMonitor`，
      所以这 3 条剧本今天也没有触发路径；`threat-audit-integrity-check` 的 trigger 是 `cron`（定时），不属事件链。

### P1 — 逐条缺环

| 事件 | 生产者 | 消费者 | 状态 |
|---|---|---|---|
| `agent.executing` / `.executed` | ~~无~~ | ~~SecMonitor~~ | ✅ **2026-09-21：订阅已删** —— 扫描入口改为 ToolGateway L4 直连 `SecMonitor.inspect()`；事件本身不再是扫描触发（若要恢复只能用于观测） |
| `security.ebpf_alert` / `security.fuse_triggered` / `security.audit_breach` | 无 | 无 | **子系统未开工**（只有常量 + 文档）；`SecAudit.verify_chain()` 已实现但无人定期调用 |
| `workflow.trigger` | `workflow_listener`（未实例化） | W1 Runtime 可消费 | ✅ **2026-09-21 归属已定**：`workflow.trigger` = 意图驱动（TARL 三段式）那条链；`sec_executor` 那份**已删**（威胁剧本改由 `security.monitor_result` 驱动）→ 今天无生产者，等 `WorkflowListener` 接线 |
| `workflow.threat_response` | 无 | 无 | 文档称「已有事件」，代码里不存在 |
| `event.transform.completed` | 无 | `WorkflowListener`（未实例化） | TARL 三段式整条未接线（W1 遗留） |
| `system.alert` / `system.heartbeat` | `SystemMonitor` 从未被实例化（且是回调式） | `daily-check` 剧本听 `system.heartbeat` | 空转；`docs/SYSTEM-MONITOR.md` 示例用的 `event_bus.emit()` 这个 API 不存在 |
| `memory.*` | `experience_learner`（未实例化） | `MemoryBridge`（未实例化） | 记忆桥整条空转 |
| `planner.*` | `planner_agent` ✅ | 无 | 发了没人听（`planner.task_created` 的消费者是没启动的 `WorkflowListener`） |
| `agent.status_changed` | `agent_runtime.py:143` ✅ | 无 | `agent_runtime` 只在测试里被实例化，daemon 里没有 |
| `task.assigned` | 无 | `agent_runtime.py:219` 注释「Stub: in Phase 3」 | STATUS 旧表里标 ✅ 的 `TASK_ASSIGNED` 名不副实 |

### P1 — 总线自身的硬化项

- `EventBus._safe_call` **静默吞掉订阅者异常**（注释自称 production 会 surface，实际既不打日志也不抛）；`models.py:109` 定义的 `TRM-9005 EventBusDispatchFailed` 全库无人 raise → 订阅者写错只表现为「事件没反应」。
- `event_index.EventIndex`（首段分桶 + 保序 + 已有测试 + 已导出）**没接进 `EventBus`**，`publish` 仍是全订阅表线性扫描 + `ensure_future` 扇出。
- 匹配规则两套：总线 `_matches`（`*` 浮动匹配 1+ 段）vs workflow trigger（去前缀 + `fnmatch`），没有统一入口。
- `LiveConsole.subscribe_events()` 在 `agent_loop.py:300` 以 `"task"` 订阅（pattern `task.*`），回调却拿 `event_type == "task.started"` 全等比较，真实类型是 `task.node.started` / `task.workflow.started` → 进度永远不亮。
- SDK 侧 `src/agent-sdk/trimum_agent.py:167` 是 `publish("tool.executing", {...})` —— `publish()` 只收 `SystemEvent`，事件名也对不上 SecMonitor 订阅的 `agent.executing`；异常被 `except Exception: pass` 吃掉。
- 历史只有内存 100 条（重启即丢）、无优先级 / 背压 / ack / 重试 / 死信。

### 优先级结论

1. 🔴 **P0 安全链接线** > **E5 官方分发渠道**：安全响应是 trimum 的招牌能力，现在「拦截」能跑而「响应 / 审计 / 通知」是空的，等于 16 条剧本 + SecExecutor 全是摆设；分发渠道再顺，发的也是链条断的产品。且改动点只有 3 处，工作量可控。
2. 🔴 **E5**（与 E6 遗留的证书 `capabilities` 运行期合并同源，一起做）。
3. 🟠 **总线硬化**：属于 P0 的配套 —— `_safe_call` 静默是排障黑洞，接完线要能看见事件到底发没发出去。
4. 🟠 **W1 遗留的 `WorkflowListener` / TARL 三段式接线**：比 P0 大（要把 TransformAgent 接进 daemon + 决策 + 确认），排其后。
5. 🟡 **P2 杂项**随时穿插（低风险、互相独立）：见「下一步（优先级排序）」。
6. 🅿️ **E7 自研 coding Agent**：大工程，等前面收口。

> ⏸️ **明确「未开工」的子系统**（别误判为 bug）：eBPF 告警（`security.ebpf_alert`）、性能熔断（`security.fuse_triggered`）、
> 审计断链检测（`security.audit_breach`）—— 这三样在 `docs/SECURITY-DEFENSE-PLAN.md` 有完整设计，代码里只有常量占位，从未动工。

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
  - 遗留：`trm skill import`（生态导入）**已于 E4 补上**（`skill_import.py` + `trm skill import`，见下方 E4）；`trm env install` 已于 2026-09-20 在 Linux 真机跑通（dry-run / 幂等 / 非 root 报错，见「其他待办」末尾）
- [x] **E4. 广接入**（2026-09-20 完成）：通用 CLI 适配器 + workflow 目录 + 统一 schema + `trm skill import`
  - [x] `ecosystem.py`：`EcosystemEntry` 统一 schema（trust / risk / requires / source_url / author / origin / enabled）
        + 分级器 `assess_risk`（动词表 + 理由，无证据兜底 medium）+ 校验器 + 三个导入器共用的 `ImportRefused`
  - [x] `cli_adapter.py` + `trm tool import-cli`：只跑 `--help` 探测；产物落 `tool.json5` + 薄壳 `main.py`，
        默认 `enabled: false`；`generic_executor` 运行时再兜一层白名单（子命令 / 旗标 / `which` 现算）
  - [x] `workflow_catalog.py` + `trm workflow import`：Warp 式目录 YAML → 编译 `WorkflowDefV2`；
        声明只能把 risk 调高不能调低；`steps[].execute[].instruction` 是命令原文
  - [x] `skill_import.py` + `trm skill import`：本地目录 / git URL（`git clone --depth 1` 到临时目录）；
        frontmatter 必填 `name`/`description`；`.git` / `node_modules` 不进副本
  - [x] `enabled` 开关：`tool_file_loader.set_manifest_enabled`（逐行就地改）+ `trm tool enable|disable` +
        `trm tool list --all`；`tool_gateway.load_all()` 只 import 启用的工具
  - [x] 红线：导入不执行 / `--dry-run` 不落盘 / 非交互要 `--yes` / 第三方（工具）默认不启用 / 不覆盖已有（除非 `--force`）/ 不引入新依赖
  - [x] 测试：`tests/test_ecosystem.py`(29) + `tests/test_cli_adapter.py`(42) + `tests/test_workflow_catalog.py`(48)
        + `tests/test_skill_import.py`(40)；`trm commands --check` → 68 条通过
  - 遗留：~~编译出的 workflow 在 `trm workflow run` 下不会真的执行命令~~ → **W1 已修**（见下条）

> 排序理由：Skills 层近乎零成本 → MCP 成本中等 → CLI 适配器 → workflow 目录。

- [x] **W1. workflow 执行语义**（2026-09-20 完成）：让 workflow 能监听 Event Bus 并驱动执行
  - [x] `workflow_engine.py`：`to_workflow_definition()` 搬运 `instruction` / `agent_type` / `input_data` /
        `trigger_event`；删掉 `return` 之后的死代码与坏掉的模块级 `start_v2`
  - [x] `workflow_runtime.py`（新）：`WorkflowRuntime` = 注册表 + Event Bus 触发器 + 驱动执行 + 运行记录；
        `agent_type: shell` 处理器走 ToolGateway（策略 / 风险 / 审计 / 脱敏 / 行为基线）
  - [x] `threat_workflows.py`：16 条威胁响应剧本 → `WorkflowDefV2`（`builtin_workflows()`）；
        `source=builtin`、默认 `enabled: false`（剧本里有 `kill` / `firewall-cmd`，自动跑等于删掉确认环节）
  - [x] `api_server.py`：daemon startup 建运行时并 `start()`；只读端点 `GET /api/workflows`、
        `GET /api/workflows/runs`（刻意不开放执行端点）
  - [x] `cli/commands/workflow.py`：`list --all` / `run [--input --event --payload --timeout --dry-run]` /
        `enable`（内置剧本落盘成用户自己的文件）
  - [x] 语义：step 各自常驻监听（不串行等待）/ 同一 step 在跑则跳过 / 空触发器=仅手动 /
        精确→去命名空间前缀→`fnmatch` 匹配 / 条件用受限 `eval` / 事件环路熔断（10s 内每 workflow 最多 20 次）
  - [x] 测试：`tests/test_workflow_runtime.py`（53）+ `tests/test_api_server_startup.py`（+2）
  - 遗留：`WorkflowListener`（Transform TARL 三段式）仍未接线；运行记录只在内存；
        内置剧本只有「落盘式」启用开关

- [ ] **E5. 官方分发渠道**（2026-09-20 需求确认）—— 🚧 **分发面已闭环（2026-09-21，第二片之后）**：
  第一片 `9b40be2`：`.trmpkg` 包格式 + 打包/校验器（`src/trimum_core/trmpkg.py`，16 项测试；签名覆盖
  manifest 规范字节、manifest 覆盖逐文件 sha256、证书链到内置根、解包路径安全、校验不过不解包）。
  第二片 `2aec23b`→`4e29b4e`：`trm pkg` CLI（6 条）+ **真实官方根** `config/trust/trimum-root.crt`（Ed25519）
  + `trmindex/1` 签名目录索引（`pkg_index.py`）+ `trm install <name>|--file|--list` 接线（`pkg_install.py`，
  登记 `~/.trimum/config/installed.json5`）+ `--allow-untrusted` 降级路径 + 证书 capabilities 运行期交集
  （`capability.py` + 网关 Layer 2.6，E6 遗留一并落地）；错误码 `TRM-4011`（总数 68）。
  第三片未做：`trm install --remove`（卸载 + 注销登记 + 删 agent 证书）、官网服务端与目录托管、多用户边界。
  **第三片实施计划见下方「🚚 E5 第三片实施计划（2026-09-21 定，待开工）」**（含逐条红线与测试清单）。
  原始需求：官网提供官方 Agent / Tool / Workflow，下载即用；
  官方根证书内置（`config/trust/trimum-root.crt`），用户无需信任自签证书；
  `.trmpkg` 包（manifest + 逐文件 sha256 + 签名 + 证书链）→ 内置根验证 → `trm install <name>` / `--file <pkg>`
  设计见 `docs/ECOSYSTEM-STRATEGY.md` 第 7 节；安装 ≠ 授权，运行时仍走 ToolGateway 分层
  - [x] 子项：身份与能力模型 —— 证书携带**能力清单**（可动用工具 / 风险上限 / 有效期），运行期与内置策略取交集（只收紧）（第二片落地：`capability.py` + 网关 Layer 2.6）
  - [x] 子项：自签证书**仅本机本用户**可用（绑 `machine_id` + 用户 keystore）；他人使用需重新自签（`agent_cert.py` 已有雏形）
  - [x] 子项：多用户前瞻（**2026-09-21 定稿**：调研 + 设计，**不改代码**）—— `~/.trimum/`（用户私有）vs `/etc/trimum/`（系统公共）边界、审计日志 `user_id` 归属、私钥保护方案 → `docs/MULTI-USER-BOUNDARY.md` + `docs/ECOSYSTEM-STRATEGY.md` §7.8
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
  - [x] 已接线（2026-09-21 E5 第二片）：证书 `capabilities` 与策略的**运行期交集**已落地（`capability.py` + 网关 Layer 2.6，多来源取最严、只收紧不放宽）；详见 `STATUS.md`「E5 第二片」
- [ ] **E7. 自研 coding Agent（候选）**：参考 `affaan-m/ECC`（262,999★，agent harness operating system，903 个 `SKILL.md` / 30+ 宿主目录）
  设计 trimum 自己的 coding Agent；调研原始件 `tmp/research/ecosystem/ecc-*`（已 gitignore）

> 统一底座：四层产出的能力都注册进同一张表，一律经 ToolGateway 分层 + 审计。

## 🚚 E5 第三片实施计划（2026-09-21 定，待开工）

> 来源：E5 第二片收尾时列的三个缺口。**开工先读**：`STATUS.md`「2026-09-21 E5 第二片」、
> `docs/ECOSYSTEM-STRATEGY.md` §7 / §7.4 / §7.5、`docs/ARCH.md`「官方分发渠道（E5）」。
> 顺序 1 → 2 → 3，**只有步骤 1 是必须的代码工作**。

### 交接前提（环境与纪律，别踩）

- 分支 `server`；`git add` / `commit` / `push` 需提权（`.git` 在沙箱里只读）。
  写文件用 `[System.IO.File]::WriteAllText` + UTF-8 **无 BOM** + LF；
  `Set-Content -Encoding utf8` 会加 BOM（禁用）；不用 `apply_patch`。
- 测试：`python -m pytest tests -q --basetemp tmp/pytest-tmp -p no:cacheprovider`；
  基线 **1326 passed / 5 failed / 8 skipped**，5 项失败 = `test_depends_on` 1 +
  `test_learning_engine` 3（沙箱写真实 `~/.trimum` 被拒）+ `test_llm_integration` 1（LLM 断网），**不算回归**。
- 命令面：`trm commands --check` → **76 commands**。动了 `__command_meta__` 的 `args` 必须同步。
- 三个测试陷阱：① `TRIMUM_TRUST_ROOT` 必须固定到 fixture 根（内置根已是**真实**根）；
  ② 改完签名索引要重签；③ 相对 `url` 的索引与包必须放同一目录。

### 步骤 1 — `trm install --remove`（✅ 已完成，2026-09-21，提交 `d7aced2`）

> **落地口径（实测，与下面这份计划的差异逐条说明）**：行为 1-8 条全部照做；返回体多一个
> ``path_missing``（登记目录已被用户手工删过 → 当过期登记划账，不崩在 `rmtree` 上）；
> ``removed`` 在干跑时为 `false`（不冒充实删，与 `env_toolchain.run_install` 的 `ok ... and not dry_run`
> 同一口径 —— 这条改了计划里的速记）；红线判定用的是**恰好等于** `<TYPE_ROOTS[type]>/<name>`，
> 比「落在类型根下」更严；内置 agent 这条**只管 agent**（同名 tool 可卸）。
> `TestRemove` 14 项全绿；全量 1315 passed / 5 failed（既有基线）/ 8 skipped。

**目标**：卸载 + 注销登记 + 删 agent 证书，运行期不再把它当已装。

**命令归属决策**：走 `trm install --remove`（与 `--list` 对称），**不新增顶层命令**
——命令面保持 76，`trm uninstall` 之类的别名不做。

| 文件 | 动作 |
|---|---|
| `src/trimum_core/pkg_install.py` | 新增 `remove_package(name, *, dry_run=False) -> dict`，加进 `__all__` |
| `src/trimum_core/cli/commands/install.py` | 新增 `--remove` / `--yes` / `--dry-run`；`handler()` 分支；`_human_remove()`；`__command_meta__["install"]["args"]` 同步 |
| `tests/test_pkg_install.py` | 新增 `TestRemove`（清单见下） |
| `docs/ARCH.md` + `docs/ECOSYSTEM-STRATEGY.md` | 模块表 / 红线 / §7.5 补卸载口径（或新开 §7.6） |

**`remove_package()` 的行为（逐条，实现时照做）**

1. 查 `load_ledger()["packages"][name]`；没有 → `TRM-4011 PACKAGE_NOT_FOUND`。
2. **红线：只删登记路径，且必须落在 `TYPE_ROOTS[type]` 期望的目录下。**
   手改 `installed.json5` 把 `path` 指到工作区外或 `~/.trimum/audit` → 直接拒（`TRM-4009`），目标不删。
3. **红线：命中内置 agent 名字就拒删。** `install_package()` 只挡「已存在且没 `--force`」
   （`pkg_install.py:273`），所以 `--force` 可能覆盖过内置 agent 目录；
   登记里**没记**「安装前 `dest` 是否存在」，无法还原 —— 用
   `agent_cert.discover_bundled_agents()` 判命中即拒并提示手工处理。
4. 删 `dest` 整棵目录。agent 证书就是 `dest/cert.json`（`_write_agent_cert` 写在**包目录里**），
   随目录一起走，**不需要**单独删；**不要**去碰 `certs/` / `audit/` / `memory/`。
5. 删 ledger 条目 → `save_ledger()`；返回
   `{name, type, version, trust, path, removed: True, dry_run: bool}`。
6. `dry_run=True`：只回报「将删什么」，盘不动、ledger 不动。
7. **幂等**：未安装 → 退出码 1 + 明确文案（不崩溃、不静默 0）。
8. 卸载**不看** `trust`，`--allow-untrusted` 与它无关（卸载不是授权动作）。

**破坏性动作的确认口径**（沿用 `trm env install` 的既有约定）：
交互式 → 提示确认；非交互 → 必须 `--yes`，否则 abort；`--dry-run` 恒不执行。
`--remove` 与 `--file` 互斥（报「不能同时」）；`--yes` / `--dry-run` 只作用于包渠道，
**不要**影响无参数的旧向导路径。

**错误码决策**：**复用 `TRM-4011`，不新增** —— 少一次全量错误码计数（当前 68）波动。
只有当实现时确认「没装过」必须与「目录不存在」区分开，才加 `TRM-4012`，并同步
`models.py` + `docs/ERROR-CODE-SPEC.md` + `tests/test_error_codes.py`。

**`TestRemove` 清单**
- 卸 tool：目录消失 + ledger 条目消失 + `trm install --list --json` 里没了
- 卸 agent：`dest` 与 `dest/cert.json` 一起消失；`certs/` / `audit/` 有哨兵文件且不受影响
- 未安装的名字 → 退出码 1 + `TRM-4011`
- 幂等：连删两次，第二次明确报错
- **ledger 被手改成越界路径** → 拒绝，且目标文件仍在
- 名字命中内置 agent → 拒绝
- `--dry-run` 不动盘、不动 ledger
- 非交互无 `--yes` → abort；`--remove` + `--file` → 报「不能同时」
- 删掉 `--allow-untrusted` 装的 tool 后 `pkg_install.untrusted_names()` 不再含它
  （运行期联动点：`capability.py:197` 读的就是这张表）

### 步骤 2 — 目录托管与发布流程（✅ 已完成，2026-09-21）

> **落地口径**：新增 `pkg_index.entries_from_directory()`（扫目录 + 质检）与 `trm pkg index <dir> -o index.json5`
> 子命令（命令面 76 → **77**）。四条口径：只收录验得过的包（一个不过就整体失败、不写索引）/
> 字段取自校验过的 manifest 而非文件名 / `url` 相对索引位置（支持子目录，可离线）/ 写完自检（就地验签）。
> **官网服务端仍不做**，改为交付 `docs/PACKAGE-CHANNEL-OPS.md`（造根 → 建签名者 → 打包 → 建索引 → 上线 →
> 轮换根 → 出问题对照表 + 边界）。验收按原计划达成：`trm pkg index dist/` → `TRIMUM_PKG_INDEX=dist/index.json5
> trm install <name>` 一条链跑通（`tests/test_pkg_install.py::test_an_index_built_by_the_cli_installs_end_to_end`）。
> 新增测试 11 项（`tests/test_cli_pkg.py::TestIndex` 10 + 端到端 1），全量 1326 passed / 5 failed（既有基线）。

- **`DEFAULT_INDEX_URL` 仍是占位**（`https://trimum.dev/packages/index.json5`，本机没有服务端）。
- 建议加 `trm pkg index <dir> -o index.json5` 子命令：扫目录里的 `.trmpkg` → 生成 `trmindex/1`
  document → 用签名者签 → 落盘。理由：`pkg.py` 已有 `root-init` / `signer-init` / `create`，
  发布方闭环缺的正好是「建索引」这最后一步，且子命令可测（比 shell 脚本好）。
- 验收：`trm pkg index` → `TRIMUM_PKG_INDEX=<dir> trm install <name>` 一条链跑通
  （`tests/test_pkg_install.py` 里已有本地索引的建法可复用）。
- **官网服务端不做**（要域名 / 托管 / CI，属产品决策）。改为写
  `docs/PACKAGE-CHANNEL-OPS.md`：造根 → 建签名者 → 打包 → 建索引 → 上线 → **轮换根**
  （换根 = 旧包全部作废）→ 自建镜像（`--index` 指内网）。

### 步骤 3 — 多用户边界（调研 + 设计，**不写实现**）✅ 2026-09-21 完成

- 见 `docs/ECOSYSTEM-STRATEGY.md` §7.2 的三个子问题：`/etc/trimum/`（系统公共）vs
  `~/.trimum/`（用户私有）的边界、审计日志 `user_id` 归属、私钥保护（文件权限 / DPAPI / keyring）。
- 现状单点已经存在：`paths.py::trimum_home()` 是唯一改点；
  `agents/<name>/cert.json` 已把「来源 + 证书 + 版本 + 登记」捆在最小单位。
- 产出：把 §7.2 扩写成带方案的章节（或 `docs/MULTI-USER-BOUNDARY.md`），含迁移成本。
- ✅ **已交付**：新建 `docs/MULTI-USER-BOUNDARY.md`（现状对照表 / 三个问题各带方案 / 六条不变量 / 实现顺序与风险 / 迁移成本）；
  `docs/ECOSYSTEM-STRATEGY.md` §7.2 改为定稿指针并新增 §7.8；`docs/ARCH.md` / `AGENTS.md` 文档地图同步。
  **复核结论：现有设计无硬伤，不改代码**（计划原文：「除非发现现有设计有硬伤，否则不动代码」）。
- 除非发现现有设计有硬伤，否则**不动代码**。

### 本片红线（写进代码与测试）

- 卸载只删**登记过的**路径，且必须落在 `TYPE_ROOTS` 期望的目录下；越界即拒。
- 内置 agent 目录不可被卸载删掉。
- 卸载不碰 `certs/` / `audit/` / `memory/`（用户数据与安全记录与包无关）。
- 破坏性动作：`--dry-run` 恒不执行；非交互无 `--yes` 必 abort。

## 🔌 MCP 接入（P1，2026-09-20 立项）

> 方案见 `docs/MCP-INTEGRATION-PLAN.md`。现状：`MCPDispatcher` 是占位实现（`src/trimum_core/tool_dispatchers.py:716`），
> trimum 目前**无任何真实 MCP 能力**。

- [x] **M0. 冻结设计**（2026-09-20）：自研最小 stdio client（不引 SDK/Node）；3 个用例 = 本机能力接入 / 远程 SaaS 受管通道 / 一行文件零代码扩能力；决议见 `docs/MCP-INTEGRATION-PLAN.md` §2.3
- [x] **M1. stdio 客户端**（2026-09-20）：`src/trimum_core/mcp_client.py`（JSON-RPC 2.0 换行分帧、stderr 落文件、超时/EOF 标记坏连接）+ `tests/test_mcp_client.py`（16 项，真协议 fixture server）
- [x] **M2. 注册与鉴权**（2026-09-20）：`mcp_registry.py`（`~/.trimum/mcp/<name>.json5`，deny-by-default + glob 白黑名单 + 连接池）+ `MCPDispatcher` 实装 + `ToolGateway` 回填审计 + `mcp_call` 事件 + `trm mcp list/tools/call/paths`；`tests/test_mcp_registry.py`（27）/ `tests/test_mcp_dispatcher.py`（30）
  - 顺带修掉：`trm --json` 的 stdout 被 INFO 日志污染（CLI 诊断改走 stderr）；连接池 `refresh` 泄漏旧客户端
- [x] **M3. 策展导入器**（2026-09-20 完成）：`mcp_catalog.py` + `trm mcp catalog import/list` → `config/mcp-catalog.yaml`（4,118 条 → **232 条候选**，`reviewed: false`，人工审核后才启用）；离线、确定性输出、拒绝覆盖已存在清单（`--force` 保留人工 `reviewed`/`name`/`note`）；`tests/test_mcp_catalog.py`（52）
- [x] **M4. HTTP/SSE + 生命周期**（2026-09-20 完成）：连接池懒启动 + 空闲回收（`reap()`）、`trm mcp list/status/restart`、运维文档；真机基线 827 passed / 11 failed / 2 skipped（均为既有环境失败）

策展红线：优先 `uvx` / `pip install` / 单二进制（Go/Rust），`npx` 派系默认不收。
（2026-09-20 快照：awesome 列表 4,117 条中 `npx` 626、`pip install` 127、`uvx` 108。）

## 🟡 后续方向（CLI 完成后）

### CLI 进阶
- [ ] `trm ask` 墨迹/屏幕截图输入支持
- [ ] `trm memory import` / `export`（记忆迁移）
- [ ] CLI 别名自定义（`.trimumrc` 配置文件）
- [ ] 自动补全脚本（bash/zsh/fish）

### 其他待办（承接之前）
- [x] **浏览器工具备选 `epiral/bb-browser` 评估完成（2026-09-20）→ 结论：不接入**：本体是 Node/TS（与「去 Node」冲突）；MCP server 源码不在公开仓库（与它自己的 `PRIVACY.md` 「可审计」矛盾）；`site` 社区适配器在页面上下文 `eval` 第三方 JS，绕开 `ToolGateway` / 策略 / 审计；上游 4 个月无 push。借鉴项已落 `docs/TOOL-DEVELOPER-GUIDE.md` §11（适配器自带 example/domain、`@N` 稳定元素编号）。完整报告：`docs/BB-BROWSER-EVALUATION.md`
- [x] **#3.8 Browser Tool 后端收尾**：opencli 已真正弃用（`tool.json5.disabled` + 加载器只认 manifest，2026-09-19 验证不再报 module_failed）
- [x] **真机 `/opt/trimum` 已同步**（2026-09-20 20:52 全树同步）：补上 M4 遗留的 `reap()` 修复，缺的 9 个模块 / 5 个 CLI 命令 / 5 个 yaml / 9 个 test 文件全部进树；复核哈希见文件头
- [x] **daemon 部署形态**（P2，2026-09-20 改判）：**回到 systemd 托管** —— `trmd.service` 现为 `enabled + active`（`Restart=always` / `RestartSec=5` / `User=guzhujushi`），手工 daemon 已退出。重启一律 `sudo systemctl restart trmd`；`scripts/restart_trmd.sh` 已加 systemd 守卫（检测到单元 active 时不再抢端口，非 root 下打指引并 `exit 3`）。历史：当天曾先选「纯手工 daemon」，但单元被重新拉起后与手工进程互抢 8321（journal 里 `NRestarts` 已到 2150），故改判。切换工具仍保留 `scripts/fix_trmd_loop.sh`
- [x] **开发树 `.venv/bin/trm` 入口失效**（2026-09-20 修）：脚本仍是旧的 `from trimum_core.main import cli_dispatch`（`cli_dispatch` 早已不存在）→ 改成 `from trimum_core.cli import main` 后 `trm --version` / `trm commands --check`（63 条）均正常。注意该 venv **没装 setuptools**，`pip install -e . --no-build-isolation` 会 `BackendUnavailable`，要正规重装得先装 setuptools（需网络）
- [x] **幽灵聚合条目的语义**（2026-09-20 收口）：原护栏「目录读不到就不动缓存」把「一个 server 都没配」和「不知道有哪些 server」混成了一件事。新增 `mcp_registry.definitions_readable()`：**目录不存在 → 照清**，**目录在但列不出来 → 不动并记 `mcp_index.prune_skipped`**；`tests/test_mcp_bridge.py` 87 → 93 项，全量 921 passed 无回归
- [x] **`trm env install` 真机跑通**（2026-09-20）：dry-run / 已装幂等 / 非 root 报错三条路径已在真机验证，并修掉两个真缺陷（管道里 `_confirm()` 永久挂死、失败时不打原因）；`ToolGateway._prompt_confirm()` 同样修成 fail closed
- [ ] **`trm env install` 的 root 真执行路径待跑**：`sudo bash /tmp/trm_env_install_real.sh`（全是已装包，幂等）
- [ ] **`/opt/trimum` 部署树待同步本轮修复**（2026-09-20 21:33）：`sudo bash /tmp/sync_opt_tree.sh`（tar 已就位，含幽灵条目/prune、env+网关确认、install 向导三项；开发树已单独同步，无需 `--fix-home`）
- [x] **`install_fn.py` 安装向导非交互挂死已修**（2026-09-20）：拆出 `_interactive()` / `_read_yes_no()`，非 TTY 不提问，三个可选步骤（LLM key / 开机自启 / 立即启动）一律跳过并提示；新增 `tests/test_install_fn.py` 14 项（含「管道里 `input()` 绝不被调用」）；实测管道场景 1.1s 退出（修前挂死）
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
| **2026-09-20 生态四层 E1 / E6 / E3** | ✅ E1 命令面 + Skills 分发；E6 选装模型 + 首启引导（宿主探测 / 身份证书 / 官方 Agent 证书）；E3 环境层 `trm env`（详见 `STATUS.md`、`docs/ARCH.md`） |
| **2026-09-20 收尾校验 + 下次继续指针** | ✅ 全量测试 687/8/4（与基线逐条一致，无回归）+ `trm commands --check` 58 条 + `trm mcp call` 端到端冒烟 stdout 纯 JSON；TODO 记 M3 输入/输出/红线，STATUS / ARCH 修正过期口径；四分支同步 |
| **2026-09-20 E2 MCP 接入（M0/M1/M2）** | ✅ stdio 客户端 + 文件化注册（deny-by-default）+ `MCPDispatcher` 实装 + `mcp_call` 审计 + `trm mcp`；73 项新测试 |
| **2026-09-20 M3 MCP 策展导入器** | ✅ `mcp_catalog.py` + `trm mcp catalog import/list` + `config/mcp-catalog.yaml`（4,118 → 232 条候选，红线逐条计数可查）；52 项新测试 |
| **2026-09-21 E5 第一片：`.trmpkg` 包格式 + 打包/校验器** | ✅ `src/trimum_core/trmpkg.py`：manifest.json5 + SIGNATURE + chain.json；签 manifest 规范字节 → manifest 覆盖逐文件 sha256；证书链追到内置根（`config/trust/trimum-root.crt`，只提交公钥）；解包拒绝绝对路径 / `..` / 链接 / 设备文件；`tests/test_trmpkg.py` 16 项（含四类拒绝路径）。CLI 与 `trm install` 接线在下一片 |
| **2026-09-21 E5 第二片：`trm pkg` + 真实内置根 + 索引 + `trm install` + 能力交集** | ✅ `trm pkg` CLI 6 条（发布方 3 + 使用者 3）+ 真实官方根（Ed25519，私钥只在发布方 `~/.trimum/trust/`）+ `pkg_index.py`（`trmindex/1` 签名索引，条目 `sha256` 是承诺）+ `pkg_install.py`（校验 → 落地 → 登记 `installed.json5`）+ `capability.py` + 网关 Layer 2.6（E6 遗留一并落地）；错误码 `TRM-4011`（总数 68）；新增 73 项测试（`test_cli_pkg` 25 / `test_pkg_install` 28 / `test_capability` 20）。剩 `--remove` / 官网托管 / 多用户边界 |
| **2026-09-21 P0 步骤 3/3：定 `workflow.trigger` 归属** | ✅ 剧本自动触发只走 `security.monitor_result`（L4 唯一生产者）；`SecExecutor` 不再发 `workflow.trigger`（意图驱动那条链留给未接线的 `WorkflowListener`）；新增端到端用例（L4 广播 → W1 Runtime → 剧本步骤经网关执行）+ 内置剧本触发器契约测试。**P0 安全响应链闭环** |
| **2026-09-21 P0 步骤 2 补丁：L4 装配统一 + 处置映射 + 签名收敛** | ✅ `SecurityRuntime`（`daemon()` / `local()`）一处装配 + 网关默认自建 `local()` → `trm ask` / `trm exec` / workflow 兜底全都过 L4；kill/freeze/isolate → 网关 `DENY`；6 组签名收敛到「动手才拦」（`crontab -l` / `systemctl status` 等只读命令解封）；新增 `tests/test_threat_signatures.py`（28 项）+ `test_gateway_layer4.py` +7 |
| **2026-09-21 P0 步骤 2/3：L4 改走 `SecMonitor.inspect()`** | ✅ 扫描 → 广播 → SecExecutor（审计/通知/阻断/`workflow.trigger`）→ 网关拒绝，一条链全通；删掉 `agent.executing` 死订阅；修掉 L4 误传 `pid=os.getpid()`（会打到 daemon 自己）；新建 `tests/test_gateway_layer4.py`（9 项，真链路断言） |
| **2026-09-21 P0 步骤 1/3：`security.monitor_result` 载荷契约扁平化** | ✅ 生产端改发扁平载荷（`monitor_result_payload()`），与 15 条内置剧本条件对齐；新建 `tests/test_sec_monitor.py`（11 项，含生产端↔消费端契约锁）；契约表落 `docs/SECURITY-DEFENSE-PLAN.md` §三 |
| **2026-09-21 根目录文档合并与清理** | ✅ 删除 `PRD.md`（≈95% 与 STATUS/TODO/docs 重复）；`ARCH.md` 去重后移入 `docs/ARCH.md`；引用同步（sync 脚本 / OPERATIONS / TODO / README / AGENTS）；清空 `tmp/`（保留 `tmp/research/`）、`.pytest_cache/`、`.sonar/` |
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
| 本地全量测试（E4） | **1099 passed / 5 failed / 7 skipped** (2026-09-20)。5 项 = 既有基线（沙箱 + PATH 缺 `python.exe` + LLM 断网），与 E4 前逐条相同 |
| 真机 Ubuntu（E4） | **1098 passed / 11 failed / 2 skipped** (2026-09-20)。严格基线对照：`git archive cfafc21` 解到 `/tmp/trimum_pre_e4` 跑 `PYTHONPATH=... pytest`，失败集合归一化 diff = **IDENTICAL_11_of_11** |
| E4 真机验收 | `scripts/accept_e4.py` → **43 passed / 0 failed**（三个导入器 + 六条红线 + 哨兵文件证明「导入不执行」） |
| 新增覆盖（2026-09-20 E4） | `test_ecosystem.py`（29）、`test_cli_adapter.py`（42）、`test_workflow_catalog.py`（48）、`test_skill_import.py`（40） |
| 本地全量（W1） | **1156 passed / 5 failed / 7 skipped** (2026-09-20)。5 项 = 既有宿主基线（沙箱 + PATH 缺 `python.exe` + LLM 断网），与 W1 前逐条相同 |
| 新增覆盖（2026-09-20 W1） | `test_workflow_runtime.py`（53：v2 编译 / 触发器匹配 / 条件 / 内置剧本 / 运行时记账 / 红线 / CLI）、`test_api_server_startup.py`（+2：daemon 起运行时 + 只读端点） |
| 新增覆盖（2026-09-20 生态轮） | `test_cli_commands_meta.py`（15）、`test_skill_sync.py`（27）、`test_hosts.py`（13）、`test_setup_wizard.py`（33）、`test_agent_cert.py` 增补（11）、`test_env_toolchain.py`（34）、`test_mcp_client.py`（16）、`test_mcp_registry.py`（27）、`test_mcp_dispatcher.py`（30） |
| 新增覆盖（2026-09-20 M3） | `test_mcp_catalog.py`（52）：解析/分类/红线/命名/渲染 IO/CLI + 真实快照比对 |
| 新增覆盖（2026-09-20 真机修复轮） | `test_setup_wizard.py::TestSetupCommand::test_skipped_identity_note_keeps_stdout_json_clean`（1，`--json` 契约回归）；`test_mcp_dispatcher.py` 审计哨兵改成不撞路径的串 |
| 新增覆盖（Phase 3 收尾） | `test_tool_gateway_security_rule.py`（11）、`test_context_compactor.py`（13）、`test_audit_store.py`（15）、`test_source_type_flow.py`（6）、`test_learning_feedback.py`（11）、`test_agent_spawn.py`（12）、`test_api_server_startup.py`（3）、`test_ipc_listener.py`（3）、`test_cli_commands.py::TestSecurityLearningCommand`（3） |

---

## 克隆/分支同步

| 分支 | 状态 | 备注 |
|------|------|------|
| `server` | ✅ 已同步 | 当前工作分支；E1 `779c0e0` / E6 `ab26edf` / 清理+证书 `1456aba` / E3 `4331437` / E2 `634e62a` / **M3 `e7a30f5`** / **真机修复轮 `209c98e`** |
| `server`（2026-09-21 E5 第二片 1/4） | ✅ 已推送 | `2aec23b` `trm pkg` CLI（verify / info / create / extract / root-init / signer-init）+ `tests/test_cli_pkg.py`（25 项） |
| `server`（2026-09-21 E5 第二片 2/4） | ✅ 已推送 | `5c836e1` 生成并提交**真实官方根** `config/trust/trimum-root.crt` + `README.md` 重写 + 3 项内置根测试 |
| `server`（2026-09-21 E5 第二片 3/4） | ✅ 已推送 | `2c091c4` `pkg_index.py` 签名目录索引 + `pkg_install.py` 安装/登记 + `trm install` 接线 + `TRM-4011` + `tests/test_pkg_install.py`（28 项） |
| `server`（2026-09-21 E5 第二片 4/4） | ✅ 已推送 | `784992c` `capability.py` 能力交集 + 网关 Layer 2.6（L2.5 后、L4 前）+ `tests/test_capability.py`（20 项） |
| `server`（2026-09-21 E5 第三片 1/3） | ✅ 已提交 | `d7aced2` `trm install --remove`（卸载 + 注销 + 两条红线 + 确认口径）+ `tests/test_pkg_install.py`（28 → 42）+ 文档（ARCH / 生态战略 §7.6） |
| `server`（2026-09-21 E5 第三片 2/3） | ✅ 已提交 | `trm pkg index` 发布方闭环（`pkg_index.entries_from_directory` + CLI 子命令，命令面 77）+ `tests/test_cli_pkg.py::TestIndex`（10）+ 端到端 1 项 + `docs/PACKAGE-CHANNEL-OPS.md` |
| `server`（2026-09-21 E5 第二片文档口径） | ✅ 已推送 | `4e29b4e` `docs/ARCH.md` 实现节 + `docs/ECOSYSTEM-STRATEGY.md` §7.5 + requires PATH 探测（缺依赖只警告不拒装） |
| `server`（2026-09-21 E5 第一片） | ✅ 已提交 | `9b40be2` `.trmpkg` 包格式 + 打包/校验器（`trmpkg.py` + 16 项测试 + 错误码 `TRM-4009/4010` + `config/trust/README.md` + `docs/ECOSYSTEM-STRATEGY.md` §7.4） |
| `server`（2026-09-21 P0 步骤 3） | ✅ 已提交 | `f6ecfe4` 定 `workflow.trigger` 归属：剧本只走 `security.monitor_result`，`SecExecutor` 不再发 `workflow.trigger`；端到端用例（L4 广播真的驱动剧本）；内置剧本触发器契约锁 |
| `server`（2026-09-21 P0 步骤 2 补丁） | ✅ 已提交 | `dbc411e` L4 装配统一（`SecurityRuntime`：任何入口都过 L4）+ 处置映射（kill/freeze/isolate → 网关 DENY）+ 签名收敛（动手才拦）；`tests/test_threat_signatures.py` 新建（28 项） |
| `server`（2026-09-21 P0 步骤 2） | ✅ 已提交 | `d5393a6` L4 走 `SecMonitor.inspect()`：拦截 + 广播 + 审计 + 通知 + `workflow.trigger` 一条链打通；删死订阅；`pid=0` 修地雷 |
| `server`（2026-09-21 P0 步骤 1） | ✅ 已提交 | `087a476` `security.monitor_result` 载荷扁平化 + `tests/test_sec_monitor.py`（11 项） |
| `server`（2026-09-21 文档合并与清理） | ✅ 已提交 | `9096e9a` 删除 `PRD.md`、`ARCH.md` → `docs/ARCH.md`、清 `tmp/`（留 `research/`） |
| `server`（E4，2026-09-20） | ✅ 已推送 | E4 计划 `fdee6d5` / S1+S2+S5 `be5198d` / S3 `861126e` / S4 `05bb1ee` / S6 文档 `be604e8` / S7 验收 + `scripts/accept_e4.py` 见 `STATUS.md`「E4 提交与分支」 |
| `main` / `ubuntu` / `arch-linux`（E4） | ⏸ 未同步（设计如此） | `AGENTS.md` 分支纪律改判：**日常只推 `server`**，这三个分支只在收尾阶段统一同步推送（E4 之前的 M4.5 收口已同步过） |
| `main` | ✅ 已同步 | E1 `49b2ef4` / E6 `e0e8f0b` / 清理+证书 `2b88561` / E3 `2b4e9b2` / E2 `8af7d5d` / **M3 `74b563f`** / **真机修复轮 `e0ad16f`** |
| `ubuntu` | ✅ 已同步 | E1 `ba3ebe7` / E6 `e335db6` / 清理+证书 `c0885a8` / E3 `a5c6ad5` / E2 `166841d` / **M3 `5200b99`** / **真机修复轮 `3040b00`** |
| `arch-linux` | ✅ 已同步 | E1 `1f58b7c` / E6 `417b9cc` / 清理+证书 `18f88c8` / E3 `98c8ccd` / E2 `c68ce85` / **M3 `1ef88fa`** / **真机修复轮 `9925c19`** |

> 收尾文档提交（2026-09-20，`docs:` 校验结果 + M3 继续指针）：server `7346ee6` / main `a7cd2db` / ubuntu `fbd6b0f` / arch-linux `0b6e1ac`
