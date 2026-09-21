# 沙箱方案（Phase 4 前置）：调研 + 真机实测 + 设计（2026-09-21）

> 站位的由来：裁决项「**沙箱是否提到编码智能体（E7）之前**」已定为 **是** —— 编码智能体会大量写盘、跑测试，
> 没有内核级边界就不敢让它自己动手。因此本文是 E7 的**前置片**。
> 本文回答四问：① 现在主流的沙箱是怎么做的；② 需不需要 Docker；③ 真机还需要装什么；④ 怎么落到 trimum 既有的网关体系里。
> 与既有文档的关系：威胁模型与 seccomp/Landlock 分层设计见 `docs/SECURITY-DEFENSE-PLAN.md`（本文**校正**它的两处前提）；
> 执行一律经 `ToolGateway` 四层（不新增执行通道）；动作编排复用 `WorkflowRuntime`；多用户边界见 `docs/MULTI-USER-BOUNDARY.md`。
> 事实层材料：`tmp/research/sandbox/`（143 份一手材料 + `draft-C-sandbox.md` 651 行）、真机实测脚本见 §7。

## 0. 结论摘要（先看这段）

| 问题 | 结论 |
|---|---|
| 主流沙箱怎么做 | **三层收敛**：① **策略层**（谁能做什么——平台策略/策略引擎，如 K8s Pod Security Standards）；② **内核层**（LSM + seccomp + namespace + cgroup，如 Landlock / seccomp-BPF / AppArmor）；③ **边界层**（换运行时拿更强边界：OCI 容器 → gVisor(runsc) → microVM(Firecracker)）。**接口收敛在 OCI runtime-spec**（namespace / seccomp / cgroup / maskedPaths 都是可移植字段）。绝大多数所谓「沙箱」= 内核层机制的组合 + 一份默认 profile。 |
| 需不需要 Docker | **不进主干**。三条理由：① trimum 要的是**每次工具调用**的边界，Docker 给的是**整机/整容器**的边界，粒度不匹配（每次 spawn 一个容器太慢）；② Docker 是**第二条执行通道**，与「一切动作经 ToolGateway」的红线冲突；③ 真机上 docker 已装（29.8.1）但**本地 0 个镜像**，用一次就要拉网。**保留为 Phase 5 的「不可信第三方 Agent 包」隔离档**（见 §6.3）。 |
| 真机能不能做 | **能，而且不需要 root**：Landlock ABI=4 已实测可拦（40 行 Python+ctypes PoC，见 §5）；seccomp 走自带 `libseccomp 2.5.5`（ctypes 可加载）；资源边界走 systemd 用户级 cgroup 委派。 |
| 两个硬限制 | ① **非特权 user namespace 被 AppArmor 禁**（`apparmor_restrict_unprivileged_userns=1`）→ `bwrap` / rootless 容器**都不可用**；② **`unprivileged_bpf_disabled=2`** → eBPF 监控**必须提权**。 |
| **裁决（2026-09-21，已定）** | 沙箱**提到编码智能体之前**；eBPF 走 **`CAP_BPF` + root helper**（daemon 仍非特权）；非特权 userns **不全局放开**（需要时定向给 `bwrap` 写 AppArmor profile）；Docker 档**留 Phase 5**；剩余待裁决见 §9.2 |
| 与既有设计的最大出入 | `docs/SECURITY-DEFENSE-PLAN.md` 把 **eBPF 当常规手段**写进了方案；真机上非特权完全不能用 BPF（见 §3.2）。另一处：该文档设想的 seccomp **L1/L2/L3 白名单**需要按 ABI 4 的现实重写（见 §6.2）。 |

## 1. 主流是怎么做的：三层 + 一份默认 profile

**证据链**（一手材料在 `tmp/research/sandbox/sources/`，逐条可指回）：

1. **接口层收敛在 OCI runtime-spec**：namespace、seccomp（含 `SCMP_ACT_NOTIFY` 的 fd 传递）、cgroup、`maskedPaths` 都是规范里的可移植字段；Landlock 自身也在向 runc/OCI 提交支持。
2. **默认加固由「runtime 默认 profile + 平台策略」定义**：
   - Docker 默认 seccomp profile：`defaultAction = SCMP_ACT_ERRNO` 的 **allowlist**，在 300+ 系统调用里默认挡掉约 44 个（包括用 `clone` 建新 namespace）。
   - Kubernetes Pod Security Standards 的 **Restricted** 档要求：`seccompProfile.type` 必须是 `RuntimeDefault` 或 `Localhost`、`capabilities.drop: [ALL]`、`allowPrivilegeEscalation: false`，并且该档位明确标注 **Linux-only**。
3. **要更强边界就换运行时，而不是换接口**：gVisor（`runsc`，用户态重实现内核面）与 Firecracker（microVM，KVM 硬件虚拟化边界）都是替换 OCI runtime 的位置。
4. **同一套内核机制，非特权也能用**：Anthropic 自家的 `sandbox-runtime` 在 Linux 上选的是 **bubblewrap**（5,293★，`pushed_at 2026-09-21`）—— 这印证「内核层机制 + 声明式包装」是业界通行做法。

**四类机制各自能挡什么**（细节见 `draft-C-sandbox.md` §2）：

| 层 | 机制 | 挡什么 | 典型代价 | 真机可用性 |
|---|---|---|---|---|
| 策略 | 策略引擎 / 平台策略 | 决策：允许/确认/拒绝 | 极低（字符串/模式匹配） | ✅ 已有（ToolGateway 四层） |
| 系统调用 | **seccomp-bpf** | 危险 syscall（`bpf`/`mount`/`ptrace`…） | 低 | ✅ 可（非特权，libseccomp） |
| 文件系统 | **Landlock LSM** | 路径级读/写/执行 | 低 | ✅ 可（非特权，ABI 4） |
| 进程/资源 | namespace + **cgroup v2** | 进程可见性、CPU/内存/PID 上限 | 低 | ⚠️ 部分（cgroup 走 systemd 委派；**非特权 userns 被禁**） |
| 整机边界 | OCI 容器 / gVisor / microVM | 全部（换内核面或换内核） | 高（运行时 + 镜像 + 启动开销） | ⚠️ Docker 有、镜像无；gVisor/Firecracker 未装 |
| MAC | AppArmor | 按 profile 限制程序行为 | 中（要写 profile） | ✅ 已启用（Ubuntu 默认） |

## 2. 各机制的关键事实（只列会改变决策的）

### 2.1 Landlock：ABI 决定能力，**kernel 6.8 = ABI 4**
`man 7 landlock` 的 VERSIONS 给出权威对照：**1=5.13 / 2=5.19 / 3=6.2 / 4=6.7 / 5=6.10 / 6=6.12 / 7=6.15 / 8=7.0 / 9=7.1**。
> 文档明确要求：**用 ABI 而不是内核版本判断能力**（*"Users should use the Landlock ABI version rather than the kernel version"*）。

真机 6.8.0-41 ⇒ **ABI 4**，即：文件系统访问位（ABI 1–3 全套，含 `TRUNCATE`/`REFER`）+ **TCP bind/connect 端口规则**；
**没有** `FS_IOCTL_DEV`（ABI 5）、**没有** `SCOPE_ABSTRACT_UNIX_SOCKET` / `SCOPE_SIGNAL`（ABI 6）。

- ⚠️ **这条缺口对我们的意义**：trimum 自己的 RPC 走 UNIX socket（`/run/trimum/trimum.sock`）。Codex CLI 的 Linux 沙箱 README 正因为「Landlock 隔离不了 app-server 的 UNIX socket」而**否决了 Landlock 方案**（`codex-rs-linux-sandbox-README.md:40-41`）。我们与它的处境不同：trimum 的 socket 是**自己的**，且沙箱只加在**子进程**上，所以不受此限——但要在设计里写清楚「不做 socket 维度的隔离」。
- Landlock 是**非特权**的（官方定性 *"unprivileged access control"*），前置条件只有 `PR_SET_NO_NEW_PRIVS`。
- Python 侧有 `Edward-Knight/landlock`（28★，MIT，`pushed_at 2026-08-31`），但其特性表把 ABI 4 的 TCP 支持标为不支持 —— **我们不需要它**：PoC 证明 ctypes 直调 syscall 就够（§5）。

### 2.2 seccomp-bpf
真机 `actions_avail = kill_process kill_thread trap errno user_notif trace log allow` —— 全部动作可用，特别是 **`SECCOMP_RET_USER_NOTIF`**（可以让用户态进程接管被拦的系统调用，做「先问再放」而不是直接杀）。
真机已装 `libseccomp2 2.5.5`，`ctypes.CDLL("libseccomp.so.2")` 可加载（**不需要 pip 包**）。

