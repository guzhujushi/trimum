#!/usr/bin/env bash
# 用 .env 里的 GITHUB_TOKEN 推送（token 不写进 .git/config，也不写进任何入库文件）
# 用法：scripts/git-push.sh [分支]   （默认 server）
set -uo pipefail
BRANCH="${1:-server}"
ROOT="$(git rev-parse --show-toplevel)" || exit 1
ENVF="$ROOT/.env"
[ -f "$ENVF" ] || { echo "[git-push] 找不到 $ENVF" >&2; exit 1; }
TOKEN="$(sed -n 's/^GITHUB_TOKEN=//p' "$ENVF" | head -1 | tr -d '\r')"
[ -n "$TOKEN" ] || { echo "[git-push] $ENVF 里没有 GITHUB_TOKEN" >&2; exit 1; }
URL="$(git remote get-url origin)"
HOSTPATH="${URL#https://}"
HOSTPATH="${HOSTPATH#*@}"
echo "[git-push] $BRANCH -> https://$HOSTPATH （token 取自 .env，不落盘到 .git）"
git -c credential.helper= push "https://x-access-token:$TOKEN@$HOSTPATH" "$BRANCH"
