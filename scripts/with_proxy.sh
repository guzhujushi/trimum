#!/usr/bin/env bash
# 经 Tailscale 借 Windows(UniClash) 的代理执行命令 —— 备用通道，按需使用
#
# 用法：
#   ~/bin/with-proxy git fetch origin server
#   ~/bin/with-proxy npm i -g @openai/codex
#   ~/bin/with-proxy curl -sI https://api.github.com
#
# 为什么是"备用"：这条路走 Tailscale DERP 中继（hkg），RTT 150~250ms，
# 实测比真机直连慢 4~10 倍（github 3.3s vs 0.7s）。真机直连平时是好的，
# 所以**只在直连抽风（GnuTLS recv error / TLS 瞬断 / 超时）时用它**。
#
# 依赖：Windows 那台开着 + Tailscale 在线 + UniClash 在跑 +
#       Windows 侧 portproxy（100.124.243.30:7993 → 127.0.0.1:7993）还在。
# 代理不可达时**自动降级为直连**，不会把命令卡死。
set -u
PROXY_HOST=100.124.243.30
PROXY_PORT=7993
PROXY="http://${PROXY_HOST}:${PROXY_PORT}"

if timeout 4 bash -c "cat < /dev/null > /dev/tcp/${PROXY_HOST}/${PROXY_PORT}" 2>/dev/null; then
  export http_proxy="$PROXY" https_proxy="$PROXY" all_proxy="$PROXY"
  export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" ALL_PROXY="$PROXY"
  no_proxy="localhost,127.0.0.1,100.115.86.48,100.124.243.30,models.sjtu.edu.cn,api.deepseek.com"
  NO_PROXY="$no_proxy"
  export no_proxy NO_PROXY
  echo "[with-proxy] 经 $PROXY 执行：$*" >&2
else
  echo "[with-proxy] 代理不可达（Windows 关机 / UniClash 没开 / portproxy 丢了）⇒ 降级直连" >&2
fi
exec "$@"
