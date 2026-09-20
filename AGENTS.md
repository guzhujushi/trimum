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