# 沙箱范围（Sandbox Scope）：三层配置 + 权限交集（2026-09-28 设计定稿；**S6① 已闭环 `723d521`**、**S6② 已闭环 `cb3514a`**，其余待做见 §7）

> 本文回答一个问题：**「哪些 Agent 能读写哪些文件、能用多少资源」这份口径写在哪、谁能改、多层冲突时听谁的。**
> 与 `docs/SANDBOX-PLAN.md` 的分工：那篇讲**机制怎么落地**（S1–S5 真机实测、Landlock/seccomp/cgroup 的能力边界），
> 本文讲**配置怎么组织**。机制事实一律以那篇为准，本文不重复。
> 实现分片见 §7；接线时机与 E7 第 4 片后半（`agent_launcher`）绑在一起，因为那片正好要消费 `limits`。

---

## 1. 问题：不同 Agent 能力不同，不能一概而论；但也不能全塞一个文件

三条同时成立、且互相拉扯的诉求：

1. **子 Agent 必须最小权限** —— 它只该做被派的那一件事，多一点能力都不给。
2. **每个 Agent 的能力本来就不同** —— 只读审阅类不需要写面；跑构建的必须写工作区 + `~/.cache`；
   处理未知第三方包的应该连网络一起掐。
3. **配置得能改、能审、能解释** —— 出了事要能回答「这次执行到底被允许了什么、这条是谁定的」。

结论：**不是二选一，而是分层 + 取交集。** 三层各管一件事，冲突时**更严者胜**（交集，永不做并集）；
且这层设计**不是为了多几个开关**，而是为了让「谁有权放宽」这件事有唯一答案。

---

## 2. 唯一口径：三层 + 交集

| 层 | 载体 | 谁写 | 作用 | 能不能放宽 |
|---|---|---|---|---|
| **L1 地板** | `~/.trimum/security.yaml` 的 `sandbox:` / `defaults:` / `agents.<name>` | 运营者（这台机器的主人） | 全局默认 + 红线（如「任何 Agent 都不许写 `/etc`」）+ 对个别 Agent 的**收紧例外** | **可以**（它是最终地板；但只有运营者能写） |
| **L2 自述** | Agent 随包走的 `sandbox:` 段（manifest / `agent.yaml`） | Agent 作者（第三方包／内置 Agent） | 声明「我至少需要读什么、能跑什么 syscall、要多少资源」 | **不可以** —— 只能比 L1/父级**更严** |
| **L3 运行时** | 环境变量（`TRIMUM_SANDBOX*` / `TRIMUM_SECCOMP`）、调用参数、派单请求 | 使用者 / 父 Agent | 一次性的收紧（排障、临时只读跑一遍） | 只收紧 |

**生效范围 = L1 ∩ L2 ∩ L3，逐维度取严，永不取并。**

**子 Agent = L1 ∩ 父 ∩ 子**（子只能更小）。两个必须写进代码的默认值：

* **默认继承父**，不是「自己一套默认」 —— 否则以后新加 Agent 忘写配置时，要么意外变宽、要么直接全拒（两种都是事故）。
* **交集算不出来就拒**，不放行 —— 口径与 `delegation.py` 现有实现一致（能力／风险／预算已经这么做）。

---

## 3. 两种 Agent 形态：配置从哪来

这一点决定了「每个 Agent 一份配置」怎么落地 —— **不能只靠静态文件**。

### 3.1 具名 Agent（装进来的 / 内置的）

有 manifest ⇒ **自己那份配置随 Agent 走**，写在它自己的 `sandbox:` 段里。
`~/.trimum/security.yaml` **不复制它的配置**，只负责地板与收紧例外。

理由：包的自述能力属于分发物的一部分（换了机器、换了用户都在包里）；中央文件每加一个 Agent 就要改一次，
既违背分发逻辑，也让「这个包到底要什么权限」在安装时无处可见。

### 3.2 运行时派生的子 Agent（E7 编码智能体那一类）

**没有静态文件可写** —— 它是父 Agent 现场派出来的。所以它的范围由**父在派单时声明**，
再与父的能力取交集；**不落盘、不生成 `agent.yaml`**。

这条路径的骨架已经有了：`src/trimum_core/delegation.py` 头部即写「派单前先做权限交集
（子能力 = 父能力 ∩ 请求，只收紧不放宽）+ 预算（步数 / token，父是上限）；交集读不出来或越权 ⇒ 直接拒，
不启动、不发事件」，`Budget.tighten()`（`:75`）就是取 min 的那半边。