### 2.3 namespace 与 cgroup v2
- **user namespace 是其余 namespace 的前提**：内核文档口径是「其余 namespace 只需调用者 user namespace 内的 `CAP_SYS_ADMIN`」。
- 真机 cgroup v2 统一层级（控制器 `cpuset cpu io memory hugetlb pids rdma misc`），但**普通用户不能直接写 `/sys/fs/cgroup`**；**用户 slice 被委派了 `cpu memory pids`** → 这是 systemd 用户级限额能用的原因。

### 2.4 AppArmor 与 Ubuntu 24.04 的非特权 userns 限制
`kernel.apparmor_restrict_unprivileged_userns = 1`（Ubuntu 24.04 默认）。真机实测：`unshare --user`、`unshare --mount`、`bwrap` **全部被拒**（`bwrap: setting up uid map: Permission denied`）。
> 一处口径冲突（如实登记）：Ubuntu 发行说明与 `sandbox-runtime` 文档都把该 sysctl 描述成「允许建 userns 但剥夺其内能力」，而真机是**直接失败**。以真机实测为准。
> 另一条实测反例：**systemd 自己却能建 userns**（`-p PrivateUsers=true` 时 `readlink /proc/self/ns/user` 变成新 inode、`CapEff=0`）—— 因为它被自己的 AppArmor profile 覆盖。**这条给了我们一条免 root 拿 userns 的路子**（见 §6.4）。

### 2.5 systemd 的沙箱指令：169 条，**但会静默降级**
`systemd.exec(5)` 里与沙箱相关的指令非常全（`ProtectSystem=` / `ProtectHome=` / `PrivateTmp=` / `PrivateDevices=` / `PrivateUsers=` / `ProtectProc=` / `SystemCallFilter=` / `RestrictAddressFamilies=` / `RestrictNamespaces=` / `RestrictFileSystems=` / `MemoryDenyWriteExecute=` / `CapabilityBoundingSet=` / `NoNewPrivileges=` / `MemoryMax=` / `CPUQuota=` …）。

**两条必须记住的原文**：
- *"many of these sandboxing features are **gracefully turned off** on systems where the underlying security mechanism is not available"* —— **静默降级，不报错**。
- *"the various settings requiring file system namespacing support (such as `ProtectSystem=`) are **not available** [in user services] … most namespacing settings … will work when used in conjunction with `PrivateUsers=true`"*。

**真机实测直接推翻了后一句的乐观解读**：见 §3.1 —— 在本机用户服务下，`ProtectSystem=strict` / `ProtectHome=read-only` / `PrivateTmp=yes` **连挂载命名空间都没建**，加不加 `PrivateUsers=true` 都一样。

## 3. 真机实测（Ubuntu 24.04.1 / kernel 6.8.0-41-generic / systemd 255）

复现命令：`scripts/check_sandbox_caps.sh`（非特权）与 `scripts/check_sandbox_caps_root.sh`（root）。
本节数字全部来自 2026-09-21 在真机 `guzhujushi@100.115.86.48` 上的实测。

### 3.1 systemd 用户级：**哪些真生效、哪些是静默 no-op**

| 指令 | 实测结果 | 证据 |
|---|---|---|
| `NoNewPrivileges=yes` | ✅ **生效** | 单元内 `/proc/self/status` 显示 `NoNewPrivs: 1` |
| `SystemCallFilter=@system-service` | ✅ **生效** | 单元内 `Seccomp: 2`、`Seccomp_filters: 3`（并已安装过滤器） |
| `MemoryMax=33554432` / `CPUQuota=50%` | ✅ **生效** | 单元内读 `memory.max` = `33554432`（走用户 slice 委派的 `cpu memory pids`） |
| `PrivateUsers=true` | ✅ **生效** | 单元内 userns inode 变化（`user:[4026532455]` vs 宿主 `user:[4026531837]`），`CapEff: 0` |
| `ProtectSystem=strict` / `ProtectHome=read-only` / `PrivateTmp=yes` | ❌ **静默 no-op** | 三个单元（单独 + 组合 + 加 `PrivateUsers=true`）的 `/proc/self/mountinfo` **条目数都是 47，与宿主完全相同** → **根本没建 mount namespace**；`$HOME` 文件照写成功、宿主能看到单元内写进 `/tmp` 的文件 |

> **踩坑记录（必须写进纪律）**：我第一次测的时候用了 `systemd-run --user -p ProtectHome=read-only ...` **不带 `--wait`**，`systemd-run` 立刻返回、我随即检查文件不存在，于是得出「拦住了」的**错误结论**。
> 正确口径只有一个：**`systemd-run --wait --pipe`** 拿到单元的真实退出码与输出。凡涉及 systemd 沙箱的判定，必须用 `--wait --pipe`，否则测的是竞态。

**这条实测直接改写了设计**：systemd **用户级**能提供的是「资源 + 系统调用 + 特权位」边界，**不是**文件系统边界。
→ **文件系统边界必须由 Landlock 在进程内自施**（§5 的 PoC 证明可行），两者拼起来才是完整的一层。

### 3.2 非特权拿不到的东西（以及原因）

| 能力 | 真机结果 | 原因 |
|---|---|---|
| user namespace（`unshare --user`） | ❌ 被拒 | `apparmor_restrict_unprivileged_userns=1` |
| mount / net namespace（`unshare -m/-n`） | ❌ 被拒 | 同上（非特权下本来就依赖 userns） |
| `bwrap`（bubblewrap） | ❌ 被拒（`setting up uid map: Permission denied`） | 同上。**所以「业界爱用 bwrap」这条在真机默认配置下走不通** |
| 直接写 `/sys/fs/cgroup` | ❌ 被拒 | cgroup 根属主是 root；改走 systemd 用户级委派 |
| **eBPF**（bpftrace / BPF LSM） | ❌ 被拒 | **`unprivileged_bpf_disabled = 2`**（= 非特权完全禁用 BPF）；另有 `perf_event_paranoid=4` |

> ⚠️ **对 `docs/SECURITY-DEFENSE-PLAN.md` 的校正**：该文档把 eBPF 监听（`security.ebpf_alert`、内核挂载点异常等）当作常规检测手段。
> 真机上 **daemon 以 `guzhujushi` 运行（`trmd.service` 的 `User=guzhujushi`）⇒ eBPF 一律不可用**。
> 要么把 eBPF 部分拆成**特权 helper**（root systemd 单元，或带 `CAP_BPF` 的进程），要么在文档里明确标为「未提权前不可用」。

### 3.3 已具备的家底（不用装）

- **Docker 29.8.1**（服务 active、用户在 docker 组、`runc 1.5.1`、Compose v5.5.1、buildx v0.37.1、overlayfs、cgroup v2 + systemd 驱动），但**本地 0 个镜像**。
- `bpftrace` / `bpftool` / `perf` / `trace-cmd` / `strace` / `gdb` / `lsof`（工具在，但**非特权用不了 BPF**）。
- `build-essential` / `gcc` / `g++` / `make` / `python3.12.3` / `python3-dev` / `python3-venv` / `git` / `curl` / `wget` / `jq` / `tree` / `htop` / `unzip` / `xz` / `rg` / `fdfind` / `apparmor` / `docker-ce`。
- 两份 venv（`~/trimum/.venv`、`/opt/trimum/venv`）都属 `guzhujushi` ⇒ **Python 侧装依赖不需要 sudo**。

## 4. 可复用的现成件（沙箱相关）

| 项目 | 是什么 | 对我们 | 结论 |
|---|---|---|---|
| `bubblewrap`（5,293★ 的 `sandbox-runtime` 在用） | 非特权容器化工具 | 真机默认配置下**用不了**（userns 被禁） | ❌ 不用 |
| `nsjail`（google） | Linux 进程隔离（namespace + seccomp + chroot） | 非特权基本不可用，且要自己构建（`libprotobuf-dev`/`libnl-route-3-dev`） | ❌ 不用 |
| `gVisor`(runsc) / `Firecracker` | 换 runtime / microVM | 边界最强，但引入新运行时与镜像，且 KVM 需要设备权限 | ⏸ Phase 5 备选 |
| `libseccomp`（已装 2.5.5） | seccomp 过滤器构建库 | **ctypes 直接可用**，无需 pip、无需 -dev | ✅ 用 |
| Landlock 的 Python 绑定（`Edward-Knight/landlock` 28★） | ctypes 封装 | 我们的 PoC 已证明裸 ctypes 足够；引入它反而多一个依赖，且其 ABI 4 支持表不全 | ❌ 不用（自己 40 行） |
| `systemd-run`（已装） | 声明式沙箱入口 | cgroup/seccomp/特权位**免 root**；文件系统类指令无效 | ✅ 用（限定范围） |
| Docker（已装） | OCI 容器 | 粒度太粗、是第二条执行通道、要拉镜像 | ⏸ Phase 5 |

