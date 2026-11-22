# Agent 工单流水线规范（qwen 实现 / ds 验收）

> 状态：**2026-11-22 定稿**。本文是“怎样把仓库任务写成工单、交给子 Agent 窗口执行”的唯一真源。
> 它描述的是**开发派活流程**，不是 trimum 运行时里的 Agent 协议；运行时契约见
> `docs/architecture/agent-runtime.md` 与 `docs/CODING-AGENT-PLAN.md`。

---

## 1. 先回答：下一个窗口能直接开工吗

**分两种情况：**

- **拿到完整项目文件夹**（含本地私有交接件、`.venv`、`.env`，并在同一台真机上）：**可以开工**。
  入口是 `TODO.md` 的未闭环条目 + 本文的工单模板；不要先通读全仓。
- **只拿到公开仓库 clone**：**不够直接开工**。`AGENTS.md`、`TODO.md`、`STATUS.md`、
  `docs/OPERATIONS.md`、`docs/QWEN-PROMPTS.md`、`.env`、`.venv` 都不在公开仓库里。
  新窗口只能从 `README.md` / `docs/ROADMAP.md` / `docs/ARCH.md` 理解方向，拿不到当前任务队列、
  真机口径和测试基线。

**最小交接包**（缺一项就可能卡住）：

1. 仓库目录本身（`server` 分支，含未提交改动时先说明）。
2. `AGENTS.md`：项目级指令与真机口径。
3. `TODO.md` + `STATUS.md`：当前队列、最近进展、测试基线。
4. `docs/OPERATIONS.md`：真机、代理、隧道、sudo 等运维细节。
5. `.venv`（或可复现的安装环境）与 `.env`（模型 key；**只在本机，不进仓库**）。
6. Codex 的 `qwen` / `ds` profile 与 `codex-run` 包装（或等价启动方式）；没有 profile 时
   `scripts/trimum-dev.sh` 无法按角色启动窗口。
7. 本文：工单格式、白名单门禁、验收分权。

> 不要把 `.env`、真机 IP、隧道名、账号口令写进工单或提交。工单只写仓库内相对路径。

---

## 2. 角色与分权

| 角色 | 谁来做 | 职责 | 明确不做 |
|---|---|---|---|
| 派活方 | 人 / Plan Agent | 选任务、写 `task.md`、给落点与白名单、决定验收口径 | 不替实现窗口写代码 |
| 实现窗口 | qwen（qwen3.8-27b） | 只按 `task.md` 改白名单内文件 | 不跑全量测试、不写验收结论、不提交、不推 |
| 验收窗口 | ds / 另一个独立窗口 / 人 | 独立跑测试、看 diff、给 `VERDICT: PASS\|FAIL` | 不改实现；发现问题只报告 + 最小复现 |
| 提交 | 验收通过后由派活方或流水线 | 只 `git add` 白名单文件，提交到 `server` | 不把未验收改动混进提交 |

**硬规则：谁写实现，谁不验收。** 实现窗口写的测试只作为“被告方证据”，验收窗口必须自己跑一遍。

---

## 3. 工单目录与文件

每张工单一个目录，默认放在 `tmp/trimum-dev/<task-id>/`（`tmp/` 已 gitignore）：

| 文件 | 作用 | 必须 |
|---|---|---|
| `task.md` | 给实现窗口的完整提示词 | 是 |
| `verify.md` | 给验收窗口的独立判据 | 是 |
| `allowed.txt` | 允许改动的文件白名单，一行一个仓库相对路径 | 是 |
| `targets.txt` | 目标测试文件与参数，一行一条 | 是 |
| `commit-msg.txt` | 验收通过后的提交信息 | 是 |
| `task-fix.md` | 验收 FAIL 后就地修的补丁提示词 | 按需 |
| `logs/` | 实现 / 门禁 / 验收日志 | 运行时生成 |

流水线入口：`scripts/trimum-dev.sh`。用法：

```bash
scripts/trimum-dev.sh new    <task-id>
scripts/trimum-dev.sh run    <task-id>          # 默认后台，立即返回
scripts/trimum-dev.sh status <task-id>
scripts/trimum-dev.sh verify <task-id>          # 工作区已有改动时，只重跑验收
scripts/trimum-dev.sh fix    <task-id>          # 验收 FAIL 后，用 task-fix.md 再开一次实现
```

实现窗口默认走 `qwen` profile；验收窗口默认走 `ds`。换 provider 必须重开进程，
不要试图在同一个 Codex 进程里用 `/model` 换 provider。

如果仓库不在 `$HOME/trimum`，或 `codex-run` 不在 `$HOME/bin/codex-run`，先设：

```bash
export TRIMUM_DEV_REPO=/path/to/trimum
export TRIMUM_DEV_CODEX_RUN=/path/to/codex-run
```

`~/.codex/skills/trimum-dev/SKILL.md` 是操作细节与踩坑记录，属于**机器级**辅助件；
拿到完整项目文件夹但没有它时，本文 + `scripts/trimum-dev.sh` 仍可完成基本派活与验收。

---

## 4. `task.md` 模板（复制后填实）

