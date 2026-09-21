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