## 5. Landlock 可行性 PoC（已真机跑通）

`tmp/poc_landlock.py`（一次性脚本，约 190 行，**只用标准库 `ctypes`**），在真机输出：

```
[1] Landlock ABI = 4
[2] ruleset fd = 3, handled_fs = 0x7fff
[3] 已加规则：/ 只读，/tmp/trm-landlock-allowed 全权限
[4] restrict_self 已生效（NoNewPrivileges=1）
    [允许路径] /tmp/trm-landlock-allowed/a.txt -> 写成功
    [未允许]   /home/guzhujushi/.trm-landlock-outside -> EACCES（Permission denied）
    [只读读取] /etc/hostname -> 读成功
    [只读写入] /etc/hostname -> EACCES（Permission denied）
    [删除]     /tmp/trm-landlock-allowed/a.txt -> 删除成功（允许路径）
[5] 验证跨 execve 继承：
    子进程写 $HOME 被拒（预期）
[6] 不可逆性：再建 ruleset 并不放宽（Landlock 只能收紧）
[7] PoC 完成
```

**三条决定设计形状的性质**：

1. **零依赖**：三个 syscall（`landlock_create_ruleset` 444 / `landlock_add_rule` 445 / `landlock_restrict_self` 446）+ `prctl(PR_SET_NO_NEW_PRIVS)` 全部走 `ctypes`，不需要 pip 包、不需要 root、不需要 `-dev` 头文件。
2. **跨 `execve` 继承**（PoC 第 5 步实测）：限制施加在**施加者及其后代**上。⇒ **只要在「派生子进程的那个点」施一次，整棵进程树（含 shell → 测试进程 → 编译器等）都被覆盖** —— 这正是编码智能体跑测试需要的语义。
3. **不可逆、只能收紧**：政策是逐层叠加的（上限 16 层），进程无法自我放宽。⇒ 它可以作为**网关决策的「执行者」**，但绝不能被当作「可以事后撤销」的机制。

**已知缺口（写进设计，不装作没有）**：ABI 4 没有 `FS_IOCTL_DEV`（设备 ioctl 不设限）、没有抽象 UNIX socket / signal 域（那是 ABI 6 / kernel 6.12+）。⇒ 沙箱**不承诺** socket 维度隔离；对 trimum 自己的 RPC socket 需要在文档里明确「不在隔离范围内」。

## 6. 设计：落到 trimum 的哪一层

### 6.1 一个前提：六个派生点，必须收到一处

查代码得到，trimum 现在派生外部进程的地方有 **6 处**（都是 `asyncio.create_subprocess_*`）：

| 位置 | 用途 |
|---|---|
| `src/trimum_core/tool_dispatchers.py:641` | `shell` 工具（`create_subprocess_shell`）——**编码智能体最常用的那条** |
| `src/trimum_core/tool_dispatchers.py:389` | `git` 工具 |
| `src/trimum_core/tool_dispatchers.py:502 / 507 / 525 / 530` | `process` 工具（list / kill / start 等） |
| `src/trimum_core/agent_launcher.py:132` | 子 Agent 进程（`sys.executable <script>`） |

**设计决定**：新增一个薄封装 `sandbox_exec`（模块入口 + 一个可执行壳），**六个点全部改走它**；谁都不许自己 `create_subprocess_*`。
这与既有红线「不新增执行通道」同构：**不是给 sandbox 开旁路，而是给所有通路加同一道闸**。

### 6.2 分层：新增「内核层」，与既有四层网关**串联而不是并列**

```
ToolGateway.execute()
  Layer 1    全局策略（policy.yaml 正则）
  Layer 2    Agent 权限（agent.json5 的 exec/deny_exec/read/write）
  Layer 2.5  SecurityRule 决策（allow / confirm / deny）
  Layer 2.6  证书能力交集（capability.py，只收紧）
  Layer 3    JIT 授权（高风险需令牌）
  Layer 4    SecMonitor 威胁扫描
  ────────────────────────────────────────────────
  ★ Layer K（新）内核层「执行者」：
      1) 解析本轮的「沙箱档案」（由上面各层决策 + agent.json5 的 sandbox 段合成）
      2) 走 sandbox_exec 施加：Landlock（文件系统）+ seccomp（系统调用）+ NoNewPrivileges
      3) 记录实际施加的规则到审计（AuditRecord 已有 sandbox 字段，models.py:749）
  ────────────────────────────────────────────────
  真正 spawn 子进程（进程树整体被约束）
```

**关键点**：Layer K **不做决策**（决策仍在上面的策略层），它只做两件事——**施加**与**如实记录**。
施加失败时**默认拒绝执行**（fail-closed），不允许「沙箱没装上但命令照跑」。

**三档档案（沿用 `docs/SECURITY-DEFENSE-PLAN.md` §7.3 的声明式思路，数值按 ABI 4 校正）**：

| 档 | 适用 | Landlock | seccomp | 说明 |
|---|---|---|---|---|
| `readonly` | 探索/审阅类任务 | `/` 只读 + 工作区只读 | `@system-service` 白名单 | 只读任务零风险 |
| `workspace-write` | 编码智能体默认 | `/` 只读 + **工作区可写** + `/tmp` 可写 | `@system-service` + 挡 `bpf`/`mount`/`setns`/`ptrace`/`init_module` | 写盘只落在工作区 |
| `strict` | 未知/第三方 Agent | 同上，再加**显式白名单路径** | 最小白名单（`draft-C` §2.2 的 L3 思路） | 需要显式声明才能访问 |

声明位置沿用既有设计：`agent.json5` 的 `sandbox` 段（`seccomp_profile` / `extra_syscalls` / `extra_block`），另加 `fs_read` / `fs_write`。

### 6.3 Docker 的裁决：**不进主干，留作 Phase 5 隔离档**

| 维度 | 判断 |
|---|---|
| 粒度 | trimum 要的是「这次工具调用」的边界；Docker 是「整容器」边界。每次 spawn 一个容器要多付出启动 + 挂载开销，不适合高频工具调用 |
| 红线 | 容器内的动作**绕过 ToolGateway**（网关在宿主进程里），等于开第二条执行通道 —— 与既有红线直接冲突 |
| 现状 | 真机已装 docker 29.8.1，但**本地 0 个镜像**；用一次就要拉网（当前策略是「先不下载」） |
| 真正的用武之地 | **E5 分发来的第三方 Agent 包**（不可信代码）→ 用一个 OCI 容器把它关起来，边界最强、代价可接受（低频率） |
| 结论 | 主干用 Landlock + seccomp + systemd 用户级 cgroup；**Docker 档留到 Phase 5**，并且届时也必须「经网关发起容器创建」，而不是让 Agent 自己 `docker run` |

### 6.4 systemd 怎么用（用对那半截）

真机实测结论决定了用法：

- ✅ **资源与系统调用边界**：把**长驻子 Agent 进程**放进 `systemd-run --user` 的 transient service，用 `MemoryMax=` / `CPUQuota=` / `TasksMax=` / `NoNewPrivileges=` / `SystemCallFilter=`。
- ✅ **`PrivateUsers=true` 可以免 root 拿到新 user namespace**（`CapEff=0`）—— 这是真机上唯一拿得到 userns 的路子（因为 systemd 被自己的 AppArmor profile 覆盖，不受 `apparmor_restrict_unprivileged_userns` 限制）。
- ❌ **不要**指望用户服务的 `ProtectSystem=` / `ProtectHome=` / `PrivateTmp=`：实测**根本不建 mount namespace**（挂载条目 47 = 宿主）。文件系统边界交给 Landlock。
- ⚠️ **系统级（root）单元能拿到完整文件系统隔离**，这是「要不要给 trimum 加一个特权 helper」这条裁决的关键筹码（§6.6）。

### 6.5 平台降级：Windows 怎么办

Landlock / seccomp 都是 **Linux 专有**，而 trimum 的开发机是 Windows（本仓库 `AGENTS.md` 的双平台现实）。
**降级原则**：`capability` 探测 + **明确报「不支持」**，绝不允许「不知道就放行」：
- Linux：施加内核层，并把实际施加的规则写进审计；
- Windows：内核层标记为 `unsupported`，只保留既有四层网关（策略/权限/规则/能力交集），**且在写盘类工具的返回里带上 `sandbox: unsupported`**，让上层知道自己少了什么；
- 未来若要在 Windows 上补：Job Object（资源/进程）+ AppContainer 或受限令牌（文件与网络），属于另立一片，**不在本轮范围**。

### 6.6 daemon 自身：S1 已落地的口径（2026-09-21 实做）