**缺口**：能力／风险／预算已进交集，**沙箱范围（路径面 + cgroup 限额）还没进**。这是 §7 要补的。

---

## 4. 配置键（三处，语义与单位统一）

### 4.1 L1 全局地板 `~/.trimum/security.yaml`

```yaml
defaults:
  mode: balanced                 # 安全等级（regex | balanced | sandbox）—— 与沙箱档位是两回事，见 §4.4

sandbox:
  mode: workspace-write          # off | readonly | workspace-write | strict
  fail_closed: true              # 施加失败是否拒绝执行（false ⇒ 降级并记 <mode>:degraded）
  read_paths: []                 # 追加读根（默认已含："/"、工作区、~/.trimum、数据目录、设备面）
  write_paths: []                # 追加写根（默认已含：工作区、/tmp、/var/tmp、~/.trimum、socket 目录）
  deny_write: []                 # ⚠️ **尚未实现**（Landlock 是加法语义，见 §5.1）：写进配置会被 `trm sandbox check` 报 `unknown_key`
  seccomp: l1                    # l1 | strict | off
  seccomp_allow: []              # 白名单模式（仅 strict 档生效）
  seccomp_block: []              # 追加拦截（任何档都生效）

limits:                          # 全局上限（子 Agent 不得越过）
  memory_max: 1GiB
  memory_swap_max: 0             # 必须与 memory_max 成对，否则灌内存照样成功（SANDBOX-PLAN §9 实测）
  cpu_quota_percent: 100
  tasks_max: 128
  # ⚠️ 下面四个键**尚未实现**（§4.4 标 ❌）：等做到再加进默认配置 ——
  #    不生效的字段写进配置文件，比没有更坏。
  io_read_bps: 0                 # 0 = 不限；仅 systemd 档生效，且是**块设备**粒度（§5.2）
  io_write_bps: 0
  file_size_max: 0               # 单文件大小上限（LimitFSIZE），仅 systemd 档
  open_files_max: 4096           # LimitNOFILE，仅 systemd 档

agents:                          # 逐 Agent 覆盖（可选）；只用于**收紧**，不放宽
  download-manager:
    sandbox: { mode: strict, seccomp: strict }
    limits:  { memory_max: 256MiB, cpu_quota_percent: 25 }
    # allow_write: [~/Downloads]   # S6③（`960a050`）：包 manifest 声明的 write 只有在这里
                                   # 被运营者显式点名授权才生效（取交集，单向）
```

### 4.2 L2 Agent 自述

```yaml
# 随 Agent 走：agents/<name>/agent.yaml（或 manifest 的 sandbox: 段）
sandbox:
  mode: readonly                 # 只能比上一层更严（rank 更小才采用）
  read: ["${WORKSPACE}"]         # 声明式读面
  # write: [...]                 # ⚠️ 现状：**被完全忽略**（见 §5.3），要开口子得先做 §7-S6③
  seccomp: strict
limits:
  memory_max: 512MiB
  cpu_quota_percent: 50
  tasks_max: 32
```

### 4.3 L3 派单声明（子 Agent 用，Python 侧）

```python
SubAgentRequest(
    ...,
    sandbox=SandboxAsk(mode="readonly", write=[], limits=Limits(memory_max_bytes=512 << 20)),
)
```

与 `delegation.py` 现有 `capabilities` / `budget` 同构：**声明的是「我需要什么」，不是「我允许什么」**，
最终由交集裁决；交集为空 ⇒ 拒单。

### 4.4 一张表说清每个键落到哪个机制

| 键 | 落到的机制 | 现状 |
|---|---|---|
| `sandbox.mode` | Landlock（`sandbox_exec.py`，preexec 钩子） | ✅ 已实现 |
| `sandbox.read_paths` / `write_paths` | Landlock 规则（按路径发放 read/write/make 权） | ✅ 已实现 |
| `sandbox.seccomp` / `seccomp_allow` / `seccomp_block` | seccomp-BPF（`seccomp_exec.py`，与 Landlock 同一 preexec） | ✅ 已实现 |
| `sandbox.fail_closed` | 施加失败时是报错还是降级 | ✅ 已实现 |
| `limits.*`（内存/CPU/进程数） | systemd-run `-p MemoryMax / MemorySwapMax / CPUQuota / TasksMax` | ⚠️ 计算与单测已有（`sandbox_limits.py`），**未接线** |
| `limits.io_*` / `file_size_max` / `open_files_max` | systemd `IOReadBandwidthMax` / `LimitFSIZE` / `LimitNOFILE` | ❌ 未实现 |
| 网络范围 | seccomp `strict` 按地址族挡（AF_UNIX 放行） | ⚠️ 仅地址族粒度；域名/IP 白名单属 HttpDispatcher 那层 |
| 文件监视 | —— | ❌ 无机制（需 fanotify/inotify 或 eBPF，属 S5-①「未做/需单独裁决」） |

