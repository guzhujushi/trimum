# trimum — 架构文档

版本：v3.0（2026-08-31）

## 1. 项目定位

### 1.1 它不是

- ❌ 一个新的 Linux 发行版（不碰 Kernel、不换 init、不自造包管理）
- ❌ 一个 AI 聊天助手
- ❌ 一个简单的 Agent 框架
- ❌ 一个桌面美化 dotfiles 项目

### 1.2 它是

**一个面向 Linux 的 AI Agent 运行时**——将 Event Bus、Workflow Engine 和 Agent Runtime 三大核心模块结合，使 AI Agent 像操作系统进程一样被调度、隔离和协作。底座是 Arch Linux + Hyprland 桌面。

目标用户：想用 Linux 但不想折腾的青少年 / 初学者 / 轻度用户。

让计算机从「我要学命令」变成「我描述意图，系统执行」。

### 1.3 与 Omarchy 的关系

Omarchy（basecamp/omarchy, MIT, 31.7k stars）是 DHH 做的开发者开箱即用 Arch 桌面——预装 IDE/Docker/Git，目标是「拿到就能写代码」。

本项目在 Omarchy 的思路基础上加入 AI 层：

| 能力 | Omarchy | 本项目 |
|---|---|---|
| 桌面预设 | ✅ | ✅ + AI 辅助切换 |
| 开发工具 | ✅ | 可选 |
| 自然语言操作 | ❌ | ✅ AI Shell |
| 自动维护 | ❌ | ✅ System Healthy Agent |
| 防滚挂 | ❌ | ✅ Btrfs + Snapper |
| 渣机友好 | ❌ | ✅ 云端 AI |

### 1.4 新架构：三大核心模块

trimum 从「多 Agent 工具集合」演化为 **AI Runtime 基础设施**。最核心的三个模块：

```
trimum Core (三大核心模块)
│
├── Event Bus ────── 神经系统（只传递，不思考）
├── Workflow Engine ── 任务逻辑（成熟经验固化→复用）
└── Agent Runtime ─── 进程管理（生命周期+权限+隔离）
     ├── Policy Engine
     ├── Tool Gateway
     ├── Agent Router（注册表匹配）
     ├── Context Manager
     └── Planner Agent ★（唯一的 LLM 组件，按需启动）
```

### 1.5 三大模块关系

```
新请求/外部事件
    │
    ▼
Agent Runtime 决定：是否有已固化 workflow？
    ├── 有 → Workflow Engine 直接执行
    │         ↓
    │         Event Bus 发布 task.* 事件
    │         ↓
    │         各 Agent 按订阅执行步骤
    │         ↓
    │         结果回写 Event Bus → 完成
    │
    └── 无 → Planner Agent（按需启动）
              ↓ LLM 拆解意图
              → 写入新 workflow（固化到 Workflow Engine）
              → Workflow Engine 执行

Agent 间通信全程通过 Event Bus：
  Agent A → Event Bus [task.*] → Agent B
  Agent B → Event Bus [event.*] → Planner（如需升级处理）
  所有 Agent → Tool Gateway ← Policy Engine 权限检查
```

---

## 2. Event Bus（事件总线）

### 2.1 定位

AI Runtime 的「神经系统」。

**核心职责**：负责所有组件之间的信息传递，**不负责思考，不负责执行**。

解决：*系统里发生了什么，谁应该知道？*

### 2.2 主要功能

**① 事件发布**
任何组件可以发布事件。例如 System Agent：

```json
{
  "type": "event.system.disk_usage",
  "source": "system_agent",
  "data": { "disk_usage": 95 }
}
```

**② 事件订阅**
Agent 根据能力订阅 topic。每个 Agent 只订阅与自己相关的 topic。

**③ Task 状态同步**
记录任务生命周期：`task.created` → `task.running` → `task.completed` / `task.failed`

**④ 异步通信**
避免 Agent A 直接调用 Agent B。所有通信经过 Event Bus 解耦。

### 2.3 三层命名空间

| 命名空间 | 谁可写 | 用途 | 示例 |
|----------|--------|------|------|
| `task.*` | Workflow Engine | 工作流步骤分发 | `task.optimize.check` |
| `event.*` | 所有 Agent | 告警/通知 | `event.system.disk_full` |
| `system.*` | Runtime 自身 | 状态事件 | `system.agent.spawned` |

### 2.4 类比

- Linux D-Bus
- Android Binder 事件机制
- Kubernetes Event
- 消息队列

---

## 3. Workflow Engine（工作流引擎）

### 3.1 定位

AI Runtime 的「任务执行逻辑」。

**核心职责**：复杂任务的步骤编排与复用。

为什么需要：如果每次任务都走 Planner Agent 重新思考，会慢、浪费 Token、不稳定。Workflow 把成熟经验固化。

### 3.2 主要功能

**① Task 拆解**
将用户请求转为结构化步骤：

