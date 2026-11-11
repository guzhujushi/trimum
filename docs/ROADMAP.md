# ROADMAP — Agent Runtime × System Intelligence

> 2026-11-11 按新架构主线重写。
> 本文只描述方向、阶段与验收口径；具体任务与进度见 `STATUS.md` / `TODO.md`，架构裁决见 `docs/ARCH.md`。
> 状态：✅ 已完成　🟡 进行中　⚪ 未开始　🚫 不做
> 目标内核基线：**Linux 7.0**（计划升级）；升级前 6.8 只作当前实测事实，不作为长期约束。

---

## 0. 总路线

```mermaid
flowchart LR
    R0[R0 文档与认知统一<br/>✅] --> R1[R1 Agent Runtime 收敛<br/>🟡]
    R1 --> R2[R2 观测基线<br/>🟡]
    R2 --> R3[R3 工作负载分析 MVP<br/>⚪]
    R3 --> R4[R4 策略仓库与选择<br/>⚪]
    R4 --> R5[R5 验证与受控执行<br/>⚪]
    R5 --> R6[R6 反馈闭环<br/>⚪]
```

两条主线始终并行：

- **Agent Runtime**：先把现有能力收敛成稳定的运行时边界。
- **System Intelligence**：先观测，再分析，再策略，最后才是受控执行。

---

## R0 — 文档与认知统一 ✅

**目标**：把旧文档中的分散功能设计收敛为「Agent Runtime + System Intelligence」两条主线。

交付：

- 重写 `README.md` 与 `docs/ARCH.md`。
- 新增 `docs/architecture/agent-runtime.md`、`docs/architecture/system-intelligence.md`。
- 新增 `docs/architecture/code-reuse.md`，记录复用矩阵、许可证边界与 Linux 7.0 前置检查。
- 许可证从 MIT 改为 GPL-2.0-only（从下一个发布版本起；历史版本仍为 MIT）。
- 清理过期快照与已被取代的实现蓝图。
- 更新相关设计文档的归属标注。

验收：

- 文档中每一项状态能对应到代码或明确标为 TBD。
- 不再把规划写成已实现能力。
- 旧模块都能在新架构中找到逻辑归属。

---

## R1 — Agent Runtime 收敛 🟡

**目标**：让现有分散模块形成稳定的 Runtime 边界，但不改变既有行为。

候选工作：

1. **Kernel 门面**：**已裁决 B 薄门面**（统一入口/schema，内部模块不拆不改）。
2. **Plan Agent 契约**：计划 schema、资源需求、能力需求、失败回退。
3. **Storage Manager**：工作区、产物、缓存、日志、审计的配额与清理。
4. **Workflow 级预算**：步数、token、并发、资源上限。
5. **状态与观测面**：统一 Agent / Workflow / Sandbox 状态，供 CLI 与 System Intelligence 读取。
6. **配置收敛**：继续执行「显式参数 > env > 配置 > 默认」，禁止新增硬编码路径 / 阈值。

硬约束：

- 不改变现有 Tool Gateway / 沙箱 / 审计的语义。
- 不新增绕过 Tool Gateway 的执行通道。
- 失败保持 fail-closed，不静默降级。

验收：

- 现有测试基线不回归。
- `trm status` / `trm doctor` 能反映 Runtime 关键状态。
- 至少一条端到端用例覆盖「计划 → 调度 → 沙箱 → 工具 → 审计」。

---

## R2 — 观测基线 🟡

**目标**：把「系统正在发生什么」变成稳定、低成本、可查询的数据面。

**已裁决（2026-11-11）：eBPF 短期保持 `perf_event_paranoid=3`（A）**；纯 `bpf(2)` attach 只作后备设计。
审计链刷屏先诊断，不直接 rechain。

候选工作：