> **注意 `level` 与 `mode` 是两套东西**：`defaults.mode`（`regex|balanced|sandbox`，`security_config.py:158`）
> 决定**策略引擎／LLM 判定／资源限制要不要开**；`sandbox.mode`（`off|readonly|workspace-write|strict`）
> 决定**内核层边界**。两者都要，别混。

---

## 5. 五个必须先讲清的坑

### 5.1 Landlock 是**加法**语义，写不出「排除」

多条规则取**并集**：父目录放了写权，子目录的「只读」规则**不能**把它收回来。
所以「工作区可写、但 `.git/` 只读」这种直觉写法**表达不出来**。

要做只能反过来：**收紧父目录 + 逐个显式放开子目录**。
同理，`deny_write`（§4.1）不能靠「加一条只读规则」实现，得在**路径解析阶段就拒绝**（判定层），
而不是交给 Landlock —— 这一点在实现时必须写清楚，否则会得到一个「看起来配了、其实没生效」的开关。

### 5.2 IO 限额不是「文件级」，而且只在 systemd 档生效

systemd 给的是**块设备**带宽（`IOReadBandwidthMax=/dev/nvme0n1 100M`）与资源类上限
（`LimitFSIZE` 单文件、`LimitNOFILE` 句柄数）。**不是**「这个目录最多写 100 MB/s」。
用户极易误解，配置注释里必须写明。`unsupported` 档（无 systemd 用户会话）时**如实降级**，不假装生效。

### 5.3 现状：包的 manifest 声明 `write` 会被**静默忽略** —— ✅ 已修（S6③ `960a050`）

`sandbox_exec.py:733` 对 manifest 的 `write` / `fs_write` / `allowed_write` 只记一条
`sandbox.manifest_write_ignored` 警告，**一条都不采纳** —— 这是有意的红线（包不许给自己开写面）。

代价：像「需要写 `~/.cache/pip`」这类**正当**需求目前无处声明。所以要留一个
**运营者显式授权**才生效的口子（§7-S6③），而不是简单放开。
**该口子已落地**：`agents.<name>.allow_write: [...]`，与 manifest 声明**取交集**（单向 —— 授权本身不开任何路径），
未授权的声明走 warning + `plan.ignored` 结构化留痕。

### 5.4 单位与键名必须收敛成一套

现在有两套写法：`security.yaml` 的 `levels.*.resource_limits`（`max_memory_mb` / `max_cpu_percent` /
`max_processes`，`security_config.py:42`/`:55`）与 `sandbox_limits.Limits`（`memory_max_bytes` /
`cpu_quota_percent` / `tasks_max`，`sandbox_limits.py:41`）。
**配置里写人读单位（`512MiB`），代码里转 bytes**，只留一套键名。`levels.*` 那套**至今无人消费**。

⚠️ 补记（S6① 实测时发现，其实是**三套**）：除了上面两套，还有
**`mcp_registry.ResourceLimits`**（`max_memory_mb` / `max_cpu_percent`，MCP server 用，`mcp_registry.py:145`）。
S6① 只收敛了沙箱这一套（`sandbox_limits`）；另两套属别的子系统，未动。
S6⑤ 落地时复核的登记状态：`limits:` 那套**已自带**未知键检查（`Limits.from_mapping` 未知键直接 `ValueError`，
等效于「写了不生效」的反面）；**`mcp_registry.ResourceLimits` 仍未登记**（无未知键校验）—— 留作后续小项（见 `TODO.md`）。

### 5.5 降级必须如实，路径不存在必须能被发现

