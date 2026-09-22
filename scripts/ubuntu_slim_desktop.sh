#!/usr/bin/env bash
# 真机（天逸510S / Ubuntu 24.04）省电与「无桌面常驻」收敛脚本
#
# 背景：这台机器要 7x24 常开当开发主机（SSH / VS Code tunnel / codex 隐身执行），
#       不需要本地图形界面。关掉图形栈与一批用不上的服务，省电 + 省内存。
#
# 用法（--apply / --rollback 需要 sudo；dry-run 不需要）：
#   bash /tmp/ubuntu_slim_desktop.sh              # dry-run：只打印将要做的动作与理由（默认）
#   sudo bash /tmp/ubuntu_slim_desktop.sh --apply # 执行：改默认 target + 停图形栈 + 停无关服务
#   sudo bash /tmp/ubuntu_slim_desktop.sh --rollback   # 还原（恢复图形栈与服务）
#   sudo bash /tmp/ubuntu_slim_desktop.sh --verify     # 只做体检，不改任何东西
#
# 设计口径（逐条理由）：
#   * **只改 target / 只停服务，绝不 purge 包**。实测 network-manager 是
#     ubuntu-desktop-minimal 的反向依赖，purge GNOME 会连带拆掉网络 → 直接失联，红线。
#   * 改 multi-user.target 只是「下次开机不进图形界面」，gdm3 一并 stop 立刻见效；
#     **两件事都完全可逆**，比卸包安全得多。
#   * 不动 no_turbo / governor：实测 idle 功耗 30W→20~25W，收益主要在内存（约省 0.9GiB），
#     压 CPU 频率得不偿失（编译变慢）。
#   * mask 掉睡眠/休眠 target：这台机器是常驻主机，**绝不能睡**。
#   * fwupd / avahi / cups / cups-browsed / bluetooth / sysstat 对无桌面主机无意义，
#     其中 fwupd 单独占约 192MB 内存。全部按「存在才停」，可逆。
#   * 前置硬检查：sshd 必须 active+enabled，否则拒绝执行（防把自己关在门外）。
set -uo pipefail

MODE=dryrun
REQUIRE_SSHD=1
SERVICES=(fwupd fwupd-refresh.timer avahi-daemon cups cups-browsed bluetooth sysstat)
TARGETS=(sleep.target suspend.target hibernate.target hybrid-sleep.target)
DEFAULT_TARGET=multi-user.target
PREV_TARGET=""
BACKUP_DIR=/var/backups/trimum

log()  { printf '%s\n' "$*"; }
ok()   { printf '  [ok]   %s\n' "$*"; }
skip() { printf '  [skip] %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*"; }
die()  { printf '  [FAIL] %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,20p' "$0"; exit 0; }

for arg in "$@"; do
  case "$arg" in
    --apply)    MODE=apply ;;
    --rollback) MODE=rollback ;;
    --verify)   MODE=verify ;;
    -h|--help)  usage ;;
    *) die "未知参数：$arg（支持 --apply / --rollback / --verify）" ;;
  esac
done

if [ "$MODE" != "dryrun" ] && [ "$(id -u)" != "0" ]; then
  die "该模式需要 root：sudo bash $0 $MODE"
fi

echo "== 0) 前置检查 =="
if systemctl is-active --quiet sshd; then ok "sshd active"; else
  if [ "$REQUIRE_SSHD" = "1" ]; then die "sshd 未运行，拒绝继续（会把自己关在门外）"; else warn "sshd 未运行"; fi
fi
if systemctl is-enabled --quiet sshd 2>/dev/null; then ok "sshd enabled"; else
  if [ "$REQUIRE_SSHD" = "1" ]; then die "sshd 未开机自启，拒绝继续"; else warn "sshd 未自启"; fi
fi
if systemctl is-active --quiet tailscaled 2>/dev/null; then ok "tailscaled active"; else warn "tailscaled 未运行（手机/异地访问可能受影响，请自行确认还有别的通路）"; fi
log "  当前默认 target: $(systemctl get-default)"

