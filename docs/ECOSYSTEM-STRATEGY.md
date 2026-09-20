# 生态战略 — 做「生态集成器」，不做「生态复制品」

> 日期：2026-09-20
> 触发问题：想极大扩大 trimum 的生态、复用别人的生态（灵感来自 Omarchy、Warp），CLI-Anything 是最优解吗？
> **结论先行：不是。** 最优解是四层「集成」结构 —— 环境清单（Omarchy 式）+ 协议（MCP）+ 知识（Agent Skills）
> + 目录（Warp 式 workflow）；CLI-Anything 降级为「可选的第三方 harness 目录」，只做导入源，不做主战略。
> 补充（同日）：第三个灵感源 **ECC**（`affaan-m/ECC`，262,999★）证明「一套技能 / 规则分发进 30+ 个宿主目录」
> 是可落地的工业级做法 —— 这条直接支撑 L2 的宿主分发路线。
> 证据原始件：`tmp/research/ecosystem/`（已 gitignore）

---

## 1. 三个灵感源的真实机制（先看证据）

### 1.1 Omarchy — 杠杆在「拥有环境」，不在「包装应用」

`omacom/omarchy`：42,147★ / 4,845 forks，MIT，Shell，默认分支 `quattro`，2026-09-19 仍在推。
仓库 2,116 个文件，顶层结构：`bin/`（**459 个 `omarchy-*` 脚本**）、`install/`（85 个叶子脚本）、
`themes/`（22 套）、`manual/`（51 章手册）、`agents/skills/`（7 个 skill）、`default/`（各应用默认配置种子）、
`shell/`（QML 状态栏）、`migrations/`、`version`。

它的生态机制有四条，**没有一条是「给每个软件写个 Python 包装器」**：

1. **单一命令命名空间 + 自描述命令面**
   `omarchy <group> <command> [args]`；`omarchy commands [--all] [--json] [--check]` 可**运行时枚举全部能力**；
   每个命令都支持 `--help`。命令元数据写在脚本头 80 行的注释里，由 `bin/omarchy` 扫描生成清单，且有测试保证有效：
   ```bash
   # omarchy:summary=Take a screenshot
   # omarchy:args=[smart|region|windows|fullscreen] [slurp|copy]
   # omarchy:examples=omarchy screenshot | omarchy capture screenshot region
   # omarchy:requires-sudo=true
   ```
   → 能力面是「扫出来的」，不是「手写出来的」；加了新脚本就自动出现在清单里。
2. **手册即权威源**：`manual/`（51 章）明确是 authoritative source，网页版只是镜像。
3. **Skills 一套喂所有宿主**：`agents/skills/*.md` 被符号链接进 `~/.claude/skills`、`~/.codex/skills`、
   `~/.pi/agent/skills`、`~/.gemini/config/skills`、`~/.hermes/skills`、`~/.agents/skills`。
   技能内容本身就是「怎么在这个环境里干活」——比如 `command-metadata.md`（改命令前必读）、
   `install-scripts.md`（改安装脚本前必读）。
4. **软件来自发行版 + 懒加载**：AI 手册里所有 coding-agent CLI（`claude` / `codex` / `opencode` / `agy` / `copilot`…）
   都是 **mise 管理的懒加载 stub**（`~/.local/bin`），首次运行才下载。不重写软件，只保证「默认装好、配置好、一条命令能调」。
5. **Agent 是环境的一等公民**：token 用量面板（`omarchy agent usage-update`）、崩溃自动交给 agent 诊断
   （`omarchy agent crash <pid>` + diagnose-crash skill）、配错可 `omarchy reinstall configs` 回滚。

### 1.2 Warp — 低门槛目录 + 社区 PR 是生态引擎

`warpdotdev/warp`：65,103★，AGPL-3.0，Rust（issues-only 仓库）。定位已从终端升为
"agentic development environment"：内置 agent **Oz**（云端并行 agent，可编程/可审计），也能跑 Claude Code / Codex / Gemini CLI。

开放扩展点做的正是「生态」：
- **`warpdotdev/workflows`（853★，Apache-2.0）**：`specs/**/*.yaml` 目录（410 个 spec），格式极简：
  `name` / `command` / `tags` / `description` / `shells` / `arguments`（参数写 `{{arg}}`）/ `source_url` / `author`；
  社区 PR 贡献，编译后同时在 Warp 内和 commands.dev 分发。
