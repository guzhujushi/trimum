# Contributing

> 协作口径以 `AGENTS.md` 为准；进度与待办以 `STATUS.md`（常驻区 + 追加日志）/ `TODO.md`（只留未闭环）为准。
> 注意：`STATUS.md` / `TODO.md` / `docs/OPERATIONS.md` 含个人主机与账号信息，**已移出 git 跟踪**（本仓库是公开的）。

## 开发状态

主线 = **§1 工程缺口（自用口径）**（见 `TODO.md`）；E7 自研编码智能体五片全闭、沙箱 S1–S6 全闭。
当前在推的队列：`cfm1`（非 CLI 确认通道）→ `pol1`（`LlmPolicyEngine` 接线）→ `dog1` → `ebpf1` → `dboot1`，另有 `cfg2`。
测试基线：全量 **`0 failed / 2169 passed / 4 skipped`**（`--collect-only` 2178）；剩 4 skipped = 2 条平台专有 + 2 条 mcp snapshot 缺件。

## 分支策略

**只有 `server` 一支**（= 默认 / 主分支）：日常只在 `server` 上提交、只推 `server`（`git push origin server`，SSH 直连）。
历史 `main` / `ubuntu` / `arch-linux` 三分支与「四分支 cherry-pick 收尾」**已废止**（2026-10-03 迁移后）。
旧历史归档在私有库 `guzhujushi/trimum-legacy`，本地 remote `legacy` + 分支 `legacy-archive` 仅作快照，不再开发。
本仓库**是公开的**：不提交密钥 / 真机 IP / 隧道名 / 个人运维细节（`STATUS.md` / `TODO.md` / `docs/OPERATIONS.md` / `.env` / `.codex/` 等已 gitignore）。

## 提交规范

`type(scope): 中文一句话`，`type` ∈ `feat` / `fix` / `chore` / `docs` / `refactor` / `test`；正文写"改了什么 / 为什么"。

```
feat(llm): 429 冷却改读 Retry-After（秒数 / HTTP 日期，缺失回退 60s，上限 300s）

- llm_router._retry_after_seconds(): 从 urllib/httpx 两类异常响应头取 retry-after
- tests/test_llm_router.py: 补秒数 / HTTP 日期 / 缺失 / 超上限 四条用例
```

不要再写 `[Phase X]` 前缀（Phase 0–3 时期的老约定）。`.env` 永不提交（已在 `.gitignore`）；机器本地配置（如 `.codex/`）也不入 git。

## 代码与文档风格

- Python 3.12；文件头 `from __future__ import annotations`；模块与公开函数写中文 docstring，重点写**为什么这么做**。
- 格式化**目标**是 `ruff` + `black`；**现状**：仓库里没有 ruff/black 配置、`.venv` 里也没装 ⇒ 提交前至少 `python -m py_compile <改动文件>` 并跑相关测试，别顺手整文件重排。
- UTF-8 无 BOM + LF；别用会写成 GBK 的工具写中文（Windows 侧口径见 `AGENTS.md`）。
- Shell 脚本放 `scripts/`，幂等可重跑；破坏性动作默认 `--dry-run`，`--apply` 才落地且带回滚。
- 临时文件一律进 `tmp/`（`*.bak_*`、`tmp/` 已忽略），根目录不留 `tmp_*`。
- **配置优先，不许硬编码**：路径 / 目录 / 端口 / 阈值这类值不许写死在代码里；解析顺序固定为
  **显式函数参数 > 环境变量 > 配置文件（`$XDG_CONFIG_HOME/trimum/config.yaml`）> 默认值**；
  配置缺失 / 坏文件 / 空项一律**静默走默认**；新增可配置项必须补「配置缺失走默认」用例并在文档写明键名
  （详见 `AGENTS.md`「配置优先，不许硬编码」）。

## 测试与验收

```bash
.venv/bin/python -m pytest tests -q --basetemp /tmp/trimum-pytest   # 全量（基线见上）
.venv/bin/python -m pytest tests/test_<模块>.py -q --basetemp /tmp/trimum-pytest
```

全量**必须**用 `.venv/bin/python`；`--basetemp` 走 `/tmp/...`（AF_UNIX 路径上限 108 字符，`tmp/` 下会让 `test_agent_spawn` 假挂）。
**验收口径**：① failed 集合逐条相同；② collect 增量必须等于新增用例数（别拿 passed 反推）。

- **实现与验收分权**：写实现的一方不写验收结论、不跑全量、不提交；验收方独立跑测试 + 接口校验 + 质量检查，末尾给 `VERDICT: PASS|FAIL`。
- 批量派活（qwen 实现 → 门禁 → ds 验收 → 通过才提交）走 `scripts/trimum-dev.sh`，口径见 `~/.codex/skills/trimum-dev/SKILL.md`：改动必须 ⊆ `allowed.txt`，越界即停手。
- 真机验收脚本：`scripts/accept_w1.py`(48/0) / `accept_e4.py`(43/0) / `accept_ipc_only.sh`(15/0) / `accept_s3.py`(35/0) / `accept_s4.py` / `accept_m4.py` / `accept_e7.py`。

