#!/usr/bin/env bash
# 让用户级 systemd 服务在无人登录时也能起 —— trimum-web / trimum-tunnel 重启后自启的前提。
#
# 需要 sudo，由本人执行（agent 不代跑）：
#   scp scripts/enable_linger.sh guzhujushi@100.115.86.48:/tmp/
#   ssh guzhujushi@100.115.86.48 "sudo bash /tmp/enable_linger.sh"
#
# 撤销：sudo loginctl disable-linger guzhujushi
set -euo pipefail
USER_NAME="${1:-guzhujushi}"
if [ "$(id -u)" -ne 0 ]; then echo "需要 root：sudo bash $0" >&2; exit 1; fi
loginctl enable-linger "$USER_NAME"
echo "--- linger 现状 ---"
loginctl show-user "$USER_NAME" | grep -iE "^(User|Linger)=" || true
echo "--- 用户单元 ---"
systemctl --user -M "${USER_NAME}@" list-units "trimum-*" --all --no-pager 2>/dev/null || echo "（root 拿不到用户管理器属正常，登录后再看：systemctl --user status trimum-web trimum-tunnel）"
echo "OK：linger 已开，重启后 trimum-web / trimum-tunnel 会随用户管理器自启。"
