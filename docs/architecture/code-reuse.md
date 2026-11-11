# 代码复用与许可证边界

> 2026-11-11 裁决：**内核目标基线改为 Linux 7.0；项目许可证改为 GPL-2.0-only；复用优先，但不引入大量依赖。**
> 本文是「复用哪些外部项目、以什么方式复用、许可证怎么处理」的唯一真源。
> 总体架构见 `docs/ARCH.md`；System Intelligence 的职责与策略链见 `docs/architecture/system-intelligence.md`。

---

## 1. 结论先行

1. **内核不再是复用障碍**：真机计划升级到 Linux 7.0，sched_ext、BPF LSM、memcg 相关能力具备评估前提。
   但「内核版本够」不等于「功能一定可用」，升级后仍要先做能力自检，不把 7.0 当成无条件可用承诺。
2. **许可证改为 GPL-2.0-only**：这样可以直接复用 GPL-2.0 的 AgentCgroup 代码；历史版本仍是 MIT，
   从下一个发布版本起按 GPL-2.0-only 分发。
3. **AgentCgroup 是第一优先复用对象**：它和 trimum 一样是 Python + cgroup v2 + eBPF 路线，最接近现有栈。
   优先复用其 Python、bash wrapper、cgroup 生命周期与 JSONL 指标，不整体嵌入它的 daemon。
4. **SchedCP / AgentSight 走可选外部工具**：它们主要是 Rust 实现，适合作为用户自行安装的外部调度器/观测器，
   不作为 trimum 核心依赖，不把 Rust 工具链带进主运行时。
5. **ActPlane 只作设计参考**：它要求 root 或 `CAP_BPF` + `CAP_SYS_ADMIN`，与 trimum「helper 不带
   `CAP_SYS_ADMIN`」的红线冲突；不能为了复用而放宽权限边界。
6. **MVP 优先**：R1 / R2 继续收敛现有 Runtime 与观测面；外部复用是加速手段，不是阻塞 MVP 的新工程。

---

## 2. 复用原则

### 2.1 四档复用方式

| 档位 | 方式 | 适用条件 | 代价 |
|---|---|---|---|
| **A 直接复用 / 小范围 vendor** | 复制或改编进 `src/trimum_core/`，保留来源与许可证 | 许可证兼容、代码量小、能隔离测试、不会引入新常驻服务 | 需要维护分叉、跟随上游修复 |
| **B 可选外部工具 / MCP** | 作为用户自装的二进制、MCP Server 或 CLI 调用 | 语言/依赖不同，但接口稳定、可替换 | 不是默认能力；需要检测与降级 |
| **C 只复用设计** | 参考事件 schema、策略模型、调度思路，自己实现 | 依赖过重、权限过大、项目不成熟 | 不能声称「已复用代码」 |
| **D 不采用** | 明确不进入主线 | 许可证不兼容、需要额外 root、维护成本高 | 可能重复造轮子，但边界更安全 |

### 2.2 硬约束

- **不为复用引入第二套运行时**：不新增常驻 daemon、不把 Rust 工具链设为安装依赖、不把外部项目整体塞进核心。
- **不为复用放宽权限**：第三方组件仍须经过 Tool Gateway、沙箱、最小权限与审计；helper 不因复用获得新 capability。
- **不把「设计参考」写成「已复用」**：文档必须区分「直接复用代码」「可选外部工具」「仅参考设计」。
- **许可证可追溯**：第三方代码必须记录来源仓库、commit、许可证、修改点；新增依赖必须说明为什么不能自己实现。
- **失败不降级**：外部工具不可用时只降能力/观测，不降低安全闸门，也不静默放行。

### 2.3 依赖预算

以下情况默认不进入核心运行时：

- 需要 Rust / Node / Go 工具链才能构建的核心路径。
- 需要 root 常驻、额外内核模块或 `CAP_SYS_ADMIN` 的组件。
- 会启动新的长期后台进程、容器运行时或数据库服务的组件。
- 只为一个小功能引入大型框架，或引入维护不活跃、许可证不清晰的代码。

确需引入时，优先顺序是：**小范围 Python 源码 vendor > 可选外部二进制/MCP > 新增 Python 依赖 > 新增非 Python 运行时**。

---

## 3. 项目矩阵

> 调研时间：2026-11-11。星标、活跃度与许可证信息会变化；正式复用前以当时的 `LICENSE`、`pyproject.toml` / `Cargo.toml`
> 和上游 commit 为准。

