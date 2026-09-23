# AGENTS.md — trimum 项目级 Codex 指令

## 项目名
- 唯一正确拼写：`trimum`，CLI 命令：`trm`。禁止写成 `trinum`。

## 分支映射
- `server` = trimum-server —— **日常开发分支**（唯一需要每轮提交/推送的分支）
- `main` = trimum（主分支）
- `ubuntu` = trimum-ubuntu
- `arch-linux` = trimum-arch

## Git 分支纪律（2026-09-20 定）
- **日常开发只提交、只推送 `server`。** `main` / `ubuntu` / `arch-linux` **不随每轮改动走**，
  不要每个提交都去 cherry-pick 三分支 —— 那是无谓的四倍工作量。
- **只有收尾阶段**（一个里程碑闭环、要发布或上真机验收时）才做四分支同步：
  1. 逐提交 `git cherry-pick` 到三个分支（不要无脑 merge，冲突逐个解决）；
  2. `git diff --name-status <target>..server` 必须为空，`.gitignore`/平台独有文件不被覆盖；
  3. `git fetch` 复核四个分支与 `origin` 一致，再按 `main` → `ubuntu` → `arch-linux` → `server` 推送；
  4. 把四列提交号写进 `STATUS.md` 的「提交与分支」表（**那时**才需要四列哈希）。
- 平时 `STATUS.md` 只记录 `server` 的提交号即可。
- 同步改动时只提交目标文件，先看 `git diff --name-status <target>..<source>`。
- 不覆盖各分支独有文件（deploy/桌面/平台相关配置）。
- push 前通过代理 `http://127.0.0.1:7993`，使用 `.env` 里的 `GITHUB_TOKEN`。

## 密钥与临时文件
- `.env` 永远不提交，已在 `.gitignore`。
- 所有临时文件放 `tmp/`，根目录 `tmp_*` 必须移入 `tmp/` 并忽略。

## 真机
- SSH：`guzhujushi@100.115.86.48`（免密，Tailscale）。屏幕是无桌面的文字控制台（`multi-user.target` + `getty@tty1`）。
- 开发目录：`/home/guzhujushi/trimum`（git，跟 `server` 分支）
- 部署目录：`/opt/trimum`
- 源码同步到两处；测试文件优先同步到 home；`/opt/trimum/tests` 需要 sudo。
- **真机现成工具**（2026-09-22/23 装）：
  - `~/bin/codex-run ds|qwen` —— 跑 codex（已带 nvm PATH + 注入 `~/.codex/env`）；`~/bin/codex-smoke` 冒烟。
  - `~/bin/tunnel-up` —— 恢复 `code tunnel`（**已改为走 systemd user service `trimum-tunnel`**，没装 service 时回退「解锁 keyring + setsid」）；口令文件 `~/.config/trimum/tunnel.pw`（0600）。
  - `~/bin/with-proxy <命令>` —— 备用网络通道（经 Tailscale → Windows UniClash `100.124.243.30:7993`）；**只在直连抽风时用**，慢 4~10 倍，代理不可达自动降级直连。
  - `~/.local/bin/code` —— VS Code CLI（1.138.0，与 server 同 commit）；扩展装在 `~/.vscode-server/extensions`。
  - VS Code 入口：**主** `https://vscode.dev/tunnel/tianyi`；**备（T2，Tailscale 直连）** `~/bin/serve-web-up` → `http://100.115.86.48:8080/`（手机浏览器可用，免域名/证书/frp）。
  - **三个用户级 systemd 服务**：`trimum-web`（VS Code Web）/ `trimum-tunnel`（隧道）/ `trimum-mihomo`（Clash Meta 核，`127.0.0.1:7890`）；装/重装 `scripts/install_user_units.sh`，重启后自启靠 `loginctl enable-linger guzhujushi`（**待本人 sudo 开**，脚本 `scripts/enable_linger.sh`）。
  - mihomo 配置 `~/.config/mihomo/config.yaml`（机场订阅只放这台机器，**不入仓库**）。
- **坑（细节见 `docs/OPERATIONS.md`）**：GitHub 凭据在 gnome-keyring 里，**没有桌面会话时 keyring 是锁的** ⇒ `code tunnel` 会误报未登录并重新要设备码；用登录口令 `gnome-keyring-daemon --unlock --replace` 解锁即可，**不要重新授权**。

## sudo 规则
- 需要 sudo 的操作写成脚本，`scp` 到远端 `/tmp/`，并明确告诉用户脚本位置。
- 示例：`scripts/sync_opt_tests.sh`。

## 详细运维流程
- 见 `docs/OPERATIONS.md`。
- 收尾/待办见 `TODO.md`、`STATUS.md`。

