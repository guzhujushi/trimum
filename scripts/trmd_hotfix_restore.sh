#!/usr/bin/env bash
# 紧急恢复：把部署树的 src 从 socket-patch 备份还原，并让 trmd 起回来（需 sudo）
#
# 背景（2026-09-21 21:09）：sync_opt_socket_patch.sh 把仓库 HEAD 的 api_server.py 装进了
# /opt/trimum/src，而它头一行 import 就是 `from .workflow_runtime import WorkflowRuntime`
# —— 部署树里没有 workflow_runtime.py（部署树比仓库旧一大截），于是 daemon 一启动就
# ModuleNotFoundError，systemd（Restart=always）每 5s 重启一次，NRestarts 一路涨。
# 加固脚本的冒烟正确判成 FAIL 并自动回滚了**单元**，但回滚只撤单元、不撤 src。
#
# 用法：
#   sudo bash /tmp/trmd_hotfix_restore.sh                     # 还原全部（回到同步前状态）
#   sudo bash /tmp/trmd_hotfix_restore.sh --only api_server.py # 只还原某一个
#   sudo bash /tmp/trmd_hotfix_restore.sh --dry-run            # 只报告
set -uo pipefail

APP_SRC=/opt/trimum/src
BACKUP_ROOT=/var/backups/trimum
UNIT=trmd
VENV_PY=/opt/trimum/venv/bin/python
TRM=/opt/trimum/venv/bin/trm

ONLY=""
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --only) shift || true; ONLY="${1:-}" ;;
    --only=*) ONLY="${1#--only=}" ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || { echo "需要 root：sudo bash $0" >&2; exit 1; }

BK="$(ls -1d "${BACKUP_ROOT}"/socket-patch-* 2>/dev/null | sort | tail -1)"
[ -n "$BK" ] || { echo "没找到 ${BACKUP_ROOT}/socket-patch-* 备份" >&2; exit 1; }
[ -d "$BK/src" ] || { echo "$BK 里没有 src/ 备份" >&2; exit 1; }
echo "备份：$BK"

echo "== 还原 $( [ -n "$ONLY" ] && echo "（仅 $ONLY）" || echo "（全部）" )"
restored=0
while IFS= read -r -d '' f; do
  rel="${f#"$BK/src/"}"
  if [ -n "$ONLY" ] && [ "$rel" != "trimum_core/$ONLY" ] && [ "$rel" != "$ONLY" ]; then continue; fi
  [ "$DRY" -eq 0 ] && install -D -o root -g root -m 0644 "$f" "$APP_SRC/$rel"
  echo "  $APP_SRC/$rel"
  restored=$((restored + 1))
done < <(find "$BK/src" -type f -print0)
if [ "$restored" -eq 0 ]; then echo "备份里没有匹配的文件（--only 写对了吗？）" >&2; exit 1; fi
if [ "$DRY" -eq 1 ]; then echo "--dry-run：什么都没改"; exit 0; fi

echo "== 护栏：部署树到底能不能 import（刚才就是漏了这一步）"
if "$VENV_PY" -c "import trimum_core.main" 2>/tmp/.trmd-import.err; then
  echo "  [PASS] import trimum_core.main 通过"
else
  echo "  [FAIL] import 仍然失败："
  sed 's/^/     /' /tmp/.trmd-import.err
  echo "  没有重启 daemon —— 先看清上面这行再说。" >&2
  exit 1
fi

echo "== 重启 $UNIT"
systemctl reset-failed "$UNIT" 2>/dev/null || true
systemctl restart "$UNIT"
for i in $(seq 1 30); do
  [ "$(systemctl is-active "$UNIT" 2>/dev/null)" = active ] && break
  sleep 1
done
systemctl show "$UNIT" -p ActiveState -p SubState -p NRestarts -p MainPID 2>&1 | sed 's/^/  /'

echo "== 收尾核对（以 guzhujushi 身份跑 trm status）"
runuser -u guzhujushi -- "$TRM" status 2>&1 | sed 's/^/  /'
echo
echo "如果上面有 daemon running / source 行，说明已经恢复。"