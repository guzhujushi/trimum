#!/usr/bin/env bash
# 一键（重）装真机的用户级 systemd 服务 + codex 的 LLM 环境注入：
#   trimum-web / trimum-tunnel / trimum-mihomo（另给前两个 unit 装 10-llm-env.conf drop-in）
#   emb-svc（可选，~/emb-svc 就位才装；原先是 crontab @reboot 拉起）
#
# 用法（仓库里跑，或 scp 到真机 /tmp 后 bash）：
#   bash scripts/install_user_units.sh
#
# 前提：
#   ~/.local/bin/code            VS Code CLI（隧道 / serve-web）
#   ~/.config/trimum/tunnel.pw   0600，解锁 gnome-keyring 用（没有则隧道会要设备码）
#   ~/.codex/env                 0600，**纯 KEY=VALUE**（LLM key）；缺了 codex 会报 Missing environment variable
#   ~/bin/mihomo                 可选；没有就跳过 trimum-mihomo（见 scripts/install_mihomo.sh）
#   ~/emb-svc/venv/bin/uvicorn   可选；没有就跳过 emb-svc
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

# codex 的 LLM key：给两个 VS Code unit 各加一个 drop-in，让扩展里跑的 codex 也拿到 key。
# 注意 systemd 的 EnvironmentFile **不认** `export KEY=VALUE`，所以 ~/.codex/env 必须是纯 KEY=VALUE
# （2026-09-24 起如此），详见 docs/OPERATIONS.md「codex 的 LLM key 注入与自检」。
for u in trimum-web trimum-tunnel; do
  install -d -m 0755 "$DEST/$u.service.d"
  cat > "$DEST/$u.service.d/10-llm-env.conf" <<'CONF'
# trimum LLM 环境（2026-09-24）：把 ~/.codex/env 的 key 注入本 unit
[Service]
EnvironmentFile=-%h/.codex/env
CONF
done
if [ ! -f "$HOME/.codex/env" ]; then
  echo "注意：~/.codex/env 不存在 —— codex 会报 Missing environment variable；"
  echo "      先用 ~/bin/codex-run ds，或建该文件（0600，纯 KEY=VALUE，键名见 docs/OPERATIONS.md）。"
fi
systemctl --user daemon-reload
systemctl --user enable --now trimum-web.service trimum-tunnel.service
if [ -x "$HOME/bin/mihomo" ]; then
  systemctl --user enable --now trimum-mihomo.service
else
  echo "（跳过 trimum-mihomo：~/bin/mihomo 不在，先跑 scripts/install_mihomo.sh）"
fi

# emb-svc（本地 embedding 服务 :18080）：源码树在仓库外（~/emb-svc），就位才装 unit
if [ -x "$HOME/emb-svc/venv/bin/uvicorn" ]; then
  install -m 0644 "$SRC/user-units/emb-svc.service" "$DEST/emb-svc.service"
  systemctl --user daemon-reload
  systemctl --user enable --now emb-svc.service
else
  echo "（跳过 emb-svc：~/emb-svc/venv/bin/uvicorn 不在）"
fi
if crontab -l 2>/dev/null | grep -q 'emb-svc/start.sh'; then
  echo "注意：crontab 里还有 @reboot emb-svc/start.sh，会和 emb-svc.service 抢 :18080；删它："
  echo "  crontab -l | grep -v 'emb-svc/start.sh' | crontab -"
fi
sleep 12
for u in trimum-web trimum-tunnel trimum-mihomo emb-svc; do
  printf "%-22s active=%-8s enabled=%s\n" "$u" "$(systemctl --user is-active "$u" 2>/dev/null)" "$(systemctl --user is-enabled "$u" 2>/dev/null)"
done
IP="$(tailscale ip -4 2>/dev/null | head -1)"
echo "web:    http://$IP:8080/  →  $(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "http://$IP:8080/")"
echo "tunnel: $(timeout 20 "$HOME/.local/bin/code" tunnel status 2>&1 | head -c 120)"
echo "linger: $(loginctl show-user "$USER" 2>/dev/null | grep -i linger || echo "未开（需 sudo：scripts/enable_linger.sh）")"
