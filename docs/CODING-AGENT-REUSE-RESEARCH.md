# 编码智能体调研：ECC 适合吗？+ 可直接复用的开源项目（2026-09-21）

> 站位：回答 `TODO.md`「🌐 生态战略 → E7 自研编码智能体」与 `docs/CODING-AGENT-PLAN.md` 的前置问题。
> 四个待答问题：① ECC 如何做成一个 coding Agent；② 参考 `~/.trimum/agents/` 别的 Agent 的文件格式能不能套上；③ 还有没有其他可直接复用的功能相近的开源项目；④ **先想清楚 ECC 适合吗**。
> 本文只做**调研与判断**，不含代码改动。事实层材料在 `tmp/research/coding-agents/` 与 `tmp/research/ecosystem/ecc-*`（均已 gitignore）。

## 0. 结论摘要（先看这段）

| 问题 | 结论 |
|---|---|
| ECC 能「做成」coding Agent 吗 | **不能**。ECC 不是 agent，是**装进别人家 agent 的插件**：68 个 `agents/*.md`（提示词）+ 292 个技能 + 规则 + 宿主钩子，外加一个 Node 安装器。README 自述 *"ECC works through each harness's normal configuration"*（`ecc-README.md:718`）—— **模型循环与工具执行全由宿主提供**。 |
| 那 ECC 有什么用 | **当内容源**（MIT，文本可改写借鉴），以及「跨宿主共享记忆」的形态参考。**不要引入它的代码**：Node CLI / Rust `ecc2/` / Python `src/llm/` 三处都不是编码循环。 |
| 参考 `~/.trimum/agents/` 格式能套上吗 | **套不上**。逐字段对照见 §2.2：`AgentManifest` 里只有 `name` / `description` 对得上；`entry` / `capabilities` / `permissions` / `events` / `risk_level` / `work_dir` 在 ECC 侧**全部无对应**。ECC agent 是「被宿主读进上下文的 md」，trimum agent 是「`entry` 指向可执行体的目录」。 |
| 有没有可直接复用的 | 有，但**很小**：`python-unidiff`（统一差异解析，MIT，活跃）可当依赖；`grep-ast`（代码感知检索）可选（366★、16.5 个月未推、带 tree-sitter 两个依赖）。其余只能**抄设计**（aider / gptme / cline / crush）。见 §3。 |
| 对本轮 E7 的最大影响 | **换参考对象**：编辑原语与验证闭环看 **aider**（Python、同语言、13 种编辑格式与真实失败模式）；ECC 在这两块**一点东西都没有**。 |

一句话：**ECC 适合当「内容素材库」与「分发形态的对照物」，不适合当引擎、不适合当格式标准、更不适合当编码智能体本体。**

## 1. ECC 是什么：事实与三处数字修正

### 1.1 元数据（GitHub API 快照 2026-09-20）

| 项 | 值 |
|---|---|
| 仓库 | `affaan-m/ECC`（默认分支 `main`） |
| star / forks / watcher | 262,999 / 39,353 / 1,350 |
| 许可 | MIT |
| 主语言 | JavaScript（仓库内另有 Python 与 Rust 子项目） |
| created / pushed | 2026-01-18 / 2026-09-20 |
| open issues / size | 199 / 51,295 KB |
| 自述定位 | *"The agent harness performance optimization system"* |

**star 可疑度核查（只陈述事实）**：star : watcher = 194.8，与同类项目同处一个区间 —— `obra/superpowers` 267.8、`dyoshikawa/rulesync` 728.0、`wshobson/agents` 126.1、`anthropics/skills` 157.3。**所以「刷星」这条在本批材料里不成立**。唯一可说的是：8 个月到 26.3 万 star，而材料里**没有任何 star 时间序列数据**可以判断曲线形状。

### 1.2 三处数字修正（既有文档需要改）

| 既有说法 | 事实 | 口径 |
|---|---|---|
| 「903 个 `SKILL.md`」 | **真实技能数 292**。903 是重复计数：`skills/` 292（源）+ `docs/` 518（多语言译本）+ `.kiro/` 43 + `.agents/` 39 + `.cursor/` 11（宿主目录副本） | `ecc-tree.json` 按 `path -like '*SKILL.md'` 分组统计 |
| 「30+ 宿主适配目录」 | **ECC 自述是 7 个 harness**（Claude Code 主、Codex 支持、Cursor/OpenCode Beta、Copilot 仅指令级、其余实验）。**「30+」是另一个项目 `rulesync` 的自述** | `ecc-README.md:1258-1266`、`:237` |
| 「2,141 个文档文件」 | 其中 777 ja-JP + 621 zh-CN + 190 es + 190 tr + 84 ko-KR + 78 zh-TW + 51 pt-BR 是**译本** | `ecc-tree.json` 按 `docs/` 二级目录分组 |

