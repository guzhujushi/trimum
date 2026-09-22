# trimum — 待办清单

> 最后更新：2026-09-22
> **本文件只留「未闭环」的待办 + 红线 + 模型分工。** 已完成的历史进度（P0 / E1–E7 / M0–M4.5 / W1 / 沙箱 S1–S3 / 穿插项 A–C 等）一律在 `STATUS.md`（追加式日志，见其「## 日志」），本文件不再重复叙述。
> 测试基线：本地 **1664 passed / 6 failed / 23 skipped**（09-22 `trm memory import/export` 之后，6 条失败 = 既有宿主基线）；真机 Ubuntu 开发树 1098/11/2；S3 合成树 1645/16/4（16 条均宿主/合成树产物，非 S3）。
> 分支：`server`，**已与 `origin/server` 同步**（最近业务提交 `01819e9` = `ask --image` + `memory import/export`，2026-09-22 22:11 推；本轮文档提交紧随其后），其后为 2026-09-22 真机纳管相关提交（见 `STATUS.md` 同日日志）。日常只推 `server`，`main` / `ubuntu` / `arch-linux` 里程碑收尾时同步；推送前开代理 `127.0.0.1:7993`。
> 标签：`【Qwen】` 交我算（免费，单次小任务）/ `【DS】` deepseek-flash（复杂件）/ `【本人】` 需 sudo 或产品决策，agent 跑不了。**跑法与 Qwen 提示词见文末两节。**

## 一句话现状

P0 安全响应链 / E5 分发渠道 / 穿插三项已收口；沙箱 **S1**（已 `apply`）+ **S2**（收口）+ **S3**（三档，真机 35/0）已落地，**TCP 已收口**（`http: disabled`）。当前主线 = **E7 自研编码智能体**（待裁决两条后开工）+ 沙箱收尾。

## 未闭环待办（按优先级）

### 1. E7 自研编码智能体（下一主线）【DS】
- 规格 + 设计已出：`docs/CODING-AGENT-PLAN.md`；**待裁决两条【本人】**：沙箱是否提前 / 首发是否允许自动改盘 + 自动跑测试。裁决后按「五步分片」落地（编辑原语 → 验证闭环 → 技能运行时 → 子 Agent 委派 → 命令行入口与验收）。
- 前置调研完成：`docs/CODING-AGENT-REUSE-RESEARCH.md` —— ECC 不适合做 coding Agent（它不是运行时，自己就是宿主插件，格式对不上 trimum 子 Agent）；**参考对象建议改为 aider**；可直接复用的只有 `python-unidiff` / `grep-ast`。
- **另两条未决（不阻塞开工，设计时一并定）**：是否改用原生工具调用；会话记录存 `~/.trimum/sessions/` 还是随项目走（建议用户私有）。
- 验收脚本 `scripts/accept_e7.py` 待写（对标 `scripts/accept_s3.py` 的做法：能跑就给 N/0，跑不了如实说）。

### 2. 沙箱（E7 前置，S1/S2/S3 已落地）
- S1 系统级加固：真机已 `apply` 并在位（`scripts/harden_trmd_unit.sh`，默认 dry-run，`--apply` 才装，失败自动回滚）。
- S2 施加点收口：已落地（`sandbox_exec`，7 个 spawn 点，fail-closed + 审计留痕）。
- S3 seccomp 三档：已落地（`l1`/`strict`/`off` + 与 Landlock 联动，真机验收 35/0）。
- **剩余（【本人】，需 sudo，agent 跑不了）**：
  - 真机 4 条命令对照（`docs/SANDBOX-PLAN.md` §10.6）。
  - **开发树整树同步**：`~/trimum/src` 与 `/opt/trimum/src` 两棵树都要整体同步到 HEAD（别只挑几个文件装）；`sudo bash /tmp/sync_opt_tree.sh --dry-run` → 满意后 `--restart`（`--rollback` 整树还原）。
  - `sudo bash /tmp/trm_env_install_real.sh`（root 真执行路径，幂等）。
