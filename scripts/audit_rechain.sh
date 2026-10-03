#!/usr/bin/env bash
# 审计链归档重建（§4.2.2 片 A1 上线步骤）
#
# 背景：`audit.jsonl` 一旦出现「链已开始之后又出现无 hmac 的行」（旧版本写者混写，
# 例如还在跑旧代码的 daemon），`AuditStore.verify_chain()` 会**永久红**，且轮转改变不了顺序。
# 回到绿的唯一办法是把旧段归档、让链从新文件重新起头。
#
# 用法：
#   bash scripts/audit_rechain.sh                 # dry-run：只打印将要做什么
#   bash scripts/audit_rechain.sh --apply         # 真正执行（可加 --yes 跳过确认）
#
# 前置：先同步并重启新版 daemon（否则旧写者接着写 legacy 行，白重建）：
#   sudo bash scripts/sync_opt_tree.sh && bash scripts/restart_trmd.sh
#
# 注意：本脚本**不删除**任何数据 —— 旧文件是 `mv` 进 `audit-archive-<时间戳>/`；`*.lock` 原地不动。
set -euo pipefail

DATA_DIR="${TRIMUM_DATA_DIR:-$HOME/.local/share/trimum}"
STAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$DATA_DIR/audit-archive-$STAMP"
APPLY=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg（--help 看用法）" >&2; exit 2 ;;
  esac
done

MOVES=()
for name in audit.jsonl audit.jsonl.1 audit.jsonl.chained; do
  [ -e "$DATA_DIR/$name" ] && MOVES+=("$DATA_DIR/$name")
done

echo "数据目录：$DATA_DIR"
if [ "${#MOVES[@]}" -eq 0 ]; then
  echo "没有可归档的文件（audit.jsonl / .1 / .chained 都不在）—— 无需重建。"
  exit 0
fi
echo "将归档到：$ARCHIVE/"
for f in "${MOVES[@]}"; do printf '  mv %s\n' "$f"; done
echo "（*.lock 原地保留；本脚本不做任何删除）"

if [ "$APPLY" -eq 0 ]; then
  echo
  echo "[dry-run] 未做任何改动。要执行：bash scripts/audit_rechain.sh --apply"
  exit 0
fi

if [ "$ASSUME_YES" -eq 0 ]; then
  printf '确认执行？(yes/N) '; read -r answer
  [ "$answer" = "yes" ] || { echo "已取消。"; exit 1; }
fi

mkdir -p "$ARCHIVE"
for f in "${MOVES[@]}"; do mv -v "$f" "$ARCHIVE/"; done
echo "归档完成：$ARCHIVE"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "$REPO_DIR/.venv/bin/python" ]; then
  echo "重建后校验（空文件应为 ok=True, errors=[]）："
  "$REPO_DIR/.venv/bin/python" - "$DATA_DIR/audit.jsonl" <<'PY'
import sys
sys.path.insert(0, "src")
from trimum_core.audit_store import AuditStore
print(AuditStore(path=sys.argv[1]).verify_chain())
PY
else
  echo "（未找到 $REPO_DIR/.venv/bin/python，跳过校验）"
fi
echo "下一步：重启新版 daemon 后，新链会从这个空文件重新起头。"
