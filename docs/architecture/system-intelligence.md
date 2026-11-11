# System Intelligence 详细设计

> 归属：`docs/ARCH.md` §4。
> 本文描述 System Intelligence 的观测、分析、策略、验证与受控执行；明确区分「已实现」与「未来设计」。
> 状态记号：✅ 已实现　🟡 部分实现　⚪ 未来设计（TBD）　🚫 已废弃

---

## 1. 目标与边界

System Intelligence 的目标：让 AI 不只是调用操作系统接口，而是能理解系统运行状态，并在安全约束下辅助优化操作系统。

它包含两件事：

1. **Observation**：知道系统正在发生什么。
2. **Enforcement**：在验证之后，受控地改变系统行为。

**边界（硬约束）**：

- **LLM 推理不进入内核执行路径**。AI 分析与策略决策在用户态完成。
- **AI 不直接拥有任意内核控制权限**。内核侧只执行经过验证的有限程序；下发由受控特权组件完成。
- **未实现的强制执行不写成已实现**。当前只有 cgroup 资源控制与 eBPF 观测链路；BPF LSM / sched_ext 是未来设计。

---

## 2. 总体结构

```mermaid
flowchart TB
    subgraph Kernel[Linux Kernel]
        TP[tracepoints / perf events]
        CGRP[cgroup v2]
        LSM[BPF LSM / sched_ext<br/>Future]
    end

    subgraph Observe[Observation]
        BPF[eBPF programs<br/>bpf_guard / exec_guard]
        RB[ring buffer]
        HELPER[trimum-bpf-helper<br/>CAP_BPF + CAP_PERFMON]
        ALERT[bpf-alerts.jsonl]
        AUD[eBPF 审计 / Event Bus]
        SYS[SystemMonitor<br/>CPU / RAM / Disk / Load]
    end

    subgraph Analyze[Analysis]
        WA[Workload Analysis Engine<br/>Future]
        REPO[Policy Repository<br/>Future]
        PE[Policy Engine<br/>Future]
    end

    subgraph Verify[Verification]
        KV[Kernel Verifier]
        HASH[sha256 / manifest]
        STATIC[Static Analysis<br/>Future]
        BENCH[Benchmark / Isolation Test<br/>Future]
        ROLLBACK[Runtime Monitor / Rollback<br/>Future]
    end

    subgraph Control[Controlled Enforcement]
        PC[Privileged Controller<br/>bpf helper now / generic controller Future]
        CGC[cgroup controller<br/>✅]
    end

    TP --> BPF --> RB --> HELPER --> ALERT --> AUD
    CGRP --> SYS
    AUD --> WA
    SYS --> WA
    WA --> PE
    REPO <--> PE
    PE --> KV
    PE --> HASH
    PE --> STATIC
    PE --> BENCH
    KV --> ROLLBACK
    HASH --> ROLLBACK
    STATIC --> ROLLBACK
    BENCH --> ROLLBACK
    ROLLBACK --> PC
    PC --> BPF
    PC --> LSM
    PE --> CGC --> CGRP
```

---

## 3. eBPF Observation / Enforcement

### 3.1 Observation（✅ 部分实现）

目标观测面：

- CPU、内存和 IO 负载。
- 进程与线程行为。
- 系统调用和资源访问。
- 网络活动。
- Agent 和 Tool 的执行行为。
- 系统性能事件。

当前已实现：

| 组件 | 作用 | 落点 |
|---|---|---|
| `bpf_guard.bpf.c` | 观测 `sys_enter_bpf`，记录 eBPF 相关系统调用行为 | `bpf/bpf_guard.bpf.c` |
| `exec_guard.bpf.c` | 观测 `sys_enter_execve`，记录进程执行 | `bpf/exec_guard.bpf.c` |
| 事件结构 | `struct trimum_bpf_event`，kind：`prog_load` / `bpf_attach` / `bpf_detach` / `map_write` / `exec` | `bpf/trimum_bpf.h` |
| 特权 helper | 加载 / 卸载 / 统计 / 读取事件；只接受四个动词 | `bpf_helper.py` / `bpf_helper_main.py` / `bpf_helper_protocol.py` |
| 真 loader | libbpf（ctypes）加载 `.o`，ring buffer 排水 | `bpf_loader.py` |
| daemon 侧审计 | 读回灌 JSONL → `security.ebpf_alert` | `bpf_audit.py` |
| 系统指标 | CPU / 内存 / 磁盘 / load 阈值告警 | `system_monitor.py` |