- **剩余（可派 agent）**：
  - `TaskRegistry.SHELL` 派生的子进程（走 `spawn_exec`）**仍未收口**（S2 起挂着，7 个点里的第 8 个）【DS】。
  - S4 子 Agent 资源边界（`systemd-run --user` transient：`MemoryMax` / `CPUQuota` / `TasksMax` / `NoNewPrivileges` / `SystemCallFilter`）→ S5 可选档（特权 helper / Docker / bwrap profile）【DS】。
  - `trm status` / `trm doctor` 还没把 Landlock + seccomp 状态摆上台面（眼下只能从审计与日志看）【Qwen】。
- 真机验收脚本：`accept_w1.py`（48/0）/ `accept_e4.py`（43/0）/ `accept_ipc_only.sh`（15/0）/ **`accept_s3.py`（35/0，覆盖 S2+S3）**；合成树跑法（`PYTHONPATH` 必须指 `.../src` 这个**导入根**，指到 `.../src/trimum_core` 会让子进程静默退回旧树）见 `docs/SANDBOX-PLAN.md` §11.6。

### 3. CLI 进阶（按顺序）
1. CLI 别名自定义（`.trimumrc` 配置文件）【Qwen】
2. 自动补全脚本（bash / zsh / fish）【Qwen】
3. 确定性字段 confidence 三级分流 —— `TransformResult.is_certain` / `needs_confirmation` / `needs_planner` 目前**零调用**（0.7 / 0.4 阈值只写在属性里，`workflow submit` 自己另写一套比较）【Qwen】
4. API Key Manager（key 现在散在 6 处各自读 env）【Qwen】

> 已完成（见 `STATUS.md`）：B4 `security revoke` / C1 `ask` Ctrl+C / F2 CLI-daemon 集成测试 / `ask --image` 多模态 / `memory import|export`。

### 4. LLM 路由遗留（清单同源：`docs/LLM-ROUTING.md` §8）
- **跨进程限流**：令牌桶在进程内，daemon 与 CLI 各 9 次/分 ⇒ 换 `FileTokenBucket`（文件锁 + 共享状态 `~/.trimum/llm-throttle.json`，接口已收口）【DS】
- **token 维度计量**：交我算还有 300k tokens/分、1B tokens/周 两个维度，现在只限了「次数」⇒ `attempt` 返回值带 usage、累计进 `stats()`（`agent_loop` 已有 `TokenUsage`）【DS】
- 429 的 `Retry-After`：现在按状态码给固定 60s，没读响应头【Qwen】
- `trm doctor` 显示路由表：现在只显示「env 有没有」，不显示「每个角色实际用谁」（实际路由靠 `llm_env_dropin.sh --check`）【Qwen】
- 成本账本：agent 角色走收费的 `deepseek-flash`，值得按天记调用次数 / 花费【Qwen】

### 5. P2 杂项（随时穿插）
- daemon 部署形态二选一（`trmd.service` root / 用户态路径）【DS】
- 桌面 / WebSocket 确认通道（`SecurityAgent.confirm()` 目前只有 CLI）【DS】
- 内置剧本运行记录只在内存（环形 200 条，重启即丢）⇒ 落盘；`trm workflow status|log` 仍是桩【DS】
- 内置剧本只有落盘式开关（`trm workflow enable <id>`），没有运行期「原地开关」【Qwen】
- `src/agent-sdk` 端到端测试与打包验证（`tests/` 至今零覆盖）【Qwen】
- SonarQube 重扫 + 归档报告【Qwen】；真机 Arch Linux smoke【本人】
- `LlmPolicyEngine` 骨架未接线（正则 → LLM 混合）【DS】
- 启动失败退出路径：**HTTP 开着的 daemon 启动失败仍走 uvicorn 自己的 `sys.exit(3)`**，可能被 `ContextManager` 的 aiosqlite 非 daemon 线程拖住（TCP 预检那两条是 `sys.exit(3)`、中途致命那条已改 `os._exit(3)`；真机同类现象见 `docs/SANDBOX-PLAN.md` §9.3.8 发现 1）【DS】
- 总线历史只有内存 100 条（重启即丢）、无优先级 / 背压 / ack / 重试 / 死信【DS】
- 官网服务端托管（E5 遗留：域名 / 托管 / CI = 产品决策，暂缓）【本人】

