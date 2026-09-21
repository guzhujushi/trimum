# E7 — 自研编码智能体：规格与设计（2026-09-21 草案，待确认）

> 立项依据：`TODO.md`「🌐 生态战略」的 E7 项；参考调研件 `tmp/research/ecosystem/ecc-*`（`affaan-m/ECC`）。
> 本文是**设计层**产物：先定「做什么、不做什么、红线在哪、分几步走」，**本轮不含代码改动**。
> 与既有文档的关系：动作一律经 `ToolGateway` 四层（`docs/SECURITY-DEFENSE-PLAN.md`）、
> 编排复用 `WorkflowRuntime`（`docs/WORKFLOW-EXECUTION-PLAN.md`）、分发复用 `trm pkg`（`docs/PACKAGE-CHANNEL-OPS.md`）、
> 多用户边界见 `docs/MULTI-USER-BOUNDARY.md`。

## 1. 结论摘要（先看这段）

trimum 已经有「循环 + 工具 + 安全层 + 编排 + 分发」，**缺的不是引擎，是编码专用的三块拼图**：

| 缺口 | 现状（查代码得到） | 本片要补 |
|---|---|---|
| **编辑原语** | `file.write` 只能整文件覆盖或追加（`mode=w/a`）；全库无 `difflib`／补丁应用 | 按锚点替换 + 统一差异应用 + **会话级快照与回滚** |
| **验证闭环** | 没有「跑测试／构建／检查并解析结果」的一等抽象，循环只拿到原始标准输出 | 结构化「红／绿 + 失败清单」回灌循环 |
| **技能与规则运行时** | `SKILL.md` 只被分发到别的宿主；`skill.yaml`（旧）与 Agent Skills（新）两套互不相干 | 按需注入上下文 + 工具事件上的检查（钩子） |

外加第四块：**子 Agent 委派做实**（`agent_runtime` 的 spawn 仍是空壳，`task.assigned` 至今没有生产者）。

定位一句话：**E7 = 让 trimum 自己会改代码，且改得可审、可回滚、可验证**；不是再做一个「Claude Code 的复刻」。

## 2. 参考对象：ECC 到底是什么（事实，不是印象）

统计自 `tmp/research/ecosystem/ecc-tree.json` 与 `ecc-repo.json`（快照日 2026-09-20，262,999 星）：

| 事实 | 数字 |
|---|---|
| 仓库条目总数 | 5,026 |
| `SKILL.md` 个数 | **903**（`skills/` 目录 934 个文件） |
| `rules/` 文件数 | 144（通用 + 按语言分组） |
| 斜杠命令 | 94 |
| 宿主适配目录 | `.claude-plugin` / `.codex` / `.opencode` / `.cursor` / `.kiro` / `.agents` 等 |
| 文档 | 2,141 个文件（`docs/`，含多语言 README） |
| 自述定位 | 「agent harness operating system」 |
| 许可 | MIT；主语言 JavaScript（外加 Shell / Python / Go 的辅助脚本） |

**关键判断：ECC 没有自己的模型循环。** 它的四件套是 **Agent 定义／技能／规则／钩子**，
循环与工具执行都由宿主（Claude Code、Codex 等）提供。它真正卖的是：
① **内容分层**（子 Agent 定义、按需加载的技能、常驻规则）；
② **运行时挂钩**（工具事件上跑检查、在编辑前拦下）；
③ **安装与适配**（一套内容分发进 30+ 宿主）；
④ **学习与记忆**（从会话里抽「直觉」，按置信度回灌上下文；跨宿主的项目记忆库）。

### 抄什么

- **按需加载省上下文**：技能不是全塞进系统提示，而是命中才注入 —— 与 trimum 的 `context_compactor` 同向。
- **工具事件上的检查**：编辑文件前后可以拦一道（控制台日志、敏感文件、格式）。
- **跨宿主记忆交接**：同一份笔记换个宿主还能用。
- **内容与运行时分离**：技能是数据，加载 ≠ 执行。

### 不抄什么

- **不建内容农场**：903 个技能里绝大多数是「语言 × 主题」的组合产物；trimum 首发只做**少数几条**编码流程（测试驱动、审阅、排障）。
- **不用 Node/TypeScript 铺适配层**：那是 ECC 的宿主现实，不是我们的；trimum 的技能分发已经有 `trm skill sync`。
- **钩子不用 shell 脚本特权执行**：trimum 的等价物是**总线订阅 + 经网关的动作**（有审计、有策略），而不是绕过网关裸跑脚本。

