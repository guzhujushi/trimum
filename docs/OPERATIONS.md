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

### 属主现状（2026-09-20 实测）
- `root:root`：`/opt/trimum/config`、`/opt/trimum/tests`、`/opt/trimum/scripts`、
  `/opt/trimum/src/trimum_core`（44 个文件里 12 个是 `guzhujushi`，早期失败解包留下 → 重装即归一）
- `guzhujushi:guzhujushi`：`/opt/trimum`、`/opt/trimum/src`、`/opt/trimum/venv`
  （**venv 属主是用户，装依赖不需要 sudo**）
- `/home/guzhujushi/trimum/src` 也是 `root:root` → `tar -xf` 无法新建 `src/agent-sdk`（内容照旧落地，只是该目录缺失）

## 部署树同步（`/opt/trimum`）

`scripts/sync_opt_tree.sh` 是唯一入口：以 root 把开发树的 `src/ config/ tests/ scripts/`
与顶层文档（`AGENTS/ARCH/PRD/STATUS/TODO.md`、`docs/OPERATIONS.md`）装进 `/opt/trimum`，
逐文件 `install -D -o root -g root`（**不做递归 chown**），末尾打印关键文件与属主校验。

```bash
scp scripts/sync_opt_tree.sh guzhujushi@100.115.86.48:/tmp/
ssh guzhujushi@100.115.86.48 'sudo bash /tmp/sync_opt_tree.sh --dry-run'   # 先看要做什么
ssh guzhujushi@100.115.86.48 'sudo bash /tmp/sync_opt_tree.sh'             # 真同步
ssh guzhujushi@100.115.86.48 'sudo bash /tmp/sync_opt_tree.sh --fix-home'  # 顺带修 /home/.../src 属主
```

- 脚本**不重启 daemon**：daemon 必须以 `guzhujushi` 运行，root 跑会把 `~/.trimum` 写脏；
  同步后自己执行 `bash /home/guzhujushi/trimum/scripts/restart_trmd.sh`。
  生产机上 daemon 由 systemd 单元 `trmd.service` 托管，那种情况下改用 `sudo systemctl restart trmd`，
  原因见「daemon 托管与重启（systemd）」。
- `config/mcp-catalog.yaml` 的默认路径按包位置解析（`REPO_ROOT/config/`），部署树对应
  `/opt/trimum/config/mcp-catalog.yaml`，所以 `config/` 必须一起同步。
- 同步源顺序：**默认优先 `/tmp/trimum-sync.tar`**（`git archive` 全量、权威），只有 tar 不存在或显式
  `--from-home` 时才用开发树。原因：`/home/guzhujushi/trimum/src` 是 root 属主，`tar -xf` 建不出
  `src/agent-sdk`，拿开发树当源会把缺件一路带到 `/opt`（2026-09-20 实际踩到）。
- `--fix-home` 修完属主后，会把源里的 `src/` 补写回开发树（补上 `src/agent-sdk`）。
- 一并同步的顶层文件：`AGENTS/ARCH/PRD/STATUS/TODO.md`、`pyproject.toml`、`docs/OPERATIONS.md`。
  其中 `pyproject.toml` 曾漂移成旧版（缺 `cryptography>=42` 声明），元数据与 venv 不一致。

## sudo 脚本规范
- 需要 sudo 的操作写成可执行脚本。
- 用 `scp` 放到远端 `/tmp/`，例如 `/tmp/sync_opt_tree.sh`。
- 告诉用户在真机执行：`sudo bash /tmp/sync_opt_tree.sh`。
- 仓库内保留副本：`scripts/sync_opt_tree.sh`（全树）、`scripts/sync_opt_tests.sh`（仅 tests 与 scripts，旧）。

## MCP server 运维（M4，2026-09-20）

定义即安装：`~/.trimum/mcp/<name>.json5`（`TRIMUM_MCP_DIR` 可换目录）。**deny-by-default**：
没有 `enabled: true` 的定义会被加载、但永不启动。daemon 按目录指纹热加载——新增或改写定义，
下一次读状态 / 调用就生效，**不用重启 daemon**（M4 之前每个 `trm mcp call` 都是新进程，看不出这点）。

### 定义字段

| 字段 | 说明 |
|---|---|
| `transport` | `stdio`（默认）/ `http` / `streamable-http` / `streamable_http` |
| `command` `args` `env` | stdio：本机子进程 |
| `url` `headers` | http 系：远端 MCP 端点。`headers` 里放 token，**不回显**（`trm mcp list` 只列键名） |
| `trust` | `local` / `cloud`；`cloud` 额外继承破坏性工具默认黑名单 |
| `enabled` | 默认 `false`（要显式打开） |
| `allow_tools` / `deny_tools` | glob，deny 优先 |
| `timeout` | 单次调用超时（秒） |
| `idle_ttl` | 空闲回收阈值（秒），默认 300；**`0` = 常驻不回收** |
| `max_memory_mb` / `max_cpu_percent` | 交给 cgroup 的资源上限（Linux） |