- 主题仓库同理（社区贡献）。

> 两者共同点：**不替别人写软件，而是定义「接入格式」+ 把目录做成人人能提交 PR 的东西。**

### 1.3 ECC — 第三个灵感源：把「一套技能 / 规则 / 命令」分发进所有 harness

`affaan-m/ECC`：**262,999★ / 39,353 forks**，MIT，默认分支 `main`，创建 2026-01-18，2026-09-20 仍在推；官网 `ecc.tools`。
自我定位是 **"the agent harness performance optimization system"**（v2.0.0 起自称 agent harness operating system）：
skills / instincts / memory / security / research-first。

仓库 5,026 个文件、**84 个顶层条目**（证据 `tmp/research/ecosystem/ecc-tree.json`）：

- **903 个 `SKILL.md`**、68 个 agent、94 个 command —— 生态面几乎全是 markdown，不是代码。
- **30+ 个宿主目录并列存在**：`.claude/` `.codex/` `.cursor/` `.gemini/` `.pi/` `.hermes/` `.kimi/` `.kiro/` `.qwen/` `.trae/` `.opencode/` `.zed/` `.agents/` `.claude-plugin/` `.codex-plugin/` …
  → 「一套内容，多宿主分发」被做到工业化程度（正是 trimum 的 L2 目标，只是它已经覆盖 30 个宿主）。
- 另有 `hooks/` `rules/` `mcp-configs/` `manifests/` `schemas/` `workflows/` `integrations/` `scaffolds/`；
  README 提供安装引导（`install.sh` / `install.ps1`，guided setup 与 native plugin 二选一）、`the-security-guide.md`、
  npm 包 `ecc-agentshield`、GitHub App、token 优化与自托管模型章节。
- **供应链红线意识**：README 顶部 WARNING 明确「只从官方渠道安装」，点名第三方 re-upload 可能夹带恶意代码 ——
  与 trimum §7 的官方签名分发是同一问题的两种答案。

**借鉴**：① 平台矩阵是「分发格式」问题，不是「写 30 套插件」；② 低摩擦安装引导（选装、可重置 / 卸载）；
③ 安全与供应链警告写在文档里，而不是藏在代码里。
**不照抄**：ECC 是 harness **增强层**（改的是别人 agent 的提示与规则），它不拥有执行通道；
trimum 的差异化仍在 ToolGateway + 审计 —— **能力从哪来可以借生态，「能力能不能跑」必须自己管**。

---

## 2. 候选生态方案对比

| 方案 | 规模 | 依赖代价 | 集成成本 | 对 trimum 的定位 |
|---|---|---|---|---|
| **CLI-Anything**（逐应用 harness） | 79 个 CLI | 多为 pip；`browser` 需 Node，`clibrowser` 需 Rust | 高：每个 harness 是别人的独立产品，版本/质量不受控 | **可选第三方目录**（导入源），不做主战略 |
| **MCP** | 4,117 个 server（TS 2,271 / Py 1,351；npx 626） | 需自建 client | 中 | **服务层主通道** |
| **Agent Skills**（SKILL.md 开放标准） | `anthropics/skills` **177,179★**、`google-labs-code/stitch-skills` 8,343★ | **无运行时依赖** | 低（写 markdown） | **长尾主通道**，零代码扩能力面 |
| 通用适配器（API/MCP ↔ CLI） | `open-webui/mcpo` 4,382★、`knowsuchagency/mcp2cli` 2,403★、`janwilmake/openapi-mcp-server` 904★ | Python/Node | 中 | 把任意 API/CLI 变成工具，替代逐应用写包装 |
| 包管理器清单（Omarchy 式） | pacman/AUR、apt、mise、winget、brew | 系统级 | 中 | 解决「机器上有什么 / 能装什么」 |
| Warp workflow 目录 | 410 个 spec | 无 | 低 | 可共享的参数化命令目录 |
| **ECC**（harness 增强层） | 262,999★；903 个 `SKILL.md` / 68 agent / 94 command；30+ 宿主目录 | 无运行时依赖（markdown + hooks） | 低（格式可直接复用） | **对照 / 灵感源**：多宿主分发的工业级样板，不引入其代码 |

补充发现：`epiral/bb-browser`（6,222★，"CLI + MCP server，用你自己的登录态控制 Chrome"）
比 CLI-Anything 的 `browser` 更契合 trimum 的自研 CDP 路线，可作为对照与备选。

