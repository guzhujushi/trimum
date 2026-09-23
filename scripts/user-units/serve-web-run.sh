#!/usr/bin/env bash
# 前台运行 VS Code Web（给 systemd 用）；交互式后台启动用 ~/bin/serve-web-up
set -u
export PATH="$HOME/.local/bin:$PATH"
IP="$(tailscale ip -4 2>/dev/null | head -1)"
: "${IP:?Tailscale 未拿到 IP}"
exec "$HOME/.local/bin/code" serve-web --host "$IP" --port "${TRIMUM_WEB_PORT:-8080}" \
  --without-connection-token --accept-server-license-terms \
  --default-folder "$HOME/trimum" --disable-telemetry
