# STATUS — trimum 项目进度

> 最后更新：2026-08-31

## 总体进度

| Phase | 组件 | 状态 | 行数 | 测试 |
|---|---|---|---|---|
| Phase 0 | 基础环境 | ✅ 完成 | — | — |
| Phase 1 | AI Shell MVP | ✅ 完成 | ~500 | — |
| Phase 1.5 | 桌面预设（Hyprland 主题 + 安装脚本） | ✅ 完成 | 22 套主题 | — |
| **Phase 2** | **Harness Core（17 模块）** | **✅ 全部完成** | **4282 行** | **33/33 ✅** |
| Phase 3 | Agent SDK (openai-agents 封装) | 📝 设计完成 | — | — |
| Phase 4 | Security Runtime (Landlock/Sandbox) | 📝 设计完成 | — | — |
| Phase 5 | Memory Layer (Knowledge Store) | 📝 设计完成 | — | — |
| Phase 6 | ISO / 一键安装镜像 | ⏳ 待开始 | — | — |

## Phase 2 详细状态

### 已完成模块（17 个）

| 模块 | 文件 | 行数 | 状态 | 测试 |
|---|---|---|---|---|
| Agent Registry | `agent_registry.py` | 158 | ✅ | ✅ |
| Agent Router | `agent_router.py` | 151 | ✅ | ✅ |
| Planner Agent | `planner_agent.py` | 513 | ✅ | — |
| Workflow Engine | `workflow_engine.py` | 602 | ✅ | — |
| Tool Gateway | `tool_gateway.py` | 414 | ✅ | ✅ |
| Event Bus | `event_bus.py` | 121 | ✅ | — |
| Policy Engine | `policy_engine.py` | 65 | ✅ | — |
| Agent Manager | `agent_manager.py` | 340 | ✅ | — |
| Context Manager | `context_manager.py` | 309 | ✅ | — |
| API Server | `api_server.py` | 310 | ✅ | — |
| IPC Handler | `ipc_handler.py` | 367 | ✅ | — |
| Models | `models.py` | 219 | ✅ | — |
| Config | `config.py` | 199 | ✅ | — |
| Logger | `logger.py` | 45 | ✅ | — |
| Main | `main.py` | 67 | ✅ | — |
| CLI Client | `trimum_client.py` | 134 | ✅ | — |
| __init__ | `__init__.py` | — | ✅ (v0.3.0) | — |

### GitHub

| 分支 | 状态 |
|---|---|
| `main` | ✅ Phase 2 已合并，全部历史可见 |
| `phase2` | ✅ Phase 2 完整代码，可基于此裁剪为各版本 |

## Phase 3 待实现

1. Agent SDK 封装（openai-agents-python）
2. 预装 Agent（AI Shell / System Healthy / Theme Manager）
3. Tool 补全（Git / Docker / HTTP / 通知等标准工具）
4. Workflow 模板预装
5. 弹性沙箱（AI 辅助策略评估 + 行为追踪）

## 设计决策记录

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-08-30 | 全程 Python（取消 Rust） | Rust 国内生态不足、AI 编程助手覆盖差 |
| 2026-08-30 | 端口 8321 | trm 首字母映射 |
| 2026-08-31 | 新增 Agent Registry + Router | 按能力路由，不硬编码 Agent 分配 |
| 2026-08-31 | 新增 Workflow Engine | 替代大量固定 Agent，DAG 编排 |
| 2026-08-31 | Tool Gateway 重构（Registry + 权限） | 统一工具注册/发现/检查 |
