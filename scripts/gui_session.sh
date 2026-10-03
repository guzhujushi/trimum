#!/usr/bin/env bash
# gui_session.sh —— 图形栈「按需开」开关（真机 天逸510S / Ubuntu 24.04）
#
# 背景：这台机器 7x24 常驻当 AI 工作站，默认**不加载**图形栈（`get-default = multi-user.target`，
#       `gdm.service` 是 static、本来就不随开机启动）；偶尔要用 GUI 时用本脚本一键拉起。
#
# 用法：
#   bash scripts/gui_session.sh status     # 只读：图形在不在、默认 target、谁在登录
#   sudo bash scripts/gui_session.sh on    # 拉起 GNOME 登录界面（本地屏幕；不动其它单元）
#   sudo bash scripts/gui_session.sh off   # 关掉图形并把文字控制台（getty@tty1）拉回来
#
# 设计口径（都是真机实测出来的）：
#   * **只 start/stop `gdm.service`，不用 `isolate graphical.target`**：gdm 的 Requires
#     只有 sysinit / system.slice / dbus.socket ⇒ 拉起它**不牵连** trmd / docker / tailscaled / sshd；
#     而 isolate 会把不在该 target 依赖图里的单元停掉（没必要冒这个险）。
#   * `gdm.service` 是 **static**（无 [Install]、`WantedBy=` 为空）⇒ 它本来就不随开机启动，
#     「按需开」是免费的：不需要 enable/disable，只要 start/stop。
#   * **`off` 必须显式把 `getty@tty1` 拉回来**：gdm 有 `Conflicts=getty@tty1.service`，开图形会杀掉
#     文字控制台；而 gdm 又有 `After=getty@tty1.service`，停掉它 systemd **不会**自动重启 getty
#     ⇒ 不管的话屏幕就黑着、没有任何提示（2026-09-22 实测踩过一次）。
#   * **红线：不要在图形会话自己的终端里跑 `off`**（会连你所在的会话一起关掉）。
#     从 SSH 里跑，或先 Ctrl+Alt+F3 切到别的 tty 再跑。
set -uo pipefail

GDM=gdm.service
GETTY=getty@tty1.service

log() { printf '%s\n' "$*"; }
die() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }
usage() { awk 'NR>1 && /^set /{exit} NR>1{sub(/^# ?/,""); print}' "$0"; exit 0; }

case "${1:-status}" in
  -h|--help) usage ;;
esac

MODE="${1:-status}"
case "$MODE" in
  status|on|off) ;;
  *) die "未知参数：$MODE（支持 status / on / off）" ;;
esac
if [ "$MODE" != "status" ] && [ "$(id -u)" != "0" ]; then
  die "$MODE 需要 root：sudo bash $0 $MODE"
fi

show_status() {
  log "默认 target      : $(systemctl get-default)"
  log "图形会话 $GDM : $(systemctl is-active "$GDM" 2>/dev/null) / $(systemctl is-enabled "$GDM" 2>/dev/null || echo '?')"
  log "文字控制台 $GETTY : $(systemctl is-active "$GETTY" 2>/dev/null)"
  log "本地登录         : $(who | tr '\n' '; ' | sed 's/; $//')"
}

case "$MODE" in
  status)
    show_status
    ;;
  on)
    systemctl start "$GDM" || die "启动 $GDM 失败"
    sleep 1
    show_status
    log ""
    log "已拉起图形界面 —— 本地屏幕应显示 GNOME 登录。用完关掉：sudo bash $0 off"
    ;;
  off)
    systemctl stop "$GDM" || die "停止 $GDM 失败"
    # gdm 与 getty@tty1 互斥：停 gdm 后 systemd 不会自动把 getty 拉回来，必须显式起。
    systemctl start "$GETTY" 2>/dev/null || log "[warn] $GETTY 没起来 —— 本地屏幕可能空着，手动 Ctrl+Alt+F2 试试"
    sleep 1
    show_status
    log ""
    log "已回到文字控制台（内存约省 0.9GiB）。要再开：sudo bash $0 on"
    ;;
esac