链路：

```text
bpf/*.bpf.c
  → clang 现场编译 .bpf.o（部署时 --apply）
  → trimum-bpf-helper（CAP_BPF + CAP_PERFMON，uid 门，sha256 校验）
  → ring buffer
  → /run/trimum-bpf/bpf-alerts.jsonl
  → bpf_audit.BpfAlertPoller
  → Event Bus `security.ebpf_alert` + 审计
```

**helper 的安全约束**（详见 `docs/SANDBOX-PLAN.md` §6.7）：

- 只有 `bpf.load` / `bpf.unload` / `bpf.stats` / `bpf.tail` 四个动词，**没有命令面**。
- 程序名只能取枚举值；不接受任意路径或命令字符串。
- 只加载清单登记且 sha256 对得上的 `/opt/trimum/bpf/<name>.bpf.o`。
- `CAP_BPF` + `CAP_PERFMON`，不给 `CAP_SYS_ADMIN`。
- 不监听网络、不 fork/exec、不接受 fd 传递。
- 失败一律 `ok:false`，不静默降级。

**已知约束**：

- Ubuntu 的 `CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y` + `kernel.perf_event_paranoid >= 4` 时，
  `perf_event_open(2)` 需要 `CAP_SYS_ADMIN`；当前方案是把 `perf_event_paranoid` 降到 `3`
  （`/etc/sysctl.d/60-trimum-perf.conf`），**不给 helper 加 `CAP_SYS_ADMIN`**。
- `EACCES(13)` 表示内核 perf 策略拦截；`EPERM(1)` 表示 seccomp 拦截。诊断时先分这两个错误码。

### 3.2 Enforcement（🟡 部分实现，未来扩展）

目标方向：

- cgroup 资源控制：✅ 已通过 `resource_controller.CgroupV2Controller` 落地。
- BPF LSM 安全策略：⚪ 未来设计。
- sched_ext 调度机制：⚪ 未来设计。
- 与其他内核控制接口协作：⚪ TBD。

**原则**：eBPF 不只是传感器，也可以参与受控的系统行为管理；但任何强制执行都必须经过
Policy Engine → Execution Verifier → Privileged Controller 这条链，不能由模型直接下发。

---

## 4. Workload Analysis Engine（⚪ Future Design）

### 4.1 输入

- cgroup / psutil 资源指标：CPU、RAM、IO、文件写入、网络请求。
- eBPF 事件：exec、bpf 系统调用、未来的 syscall / 网络事件。
- 审计与 Event Bus：Agent / Tool 执行记录、失败、审批、威胁事件。
- SystemMonitor 阈值告警与历史采样。

### 4.2 输出

建议的输出结构（TBD，仅示意，不是已冻结契约）：

```yaml
workload:
  id: <agent-or-workflow-id>
  class: coding | shell | browser | mcp | batch | unknown
  phase: startup | steady | burst | idle
  resources:
    cpu: {usage, pressure, trend}
    memory: {usage, pressure, trend}
    io: {read, write, pressure}
    network: {requests, bytes}
  bottlenecks: [cpu | memory | io | network | lock | unknown]
  confidence: 0.0-1.0
  evidence: [<metric/event ids>]
```

### 4.3 职责

- 识别工作负载类型与阶段。
- 发现资源竞争和性能瓶颈。
- 为 Policy Engine 提供系统状态依据。
- 不做权限裁决，不直接改系统。

### 4.4 当前状态