if [ "$MODE" = "verify" ]; then
  echo "== 体检（不改动） =="
  log "  default target : $(systemctl get-default)"
  log "  graphical      : $(systemctl is-active graphical.target 2>/dev/null)"
  for s in "${SERVICES[@]}"; do
    log "  $(printf '%-20s' "$s") active=$(systemctl is-active "$s" 2>/dev/null) enabled=$(systemctl is-enabled "$s" 2>/dev/null || echo n/a)"
  done
  for t in "${TARGETS[@]}"; do
    log "  $(printf '%-20s' "$t") $(systemctl is-enabled "$t" 2>/dev/null || echo n/a)"
  done
  exit 0
fi

is_installed_unit() { systemctl list-unit-files "$1" 2>/dev/null | grep -q "^$1"; }

if [ "$MODE" = "dryrun" ]; then
  echo "== dry-run：将要执行的动作（加 --apply 才真正执行） =="
  log "  1) systemctl set-default $DEFAULT_TARGET      # 下次开机不进图形界面"
  log "  2) systemctl disable --now gdm3              # 立刻停掉图形登录管理器"
  for t in "${TARGETS[@]}"; do log "  3) systemctl mask $t"; done
  for s in "${SERVICES[@]}"; do
    if is_installed_unit "$s"; then log "  4) systemctl disable --now $s"; else skip "$s 未安装，跳过"; fi
  done
  log ""
  log "  预计收益：内存约省 0.9GiB（gdm3+gnome-shell+fwupd 等），idle 功耗 30W→20~25W"
  log "  回滚：sudo bash $0 --rollback"
  exit 0
fi

if [ "$MODE" = "rollback" ]; then
  echo "== 回滚 =="
  prev=""
  [ -f "$BACKUP_DIR/slim-prev-target" ] && prev="$(cat "$BACKUP_DIR/slim-prev-target")"
  [ -z "$prev" ] && prev=graphical.target
  log "  1) systemctl set-default $prev"
  log "  2) systemctl unmask ${TARGETS[*]}"
  for t in "${TARGETS[@]}"; do systemctl unmask "$t" 2>/dev/null && ok "unmask $t"; done
  for s in "${SERVICES[@]}"; do
    is_installed_unit "$s" || { skip "$s 未安装"; continue; }
    systemctl enable --now "$s" >/dev/null 2>&1 && ok "enable --now $s" || warn "$s 恢复失败"
  done
  systemctl set-default "$prev" >/dev/null 2>&1 && ok "default target → $prev"
  systemctl enable --now gdm3 >/dev/null 2>&1 && ok "gdm3 已恢复" || warn "gdm3 恢复失败（可手动 systemctl start gdm3）"
  log "  提示：图形界面要下次重启或 start graphical.target 才完全起来。"
  exit 0
fi

echo "== apply =="
mkdir -p "$BACKUP_DIR"
systemctl get-default > "$BACKUP_DIR/slim-prev-target"
ok "已备份原默认 target → $BACKUP_DIR/slim-prev-target"

systemctl set-default "$DEFAULT_TARGET" >/dev/null && ok "default target → $DEFAULT_TARGET" || warn "set-default 失败"

if systemctl is-active --quiet gdm3; then
  systemctl disable --now gdm3 >/dev/null 2>&1 && ok "gdm3 已停用" || warn "gdm3 停用失败"
else
  skip "gdm3 未运行"
fi

for t in "${TARGETS[@]}"; do
  systemctl mask "$t" >/dev/null 2>&1 && ok "mask $t" || warn "mask $t 失败"
done

for s in "${SERVICES[@]}"; do
  is_installed_unit "$s" || { skip "$s 未安装"; continue; }
  if systemctl is-active --quiet "$s"; then
    systemctl disable --now "$s" >/dev/null 2>&1 && ok "disable --now $s" || warn "$s 停用失败"
  else
    systemctl disable "$s" >/dev/null 2>&1 && ok "disable $s（本就未运行）" || warn "$s disable 失败"
  fi
done

echo ""
log "完成。当前默认 target: $(systemctl get-default)"
log "回滚：sudo bash $0 --rollback"
log "复查：bash $0 --verify"