### 6. 未开工子系统（别误判为 bug）
- eBPF 告警 `security.ebpf_alert` / 性能熔断 `security.fuse_triggered` / 审计断链检测 `security.audit_breach`（`SecAudit.verify_chain()` 已实现但无人调用）【DS】—— 完整设计在 `docs/SECURITY-DEFENSE-PLAN.md`，代码里只有常量占位。
- 记忆桥：`memory_bridge` + `experience_learner` 至今**零调用点**（`memory.*` 整条空转）【DS】—— 架构见 `docs/MEMORY-ARCH.md`。
- 系统监视：`SystemMonitor` 从未被实例化，`system.heartbeat` 空转；`docs/SYSTEM-MONITOR.md` 示例里的 `event_bus.emit()` 这个 API 不存在【DS】。
- 子 Agent 真启动：`agent_runtime` 的 spawn 仍是 Stub（`task.assigned` 无生产者，`agent.status_changed` 无消费者）【DS】。
- `DEFAULT_INDEX_URL` 仍是占位（`https://trimum.dev/packages/index.json5`，本机无服务端）【本人】。

### 7. 安全收尾（三条都未处理）
- 本仓库 `.git/config` 的 origin URL 里是**明文 GitHub token** ⇒ 建议轮换 + 改用 credential helper（AGENTS.md 的 `GITHUB_TOKEN` 用法不受影响）【本人】
- 本机 `.env` 里存了真机 sudo 口令（`USER_PASSWORD`）⇒ 建议给这台机配一条 NOPASSWD 白名单【本人】
- `~/.trimum/.env` 是只含 `OPENAI_*` 的老 stub（加载器已修成「按 key 叠加 + 仓库 `.env` 权威」）⇒ 建议删掉，免得再被误选【本人】

### 8. Ubuntu 真机常驻（2026-09-22 新增；背景见 `STATUS.md` 同日日志）
- **隧道重启后自动恢复**（授权与在线已完成：`vscode.dev/tunnel/tianyi`、`status` = Connected）。需**决策** + 一条 sudo：
  `sudo loginctl enable-linger guzhujushi`（用户级 systemd 服务没 linger 起不来）；且**开机时 gnome-keyring 是锁的**（token 存在 keyring 里），光装 `code tunnel service install` 重启后仍要人工授权 ⇒ 二选一：
  ① **空口令默认 keyring**：把 `login.keyring` 备份后重建（不落盘口令，任何会话都能读 token）；
  ② **0600 口令文件 + 开机解锁的 user service**：保留现有 keyring，但机器上要存登录口令。【本人决策】
- 省电脚本**剩余步骤**（mask 睡眠 target + 停 avahi/cups/cups-browsed/sysstat）：要从 **SSH** 重跑 `sudo bash /tmp/ubuntu_slim_desktop.sh --apply`（在桌面终端里跑会被 `disable --now gdm3` 连带杀掉，只剩半吊子状态；脚本头部已写红线）【本人】
- 真机本地屏幕黑屏 ⇒ 脚本已补 `systemctl start getty@tty1`（`gdm` 与 `getty@tty1` 互斥，见 `STATUS.md` 同日日志），重跑即恢复文字登录提示【本人】
- 备用通路：code-server + frp + Nginx 反代 `vs.guzhujushi.cn`（基础设施已备好；**tunnel 这条路用不到域名**）【DS】
- `trm codex-proxy`：qwen 撞 429 自动降 `ds`（方案 B2，见 `docs/CODEX-MODEL-POLICY.md` §4）【DS】
- 真机 sudo NOPASSWD 白名单（本机 `.env` 现明文存着真机 sudo 口令，见「安全收尾」）【本人】