* 没有 Landlock / 没有 systemd 用户会话 ⇒ 走 `unsupported` 档，**原样降级 + 审计标记**，不假装有边界。
* 配置里的路径**不存在时现在的实现是「跳过 + debug 日志」**（`sandbox.rule_skipped_not_a_file`）——
  写错不会当场报错。所以 §7-S6④ 的 `explain` 与 S6⑤ 的校验器**不是锦上添花，是这个设计的必要条件**。
  **两件均已闭环**（`f17004c` / `126ae8c`）：`trm sandbox check` 把 security.yaml / manifest / 派单请求里的
  坏路径报成 error，`trm sandbox explain` 把每条规则的来源摊开；daemon 启动时也会跑一遍校验器（只记日志，绝不挡启动）。

### 5.6 `preexec` 与 systemd 的 fork **不是一条链**（2026-09-28 接线时踩到）

`sandbox_exec` 的 Landlock/seccomp 是 `preexec_fn`，只作用于它自己 fork 的那个子进程。
一旦把派生动作交给 `systemd-run`，那个子进程是 **systemd-run**，真正的 agent 由 `systemd --user`
**重新 fork** ⇒ **边界一条都没套上，而状态还报着 `workspace-write`/`l1`**（违反「如实降级」红线）。
修法：cgroup 档的 argv 里包一层 `python -m trimum_core.sandbox_exec …`，让「施加 → `execvp` 成 agent」
在**同一个进程**里完成（`execvp` 不改 PID ⇒ 单元主进程仍是 agent）。见 `docs/SANDBOX-PLAN.md` §13。

### 5.7 单元上的 `SystemCallFilter` 是**第二套 syscall 口径**（同日踩到）

`SystemCallFilter=@system-service` 是**白名单**，实测**不含** `seccomp(2)` 与 `landlock_*`
（§“§6.6/§12.5 别各写一套”）：单元内一装 Layer K 就被内核 `SIGSYS(31)` 打死。
⇒ 已在 `sandbox_limits.properties()` 里**撤掉**：单元只留资源属性 + `NoNewPrivileges`，
syscall 边界**唯一**由 `seccomp_exec` 的档位负责（`cb3514a`）。

---

## 6. 与现有代码的映射（改之前先读这张表）

| 关注点 | 落点 |
|---|---|
| 配置读取（内置默认 + 用户覆盖 + 深合并） | `src/trimum_core/security_config.py`（`DEFAULT_SECURITY_YAML` `:21`、`sandbox:` `:87`、`agents:` `:104`、`get_mode` `:158`） |
| 沙箱档位与 Landlock 施加 | `src/trimum_core/sandbox_exec.py`（`MODE_*` `:55`、`_MODE_RANK` `:64`、`_declared` `:472`、`_resolve_mode` `:488`、读写根拼装 `:729`） |
| seccomp 档位 | `src/trimum_core/seccomp_exec.py`（`PROFILE_*` `:55`） |
| 资源限额的纯计算 | `src/trimum_core/sandbox_limits.py`（`Limits` `:41`、`properties()` `:96`、`build_command()` `:130`） |
| 状态回写 / 展示 | `src/trimum_core/sandbox_state.py`（`trm status` 读它） |
| 派单交集 | `src/trimum_core/delegation.py`（`Budget.tighten` `:75`） |

**优先级链（代码已经这样实现，别再发明一套）**：
`内置默认 < ~/.trimum/security.yaml < 环境变量`；agent manifest **只能收紧**；
`explicit` 调用参数 > env > `security.yaml.sandbox.mode` 作为基准，manifest 在此基础上取更严者。

---

## 7. 待做：建议合成一小片 **S6「沙箱范围配置统一」**

排序意图：**S6①② 紧贴 E7 第 4 片后半**（那片要接线 `limits`，先把键名与单位定死，避免接线完再返工），
S6③④⑤ 紧随其后 —— **三片均已闭环**（`960a050` / `f17004c` / `126ae8c`，见下表）。