没有统一引擎。`system_monitor.py` 只做阈值告警；`resource_controller.py` 只做采样与限额；
`behavior_monitor.py` / `learning_engine.py` 是**安全行为**基线，不是工作负载分类器。

---

## 5. Policy Repository（⚪ Future Design）

### 5.1 目标

沉淀可复用的系统策略，避免每次都让模型从零生成：

- 已有调度策略。
- eBPF 程序和调度器。
- 工作负载特征。
- 策略适用条件。
- 历史执行结果。
- 性能测试数据。

### 5.2 建议条目结构（TBD）

```yaml
id: sched.burst.coding.v1
kind: scheduler | ebpf_program | cgroup_profile | lsm_policy
applies_to:
  workload_class: coding
  phase: burst
  kernel: ">=6.8"
  prerequisites: [cgroup_v2, bpf_perfmon]
program:
  source: bpf/xxx.bpf.c
  sha256: <hash>
params:
  cpu_weight: ...
evidence:
  benchmark: <result id>
  history: [<run ids>]
provenance:
  author: human | ai-assisted
  verified_by: <verifier run id>
  created_at: <date>
```

### 5.3 原则

- **复用优先**：先查仓库，再调整参数，最后才考虑生成新策略。
- **来源可追溯**：每条策略记录作者、验证记录、适用条件与历史结果。
- **不把仓库当垃圾场**：验证失败或长期无收益的策略应标记 / 淘汰（机制 TBD）。

### 5.4 当前状态

现有 `config/policy.yaml`、威胁剧本、eBPF 程序清单是**前身**，不是完整策略仓库。

---

## 6. Policy Engine（⚪ Future Design）

职责：

- 根据工作负载分析选择策略。
- 调整已有策略参数。
- 必要时修改或组合已有策略。
- 在适当情况下生成新策略。
- 根据系统反馈进行策略优化。

**与现有 `policy_engine.py` 的区别**：

| 名称 | 作用域 | 现状 |
|---|---|---|
| `policy_engine.py` | Agent Runtime 安全策略：allow / confirm / deny | ✅ 已实现 |
| System Intelligence Policy Engine | 系统调度 / 资源 / eBPF 策略选择 | ⚪ Future |

两者不要混名。本文的 Policy Engine 不直接执行系统操作，只产出「候选策略 + 参数 + 理由 + 证据」。

---

## 7. Execution Verifier

### 7.1 职责

- eBPF Verifier 检查。
- 静态分析。
- 运行前验证。
- 隔离环境测试。
- 性能基准测试。
- 部署前策略检查。
- 运行时监控。
- 异常熔断和策略回滚。

### 7.2 硬约束

- AI 生成的内核策略**绝不能未经验证直接部署**。
- 验证失败一律拒绝；不因为「看起来没问题」放行。
- 验证记录必须可追溯（策略 ID、程序 sha256、测试环境、结果）。

### 7.3 当前状态

| 能力 | 状态 | 说明 |
|---|---|---|
| 内核 eBPF verifier | ✅ | 由内核执行；加载失败即拒绝 |
| 程序 sha256 清单校验 | ✅ | `bpf_helper_protocol` / `apply_ebpf1e.sh` |
| uid 门与能力最小化 | ✅ | `SO_PEERCRED` + `CAP_BPF/CAP_PERFMON` |
| 沙箱隔离测试 | ✅ | Landlock / seccomp / cgroup |
| 静态分析 | ⚪ | 没有专门的分析管线 |
| 性能基准 | ⚪ | 没有自动基准框架 |
| 运行时熔断 / 自动回滚 | ⚪ | 只有失败拒绝与人工回滚脚本 |

---

## 8. Privileged Controller

### 8.1 原则

- AI 不直接拥有任意内核控制权限。
- 由受控的用户态特权组件执行**有限的、经过授权的**系统操作。
- 控制器不接受命令字符串，只接受白名单动词与受限参数。
- 控制器失败必须显式返回，不静默降级。

