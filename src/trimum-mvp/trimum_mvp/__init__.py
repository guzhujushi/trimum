"""trimum_mvp — trimum AI Shell Phase 1 MVP 包。

模块：
- cli.py      CLI 入口（trm 命令）
- llm.py      LLM 适配器（OpenAI 兼容 API）
- planner.py  命令规划器（自然语言 -> 命令计划）
- policy.py   策略引擎（YAML 规则 -> 风险分级）
- executor.py 执行器（确认流程 + subprocess 执行）
- output.py   Rich 输出格式化
"""