**为什么 CLI-Anything 不是最优解**：它把「生态」理解成「为每个软件手写一个 CLI 包装」——
这等于用 79 个别人的独立项目来做 trimum 的生态面，版本、语言栈（Node/Rust）、质量、维护节奏都不受控；
而真正规模最大的两条通道（**Skills 17.7 万★**、**MCP 4 千 server**）它都只是「顺便支持」。
正确用法是把它当**目录/约定来源**（registry 字段、SKILL.md 组织、harness 方法论），而不是依赖。

---

## 3. 建议的四层战略

### L0 环境清单层（Omarchy 式，零包装）

- `trm env inventory`：扫描已装软件（pacman / apt / mise / winget / brew + PATH 探测）→ 输出「本机可用能力清单」。
- `trm env install <pkg>`：确认后调**系统包管理器**；trimum 不自建包仓库。
- **工具链大部分是「选装」**（见 §7.3）：清单同时表达「可装」与「已装」，首次安装引导逐项询问，默认全不装。
- 结论：**软件生态交给发行版**；trimum 只负责「知道有什么 + 要不要装 + 装完配置 + 受管地调用」。

### L1 协议层（MCP）——「会说 MCP 的服务」

- 按 `docs/MCP-INTEGRATION-PLAN.md` 落地：client（stdio / HTTP）+ `~/.trimum/mcp/<name>.json5` + ToolGateway 分层接入。
- 定位：SaaS / 远程 API 生态走这条；默认 deny-by-default。
- **2026-09-20 已落地 stdio 半边**（E2/M1+M2）：`mcp_client.py` + `mcp_registry.py` + `MCPDispatcher` + `trm mcp`；
  **2026-09-20 又落地策展导入器**（E2/M3）：`mcp_catalog.py` + `config/mcp-catalog.yaml`（232 条候选，`reviewed: false`）；HTTP/SSE 传输与空闲回收仍是 M4。

### L2 知识层（Agent Skills）——零代码的长尾

- 现状：`~/.trimum/skills/` 目录已在，分发（symlink / junction / copy 回退）已实现（E1），但目标根是**硬编码 7 个**。
- 要改：分发目标**按已探测到的宿主动态决定** —— 第三方 coding agent 是选装项，没装就不建目录（见 §7.3 / E6）。
- 补做：`trm skill list / import <repo|url>`，遵循 agentskills.io 规范，把外部生态的技能拉进本地再分发。
- 这是「让 Agent 会用所有软件」性价比最高的一层：**只写文档，不写适配器**；ECC（§1.3）用 903 个 `SKILL.md` 覆盖 30+ 宿主，证明这条路能走到工业级规模。

### L3 目录层（Warp 式可共享目录 + trimum 的编排）

- 定义 `workflows/*.yaml`（`name` / `command` / `tags` / `arguments` / `risk` / `requires`）作为**社区贡献前门**，
  编译进现有 Workflow / TARL 引擎（TARL 更强，但门槛高；YAML 是低摩擦入口）。
- `trm workflow import <repo>`：目录即生态，PR 即贡献。

### 统一底座（这才是 trimum 的差异化）

四层产出的**每一个能力**都注册进同一张表，并带 `trust` / `risk` / `requires` / `source_url` 元数据，
一律经 ToolGateway 分层（Policy → Agent 权限 → SecurityRule → JIT）+ 审计 + 凭据脱敏。
再补一个 Omarchy 式自描述面：**`trm commands --json --check`**，让 Agent 运行时枚举全部能力。

> 一句话：**别人比的是「能调多少软件」，trimum 比的是「调多少软件都不出事、且事后查得到」。**

---

## 4. 落到代码：已有 / 缺口

**已有（可直接复用）**：`trm` CLI 15 个命令组；文件化工具 `~/.trimum/tools/`；ToolGateway 六层检查 + 审计落盘；
Workflow/TARL 引擎；`~/.trimum/skills/` 目录；子 Agent 真实 spawn + cgroup。

**缺口（按优先级）**：

