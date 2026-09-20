# PRD — trimum

## 产品目标

trimum 是一个 Python 实现的 AI Shell 与 Agent 运行时，提供 Tool Gateway、策略引擎、
Agent Registry 等能力，并通过 `~/.trimum/tools/<name>/` 的文件化工具插件系统接入
自定义工具。完整产品说明见 `README.md`。

## 功能需求

### 已交付（Phase 1-3）

- `trm` CLI：argparse 子命令（15 个命令组），人类可读 / `--json` / `--quiet`，退出码 0/1/2。
- Tool Gateway 分层检查：cwd Jail → PolicyEngine → Agent 权限 → SecurityRule → SecMonitor → JIT 授权。
- 文件化工具插件（`~/.trimum/tools/<name>/{tool.json5,main.py}`）+ 子 Agent 真实 spawn + cgroup 配额。
- 审计落盘与结构化查询（`trm log audit`）、策略学习反馈环、上下文压缩（`context_compactor.py`）。

### 本次任务需求（2026-09-20）

- 对齐文档口径：`STATUS.md` / `TODO.md` / `docs/INTEGRATION-PLAN-BROWSER.md` 与实测实现保持一致。
- 核实「OpenCLI 弃用 → CLI-Anything 接入」这一 P0 前提是否成立，产出调研结论。
- 为「引入 MCP 生态（awesome-mcp-servers）」给出可行方案与阶段计划。

### 已交付（2026-09-20，E1）

- 自描述命令面：命令元数据契约 + `trm commands [--all|--json|--check]`（Agent 可运行时枚举全部能力）。
- Agent Skills 分发：`trm skill list/sync/paths`，把 `SKILL.md` 技能链接进 `~/.agents/skills`、`~/.codex/skills`、`~/.claude/skills` 等宿主目录。

### 规划中（下一阶段）

- **官方分发渠道**：官网提供官方 Agent / Tool / Workflow，`trm install <name>` 下载即用；内置官方根证书
  （`config/trust/trimum-root.crt`）验证签名，用户无需信任自签证书；安装 ≠ 授权，运行时仍走 ToolGateway 分层。
- **证书 = 来源 + 身份 + 能力**（见 `docs/ECOSYSTEM-STRATEGY.md` §7.1）：官方根只回答「来源可不可信」；
  证书还携带**能力清单**（可动用哪些工具 / 风险上限 / 有效期），运行时与内置策略**取交集**，只收紧、不放宽。
- **自签证书仅本机本用户可用**：绑定 `machine_id` + 用户 keystore（`agent_cert.py` 已有雏形），
  他人使用需**重新自签**，不能靠复制证书获得能力。
- **多用户前瞻**（§7.2）：`~/.trimum/` 用户私有（certs / skills / tools / 审计）与系统公共（`/etc/trimum/`）的边界待定；
  审计日志需补 `user_id` 归属；官方证书建议多用户共用、自签证书每用户各一份。
- **选装模型 + 首次安装引导**（§7.3 / E6）：全套开发者工具链大部分为**选装**，第一次安装引导（`trm setup`）逐项询问，
  默认全不装；**零预装可跑** —— trimum 不依赖任何第三方 coding agent，skills 分发目标按已探测宿主动态决定。
- **自研 coding Agent（候选，参考 ECC）**：trimum 将来可能自己做 coding Agent，故不得假设机器上装了
  `claude` / `codex` / `opencode` 之类，也不假设它们会被实际使用。
- MCP 接入：MCP 客户端 + server 定义文件化 + ToolGateway 鉴权接线（见 `docs/MCP-INTEGRATION-PLAN.md`）。
- 浏览器工具：自研 CDP 工具为主，`epiral/bb-browser`（CLI + MCP，复用本机登录态）作为补充/对照。
- 桌面 / WebSocket 确认通道；`trm security revoke`；`trm memory import|export`。

## 用户场景

- 开发者用 `trm ask` / `trm exec` 让 AI 在本机执行命令，高风险操作被拦截或要求确认。
- 子 Agent 在受限配额下并行跑长任务，全部动作可审计、可回溯。
- 通过 `~/.trimum/mcp/` 启用第三方 MCP server，其工具与内置工具享受同一套策略与审计。

## 验收标准

- 文档中每一项勾选状态都能对应到代码实现，或明确标注为缺口。
- 调研结论可复现：`docs/CLI-ANYTHING-RESEARCH.md` 每条结论都附证据（registry / README / 本机检查）。
- `python -m pytest tests/test_cli.py -v` 全部通过（既有基线，不受本轮文档改动影响）。

## 范围边界

- 本轮**只改文档**，不动 `src/`、`tests/`、`scripts/`。
- 不安装 CLI-Anything（需 Node 生态，且经调研已否决），不引入任何新依赖。
- MCP 接入本轮只出方案，不写实现。
