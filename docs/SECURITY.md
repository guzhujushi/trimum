# 弹性沙箱体系（Security Agent）

> 最后更新：2026-09-01
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