> 口径提醒：ECC 自己的 `agent.yaml` 只编目 **155 个技能 / 94 个命令**，与 README 的 292 / 94 也不一致。**以后引用 ECC 规模一律带出处，别再用「903」。**

### 1.3 它到底由什么构成（tree 事实，5,026 条目）

- **内容层**：`agents/` 68 个扁平 md；`skills/<name>/SKILL.md` **292** 个；`rules/` 122 个文件；`commands/` 94 个 md；`legacy-command-shims/` 13 个；`contexts/` 3 个。
- **宿主适配层**：`.claude-plugin/`（插件 + marketplace 清单）、`.codex-plugin/`、`plugins/ecc/.codex-plugin/`、`.opencode/`、`.cursor/`、`.kiro/`、`.agents/`、`.pi/`、`.trae/` 等目录副本。
- **安装/运维层**：Node CLI（`package.json`、`install.sh` / `install.ps1`、npm 包 `ecc-universal@2.2.2`）、`scripts/` 295 个文件、`manifests/`、`schemas/`（13 个 JSON Schema）。
- **README 未说明的两处可执行体**：`ecc2/`（Rust crate：session / daemon / tui / worktree / harness-eval）与 `src/llm/`（Python 包 `llm-abstraction` 0.1.0，多 provider，依赖 `anthropic` + `openai` SDK）。`ecc2/README.md` 自述是 **alpha**：*"it is not the finished ECC 2.0 product yet"*，并明确列出还缺 *"explicit agent-to-agent delegation"* 与 *"richer multi-agent orchestration"*。

### 1.4 ECC 有没有自己的运行时？没有

依据（README 与原件）：

- `ecc-README.md:139`：*"works best with Claude Code today, has a supported Codex sync path, and provides capability-limited adapters for Cursor, OpenCode, Gemini, Zed, GitHub Copilot, Antigravity, Qwen, and other harnesses"* —— 是**配置宿主**，不是自己跑。
- `ecc-README.md:718`：*"ECC works through each harness's normal configuration"*。
- hooks 的真实形态（`hooks/hooks.json`）：`PreToolUse` 上的 `matcher` + 一长串 `node ...` 命令，**由宿主触发的 shell 命令**。ECC 所谓的「运行时挂钩」= 宿主事件 + shell 脚本，不是自己的循环。
- `.claude-plugin/plugin.json` / `.codex-plugin/plugin.json`：ECC 自己就是**发给两个宿主的插件包**（前者 `skills: ["./skills/"]` + `commands`，后者 `hooks: "./hooks/codex-hooks.json"` + `mcpServers: "./.mcp.json"`）。

**这也解释了为什么「把 ECC 做成 agent」不成立**：ECC 没有可被复用的执行体，只有被别的执行体读入的文本。

## 2. 「把 ECC 做成 coding Agent」三条路，逐条算账

### 2.1 三条路

| 路径 | 做法 | 结果 |
|---|---|---|
| **A. 包成 trimum 子 Agent** | 把 ECC 的 `agents/*.md` 转成 `~/.trimum/agents/<id>/agent.json5` + `main.py` | **空壳**。字段大量对不上（§2.2）；提示词没有执行体；而且 `system_prompt_path` 在 trimum 代码里**今天没有任何消费者**（`src/trimum_core/models.py:584` 只有字段定义，全库无读取点，已 grep 核实） |
| **B. 当上下文内容注入** | 把 ECC 的 skill / rule 文本喂进 trimum 的循环 | ✅ **唯一成立的用法**，正对 E7 步骤 3（`instruction_loader`）。但 ECC 的钩子/命令形态（shell 特权执行）与红线冲突，规则要重写 |
| **C. 接它的代码当引擎** | 用 Node CLI / Rust `ecc2` / Python `src/llm` 当运行时 | ❌ 三处都不是编码循环：安装器 / alpha 控制面 / LLM 抽象层。接进来只换来 **Node + Rust 依赖**，换不来编辑与验证能力 |

### 2.2 格式对照：ECC agent 定义 vs trimum `AgentManifest`

trimum 权威字段表：`src/trimum_core/models.py:560-604`；目录约定：`C:\Users\guzhu\.trimum\agents\TEMPLATE.md`（`agent.json5` + `AGENT.md` + `main.py` + 可选 `prompts/`、`memory/`）。ECC 侧：`agents/<name>.md` = YAML frontmatter + markdown 正文。