| 片 | 内容 | 为什么 |
|---|---|---|
| **S6①** ✅ | 键名 / 单位收敛（§5.4）：`limits:` 提出到顶层、`levels.*.resource_limits` 已删；配置用人读单位。
**已闭环 `723d521`**（`parse_size` + `Limits.from_mapping`，未知键报错）+ `5faa3e3`（注释口径修正）；目标测试 47 passed、ds 验收 PASS（含两条变异测试） | 接线前定死，不然接线一次、改配置又返工 |
| **S6②** ✅ | `limits` 接线到 `agent_launcher`（cgroup 真限额；`unsupported` 档原样降级）。**已闭环 `cb3514a`**（`run_agent`：`Limits.from_mapping(cfg.get_limits())` + `build_command` 包装 + 单元内施 Layer K；目标 69 passed、全量 15/1950/4、ds 验收 PASS + 三条变异测试） | 即 E7 第 4 片后半的第 ① 件，**不要重复做两遍** |
| **S6③** ✅ | manifest `write` 的**运营者显式授权**口子（`agents.<name>.allow_write: [...]`，仍走交集）。**已闭环 `960a050`**（`sandbox_exec` 取交集 + `security_config.get_agent_allow_write`；目标 74 passed、全量 16/1986/4 对基线逐条一致、ds 验收 PASS —— 前两轮 FAIL 是用例空转/漏报，已修） | 修 §5.3 的「正当需求无处声明」 |
| **S6④** ✅ | `trm sandbox explain <agent>`：打印**生效范围 + 每条来源**（内置 / security.yaml / env / manifest / 派单请求）+ 路径是否存在。**已闭环 `f17004c`**（`sandbox_exec.explain_scope` + `agent_registry.read_manifest`（只读、不注册）+ CLI `explain`；目标 127 passed、全量 16/2002/4，passed 增量 16 == 新增用例数、ds 验收 PASS + 四条变异全杀） | 三层叠加后没人知道到底生效了什么；Agent 一多，这比配置文件本身更重要 |
| **S6⑤** ✅ | 校验器：启动时 + `trm sandbox check` 干跑（未知名 / 不存在的路径 / 会被静默忽略的声明 一律报出来）。**已闭环 `126ae8c`**（`sandbox_exec.validate_scope`（只调 `explain_scope`、同源）+ CLI `check [--read/--write]` + `api_server` 启动时只记日志；目标 127 passed、全量 15/2018/4，passed 增量 15 == 新增用例数、ds 验收 PASS + 四条变异全杀。第 1 轮曾 FAIL：派单路径来源是死代码 + 一条用例只在开发机成立，均已修） | 修 §5.5 的「列漏 = 运行时才炸」 |

**单列、不塞进 S6**：
* **文件监视**（fanotify/inotify 或 eBPF）—— 属 S5-① 范畴，需单独裁决；**在没机制之前，禁止把它写进配置文件**（写了就是不生效的字段，比没有更坏）。
* **IO 限额**（§5.2）—— 独立小片；先想清楚「块设备粒度」对用户有没有意义，再决定做不做。

**验收口径（照 S1–S5 的老规矩）**：
1. `tests/` 只验**字符串与判定**（`Limits` / 规则树 / 来源标注），不派生进程；
2. 真跑交独立的 `scripts/accept_s6.py`（能跑给 N/0，跑不了如实说），至少覆盖：
   ① 子 Agent 声明的范围**小于**父时按子的、**大于**父时被拒；
   ② `explain` 输出的来源标注与实际施加规则**逐条对得上**；
   ③ 路径不存在 / 未知名 / 被忽略的声明**必须被校验器报出**。
3. 一次**变异测试**：把交集改成并集（或把「默认继承父」改成「自己一套默认」），验收必须失败 —— 否则等于没测。

---

## 8. 反例：这几种写法不要

```yaml
# ❌ 把每个 Agent 的全部配置堆进 security.yaml —— 每加一个 Agent 就要改中央文件，
#    而且「这个包要什么权限」在安装时看不见
agents:
  agent-a: { mode: workspace-write, write_paths: [...], seccomp: l1, limits: {...} }
  agent-b: { ... }

# ❌ 让 manifest 自己声明 write / mode: off —— 包给自己开权限，红线

# ❌ 写「工作区可写，但 .git 只读」 —— Landlock 加法语义做不到（§5.1）

# ❌ 把「监视窗口」当成现成能力写进配置 —— 没有机制（§7 单列）
```

---

## 9. 一页速记

1. **三层**：运营者地板（security.yaml）∩ Agent 自述（随包走）∩ 运行时（env/派单），**更严者胜**。
2. **子 Agent = 全局 ∩ 父 ∩ 子**；默认继承父；交集算不出来就拒。
3. **具名 Agent 的配置随包走，不进 security.yaml**；派生的子 Agent 不落文件，由父在派单时声明。
4. 每加一个开关，先回答「谁来放宽」与「怎么解释生效范围」——解释不了就别加。