| 项目 | 现状 / 技术栈 | 许可证 | 与 trimum 的匹配度 | 复用方式 | 具体复用点 | 主要风险 |
|---|---|---|---|---|---|---|
| **AgentCgroup** | 活跃；Python daemon + bash wrapper + eBPF + cgroup v2；kernel 6.12+；依赖 clang/gcc/make/libbpf-dev/libelf-dev | **GPL-2.0** | **最高**：同语言、同 cgroup 路线、同 Agent 资源控制问题 | **A 第一优先，小范围 vendor** | `agentcgroupd.py` 的 cgroup 层级与 session 生命周期；`bash_wrapper.sh` 的 tool-call 级临时 cgroup；`AGENT_RESOURCE_HINT`；OOM 时向 stderr 注入反馈；`memcg_controller.py` 的 cgroup v2 fallback；JSONL metrics | GPL 版本需核对 `only` / `or-later`；`memcg_bpf_ops` 不保证在 7.0 主线；不能整体带入 daemon |
| **SchedCP** | experimental / WIP；Rust；kernel 6.12+；sched_ext | MIT | 中：调度器选择与 workload profiling 有参考价值 | **B 可选外部工具 / MCP** | `list_schedulers` / `run_scheduler` / `system_monitor` / `workload` 的工具面；调度器选择与历史记录 | 项目未稳定；需要 Rust + scx 工具链；不作为默认依赖 |
| **AgentSight** | 活跃；Rust + eBPF；local-first | MIT | 中：Agent 行为观测与事件关联 | **B 可选外部观测工具** | prompt / model / tool / file / network 关联视图；`top` / `vis` 展示；事件 schema | 需要外部二进制；不嵌入核心；观测失败不能影响业务 |
| **ActPlane** | 活跃；Rust + eBPF LSM | MIT | 低：策略思路有参考价值，但权限模型冲突 | **C 仅设计参考 / 不采用运行时** | 信息流约束、进程血缘、BPF-LSM `block` / `notify` / `kill`、拒绝原因回灌 | 需要 root 或 `CAP_BPF` + `CAP_SYS_ADMIN`；与最小权限红线冲突 |

---

## 4. AgentCgroup：第一优先复用对象

### 4.1 为什么是它

AgentCgroup 解决的是「每次 tool call 都是一个新的资源控制单元」这个问题，和 trimum 的 Agent Runtime
资源模型高度重合：

- Agent / session 有层级，不能只对一个长期进程做粗粒度限制。
- 每次 tool call 可能启动短命子进程，需要在调用边界创建/回收 cgroup。
- Agent 需要把资源需求上送给系统，系统需要在 OOM 或越限时把原因回传给 Agent。
- cgroup v2 与 eBPF 的组合能提供比单纯 `psutil` 更硬的边界。

### 4.2 可复用模块

| 上游模块 / 机制 | 可复用内容 | 建议落点 | 复用方式 |
|---|---|---|---|
| `agentcgroupd.py` | cgroup 层级、session high/low、生命周期 | `resource_controller.py` / 新的 Resource Manager 适配层 | 抽取小模块，不复制整 daemon |
| `bash_wrapper.sh` | 每次 tool call 的临时 cgroup 包裹 | `sandbox_exec.py` / Tool dispatcher 的进程启动收口 | 改编为 Python 调用，保留失败 fail-closed |
| `AGENT_RESOURCE_HINT` | Agent → System 的资源需求上送 | Plan schema 的 `resources` / RuntimeKernel 预检 | 作为字段与校验规则参考 |
| OOM stderr 反馈 | System → Agent 的自然语言失败原因 | Tool 返回 / Agent 运行时错误 | 复用文案结构，接现有审计 |
| `memcg_controller.py` | cgroup v2 `memory.high` / `memory.max` fallback | `resource_controller.py` | 优先复用 fallback；BPF 路径单独验证 |
| `scx_flatcg` | sched_ext CPU 调度器 | System Intelligence 的调度策略候选 | 先作为外部调度器 PoC，不直接塞进核心 |
| JSONL metrics | 资源与控制事件记录 | Event Bus / `trm status` / 审计 | 复用 schema，写入仍走 trimum 自己的持久化 |

### 4.3 不直接搬的部分

- 不整体复制 `agentcgroupd` 并让它成为第二个常驻服务；trimum 的 daemon 仍是唯一控制面。
- 不把 AgentCgroup 的权限模型直接照搬；所有资源操作仍要经过 RuntimeKernel / Tool Gateway / 最小权限组件。
- 不在没有测试与回滚的情况下启用 `memcg_bpf_ops`；先确认 Linux 7.0 的实际支持情况。
- 不把其 bash wrapper 作为唯一执行通道；trimum 的进程启动仍要收口到 `sandbox_exec.py`。

### 4.4 落地顺序

1. **先做许可证与来源审计**：确认 AgentCgroup `LICENSE` 是 `GPL-2.0-only` 还是 `GPL-2.0-or-later`，
   记录上游 commit，建立 `third_party/agentcgroup/` 的来源说明与许可证副本。
