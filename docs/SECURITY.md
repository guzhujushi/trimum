# 弹性沙箱体系（Security Agent）

> **架构归属（2026-11-11 重构）**：本文是 **Agent Runtime 安全治理**的细化文档，总体架构见
> `docs/ARCH.md` §3.5；机制事实以 `docs/SANDBOX-PLAN.md` 为准，配置分层见 `docs/SANDBOX-SCOPE.md`。
> 本文不重复 System Intelligence 的观测/策略设计，二者边界见 `docs/architecture/system-intelligence.md`。
>
> 最后更新：2026-11-11（归属标注）；机制内容沿用 2026-09-01 版本。
> 三层沙箱：硬性 / 弹性 / 智能，可选切换

---

## 架构

```
Agent/Tool 请求执行或跨 Agent 访问
    │
    ▼
┌───────────────────────────────────────────────┐
│            Security Agent (决策中心)            │
│                                               │
│  ╔═══════════════════════════════════════════╗ │
│  ║  可切换沙箱模式                           ║ │
│  ║  ┌──────────┐ ┌──────────┐ ┌──────────┐  ║ │
│  ║  │ 硬性模式  │ │ 弹性模式  │ │ 智能模式  │  ║ │
│  ║  │ 纯规则    │ │ 规则+监控 │ │ 规则+监控 │  ║ │
│  ║  │ 无 LLM   │ │ 人类确认  │ │ +LLM兜底  │  ║ │
│  ║  └──────────┘ └──────────┘ └──────────┘  ║ │
│  ╚═══════════════════════════════════════════╝ │
│                                               │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Policy Engine │  │  Behavior Monitor    │  │
│  │ 规则匹配      │  │  行为基线 + 异常检测  │  │
│  └──────────────┘  └──────────────────────┘  │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Landlock(P4)  │  │  资源阈值检查        │  │
│  │ 文件系统隔离   │  │  CPU/内存/频率       │  │
│  └──────────────┘  └──────────────────────┘  │
│                                               │
│  决策输出: allow / confirm(弹窗) / deny       │
└───────────────────────────────────────────────┘
```

## 沙箱模式

| 模式 | 决策依据 | 适用场景 |
|---|---|---|
| **硬性模式** | Policy Engine 规则 + 频率限制 | 生产环境，高性能，无交互 |
| **弹性模式** | 规则 + Behavior Monitor + 弹窗确认 | 开发环境，有人值守 |
| **智能模式** | 规则 + 监控 + LLM 兜底分析 | 探索性使用，复杂权限决策 |

## 决策规则

### 跨 Agent/工具访问

| 场景 | 结果 |
|---|---|
| 同一沙箱 + 同一工具 | allow |
| 不同沙箱 | confirm（跨沙箱） |
| 同一沙箱 + 不同工具（开发者工具互访） | confirm |
| 沙箱外 → 沙箱内 | deny（防逃逸） |
| 工作流白名单内 | allow |

### 命令执行

```
PolicyEngine 规则匹配
    ├── CRITICAL → deny
    ├── DENY     → deny
    ├── CONFIRM  → confirm（弹窗）
    └── ALLOW    → Behavior Monitor 二次检查
                        ├── anomaly → confirm（弹窗）
                        └── normal  → allow
```

### 非交互 confirm：一次性审批通道（`trm approve`，2026-10-05）

`confirm（弹窗）` 只有 CLI 有人值守时可用。web / API / workflow / agent-sdk 这些非交互通道
（`interactive=False`）拿不到弹窗，**不再直接执行**：

1. 先查声明式放行表 `approvals.allow`（元素 `{tool, cwd}`；`tool` 精确匹配、`cwd` 前缀匹配，空串 = 任意）；
2. 命中 ⇒ 放行（审计事件 `approval_preauthorized`）；
3. 未命中 ⇒ 落一条 pending 请求（`<TRIMUM_HOME>/approvals/<id>.json`，原子写 0600）并**拒执行**（fail-closed），
   错误信息里带 `trm approve <id>`；人在 CLI 批准 / 拒绝后由调用方 `consume()` 一次性取走结果，TTL 过期不放行。

| 配置项 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `approvals.allow` | — | `[]` | 声明式放行表（列表，元素 `{tool, cwd}`）；缺失 / 类型不对 / 坏 YAML ⇒ 视为无规则（fail-closed） |
| `approvals.ttl_seconds` | `TRIMUM_APPROVAL_TTL` | `300` | pending 超时秒数；显式参数 > 环境变量 > 配置 > 默认，解析失败或 `<=0` 回 300 |
| `paths.approvals` | `TRIMUM_APPROVALS_DIR` | `~/.trimum/approvals` | pending 文件落点（一请求一 `<id>.json`） |

