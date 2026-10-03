#!/usr/bin/env bash
# T2：VS Code Web（code serve-web），只绑 Tailscale IP，手机浏览器直连
#
# 用法：
#   ~/bin/serve-web-up          # 装了 systemd user service（trimum-web）就重启它，否则后台起一个
#   TRIMUM_WEB_PORT=8081 ~/bin/serve-web-up
#   关掉（service 在位）：systemctl --user stop trimum-web.service
#
# 为什么绑 Tailscale IP 而不是 0.0.0.0：Tailscale 自带加密与设备身份，
# 只有 tailnet 内设备可达 ⇒ 不需要域名 / 证书 / 备案 / frp，也不暴露公网。
set -u
export PATH="$HOME/.local/bin:$PATH"
UNIT="trimum-web.service"
IP="$(tailscale ip -4 2>/dev/null | head -1)"
PORT="${TRIMUM_WEB_PORT:-8080}"
LOG="$HOME/.vscode-web/serve-web.log"
mkdir -p "$(dirname "$LOG")"
if [ -z "$IP" ]; then echo "Tailscale 没拿到 IP，退出"; exit 1; fi

if systemctl --user cat "$UNIT" >/dev/null 2>&1; then
  systemctl --user restart "$UNIT"
  sleep 8
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "http://$IP:$PORT/")
  echo "$(systemctl --user is-active "$UNIT")  HTTP $code  =>  http://$IP:$PORT/"
  case "$code" in 200|202) exit 0 ;; *) echo "查：journalctl --user -u $UNIT -n 40 --no-pager"; exit 1 ;; esac
fi

# ---- 回退路径（未装 service）----
if curl -s -o /dev/null --max-time 3 "http://$IP:$PORT/"; then
  echo "已在运行：http://$IP:$PORT/"; exit 0
fi
pkill -f "code serve-web" 2>/dev/null; sleep 1
setsid nohup "$HOME/.local/bin/code" serve-web --host "$IP" --port "$PORT" \
  --without-connection-token --accept-server-license-terms \
  --default-folder "$HOME/trimum" --disable-telemetry >>"$LOG" 2>&1 < /dev/null &
sleep 6
echo "HTTP $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://$IP:$PORT/")  =>  http://$IP:$PORT/"
# 注意：首次启动会下载 server 端，期间返回 202 / 页面提示 downloading，下完自动变 200