| # | 缺口 | 说明 |
|---|---|---|
| ~~1~~ | ~~`trm commands --all/--json/--check` + 命令元数据契约~~ | **已实现（2026-09-20，E1）**：命令面从 argparse 树推导（单一事实源）+ `cli/registry.py` 校验元数据 |
| ~~2~~ | ~~Skills 分发（symlink 到各宿主）~~ | **已实现（2026-09-20，E1/E6/E4）**：`skill_sync.py` 目标根按探测结果决定；**`trm skill import` 已补上**（`skill_import.py`，本地目录 / git 仓库 → `~/.trimum/skills/`） |
| ~~3~~ | ~~MCP client（M1/M2）~~ | **已实现（2026-09-20，E2）**：stdio 客户端 + 文件化注册（deny-by-default）+ 分发 + `mcp_call` 审计；策展导入器见 M3 ✅；HTTP 见 M4 |
| ~~4~~ | ~~通用 CLI 适配器（`--help` → 工具条目 + 风险分级）~~ | **已实现（2026-09-20，E4）**：`cli_adapter.py` + `trm tool import-cli`；只跑 `--help` 探测，产物默认 `enabled: false`，运行时再兜一层白名单（`generic_executor`） |
| ~~5~~ | ~~`trm env inventory/install`~~ | **已实现（2026-09-20，E3）**：9 个包管理器探测 + 已装清单 + 计划/执行分离（`env_toolchain.py`）；不自建包仓库 |
| ~~6~~ | ~~workflow 目录格式 + `trm workflow import`~~ | **已实现（2026-09-20，E4）**：`workflow_catalog.py`；声明只能把 risk 调高、不能调低；编译到 `WorkflowDefV2` 落 `~/.trimum/workflows/<id>/workflow.yaml` |
| ~~7~~ | ~~生态统一注册表 schema（`trust`/`risk`/`requires`/`source_url`/`author`）~~ | **已实现（2026-09-20，E4）**：`ecosystem.py` 的 `EcosystemEntry` + 风险分级器 + 校验器；三个导入器（tool / workflow / skill）产出同一种条目，共用一个 `ImportRefused` |
| ~~8~~ | ~~skills 分发目标按已探测宿主动态决定~~ | **已实现（2026-09-20，E6）**：`src/trimum_core/hosts.py`；`--all-hosts` 保留全量模式 |
| ~~9~~ | ~~首次安装引导 `trm setup`~~ | **已实现（2026-09-20，E6）**：`setup_wizard.py` + `trm setup`；选装清单见 `config/setup-catalog.yaml` |

---

## 5. 路线图（E0-E7）

| 阶段 | 内容 | 验收 |
|---|---|---|
| **E0** | 冻结本战略；同步修正 MCP 方案的取舍；确定首批 3 个用例 | 用户确认 |
| **E1** | 命令元数据契约 + `trm commands --json --check` + skills 分发 | 单测；`trm commands --json` 可被 Agent 直接消费 |
| **E2** ✅ | MCP **M0/M1/M2**（stdio client + registry + ToolGateway 接线 + `mcp_call` 审计）（2026-09-20 完成） | `mcp_client.py` / `mcp_registry.py` / `MCPDispatcher` / `trm mcp`；73 项新测试（含真协议 fixture server）；`trm mcp list` 可用 —— M3 ✅ 策展导入器（`trm mcp catalog import/list`，232 条候选）；M4 HTTP 待做 |
| **E3** ✅ | **环境层**：`trm env inventory` + `trm env install`（2026-09-20 完成） | `env_toolchain.py`；清单只读（risk: low）、安装必须确认、`--dry-run` 不执行、已装幂等；`tests/test_env_toolchain.py`（34）—— **`trm skill import` 未做，顺延到 E4** |
| **E4** ✅ | 通用 CLI 适配器 + workflow 目录（Warp 式）+ 导入器 + `trm skill import`（2026-09-20 完成） | `ecosystem.py` / `cli_adapter.py` / `workflow_catalog.py` / `skill_import.py`；三个导入器都是「dry-run 不落盘 / 第三方默认不启用（工具）/ 不覆盖已有 / 不执行导入物」；117 项新测试 |
| **E5** | 官方分发渠道：官网目录 + 官方根证书 + `.trmpkg` 校验器 + `trm install` | 签名校验单测（内置根/坏签名/哈希不符）+ 离线安装 dry-run |
| **E6** ✅ | 选装工具链模型 + 首次安装引导 `trm setup` + 宿主探测（2026-09-20 完成） | `hosts.py` / `setup_wizard.py` / `identity.py` / `config/setup-catalog.yaml`；47 项新测试；`trm commands --check` 50 条通过 |
| **E7** | 身份与多用户：证书 = 身份 + 能力清单；每用户独立 keystore | 见 §7.1 / §7.2 |