| trimum `AgentManifest` | ECC 对应物 | 结论 |
|---|---|---|
| `name` / `description` | agent md frontmatter `name` / `description` | **有对应** |
| `system_prompt_path` / `system_prompt` | agent md 的**正文** | 近似对应（内联 vs 外链） |
| `exec_allow` / `exec_deny` | frontmatter `tools: Read, Grep, Glob, Bash` | 形式相近、语义不同：ECC 是「允许哪些宿主工具」，trimum 是「允许/禁止哪些命令前缀」 |
| `capabilities` | 无（只有正文文字 + README 的命令映射表，是文档不是机器字段） | **无对应** |
| `permissions{read,write,exec,deny_exec}` / `read` / `write` | 无（等价物在 hook / GateGuard / 宿主 sandbox 里，不在 agent 定义里） | **无对应** |
| `events{publishes,subscribes}` | 无（ECC 无事件总线；只有宿主事件单向触发） | **无对应** |
| `entry`（可执行入口，默认 `./main.py`） | 无 | **无对应（关键差异）** |
| `risk_level` / `work_dir` / `version` / `author` / `depends_on` | 无 | **无对应** |
| — | frontmatter `model: opus` | trimum **没有** per-agent 模型字段 |

生效机制也完全不同：ECC 的定义由**宿主**读取并执行（模型循环、工具调用、钩子触发都在宿主）；trimum 的定义由 `trimum_core` 读取、由 `entry` 指向的 `main.py` / `module:Class` 执行；跨 Agent 走事件总线；安全边界（权限 / 风险等级 / 目录牢笼）写在 manifest 里。**结论：ECC 的格式不是「trimum 子 Agent 格式的另一种写法」，是另一种东西。**

### 2.3 一件已经做完的事：ECC 的分发机制，trimum 已经有了

`src/trimum_core/skill_sync.py` + `src/trimum_core/hosts.py`：

- `KNOWN_HOSTS` **14 个宿主**：`.agents`、`.claude`、`.codex`、`.pi`、`.gemini`、`.hermes`、`.cursor`、`.opencode`、`.kimi`、`.qwen`、`.zed`、`.kiro`、`.trae`、`.openclaw` —— 已经覆盖了 ECC 树里出现的全部宿主目录。
- 机制：**一份源**（`SKILL.md`）→ 按检测结果符号链接 / junction 进各宿主技能根；`TRIMUM_SKILL_TARGETS` 可覆盖，`all_hosts=True` 恢复全量；`~/.trimum/agent-skills` 永远是兜底目标。
- 代码注释直接写着这是 *"the wider set of ECC-style harnesses"*。

**所以「学 ECC 做多宿主分发」这个动作在 trimum 里已经完成了，差的只是内容。** 分发机制不需要再从 ECC 学第二遍。

## 3. 其他可直接复用的开源项目

### 3.1 同赛道（内容 / 分发层）对照：ECC 不是最优选

| 维度 | `affaan-m/ECC` | `obra/superpowers` | `dyoshikawa/rulesync` | `wshobson/agents` | `anthropics/skills` |
|---|---|---|---|---|---|
| star / watcher | 262,999 / 1,350 | **289,517 / 1,081** | 1,456 / 2 | 39,847 / 316 | 177,404 / 1,128 |
| 载体 | md 内容 + Node CLI + 双宿主插件 | 纯 md 技能库 + 各宿主脚本 | **Node CLI 生成器（一份源 → 各宿主配置）** | md 单源 + `make generate` | md 技能 + 规范 + 模板 |
| README 明写宿主数 | 7（主 Claude Code + Codex） | **16** | **30+** | 7 | 3 |
| 许可 | MIT | MIT | MIT | MIT | 混合：`docx`/`pdf`/`pptx`/`xlsx` 是 **source-available，不可抄** |
| 是不是 agent 运行时 | 不是 | 不是 | 不是 | 不是 | 不是 |

结论：
- **四个都不是 agent 运行时**，都只能提供内容 / 分发能力 —— 与 §1.4 的判定一致，这个赛道没有「拿过来就是智能体」的东西。
- 论载体，trimum 真正该看的是 **rulesync**（一份源生成 30+ 宿主配置的成熟 CLI）。但 trimum 的 `trm skill sync` 已经覆盖了**技能**这一个维度，rulesync 值得看的是它还把 **rules / commands / subagents / hooks / permissions / mcp / ignore** 一起做成了产物类目。
- **superpowers 已经在本机启用**（见 `AGENTS.md` 的「流程层」），star 还比 ECC 高；内容体量上 `wshobson/agents`（自述 202 agents / 183 skills / 105 commands）也大于 ECC。
- 抄文本之前先看许可：`anthropics/skills` 里有 4 个技能是 source-available。

