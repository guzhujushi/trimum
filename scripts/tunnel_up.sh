#!/usr/bin/env bash
# 真机隧道一键恢复（v2，2026-09-23）：优先走 systemd user service（trimum-tunnel），
# 没装 service 时回退到老的「解锁 keyring + setsid nohup」路径。
#
# 用法：
#   ~/bin/tunnel-up                              # 直接跑（service 在位时=restart + 报状态）
#   TRIMUM_PW_FILE=/tmp/.pw ~/bin/tunnel-up      # 自定义口令文件（默认 ~/.config/trimum/tunnel.pw）
#
# 为什么需要口令：GitHub 凭据在 gnome-keyring 里，会话一结束 keyring 就锁；
# 没有桌面会话时得解锁一次，隧道才认得「已登录」。口令文件必须 0600。
# 7x24 常驻还需 `loginctl enable-linger guzhujushi`（sudo，见 scripts/enable_linger.sh）。
set -u
export PATH="$HOME/.local/bin:$PATH"
UNIT="trimum-tunnel.service"

if systemctl --user cat "$UNIT" >/dev/null 2>&1; then
  systemctl --user restart "$UNIT"
  sleep 18
  status="$(timeout 20 code tunnel status 2>&1 | head -c 400)"
  echo "unit=$(systemctl --user is-active "$UNIT")"
  echo "$status"
  echo "入口：https://vscode.dev/tunnel/tianyi"
  case "$status" in
    *'"Connected"'*) exit 0 ;;
    *) echo "未 Connected —— 查：journalctl --user -u $UNIT -n 40 --no-pager"; exit 1 ;;
  esac
fi

# ---- 回退路径（未装 service）----
LOG="$HOME/.code-tunnel-logs/login.log"
mkdir -p "$(dirname "$LOG")"

PW=""
if [ -n "${TRIMUM_PW_FILE:-}" ] && [ -f "${TRIMUM_PW_FILE}" ]; then
  PW="$(cat "${TRIMUM_PW_FILE}")"
elif [ -f "$HOME/.config/trimum/tunnel.pw" ]; then
  PW="$(cat "$HOME/.config/trimum/tunnel.pw")"
elif [ -t 0 ]; then
  printf '真机登录口令（解锁 keyring 用，不回显）: ' >&2
  read -rs PW </dev/tty || true
  echo >&2
fi

if [ -n "$PW" ]; then
  eval "$(printf '%s' "$PW" | gnome-keyring-daemon --unlock --replace --components=secrets 2>/dev/null)"
  unset PW
  echo "[1/3] keyring 已尝试解锁"
else
  echo "[1/3] 没拿到口令，跳过解锁（若 keyring 是锁的，隧道会又要设备码）"
fi

echo "[2/3] 登录态：$(timeout 20 code tunnel user show 2>&1 | head -1)"
pkill -f "code tunnel" 2>/dev/null; sleep 1
setsid nohup "$HOME/.local/bin/code" tunnel --accept-server-license-terms --name tianyi >> "$LOG" 2>&1 < /dev/null &
sleep 16
echo "[3/3] 状态：$(timeout 20 code tunnel status 2>&1 | head -1)"
echo "       入口：https://vscode.dev/tunnel/tianyi"
