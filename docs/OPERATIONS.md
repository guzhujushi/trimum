# trimum 运维同步流程

## 分支映射
| 分支名 | 对应环境 |
|---|---|
| `main` | trimum（主分支） |
| `ubuntu` | trimum-ubuntu |
| `arch-linux` | trimum-arch |
| `server` | trimum-server |

## GitHub push
1. 加载 `.env`：`GITHUB_TOKEN`。
2. 设置代理：
   - `HTTP_PROXY=http://127.0.0.1:7993`
   - `HTTPS_PROXY=http://127.0.0.1:7993`
3. 推送远程 `github.com/guzhujushi/trimum.git`。
4. 如使用 `gh`，用同一 `GITHUB_TOKEN` 登录的账号。

## 分支同步流程
1. 在当前工作分支只提交需要同步的文件。
2. 查看目标分支差异：`git diff --name-status <target>..<source>`。
3. 若差异只包含本次提交文件，用 `git cherry-pick <commit>` 同步。
4. 遇到平台/部署独有文件冲突时手动合并，不做 `merge -X theirs`。
5. 逐个 push：`main`、`ubuntu`、`arch-linux`、`server`。

## 真机同步
- SSH 免密：`guzhujushi@100.115.86.48`
- 开发目录：`/home/guzhujushi/trimum`
- 部署目录：`/opt/trimum`
- 同步源码到两个目录；`tests/` 优先同步到 home。
- `/opt/trimum/tests` 当前为 root:root 755，需 sudo。

## sudo 脚本规范
- 需要 sudo 的操作写成可执行脚本。
- 用 `scp` 放到远端 `/tmp/`，例如 `/tmp/sync_opt_tests.sh`。
- 告诉用户在真机执行：`sudo bash /tmp/sync_opt_tests.sh`。
- 仓库内保留副本：`scripts/sync_opt_tests.sh`。

## 收尾清单
- 发布前跑 CLI 测试：`pytest tests/test_cli.py -q`
- 全量测试跳过已知证书问题：`pytest tests -q --ignore=tests/test_agent_cert.py`
- 同步 `STATUS.md` / `TODO.md`
- 清理根目录 `tmp_*` 文件到 `tmp/`

## 真机同步实操（2026-09-20 验证）

1. **打包**：本地 `git archive` 或把改动文件打成 tar，`scp` 到远端 `/tmp/`。
   - 只同步改动文件时，先比对哈希确认宿主基线未被改动（本次宿主 `src/` 与本地 HEAD 逐文件一致）。
2. **解压**：
   - 开发目录：`cd /home/guzhujushi/trimum && tar -xf /tmp/<pkg>.tar`
   - 部署目录：`cd /opt/trimum && tar -xf /tmp/<pkg>.tar --exclude='tests/*' --exclude='tests'`
     （`/opt/trimum/tests` 与 `/opt/trimum/scripts` 属 root，需走 `sudo bash /tmp/sync_opt_tests.sh`）
3. **重启 daemon（必做）**：常驻 `trimum_core.main` 进程里是**旧代码**，不同步重启会出现
   「代码已更新但行为还是旧的」（本次 `agent spawn` 返回 stub 消息就是这个原因）。
   仓库里备好脚本：`scripts/restart_trmd.sh`（等旧进程完全退出后再起，避免旧进程
   shutdown 时 `unlink` 掉新进程刚绑好的 socket）。
   ```bash
   pkill -f 'trimum_core.main'   # 注意：别让 pattern 命中当前 shell 自己的命令行
   ```
   注意 `trm daemon start/restart` 是**前台**运行，在 SSH 会话里会一直挂着。
4. **确认监听形态**：`trm daemon status` 的 `source` 是 `rpc` 还是 `http`。
   `/opt/trimum/config.yaml` 用 `/run/trimum/trimum.sock`（root 路径），普通用户运行会
   `unix_socket_start_failed` → 自动退回 HTTP（功能可用，RPC 不可用）；cgroup 同理需 root。
5. **跑测试**：`cd /home/guzhujushi/trimum && .venv/bin/python -m pytest tests -q`
   - 宿主 venv 需要 `pytest pytest-asyncio rich`（`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple`）。
   - 对照基线：`git archive HEAD -o baseline.tar` → 解到 `/tmp/trimum_baseline` →
     `PYTHONPATH=/tmp/trimum_baseline/src .venv/bin/python -m pytest tests -q`，
     与工作副本对比失败集合，区分「既有环境失败」与「回归」。
   - 卡住时先看进程栈：`pytest -o faulthandler_timeout=20` 会在超时后 dump 所有线程栈
     （真机上就是靠它定位到「监听 socket 阻塞事件循环」的）。
6. **smoke 清单**：`trm --version` / `trm tool list` / `trm exec 'echo smoke'` /
   `trm log audit --json` / `trm security learning` / `trm agent spawn demo`。

## 宿主路径速查

| 用途 | 路径 |
|---|---|
| 工具目录 | `~/.trimum/tools/<name>/{tool.json5,main.py}`（弃用 = 改名为 `tool.json5.disabled`） |
| Agent 数据 | `~/.trimum/agents/<type>/{cert.json,memory/}` |
| Agent 脚本 | `~/.local/share/trimum/agents/<type>/main.py` |
| Agent 日志 | `~/.local/share/trimum/agent-logs/<agent_id>.log` |
| 审计 | `~/.local/share/trimum/audit.jsonl` |
| 运行日志 | `~/.local/share/trimum/trimum.log` |
