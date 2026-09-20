# CLI-Anything 调研报告

> 调研日期：2026-09-20
> 方法：经 7993 代理 + `.env` 中 `GITHUB_TOKEN` 调 GitHub API / raw 抓取；原始件落 `tmp/research/`（已 gitignore）
> 目的：核对 P0「OpenCLI 弃用 → CLI-Anything 接入」的前提是否成立

## 1. 仓库概况

| 项 | 值 |
|---|---|
| 仓库 | `HKUDS/CLI-Anything`（HKU Data Intelligence Lab） |
| 定位 | "Making ALL Software Agent-Native"，配套 CLI-Hub 分发 |
| Stars / Forks | 49,602 / 4,581（2026-09-20 抓取） |
| License | Apache-2.0 |
| 语言 / 体积 | Python / 41.4 MB |
| 最新 release | `v0.4.0`（2026-06-25 发布） |
| 最近 push | 2026-08-21 |
| 主页 | https://clianything.cc/ |

## 2. 体系结构

- **布局**：每个受支持软件一个顶层目录 `<name>/agent-harness/`，内含可 `pip install` 的
  `cli_anything/<name>/` 包（`*_cli.py` + `core/` + `utils/` + `skills/SKILL.md` + `tests/`）。
- **注册表**：仓库根 `registry.json`（79 个 CLI）、`public_registry.json`、`matrix_registry.json`（能力矩阵）。
- **分发**：`pip install cli-anything-hub` → `cli-hub install <name>`；`cli-hub matrix install` 按能力矩阵批量安装。
- **Skills**：`skills/cli-anything-<name>/SKILL.md` 统一目录，可 `npx skills add HKUDS/CLI-Anything --skill <name>` 安装。
- **宿主适配**：仓库自带 `.claude-plugin/`、`.cursor-plugin/`、`codex-skill/`（含 `install.ps1` / `install.sh`）、
  `hermes-skill/`、`reasonix-skill/`、`opencode-commands/`。
- **质量约定**：每个 harness 自带 pytest（含 e2e）、`--json` 机读 + 人类可读双输出、可选 REPL 交互模式。

## 3. 对 trimum 的三条硬结论

### 3.1 `browser-cdp` 在 CLI-Anything 中不存在

`registry.json` 的 web 分类只有两个条目：

| name | entry_point | requires | install_cmd |
|---|---|---|---|
| `browser` | `cli-anything-browser` | **Node.js, npx, Chrome + DOMShell 扩展** | `pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=browser/agent-harness` |
| `clibrowser` | `clibrowser` | **Rust 工具链（cargo）**或下载二进制 | `cargo install --git https://github.com/allthingssecurity/clibrowser.git --tag v0.1.0 --locked` |

79 个条目中全库检索无 `browser-cdp`；`CDP` 字样仅出现在第三方条目 `tinyfish`（REST API 远程 CDP 会话）。
→ `docs/INTEGRATION-PLAN-BROWSER.md` 与 `TODO.md` 中「落地 browser / browser-cdp / clibrowser 三工具」的表述有误。

### 3.2 `browser` 恰恰是 Node 依赖

`cli-anything-browser` 是 DOMShell MCP server（`npx @apireno/domshell`）的 Click 包装，必须有
Node.js + npx + Chrome + DOMShell 扩展才能运行；`--daemon` 只在单个进程内有效，跨进程无状态
（官方 README 明确说明）。→ 与「opencli 引入 Node.js，不符合轻量化初衷，故弃用」的决策**直接冲突**。

### 3.3 trimum 已有等价自研实现

`~/.trimum/tools/browser/`（`main.py` + `_cdp.py`，CDP 原生 Python 实现）：

- 19 个 action：`page.open/url/title/snapshot/back/forward/reload`、`act.click/type/eval/press/select`、
  `util.list-pages/text/screenshot/wait`、`daemon.start/status/stop`
- 默认 CDP 后端（连 `--remote-debugging-port=9222` 的 Chrome，保留登录态）；DOMShell 仅作可选后端
- CDP 地址优先级：请求参数 > `CLI_ANYTHING_CDP_URL` > `http://localhost:9222`

→ 已覆盖 CLI-Anything `browser` 的主要能力且无 Node 依赖。**浏览器能力继续自研，不引入 CLI-Anything browser。**

## 4. 本机现状核对（2026-09-20）

| 检查项 | 结果 |
|---|---|
| `cli-hub` 命令 | 未安装（PATH 中无） |
| pip 包 `cli-anything-hub` | 未安装（`pip list` 无匹配） |
| `~/.trimum/tools/browser` | 存在，自研 CDP 实现（`kind: custom`、`risk: medium`、`timeout: 120`） |
| `~/.trimum/tools/opencli` | 存在，manifest 已改名 `tool.json5.disabled`，加载器跳过 |

## 5. 值得借鉴的部分（不引入依赖）

1. **Harness 方法论**：一个软件 = 一个 CLI = 一份 SKILL.md + 一套 pytest + JSON/Human 双输出。
   trimum 的对应物是 `tool.json5` + `tests/` + `--json`；建议把「工具自带 SKILL.md」写进 `docs/TOOL-DEVELOPER-GUIDE.md`。
2. **能力矩阵（CLI-Matrix）**：`cli-hub can <task>` 查「哪些 CLI 能完成该任务」，与 trimum 的 Workflow TARL
   匹配同构，可作为 Workflow 自动推荐的参考实现。
3. **registry 字段设计**：`name / display_name / version / description / requires / install_cmd / entry_point / skill_md / category / contributors`
   —— 比 trimum 现有 manifest 多了「依赖前置声明」与「技能文档指针」，值得补进 `tool.json5` schema。
4. **多宿主适配层**：同一套 CLI 向 Claude Code / Cursor / Codex 分发（`.claude-plugin/`、`codex-skill/`），
   对应 trimum 未来「工具包对外分发」的形态。

## 6. 建议

- **不改路线**：P0 由「接入 CLI-Anything」降级为「借鉴其约定」，浏览器能力继续走自研 CDP 工具。
- 同步修正 `docs/INTEGRATION-PLAN-BROWSER.md` 与 `TODO.md` 的表述（本轮已完成）。
- 暂不评估 `clibrowser`：需要 Rust 工具链（本机无 cargo），且与现有 `scraper` / `http` 工具能力重叠，收益低。
- 如仍要试 CLI-Anything 分发能力：经 7993 代理在**非生产 venv** 里 `pip install cli-anything-hub`，
  只装纯 Python、无 Node 依赖的 harness（如 `mermaid` / `drawio`），观察其 install 流程与 `--json` 约定。

## 7. 原始件

`tmp/research/`（已 gitignore）：

| 文件 | 内容 |
|---|---|
| `cli-anything-README.md` | 仓库 README（81 KB） |
| `cli-anything-repo.json` / `cli-anything-release.json` | 仓库元数据 / v0.4.0 release notes |
| `cli-anything-tree.json` | 全量文件树（2,582 条） |
| `cli-anything/registry.json` | 79 个 CLI 的注册表（61 KB） |
| `cli-anything/browser-HARNESS.md` / `browser-README.md` / `browser-SKILL.md` / `browser-setup.py` | browser harness 细节 |
| `cli-anything/codex-skill.md` / `CONTRIBUTING.md` | 宿主技能与贡献规范 |
