#!/usr/bin/env bash
# 一键（重）装真机的三个用户级 systemd 服务：trimum-web / trimum-tunnel / trimum-mihomo
#
# 用法（仓库里跑，或 scp 到真机 /tmp 后 bash）：
#   bash scripts/install_user_units.sh
#
# 前提：
#   ~/.local/bin/code            VS Code CLI（隧道 / serve-web）
#   ~/.config/trimum/tunnel.pw   0600，解锁 gnome-keyring 用（没有则隧道会要设备码）
#   ~/bin/mihomo                 可选；没有就跳过第三个服务（见 scripts/install_mihomo.sh）
#
# 重启后自启还需（sudo，本人跑）：scripts/enable_linger.sh
set -u
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.config/systemd/user"
mkdir -p "$DEST" "$HOME/bin"
install -m 0755 "$SRC/user-units/serve-web-run.sh" "$HOME/bin/serve-web-run"
install -m 0755 "$SRC/user-units/tunnel-run.sh" "$HOME/bin/tunnel-run"
for u in trimum-web trimum-tunnel trimum-mihomo; do
  install -m 0644 "$SRC/user-units/$u.service" "$DEST/$u.service"
done
systemctl --user daemon-reload
systemctl --user enable --now trimum-web.service trimum-tunnel.service
if [ -x "$HOME/bin/mihomo" ]; then
  systemctl --user enable --now trimum-mihomo.service
else
  echo "（跳过 trimum-mihomo：~/bin/mihomo 不在，先跑 scripts/install_mihomo.sh）"
fi
sleep 12
for u in trimum-web trimum-tunnel trimum-mihomo; do
  printf "%-22s active=%-8s enabled=%s\n" "$u" "$(systemctl --user is-active "$u" 2>/dev/null)" "$(systemctl --user is-enabled "$u" 2>/dev/null)"
done
IP="$(tailscale ip -4 2>/dev/null | head -1)"
echo "web:    http://$IP:8080/  →  $(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "http://$IP:8080/")"
echo "tunnel: $(timeout 20 "$HOME/.local/bin/code" tunnel status 2>&1 | head -c 120)"
echo "linger: $(loginctl show-user "$USER" 2>/dev/null | grep -i linger || echo "未开（需 sudo：scripts/enable_linger.sh）")"
