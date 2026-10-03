#!/usr/bin/env bash
# mihomo（Clash Meta 核心）用户级安装 + 链路实测（先用 DIRECT，订阅之后再插）
#
# 用法：scp 到真机 /tmp 后 bash，或直接 bash scripts/install_mihomo.sh
# 关键：一条 systemd user service（trimum-mihomo），监听 127.0.0.1:7890；订阅走 ~/.config/mihomo/config.yaml
#       **机场订阅链接不入仓库**（红线：密钥/订阅只记位置与形状）
set -u
echo "===== 1) 找最新 release 资产 ====="
API=https://api.github.com/repos/MetaCubeX/mihomo/releases/latest
json="$(curl -s --max-time 20 "$API")"
tag="$(printf "%s" "$json" | grep -m1 '"tag_name"' | cut -d'"' -f4)"
echo "tag=$tag"
url="$(printf "%s" "$json" | grep -o 'https://[^"]*mihomo-linux-amd64-compatible[^"]*\.gz' | head -1)"
[ -n "$url" ] || url="$(printf "%s" "$json" | grep -o 'https://[^"]*mihomo-linux-amd64[^"]*\.gz' | head -1)"
echo "asset=${url%%\?*}"
echo
echo "===== 2) 下载并安装到 ~/bin/mihomo ====="
cd /tmp || exit 1
curl -sL --max-time 180 -o mihomo.gz "$url" && echo "下载 $(stat -c %s mihomo.gz) bytes"
gzip -dc mihomo.gz > "$HOME/bin/mihomo" && chmod +x "$HOME/bin/mihomo"
"$HOME/bin/mihomo" -v 2>&1 | head -3
echo
echo "===== 3) 最小配置（DIRECT only，用于验证链路） ====="
mkdir -p "$HOME/.config/mihomo"
test -f "$HOME/.config/mihomo/config.yaml" || cat > "$HOME/.config/mihomo/config.yaml" <<'EOF'
# trimum: mihomo 最小配置（占位）。真正的机场订阅走下面 providers 段，链接不入仓库。
mixed-port: 7890
allow-lan: false
mode: rule
log-level: info
external-controller: 127.0.0.1:9090
proxies: []
proxy-groups:
  - name: PROXY
    type: select
    proxies: [DIRECT]
rules:
  - MATCH,PROXY
EOF
echo "config: $(wc -l < "$HOME/.config/mihomo/config.yaml") 行"
echo
echo "===== 4) 起 systemd user service ====="
cat > "$HOME/.config/systemd/user/trimum-mihomo.service" <<'EOF'
[Unit]
Description=trimum: mihomo (Clash Meta core) for the host proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/bin/mihomo -d %h/.config/mihomo
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now trimum-mihomo.service 2>&1 | tail -n 2
sleep 8
echo "is-active=$(systemctl --user is-active trimum-mihomo.service)"
ss -ltn | grep -E ":(7890|9090)\b" || echo "端口没起来"
echo
echo "===== 5) 链路实测：经 127.0.0.1:7890 出网 ====="
for u in https://github.com https://api.github.com; do
  printf "%-28s proxy=%s\n" "$u" "$(curl -s -o /dev/null -w "%{http_code} %{time_total}s" --max-time 20 -x http://127.0.0.1:7890 "$u")"
done
echo
echo "===== 6) journal 尾部（有报错就看这里） ====="
journalctl --user -u trimum-mihomo.service -n 8 --no-pager 2>&1 | tail -n 8