`/etc/systemd/system/trmd.service` 原来是**零加固**（只有 `User=guzhujushi` + `WorkingDirectory=/opt/trimum`）。
落地方式是 **drop-in**（`/etc/systemd/system/trmd.service.d/10-hardening.conf`），由 `scripts/harden_trmd_unit.sh` 生成：
**默认 dry-run**，`--apply` 才装；装前备份到 `/var/backups/trimum/harden-<时间戳>/`（含一键回滚脚本），
装后跑冒烟，**任一断言失败自动回滚**。

**与本文原先设想的三处修正**（都是真机实测逼出来的）：

| 原设想 | 实际采用 | 理由 |
|---|---|---|
| `ProtectSystem=strict` + `ReadWritePaths` 白名单 | **`ProtectSystem=full`**（`/usr` `/boot` `/efi` **与 `/etc`** 只读），不列白名单 | daemon 要在**任意工作区**写盘（工作区在 `$HOME` 下，用户还可能让它去别处），`strict` 的白名单**根本列不全**：列漏 = 运行时才炸，全开 = 等于没加固。`full` 恰好盖住持久化面（写 unit / 改 PAM / 塞 cron / 换二进制）。**工作区粒度的边界交给 S2 的 Landlock**（按路径才是对的工具） |
| `ProtectHome=read-only` | **`ProtectHome=no`（显式写出来）** | 同上：`~/.trimum` 与工作区都在 `$HOME`。这是一条**明确放弃**的边界，写在 drop-in 里当记录 |
| `SystemCallFilter=@system-service`（白名单） | **黑名单**（`~` 前缀，多行合并） | 实测：systemd 255 的 `@system-service`（展开 375 条）**不含** `seccomp(2)` 与 `landlock_create_ruleset/add_rule/restrict_self`（444/445/446）—— 这三个**在任何分组里都没有**。用白名单会把它们一起挡掉，等于**把 S2/S3 自己要装的沙箱挡在门外**。黑名单只列「要挡的」，新 syscall 默认放行，正好兼容 Layer K 的自装逻辑 |

**被挡的清单**（`@clock @module @raw-io @reboot @swap @obsolete @mount @keyring @cpu-emulation @debug` +
`acct bpf capset chroot fanotify_* nfsservctl open_by_handle_at pivot_root quotactl* setdomainname sethostname vhangup` +
`userfaultfd io_uring_setup process_vm_readv/writev`），**故意的例外**：`@chown` 与 `setuid/setresuid/setreuid/setgroups/setfsuid` 不禁 ——
daemon 没有 `CAP_CHOWN`/`CAP_SETUID`，这些调用对它本来就什么都做不了，禁掉只会给正常工具添堵（`cp -a` / `rsync -a` / `mv` 跨设备）；
被挡的调用**返回 EPERM**（不是默认的 SIGSYS 杀进程），工具能自己报错、不会莫名消失。

**另外三项实测发现（都改了设计）**：

1. **`PrivateDevices=yes` 不能开**：它会新建一个只有 `null/zero/full/random/urandom/tty/ptmx` 的 `/dev`，**不带 `/dev/shm`**
   → Python `multiprocessing` / 共享内存类工具会挂。收益（挡 `/dev/mem`、块设备）对一个**非 root** daemon 本来就近于零，故不开。
2. **daemon 的 IPC socket 之前根本没起来**：默认路径（`/run/user/<uid>/trimum.sock`）下没有文件（系统单元里 `XDG_RUNTIME_DIR` 为空），
   `trm status` 一直显示 `source: http`。S1 用 `RuntimeDirectory=trimum` + `Environment=XDG_RUNTIME_DIR=/run/trimum`
   把它落到 `/run/trimum/trimum.sock`（目录 0750 / socket 0700），客户端 `trimum_client.SYSTEM_RUNTIME_SOCKET` 认同一条路。
3. **HTTP 端口是一个尚未收口的授权面**：`127.0.0.1:8321` 对**同机任何用户**开放（loopback 不做 uid 检查），
   而它背后就是完整的工具执行 API。systemd 的只读路径指令**管不了 IPC**（systemd 文档原文：这类选项
   「do not affect the ability for programs to connect to and communicate with AF_UNIX sockets」），
   要收口只能从监听面本身动手 —— 见 §9 新增待裁决 1。

**S1 的验收口径（冒烟逐条断言，失败即回滚）**：`systemctl is-active`；`ProtectSystem=full`；
`/proc/<pid>/status` 里 `NoNewPrivs: 1` 与 `Seccomp: 2`；`/proc/<pid>/mountinfo` 里 `/usr` 与 `/etc` 是 `ro` 而 `/home` 不是；
**`mountinfo` 条目数 > 宿主基线 47**（证明命名空间真的建了 —— 与上一轮「用户级单元静默 no-op」用的是同一把尺子）；
`/run/trimum/trimum.sock` 存在；以服务用户跑 `trm status` / `trm tool list` 通过；日志无 `unix_socket_start_failed`；
以及「同一套黑名单下 `landlock_*`/`seccomp`/`prctl` 不被挡、`bpf`/`ptrace`/`mount` 被挡」的 syscall 探针。

> **改前基线（真机实测）**：`systemd-analyze security trmd` = **9.2 UNSAFE**；`mountinfo` = **47 条**（= 没有命名空间）；
> syscall 探针（用户级复现同一套黑名单）：`bpf`/`ptrace`/`mount`/`init_module`/`kexec_load`/`userfaultfd`/`io_uring_setup`/`process_vm_readv`/`swapon`/`add_key` 全部 `errno=1 EPERM`，
> 而 `landlock_create_ruleset`(14) / `landlock_restrict_self`(77) / `seccomp`(22) / `prctl`(22) 正常返回「参数非法」，**没有被误伤**；
> `--allow-debug` 变体下 `ptrace` 恢复为 `errno=0`、`bpf` 仍 `EPERM`。

### 6.7 特权 helper 的设计（裁决 4 的落地口径，2026-09-21）

**裁决**：daemon 保持**非特权**，另起一个**特权 helper**；helper 只要 `CAP_BPF` + `CAP_PERFMON`
（**不要 full root，不要 `CAP_SYS_ADMIN`**）。设计目标两条：**① 不让「恶意高危指令」借 helper 的手落地；② 不让 eBPF 被恶意劫持。**

| 决定 | 具体做法 | 挡住什么 |
|---|---|---|
| **不给命令面，只给动词** | helper 监听 `/run/trimum/priv.sock`（`root:guzhujushi` 0660，用 `SO_PEERCRED` 校验对端 uid）；请求体是 `{verb, params}`，**verb 白名单硬编码**：`bpf.load` / `bpf.unload` / `bpf.stats` / `bpf.tail`。**不接受命令字符串、不接受路径参数**：程序名只能是枚举值，数值参数有上下界 | 「借 helper 执行任意命令」这条最危险的路**根本不存在** |
| **程序对象由 root 预置并校验** | 只加载 `/opt/trimum/bpf/<枚举名>.o`（`root:root 0444`）；装载前比对 sha256（清单 `/etc/trimum/bpf-manifest.txt`，root 私有）；helper 自身 `ReadOnlyPaths=/opt/trimum/bpf` | 「换掉 .o 就让 helper 加载任意内核程序」 |
| **最小权限** | `CapabilityBoundingSet=CAP_BPF CAP_PERFMON` + `AmbientCapabilities=` 同两枚；`NoNewPrivileges=yes` | 拿到 root 就等于拿到整机；CAP_BPF 只够 eBPF 那点事 |
| **AppArmor 定向 profile** | helper 只许 bind `priv.sock`、读 `/opt/trimum/bpf/**`、**不 exec 任何东西**；`aa-complain` 可一键回滚 | 万一 helper 被攻破，可做的事被钉死在 profile 里 |
| **单向数据流、拒绝 fd 传递** | helper → daemon 只经事件回灌（journal / 从 ringbuf 读出的 JSON）；**一律拒收 `SCM_RIGHTS`** | 「让 helper 替你加载任意程序」「拿别人的 fd」这两条 |
| **不监听网络、不 fork/exec** | helper 不 bind TCP；自身 seccomp 白名单里**没有 `execve`**，进程内没有 shell | 把 helper 当跳板再起进程 |
| **失败即关 + 如实记录** | 校验失败 / 加载失败一律拒绝，并写审计（`AuditRecord.sandbox` 记 helper、动词、程序名、sha256） | 不留「静默放行」的口子 |