2. **先复用 cgroup v2 fallback**：不依赖 `memcg_bpf_ops`，先接 `memory.high` / `memory.max` 与 CPU 配额。
3. **再接 tool-call 级临时 cgroup**：只改进程启动收口，不改变 Tool Gateway 语义。
4. **最后评估 sched_ext / memcg BPF**：在内核 7.0 上做能力自检与最小 PoC，通过后才进入可选策略。

---

## 5. SchedCP / AgentSight / ActPlane 的边界

### 5.1 SchedCP

- **不嵌入核心**：Rust + scx 工具链会增加构建与部署面，且项目仍是 experimental。
- **可选外部工具**：如果用户自己安装了 SchedCP，可以由 trimum 通过 MCP / CLI 适配器发现，而不是默认启动。
- **可借鉴**：workload profiling、scheduler selection、执行状态与历史记录；这些可以进入 trimum 的 Policy Repository 设计。

### 5.2 AgentSight

- **不嵌入核心**：Rust + eBPF 二进制的构建、升级与权限面不适合作为默认依赖。
- **可选外部观测器**：适合做「深度诊断模式」，由用户显式启用；常规观测仍走 trimum 自己的 eBPF 事件与 SystemMonitor。
- **可借鉴**：prompt / model / tool / file / network 的关联事件 schema 与展示方式。

### 5.3 ActPlane

- **只作设计参考**：信息流约束、进程血缘、BPF-LSM 拒绝与回灌都值得借鉴。
- **不采用其运行时**：需要 root 或 `CAP_BPF` + `CAP_SYS_ADMIN`，会破坏 trimum 的最小权限边界。
- 如果未来要采用 BPF-LSM，必须先设计独立的最小权限控制器与人工审批链，不能直接把 ActPlane 装进 helper。

---

## 6. Linux 7.0 前置检查

升级内核只是打开评估窗口，不等于所有能力自动可用。升级后先跑以下检查，结果写回文档与 `trm doctor`：

| 能力 | 要确认什么 | 不满足时 |
|---|---|---|
| **sched_ext** | `CONFIG_SCHED_CLASS_EXT=y`；能否加载最小调度器；加载需要哪些 capability | 只保留外部可选工具，不进入核心 |
| **BPF LSM** | `CONFIG_BPF_LSM=y`；LSM hook 是否启用；attach 权限 | 只做观测，不做强制执行 |
| **memcg BPF** | `memcg_bpf_ops` 是否在 7.0 主线；能否加载 `memcg_priority` | 使用 cgroup v2 `memory.high` / `memory.max` fallback |
| **perf / tracepoint** | `perf_event_paranoid` 与 `CONFIG_SECURITY_PERF_EVENTS_RESTRICT` 的实际组合 | 保留 `perf_event_paranoid=3` 方案或纯 `bpf(2)` 后备 |
| **Landlock ABI** | 实际 ABI 与可用访问位 | 按 ABI 而不是内核版本判断能力 |

硬约束：**不为通过检查而放宽 `trimum-bpf-helper` 的 capability、`SystemCallFilter` 或 uid 门**。

---

## 7. 分阶段落地

| 阶段 | 内容 | 是否阻塞 MVP |
|---|---|---|
| **P0 记录与审计** | 本文、许可证变更、上游来源与版本记录 | 否；先完成文档 |
| **P1 cgroup v2 复用** | AgentCgroup 的 cgroup fallback、tool-call cgroup、hint / OOM 反馈 | 否；随 R1 Resource Manager 收敛 |
| **P2 可选外部工具** | SchedCP / AgentSight 的 MCP / CLI 适配器 | 否；用户显式启用 |
| **P3 sched_ext / memcg BPF** | Linux 7.0 能力检查、最小 PoC、策略仓库准入 | 否；MVP 稳定后再做 |

**MVP 优先级**：R1（Runtime 收敛）与 R2（观测基线）先跑通；复用工作不得把主线拖入新语言、新服务或新权限模型。

---

## 8. 引入检查清单

引入任何外部代码前，至少回答：

- [ ] 许可证是否与 GPL-2.0-only 兼容？是否需要保留版权、许可证与修改说明？
- [ ] 上游 commit / 版本是否固定？是否有来源记录？
- [ ] 是否引入新的常驻进程、非 Python 工具链或 root 权限？
- [ ] 是否有独立测试与回滚方案？
- [ ] 是否绕过 Tool Gateway / 沙箱 / 审计？
- [ ] 失败时是否只降能力/观测，而不是降安全？
- [ ] 是否真的比自研更省维护成本？如果只是一个小组件，能否直接复用而不是引入整个项目？

---

## 9. 当前结论

> **复用优先，但不整体吞并。**
> AgentCgroup 先复用小模块；SchedCP / AgentSight 作为可选外部工具；ActPlane 只作设计参考。
> Linux 7.0 打开 sched_ext / BPF LSM / memcg 的评估窗口，但 MVP 仍然先做 Runtime 与观测基线。
