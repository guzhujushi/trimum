# bb-browser 调研报告

> 调研日期：2026-09-20
> 方法：经 7993 代理抓 GitHub API / raw（`epiral/bb-browser`）；原始件落 `tmp/small/bb-*`（临时物，本轮后清理）
> 目的：核对 `TODO.md` 里「浏览器工具备选：`epiral/bb-browser` 可作为自研 CDP 工具的补充/对照」是否成立

## 1. 仓库概况

| 项 | 值 |
|---|---|
| 仓库 | `epiral/bb-browser`（BadBoy Browser） |
| 定位 | "Your browser is the API" —— 用**本机已登录的真实 Chrome** 给 Agent 当取数接口 |
| Stars / Forks | 6,223 / 605（2026-09-20 抓取） |
| License / 语言 | MIT / TypeScript（Node.js ≥ 18，pnpm workspace + turbo + tsup） |
| 体积 / 文件数 | 592 KB / 105 个文件（不含 `dist`） |
| 创建 / 最近 push | 2026-01-31 / **2026-05-29**（距今约 4 个月无 push） |
| 版本 | `0.14.2`（npm 包名 `bb-browser`） |

## 2. 体系结构

```
AI Agent (Claude Code / Codex / Cursor)
   │ CLI 或 MCP (stdio)
   ▼
bb-browser CLI ──HTTP──▶ daemon(127.0.0.1:19824) ──SSE──▶ Chrome 扩展(MV3) ──CDP──▶ 真实浏览器 tab
                            └ per-tab 事件环（network / console / errors）
```

- **两条接入面**：CLI（`bb-browser open|snapshot|click|fill|eval|fetch|network|screenshot|...`）与
  MCP（`npx -y bb-browser --mcp`，stdio，工具名见 CHANGELOG 的 `mcp:` 条目）。
- **默认路径需要 Chrome 扩展**（MV3 Service Worker，靠 15 秒 SSE 心跳保活，见 `packages/shared/src/constants.ts`）；
  `packages/cli/src/cdp-discovery.ts` 另有一条**直连**路径：探测 `127.0.0.1:9222`
  （`--remote-debugging-port` 启动的 Chrome）或自管端口 —— 这条与 trimum 自研 CDP 工具是同一机制。
- **site 系统**（核心卖点）：把网站变成 CLI 子命令，**103 条命令 / 36 个平台**
  （twitter、zhihu、bilibili、github、arxiv、eastmoney…），适配器本体在**另一个仓库** `epiral/bb-sites`，
  `bb-browser site update` 一键拉取；每条命令是一个 JS 文件，在页面上下文里 `eval` + 复用你的 Cookie。
- **Hub 模式**（`--hub <url>`）：daemon 作为 "Edge Clip" 经 gRPC 注册到 Pinix Hub
  （依赖 `@pinixai/hub-client`、`@connectrpc/connect`；会写 `~/.pinix/data`，并从一个腾讯云 COS 桶下载 viewer）。
  **默认关闭**（要显式 `--hub`），但存在。

## 3. 对 trimum 的硬结论

### 3.1 不作为运行时依赖接入

| 原因 | 依据 |
|---|---|
| **Node 依赖** | 本体是 TypeScript + pnpm/turbo；trimum 的既定方向是「去 Node」（`docs/CLI-ANYTHING-RESEARCH.md` §3.2 已因同样理由否决 CLI-Anything 的 browser 面） |
| **MCP server 源码不在公开树** | 105 个文件里没有 mcp 包，`packages/cli/src/index.ts` 里 0 处 `mcp`；但 README 承诺 `npx bb-browser --mcp`、CHANGELOG 有 5 条 `mcp:` 提交 → 该能力只在 npm `dist` 里，**与 `PRIVACY.md` 的「fully open source, you can audit the code」不一致**，无法审计 |
| **绕开 trimum 的治理面** | site 适配器是**社区仓库**的 JS，在页面上下文里 `eval`（Tier 3 甚至注入 webpack store）——不经过 `ToolGateway` / `security_rule` / 审计，也不进 `ToolRegistry`。trimum 的安全模型（Layer 1/2/2.5、cwd jail、JIT 令牌、审计）在它面前等于不存在 |
| **上游活跃度** | 4 个月无 push；扩展 + daemon + CLI + 社区适配器四件套都要跟版本 |