### 9. 开发环境分工与迁移（2026-09-23 盘点）
- **裁决：GPU / CUDA 开发留在本机**（本机 = RTX 5060 Laptop 8GiB / 驱动 592.01；真机只有 Intel UHD630 核显、**无 CUDA**）⇒ PyTorch / 训练类一律不进真机；真机定位收窄为「7x24 常驻服务 + 无 GPU 的日常开发（CLI / 后端 / 沙箱 / 隧道）」。【已裁】
- 阿里云（`8.145.36.108`，乌兰察布，2 vCPU / **1.6Gi 内存仅剩 580Mi** / 20G 盘用 58% / 已开机 33 天）迁移候选，待拍板：
  | 服务 | 现在 | 建议 | 理由 |
  |---|---|---|---|
  | gitea（4.3M 数据） | 阿里云 `:3000` | **可挪真机** | 不在 nginx 站点里（无公开域名）⇒ 走 Tailscale 即可；挪走能救云端内存 |
  | alist（5.0M 数据） | 阿里云 `:5244`，`pan.guzhujushi.cn` | 可挪真机（需 frp 反代回云端） | 个人文件列表，但域名要走 frp 回源 |
  | myblog（FastAPI/uvicorn） | 阿里云 `myblog` 站点 | **留云端** | 公开站点，家里网络抖动即掉线 |
  | frps / nginx / caddy | 阿里云 | **必须留** | 公网入口 + 证书终结（frps 7000/7500/8322） |
  | 阿里云的 VS Code tunnel | `code.guzhujushi.cn` | 待确认，可能可关 | 与真机 `tianyi` 隧道重复；关掉省 1.6Gi 机器的内存 |
- 【本人】**阿里云 `frps.toml` 的 `auth.token` 太弱（短、纯字典词），且 2026-09-23 被误写进本仓库（公开）⇒ 必须视为已泄露，尽快轮换**（轮换要同步所有 frpc 客户端：真机那条必须一起改，否则隧道断）。
- 【红线】把真实密钥写进仓库（本轮已踩一次：阿里云 frp token）⇒ 密钥只能记「位置 + 形状」，不写值；已写入的要**轮换**，不能只删字面值。
- 【本人】本机两个监听进程待确认（非管理员拿不到命令行）：`100.124.243.30:8080`（python 3.14，绑在 Tailscale IP 上）、`0.0.0.0:57322`（node，`D:\New Folder\node.exe`）—— 是什么服务、要不要挪真机？
- 【DS】真机装 Clash/Mihomo 客户端（复用现有订阅）**替代** `~/bin/with-proxy` 这条「经 Windows 笔记本」的迂回路径（Tailscale DERP 中继，慢 4–10 倍、且依赖笔记本开机）。

## 红线（写进代码与测试）

- 卸载只删**登记过**的路径，且必须落在 `TYPE_ROOTS` 期望目录下；越界即拒。
- 内置 agent 目录不可被卸载删掉；卸载不碰 `certs/` / `audit/` / `memory/`。
- 破坏性动作：`--dry-run` 恒不执行；非交互无 `--yes` 必 abort。
- L4 常开前提：只读命令（`cat /etc/ld.so.preload` / `crontab -l` / `systemctl status` / `ls -la ~/.ssh/` 等）不再误命中（真阳/真阴表 `tests/test_threat_signatures.py`）。
- 剧本自动触发：**取证类开** / **处置类保持 `enabled=False`**（处置必须由人发起）/ **自动触发不派子 Agent**（事件触发的非取证步骤一律 SKIPPED）；`enabled` 只决定「事件要不要跑」，**不能**放宽步骤闸门。
- 导入类（E4）：导入不执行 / `--dry-run` 不落盘 / 非交互要 `--yes` / 第三方工具默认不启用 / 不覆盖已有（除非 `--force`）。

## 🤖 模型分工（Qwen / deepseek-flash）