**为什么不是「给 daemon 加 `CAP_BPF`」**：daemon 要跑任意用户 / 第三方工具，一旦它的 capability 集里长期挂着 `CAP_BPF`，
被它派生的任何一条命令只要摸到 `/proc/<pid>` 或复用父进程的权限面，就有机会把 eBPF 变成「内核里长期驻留的钩子」；
而 helper **不接受命令**，即使被打穿也只能做那四个动词。这条同时满足裁决 4（daemon 保持非特权）。
**落地时机**：**S5-①**（排在 S2/S3 之后）—— helper 的审计格式要复用 S2 建立的那一套。


## 7. 真机还需要装什么（工具链）

**结论：沙箱主干（Landlock + seccomp + systemd 用户级 + cgroup）几乎不需要新装任何东西。**
要装的是「把 C/BPF 侧做扎实」和「写脚本/排障」的那一批。

### 7.1 清单（`scripts/setup_ubuntu_toolchain.sh`，默认 dry-run）

| 档 | 包 | 用途 | 真机现状 |
|---|---|---|---|
| core | `build-essential` `python3-dev` `python3-venv` | 编译与 venv（Python 侧依赖的底座） | ✅ 已装 |
| core | `pkg-config` | C 构建系统的探测入口 | ❌ 缺 |
| core | `cmake` `ninja-build` `meson` | 构建 C/C++ 沙箱工具 | ❌ 缺 |
| core | `clang` `llvm` | 编译 eBPF C 程序；LLVM 工具的 BPF 后端 | ❌ 缺 |
| core | `libseccomp-dev` `libcap-dev` `libbpf-dev` | C 侧头文件（Python 侧有 `libseccomp2` 就够，写 C helper / BPF 程序才要） | ❌ 缺 |
| core | `linux-tools-generic` | 版本匹配的 `perf` / `bpftool` | ❌ 缺 |
| ops | `shellcheck` | 仓库里脚本多，统一 lint | ❌ 缺 |
| ops | `apparmor-utils` | `aa-status` / `aa-complain`（查改 profile，userns 限制的处置要用） | ❌ 缺 |
| ops | `auditd` | 内核审计（syscall 级取证、审计断链） | ❌ 缺 |
| optional | `uidmap` `fuse-overlayfs` | rootless 容器前提 —— **但 userns 被禁，装了也用不上**，等裁决 | ❌ 缺 |
| optional | `golang-go` | 写 Go 辅助程序才需要（当前无需求） | ❌ 缺 |

> **不需要装的**：`bubblewrap`（已装但被 userns 限制挡死）、`podman`（同上）、`nsjail`（非特权不可用 + 要一堆构建依赖）、`docker`（已装）、`ripgrep`/`fd-find`（已装，二进制名是 `rg`/`fdfind`）。
> **Python 侧不需要 sudo**：`~/trimum/.venv` 与 `/opt/trimum/venv` 属主都是 `guzhujushi`。

### 7.2 三个脚本（已放真机 `/tmp/`，只跑 dry-run，**未下载、未安装**）

| 脚本 | 位置 | 作用 |
|---|---|---|
| `setup_ubuntu_toolchain.sh` | 仓库 `scripts/` + 真机 `/tmp/` | **需要 sudo**。默认 dry-run；`--apply` 才装；`--tier core|ops|optional|all` |
| `check_sandbox_caps.sh` | 同上 | **不需要 sudo**。沙箱能力自检（PASS/WARN/FAIL），已在真机跑通：**PASS=8 WARN=6 FAIL=0** |
| `check_sandbox_caps_root.sh` | 同上 | **需要 sudo**。系统级 systemd 沙箱是否真的生效 / cgroup 直写 / eBPF 是否可用 / subuid 状态 |
| `harden_trmd_unit.sh` | 同上 | **需要 sudo**。`--apply` 才装 S1 加固（drop-in + 冒烟 + 失败自动回滚）；`--verify` / `--rollback` / `--stage`；口径见 §6.6 |

用户侧要跑的命令（都还没跑）：
```bash
sudo bash /tmp/setup_ubuntu_toolchain.sh              # 先看要装什么（不下载）
sudo bash /tmp/setup_ubuntu_toolchain.sh --apply      # 确认后再装
bash /tmp/check_sandbox_caps.sh                       # 非特权能力自检
sudo bash /tmp/check_sandbox_caps_root.sh             # 系统级能力核对（回答「要不要特权 helper」）
```

## 8. 分片实施建议（每片独立可验收）

> 顺序理由：先把「边界」立起来，再让编码智能体动手（这正是「沙箱提前」的裁决含义）。

| 片 | 做什么 | 验收标准 |
|---|---|---|
| **S1 daemon 加固** | ✅ **脚本已就绪**（`scripts/harden_trmd_unit.sh`，dry-run 默认 / 备份 / 冒烟 / 失败自动回滚；口径见 §6.6）。**未 apply** —— 要 `sudo` 密码，等你自己跑 | daemon 重启后 `systemctl is-active` + `/proc/<pid>/status` 里 `NoNewPrivs: 1`/`Seccomp: 2` + `/proc/<pid>/mountinfo` 里 `/usr`/`/etc` 是 `ro` 而 `/home` 不是 + `mountinfo` 条目数 > 47 + `/run/trimum/trimum.sock` 存在 + 以服务用户跑 `trm status`/`trm tool list` 通过 + syscall 探针（`landlock_*`/`seccomp`/`prctl` 不被挡、`bpf`/`ptrace`/`mount` 被挡）。改前基线：`systemd-analyze security` = **9.2 UNSAFE** |
| **S2 施加点收口** | 新增 `sandbox_exec`（Landlock + `PR_SET_NO_NEW_PRIVS`，ctypes）；6 个 spawn 点全部改走它；施加失败 **fail-closed** 并写审计 | 单元测试：允许路径可写 / 未允许路径 `EACCES` / 施加失败时命令**不执行**且审计有记录 / Windows 上报 `unsupported` 而非放行 |
| **S3 seccomp 档位** | 用 `libseccomp`(ctypes) 实现 `readonly` / `workspace-write` / `strict` 三档；`agent.json5` 的 `sandbox` 段声明式接进来 | 三档各自的 syscall 白/黑名单测试（含 `bpf`/`mount`/`ptrace` 被拒）；档案缺省值 = `workspace-write`；被拒的 syscall 有审计留痕 |
| **S4 子 Agent 资源边界** | 长驻子 Agent 走 `systemd-run --user` transient service（`MemoryMax`/`CPUQuota`/`TasksMax`/`NoNewPrivileges`/`SystemCallFilter`） | 子 Agent 超内存被 cgroup 杀掉且父会话收到明确失败；不装 systemd 的环境优雅降级（记 `unsupported`） |
| **S5 可选档**（要裁决） | ① eBPF 监控的特权 helper；② Docker 隔离档（第三方包）；③ 放开非特权 userns | 各自单独裁决后再开 |

## 9. 裁决与剩余待办

### 9.1 已裁决（2026-09-21）

| # | 问题 | 裁决 | 落地位置 |
|---|---|---|---|
| 1 | eBPF 监控要不要提权 | **要，但走 `CAP_BPF` + root helper**（不给 daemon 加能力，也不把 eBPF 从方案里摘掉） | §6.7 设计已定 → **S5-①** |
| 2 | 要不要放开非特权 user namespace | **不全局放开**（保持 `kernel.apparmor_restrict_unprivileged_userns=1`），将来需要时**定向**给 `bwrap` 写 AppArmor profile | **S5-③**（当前没有必须用 bwrap 的场景，Landlock 已覆盖文件系统边界） |
| 3 | Docker 档放哪 | **Phase 5**（隔离不可信第三方 Agent 包），不进 E7 主干 | Phase 5 |
| 4 | daemon 保持非特权 vs 加特权 helper | **加特权 helper**，daemon 本身仍非特权 | §6.7 → S5-① |
| 5 | 沙箱是否提到编码智能体之前 | **是** —— 本文即 E7 的前置片 | S1 已就绪（脚本 + 冒烟 + 回滚，等 `--apply`） |

### 9.2 上一轮待裁决 —— 已裁决（2026-09-21 本轮）

| # | 问题 | 裁决 |
|---|---|---|
| 1 | HTTP 端口要不要收口（§9.2 原第 1 条） | **只留 unix socket**（选项 (a)）。切割前必须先补的 RPC 面见 §9.3.5。 |
| 2 | `@debug` 取舍 | **放行**：`ptrace` / `perf_event_open` / `pidfd_getfd` 可用（`gdb` / `strace` / `perf` 才能跑），`bpf` 仍在黑名单里。脚本默认 `ALLOW_DEBUG=1`，`--deny-debug` 可关。 |
| 3 | `ReadOnlyPaths=/opt/trimum` 保留？ | **不保留**。脚本默认 `READONLY_DEPLOY=0`，`--readonly-deploy-tree` 可开。 |

### 9.3 socket 收口：先把「socket 为什么老坏」查清楚（2026-09-21 实做）