## 文档地图（2026-09-21）
- **架构**：`docs/ARCH.md`（2026-09-21 由根目录 `ARCH.md` 移入；根目录不再保留 `PRD.md` / `ARCH.md`）。
- **需求 / 生态战略**：`docs/ECOSYSTEM-STRATEGY.md`、`docs/MCP-INTEGRATION-PLAN.md`、`docs/CLI-ANYTHING-RESEARCH.md`。
- **编码智能体（E7）**：规格与设计 `docs/CODING-AGENT-PLAN.md`；前置调研（ECC 适合吗 + 可复用开源件）`docs/CODING-AGENT-REUSE-RESEARCH.md`（**注意：ECC 的「903 个 SKILL.md」「30+ 宿主」是错的，真实 292 / 7**）。
- **沙箱（E7 前置片，2026-09-21）**：`docs/SANDBOX-PLAN.md`（主流做法三层 / Docker 裁决 / 真机实测 / 设计 + 分片 S1–S5 / **裁决见 §9**）；
  脚本 `scripts/setup_ubuntu_toolchain.sh`（装工具链）、`scripts/check_sandbox_caps{,_root}.sh`（能力自检）、`scripts/harden_trmd_unit.sh`（**S1 daemon 加固，默认 dry-run，`--apply` 才装，失败自动回滚**）——**都需 sudo，真机 sudo 需要密码，只能本人跑**。
- **运维**：`docs/OPERATIONS.md`；**包渠道运维**（造根 / 打包 / 建索引 / 上线 / 轮换根）：`docs/PACKAGE-CHANNEL-OPS.md`；**多用户边界**（调研 + 设计，2026-09-21）：`docs/MULTI-USER-BOUNDARY.md`；**进度 / 待办**：`STATUS.md` / `TODO.md`。
- **原始调研件**：`tmp/research/`（已 gitignore，`docs/` 有多处引用，且是 `trm mcp catalog import` 的默认输入，不要整目录清空）。

## 文档分工与追加式（2026-09-22 改）

- **`TODO.md` 只留未闭环的待办 + 红线**；已完成的历史进度一律进 `STATUS.md`，不重复叙述。
- **`STATUS.md` = 常驻区（就地小改）+ 追加日志（只增不改）**：
  - 顶部「当前状态 / 任务清单 / 决策记录 / 下一步」为常驻区，随进展就地小改。
  - 底部「## 日志」按日期从旧到新；**新进展只追加到文件最末尾**，不回填、不通读全文。
  - 日常只需读「当前状态」+ 最新一条日志即可定位；历史细节按需翻对应日期条目。


## 平台判别（每个任务第一步，2026-09-23 加）

**先判定自己在哪台机器上跑，再选口径。** 判据：能跑 `uname -s` 得到 `Linux` ⇒ **真机侧**；
只有 PowerShell、`$env:OS` = `Windows_NT` ⇒ **Windows 侧**。两边都是 trimum 仓库，但**命令口径完全不同**。

| 事项 | Windows 侧（本地开发机） | 真机侧（Ubuntu / 天逸510S，7x24 常驻） |
|---|---|---|
| 写文件 | Node REPL `fs.writeFileSync(path, text, {encoding:"utf8"})`；**别**用 PS here-string（按 GBK 写坏中文） | 直接 `cat > file <<'EOF'`（UTF-8 + LF 天然正确），Node 写法同样可用 |
| 行尾 | 生成的 `.sh` 必须 LF；推到真机前一律 `tr -d '\r'` | 天然 LF，无需处理 |
| Shell | PowerShell：**没有 `<` 重定向**；`$( )`、`\"`、`$HOME`、管道会被 PowerShell 吃掉/展开 | 正常 bash，可直接跑 |
| 复杂命令 | **一律写成 `.sh` 文件再跑，不要内联**（内联一次坑一次，实测踩了三次） | 可直接跑；多步同样建议写文件 |
| 连对方 | `scp tmp/x.sh guzhujushi@100.115.86.48:/tmp/` → `ssh -o BatchMode=yes guzhujushi@100.115.86.48 "tr -d '\r' < /tmp/x.sh > /tmp/x2.sh; bash /tmp/x2.sh 2>&1"` | 本地直接 `bash x.sh`，无需 scp |
| 跑 codex | `.\scripts\codex-model.ps1 qwen` / `ds`（换 provider 必须重开进程，`/model` 改不了 provider） | `~/bin/codex-run ds|qwen`；冒烟 `~/bin/codex-smoke` |
| `codex exec` | 无特殊要求 | **必须 `</dev/null`**：SSH 管道的 stdin 不关闭，它会干等 EOF（实测卡 7 分钟、连 API socket 都不建）；再套 `timeout 240` 兜底 |
| 后台常驻 | `Start-Process -WindowStyle Hidden` | `setsid nohup <cmd> >>log 2>&1 < /dev/null &`（只 `nohup` 会随会话清理） |
| 网络 | 境外 API / GitHub 走代理 `http://127.0.0.1:7993` | 真机**直连**（实测 github/api/npm 全 200，0.2–0.7s）；直连偶发瞬断（`GnuTLS recv error -110` / TLS 超时）时走备用通道 **`~/bin/with-proxy <命令>`**（经 Tailscale 借 Windows 的 UniClash，慢 4~10 倍，代理不可达会自动降级直连） |
| sudo | 无 | **agent 不代跑 sudo**，写成脚本交本人；真机 sudo 要口令 |
| 临时文件 | `tmp/` | `tmp/`（真机重启会清 `/tmp`，长期脚本别只放 /tmp） |