**怎么读标签**：`【Qwen】` = 单次小任务，够用且免费（`scripts/codex-model.ps1 qwen`）；`【DS】` = 上 deepseek-flash（`scripts/codex-model.ps1 ds`）；`【本人】` = 要 sudo 或要拍产品决策，agent 跑不了。
**不会敲命令行就用这两个**：`scripts\codex-qwen.cmd`（Qwen）/ `scripts\codex-ds.cmd`（DS）—— 双击或直接敲路径即可。
**为什么不能全靠 Qwen**：交我算 10 次/分，而 Codex 每次调用 ~15k tokens、一个 turn 十几次调用 ⇒ 几秒就撞 429；且 Codex **没有**「限流自动降级」的开关（证据 / 替代方案：`docs/CODEX-MODEL-POLICY.md`）。
**⚠ 2026-09-22 复盘（踩过的坑）**：`/model` 只改**模型名**、**不改 provider** —— 在 `ds` 会话里填 `qwen3.8-27b`，甚至填 provider 名 `sjtu-jiaowusuan`，都会被 DeepSeek 以 `The supported API model names are deepseek-flash, deepseek-v4-pro` 拒掉。**换 provider 必须重开进程**：`.\scripts\codex-model.ps1 qwen`。

| 任务类型 | 模型 | 怎么跑 |
|---|---|---|
| 文档回填 / TODO-STATUS 同步 / 提交号 / 格式与行尾修正 | 【Qwen】 | `codex-model.ps1 qwen -Exec "..."` |
| 加改单元测试、跑全量、单文件小重构（验收标准明确） | 【Qwen】 | 同上 |
| 新 CLI 子命令 / 脚本与语法自检 / 日志与证据整理 / 只读调研 | 【Qwen】 | 同上 |
| 沙箱施加点（Landlock / seccomp / fail-closed）、并发与竞态（socket / IPC / 限流 / 文件锁） | 【DS】 | `codex-model.ps1 ds` |
| 架构裁决、跨模块重构、长链路调试、真机切换与回滚设计 | 【DS】 | 同上 |
| 需要 sudo、要动真机、要拍产品决策 | 【本人】 | —— |

**待裁决（2026-09-22）**：环境变量 `JIAOWOISAN_API_KEY` 要不要跟着 provider 一起改名（`JIAOWOSUAN_API_KEY`）？它会牵动 `src/`（`llm_router.py` / `doctor.py` / `health.py` / `security_config.py`）、`tests/`、`scripts/llm_env_dropin.sh` 与真机 drop-in —— 建议**只加新名、保留旧名作别名**，别让真机 daemon 起不来。【本人】

---

## Qwen 任务提示词（复制即用）

**统一前缀（每条都带上）**：

```text
先读 STATUS.md 顶部「当前状态」+ TODO.md 对应条目，再动手；只改该任务涉及的文件，不做无关重构。
全量回归：python -m pytest tests -q --basetemp tmp/pytest-tmp -p no:cacheprovider
（基线 1664 passed / 6 failed / 23 skipped；6 条失败是既有宿主基线，不算回归）
收尾：TODO.md 勾选 + STATUS.md 末尾追加一条日志（含提交号）；只提交、只推 server；
提交信息写进 tmp/commit-msg.txt，然后 git commit -F tmp/commit-msg.txt。
```

### Q1 — `.trimumrc` 别名【Qwen】

```text
给 trm 加 .trimumrc 别名配置：读 $TRIMUM_HOME/.trimumrc，回退 ~/.trimumrc，再回退项目根的 .trimumrc；
格式自己定一种（TOML 的 aliases 表，或「一行一条：别名 = 命令」），并把格式写进 docs/。
落点：src/trimum_core/cli/main.py，在 argparse 解析之前展开 argv。
要求：
① 只替换首个子命令位置，别动参数里的同名字符串（比如 trm exec -- gs 不许展开）；
② 别名与已有命令名冲突时报错并以退出码 3 结束；
③ 只展开一层，不递归；
④ 新增 tests/test_cli_alias.py：展开 / 冲突 / 无配置文件 / 不递归 四条。
验收：新测试全绿，且 trm commands --check 仍 ok（别名不算新命令，命令数不变）。
```

### Q2 — shell 补全脚本【Qwen】

```text
给 trm 写 shell 补全：新增 trm completion <bash|zsh|fish> 子命令（补全脚本打到 stdout）。
命令 / 子命令 / 选项清单必须从 src/trimum_core/cli/registry.py 现算，别手抄（会漂移）；文件名补全走当前目录。
要求：
① 补全脚本内容不要出现中文；
② 三档都要能直接 source / eval 不报错；
③ 新增 tests/test_cli_completion.py：三档都能吐脚本 + 关键子命令名齐全（含 ask、workflow submit、memory import）；
④ 在 docs/OPERATIONS.md 补 3 行用法。
验收：新测试全绿 + trm commands --check 仍 ok。
```