```yaml
workflow:
  name: server_optimize
  steps:
    - system_check
    - log_analysis
    - security_review
    - optimization
    - report
```

**② 流程控制**
- 顺序执行：A → B → C
- 条件分支：CPU > 90% → 启动优化流程
- 并行执行：同时检查 CPU/内存/磁盘
- 人工确认节点：危险操作等待用户确认

**③ Workflow 复用**
已有 workflow 可直接执行，不走 Planner。如「磁盘空间不足」→ 直接执行 `disk_cleanup.workflow`。

**④ 失败处理**
- 重试（最多 N 次）
- 降级（跳过失败步骤）
- 回滚（调用 undo 步骤）

### 3.3 实现形态

有向无环图（DAG）执行器。每个节点是一个 Agent 任务，边表示依赖关系。

### 3.4 类比

- Kubernetes Operator
- GitHub Actions
- Airflow / Temporal

---

## 4. Agent Runtime（智能体运行时）

### 4.1 定位

AI Runtime 的「进程管理器」。

**核心职责**：Agent 的启动/运行/销毁、权限隔离、工具访问。

### 4.2 子模块

| 模块 | 职责 |
|------|------|
| Policy Engine | YAML 规则匹配 + 风险评级 |
| Tool Gateway | 工具调用封装（Shell/Git/Docker），双层权限检查 |
| Agent Router | 注册表查询 + 能力匹配 |
| Context Manager | Agent 上下文持久化（SQLite） |
| **Planner Agent ★** | 唯一含 AI 智能的组件，理解新请求→LLM 拆解→固化 Workflow |

### 4.3 Agent 生命周期

```
    Spawn（按需启动）
      ↓
  Initialized（分配 Context）
      ↓
  Running（执行 Task）
      ↓
  Waiting Tool（请求工具网关）
      ↓
  Completed
      ↓
  Destroyed（释放资源）
```

Agent 默认不常驻。每个任务完成后销毁。可配置为热 Agent（常驻，如 System Monitor）。

### 4.4 Planner Agent 定位

- **按需启动**（不是常驻），只在无匹配 workflow 时才启动
- **Runtime 内唯一含 LLM 智能的组件**
- 职责：
  1. 理解新请求意图
  2. LLM 拆解为结构化步骤
  3. 写入新 workflow（固化到 Workflow Engine）
  4. 以后同类请求直接走 workflow，不走 Planner
- 失败时发出 `event.planner.failed` 事件

### 4.5 权限模型

Policy Engine 使用 YAML 规则定义权限策略。

核心原则：

| 级别 | 风险 | 动作 | 示例 |
|------|------|------|------|
| Level 0 | 低 | 自动执行 | `ls`, `df`, `ps`, `git status` |
| Level 1 | 中 | 用户确认 | `rm`, `pacman -S`, `docker build` |
| Level 2 | 高 | 强确认 + 审计 | 系统配置修改 |
| Level 3 | 禁止 | 直接拒绝 | `rm -rf /`, 读 `/etc/shadow` |

---

## 5. Agent 插件化规范

### 5.1 agent.json 完整字段

```json
{
  "identity": {
    "name": "system-monitor",
    "display_name": "系统监控助手",
    "version": "1.0.0",
    "description": "持续监控系统健康状态"
  },
  "capabilities": ["system.monitor", "system.diagnose"],
  "lifecycle": {
    "is_hot": true,
    "timeout_seconds": 30,
    "memory_limit_mb": 512
  },
  "allowed_tools": ["shell", "file.read"],
  "permissions": {
    "exec": ["ps", "df", "free", "uptime", "top"],
    "read": ["/proc/**", "/sys/**"],
    "deny_exec": []
  },
  "communication": {
    "subscribed_topics": ["task.monitor.*", "event.system.*"],
    "publish_topics": ["event.system.alert"]
  },
  "execution": {
    "entry": "agent.py",
    "risk_level": "low"
  }
}
```

### 5.2 字段说明

| 字段 | 说明 |
|------|------|
| `identity` | 名称、显示名、版本、描述 |
| `capabilities` | 能力声明（点分命名法），用于 Agent Router 匹配 |
| `lifecycle.is_hot` | 是否常驻（热 Agent）|
| `lifecycle.timeout_seconds` | 任务超时 |
| `lifecycle.memory_limit_mb` | 内存限制 |
| `allowed_tools` | 允许调用的 Tool Registry 工具名 |
| `permissions.exec` | 允许执行的命令模式 |
| `permissions.read` | 允许读取的文件路径模式 |
| `permissions.deny_exec` | 明确禁止的命令模式 |
| `communication.subscribed_topics` | Event Bus 订阅的 topic |
| `communication.publish_topics` | Agent 可发布的 topic |
| `execution.entry` | Agent 入口文件 |
| `execution.risk_level` | Agent 任务默认风险级别 |

### 5.3 注册表存储

