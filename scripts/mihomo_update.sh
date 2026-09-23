#!/usr/bin/env bash
# 真机 mihomo 配置刷新：用 Clash UA 拉机场订阅 → 打两个补丁 → 原子替换 → 重启服务
#
#   ~/bin/mihomo-update
#
# 为什么要 UA：同一订阅在 clash 系 UA 下给 Clash YAML，其它 UA 给 base64（实测 2026-09-23）。
# 两个补丁：
#   1. mixed-port → 7890（与 ~/bin/with-proxy、文档口径统一）
#   2. dns.listen  :53 → 127.0.0.1:1053（:53 是特权端口，用户级 service 绑不上）
set -u
URL_FILE="$HOME/.config/mihomo/subscription.url"
CFG="$HOME/.config/mihomo/config.yaml"
NEW="$HOME/.config/mihomo/.config.new"
UA="clash-verge/1.6.0"

[ -f "$URL_FILE" ] || { echo "缺 $URL_FILE（0600，内容=机场订阅链接，不入仓库）"; exit 1; }
url="$(tr -d "\r\n" < "$URL_FILE")"
code="$(curl -s -A "$UA" -o "$NEW" -w "%{http_code}" --max-time 60 "$url")"
if [ "$code" != "200" ] || ! grep -q "^proxies:" "$NEW"; then
  echo "拉取失败（HTTP $code）或返回的不是 Clash 配置 —— 保留原配置，不动服务"
  rm -f "$NEW"; exit 1
fi
sed -i "s/^mixed-port:.*/mixed-port: 7890/" "$NEW"
sed -i "s/listen: .:53./listen: 127.0.0.1:1053/" "$NEW"
chmod 600 "$NEW"
install -m 600 "$NEW" "$CFG"; rm -f "$NEW"
echo "配置已更新：$(wc -l < "$CFG") 行 / $(grep -m1 "^mixed-port:" "$CFG") / $(grep -m1 "listen:" "$CFG" | tr -d " ")"
systemctl --user restart trimum-mihomo.service
sleep 6
echo "service=$(systemctl --user is-active trimum-mihomo.service)"
echo "api=$(curl -s --max-time 5 http://127.0.0.1:9090/version | head -c 140)"