## 本机写入与 shell 纪律（Windows 侧，2026-09-22 实测）

- **写含中文的文件**：走 Node REPL 的 `fs.writeFileSync(path, text, { encoding: "utf8" })`（自带 LF，实测 round-trip 一致、`cr=0`）。
  PowerShell 5.1 的 here-string / `Set-Content` 会把中文按 GBK 写坏；本环境 `apply_patch` 不可用。
  大改用「整篇重写」，小改用「锚点唯一才替换」（锚点出现次数不为 1 就报错退出）。
- **Git Bash 可用**：`& "C:\Program Files\Git\bin\bash.exe" -lc "<脚本>"`。中文内联、here-doc 都无损，行尾保持 LF。
  - PATH 上的 `bash` 是别的包装器，**用绝对路径**指向 `C:\Program Files\Git\bin\bash.exe`。
  - **别**把 bash 传给工具自己的 shell 参数：那样 bash 把 stdin 当脚本读，here-doc 会把后续内容吃掉（实测出 0 字节文件 + 卡住）。
  - 命令行里避免出现单独的 `<`（PowerShell 会当成保留重定向符而报解析错）；重定向写 `>`、here-doc 写 `<<` 都正常。
- **临时文件**一律进 `tmp/`；改动前的备份命名 `tmp/<file>.bak_<原因>`（`*.bak_*` 已在 `.gitignore`）。

## qwen 任务纪律（2026-09-22 定：一个模块一停，少读源码）

> 背景：交我算 `qwen3.8-27b` 免费但 **10 次/分**，而 Codex 一个 turn 常 5–15 次调用 ⇒ **连派 3 个以上任务必撞 429**。
> 标签与跑法见 `TODO.md`「🤖 模型分工」；本节只讲**怎么派活给 qwen**。

### 三条原则

1. **一个模块一个 prompt**：改完即停；不做「顺手优化」、不跨模块重构、不连续追问。
2. **少读源码**：落点（文件 + 行号区间 + 函数名）由派活方在提示词里给全，**不许它自己在仓库里翻找**。
3. **实现与验收分权**：qwen 只写实现；**不写验收、不跑全量测试、不提交**。测试与验收交 `ds` 窗口或本人（谁写实现谁不验收）。

### 写进每条提示词的硬约束

- 只允许改提示词里**明确列出**的文件，其他文件一律不许动。
- 不许全仓搜索、不许读指定模块之外的源码；**找不到落点就停下报告**，不许自行扩大范围。
- 不许跑 `pytest` 全量、不许 `git commit` / `git push`；只允许单文件语法自检（`python -m py_compile <文件>`）。
- 改完立刻结束，不格式化、不重构无关行。

### 派活模板

```text
【任务】只改 <文件A>（必要时加 <文件B>），其余一律不许动。
【落点】<文件A>:<行号区间> 的 <函数名>；口径按 <现有签名>。
【硬约束】① 不许全仓搜索 / 不许读 <模块X> 之外的源码，找不到落点就停下报告；
         ② 不许跑 pytest 全量、不许 git 提交，只允许 python -m py_compile <文件A>；
         ③ 改完即停，不做顺手优化、不重构无关行。
【输出】固定三段：① 改动清单（文件:行号 + 一句话）② 为什么这样改（≤3 行）
         ③ 交接给验收窗口：建议的测试命令 + 需人工确认的点
```

### 隐身执行（无窗口）

- 真机（无图形栈）：`codex exec -p qwen --skip-git-repo-check -s workspace-write` —— 天然无窗口。
- Windows：`Start-Process -WindowStyle Hidden`，或 `.\scripts\codex-model.ps1 qwen -Exec (Get-Content tmp\task.md -Raw)`。

### 撞限流怎么办

- 撞 429 就**等 1 分钟**（或换 `ds`），别重试轰炸。
- 判断力活（架构裁决、沙箱施加点、并发/竞态、跨模块重构）**直接派 `ds`**，不要派 qwen。