### Q3 — confidence 三级分流接线【Qwen】

```text
把 TransformResult 的三级判定变成唯一口径。现在 is_certain（>=0.7）/ needs_confirmation（0.4~0.7）/
needs_planner（<0.4）三个属性零调用，而 src/trimum_core/cli/commands/workflow.py 的 _handle_submit
自己另写了一套阈值比较。
要求：
① 把手写比较换成这三个属性，阈值本身不许改；
② 检查 trm ask 的派发路径是否也走同一判定，不一致就对齐，并在日志里写清改了什么；
③ 在 transform_agent.py 的属性上标明「口径只有这一处」；
④ tests/test_transform_agent.py 补边界用例（正好 0.4 / 正好 0.7）；
⑤ 别改 docs/TARL-SPEC.md 的语义描述。
验收：tests/test_transform_agent.py + tests/test_cli.py 全绿，全量无回归。
```

### Q4 — API Key Manager【Qwen】

```text
统一 API Key 管理。现在 key 散在 agent_loop.py / experience_learner.py / doctor.py / health.py /
llm_router.py / security_config.py 各自读环境变量。
要求：
① 新增 trm key set|list|test|rm，存储落 ~/.trimum/keys.json（权限 0600，绝不进仓库）；
② 读取优先级：显式参数 → keys.json → 环境变量；现有 env 通路必须继续可用（真机 daemon 靠它起）；
③ list 只输出掩码（如 sk-…a1b2），任何输出都不得回显完整 key；
④ test 真发一次最小请求验证可用；
⑤ 不新增第三方依赖（能 stdlib 就 stdlib）；
⑥ 测试：掩码正确 / 优先级 / 权限非 0600 时拒绝读。
验收：新测试全绿 + trm doctor --json 里能看到每个 key 的来源（env 还是 keys.json）。
```

### Q5 — 429 读 `Retry-After`【Qwen】

```text
src/trimum_core/llm_router.py 现在按状态码固定等 60s，改成读 Retry-After。
要求：
① 有 Retry-After 就用它（秒数与 HTTP 日期两种格式都要认），没有才回退 60s；
② 加上限（建议 300s）防呆，超上限就按上限；
③ 只改退避这一处，别动路由优先级与回退链；
④ tests/test_llm_router.py 补：秒数 / HTTP 日期 / 缺失 / 超上限 四条；
⑤ 日志里打出实际等待秒数。
验收：tests/test_llm_router.py 全绿，全量无回归。
```

### Q6 — `trm doctor` 显示路由表【Qwen】

```text
trm doctor 现在只显示「env 有没有」，不显示「每个角色实际用谁」。
要求：
① trm doctor --json 增加 llm_routes：角色 → provider / model / 用哪个 env key / key 是否就位；
② 人读输出加一块小表格；
③ 路由表从 llm_router 现算，别写死；
④ 不打印 key 明文；
⑤ 测试（tests/test_cli_commands.py）：三个角色都在 + 缺 key 时标 missing。
验收：新测试全绿 + 本机 trm doctor 肉眼过一遍。
```

### Q7 — 成本账本【Qwen】

```text
agent 角色走的是收费的 deepseek-flash，要能按天看调用次数与花费。
要求：
① 每次调用追加一行到 ~/.trimum/llm-usage.jsonl（时间 / 角色 / provider / model / prompt+completion tokens / 估算花费）；
② 单价表放 config/llm-pricing.yaml，缺了不报错，只记 token 不算钱；
③ 新增 trm cost today|month --json；
④ 不联网、不新增依赖；
⑤ 测试：追加一行 / 缺单价表 / 按天汇总 三条。
验收：新测试全绿 + 日志里给一次真实样例（没有就写没有，别造）。
```

### Q8 — 把沙箱状态摆上台面【Qwen】