### 3.2 作为「对照与借鉴」的价值是实的

1. **「把网站变成命令」的目录形态**：`site` = 社区适配器 + `site update` 一键更新 + `site info` 查
   `args / example / domain`。这正是 trimum **E4 广接入 + E5 官方分发**要长成的样子：
   对应物是 `config/mcp-catalog.yaml`（M3 已做审核入口 `trm mcp catalog list --unreviewed`）与规划中的 `.trmpkg`。
   可借鉴的字段：每条适配器**自带示例、域名、参数说明**，安装器可校验、agent 可自解释。
2. **`snapshot -i` 的 `@N` 元素引用**：把可访问性树压成稳定编号，后续 `click @3` / `fill @5 "x"` 用编号指代
   —— 比让 LLM 生成 CSS 选择器稳。trimum 自研 browser 工具（19 个 action）可对照自查这一处。
3. **面向 Agent 的 SKILL.md 写法**：`allowed-tools: Bash(bb-browser:*)` + 「核心价值 / 快速开始 / 命令表」三段式，
   与 trimum 的 Agent Skills 分发（`trm skill`）同构，可直接当排版参照。
4. **两条接入路径的取舍**：它同时提供 CLI 与 MCP，且 MCP 会**自动拉起 daemon** —— 对应 trimum M4.5 的
   「远端工具聚合进 ToolRegistry」，验证了「MCP 是给 Agent 的统一入口」这一判断。

### 3.3 若将来仍要试（不进主线）

- 只走 **MCP 客户端**形态：`trm mcp add` 一条 server 定义（`npx -y bb-browser --mcp`），
  让它的工具以 `<server>__<tool>` 进 `ToolRegistry`，从而**落在 trimum 的审计与策略里**；
- **不使用** `site` 社区适配器库（页面上下文 `eval` 任意第三方 JS）；
- **不使用** `--hub`/OpenClaw 模式（默认关闭的第三方云通道）；
- 需要 Node 18+ 与 Chrome 扩展这一前提，在评估结论里明确写清。

## 4. 本机现状核对（2026-09-20）

| 检查项 | 结果 |
|---|---|
| `bb-browser` 命令 | 未安装（PATH 中无） |
| Node.js | **已装**（开发机 `node v24.18.1` / `npm 11.16.0`）—— 前提具备，但 trimum 侧不打算依赖 |
| `~/.trimum/tools/browser` | 存在，自研 CDP 实现（19 个 action，`risk: medium`） |
| trimum MCP 客户端 | 已有（M0–M4 + M4.5 聚合），若接入无需新代码 |

## 5. 结论

**维持「自研 CDP 工具」为主线，不引入 bb-browser 依赖。** 它的 `site` 目录形态与
`snapshot -i` 的引用编号值得借鉴，已分别记入 `TODO.md`（E4/E5 待办）与
`docs/TOOL-DEVELOPER-GUIDE.md` §11；本轮不产生代码变更。

## 6. 原始件

| 文件 | 内容 |
|---|---|
| `tmp/small/bb-readme.md` | README（7.3 KB，中英双版，此处为英文版） |
| `tmp/small/bb-paths.txt` | 全量文件树（105 条） |
| `tmp/small/bb-index.ts` / `bb-chrome.ts` / `bb-commands.ts` / `bb-constants.ts` | CLI 入口 / daemon CDP 层 / 命令表 / 共享常量 |
| `tmp/small/bb-SKILL.md` | `skills/bb-browser/SKILL.md`（8.7 KB） |