### 3.2 引擎 / 组件层：能直接 `import` 的只有两块

（全表与逐仓库依据见 `tmp/research/coding-agents/draft-A-engines.md` §1–§4）

| 排序 | 项目 | 可复用部件 | 接入成本 | 关键事实 |
|---|---|---|---|---|
| ① | `matiasb/python-unidiff` | `PatchSet` → `PatchedFile` → `Hunk` → `Line`：**统一差异的解析与校验**（行号、增删、git mode、symlink/submodule、二进制、CR/控制字符边界） | **低**（直接依赖） | MIT；`pushed_at` 2026-09-15（活跃）；**只 parse 不 apply** |
| ② | `Aider-AI/grep-ast` | 代码感知检索（命中行 + 所在函数/类 + 上下文块），正对「上下文没有代码感知」的缺口 | 低（需 `tree-sitter` + `tree-sitter-languages`） | 366★；`pushed_at` 2025-05-08（**约 16.5 个月未推**）；只能从 git 装 |
| ③ | `gptme/gptme`（**抄设计**） | `patch` / `morph` 增量编辑、before/after tool-call hooks、`--tools` 白名单、`--output-format json` | 中 | MIT；Python 3.10+；**自带循环与工具执行，只能抄不能接** |
| ④ | `cline` / `charmbracelet/crush` / `anomalyco/opencode`（**抄设计**） | 工具生命周期钩子做审计与策略、逐工具 allow/deny + permission queue、**plan（只读，默认拒改）/ build（可写）双权限梯度** | 高 | Node（crush 是 Go）；crush 许可是 **FSL-1.1-MIT（非 OSI）** |

**不建议直接接**（材料层面的事实理由）：
- `RooCodeInc/Roo-Code`：`archived = true`（已关停）。
- `continuedev/continue`：README 自称 *"no longer actively maintained and is read-only"*。
- `techtonik/python-patch`：`pushed_at` 停在 2022-01（约 4 年 8 个月）、`license` 为空、无 README。
- `SWE-agent/SWE-agent`：官方 README 推荐改用 mini-swe-agent。
- `openai/codex` / `aaif-goose/goose`：README 里没有部件级信息（只有安装 / 登录 / 扩展）。
- `containers/bubblewrap` / `google/nsjail`：Linux 内核特性（命名空间 + seccomp + pivot_root），Windows 无对应；只可作**未来沙箱设计**参考。

### 3.3 与本轮 E7 最相关的一个：aider（源码级事实）

aider 是与 E7 功能最接近的项目（Python、编码智能体、编辑 + 验证 + git 全套）。源码级事实（树 sha `5dc9490…`，抓 30 个文件，详见 `draft-A-engines.md` §6）：

- **编辑格式有 13 种**（`--edit-format` 取值）：Search/Replace 块（`editblock`）、统一差异（`udiff`）、整文件（`whole`）、V4A patch（`*** Begin Patch` / `*** Add File:`）、`architect`、`editor-diff`、`editor-whole`、`diff-fenced`、`udiff-simple` 等。
  → **对我们最直接的一条：一种差异格式不够用。** E7 步骤 1 只提了「锚点替换 + 统一差异」两种，正好是 aider 13 种里的 2 种。
- **解析失败怎么办**：全部 `raise ValueError` → 把错误反射回模型重来，`max_reflections = 3`，**没有自动重新解析**。这正是 E7 步骤 2「失败清单回灌循环」的现成形态。
- **落盘路径**：**自己解析、自己写盘**，不调 `patch(1)`（`io.write_text` 5 处 + `apply_updates()` 四步流水线）。
- **代码里两处反面教材**：`search_replace.py:438-439` 的**唯一性检查被注释掉了**；`editblock_coder.py:183` 有一段无条件 `return` 的死代码，使 fuzzy 匹配永不可达。
  → E7 把「锚点不唯一即拒」写成纪律，而 aider 恰恰**关掉了**这个检查。**这是设计张力，不是抄 bug 的问题**：太严 → 反复重试烧 token；太松 → 改错地方。判据得我们自己定。
