我已经通过 GitHub 连接读取了你的 [Trimum 仓库](https://github.com/guzhujushi/trimum?utm_source=chatgpt.com)，检查的是当前默认的 **`server` 分支**，最新提交为 `ccf5f3d3c2`（2026 年 11 月 22 日）。

## 一、先说总体判断

**Trimum 在架构定位上没有明显跑偏，但代码的实际重心还没有完全转向你最新确定的两个核心。**

这是两个不同层面的问题。

你现在的 README 已经明确：

> Trimum 不是 AI 桌面助手、Agent 框架或 Linux 发行版，而是一套连接 AI Agent 与操作系统的运行基础设施。

而且你已经把架构收敛为：

1. **Agent Runtime**：Agent 生命周期、沙箱、上下文、资源、工具和执行管理。
2. **System Intelligence**：eBPF 观测、工作负载分析、策略选择、执行验证和受控系统调整。

我认为这个定位是正确的，也符合我们近期讨论的方向。

尤其值得肯定的是，你没有把 System Intelligence 描述成已经实现的完整智能调度系统，而是明确标注：当前主要完成了 eBPF 观测，工作负载分析和调度策略闭环仍处于规划阶段。

但我检查仓库结构后，发现了一个比较明显的现象：

**Trimum 已经积累了大量功能模块，而真正应该成为核心的资源管理、统一执行边界和系统智能控制闭环，仍有重要部分尚未完成。**

这不是说已有代码没有价值，而是下一阶段应当调整开发资源的分配。

## 二、我认为最需要关注的几个偏离点

### 1. 🔴 资源限制还不是统一、强制的执行边界

这是目前最值得优先修复的地方。

我检查了三个文件：

- [resource_controller.py](https://github.com/guzhujushi/trimum/blob/server/src/trimum_core/resource_controller.py?utm_source=chatgpt.com)
- [agent_manager.py](https://github.com/guzhujushi/trimum/blob/server/src/trimum_core/agent_manager.py?utm_source=chatgpt.com)
- [sandbox_limits.py](https://github.com/guzhujushi/trimum/blob/server/src/trimum_core/sandbox_limits.py?utm_source=chatgpt.com)

其中有两套不同的资源限制路径。

**第一套：直接操作 cgroup v2。**

`CgroupV2Controller.apply_cgroup()` 尝试在 `/sys/fs/cgroup/trimum/<agent_id>` 下创建资源组，并写入 CPU、内存和 PID。

但是，当创建或写入失败时，它只输出警告，不向调用者报告失败。

而 `AgentManager.spawn()` 会继续保留 Agent 的 `RUNNING` 状态。

这意味着：**一个 Agent 有可能已经启动，却没有成功获得预期的硬资源限制。**

**第二套：通过 systemd-run 创建资源组。**

`agent_launcher.run_agent()` 可以通过 `systemd-run --user` 设置资源限制，这条路径更适合普通 Linux 用户。

但当 systemd 不可用时，`sandbox_limits.py` 明确允许回退到没有 cgroup 限制的执行方式。

这种处理不一定是错误的：如果某种任务允许尽力而为的资源限制，就可以降级。问题是它不能同时满足你设计中的“硬资源预算必须拒绝超额执行”。

**我的建议：统一资源控制结果，并明确区分硬约束和软约束。**

如果任务声明必须具有 `MemoryMax`，而实际无法施加，就应拒绝启动；如果只是可选的性能预算，则可以明确标记为降级运行。

这正是 AgentCgroup 值得优先复用的地方。不过，引入它之前也应先统一 Trimum 自己的资源控制接口，否则只是再增加第三套实现。

### 2. 🔴 HTTP 管理接口存在需要优先收紧的授权边界

我还发现了一个安全问题，比架构细节更紧急。

在 [api_server.py](https://github.com/guzhujushi/trimum/blob/server/src/trimum_core/api_server.py?utm_source=chatgpt.com) 中，HTTP 接口包含：

- 启动、停止 Agent；
- 执行工具；
- 读写 Agent Context；
- 签发一次性 JIT 授权令牌。

尤其是 `/api/security/allow_once`，当前路由直接调用 `issue_jit_token()`，在我检查的 HTTP 应用代码中，没有看到对调用者身份或管理员权限的验证。

同时，`config.py` 中 HTTP 默认启用，并监听 `127.0.0.1`。

**监听 localhost 不等于完成了身份认证。** 只要 HTTP 接口被启用，能够访问该本地端口的其他进程原则上也能发送请求。若以后支持多用户，这个问题会更明显。

我不能仅凭静态阅读断言整个系统已经可以被成功提权；工具执行还有其他策略检查。但 JIT 令牌签发缺少明确的授权边界，本身就不符合 Trimum 的安全设计目标。

建议优先采用经过身份验证的 Unix Socket 作为本地控制入口。HTTP 若保留，也必须有独立的调用者认证与操作级授权，并限制高权限管理接口的访问。

### 3. 🔴 `--quiet` / `--json` 模式下，用户确认可能被自动通过

这是代码审查中另一个值得立即修复的问题。

在 [cli/commands/ask.py](https://github.com/guzhujushi/trimum/blob/server/src/trimum_core/cli/commands/ask.py?utm_source=chatgpt.com#L13-L16) 中：

```python
class _QuietConsole:
    async def confirm(self, question: str, default: bool = False) -> bool:
        del question, default
        return True
```

`--quiet` 和 `--json` 模式会使用这个 Console。

而在 [agent_loop.py](https://github.com/guzhujushi/trimum/blob/server/src/trimum_core/agent_loop.py?utm_source=chatgpt.com#L773-L798) 中，当操作需要用户确认时，会调用：

```python
ok = await self.console.confirm("执行以上操作?", default=False)
```

这意味着，非交互模式下，本来需要人确认的步骤，在 AgentLoop 这一层会直接得到 `True`。

Tool Gateway 后续可能还有自己的安全检查，因此不能直接断言所有危险操作都会成功执行。但**用户确认这个控制环节确实可能被跳过**。

我建议把 `_QuietConsole.confirm()` 改为返回 `False`，除非存在独立验证过的预授权凭据。

这不是功能设计上的小问题，而是违反了你一直坚持的原则：**高风险操作最终必须由人授权。**

---

### 4. 🟠 Agent Runtime 目前还没有真正统一

这是我认为最大的**架构偏离**。

目前存在多条执行路径：

| 入口 | 实际执行路径 |
|---|---|
| `trm ask` | `AgentLoop` → 自己构造的 Tool Gateway |
| `trm exec` | CLI → 新建 Tool Gateway → 执行 |
| HTTP `/api/execute` | daemon → Tool Gateway |
| Agent Spawn | `AgentManager` → `launch_agent` |
| Agent 委派 | `delegation` → `run_agent` |
| Workflow | `WorkflowRuntime` → Workflow Engine / Tool Gateway |

它们并非完全独立，已经复用了不少安全和执行模块。

但目前还没有实现你在文档中确定的统一 `RuntimeKernel` 门面。

例如，[agent_loop.py](https://github.com/guzhujushi/trimum/blob/server/src/trimum_core/agent_loop.py?utm_source=chatgpt.com) 会构造自己的 `EventBus`、`ToolGateway` 和 `PsutilController`。

这意味着 `trm ask` 不一定使用 daemon 中的同一个 Runtime 状态、资源管理器和事件总线。

另外，[agent_launcher.py](https://github.com/guzhujushi/trimum/blob/server/src/trimum_core/agent_launcher.py?utm_source=chatgpt.com#L65-L72) 的 `resolve_agent_script()` 仍然将入口固定为：

```python
<agents_root>/<agent_type>/main.py
```

而最新设计文档已经确定，应当通过 Agent Manifest 的 `entry` 字段指定执行入口。

这说明 **Plan、Agent Manifest 和 Runtime 的统一契约仍处于设计领先于实现的状态**。

我认为正确的处理方式不是推翻现有 AgentLoop、WorkflowEngine 或 ToolGateway，而是完成文档中已经决定的薄门面设计：

```text
          CLI / API / Workflow
                   │
                   ▼
             RuntimeKernel
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
   AgentManager  Resource    ToolGateway
                 Manager
       │           │           │
       └───────────┼───────────┘
                   ▼
             SandboxExec
                   │
                   ▼
            Linux Process
```

这样才符合你最初的想法：**Plan Agent 负责逻辑决策，Runtime 统一管理实际执行。**

需要强调，薄门面不应该成为一个新的巨大调度器。它只需要解决入口、契约、资源预检和生命周期一致性。

---

### 5. 🟠 System Intelligence 的观测数据还有基础问题

我检查了当前 eBPF 程序和资源指标采集代码。

你的 eBPF 实现主要集中在两类事件：

- `sys_enter_bpf`：监控与 BPF 有关的系统调用。
- `sys_enter_execve`：监控进程执行。

它们适合安全审计和进程行为追踪。

但这还不是你想要的完整工作负载感知系统。

要判断一个 Agent 是 CPU 密集型、内存密集型还是 I/O 密集型，还需要把资源指标关联到具体的 Agent、Tool Call 和 cgroup。

更具体地说，我发现了一个实际的解析问题。

在 `resource_controller.py` 的 `get_usage()` 中，读取 `io.stat` 的逻辑是：

```python
for line in io_stat.splitlines():
    key, _, value = line.partition(" ")
    if key == "rbytes":
        ...
    elif key == "wbytes":
        ...
```

但 Linux cgroup v2 的 `io.stat` 实际格式是：

```text
8:0 rbytes=90430464 wbytes=299008000 ...
```

第一个字段是设备号，而不是 `rbytes`。

所以当前代码无法正确解析常规格式的 I/O 统计数据。[Linux Kernel Archives](https://cdn.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html?utm_source=chatgpt.com)

这是一个很典型的问题：

**System Intelligence 未来会依赖这些数据做智能分析。如果底层统计不可靠，之后再复杂的策略引擎也没有意义。**

我建议 R2 阶段优先完成稳定的数据采集、Agent/Tool 归属映射、指标正确性测试和观测开销测试，再开始引入复杂的 AI 分析。

---

### 6. 🟡 历史功能仍然占据了相当大的代码空间

仓库中仍保留了很多旧方向的实现，例如：

| 模块 | 我的建议 |
|---|---|
| Coding Agent | 保留，作为 Runtime 的一个应用 |
| MCP / Skills 生态 | 保留，但暂时冻结功能扩展 |
| Package / Install 体系 | 保留，优先维护稳定性 |
| Experience Learning / Memory | 保留必要能力，不再发展独立智能子系统 |
| Browser、桌面集成 | 暂不扩展 |
| 个人运维脚本 | 考虑从核心项目中分离 |

例如 `scripts/` 下还有 Gitea 邮件配置、博客同步、代理维护、隧道启动和服务器运维脚本。

这些东西不是没有价值，但与 Trimum 的核心运行时并不直接相关。

另外，[config/trimum.yaml](https://github.com/guzhujushi/trimum/blob/server/config/trimum.yaml?utm_source=chatgpt.com) 中仍包含旧的 `hot_pool`、Docker sandbox、Redis 等配置。它与当前使用 `core` 配置段的实现并不一致。

如果这确实是废弃配置，我建议移动到明确标注的历史目录，避免未来贡献者把它误认为当前有效配置。

不过，**我不建议现在大规模删除历史功能。**

目前更好的做法是冻结可选模块的功能开发，让代码继续存在、维持兼容，把开发资源转向两个核心。

---

### 7. 🟡 开源复用策略已经写进文档，但还没有充分落地

这一点与你刚才强调的开发理念直接相关。

我读了：

[docs/architecture/code-reuse.md](https://github.com/guzhujushi/trimum/blob/server/docs/architecture/code-reuse.md?utm_source=chatgpt.com)

里面已经明确：

- AgentCgroup 第一优先。
- 优先复用 cgroup 生命周期、Tool Call 级资源组和 OOM 反馈机制。
- SchedCP、AgentSight 作为可选外部工具。
- 不整体接入 AIOS。
- 复用代码时记录许可证、上游版本和修改来源。

这部分与我们最近的讨论高度一致。

但是，目前仓库中的 AgentCgroup 集成主要还是文档计划。**我没有在当前源码树中发现已经引入的 AgentCgroup 模块或相应的第三方源码目录。**

你现在的资源管理仍然主要依赖 Trimum 自己的实现。

这并不是已经偏离设计，而是下一阶段最值得推进的工作。

我还注意到 `bpf_loader.py` 自己通过 Python `ctypes` 封装了 libbpf 接口。既然这部分已经实现，就不需要立即重写；但未来扩展 eBPF 功能时，应该先评估能否复用更成熟的加载器或绑定库，避免不断扩大自维护的底层封装。

---

## 三、如果由我决定，接下来会怎样调整开发顺序？

我会根据这次代码检查，把近期任务重新排列：

| 优先级 | 工作 | 原因 |
|---|---|---|
| **P0** | 修复 `--quiet` / `--json` 自动确认 | 防止绕过用户确认 |
| **P0** | 收紧 HTTP 高权限接口的认证与授权 | 建立可信管理入口 |
| **P0** | 资源硬约束失败必须可检测、可拒绝 | 保证 Agent 隔离真实有效 |
| **P1** | 实现薄 `RuntimeKernel` | 统一执行入口和状态 |
| **P1** | 统一 Agent / Tool / Workflow 的资源归属 | 为 AgentCgroup 接入做准备 |
| **P1** | 修复并验证 cgroup 指标采集 | 为 System Intelligence 提供可靠数据 |
| **P2** | 接入 AgentCgroup 可复用部分 | 减少自研资源控制代码 |
| **P2** | 建立最小 Workload Analysis MVP | 开始形成系统智能能力 |
| **P3** | 策略仓库、sched_ext、动态反馈 | 在观测和控制基础稳定后推进 |

其中，**我甚至建议先暂停其他新功能，处理完前三项再继续 R1。**

这些问题涉及基础安全保证，优先级应该高于扩展更多 Agent 能力。

## 四、还有一个方向我不认为需要修改

仓库目前已经明确选择了**纯 Python 核心 Runtime**，而不是我们以前讨论过的 Rust + Python 混合架构。

这本身不构成偏离。

Python 一样可以管理 Linux 原生进程、cgroup、Landlock 和 eBPF 用户态控制接口。

关键不是代码用什么语言编写，而是：

- 安全约束是否真的由内核强制执行；
- Agent 是否通过统一 Runtime 被管理；
- 内核状态是否能够被准确观测；
- 资源决策与系统控制是否能够形成反馈；
- 扩展能力是否真的可以按需加载。

不过，你希望 Trimum 保持极致轻量，而当前核心依赖包含 FastAPI、Uvicorn、Pydantic 等组件，daemon 启动时也会创建多个后台任务。

这些不一定带来严重性能问题，但**需要实际测量启动时间、空闲 RSS、后台 CPU 使用率和单次任务额外开销**，不能仅凭架构中的 Lightweight 原则判断已经实现。

另外，README 声称 Linux 7.0 环境下有 `2507 passed / 4 skipped` 的测试基线。我看到了相关记录，但这次检查是 GitHub 源码静态审查，**没有在你的实际 Linux 环境中重新执行测试或验证运行时漏洞**。上面的发现应当通过针对性测试确认修复效果。

---

## 五、最终评价

我会把当前 Trimum 的状态概括为：

| 维度 | 评价 |
|---|---|
| 项目定位 | ✅ 已经收敛 |
| 架构设计 | ✅ 整体合理 |
| Agent Runtime 基础能力 | ✅ 已有较多实现 |
| Runtime 统一性 | 🟠 尚未完成 |
| 安全与资源强制边界 | 🔴 存在需要优先处理的问题 |
| System Intelligence 观测 | 🟡 已有基础，但仍需完善 |
| 智能调度和反馈闭环 | ⚪ 尚未实现 |
| 开源代码复用 | 🟡 有明确计划，实际集成尚少 |
| 控制功能范围 | 🟡 仍有历史功能积累 |

**我认为 Trimum 最大的问题已经不是缺少功能，而是现有功能之间还没有形成足够稳定、统一的核心执行体系。**

你之前提到，早期开发过度依赖 AI 生成代码，后来很难理解和安全审查。我这次看到的多个执行入口、不同资源控制路径以及部分安全处理不一致的问题，确实体现出了这种开发模式可能积累的技术债务。

不过，你最近做的架构收敛并不是白费功夫。现在文档已经明确指出应该统一什么、保留什么、暂停什么。

我的建议是：

**下一阶段不要继续扩展 Trimum，而是围绕 RuntimeKernel、Resource Manager 和 Tool Gateway 做一次以安全边界为中心的架构收敛。**

完成这一步，再引入 AgentCgroup，System Intelligence 才能获得一个真正稳定、可信的运行基础。

从长期来看，这比现在急着实现 AI 自动调度 Linux 内核更重要。