## 3. 现状勘察：trimum 手里已经有什么

| 能力 | 模块 | 状态 |
|---|---|---|
| 交互循环（单步计划 → 执行 → 历史回灌，默认 20 轮） | `agent_loop.py`（`trm exec`） | ✅ 可用；模型走内置 HTTP 调 OpenAI 兼容端点（默认 deepseek），支持流式；无密钥时返回空串 |
| 工具面（文件／版本控制／命令／进程／系统／网络／环境／知识／通知／浏览器／文档／外部工具） | `tool_dispatchers.py` | ✅ 注册在 `ToolRegistry`，**全部经 `ToolGateway` 四层** |
| 安全层（策略 / 风险 / 安全规则 / 能力交集 / 确认 / 威胁扫描 + 审计 + 脱敏 + 目录牢笼 + 行为基线） | `tool_gateway.py` 等 | ✅ P0 已闭环（2026-09-21） |
| 事件编排（事件驱动剧本、自动触发按性质分档、运行记录） | `workflow_runtime.py` | ✅ W1 闭环；运行记录只在内存 |
| 意图翻译与拆解（TARL 三段式、低匹配转 Planner） | `transform_agent.py` / `planner_agent.py` / `workflow_listener.py` | ✅ 2026-09-21 接线（穿插项步骤 C） |
| 子 Agent | `agent_runner.py` / `agent_registry.py` / `agent_manager.py` / `agent_runtime.py` / `agent_cert.py` | ⚠️ 入口与身份齐了，**spawn 仍是空壳**、`task.assigned` 无生产者 |
| 技能（两套） | 旧：`skill_loader` / `skill_router` / `skill_executor`（`skill.yaml` 工具组合）；新：`skill_import` / `skill_sync`（`SKILL.md` 分发） | ⚠️ 两套互不相干，且**都不被运行时加载进循环** |
| 学习与记忆 | `learning_engine.py`（daemon 学习回环在用）／`experience_learner.py` + `memory_bridge.py` | ⚠️ 后两者**全库零调用点** |
| 分发与身份 | `trmpkg` / `pkg_install` / `pkg_index` / `capability` / `identity` | ✅ E5 闭环（含能力清单运行期交集） |
| 上下文管理 | `context_manager.py` / `context_compactor.py`（纯规则，预算 3,000 字符） | ✅ 可用，但**没有代码感知** |
| 沙箱 | Landlock / Seccomp | ❌ **未做**（`TODO.md` 里仍是 Phase 4） |

一句话：**引擎、工具、安全、分发都在，缺的是「改代码」这件具体活儿的一套动作与判据。**

## 4. 定位裁决

### 做

1. **编辑原语**：`replace_anchor`（按锚点替换）＋ `apply_difference`（应用统一差异）＋ 每次改动的**快照 + 回滚**。
   理由：`file.write` 整文件重写既费 token 又抹掉差异，出问题无法精确撤销 —— 这直接违背「可审计」的定位。
2. **验证闭环**：把「跑测试 / 构建 / 静态检查」变成一等动作，产出结构化的「红／绿 + 失败清单 + 证据（命令、退出码、关键输出行）」，
   回灌到循环的下一步决策里。**红线：验证命令同样经网关**，不是智能体的后门。
3. **技能与规则运行时**：把 `SKILL.md` 与规则文本按**命中才加载**注入上下文；把「钩子」实现成**总线订阅 + 网关动作**。
   首发只落 3 条流程：测试驱动、代码审阅、排障。
4. **子 Agent 委派做实**：`agent_runtime` 真启动子 Agent，`task.assigned` 有生产者；子 Agent 继承父的**权限交集**与**预算**。

### 不做（写清楚，防止范围失控）

- 不重写模型客户端（继续 OpenAI 兼容端点，不引第三方代理框架）。
- 不做编辑器／集成开发环境插件。
- 不做 30+ 宿主的适配器农场（`trm skill sync` 已有；ECC 那种内容体量不是我们的目标）。
- 不在本片接记忆／学习（`memory_bridge` / `experience_learner`）—— 那是下一片的事，先让改动可回滚、可验证。
- 不做「自动提交版本库」：`git commit` / `git push` 永远要人点。