> 用户口径：*「刚刚回滚了，IPC socket 不存在，之前用 Socket 跑的时候一直出 bug 才暂时用 http 代替，现在改成 Socket 吧，你先看看吧」*
> 本节就是「先看看」的产出：先把历史 bug 逐条坐实，再定改法。

#### 9.3.1 现场（真机一手，全部只读）

| 观测 | 事实 |
|---|---|
| 现役 daemon（pid 16989，20:50:02 起） | 绑 `/run/user/1000/trimum.sock`：`ss -xl` 里有 `u_str LISTEN`，connect 探测成功并回 `{"status":"ok","version":"0.5.0"}` |
| `/run/trimum/` | **空目录**（`/run/trimum/trimum.sock` 不存在）—— 用户看到的「IPC socket 不存在」就是这条 |
| 为什么是空的 | 加固那两次（20:40:10 / 20:50:01）socket **确实绑上了** `/run/trimum/trimum.sock`（daemon 日志有 `unix_socket_listening path=/run/trimum/trimum.sock`）；回滚撤掉 drop-in 后 daemon 回到 `/run/user/1000/...`，而 `/run/trimum` 这个目录是 `RuntimeDirectory` 建的、回滚后没人回收，只剩空壳 |
| `trm status` | `source: rpc` / `endpoint: 127.0.0.1:8321 (socket=/run/user/1000/trimum.sock)`：**客户端补丁已经在部署树里**（`/opt/trimum/src/trimum_core/trimum_client.py` 含 `SYSTEM_RUNTIME_SOCKET`，sha256 `3a3caba4…`）；但开发树 `/home/guzhujushi/trimum/src` 那份**还是旧的**（无该符号） |

#### 9.3.2 历史 bug 坐实：三条，都能在日志里指到行

1. **父目录不存在 → bind `ENOENT` → 静默咽掉**（头号嫌疑，已坐实）
   `~/.local/share/trimum/trimum.log` 里有一行 `{"error": "[Errno 2] No such file or directory", "event": "unix_socket_start_failed", "level": "warning"}`。
   `ipc_handler._start_unix_socket()` 捕获后**只 `warning` 一声就 `return`**，daemon 照样 `active`、HTTP 照样服务 ——
   「socket 到底起没起来」这件事对 systemd 和对人都不可见。系统服务启动时 `XDG_RUNTIME_DIR` 是空的，退回的
   `/run/user/<uid>` 属于登录会话：开机时还不存在，daemon 又没权限建（`/run` 只 root 可写）。
2. **双实例互踩**：日志里有 `{"event": "unix_socket_in_use", "detail": "已有进程在监听，本实例拒绝抢占"}`；journal 里 9/20 那一刻的
   `restart counter` 已经涨到 **2134**，每条都是 `trmd: 启动中止 —— TCP 127.0.0.1:8321 已被占用` → `exit 3` → `Restart=always` 再来一次。
   **socket 冲突是「退让」、TCP 冲突是「退出重启」**，两种语义混在一起，观测上就成了一锅粥。
3. **客户端按「文件存在」挑，不按「能连通」挑**：`discover_socket()` 原来只做 `exists()`。进程被 SIGKILL 后残留的 stale
   socket 文件会被选中 → 连不上 → `_utils.get_daemon_status()` 静默退回 HTTP（`source: http`）。
   **这就是「切成 socket 了、看着还在走 HTTP」的观感来源。**

#### 9.3.3 两次 apply（20:40 / 20:50）为什么失败

**不是加固本身的问题，是冒烟抢跑。** 证据链：

- `/tmp/.trm-status.out`（root 属主，20:50）内容 = `[OFFLINE] daemon is not running` —— 冒烟里那次 `trm status` 时，**RPC 与 HTTP 两条路都不通**；
- 而同一时刻 daemon 已经绑上 socket（daemon 日志 `unix_socket_listening /run/trimum/trimum.sock`）；
- journal：20:50:01 起、**20:50:02 就被回滚停掉**，只隔约 1 秒 —— 只有「抢在 daemon 就绪之前断言」才会快到这一步。

`smoke()` 原来只等 `systemctl is-active`（`Type=simple` 下进程一起来就算 active），而 uvicorn 还要几百毫秒才 bind、IPC socket 更晚才建出来。
**断言跑在就绪之前 → `[FAIL] IPC socket 不存在` → 自动回滚**，用户看到的就是这一行。

修法：冒烟加 `wait_ready()`（60 × 0.5s 轮询「socket 真能连上」），FAIL 时把现场（`systemctl status` + journal + daemon 日志片段）
打进 `$BK/smoke.log`。**上一轮两次 apply 失败后证据全丢，这次不许再丢。**

#### 9.3.4 本轮改动（代码 + 脚本）

| 文件 | 改动 | 治的是 |
|---|---|---|
| `config.py` | 新增 `SOCKET_ENV="TRIMUM_SOCKET"` / `SYSTEM_RUNTIME_SOCKET` / `socket_is_live()` / `socket_candidates()` / `discover_socket(extra=…)`；`default_socket_path()` 认 `TRIMUM_SOCKET` | 两端共用一份路径契约（§9.3.2-1、-2） |
| `trimum_client.py` | 候选表加 `TRIMUM_SOCKET`；`discover_socket()` 改成**先挑真能连上的**，再退回「文件存在」 | §9.3.2-3 |
| `ipc_handler.py` | bind 前 `makedirs(parent)`；失败从 `warning` 升级为 `logger.error` + **stderr**（`trmd: IPC socket 起不来 —— <path>（<errno>）`）+ 记 `socket_start_error` | §9.3.2-1 |
| `api_server.py` | `await ipc.start()`（原来 `create_task`，失败被后台任务吞掉），失败再补一条 `ipc_socket_unavailable` error | §9.3.2-1、-2 |
| `cli/_utils.py` | `rpc_call()` 走 `discover_socket(extra=[config.socket_path])`，不再拿 `config.socket_path` 硬连 | §9.3.2-3 |
| `scripts/harden_trmd_unit.sh` | 单元改用 `Environment=TRIMUM_SOCKET=/run/trimum/trimum.sock`（**不再劫持 `XDG_RUNTIME_DIR`**）；加 `wait_ready()`；FAIL 留证到 `$BK/smoke.log`；默认 `ALLOW_DEBUG=1`、默认不加 `ReadOnlyPaths` | 本轮裁决 2 / 3 + §9.3.3 |

测试：`tests/test_socket_path_consistency.py` **11 → 20 项**（新增：env 契约、两端候选表逐条一致、stale 文件被跳过、
bind 失败不再静默、缺父目录自动创建）。本地 `18 passed / 2 skipped`（两项为 Windows 无 `AF_UNIX` 的 skip）。

#### 9.3.5 把 TCP 收掉：四条前置（**2026-09-21 第四轮已全部落地**，见 §9.3.7）

`core.host` 不再监听 TCP **之前**，必须先补齐 socket 这一侧的覆盖面，否则 CLI 会瘸：

1. **`health` 返回 `pid` / `uptime`**：`trm status` 现在的 pid 靠 `psutil` 扫 `127.0.0.1:8321` 的监听者（`status.py::_find_daemon_pid`），TCP 一关就没得扫。
2. **补 RPC 方法**：`/api/security/tokens`、`/api/security/learning`、`/api/security/learn` —— `cli/commands/security.py` 目前 **HTTP-only**，是关掉 TCP 后唯一会直接坏的命令面（`/api/workflows*` 没有 CLI 消费者）。
3. **加开关 `core.http_enabled`**（默认先 `true`）：切 `false` 时 uvicorn 不监听，preflight 也只查 socket。
4. **socket bind 失败在「无 HTTP」时升级为致命**：否则关掉 TCP 又没有 socket = daemon 什么都没提供，却仍然报 `active`。
5. `trm agent` 已经 RPC 优先（`agent.py::_remote_agent_call`），不用改；`/api/events/stream`（SSE）没有 CLI 消费者。

上面 1～4 已在同日第四轮全部落地（改法与测试见 §9.3.7）。**开关默认仍是 `true`**：让 daemon 真的停止监听 TCP
这一步要等 S1 上机验收过 —— 顺序是「`trm status` 看到 `ipc socket: ok`」→「用 `Environment=TRIMUM_HTTP=0`
试跑一轮 CLI」→「都正常再把 `/etc/trimum/config.yaml` 的 `http_enabled` 改成 false」。


#### 9.3.6 事故：装 HEAD 的 `api_server.py` 把 daemon 打成崩溃循环（2026-09-21 21:09）

**现象**：`harden_trmd_unit.sh --apply` 冒烟判 FAIL 并自动回滚 **单元**（这一半是对的），但 daemon 仍然
`activating (auto-restart)`，`NRestarts` 一路涨到 29 —— journal 里是：

