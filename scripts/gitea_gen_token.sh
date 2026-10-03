#!/usr/bin/env bash
# 生成 Gitea admin access token（给「博客好友同步」等脚本用）。
#
# GITEA_ADMIN_TOKEN 不是 Gitea 里现成能看的东西 —— 它只能在 Gitea 里**生成**：
#   A) 网页：登录 code.guzhujushi.cn → 右上头像 → 设置(Settings) → 应用(Applications)
#      → 「管理令牌 / Generate New Token」→ 勾选 admin 相关 scope → 生成后**只显示一次**，复制。
#   B) 命令行（本脚本，真机 sudo）—— 等价且更省事。
#
# 用法：
#   bash scripts/gitea_gen_token.sh            # 打印将执行的命令
#   sudo bash scripts/gitea_gen_token.sh --apply
# 生成后把 token 粘进 ~/trimum/.env 的 GITEA_ADMIN_TOKEN=...
set -uo pipefail
USER_NAME="${GITEA_USER:-guzhujushi}"
TOKEN_NAME="${GITEA_TOKEN_NAME:-trimum-sync}"
APPLY=0
for a in "$@"; do case "$a" in
  --apply) APPLY=1;; -h|--help) sed -n '2,16p' "$0"|sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "未知参数：$a" >&2; exit 2;; esac; done
CMD=(/usr/local/bin/gitea admin user generate-access-token --config /etc/gitea/app.ini --username "$USER_NAME" --token-name "$TOKEN_NAME" --scopes all --raw)
echo "将执行："
echo "  sudo -u git ${CMD[*]}"
if [ "$APPLY" -eq 0 ]; then echo; echo "（加 --apply 真跑）"; exit 0; fi
[ "$(id -u)" -eq 0 ] || { echo "需要 root：sudo bash $0 --apply" >&2; exit 1; }
sudo -u git "${CMD[@]}"
echo
echo "↑ 把上面的 token 填进 ~/trimum/.env 的 GITEA_ADMIN_TOKEN="