Agent manifest 存于 `~/.trimum/agents/<name>/agent.json`，由 Agent Registry 自动扫描加载。

---

## 6. 防滚挂体系（Distro-Proof Design）

### 6.1 核心机制：Btrfs + Snapper

```
用户触发更新（trm update / pacman -Syu）
    ↓
Snapper pre-snapshot（更新前系统状态）
    ↓
执行更新
    ↓
System Healthy Agent 全面检查
    ├── 全部检查通过 → 标记快照为 "OK"，保留备用
    └── 检查失败 >= 2 项 → 自动 Snapper rollback
                               ↓
                          用户收到通知：
                          「本次更新有问题，已自动回滚。失败项：xxx」
```

### 6.2 快照策略

| 触发条件 | 动作 | 保留数 |
|---|---|---|
| 每次 `pacman -Syu` 前 | pre/post snapshot | 最新 10 组 |
| 每 24 小时 | 定时快照 | 最新 7 组 |
| AI Agent 重要操作前 | 手动调用 `trm save-state` | 用户指定 |
| 用户手动触发 | `trm snapshot` | 用户指定 |

### 6.3 System Healthy Agent 检查项

1. 所有 systemd 服务是否 active（重点关注 dbus / NetworkManager / pipewire）
2. 磁盘可用空间 > 总容量 10%
3. 空闲内存 > 512MB
4. 关键服务端口是否可达
5. 能否连接 AI API
6. `/var/log` 无大量 ERROR/CRITICAL 日志
7. 内核 `dmesg` 无 OOM / panic / 驱动崩溃
8. trimum Core API 正常返回

失败数 >= 2 → 自动回滚 + 桌面通知。

---

## 7. Interface Layer 设计

### 7.1 三层接口

| 接口 | 协议 | 用途 | 阶段 |
|---|---|---|---|
| CLI | stdin/stdout | `trm "查看磁盘"` 作为 Shell 原语 | Phase 1 |
| Unix Domain Socket | 内部 IPC | Neovim 插件、Waybar 插件 | Phase 2+ |
| HTTP API | REST JSON | 外部工具、SDK 客户端 | Phase 2+ |

### 7.2 Shell 深度绑定

| 模式 | 命令 | 阶段 |
|---|---|---|
| `ai` 统一入口 | `ai "检查docker为什么启动失败"` | Phase 1 |
| `explain` 管道原语 | `cat server.py \| explain` | Phase 3 |
| `fix` 诊断修复 | 命令失败后输入 `fix` | Phase 3 |

**设计原则**：AI 增强 Shell，不替代 Shell。

---

## 8. Memory Layer 设计（Phase 5）

### 8.1 定位

Memory Layer 是 trimum 的持久层，与 Core 同级。包含两个子层：

| 子层 | 职责 | 实现 |
|---|---|---|
| 长期记忆 | Agent 间共享状态、用户偏好 | SQLite → PostgreSQL |
| Knowledge Store | 文档语义检索、RAG | PostgreSQL + pgvector |

### 8.2 设计原则

- Agent 不知道彼此在想什么，但可以读共享记忆
- Knowledge Store 不主动推送信息——Agent SDK 按需调用
- 嵌入模型按需加载

---

## 9. 与传统 Agent 框架的区别

| 维度 | 传统 Agent | Trimum |
|------|-----------|--------|
| 任务 | 临时生成 | Workflow 复用 |
| 通信 | Agent 直接调用 Agent | Event Bus 解耦 |
| 运行 | 脚本执行 | Runtime 管理 |
| 权限 | 依赖 Prompt | 系统级限制 |
| 安全 | 靠模型自我约束 | Landlock/Seccomp/Docker |
| 扩展 | 添加工具 | 注册 Agent |
| 稳定性 | 依赖模型稳定性 | 依赖 Runtime 稳定性 |

---

## 10. 开发路线概要

| Phase | 产出 | 内容 | 预估 |
|---|---|---|---|
| 0 | 基础环境 | Arch + Python + Docker + Git | 已结束 |
| 1 | AI Shell MVP | Python CLI，自然语言→安全执行 | 已结束 |
| 1.5 | 桌面预设 | Hyprland 主题包 + Btrfs/Snapper 配置 | 已结束 |
| **2** | **trimum Core Runtime** | Event Bus + Workflow Engine + Agent Runtime | **当前** |
| 3 | Agent SDK | Python 包 + 预装 Agent | 后续 |
| 4 | Security | Landlock + Seccomp + Docker 沙箱 | 后续 |
| 5 | Memory Layer | 长期记忆 + Knowledge Store | 后续 |
| 6 | ISO | 一键安装镜像 | 视需要 |

---

## 11. 安全

- **CLI**：仅限当前用户执行（Unix 权限控制）
- **Socket**：仅监听 `0700` 权限
- **HTTP**：仅监听 `127.0.0.1`，永不暴露公网