### 生命周期（daemon 内）

- 一个 server 一个子进程 / 会话，**按名复用**；坏掉的流直接丢弃重建（自愈）。
- **空闲回收**：回收器每 30s 扫一轮（`api_server.MCP_REAPER_INTERVAL_SECONDS`），
  超过自己 `idle_ttl` 的 server 关掉；`idle_ttl: 0` 的常驻。
- **cgroup 绑定**：stdio 子进程交给 `create_resource_controller()`，`agent_id = mcp-<name>`。
  非 root / 无 cgroup v2 时 `apply_cgroup` 是空操作，状态记为
  `unavailable (not bound: needs root + cgroup v2 on Linux)` —— **只记录，不影响调用**。
- 子进程 stderr 落 `<logging.file 同目录>/mcp-<name>.log`，**不走管道**（避免 64KB 写满卡死）。

### 观测与操作

```bash
trm mcp list                    # 定义与启用状态（不启动任何进程）
trm mcp status                  # 谁在跑：pid / 空闲秒数 / cgroup 状态
trm mcp status --json           # source: daemon | cli
trm mcp restart <server>        # 停旧起新，其它 server 不受影响
trm mcp tools [server]          # 列工具（会启动 server）
trm mcp call <server> <tool> '{"k":"v"}'   # 调用（完整 ToolGateway 分层 + mcp_call 审计）
```

- `source: daemon` = 状态来自常驻 daemon 的共享池（真实进程）；`source: cli` = daemon 不在线，
  只读定义（此时一个 server 都不会在跑，这是正常结果而不是故障）。
- `--config X` 决定问哪个 daemon（`X` 里的 `core.socket_path`）；`--dir Y` 则强制本地读 `Y` 的定义。
- 无 daemon 时 `trm mcp restart <server>` 的含义是「起一次证明定义还能用，退出前再关掉」。
- 排障：`status` 的 `cgroup` 列 / `pid` 列；`<日志目录>/mcp-<name>.log`；
  审计 `trm log audit --json`（`event_type=mcp_call`，只记参数**键名**，不记值）。
- IPC 方法：`mcp.status`、`mcp.restart`（JSON-RPC over Unix socket，与 CLI 同源）。

### 工具聚合与缓存（M4.5）

远端工具以 `<server>__<tool>` 出现在 `trm tool list` 里（该行 `source: mcp`），可以直接按这个名字调用：

```bash
trm tool list --mcp                       # 只看远端聚合进来的
trm tool info echo__echo                  # 看它来自哪个 server
trm mcp call echo__echo '{"text": "hi"}'  # 与 `trm mcp call echo echo '...'` 等价
```

- 清单是**缓存**（`~/.trimum/mcp-tools.json`，`TRIMUM_MCP_INDEX` 可覆盖）：只有成功跑过一次
  `trm mcp tools` 的 server 才会出现在里面 —— 这是刻意的，否则「列一下远端工具」就得把每个
  server 拉起来，M4 的懒启动 / 空闲回收就白做了。
- 缓存可以随时删（下次列工具会重建）；文件写坏只会被当成「还没有缓存」，不影响任何调用。
- server 定义删掉后，缓存里的名字会在 daemon **下次启动**时被 `prune` 清掉；在那之前调用它会得到
  `MCP server not found: <server>`（参数已解成 server + tool），不会静默失败。
- **整个 `~/.trimum/mcp/` 目录被删**也算「定义不存在」：启动时那一轮 `prune` 会把缓存清空
  （不清的话 `trm tool list` 会列出一批调用必然失败的幽灵工具）；只有目录**存在但列不出来**
  （权限 / IO）时才按「不知道有哪些 server」处理：不动缓存，并在 journal 里记一条
  `mcp_index.prune_skipped reason=unreadable`。
- 手工清缓存：直接 `rm ~/.trimum/mcp-tools.json`（下次成功 `tools/list` 会重建）。
- 缓存里**不含密钥**（`env` / `headers` 只记键名），可以放心 `cat`。
- 名字撞上本地工具时**本地工具赢**（远端工具少一个入口，比覆盖本地工具安全）。

### 部署（`/opt/trimum` 需要 sudo）

- `sudo bash /tmp/sync_opt_tree.sh --dry-run` 先看要做什么 → `sudo bash /tmp/sync_opt_tree.sh` 真同步
  （源优先 `/tmp/trimum-sync.tar`，逐文件 `install -D -o root -g root`，不做递归 chown；
  仓库副本 `scripts/sync_opt_tree.sh`）。
- `sudo bash /tmp/sync_opt_m4.sh` 是 M4 那一轮的**增量**补丁脚本（带 sha256 校验），现在已被全树同步
  取代：M4 遗留的 `reap()` 修复随全树同步一起进部署树。判断依据 ——
  `sha256sum /opt/trimum/src/trimum_core/mcp_registry.py` 应等于开发树同名文件（2026-09-20 实测未同步前
  是 `fe0166cd…`，开发树 `86447a65…`）。
