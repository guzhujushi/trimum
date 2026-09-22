#!/usr/bin/env bash
# 真机隧道一键恢复：解锁 keyring（可选）→ 拉起 code tunnel（脱离会话）→ 报状态
#
# 用法：
#   ~/bin/tunnel-up                              # 交互式（会提示输登录口令）
#   TRIMUM_PW_FILE=/tmp/.pw ~/bin/tunnel-up      # 从 0600 文件读口令（非交互）
#   TRIMUM_PW_FILE=~/.config/trimum/tunnel.pw ~/bin/tunnel-up   # 长期方案②就指到这里
#
# 为什么需要口令：GitHub 凭据存在 gnome-keyring 里，会话一结束 keyring 就锁；
# 没有桌面会话时得手动 unlock 一次，隧道才认得"已登录"。
set -u
export PATH="$HOME/.local/bin:$PATH"
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

if timeout 20 code tunnel status 2>/dev/null | grep -q '"Connected"'; then
  echo "[3/3] 隧道已在跑（Connected），无需重启进程"
  exit 0
fi

pkill -f "code tunnel" 2>/dev/null; sleep 1
setsid nohup "$HOME/.local/bin/code" tunnel --accept-server-license-terms --name tianyi >> "$LOG" 2>&1 < /dev/null &
sleep 16
echo "[3/3] 状态：$(timeout 20 code tunnel status 2>&1 | head -1)"
echo "       入口：https://vscode.dev/tunnel/tianyi"
