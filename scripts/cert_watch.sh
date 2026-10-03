#!/usr/bin/env bash
# cert_watch.sh —— Let's Encrypt 证书「到期 / 续期风险」监控（只读：不签、不删、不续）
#
# 为什么要有它：certbot.timer 每天跑两次，失败是**静默**的。实测两类坑：
#   ① 跨境链路抖动（到 acme 端点偶发失败）；
#   ② 孤儿证书：站点与 DNS 都没了，renewal 配置还在 ⇒ 每次 renew 必 NXDOMAIN。
#
# 用法（在装证书的那台机器上以 root 跑）：
#   ./cert_watch.sh                  # 人类可读输出；有告警就写状态文件并退出 1
#   ./cert_watch.sh --quiet          # 只在有告警时输出（systemd 单元用这个）
#   ./cert_watch.sh --dry-run        # 额外对每张证书跑 certbot renew --dry-run（联网、慢）
#   ./cert_watch.sh --no-state       # 只打印，不写状态文件（自测用）
#   CERT_WATCH_THRESHOLD=30 ./cert_watch.sh
#
# 退出码：0 = 正常；1 = 有告警；2 = 环境问题（缺 certbot 等）
set -uo pipefail

THRESHOLD="${CERT_WATCH_THRESHOLD:-20}"
LOG="${CERT_WATCH_LOG:-/var/log/cert-watch.log}"
STATE_DIR="${CERT_WATCH_STATE_DIR:-/var/lib/cert-watch}"
QUIET=0; DRY=0; STATE=1
for a in "$@"; do
  case "$a" in
    --quiet) QUIET=1 ;;
    --dry-run) DRY=1 ;;
    --no-state) STATE=0 ;;
    -h|--help) sed -n "2,16p" "$0"; exit 0 ;;
    *) echo "cert_watch: 未知参数 $a" >&2; exit 2 ;;
  esac
done

command -v certbot >/dev/null 2>&1 || { echo "cert_watch: 找不到 certbot" >&2; exit 2; }

OUT=""; WARN=0; COUNT=0
add() { printf -v OUT "%s%s\n" "$OUT" "$1"; }

# ---- 1) 到期日 ----
CERT_TXT="$(certbot certificates 2>/dev/null)"
if [ -z "$CERT_TXT" ]; then
  add "  [X] certbot certificates 输出为空 —— certbot 本身可能有问题"
  WARN=1
fi
now=$(date +%s)
while IFS="|" read -r name exp; do
  [ -n "$name" ] || continue
  COUNT=$((COUNT+1))
  clean="${exp%% (*}"
  ep="$(date -d "$clean" +%s 2>/dev/null)"
  if [ -z "$ep" ]; then
    add "  [X] $name：到期日解析失败（$exp）"; WARN=1; continue
  fi
  days=$(( (ep - now) / 86400 ))
  if [ "$days" -lt "$THRESHOLD" ]; then
    add "  [X] $name：${days} 天后到期（$clean）—— 低于阈值 ${THRESHOLD} 天"
    WARN=1
  else
    add "  [ok] $name：${days} 天后到期（$clean）"
  fi
done < <(printf "%s\n" "$CERT_TXT" | awk '/^[[:space:]]*Certificate Name:/ { name=$3 } /^[[:space:]]*Expiry Date:/ { sub(/^[[:space:]]*Expiry Date:[[:space:]]*/, ""); print name "|" $0 }')

# ---- 2) renewal 配置里的域名是否解析（孤儿证书检测）----
for f in /etc/letsencrypt/renewal/*.conf; do
  [ -e "$f" ] || break
  cn="$(basename "$f" .conf)"
  doms="$(awk -F'=[[:space:]]*' '/^[[:space:]]*domains[[:space:]]*=/{print $2; exit}' "$f")"
  [ -n "$doms" ] || doms="$cn"
  bad=""
  for d in ${doms//,/ }; do
    getent hosts "$d" >/dev/null 2>&1 || bad="${bad:+$bad, }$d"
  done
  if [ -n "$bad" ]; then
    add "  [X] $cn：域名不解析（$bad）⇒ renew 必失败；不用了就 certbot delete，要用就补 DNS"
    WARN=1
  fi
done

# ---- 3) 上一轮 certbot 服务结果 ----
RESULT="$(systemctl show certbot.service -p Result --value 2>/dev/null)"
WHEN="$(systemctl show certbot.service -p ExecMainExitTimestamp --value 2>/dev/null)"
if [ -n "$RESULT" ] && [ "$RESULT" != "success" ]; then
  add "  [X] certbot.service 上次结果 = $RESULT（${WHEN:-时间未知}）"
  WARN=1
elif [ -n "$WHEN" ]; then
  add "  [ok] certbot.service 上次结果 = success（$WHEN）"
fi

# ---- 4) 可选：逐证书 dry-run（联网，慢）----
if [ "$DRY" = "1" ]; then
  for f in /etc/letsencrypt/renewal/*.conf; do
    [ -e "$f" ] || break
    cn="$(basename "$f" .conf)"
    if timeout 120 certbot renew --dry-run --cert-name "$cn" >/dev/null 2>&1; then
      add "  [ok] dry-run $cn"
    else
      add "  [X] dry-run $cn 失败（见 /var/log/letsencrypt/letsencrypt.log）"; WARN=1
    fi
  done
fi

# ---- 5) 输出 / 落盘 ----
if [ "$WARN" = "0" ]; then
  [ "$QUIET" = "0" ] && printf "cert_watch: 全部正常（%s 张证书，阈值 %s 天）\n%s" "$COUNT" "$THRESHOLD" "$OUT"
  [ "$STATE" = "1" ] && rm -f "$STATE_DIR/alert.txt"
else
  printf "cert_watch: 有告警（%s 张证书，阈值 %s 天）\n%s" "$COUNT" "$THRESHOLD" "$OUT" >&2
  if [ "$STATE" = "1" ]; then
    mkdir -p "$STATE_DIR"
    { echo "！证书告警（cert_watch $(date "+%F %T")，阈值 ${THRESHOLD} 天）"; printf "%s" "$OUT"; } > "$STATE_DIR/alert.txt"
    chmod 0644 "$STATE_DIR/alert.txt"
  fi
fi

if [ "$STATE" = "1" ]; then
  { printf "%s cert_watch threshold=%s certs=%s warn=%s\n" "$(date "+%F %T")" "$THRESHOLD" "$COUNT" "$WARN"; printf "%s" "$OUT"; } >> "$LOG" 2>/dev/null
fi

[ "$WARN" = "0" ] && exit 0 || exit 1
