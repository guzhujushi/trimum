#!/usr/bin/env bash
# vps_health.sh —— 云主机 / 常驻机「体检一览」（只读，不改任何配置）
#
# 用法：
#   ./vps_health.sh                  # 默认看 nginx frps gitea alist
#   ./vps_health.sh nginx frps dify  # 追加/替换要看的服务
#   ./vps_health.sh --full           # 额外跑 dry-run 类检查（联网、慢）
#
# 输出给谁看：人（贴进 STATUS.md 日志）——所以只打印「需要你知道」的东西。
set -uo pipefail

SERVICES=()
FULL=0
for a in "$@"; do case "$a" in
  --full) FULL=1 ;;
  *) SERVICES+=("$a") ;;
esac; done
[ "${#SERVICES[@]}" -gt 0 ] || SERVICES=(nginx frps gitea alist)

sec() { printf "\n== %s ==\n" "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

sec "主机 / 运行时长"
hostname; (hostnamectl 2>/dev/null | sed -n "1,2p") || true
uptime

sec "内存 / 磁盘"
free -m | head -2
df -h / | tail -1

sec "服务状态（${SERVICES[*]}）"
for s in "${SERVICES[@]}"; do
  printf "  %-10s active=%-8s enabled=%s\n" "$s" "$(systemctl is-active "$s" 2>&1)" "$(systemctl is-enabled "$s" 2>&1)"
done

sec "failed 单元"
FAILED="$(systemctl list-units --state=failed --no-legend 2>/dev/null | awk "{print \$1}")"
[ -n "$FAILED" ] && printf "  %s\n" $FAILED || echo "  （无）"

sec "监听端口"
PUB=""; LOOP=""
while read -r addr; do
  case "$addr" in
    127.*|\[::1\]:*) LOOP="${LOOP}${LOOP:+ }${addr}" ;;
    *) PUB="${PUB}${PUB:+ }${addr}" ;;
  esac
done < <(ss -ltn 2>/dev/null | awk "NR>1 {print \$4}" | sort -u)
printf "  公网/其他: %s\n" "${PUB:-（无）}"
printf "  loopback : %s\n" "${LOOP:-（无）}"

sec "主机防火墙"
if have ufw; then ufw status | head -14; elif have firewall-cmd; then firewall-cmd --list-all; else echo "  （无 ufw / firewalld）"; fi

sec "nginx"
if have nginx; then
  nginx -t 2>&1 | tail -1
  echo "  启用站点: $(ls /etc/nginx/sites-enabled/ 2>/dev/null | tr "\n" " ")"
  echo "  上游指向:"
  nginx -T 2>/dev/null | grep -E "proxy_pass|server [0-9]" | sed "s/^[[:space:]]*/    /" | sort -u | head -12
  ERR="$(tail -3 /var/log/nginx/error.log 2>/dev/null | cut -c1-120)"
  [ -n "$ERR" ] && { echo "  最近 error.log:"; printf "%s\n" "$ERR" | sed "s/^/    /"; }
else echo "  （未装 nginx）"; fi

sec "证书（certbot）"
if have certbot; then
  certbot certificates 2>/dev/null | grep -E "Certificate Name|Domains|Expiry Date" | sed "s/^[[:space:]]*/  /"
  echo "  续期定时器:"; systemctl list-timers certbot.timer --no-pager 2>/dev/null | sed -n "2p" | sed "s/^/    /"
  [ -x /usr/local/bin/cert_watch.sh ] && { echo "  cert-watch 上次结果:"; tail -2 /var/log/cert-watch.log 2>/dev/null | sed "s/^/    /"; }
else echo "  （未装 certbot）"; fi

sec "出网 / DNS（跨境链路体检）"
for h in acme-v02.api.letsencrypt.org github.com; do
  ip4="$(getent ahostsv4 "$h" 2>/dev/null | awk "NR==1{print \$1}")"
  printf "  %-32s A=%s" "$h" "${ip4:-解析失败}"
  if have curl; then
    code="$(timeout 8 curl -s -o /dev/null -w "%{http_code}" "https://$h/" 2>/dev/null)"
    printf " http=%s" "${code:-000}"
  fi
  echo
done
echo "  IPv6 默认路由: $(ip -6 route show default 2>/dev/null | head -1 || true)"
grep -vE "^#|^$" /etc/gai.conf 2>/dev/null | sed "s/^/  gai.conf: /"

sec "容器 / 其他常驻"
if have docker; then docker ps --format "  {{.Names}} | {{.Status}} | {{.Ports}}" 2>&1 | head -12; else echo "  （无 docker）"; fi

if [ "$FULL" = "1" ]; then
  sec "--full：certbot dry-run"
  timeout 180 certbot renew --dry-run 2>&1 | tail -5
fi

sec "结束"
echo "  贴这段进 STATUS.md 日志即可；有 X / failed / 000 的项才需要处理。"