---

## 6. 风险与未决问题

1. **碎片化风险**：四条通道（MCP / skills / CLI / workflow）必须有统一注册表，否则又变成一堆散装配置。
2. **第三方信任**：CLI-Anything harness、MCP server、skill 都可能夹带执行逻辑 → `trust: third-party` + 默认禁用 + 显式确认。
3. **与「轻量」的张力**：每加一条通道都增加维护面；skills 层近乎零成本，MCP 层成本最高 —— 排序应为 Skills → MCP → CLI 适配器 → workflow 目录。
4. **未决**：是否保留 CLI-Anything 作为可选导入源（建议：保留为 import 源，不做默认，不写进默认安装）。
5. **未决**：`trm commands` 是否直接兼容 Omarchy 注释语法（建议：语义对齐，语法自成一套，避免绑定别人的格式）。
6. **未决**：L0 的首发平台顺序（Arch 优先，还是 Arch/Ubuntu/Windows 三线同做）。
7. **多用户下的私钥保护**：自签证书私钥若与证书同放 `~/.trimum`，同机其他用户可直接复制 → 需要文件权限 / DPAPI / 系统 keyring 支撑（未决）。
8. **证书能力清单与运行时的一致性**：证书里写的「可动用工具」必须真能被 ToolGateway 执行，否则证书只是文档（未决：证书 capability 与 `security_rule.py` 的合并顺序）。

---

## 7. 官方分发渠道与信任模型（官网 + 官方证书 + `trm install`）

> 需求来源：2026-09-20 用户确认 —— 官网提供官方 Agent / Tool / Workflow，「下载即用」，
> 由官方证书保证来源，用户不需要做「信任自签证书」这种选择。

1. **信任根内置**：trimum 随包内置官方根证书（`config/trust/trimum-root.crt`，公钥固定），
   官网产物由该根签发的证书签名 —— 等价于浏览器根证书 / 发行版软件源签名模型，用户天然信任、无需弹窗选择。
2. **包格式**：`.trmpkg` = `tar.gz` + `manifest.json5`（`name` / `type` / `version` / `requires` / `entry` / 文件 sha256）
   + `SIGNATURE` + `chain.pem`。
3. **校验顺序**：解包 → 逐文件 sha256 → 用**内置根**验证证书链 → 验证签名 → 检查 `requires` 前置依赖；
   任何一步失败即拒绝安装。
4. **安装 ≠ 授权**：官方包安装后按 `trust: official` 注册，运行时照走 ToolGateway 分层与审计。
   官方身份只回答「来源可不可信」，不回答「这条命令允不允许执行」。
5. **离线可校验**：只依赖内置根证书与包内签名，不依赖 TLS 信任链（防中间人、防官网被篡改）。
6. **CLI 入口**：`trm install <name>`（取官方目录）与 `trm install --file <pkg>`（本地包）共用同一校验器；
   目录索引本身也必须签名。
7. **降级路径**：`--allow-untrusted` 仅在用户显式要求时启用，安装后标记 `trust: untrusted`，
   运行期强制 confirm。

> 定位：该渠道是四层生态的**分发面**，不新增能力来源，只决定「生态件如何可信地到达本机」。

### 7.1 证书不只是「来源证明」，还是「身份 + 能力授权」

> 用户提示（2026-09-20）：证书里会包含安全相关内容，比如**可以动用哪些工具**；
> 并且**自签证书只有自己能用，别人想用需要再次自签**。

现有雏形已经印证了这句话：`src/trimum_core/agent_cert.py` 实现 official / self_signed / none 三档信任，
自签证书带 `machine_id`，换机器即降级为 `CONFIRM` —— 「别人拿走你的自签证书不能直接用」今天就已经成立。

要演进成三层，每层回答一个不同的问题：

| 层 | 回答的问题 | 载体 | 现状 |
|---|---|---|---|
| **来源**（provenance） | 这个包 / agent 是谁发布的、有没有被改过 | 官方根签发的证书 + 逐文件哈希 | 规划（E5） |
| **身份**（identity） | 这是哪个用户的实例（人 / 机器 / 组织） | 每用户独立密钥对 + `user_id` + `machine_id` | 雏形（`agent_cert.py`） |
| **能力**（capability） | 这个身份**允许动用哪些工具、风险上限多少** | 证书内 capability 清单（工具白名单 + `max_risk` + 有效期） | 待建 |