### 8.2 当前实现：trimum-bpf-helper（🟡）

- 动词：`bpf.load` / `bpf.unload` / `bpf.stats` / `bpf.tail`。
- 能力：`CAP_BPF` + `CAP_PERFMON`，无 `CAP_SYS_ADMIN`。
- 认证：Unix socket + `SO_PEERCRED` + 白名单 uid。
- 程序来源：`/opt/trimum/bpf/<枚举名>.bpf.o`，sha256 清单校验。
- 运行目录：`/run/trimum-bpf`（与 `trmd` 的 `/run/trimum` 分离）。
- 数据流：单向回灌到 JSONL，daemon 侧审计。

它**不是**通用内核控制器：不能执行任意 eBPF 程序、不能写任意内核参数、不能代替 root。

### 8.3 未来扩展（⚪）

- 是否扩展 helper 支持更多受控动词（如 sched_ext 相关操作）。
- 是否另起一个独立 controller（按策略类型分权）。
- 如何做到「能力最小化 + 可审计 + 可回滚」。

这些都需要单独裁决，不在本文擅自定案。

---

## 9. 反馈闭环

```mermaid
sequenceDiagram
    participant AR as Agent Runtime
    participant K as Linux Kernel
    participant O as eBPF / SystemMonitor
    participant A as Workload Analysis
    participant P as Policy Engine
    participant V as Execution Verifier
    participant C as Privileged Controller

    AR->>K: Agent / Tool 执行
    K-->>O: 事件 / 资源指标
    O-->>A: 观测数据
    A->>P: 工作负载分类 / 瓶颈 / 资源竞争
    P->>P: 查询 Policy Repository，选择或调整策略
    P->>V: 候选策略 + 参数 + 证据
    V->>V: 静态分析 / 隔离测试 / 基准
    V->>C: 验证通过的有限操作
    C->>K: 受控部署（cgroup / eBPF / Future LSM）
    K-->>AR: 系统状态变化
    A-->>AR: 资源与执行策略建议
```

闭环的三个共同维度：

1. **资源管理**：Runtime 提需求，System Intelligence 观察全局竞争并建议调整。
2. **安全治理**：Runtime 管沙箱与工具权限，System Intelligence 管系统级策略与受控执行。
3. **动态控制**：Runtime 根据反馈调整后续任务的资源需求与执行方式。

---

## 10. 当前实现边界（汇总）

| 能力 | 状态 | 备注 |
|---|---|---|
| eBPF 观测链路 | ✅ | helper + loader + 审计回灌，真机已跑通 |
| cgroup 资源控制 | ✅ | Agent 级预算 |
| SystemMonitor 阈值告警 | ✅ | CPU / 内存 / 磁盘 / load |
| 工作负载分类 / 瓶颈分析 | ⚪ | 无统一引擎 |
| Policy Repository | ⚪ | 零散策略文件 |
| 调度策略选择 / 参数调整 / 生成 | ⚪ | 无实现 |
| 静态分析 / 基准 / 自动回滚 | ⚪ | 无实现 |
| BPF LSM / sched_ext | ⚪ | 无实现 |
| 通用 Privileged Controller | ⚪ | 只有受限 bpf helper |

---

## 11. TBD / 待决策

1. 工作负载分析的输入/输出 schema 与采样频率。
2. 指标来源优先级：eBPF、cgroup、psutil、审计事件如何合并。
3. Policy Repository 的存储形态、版本、签名与淘汰机制。
4. Policy Engine 允许「生成新策略」的边界与人工审批点。
5. Execution Verifier 的验证等级与准入清单。
6. Privileged Controller 的通用化边界与分权模型。
7. 运行时熔断、回滚与人工接管流程。
8. 如何避免观测开销影响业务（采样、聚合、背压）。

---

## 12. 一句话

> System Intelligence 不是「让 AI 直接改内核」，而是「让 AI 在可观测、可验证、可回滚的约束下，
> 辅助系统做出更好的资源与执行决策」。
