# STATUS — trimum 项目进度

> 最后更新：2026-09-04

## 总体进度

| Phase | 组件 | 状态 | 行数 | 测试 |
|---|---|---|---|---|
| Phase 0 | 基础环境 | ✅ 完成 | — | — |
| Phase 1 | AI Shell MVP | ✅ 完成 | ~500 | — |
| Phase 1.5 | 桌面预设（Hyprland 主题 + 安装脚本） | ✅ 完成 | 22 套主题 | — |
| **Phase 2** | **Harness Core（17 模块）** | **✅ 完成** | **~4282 行** | **33/33 ✅** |
| **Phase 3 ∼ 3.5** | **Agent SDK + 安全体系 + 扩展** | **✅ 核心完成** | **9010 行** | **135/135 ✅** |
| Phase 4 | Security Runtime (Landlock/Sandbox) | 📝 设计完成 | — | — |
| Phase 5 | Memory Layer (Knowledge Store) | 📝 设计完成 | — | — |
| Phase 6 | ISO / 一键安装镜像 | ⏳ 待开始 | — | — |

## 当前代码规模

```
src/trimum_core/    28 个 Python 模块  9010 行
tests/               6 个测试文件      2278 行
docs/               17 个文档文件
agent-sdk/           1 个核心模块       283 行
```

## Phase 3 ∼ 3.5 已实现模块

| 模块 | 文件 | 行数 | 状态 | 测试 | 说明 |
|---|---|---|---|---|---|
| Agent SDK 封装 | `src/agent-sdk/` | 283 | ✅ 完成 | ✅ 3 pass | TrimumAgent 封装 |
| Agent Registry (文件化) | `agent_registry.py` | 208 | ✅ 完成 | ✅ | agent.json5 加载 |
| Agent Router | `agent_router.py` | 159 | ✅ 完成 | ✅ | 能力路由 + 管道 |
| Agent Manager | `agent_manager.py` | 340 | ✅ 完成 | — | 进程生命周期 |
| Agent Runtime | `agent_runtime.py` | 200 | ✅ 完成 | — | Task 执行器 |
| Agent Socket | `agent_socket.py` | 185 | ✅ 完成 | — | Unix Socket IPC |
| **Agent Certificate** | **`agent_cert.py`** | **317** | **✅ 完成** | **✅ 15** | 三档信任模型 |
| Tool Gateway (v2) | `tool_gateway.py` | 549 | ✅ 完成 | ✅ | Registry + 权限双栈 |
| **Tool Dispatchers (11个)** | **`tool_dispatchers.py`** | **908** | **✅ 完成** | **✅** | 11 种 Dispatcher |
| Tool File Loader | `tool_file_loader.py` | 169 | ✅ 完成 | — | tool.json5 加载 |
| Policy Engine | `policy_engine.py` | 140 | ✅ 完成 | ✅ | +source_type 过滤 |
| **Security Rule** | **`security_rule.py`** | **431** | **✅ 完成** | — | 三层沙箱模式 |
| **Transform Agent** | **`transform_agent.py`** | **325** | **✅ 完成** | — | NL→TARL/Shell |
| **Workflow Engine v2** | **`workflow_engine.py`** | **996** | **✅ 完成** | **✅ 14** | DAG + WorkflowDefV2+YAML |
| **Workflow Listener** | **`workflow_listener.py`** | **365** | **✅ 完成** | — | 事件监听 |
| **Behavior Monitor** | **`behavior_monitor.py`** | **246** | **✅ 完成** | — | 行为基线 |
| **System Monitor** | **`system_monitor.py`** | **247** | **✅ 完成** | — | 硬件采集+告警 |
| **Memory Bridge** | **`memory_bridge.py`** | **208** | **✅ 完成** | — | Event Bus→ContextManager |
| Context Manager | `context_manager.py` | 510 | ✅ 完成 | ✅ | +FTS5 全文搜索 |
| Event Bus | `event_bus.py` | 187 | ✅ 完成 | ✅ | pub/sub |
| Planner Agent | `planner_agent.py` | 611 | ✅ 完成 | — | LLM 规划 |
| TARL Parser | `tarl_parser.py` | 325 | ✅ 完成 | — | TARL 指令解析 |
| API Server | `api_server.py` | 310 | ✅ 完成 | — | FastAPI + SSE |
| IPC Handler | `ipc_handler.py` | 367 | ✅ 完成 | — | JSON-RPC |
| Models | `models.py` | 262 | ✅ 完成 | — | +SourceType 枚举 |
| Config | `config.py` | 199 | ✅ 完成 | — | — |
| Logger | `logger.py` | 45 | ✅ 完成 | — | — |
| Main | `main.py` | 67 | ✅ 完成 | — | — |
| CLI Client | `trimum_client.py` | 134 | ✅ 完成 | — | — |

## Phase 3 待实现（安全补齐）

| 项目 | 优先级 | 说明 |
|---|---|---|
| 凭据脱敏（Secrets Redaction） | 🔴 高 | 审计日志暴露 API key 是真实风险 |
| JIT 一次性授权模式 | 🟡 中 | SecurityAgent.allow_once |
| Transform Agent 稳定性测试 | 🟡 中 | 50+ NL→TARL 样本自动化 |
| 子 Agent 资源配额（CPU/内存） | 🟢 低 | psutil 限制 |
| 结构化审计日志（JSON 事件） | 🟢 低 | Event Bus 审计事件 |
| 流式 CLI 输出 | 🟢 低 | typer + rich |
| TRM 错误码体系 | 🟢 低 | TRM-1xxx/2xxx/3xxx 三段式 |

## Phase 3.5 剩余

| 项目 | 优先级 | 说明 |
|---|---|---|
| X1 Skill 层原型 | 🟡 中 | skill_loader.py + demo skill.yaml |
| X2 ExperienceLearner | 🟡 中 | 失败事件→LLM→经验提炼 |
| X3 Agent 自优化 | 🟢 低 | 有限范围 prompt 改进 |
| #20 记忆文件放 Agent 文件夹 | 🟡 中 | agents/<name>/memory/agent.db |
| #21 Certs 放 Agent 文件夹 | 🟡 中 | agents/<name>/cert.json |

## GitHub

| 分支 | 状态 |
|---|---|
| `main` | ✅ Phase 2 历史 + Phase 3 增量 |

## 设计决策记录

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-09-03 | 证书体系三档设计 | 官方拷入即用、自签绑 machine_id、无证走 ConfirmEntry |
| 2026-09-03 | PolicyEngine source 过滤 | 无 source 规则全局匹配；有 source 只匹配对应 type |
| 2026-09-03 | Transform Agent 默认 origin:ai | shell/TARL 输出自动附带 |
| 2026-09-03 | Workflow 文件化 YAML 格式 | Pydantic 序列化 + PyYAML 加载 |
| 2026-08-31 | Tool Dispatchers 原生 Python | 安全/可控，零外部依赖 |
| 2026-08-30 | 全程 Python（取消 Rust） | Rust 国内生态不足、AI 编程助手覆盖差 |
| 2026-08-30 | 端口 8321 | trm 首字母映射 |