CLI：`trm approve <id>`（批准）/ `trm approve <id> --deny`（拒绝）/ `trm approve --list`（列出 pending）。
**默认不配规则 ⇒ 非交互 confirm 一律拒绝**；`interactive=True` 的弹窗路径不受影响。

workflow 定义也能声明放行（cfm1c）：**顶层** `approvals.allow` 生效于该 workflow 的所有节点，
**节点级**同名键（`steps[].execute[].approvals`）非空时**整体覆盖**顶层（不是逐键合并）；都未声明 ⇒ 不注入任何规则。

```yaml
id: deploy
approvals:
  allow:
    - {tool: shell, cwd: /srv/repo}   # 该 workflow 的所有 shell 节点在 /srv/repo 前缀下放行
steps:
  - trigger: {event_type: workflow.request}
    execute:
      - agent_type: shell
        instruction: git pull
        approvals: {allow: []}        # 该节点整体覆盖顶层（空 = 不放行，收紧到默认 fail-closed）
```

### HTTP 管理面认证（2026-11-22）

HTTP（`127.0.0.1:8321`）与 Unix socket 暴露同一批管理操作：执行工具、启停 Agent、
读写 Context、签发 JIT 一次性令牌。**loopback 不构成身份认证**——同机任何进程都能连
`127.0.0.1`，所以 `core.http_enabled=true` 时 `/api/*` 一律要求调用者 token；
只有 `/health` 保持公开。

| 配置项 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `core.http_admin_token` | `TRIMUM_HTTP_ADMIN_TOKEN` | 空 | HTTP 管理面 token；至少 16 字符。空 ⇒ `/api/*` 全部 403（fail-closed） |

调用方通过 `X-Trimum-Admin-Token` 头提交。优先级按项目口径：环境变量 > 配置文件 > 空默认。
状态码：未配置 ⇒ **403**；配置了但短于 16 字符 ⇒ **503**；缺失 / 错误 / 畸形 token ⇒ **401**。
token 不写日志、不回显；比较使用常量时间的字节级 `hmac.compare_digest`。
未配置 token 时应走 Unix socket（`TRIMUM_SOCKET` / `$XDG_RUNTIME_DIR/trimum.sock`）。
非交互 `--quiet` / `--json` 的 `confirm()` 也按 fail-closed 处理，不会因为没有弹窗而自动放行。

### Agent 资源强制（2026-11-22）

`agent_manager.spawn()` 的资源约束分两档；策略按「请求参数 > `TRIMUM_RESOURCE_ENFORCEMENT` >
`agent_manager.resource_enforcement` > `soft`」解析。

| 模式 | 保证 | 失败行为 |
|---|---|---|
| `hard` | 启动前创建 cgroup、写 `cpu.max` / `memory.max` 并读回一致；子进程在 `fork` 后、`exec` 前把自己写入 `cgroup.procs`；启动后再次读回 PID 与限额 | 任一准备 / 入组 / 读回失败 ⇒ 不启动或立即终止，返回 `FAILED` |
| `soft` | 尽力施加并读回验证；历史行为保持可用 | 允许继续运行，但 spawn 结果必须显式标注降级 / 无执行前保证 |

CPU 百分比语义是「相对一个核心」：`100` ⇒ `cpu.max = 100000 100000`（一个完整核心），
`250` ⇒ `250000 100000`（2.5 个核心）；`<= 0` 才是无配额 `max 100000`。内存 `<= 0` ⇒ `memory.max = max`。
**`max 100000` 不等于 100%**，不得把无限制误报成「限制为一个核心」。

停止 Agent 时先终止主进程，再用 `cgroup.kill` 清理整个进程树；只有控制器不支持时才退回按 PID 清理。
`hard` 只有在「执行前限额已生效 + 启动后归属与限额均读回一致」时才可视为完整安全保证。

## Behavior Monitor 检测项

| 检测 | 方法 | 阈值 |
|---|---|---|
| 文件写入风暴 | 频率检测 | >30 次/分钟 |
| 文件删除风暴 | 频率检测 | >20 次/分钟 |
| 网络请求风暴 | 频率检测 | >20 次/分钟 |
| 远程操作密集 | 频率检测 | >5 次/分钟 |
| 磁盘写入密集 | 频率检测 | >2 次/分钟 |
| 容器操作密集 | 频率检测 | >5 次/分钟 |
| 跨沙箱操作 | 沙箱变化检测 | 首次进入新沙箱 |
| 新操作类型 | 行为模式变化 | 首次出现的新命令类别 |

## 防溢出检测

```python
risks = agent.get_escape_risks(sandbox_config)
# 返回: ["Docker socket mounted — container escape possible",
#        "Privileged mode — full host access",
#        ...]
```

检测项：
- Docker socket 挂载
- 特权模式
- Host PID namespace
- Host network
- 敏感系统路径挂载（/etc, /usr, /boot, /sys）
- 跨容器网络