```text
缺口见 docs/SANDBOX-PLAN.md §10.8 / §11.7：trm status 与 trm doctor 现在都看不出 Landlock / seccomp 在哪一档。
要求：
① 显示三项：Landlock 档（readonly / 工作区可写 / off）、seccomp 档（l1 / strict / off）、S1 daemon 加固 drop-in 在不在；
② 状态从运行时真实配置现算（sandbox_exec / seccomp_exec 已有单一口径状态词表，见 §10.3），别读死文件；
③ 拿不到就显示 unknown，不许崩；
④ --json 里加 sandbox 段；
⑤ 测试（tests/test_cli_commands.py）：三档各一次 + 缺配置 → unknown。
验收：新测试全绿；不要动 scripts/accept_s3.py 的期望值（那是真机基线）。
```

### Q9 — 内置剧本「原地开关」【Qwen】

```text
内置剧本现在只有落盘式开关（trm workflow enable <id> 改文件，要重启才生效）。
要求：
① 加运行期开关：内存态 + 落盘持久化，重启后保持；
② 新增 trm workflow on|off <id>，trm workflow list 显示当前态；
③ 关掉后事件不再触发该剧本；
④ 测试：关掉后不触发 / 重启后保持 / 未启用状态下触发被忽略；
⑤ 红线不许碰：不能放宽步骤闸门，处置类剧本保持 enabled=False（见本文件「红线」）。
验收：新测试全绿，全量无回归。
```

### Q10 — `src/agent-sdk` 端到端与打包验证【Qwen】

```text
tests/ 至今对 src/agent-sdk 零覆盖。
要求：
① 先读 src/agent-sdk/trimum_agent.py，把它的公开接口列进 STATUS.md 日志（别改它的行为）；
② 新增 tests/test_agent_sdk_e2e.py：起一个真实 AgentSocketServer（或走 daemon 的 socket 路径），
   用 SDK 连上 → start / status / stop → 断言返回与事件；
③ 打包验证：能从打好的 wheel 里 import trimum_agent；本机缺 setuptools / 网络时跑不了就如实写进日志；
④ 需要外部条件的用例用 pytest.importorskip 兜住。
验收：新测试全绿，或如实列出哪条被 skip 及原因。
```

### Q11 — SonarQube 重扫 + 归档【Qwen】

```text
要求：
① 只扫描 + 归档，不改代码；
② 报告落 docs/SONAR-REPORT-2026-09.md（新建）：issue 总数按「真 bug / 假阳性 / 低风险」三类；
③ 与上次 181 条对比（上次排除口径：图片 / Waybar CSS / 源文件编码）；
④ 扫描命令原样记进报告，下次照抄；
⑤ 本机没有可跑的 SonarQube 就如实说明并停手，别伪造数据。
验收：报告落地 + STATUS.md 追加一条日志。
```

> 【DS】的任务不写提示词 —— 复杂件直接在 `ds` 会话里开工，验收口径按 `docs/` 里对应专题文档（`CODING-AGENT-PLAN.md` / `SANDBOX-PLAN.md` / `LLM-ROUTING.md`）走。

---

## 历史指针（时间倒序，标题级；细节见 `STATUS.md` / `docs/`）

- 2026-09-22：CLI 进阶一（`ask --image`）+ 二（`memory import/export`）+ 零散待办（B4/C1/F2）+ RAG 调研 + S3 三档 + S2 施加点收口 + Codex 模型切换复盘 + 本文档改写（TODO 只留未闭环 + 模型分工）
- 2026-09-21：沙箱 S1/S2/S3 + 真机切开关（TCP 收口）+ LLM 路由/限流/回退 + 测试隔离 + Codex 模型分工 + 穿插项 A/B/C + E5 三片 + P0 四步 + 根目录文档合并
- 2026-09-20：E2/E3/E4/E6 + M3/M4/M4.5 + W1 + EventBus 审计 + 文档清理
- 2026-09-19：Phase A/B/C + P0/P1 收尾（CLI 框架 + 核心命令 + Agent 交互）
- 更早（Phase 0–3 基建 / 弹性沙箱 / Ubuntu Deploy）→ `STATUS.md`「## 日志」+ `docs/ARCH.md`