```
File "/opt/trimum/src/trimum_core/api_server.py", line 42, in <module>
    from .workflow_runtime import WorkflowRuntime
ModuleNotFoundError: No module named 'trimum_core.workflow_runtime'
```

**真因**：`sync_opt_socket_patch.sh`（本轮新写）把仓库 **HEAD 的 `api_server.py`** 直接覆盖进 `/opt/trimum/src`。
那份文件的模块级 import 引用了 `workflow_runtime`，而**部署树里没有这个模块**（部署树比仓库旧一大截：
`/opt/trimum/src/trimum_core/workflow_runtime.py` 不存在，开发树里却是 9/20 22:48 的 33 KB）。daemon 一启动就
`ModuleNotFoundError`，`Restart=always` 每 5s 重启一次。**回滚只撤单元、不撤 `src`**，所以它一直循环。

**两条教训，都已落成护栏**：

1. **只装「在当前部署树里能 import」的文件**。`sync_opt_socket_patch.sh` 的文件集从 5 个收到 4 个
   （去掉 `api_server.py`）。代价只有一条：`await ipc.start()`（bind 失败立刻致命）暂时装不上；bind 失败
   现在由 `ipc_handler` 记 `error` + 打 stderr，仍然看得见。等部署树整体同步到 HEAD 再补回去。
2. **装之前先做「导入预演」**：把整棵 `$APP_SRC` 复制到 `/tmp/.socket-patch-rehearsal`，覆盖待装文件，
   用 `PYTHONPATH=$STAGE /opt/trimum/venv/bin/python -c "import trimum_core.main"` 验证（并断言
   `trimum_core.__file__` 真的来自预演目录，否则预演是假的）；不通就**一个字都不碰生产**。
   装完再用真树 import 一次复核。

**顺带确认的好消息**：事故那一刻 `main.py` 已经成功 import 了 `config` / `ipc_handler`（崩在 `api_server`
那一行），说明本轮 `config.py` / `ipc_handler.py` 的改动与部署树兼容。

**紧急恢复**：`scripts/trmd_hotfix_restore.sh`（需 sudo）—— 从最近一次 `socket-patch-*` 备份还原 `src`、
先验 `import trimum_core.main`、再重启 trmd、最后以 `guzhujushi` 身份跑 `trm status` 收尾核对。
**正确顺序**：先回滚 src（hotfix restore），再跑新版 sync。

#### 9.3.7 TCP 收口：四条前置落地 + 新开关 `core.http_enabled`（2026-09-21 第四轮）

用户口径：*「成功，写TCP吧」*（S1 恢复脚本跑通之后）。四条（§9.3.5）全部落地，**只在代码侧** ——
`http_enabled` 默认 `true`，生产单元一个字节没动。

| # | 改法 | 文件 |
|---|---|---|
| 1 | `health` 由 daemon **自报** `pid` / `uptime` / `http` / `ipc`，HTTP 与 IPC **共用一份** `_health_payload()`；`trm status` 先认 `health.pid`，再退 pid 文件，最后才是 psutil 扫监听端口 | `api_server.py`、`cli/commands/status.py` |
| 2 | 新增 RPC `security.tokens` / `security.learning` / `security.learn`；实现抽成模块级 `_jit_tokens()` / `_learning_status()` / `_run_learning()`，**HTTP 与 IPC 共用同一份**；`trm security tokens / learning / learn` 改 **RPC 优先、HTTP 兜底** | `api_server.py`、`cli/commands/security.py` |
| 3 | 新开关 `core.http_enabled`（默认 `true`）+ `TRIMUM_HTTP` 环境变量覆盖（`0`/`false`/`no`/`off` 关，其余一律当开）。关掉时 **不启 uvicorn**，由 `main._serve_without_http()` 自己驱 `app.router.lifespan_context(app)` —— 与 uvicorn 内部走的是**同一段 lifespan**；端口预检也只在开 HTTP 时跑 | `config.py`、`main.py` |
| 4 | 关掉 HTTP 时 socket bind 失败 → `IpcUnavailableError` 从 startup handler 抛出 → `trmd` 以退出码 `3` 中止（沿用 `abort_startup` 口径）。**开着 HTTP 时仍只记 `error`**：那时用户还有路走，不该拦启动 | `ipc_handler.py`、`api_server.py`、`main.py` |

顺带一条：`IpcHandler.listening`（本进程是否真在 listen）成了 `health.ipc` 的来源 ——
「socket 到底起没起来」从此是 `trm status` 上的一行，不用再翻日志对时间线。

测试 `tests/test_ipc_only_mode.py` **14 项**：开关的默认 / 配置 / env / 垃圾值四条；`health` 两份口径逐字段一致；
`security.*` 三个 RPC 的行为（令牌只露前 8 位、按 agent 过滤、learning 的 summary+profiles）；
`main._serve_without_http` 真的把 lifespan 拉起来又干净收摊；「HTTP 开 → socket 失败仍启动」与
「HTTP 关 → socket 失败必失败」两条对照。另改 `test_api_server_startup.py::TestHealthVersion`（health 不再只有 version）
与 `test_cli_commands.py`（RPC 优先 + pid 来自 health）。

**真机切换顺序（等 S1 过了再走，别提前）**：

```bash
# ① socket 侧先确认好了没有
trm status                       # 期望 "ipc socket: ok"

# ② 用环境变量只关这一个进程的 HTTP（删掉即回滚，不动 config.yaml）
#    由 harden 脚本的 drop-in 写 [Service] Environment=TRIMUM_HTTP=0，然后：
sudo systemctl restart trmd
trm status                       # 期望 http: disabled 且 ipc socket: ok
trm agent list; trm security tokens; trm security learning; trm security learn
```

③ 上面四条 CLI 全绿之后，才把 `/etc/trimum/config.yaml` 的 `http_enabled` 设成 `false`（
`scripts/install.sh` 生成的模板已带这一行，默认 `true`）。**这一轮没做，等 S1 验收。**

#### 9.3.8 真机验证：隔离环境 15 PASS / 0 FAIL，并抓到两件事（2026-09-21 第四轮）

**做法**（落成 `scripts/accept_ipc_only.sh`，全程不用 sudo、不碰生产 daemon、不碰 `~/.trimum`）：
把 HEAD 的**整棵** `src` 解到 `/tmp/ipconly-head`，再把 `XDG_CONFIG_HOME` / `XDG_DATA_HOME` /
`XDG_RUNTIME_DIR` / `TRIMUM_HOME` / `TRIMUM_SOCKET` 全部指到 `/tmp/ipconly`，用
`/opt/trimum/venv/bin/python`（真机系统 python3 没有 fastapi 等依赖）起一个
`core.http_enabled: false` 的 daemon，然后逐项断言。

**结果：15 PASS / 0 FAIL。** 覆盖：socket 60s 内就绪；`trm status` 走 RPC 且 `http=false` /
`ipc=true` / `pid` 与 socket 路径都对得上自己的 daemon；`security learning / tokens / learn`
三个命令在 HTTP 关闭下**全部走通**；本进程没有任何 HTTP 端口监听（只有 workflow driver 的临时端口）；
socket 起不来时 `exit 3`；SIGTERM 干净收摊（socket 文件被收走、日志有 `mode=ipc-only` 与
`trimum_core_stopped`）；`TRIMUM_HTTP=1` 能把 HTTP 反向打开（开关可逆）。

**发现 1（真 bug，已修）：致命路径的 `exit 3` 会挂住。** 第一版沿用 `sys.exit(3)`，真机上
`timeout 90` 之后只能 SIGKILL，拿到的是退出码 **124 而不是 3**。faulthandler 线程栈直接指出真因：

```
Current thread 0x… (most recent call first):
  File "/usr/lib/python3.12/threading.py", line 1622 in _shutdown
Thread 0x…:
  File "/opt/trimum/venv/lib/python3.12/site-packages/aiosqlite/core.py", line 59 in _connection_worker_thread
Thread 0x…:
  File "/opt/trimum/venv/lib/python3.12/site-packages/aiosqlite/core.py", line 59 in _connection_worker_thread
```

`ContextManager` 的 aiosqlite 连接线程是**非 daemon** 线程；startup 失败时 lifespan 的 `__aexit__`
根本不会跑（`__aenter__` 就抛了），连接没人关 → 解释器停在 `threading._shutdown()` 里等它。
**修法**：`abort_startup(..., hard=True)` —— 先 `logging.shutdown()` + flush，再 `os._exit(3)`；
预检那两条路（端口被占 / socket 被别人听）保持 `sys.exit`，因为那时什么都还没起。
回归测试在子进程里放一个故意 `sleep(300)` 的非 daemon 线程（旧写法会挂到超时）。

