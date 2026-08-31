# Contributing

## 开发状态

当前处于 **Phase 2（trimum Core Runtime）** 开发阶段。三大核心模块正在实现：

- **Event Bus** — 事件总线（神经系统）
- **Workflow Engine** — 工作流引擎（任务逻辑）
- **Agent Runtime** — 智能体运行时（进程管理）

欢迎 Issues 和 PR。

## 目录结构

```
src/trimum_core/          # trimum Core 包
├── event_bus.py          # Event Bus 实现
├── workflow_engine.py    # Workflow Engine（DAG 执行器）
├── agent_runtime.py      # Agent Runtime 生命周期管理
├── agent_registry.py     # Agent 注册表
├── agent_router.py       # Agent 路由（注册表匹配）
├── planner_agent.py      # Planner Agent（唯一 LLM 组件）
├── policy_engine.py      # 策略引擎
├── tool_gateway.py       # 工具网关
├── context_manager.py    # 上下文管理器
├── api_server.py         # HTTP API
├── ipc_handler.py        # Unix Socket IPC
├── models.py             # Pydantic 数据模型
├── config.py             # 配置
├── logger.py             # 日志
├── main.py               # 入口
└── __init__.py

config/                   # 配置文件
├── trimum.yaml           # trimum Core 配置
└── policy.yaml           # 安全策略规则
```

## 分支策略

- `main` — 稳定版本
- `develop` — 开发分支
- `phase/*` — 阶段分支（如 `phase/2-core-runtime`）
- `feat/*` — 功能分支
- `fix/*` — 修复分支

## 提交规范

格式遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>: <简短描述>

- 做了什么
- 为什么
```

type 前缀说明：

| 前缀 | 用途 | 示例 |
|------|------|------|
| `runtime:` | Agent Runtime 相关 | `runtime: implement agent lifecycle manager` |
| `workflow:` | Workflow Engine 相关 | `workflow: add DAG execution loop` |
| `event:` | Event Bus 相关 | `event: add three-layer namespace routing` |
| `tool:` | Tool Gateway 相关 | `tool: add shell adapter command whitelist` |
| `policy:` | Policy Engine 相关 | `policy: add risk level evaluator` |
| `agent:` | Agent/Registry 相关 | `agent: add planner agent on-demand startup` |
| `docs:` | 文档 | `docs: update ARCHITECTURE.md to v3.0` |
| `fix:` | 修复 | `fix: correct event bus deadlock on unsubscribe` |
| `refactor:` | 重构 | `refactor: split agent_runtime into submodules` |
| `test:` | 测试 | `test: add event bus pub/sub unit tests` |
| `chore:` | 杂项 | `chore: update dependencies` |

## 代码风格

- **Python**：`ruff` + `black`（行宽 100）
- **Shell**：`shellcheck` + `shfmt`
- **配置文件**：YAML，两个空格缩进

```bash
# 安装 lint 工具
pip install ruff black
# 检查
ruff check src/
black --check src/
```

## Agent 插件规范

所有 Agent 通过 `agent.json` 声明自身。manifest 存于 `~/.trimum/agents/<name>/agent.json`。

详见 `docs/ARCHITECTURE.md` 第 5 节。

## 测试要求

- 每个模块须有单元测试
- Event Bus：测试三层命名空间 pub/sub、过滤
- Workflow Engine：测试 DAG 顺序/条件/并行执行
- Agent Runtime：测试生命周期状态机
- Policy Engine：测试 YAML 规则匹配所有 Level

```bash
# 运行测试
pytest src/trimum_core/tests/
```

## Pull Request 流程

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feat/my-feature`
3. 提交变更
4. 推送到分支：`git push origin feat/my-feature`
5. 发起 Pull Request

## 许可

MIT License — 详见 [LICENSE](LICENSE)