- **repo map**：`repomap.py` 867 行；tree-sitter + `grep_ast` + `networkx.pagerank`（函数内 import）+ diskcache；命中行按 `line[:100]` 截断。
- **验证闭环**：`linter.py` 三合一 lint，把 `# Fix any errors below` + `tree_context` 回灌给模型；**注意顺序：先 `auto_commit` 再 `confirm_ask`**。
- **依赖事实**：`pyproject.toml` 不内联依赖，三层 `pyproject → requirements.txt(489 行) → requirements.in(50 行)`，注释里还有「为躲开 matplotlib 而单独用 networkx」「为躲开 pywin32 而不带 `litellm[proxy]`」这类取舍。
  → 「依赖要少」这条红线上，**aider 是反面例子**：它是个自带 400+ 行依赖的完整应用。
- **可复用性**：`[project.scripts]` + `packages.find include=["aider"]` 说明它是正经可安装包，但材料里**没有库级 API 文档**；硬耦合在 `aider/io.py`、`base_prompts.py`、`shell.py`。低耦合候选是 `search_replace.py` 的匹配策略与 `editblock_coder.py:364-657` 的纯函数族。
- **红线冲突（关键）**：aider **自动提交版本库**，而且 `auto_commit` 发生在 `confirm_ask` **之前**。trimum E7 红线是「`git commit` / `git push` 永远要人点」。→ aider 只能**抄原语与失败处理**，不能接它的流程。

## 4. 对 E7 的影响与建议（供裁决）

### 4.1 结论

1. **ECC 不适合做成 coding Agent**，也不适合当格式标准或引擎。它适合当**内容素材库**（MIT 文本可改写）与「跨宿主记忆 vault」的形态参考。既有文档里对 ECC 的三处规模描述需按 §1.2 修正。
2. **E7 的参考对象应换成 aider**（编辑原语、验证回灌、失败模式），而不是 ECC。在 E7 §1 列出的三块缺口里，ECC 只在「技能与规则运行时」上沾边，而且那部分的钩子形态与红线冲突。
3. **可直接复用的清单很短**：`python-unidiff`（依赖）；`grep-ast`（可选依赖，注意维护状态）；其余（aider / gptme / cline / crush / opencode）**抄设计**。

### 4.2 建议动作（都不改代码，先把方向定下来）

- `docs/CODING-AGENT-PLAN.md`：§2 的三处规模数字按 §1.2 修正；§7 步骤 1 把「编辑格式」从 2 种扩成「先定 1 主 1 备 + 解析失败回灌」；§8 增加一条裁决项「aider 的『唯一性检查被关掉』要不要照抄」。
- `TODO.md` E7 项：参考对象由「ECC」改为「aider（主）+ gptme / cline（辅）」，ECC 降级为内容素材来源。
- **不建议**：引入 Node / Rust 运行时；搬 ECC 的 shell 钩子；一次性导入 292 个技能。
- 仍待裁决的还是 `CODING-AGENT-PLAN.md` §8 那两条：① 沙箱（Landlock / Seccomp）是否提到编码智能体之前；② 首发是否允许自动改盘 + 自动跑测试。

## 5. 材料与口径

| 材料 | 位置 |
|---|---|
| ECC 元数据 / README / 文件树 | `tmp/research/ecosystem/ecc-{repo.json,README.md,tree.json}`（快照 2026-09-20） |
| ECC 关键文件原件 | `tmp/research/ecosystem/ecc-files/`（`agent.yaml`、`agents/planner.md`、`skills/tdd-workflow/SKILL.md`、`hooks/hooks.json`、两套 `plugin.json`、`ecc2/README.md`、`pyproject.toml` 等） |
| 候选项目元数据 / README | `tmp/research/coding-agents/*-{repo.json,README.md}`（快照 2026-09-21，19 个对象） |
| aider 源码级材料 | `tmp/research/coding-agents/aider-tree.json` + `aider-files/`（30 个文件，sha `5dc9490…`） |
| 引擎/组件事实草稿 | `tmp/research/coding-agents/draft-A-engines.md`（747 行） |
| 内容层事实草稿 | `tmp/research/coding-agents/draft-B-content-layer.md`（576 行） |
| 抓取脚本 | `tmp/research/fetch-coding-agents{,2}.ps1`、`fetch-ecc-files.ps1`、`coding-agents/fetch-aider.ps1` |

**明确的材料缺口（不许脑补）**：ECC 的 `ecc2/`、`src/llm/`、`schemas/`、`manifests/` 内容未读；没有 star 时间序列 / fork 来源 / traffic 数据；除 aider 外**没有**各项目的依赖清单；`search-skill-dist.json` 只有 2 条结果，不足以做同赛道排名。

---

> 本文是**调研与判断**，不是实施计划。裁决后，方向性改动并入 `docs/CODING-AGENT-PLAN.md`，进度写入 `STATUS.md`。