- 装完重启 daemon：systemd 托管时 `sudo systemctl restart trmd`，否则以 guzhujushi 身份跑
  `bash /home/guzhujushi/trimum/scripts/restart_trmd.sh`（脚本会自己识别并让位）。
- 无人值守验收：`scripts/accept_m4.py`（起 8323 端口的隔离 daemon，跑 16 项断言，
  不碰生产 daemon；本机 `python scripts/accept_m4.py` 亦可）。

## daemon 托管与重启（systemd）

生产机 `/etc/systemd/system/trmd.service` 是 daemon 的**真正托管者**：

```ini
[Service]
Type=simple
User=guzhujushi
WorkingDirectory=/opt/trimum
ExecStart=/opt/trimum/venv/bin/python -m trimum_core.main
Restart=always
RestartSec=5
```

- **`disabled` 不等于没在跑**：单元没有开机自启，但可以是 `active`（手动 start 过一次就会一直在，
  且 `Restart=always` 会把它拉回来）。`systemctl is-enabled trmd` 与 `is-active trmd` 是两件事。
- **托管期间不要 `pkill`**：杀掉后 systemd 会在 `RestartSec`（5s）后复活它，新起的实例抢不到 8321，
  日志里只有 `[Errno 98] address already in use` —— 2026-09-20 的「端口被占用」就是这个。
  判断依据：`ss -ltnp` 里占着端口的那个 PID，其 `fd1`/`fd2` 指向 `/run/systemd/journal/stdout`
  （systemd 起的进程日志进 journal，不写 `/tmp/trmd.out`）。
- 正确动作：

```bash
sudo systemctl restart trmd                       # 重启；单元里的 User= 保证仍以 guzhujushi 运行
systemctl status trmd --no-pager
journalctl -u trmd -n 30 --no-pager               # 日志在这里，不在 /tmp/trmd.out
```

- `scripts/restart_trmd.sh` 已内建守卫：检测到单元 active 时，root 下自动改走 `systemctl restart`，
  非 root 下打印指引并以退出码 `3` 结束（不再去抢端口）。手工托管（单元不存在/未运行）时行为不变。
- 改变托管方式：改回手工 `sudo systemctl disable --now trmd`；要开机自启 `sudo systemctl enable trmd`。

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
   - 部署目录：改用 `sudo bash /tmp/sync_opt_tree.sh`（见「部署树同步」）。`config/`、`tests/`、
     `scripts/`、`src/trimum_core` 都是 root 属主，`tar -xf` 直解会被拒或只写一半。
3. **重启 daemon（必做）**：常驻 `trimum_core.main` 进程里是**旧代码**，不同步重启会出现
   「代码已更新但行为还是旧的」（本次 `agent spawn` 返回 stub 消息就是这个原因）。
   仓库里备好脚本：`scripts/restart_trmd.sh`（等旧进程完全退出后再起，避免旧进程
   shutdown 时 `unlink` 掉新进程刚绑好的 socket）。
   ```bash
   pkill -f 'trimum_core.main'   # 注意：别让 pattern 命中当前 shell 自己的命令行
   ```
   注意 `trm daemon start/restart` 是**前台**运行，在 SSH 会话里会一直挂着。
   **systemd 托管时别用 `pkill`**（会被 `Restart=always` 复活并抢端口），改用
   `sudo systemctl restart trmd`，见「daemon 托管与重启（systemd）」。
4. **确认监听形态**：`trm daemon status` 的 `source` 是 `rpc` 还是 `http`。
   `/opt/trimum/config.yaml` 用 `/run/trimum/trimum.sock`（root 路径），普通用户运行会
   `unix_socket_start_failed` → 自动退回 HTTP（功能可用，RPC 不可用）；cgroup 同理需 root。
5. **跑测试**：`cd /home/guzhujushi/trimum && .venv/bin/python -m pytest tests -q`
   - 宿主 venv 需要 `pytest pytest-asyncio rich`（`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple`）。
   - **`cryptography` 是包依赖（`pyproject.toml` 已声明），但真机两份 venv 都可能缺**：缺它时
     `trm setup` 身份步骤返回 `status=skipped`，`tests/test_setup_wizard.py` 的 6 项身份用例失败。
     两份 venv 都属 `guzhujushi`，装依赖**不需要 sudo**：`.venv/bin/python -m pip install "cryptography>=42"`，
     `/opt/trimum/venv` 同理（2026-09-20 补装 `cryptography-50.0.1`）。
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
| MCP 定义 | `~/.trimum/mcp/<name>.json5`（`TRIMUM_MCP_DIR` 可换目录） |
| MCP 子进程日志 | `<logging.file 同目录>/mcp-<name>.log` |
| MCP 验收脚本 | `scripts/accept_m4.py`（隔离 daemon，16 项断言） |