## 5. 架构与模块

```text
人：trm code "<任务>"
        │
        ▼
  agent_loop（已有循环，20 轮上限）
        │  每轮：单步计划 → 动作 → 证据回灌
        ├── 新增：编辑原语 ── patch_ops.py（锚点替换 / 统一差异 / 快照 / 回滚）
        ├── 新增：验证闭环 ── verifier.py（测试 / 构建 / 检查 → 红绿 + 失败清单）
        ├── 新增：说明加载 ── instruction_loader.py（技能 / 规则按需注入）
        └── 做实：子 Agent ── agent_runtime（spawn + task.assigned + 权限交集）
        │
        ▼
  ToolGateway（既有四层，不新增旁路）→ 审计 / 事件总线 / 事件编排
```

| 模块（拟） | 职责 | 复用 |
|---|---|---|
| `patch_ops.py` | 锚点替换、统一差异应用、改动前快照、按运行回滚；越界路径（版本库内部、证书目录）直接拒 | `file` 工具与 `file_trust` |
| `verifier.py` | 登记「这条项目怎么验证」（测试命令、构建命令、检查命令）；跑一次 → 解析 → 结构化结论 | `shell`／`process` 工具、`ToolGateway` |
| `instruction_loader.py` | 扫描技能与规则 → 关键词／标签命中 → 注入上下文；记录「本轮用了哪条技能」 | `skill_loader`（旧）、`skill_import`（新）、`context_compactor` |
| `coding_agent.py`（薄） | 把上面四块串成一个编码任务会话：会话状态、改动清单、验证记录、退出码 | `agent_loop` |

接口草签（先定形状，实现再定细节）：

- `PatchResult = {path, added_lines, removed_lines, difference, snapshot_id, status, reason}`
- `VerificationResult = {kind: test|build|lint, command, exit_code, verdict: green|red|unknown, failures: [{file, line, message}], evidence_lines: [...]}`
- `SessionRecord = {task, changes: [PatchResult], verifications: [VerificationResult], started_at, ended_at}`

## 6. 红线（写进代码与测试）

| 红线 | 落点 |
|---|---|
| 不新增执行通道 | 编辑、验证、技能里声明的命令全部经 `ToolGateway`，照走策略 / 风险 / 安全规则 / 能力交集 / 确认 / 审计 / 脱敏 / 目录牢笼 |
| 改动必须能回滚 | 每次编辑先存快照 + 生成统一差异；**没有差异的「改动」不许当成成功**；回滚按运行编号一次撤销 |
| 保护路径直接拒 | 版本库内部、证书目录、审计目录、密钥文件：不因「模型要求」而放行（与 `trm install --remove` 的越界拒绝同一口径） |
| 不自动提交版本库 | 改完给人看差异；`git commit` / `git push` 只能人发起 |
| 测试不过不许声称完成 | 验证结果必须回灌循环；模型自称「已修好」不算证据（与 W1「失败不伪装」同一口径） |
| 子 Agent 不越权 | 权限取父的交集（只收紧）、步数与 token 预算受限、每次派发留审计 |
| 技能与规则是数据不是代码 | 加载不执行；技能里写的命令要过网关与确认；`--dry-run` 下不落盘 |
| 没有模型就说没有 | 未配密钥 / 断网 → 明确报错退出，**不许假装完成任务** |

## 7. 分片实施计划（每片独立可用、可验收）

### 步骤 1 — 编辑原语与会话留痕

- `patch_ops.py`：`replace_anchor(path, anchor, replacement, *, count=1)`（锚点不唯一即拒，沿用本轮纪律）、
  `apply_difference(path, difference)`（统一差异，校验上下文行）、`snapshot(path)` / `rollback(session_id)`。
- 预览与执行分离：`--dry-run` 只出差异不落盘（与 `trm env install` / `trm install` 同一口径）。
- 验收：锚点不唯一拒 / 上下文行不符拒 / 保护路径拒 / 回滚把文件还原到字节一致 /
  差异行数与实际改动一致；测试 `tests/test_patch_ops.py`。

### 步骤 2 — 验证闭环

