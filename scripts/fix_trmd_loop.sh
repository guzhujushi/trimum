#!/usr/bin/env bash
# 修 trmd.service 与手工 daemon 抢端口导致的崩溃重启循环
#
#   sudo bash /tmp/fix_trmd_loop.sh                # 方案A（默认）：停用 systemd 单元，保留手工 daemon
#   sudo bash /tmp/fix_trmd_loop.sh --use-systemd  # 方案B：停手工 daemon，改由 systemd 托管
#   sudo bash /tmp/fix_trmd_loop.sh --check        # 只看现状，不改动
#
# 背景（2026-09-20 实测）：trmd.service 为 enabled + Restart=always + RestartSec=5，而手工 daemon
# 已占用 127.0.0.1:8321 → 单元每 5s 起一次、立刻 exit 3（journal 里 NRestarts 已到 88）。更糟的是
# ipc_handler._start_unix_socket() 先 unlink 再 bind，于是这个短命进程每次都抢走运行中 daemon 的
# /run/user/1000/trimum.sock，自己死掉后留下无人监听的 socket 文件 → `trm` 的 RPC 间歇失效并静默
# 退回 HTTP（`trm status` 会显示 source: http）。
#
# 方案A 之后请以 guzhujushi 身份重启手工 daemon 拿回 socket：
#   bash /home/guzhujushi/trimum/scripts/restart_trmd.sh
set -euo pipefail

MODE=keep-manual
case "${1:-}" in
    "") MODE=keep-manual ;;
    --use-systemd) MODE=use-systemd ;;
    --check) MODE=check ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
esac

[[ ${EUID} -eq 0 ]] || { echo "请用 sudo 运行：sudo bash $0" >&2; exit 1; }

SOCK=/run/user/1000/trimum.sock
PATTERN='trimum_core[.]main'

report() {
    echo "--- 现状 ---"
    echo "  单元      : $(systemctl is-enabled trmd 2>&1) / $(systemctl is-active trmd 2>&1)"
    systemctl show trmd -p NRestarts -p ExecMainStatus 2>/dev/null | sed 's/^/  /'
    echo "  进程      :"
    pgrep -af "$PATTERN" | sed 's/^/    /' || echo "    (无)"
    echo "  socket    : $(ls -l $SOCK 2>&1)"
    echo "  HTTP 健康 : $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8321/health 2>&1)"
}

[[ $MODE == check ]] && { report; exit 0; }

if [[ $MODE == keep-manual ]]; then
    echo "== 方案A：停用 systemd 单元，保留手工 daemon =="
    systemctl disable --now trmd 2>&1 | sed 's/^/  /' || true
    if [[ -S $SOCK ]]; then
        rm -f "$SOCK"
        echo "  清掉被短命进程留下的死 socket 文件 $SOCK"
    fi
    report
    echo
    echo "接下来以 guzhujushi 身份执行（拿回 RPC socket）："
    echo "  bash /home/guzhujushi/trimum/scripts/restart_trmd.sh"
    echo "若要改回 systemd 托管：先停掉手工 daemon，再 sudo systemctl enable --now trmd"
    exit 0
fi

echo "== 方案B：停手工 daemon，改由 systemd 托管 =="
systemctl stop trmd 2>&1 | sed 's/^/  /' || true
for pid in $(pgrep -f "$PATTERN" || true); do
    echo "  停手工 daemon $pid"
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null || true; fi
done
[[ -S $SOCK ]] && rm -f "$SOCK"

install -d -m 0755 /etc/systemd/system/trmd.service.d
cat > /etc/systemd/system/trmd.service.d/override.conf <<'EOF'
[Unit]
Description=trimum Agent Runtime Daemon

[Service]
Restart=on-failure
RestartSec=5
EOF
systemctl daemon-reload
systemctl enable --now trmd 2>&1 | sed 's/^/  /' || true
sleep 6
report
echo
echo "注意：core.socket_path 目前硬编码 /run/user/1000/trimum.sock（config.py:24）；"
echo "本单元以 User=guzhujushi（uid 1000）运行才恰好可用，换用户即失效。"
exit 0