```text
【任务】只改 <文件A>（必要时加 <文件B>），其余文件一律不许动。
【背景】<一句话说明为什么要改；不要贴大段架构文档>
【落点】<文件A>:<起始行>-<结束行> 的 <函数/类名>；签名/数据结构已内联在下面。
【现状】<把要改的代码原文或最小骨架贴进来>
【要求】
  ① <可验证的行为 1>
  ② <可验证的行为 2>
  ③ <边界/失败路径>
【硬约束】
  ① 不许全仓搜索、不许读 <模块X> 之外的源码；找不到落点就停下报告，不许自行扩大范围。
  ② 不许跑 pytest 全量、不许 git commit / push / checkout / restore / stash / clean / reset。
  ③ 不许整文件重写；只做最小 diff；改完即停，不做顺手优化。
  ④ 只允许 python -m py_compile <文件A> 做语法自检。
【输出】固定三段：
  ① 改动清单（文件:行号 + 一句话）
  ② 为什么这样改（≤3 行）
  ③ 交接给验收窗口：建议的测试命令 + 需人工确认的点
```

### 写工单的硬要求

- **落点必须写到函数级**，并把函数签名、关键数据结构、期望断言原文内联进提示词。
  实测：让 qwen 自己在仓库里找落点，会把 token 全花在读文件上，最后零产出。
- **一个模块一张工单**。改完即停，不跨模块顺手重构。
- 只列**允许改的文件**；新建文件也要逐条列进 `allowed.txt`。
- 需要读的源码越少越好；工单里已经给出原文的，明令“禁止再读源码”。
- 如果入口不存在（CLI 开关、配置键、公开函数参数都没有），先在工单里补入口，或把要求改窄；
  不要让实现窗口猜“从哪个公开入口进来”。

---

## 5. `verify.md` 模板

```text
【验收对象】<task-id>，工作区 diff 范围以 allowed.txt 为准。
【独立判据】
  ① 改动必须 ⊆ allowed.txt；越界直接 FAIL。
  ② 跑 targets.txt 指定的测试；再跑全量回归并与基线对比 failed 集合。
  ③ 检查公开入口 / 边界 / 失败路径是否真的可用，不只看实现窗口自报。
  ④ 涉及 CLI / UI 输出时，必须给终端实录。
【交付物】三件缺一不可：
  ① git diff --stat + 关键 hunk；
  ② 测试结果与全量对照（failed 集合逐条比、collect 增量）；
  ③ 需要人工确认的风险点。
【结论】最后一行必须是 VERDICT: PASS 或 VERDICT: FAIL。
```

验收窗口**不得改实现**。发现实现窗口顺手改了已验收文件时，用 `sha256sum` 钉死并直接判 FAIL。

---

## 6. qwen 额度与失败处理

- qwen 的额度约为 **10 次/分**；Codex 一个 turn 常要 5–15 次调用，连续派 3 个以上任务容易撞 429。
- 撞 429：等 1 分钟或换 `ds`，不要重试轰炸。
- 实现窗口撞额度后，可以改由 Codex 直接实现，但要在 `NOTE-impl-by-codex.md` 记录“本轮不是 qwen 实现”
  及相对 `task.md` 的偏离；**验收仍必须独立做**。
- 不要用“再跑一次”解决验收失败：先看 `verify` 的失败点；需要修就写 `task-fix.md`，并点名禁改已通过的文件。

---

## 7. 测试与提交口径

```bash
# 目标测试
.venv/bin/python -m pytest tests/test_<模块>.py -q \
  --basetemp /tmp/trimum-pytest -p no:cacheprovider

# 全量回归（验收窗口）
.venv/bin/python -m pytest tests -q \
  --basetemp /tmp/trimum-pytest -p no:cacheprovider
```

- 全量必须在**沙箱外**跑；`--basetemp` 必须在 `/tmp/...`（AF_UNIX 路径上限 108，`tmp/` 下会让
  `test_agent_spawn` 假挂）。
- 验收口径：**failed 集合逐条相同**；collect 增量等于新增用例数，不能拿 passed 反推。
- 提交信息走 `tmp/commit-msg.txt`，格式 `type(scope): 中文一句话`；只提交白名单文件，只推 `server`。

---

## 8. 当前基线与已知限制（2026-11-22）

- 真机内核：**Linux 7.0.0-31-generic**（Ubuntu 24.04.5）。
- 7.0 上已复跑全量（2026-11-22）：**2507 passed / 4 skipped / 0 failed**，用时约 140 秒。
  这是当前 7.0 基线；6.8 时代最后一次记录也是同一组数字。
- 7.0 只读自检已确认：Landlock **ABI 8**、seccomp `user_notif`、cgroup v2、`systemd-run --user`
  的 `MemoryMax` / `CPUQuota`、BTF、`CONFIG_BPF_LSM=y`、`CONFIG_SCHED_CLASS_EXT=y`。
  实际 BPF LSM / sched_ext 接入仍待 PoC，不要因为“配置为 y”就写成已实现。
- `unprivileged_bpf_disabled=2`、`perf_event_paranoid=3` 仍然成立；eBPF 监控仍走特权 helper。

---

## 9. 红线

- 不把密钥、真机 IP、隧道名、个人运维细节写进工单或提交。
- 不允许实现窗口扩大范围、全仓搜索、整文件重写、跑全量、做 git 事务。
- 不允许跳过验收直接提交；不允许把观测/审计失败变成业务失败。
- 不允许为了让测试变绿而放宽沙箱、审批或 fail-closed 语义。