三条硬规则：

1. **证书可携带能力清单**（`tools` / `max_risk` / `expires_at` / `scope`）；运行时与 `security_rule.py`、ToolGateway 分层**取交集**，
   证书只做「收紧」，永不放宽内置策略。
2. **自签证书天生单用户**：绑定 `machine_id` + 用户 keystore；换人 / 换机自动失效，需**重新自签**（不是「导入」）。
3. **安装 ≠ 授权**（重申）：拿到官方包只证明来源可信；能不能执行，仍由本机策略 + 本用户证书共同决定。

### 7.2 用户体系与多用户（前瞻）

- 当前 `~/.trimum/` 是**单用户家目录模型**：天然一用户一份 `certs/`、`skills/`、`tools/`、审计日志。
- 已有雏形：agent 文件夹自带 `cert.json`（`~/.trimum/agents/<name>/cert.json`）已把「代码 + 证书 + 记忆 + 经验」打成一体，
  迁移与隔离的最小单位已经存在。
- 待设计（未决）：① 共享机器上 `/etc/trimum/`（系统级根 + 公共工具）与 `~/.trimum/`（用户私有）的边界；
  ② 审计日志的多用户归属（当前日志无 `user_id` 字段）；③ 私钥保护（文件权限 / DPAPI / keyring）；
  ④ 官方证书可否多用户共用（建议：官方证书共用，自签证书每用户各一份）。

### 7.3 首次安装引导与「选装」模型

> 用户提示（2026-09-20）：**这些软件以后是用户选装的**；将来要集成**全套开发者工具链**，大部分为选装，
> **第一次安装引导会问**；而且 trimum 将来可能自己做一个 coding Agent（参考 ECC），
> 所以**不能假设机器上装了 `claude` / `codex` / `opencode` 之类**，也不能假设它们会被实际使用。

- `trm setup`（**已实现，2026-09-20**）：首次运行引导 ——
  ① 选装工具链（`config/setup-catalog.yaml`，7 组 25 项，默认全不装，逐项确认，**只登记不安装**）；
  ② 生成用户密钥对 + 自签身份证书（`~/.trimum/identity/`，Ed25519）；
  ③ 探测已存在的宿主，按探测结果决定 skills 分发目标；④ 结果写入 `~/.trimum/config/setup.json5`。
  非交互（无 TTY 或 `--yes`）不提示，`--dry-run` 不落盘，`--skip STEP` 跳过单项。
- L0 因此从「扫描已装软件」升级为「**清单 = 可选装 + 已装**」：`trm env inventory` 回答「有什么」，
  `trm setup` 回答「要不要装」，两者共用同一份能力目录。
- **零预装可跑**（已实现且有测试）：trimum 本体不依赖任何第三方 coding agent；一个宿主都没有时，skills 只落到 `~/.trimum/agent-skills`。

---

## 8. 原始件（`tmp/research/ecosystem/`，已 gitignore）

| 文件 | 内容 |
|---|---|
| `omarchy-repo.json` / `omarchy-README.md` / `omarchy-tree.json` | Omarchy 元数据、README、全量文件树（2,116 条） |
| `omarchy-cli-manual.md` / `omarchy-ai-manual.md` | Omarchy CLI 手册、AI 章节（skills 分发与 mise 懒加载证据） |
| `omarchy-skill-command-metadata.md` / `omarchy-skill-install-scripts.md` | 命令元数据契约、安装脚本约定 |
| `warp-repo.json` / `warp-README.md` | Warp 元数据与 README |
| `warp-workflows-repo.json` / `warp-workflows-tree.json` / `warp-workflows-FORMAT.md` / `warp-workflow-sample.yaml` / `warp-workflows-README.md` | Warp workflow 目录格式与样例 |
| `anthropic-skills-README.md` / `anthropic-skills-repo.json` | Agent Skills 标准参考实现（177,179★） |
| `search-*.json` | GitHub 搜索快照（CLI→MCP 桥接、OpenAPI→MCP、通用适配器） |
| `ecc-repo.json` / `ecc-README.md` / `ecc-tree.json` | ECC（affaan-m/ECC，262,999★）元数据、README（105KB）、全量文件树（5,026 条） |