1. eBPF 事件 schema 与采样策略（避免高频事件拖垮业务）。
2. cgroup / psutil / SystemMonitor 指标统一。
3. 指标与审计 / Event Bus 的关联（run id / agent id / workflow id）。
4. 观测数据保留、轮转与查询接口。
5. 观测失败不影响业务的旁路保证。

验收：

- 能回答「某个 Agent / Workflow 在执行期间消耗了什么、触发了什么事件」。
- 观测开销有上限，且有背压 / 采样策略。
- eBPF 加载失败、回灌失败、指标缺失都有明确降级路径（只降观测，不降安全）。

---

## R3 — Workload Analysis MVP ⚪

**目标**：从原始指标走向「工作负载分类 + 瓶颈判断」。

**已裁决（2026-11-11）：A 规则 / 阈值优先**。个人 AI 工作站，不做高并发；
复用 AgentCgroup 的 cgroup 生命周期、tool-call 临时 cgroup、hint / OOM 反馈与 JSONL metrics；
SchedCP / AgentSight 作为可选外部工具，不整体嵌入。目标内核 Linux 7.0，升级后先做能力自检。

候选工作：

1. 工作负载分类：coding / shell / browser / mcp / batch / unknown。
2. 阶段识别：startup / steady / burst / idle。
3. 资源竞争与瓶颈判断：CPU / 内存 / IO / 网络 / 锁。
4. 置信度与证据链。
5. 离线回放与调参。

验收：

- 在一组可复现负载上给出分类与瓶颈，且有证据。
- 不把「猜」当结论；置信度低时明确输出 unknown。
- 分析结果可被 Policy Engine 消费（即使 Policy Engine 还没实现）。

---

## R4 — 策略仓库与策略选择 ⚪

**目标**：先复用，再调整，最后才生成。

**已裁决（2026-11-11）：存储 A（Git 版本化 YAML）；生成边界 B（AI 提议 + 人工审批 + 强制验证）。**

候选工作：

1. Policy Repository 条目格式、存储、版本、签名。
2. 已有策略的登记：cgroup profile、eBPF 程序、调度策略。
3. 适用条件与前置依赖。
4. 历史结果与性能基准记录。
5. Policy Engine 的选择 / 参数调整逻辑。
6. 「生成新策略」的边界与人工审批点。

验收：

- 给定工作负载分析结果，能选出已有策略或明确说「没有适用策略」。
- 每条策略可追溯作者、验证记录、适用条件。
- 不经过仓库与验证的策略不能进入执行链。

---

## R5 — 验证与受控执行 ⚪

**目标**：让「AI 辅助的系统调整」可控、可验证、可回滚。

**已裁决（2026-11-11）：Privileged Controller C（先不拆，人类审批顶着）。**
Linux 7.0 升级后，BPF LSM / sched_ext 可以做能力检查与最小 PoC；仍不阻塞 MVP，也不放宽 helper 权限。

候选工作：

1. 静态分析 / 运行前验证。
2. 隔离环境测试与性能基准。
3. 运行时监控、异常熔断、自动回滚。
4. Privileged Controller 的通用化边界（继续最小权限）。
5. BPF LSM / sched_ext 的可行性评估与 PoC。
6. 人工审批与紧急停止。

验收：

- 未经验证的策略无法部署。
- 部署失败能自动回滚或至少安全停止。
- 所有受控操作有审计记录。
- 不给 daemon / helper 增加不必要的 capability。

---

## R6 — 反馈闭环 ⚪

**目标**：Agent Runtime 与 System Intelligence 形成稳定闭环。

**已裁决（2026-11-11）：暂缓**，等 R1 / R2 / R4 稳定后再做。

候选工作：

1. Runtime → System Intelligence：资源使用、执行结果、失败原因。
2. System Intelligence → Runtime：资源建议、策略建议、风险提示。
3. 反馈的频率、去抖、优先级与冲突处理。
4. 闭环效果评估：吞吐、延迟、资源利用率、失败率。
5. 人工接管与解释界面。

验收：

