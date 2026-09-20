#!/usr/bin/env bash
# 重启 trimum daemon：先停掉旧实例，再起新实例，最后报告进程、状态与日志尾巴。
#
#   bash scripts/restart_trmd.sh
#
# 为什么不能「kill 完立刻起」：
# - 旧实例退出前仍占着 8321（uvicorn 走完 shutdown、unlink socket 都要时间），
#   新实例赶在它前面 bind，只会拿到 `[Errno 98] address already in use`。
# - pkill 的 pattern 写成 `trimum_core[.]main`，否则会连这个 shell 一起匹配上。
# - daemon 若由 systemd 单元托管（Restart=always），整段让位给
#   `sudo systemctl restart`，见下面第 0 步的守卫。
set -uo pipefail

PATTERN='trimum_core[.]main'
PYTHON="${TRIMUM_PYTHON:-/opt/trimum/venv/bin/python}"
WORKDIR="${TRIMUM_WORKDIR:-/opt/trimum}"
LOGFILE="${TRIMUM_DAEMON_LOG:-/tmp/trmd.out}"

# ---------------------------------------------------------------------------
# 0. systemd 守卫
#
# 生产机上 daemon 由 /etc/systemd/system/trmd.service 托管（Restart=always）。
# 这种情况下 `kill` 只会换来一次「5 秒后复活 + 抢走 8321」，本脚本随后起的
# 实例反而 bind 失败，日志里只留下 `[Errno 98] address already in use`，
# 看起来像是端口被别人占了，其实是两个人在抢同一把椅子。
# 单元是 disabled ≠ 没在跑：它照样 active。
# ---------------------------------------------------------------------------
UNIT="${TRIMUM_SYSTEMD_UNIT:-trmd.service}"
if command -v systemctl >/dev/null 2>&1 && systemctl cat "$UNIT" >/dev/null 2>&1; then
    STATE=$(systemctl is-active "$UNIT" 2>/dev/null || true)
    if [ "$STATE" = "active" ] || [ "$STATE" = "activating" ]; then
        if [ "${EUID}" -eq 0 ]; then
            echo "检测到 systemd 单元 $UNIT 在托管 daemon，改由 systemd 重启（单元内的 User= 决定运行身份）"
            systemctl restart "$UNIT"
            sleep 3
            systemctl --no-pager --lines=0 status "$UNIT" | head -8
            exit 0
        fi
        cat >&2 <<EOF
检测到 systemd 单元 $UNIT 正在托管 daemon（Restart=always）。
本脚本的 kill 会让 systemd 在 RestartSec 后把它拉起来，新起的实例抢不到
8321，只会看到「address already in use」。请改用：

    sudo systemctl restart $UNIT
    systemctl status $UNIT --no-pager

（想改回手工托管：sudo systemctl disable --now $UNIT）
EOF
        exit 3
    fi
    echo "systemd 单元 $UNIT 存在但未运行，按手工方式启动"
fi

OLD=$(pgrep -f "$PATTERN" | head -1)
if [ -n "${OLD:-}" ]; then
    echo "stopping old daemon $OLD"
    kill -TERM "$OLD"
    for i in $(seq 1 20); do
        sleep 1
        kill -0 "$OLD" 2>/dev/null || { echo "old exited after ${i}s"; break; }
    done
    if kill -0 "$OLD" 2>/dev/null; then
        echo "old still alive, sending SIGKILL"
        kill -9 "$OLD"
        sleep 1
    fi
fi

cd "$WORKDIR"
setsid nohup "$PYTHON" -m trimum_core.main > "$LOGFILE" 2>&1 < /dev/null &
sleep 5

echo "--- process ---"
pgrep -af "$PATTERN" || echo "(daemon not running)"
echo "--- daemon status ---"
trm daemon status 2>&1 | tail -2
echo "--- log tail ($LOGFILE) ---"
tail -4 "$LOGFILE"
