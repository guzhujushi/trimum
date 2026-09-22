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
- SSH：`guzhujushi@100.115.86.48`（免密）。
- 开发目录：`/home/guzhujushi/trimum`
- 部署目录：`/opt/trimum`
- 源码同步到两处；测试文件优先同步到 home；`/opt/trimum/tests` 需要 sudo。

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


## 本机写入与 shell 纪律（2026-09-22 实测）

- **写含中文的文件**：走 Node REPL 的 `fs.writeFileSync(path, text, { encoding: "utf8" })`（自带 LF，实测 round-trip 一致、`cr=0`）。
  PowerShell 5.1 的 here-string / `Set-Content` 会把中文按 GBK 写坏；本环境 `apply_patch` 不可用。
  大改用「整篇重写」，小改用「锚点唯一才替换」（锚点出现次数不为 1 就报错退出）。
- **Git Bash 可用**：`& "C:\Program Files\Git\bin\bash.exe" -lc "<脚本>"`。中文内联、here-doc 都无损，行尾保持 LF。
  - PATH 上的 `bash` 是别的包装器，**用绝对路径**指向 `C:\Program Files\Git\bin\bash.exe`。
  - **别**把 bash 传给工具自己的 shell 参数：那样 bash 把 stdin 当脚本读，here-doc 会把后续内容吃掉（实测出 0 字节文件 + 卡住）。
  - 命令行里避免出现单独的 `<`（PowerShell 会当成保留重定向符而报解析错）；重定向写 `>`、here-doc 写 `<<` 都正常。
- **临时文件**一律进 `tmp/`；改动前的备份命名 `tmp/<file>.bak_<原因>`（`*.bak_*` 已在 `.gitignore`）。
