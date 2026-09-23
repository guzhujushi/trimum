#!/usr/bin/env bash
# 真机出网代理（v2，2026-09-23）：优先级 = 本机 mihomo(127.0.0.1:7890) → Windows UniClash(经 Tailscale) → 直连
#
# 用法：
#   ~/bin/with-proxy git fetch origin server
#   ~/bin/with-proxy npm i -g @openai/codex
#
# 为什么这么排：本机 mihomo 直连机场，RTT 与直连同量级；经 Tailscale 借 Windows 的 UniClash
# 走 DERP 中继（hkg），慢 4~10 倍且依赖笔记本开机 —— 只当兜底。
set -u
LOCAL_HOST=127.0.0.1
LOCAL_PORT=7890
WIN_HOST=100.124.243.30
WIN_PORT=7993
NO_PROXY_LIST="localhost,127.0.0.1,100.115.86.48,100.124.243.30,models.sjtu.edu.cn,api.deepseek.com"

proxy_alive() { timeout "$3" bash -c "cat < /dev/null > /dev/tcp/$1/$2" 2>/dev/null; }

if proxy_alive "$LOCAL_HOST" "$LOCAL_PORT" 3; then
  P="http://$LOCAL_HOST:$LOCAL_PORT"; TAG="本机 mihomo"
elif proxy_alive "$WIN_HOST" "$WIN_PORT" 4; then
  P="http://$WIN_HOST:$WIN_PORT"; TAG="备用通道（Tailscale→Windows UniClash，慢 4~10 倍）"
else
  P=""; TAG=""
fi

if [ -n "$P" ]; then
  export http_proxy="$P" https_proxy="$P" all_proxy="$P"
  export HTTP_PROXY="$P" HTTPS_PROXY="$P" ALL_PROXY="$P"
  export no_proxy="$NO_PROXY_LIST" NO_PROXY="$NO_PROXY_LIST"
  echo "[with-proxy] $TAG → $P" >&2
else
  echo "[with-proxy] 两条代理都不可达 ⇒ 降级直连" >&2
fi

exec "$@"
