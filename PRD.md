# PRD — trimum

## 产品目标

trimum 是一个 Python 实现的 AI Shell 与 Agent 运行时，提供 Tool Gateway、策略引擎、
Agent Registry 等能力，并通过 `~/.trimum/tools/<name>/` 的文件化工具插件系统接入
自定义工具。完整产品说明见 `README.md`。

## 本次任务需求

- 依据 `tmp/spec_cli_implementation.md` 实现 `trm` argparse CLI。
- 将现有 `main.py` 中基于 `sys.argv` 的 `cli_dispatch()` 能力拆分为独立命令模块。
- 提供 version/health/status/doctor/ask/exec/install/memory/security/daemon/log/tool/agent/config/workflow。
- 保持零新增 CLI 依赖，仅使用 Python 标准库 `argparse`。
- 输出默认人类可读，`--json` 输出 JSON；退出码成功 0、参数错误 2、执行失败 1。

## 验收标准

- `python -m trimum_core.cli --help` 正常显示所有子命令。
- `python -m trimum_core.cli version` 输出 `trimum v0.5.0`。
- `python -m pytest tests/test_cli.py -v` 全部通过。