## 平台口径（先判自己在哪台机器上跑）

- `uname -s` 得到 `Linux` ⇒ **真机侧**（Ubuntu / 天逸510S，7x24 常驻；开发目录 `~/trimum`，部署目录 `/opt/trimum`）。
- 只有 PowerShell、`$env:OS` = `Windows_NT` ⇒ **Windows 侧**（本地开发机；PowerShell **没有** `<` 重定向，复杂命令一律先写 `.sh` 文件再跑）。

两边的写文件 / 行尾 / 后台常驻 / 网络代理 / sudo 口径都不同，完整对照表见 `AGENTS.md`。真机上 **agent 不代跑 sudo**：需要 sudo 的活写成脚本交本人。

## Agent 开发标准（已按代码现状复核，2026-09-26）

### 目录：两套，别混

| 用途 | 路径 | 谁在用 |
|---|---|---|
| **拉起进程**（子 Agent 脚本） | `~/.local/share/trimum/agents/<agent_type>/main.py`（Windows 回退 `~/.trimum/agents/<agent_type>/main.py`） | `agent_launcher.py`（`AgentManager.spawn` 与 `AgentRuntime.start_agent` 共用） |
| **清单 / 证书 / 私有记忆** | `~/.trimum/agents/<name>/`：`agent.json` 或 `agent.json5` + `cert.json` + `memory/` | `agent_registry.py` / `agent_cert.py` / `context_manager.py` |

子进程输出**不走 PIPE**，追加写入 `<agents_root>/../agent-logs/<agent_id>.log`（PIPE 写满 64KB 会把 Agent 卡死）。

### 子 Agent 脚本契约（硬约束，见 `scripts/agent-template/main.py`）

- `argv[1]` = `agent_id`；环境变量 `TRIMUM_AGENT_ID` / `TRIMUM_AGENT_TYPE` / `TRIMUM_SOCKET_PATH`；
- 收到 `SIGTERM` 后尽快退出（超时会被 `kill`）；
- 入口**不是** `execute(request)` —— 需要请求-响应就走 socket：自己装 `AgentSocketClient` 连 `TRIMUM_SOCKET_PATH`；
- 起步：`cp scripts/agent-template/main.py <agents_root>/<agent_type>/main.py`，然后 `trm agent spawn <id>`（或 `POST /api/agents/spawn`）。

### `agent.json5` Manifest（真实字段见 `src/trimum_core/models.py:572`）

必填 `name` / `version` / `capabilities`；常用选填：

| 字段 | 说明 |
|---|---|
| `description` / `display_name` / `author` | 人类可读信息 |
| `entry` | 入口路径，默认 `./main.py` |
| `risk_level` | `low` / `medium`（默认）/ `high` / `critical` |
| `capabilities` | 能力名；`skill:<name>` 会由 `skill_router` 路由 |
| `depends_on` | 依赖的 CLI / MCP 工具 |
| `exec_allow` / `exec_deny` / `read` / `write` | 扁平权限声明（Ubuntu 预置 Agent 用这套） |
| `permissions` | 嵌套写法 `{read, write, exec, deny_exec}`（两套 schema 都支持） |
| `events` | `{publishes, subscribes}` |
| `system_prompt_path` / `system_prompt` | 长期提示词，省 token |
| `work_dir` | cwd jail 根路径；空 = 不限制 |
| `sandbox` | S2 内核层档位，**只能比全局档位更严，不能放宽**（`docs/SANDBOX-PLAN.md` §6.2） |

清单校验失败 → `TRM-3004 AGENT_MANIFEST_INVALID`。第三方 Agent 带 `cert.json` 走信任检查（`check_agent_trust` / `confirm_and_trust`），第三方工具**默认不启用**。

### `AGENT.md` 写什么

它是**给人看的行为说明**，不被代码当契约读取 ⇒ 写定位、职责、能力、通信（订阅/发布）、可调用工具、安全边界（可以 / 不可以）、长期记忆、依赖与配置、踩坑经验即可。

### 尚未实现（别按契约写）

`AgentRouter` 类**不存在**（只有 `skill_router.py` / `skill_loader.py` 的 docstring 提到）；`task.assigned` 事件**没有生产者**；`memory_bridge` / `experience_learner` 至今零调用点；`SystemMonitor` 从未被实例化。
⇒ 把这些写进 `AGENT.md` 时请标注「设计意图」，别写成现在就能用。

## 文档分工

`AGENTS.md` = 项目级指令（分支 / 真机 / 密钥 / 平台口径）；`docs/ARCH.md` = 架构；专题文档 `docs/CODING-AGENT-PLAN.md` / `docs/SANDBOX-PLAN.md` / `docs/LLM-ROUTING.md` / `docs/MULTI-USER-BOUNDARY.md`；
`STATUS.md` = **常驻区（就地小改）+ 追加日志（新进展只追加到文件末尾，不回填、不通读）**；`TODO.md` = **只剩未闭环 + 红线**，已完成项一律进 `STATUS.md`。