- 反馈能实际影响后续任务的资源需求或执行方式。
- 反馈失败不影响业务。
- 每个自动调整都能解释「为什么」。

---

## 可选扩展轨道（不阻塞主线）

| 轨道 | 内容 | 状态 |
|---|---|---|
| 生态四层 L0–L3 | 环境清单、MCP、Agent Skills、workflow 目录 | ✅ 已实现，维护为主 |
| 编码智能体 | `trm exec --code`、编辑原语、验证闭环、技能运行时 | ✅ 主体已实现 |
| 官方分发渠道 | 包格式、签名、索引、`trm install` | ✅ 主体已实现 |
| 多用户边界 | `/etc/trimum` 公共层、审计归属、私钥保护 | 🟡 调研完成，未改代码 |
| 浏览器 / 桌面 / GUI | 浏览器工具、桌面预设、远程桌面 | 🟡 可选前端，不是核心 |
| AIOS / Cerebrum 兼容 | 可选外部 Agent Runtime / SDK 适配；独立 venv + 沙箱，不进入核心 | 🟡 调研完成，暂不接入 |
| 语义记忆 / RAG | 本地 embedding + sqlite-vec + RRF | ⚪ 未来设计 |

---

## 明确不做 / 暂不投入

- 完整 Linux 发行版。
- 以桌面美化和桌面环境为核心卖点。
- 大规模插件生态作为主线。
- 独立知识管理系统 / 独立系统 Agent / 复杂 GUI 助手。
- 为兼容旧架构而保留的重复抽象。
- 把 LLM 推理放进内核执行路径。

---

## 已裁决（2026-11-11）

| 决策 | 结论 |
|---|---|
| 内核基线 | Linux 7.0（计划升级）；升级前 6.8 只作实测事实。 |
| 许可证 | GPL-2.0-only；历史版本仍为 MIT。 |
| 代码复用 | AgentCgroup 第一优先；SchedCP / AgentSight 可选外部；ActPlane 只作设计参考；核心不引入 Rust 工具链或新常驻服务。 |
| RuntimeKernel | B 薄门面：统一入口/schema，内部模块不拆。 |
| Plan Agent | B 版本化 schema；TARL 只带引用与摘要。 |
| Storage Manager | B 统一 API + 配额。 |
| Workflow 预算 | B 独立 WorkflowBudget。 |
| EventBus | B JSONL/WAL + 回放。 |
| 成本视图 | A `trm status` + `--json`。 |
| 硬资源 / token 成本 | 硬资源 A 硬拒绝；token/成本 B pending 审批；默认 10% 浮动。 |
| eBPF perf gate | A 短期 `perf_event_paranoid=3`；纯 `bpf(2)` 后备。 |
| 审计链刷屏 | 先诊断；良性则隔离旧链 + 新链。 |
| Workload Analysis | A 规则/阈值优先；复用 AgentCgroup / SchedCP / AgentSight 的指标与事件设计，不整体嵌入其运行时。 |
| Policy Repository | A Git 版本化 YAML。 |
| 策略生成 | B AI 提议 + 人工审批 + 强制验证。 |
| Privileged Controller | C 先不拆，人类审批顶着。 |
| 反馈闭环 | 暂缓，等 R1/R2/R4 稳定。 |

## 剩余待决策

1. Plan schema 字段冻结与兼容策略。
2. StorageManager 配额默认值与迁移顺序。
3. 系统级调度反馈接口。
4. Execution Verifier 验证等级。
5. Linux 7.0 上 sched_ext / BPF LSM / memcg_bpf_ops 的实际能力与 PoC 准入。
6. GPU / 网络 / 存储 IO 预算模型。
7. 多用户下 Runtime 归属。
8. AgentCgroup 的 GPL 精确版本与可 vendor 模块边界。

这些决策在 `docs/ARCH.md` §9、两份详细设计文档与 `docs/architecture/code-reuse.md` 中保持同步。
