# ARCH — trimum AI Shell MVP（Phase 1）

## 技术选型
- 语言：Python 3.12+（全项目统一 Python 栈，降低维护成本）。
- CLI：Typer（参数解析 + `trm` 入口）。
- 输出：Rich（彩色分级输出、确认交互）。
- HTTP：httpx（OpenAI 兼容 API 调用，支持流式）。
- 配置/策略：PyYAML（config.yaml + policy.yaml）。
- 测试：unittest + mock（不依赖真实 LLM 网络调用）。

## 模块划分
| 模块 | 职责 |
|---|---|
| `cli.py` | CLI 入口：解析自然语言参数、读取 stdin 管道、组装 planner → executor 流程 |
| `llm.py` | LLM 适配器：OpenAI 兼容 chat/completions，stream/非 stream、重试、环境变量读取 |
| `planner.py` | 命令规划器：自然语言 → 结构化命令计划（JSON）；失败降级为正则意图匹配 |
| `policy.py` | 策略引擎：加载 YAML 规则，正则匹配命令 → 风险级别 + 动作 |
| `executor.py` | 执行器：subprocess 执行 + 超时 + 3 步确认流程 + 审计日志 |
| `output.py` | Rich 输出格式化：success/warning/error/info、计划展示、风险颜色 |

## 数据流
```
stdin/自然语言 → cli.py
  → planner.py（llm.py 调用 OpenAI 兼容 API）
      → CommandPlan{plan, commands, risk, explanation}
  → policy.py 逐命令重新评估风险（策略引擎为准，覆盖 LLM 自报风险）
  → executor.py（low: 自动 / medium: 确认 / high: 确认+警告+审计 / critical: 拒绝）
      → subprocess.run(超时 60s) → output.py 展示结果
```

## 目录结构
```
src/trimum-mvp/
├── trimum_mvp/         # 包目录（M-5：避免顶层通用模块名污染 site-packages）
│   ├── __init__.py
│   ├── cli.py          # Typer 入口（trm = trimum_mvp.cli:app）
│   ├── llm.py          # LLM 适配器
│   ├── planner.py      # 命令规划器
│   ├── policy.py       # 策略引擎（含 normalize_command 规范化）
│   ├── executor.py     # 命令执行器
│   └── output.py       # Rich 输出（GBK 安全符号 + markup=False）
├── config.yaml         # 默认配置
├── policy.yaml         # 权限规则
├── pyproject.toml      # 元数据 + 依赖
├── README.md
└── test_scenarios.py   # 10 场景模拟测试
desktop/
├── zsh-ai.sh           # ai() Shell 函数（Linux/Arch）
└── ai.ps1              # PowerShell 等价入口（Windows 开发验证）
```

## 接口设计
- `trimum_mvp.llm.LLMClient.chat(messages, stream=False) -> str`：返回补全文本（stream 时逐块打印）。
- `trimum_mvp.planner.Planner.plan(user_input, pipe_input=None) -> CommandPlan`。
- `trimum_mvp.policy.PolicyEngine.evaluate(command) -> PolicyDecision`（匹配前先 normalize_command 拆段）。
- `trimum_mvp.executor.Executor.execute(plan) -> list[ExecutionResult]`。
- 环境变量：`TRIMUM_API_KEY` / `OPENAI_API_KEY`（API Key）、`TRIMUM_BASE_URL`（可选覆盖 base_url）。

## 部署方案
- 开发期：直接在 Windows 上 `pip install -e src/trimum-mvp`，`trm "..."` 验证。
- Linux/Arch：Phase 1 验收后部署，`desktop/zsh-ai.sh` 提供 `ai()` 函数；策略/配置路径可改由环境变量或 `--config` 覆盖。
- 审计日志：`~/.trimum/audit.log`（高风险命令追加记录）。