- `verifier.py`：项目级验证登记（默认探测：`pytest` / `cargo test` / `go test` / `npm test` / 构建命令），
  解析器把输出归一成「红／绿 + 失败清单」，失败项带文件与行号。
- 验收：绿色 / 红色 / 命令不存在 / 超时 / 被网关拒 五条路径；被拒时结论必须是 `unknown` 而非 `green`（不许把「没跑成」当通过）。

### 步骤 3 — 技能与规则运行时

- `instruction_loader.py`：扫 `~/.trimum/skills/` 与仓库内技能目录，按任务关键词命中注入；
  首批三条流程：测试驱动、代码审阅、排障（内容小、可读、可测）。
- 钩子：以总线订阅实现「编辑前检查 / 编辑后提示」，**动作经网关**，默认只提示不阻断（阻断要显式开启）。
- 验收：命中才注入（未命中不占上下文）/ 注入内容有长度上限 / 钩子只提示不改写 / 技能文本里的命令不自动执行。

### 步骤 4 — 子 Agent 委派做实

- `agent_runtime`：spawn 真启动（用既有 `AgentRunner` 入口）、`task.assigned` 事件补生产者、
  子 Agent 结果回到父会话；权限交集 + 预算（步数 / token）+ 审计。
- 验收：父派子跑通；子越权（超出父能力）被拒；子崩溃不影响父；预算耗尽明确停止并上报。

### 步骤 5 — 命令行入口与真机验收

- `trm code "<任务>"`（命令面 78 → 79）：`--dry-run`（只出计划与差异）、`--skill <名>`、`--timeout`、`--yes`；
  退出码口径与 `trm workflow run` 一致（做了就是 0，被拒/失败就是非 0）。
- 真机 Ubuntu 验收脚本 `scripts/accept_e7.py`：只读任务 / 小改动任务 / 测试驱动任务 / 越界拒绝 / 回滚 五组。

> 顺序理由：没有可回滚的编辑，验证再准也不敢用；没有验证，技能再多也判断不了「改对了没有」；
> 子 Agent 放最后是因为它会放大前四步的每一个缺陷。

## 8. 风险与未决问题（需要裁决）

1. **沙箱与「安全优先」的正面冲突**：编码智能体会大量写文件、跑测试，而 Landlock / Seccomp 至今未做。
   问题：是否把沙箱提到 E7 之前（否则「安全优先」在编码场景下只剩策略与审计，没有内核级边界）？
2. **首发能力边界**：智能体是否允许**自动改文件 + 自动跑测试**（高风险但有用），还是一律先出差异等人点？
   建议：默认「出差异 + 跑只读验证」，写盘要确认；`--yes` 才自动落盘。
3. **命令入口**：独立命令 `trm code` 还是 `trm exec --code`？建议独立命令（语义不同：一个通用问答执行，一个编码任务会话）。
4. **工具调用方式**：继续「让模型吐单步 JSON」还是切**原生工具调用**（模型侧支持函数调用）？
   建议本片先不切（改动面小、可离线降级），但把工具 schema 输出预留好（`trm commands --json` 已经是雏形）。
5. **两套技能是否合并**：`skill.yaml`（可执行的工具组合）与 `SKILL.md`（说明性文本）—— 合并成一套，还是明确分工
   （前者是「能力」，后者是「说明」）？建议明确分工，不合并。
6. **改动留痕存哪**：会话记录进 `~/.trimum/sessions/`（用户私有，与多用户边界一致）还是随项目走？建议用户私有。

## 9. 与其它片的边界

- **E5 分发**：编码智能体本身作为一个官方包分发时，走既有 `.trmpkg` + 内置根 + 能力清单（不新造渠道）。
- **W1 编排**：「跑测试 → 改代码 → 再跑」这类多轮流程可以编译成剧本，但**首发不做**（先让人在循环里看着）。
- **P0 安全链**：威胁扫描 / 处置映射与编码智能体共用同一个网关与审计，不另立一套。
- **多用户**：会话记录、快照、审计都落在 `~/.trimum/` 下，保持「用户私有」这条既有边界。

---

> **下一步（等裁决）**：上列 §8 的 1 / 2 两条决定「先做沙箱还是先做编辑原语」，其余按 §7 顺序推进。
> 裁决后本文转为「实施计划」，按片提交，每片带测试与真机验收。
