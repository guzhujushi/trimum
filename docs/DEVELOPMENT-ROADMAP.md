# 开发路线

## Phase 0：基础环境 ✅ 已完成
- Arch Linux + Python + Docker + Git

## Phase 1：AI Shell MVP ✅ 已完成
- 自然语言 → 安全执行 → 输出
- `trm` 命令行工具

## Phase 1.5：桌面预设 ✅ 已完成
- 22 套 Hyprland 主题预设
- Btrfs + Snapper 自动配置
- 一键安装脚本

## Phase 2：Harness Core ✅ 已完成（2026-08-31）
> 17 个模块，4282 行代码，33 项测试全部通过

### 包含组件
- **Harness Runtime** — Agent 生命周期、权限、资源管理
- **Agent Router** — 按能力匹配 Agent，管道构建
- **Event Bus** — 异步 pub/sub 系统事件
- **Workflow Engine** — DAG 任务编排（并行/串行/依赖链）
- **Tool Gateway** — Tool Registry + Agent 权限感知（双层检查）
- **Security Runtime** — Policy Engine（YAML 规则 + Risk Level）
- **Planner Agent** — 唯一 LLM 组件，按需启动

## Phase 3：Agent SDK（待开始）

### 目标
提供 Agent 开发框架，预装 5+ Agent。

### 预装 Agent
| Agent | 职责 | 风险 |
|---|---|---|
| AI Shell | 自然语言→命令→安全执行 | 按命令 |
| System Healthy | 系统健康检查 + 更新后自检 | 低（只读） |
| Theme Manager | AI 辅助切换桌面主题 | 低 |
| Security Agent | Landlock Hook + 高危操作拦截 | 低 |
| File Ops | 自然语言文件管理 | 中 |

### 技术栈
- openai-agents-python（Agent 运行时基座）
- httpx（与 Core 通信）
- apprise（统一通知）

### 任务拆解
1. 补全 Tool Gateway 标准工具（HTTP / 通知 / Git / Docker / 文件系统 / 数据库）
2. Agent 文件化注册（`~/.trimum/agents/` 目录 + manifest）
3. 预装 Workflow 模板
4. Tool + Agent 鉴权（最小权力系统）
5. 弹性沙箱（AI 辅助策略评估 + 行为追踪）

## Phase 4：Security Runtime（待开始）

### 目标
用 Linux 内核机制加固 Agent 执行环境。

### 实现路径
```
Level 0：直接执行（低风险）
Level 1：Landlock + Seccomp（中风险）
Level 2：Namespace（User/Mount）轻量隔离
Level 3：Docker 沙箱（高风险完整隔离）
```

### 依赖
- Linux 5.13+（Landlock）
- Docker（沙箱模式）

## Phase 5：Memory Layer（待开始）

### 目标
落地长期记忆 + Knowledge Store。

### 实现
| 子层 | 技术选型 |
|---|---|
| 长期记忆 | SQLite（轻量） |
| 向量检索 | chroma（pip 秒装）或 SQLite + numpy |
| 关键字搜索 | SQLite FTS5 |
| Embedding | BGE-small 或 E5 |

## Phase 6：ISO / 安装镜像（待开始）

### 目标
一键安装镜像，任何 x86_64 机器上从零到完整 AI Linux 桌面。

### 三档安装模式
| 模式 | 内容 | 磁盘 |
|---|---|---|
| 🌟 普通模式 | AI Desktop + 浏览器 | ~10-20GB |
| 🚀 开发者模式 | 普通 + IDE/AI编码/Docker | ~40-60GB |
| 🧪 AI Engineer | 开发者 + 本地模型/GPU/RAG | 100GB+ |

## 时间线预期

| Phase | 状态 | 预计完成 |
|---|---|---|
| Phase 0 | ✅ | — |
| Phase 1 | ✅ | — |
| Phase 1.5 | ✅ | — |
| **Phase 2** | **✅ 已完成** | **2026-08-31** |
| Phase 3 | 📝 设计完成 | 待定 |
| Phase 4 | 📝 设计完成 | 待定 |
| Phase 5 | 📝 设计完成 | 待定 |
| Phase 6 | ⏳ | 待定 |

每个阶段独立可交付，不依赖后续阶段。