**同一类风险 uvicorn 路径也有**（启动失败时是 uvicorn 自己 `sys.exit(3)`，同样可能被非 daemon
线程拖住）—— 本轮没动，记进 `TODO.md`。

**发现 2（部署面事实，重要）：开发树 `/home/guzhujushi/trimum/src` 也落后 HEAD 一大截。**
第一次真机验证直接翻车：只覆盖本轮 7 个文件之后 daemon 起不来，

```
ImportError: cannot import name 'SecurityRuntime' from 'trimum_core.sec_executor'
```

即 `sec_executor.py` 也是旧版 —— §9.3.6 踩的是**部署树**缺 `workflow_runtime.py`，这次是**开发树**缺
`SecurityRuntime`。**两条结论**：① 两棵树都需要一次「整体同步到 HEAD」（`scripts/sync_opt_tree.sh`）；
② §9.3.6 那条**导入预演**是真有用的护栏 —— 谁再想「只挑几个文件装上去」，先跑预演。
#### 9.3.9 真机切开关：第一次跑失败的两条真因（2026-09-21 第五轮）

**第一次跑（21:54 / 21:56 两次 `sudo bash /tmp/sync_opt_tree.sh --restart`）都秒退**，生产一个字节没动
（部署树仍 62 个模块、没有 `/var/backups/trimum/src-*`、daemon 仍是 21:15 起的那个）。查出来的两条真因
都不在「加固」上，而在**脚本自己的失败路径设计**与 **`/tmp` 的跨用户语义**上：

| # | 真因 | 证据 | 修法 |
|---|---|---|---|
| 1 | **`set -e` 把现场吃掉了**：预演命令失败（含「命令找不到」= 退出码 127）时 bash 立刻退出，**连 `ERR` trap 都不打**，用户只看到一屏无解释输出 | 本地最小复现：`set -e` + 函数里调一个不存在的命令 → 退出码 127、trap 不触发、后续 `echo` 不执行 | 预演命令用 `set +e … rc=$? … set -e` 包起来，打印退出码与原始输出；全局加 `STEP=` + `ERR` trap，中断时报出「哪一步、哪一行、什么码」 |
| 2 | **「root 写、daemon 用户读」这条跨用户路径本来就不该存在**：预演脚本原先落地成 `/tmp/.trm-walk.py`（root 的 umask 一收紧就 `Permission denied`）；`rm -rf /tmp/trimum-sync-stage` 也会被**上一次 root 运行留下的 root 属主残留**挡住 | 真机：`/tmp/trimum-sync-stage` 属主 `root:root`；非 root 重跑时 `rm -rf` 逐文件刷「权限不够」（一次 500+ 行） | 预演代码**改走 stdin 喂给 python**，不再落地临时脚本；解出来的树 `chmod -R a+rX`；stage 删不掉就自动换 `mktemp` 新目录 |

**顺带两条反向护栏**（「预演通过」必须是真通过）：① 预演输出第一行必须等于
`ROOT <候选树>/trimum_core/__init__.py` —— venv 的 editable `.pth` 指向 `/opt/trimum/src`，
不查这一行就可能「加载的其实是旧树」或「预演根本没跑」；② 预演命令非零退出先打 WARN，再被 ① 拦住 → `exit 3`。

**真机实测（第五轮）**：正向 `--rehearse-only` **PASS**（HEAD 的 71 个模块全部 import 得过、相对旧树无新增失败）；
反向（把 `TRIMUM_APP_DIR` 指到不存在的 venv）**正确报错并 `exit 3`**，一个字没碰生产。

**本轮新增/改动的脚本**：

- `scripts/switch_ipconly.sh`（新）：`--check` / `--apply` / `--rollback`。**另开**一个 drop-in
  `20-http-off.conf`（只写 `Environment=TRIMUM_HTTP=0`，不碰已验收的 `10-hardening.conf`）；
  `--apply` = 前置 fail-closed + 就绪门 + 三条决定性断言（daemon 自报、全机 8321 无监听、daemon 只持有临时端口）+ 失败自动回滚。
- `scripts/sync_opt_tree.sh`（改）：装前**整树备份**到 `/var/backups/trimum/src-<时间戳>`、装前**导入预演**、
  `--rollback` / `--restart` / `--rehearse-only`，以及上面两条真因对应的修法。
### 9.4 材料与缺口

| 材料 | 位置 |
|---|---|
| 沙箱机制一手材料（143 份） | `tmp/research/sandbox/sources/`（每条对应来源 URL，见草稿 §6 来源清单） |
| 沙箱机制事实草稿（651 行） | `tmp/research/sandbox/draft-C-sandbox.md`（横向对照表 + 逐机制 + 主流分层 + 「材料里没有」清单） |
| 抓取脚本 | `tmp/research/sandbox/fetch-sandbox{,2..7}.ps1` |
| 真机探测脚本（4 个） | `tmp/probe_sandbox_host{,2,3}.sh`、`tmp/probe_systemd_enforce{,2,3}.sh`、`tmp/probe_mounts.sh` |
| Landlock PoC | `tmp/poc_landlock.py`（真机跑通，输出见 §5） |
| 落地脚本 | `scripts/setup_ubuntu_toolchain.sh`、`scripts/check_sandbox_caps.sh`、`scripts/check_sandbox_caps_root.sh`、`scripts/harden_trmd_unit.sh` |
| TCP 收口真机验收脚本（隔离环境，15 项断言） | `scripts/accept_ipc_only.sh`（2026-09-21 第四轮新增，结果见 §9.3.8） |
| S1 真机探测（只读，本轮新增） | `tmp/probe_daemon_runtime.sh` / `tmp/probe_daemon_health.sh` / `tmp/probe_deploy_layout.sh` / `tmp/probe_deploy_writes.sh` / `tmp/probe_syscall_filter.sh` / `tmp/parse_syscall_groups.py`（解析 `systemd-analyze syscall-filter` 的分组传递闭包）/ `tmp/verify_seccomp_names.sh` / `tmp/verify_denylist_effect.sh`（黑名单实际拦截效果）/ `tmp/verify_harden_dryrun.sh` |

**明确的材料缺口（不许脑补）**：Windows 侧的等价机制（Job Object / AppContainer）没有一手材料；Docker 29 对应的默认 seccomp profile 原件 404（只拿到 v28）；gVisor rootless 文档 404；nsjail 非特权可用性没有一手材料；`packages.ubuntu.com` 两次抓取失败（包版本以真机 `apt-cache` 为准）。

---

> 本轮（2026-09-21 第二轮）在**代码侧**动了 socket 层：路径契约收敛到 `TRIMUM_SOCKET`、客户端按「能连通」挑、
> bind 失败不再静默（见 §9.3.4）。**仍未安装任何包、未改动运行中的单元**。
> - 两次 `--apply`（20:40 / 20:50）被冒烟抢跑误判回滚 → 已加就绪门（§9.3.3）；
> - 第三次 `--apply`（21:09）是**真事故**：同步脚本把 HEAD 的 `api_server.py` 装进旧部署树 →
>   `ModuleNotFoundError: trimum_core.workflow_runtime` → daemon 崩溃循环（`NRestarts=29`）；
>   冒烟正确判 FAIL 并回滚了单元，但**回滚不撤 `src`**（§9.3.6）。文件集已收到 4 个 + 补上导入预演护栏；
>   恢复用 `scripts/trmd_hotfix_restore.sh`。
> 下一步（顺序不能反）：① `sudo bash /tmp/trmd_hotfix_restore.sh` ② `sudo bash /tmp/sync_opt_socket_patch.sh`
> ③ `sudo bash /tmp/harden_trmd_unit.sh --apply`；过了再按 §9.3.5 收掉 TCP。裁决记录见 §9.1 / §9.2。
> **第四轮（同日）：§9.3.5 的四条前置已在代码侧落地**（`core.http_enabled` 默认仍 `true`，生产单元未切）——
> 改法、测试与真机切换顺序见 §9.3.7；隔离环境的真机验收（15 PASS / 0 FAIL）与两个真发现见 §9.3.8。
> 生产单元仍未切 —— 只差「在 drop-in 里写一行 `Environment=TRIMUM_HTTP=0` 然后重启 trmd」。
> **第五轮（同日）**：这一步做成了两个可验收脚本（整树备份 / 导入预演 / 回滚三条护栏 + 失败自动回滚），
> 前置门已实测能拦住旧部署树（`--check` 两条 FAIL）；第一次真机跑失败的两条真因与修法见 §9.3.9。
> 顺序：① `sudo bash /tmp/sync_opt_tree.sh --restart` ② `sudo bash /tmp/switch_ipconly.sh --check` ③ 再 `--apply`。