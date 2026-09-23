#!/usr/bin/env bash
# 前台运行 VS Code 隧道（给 systemd 用）：先解锁 keyring，再 exec 隧道
# 口令文件：~/.config/trimum/tunnel.pw（0600）。见 docs/OPERATIONS.md「真机常驻」。
set -u
export PATH="$HOME/.local/bin:$PATH"
PW_FILE="$HOME/.config/trimum/tunnel.pw"
if [ -f "$PW_FILE" ]; then
  eval "$(cat "$PW_FILE" | gnome-keyring-daemon --unlock --replace --components=secrets 2>/dev/null)"
  echo "[tunnel-run] keyring 解锁已尝试"
else
  echo "[tunnel-run] 没有 $PW_FILE，跳过 keyring 解锁"
fi
echo "[tunnel-run] 登录态：$(timeout 20 code tunnel user show 2>&1 | head -1)"
exec "$HOME/.local/bin/code" tunnel --accept-server-license-terms --name tianyi
