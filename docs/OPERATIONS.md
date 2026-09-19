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