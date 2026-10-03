#!/usr/bin/env bash
# 把 trimum_client.py 的 socket 候选补丁同步进部署树（需 sudo）
#
# 为什么需要：S1 把 daemon 的 IPC socket 落到 /run/trimum/trimum.sock，
# 而客户端的候选表里原先没有这条路（XDG → /run/user/<uid> → 数据目录），
# 于是 daemon 绑了 A、客户端去连 B，继续静默降级成 HTTP。
#
# 用法（先在本机 scp 源文件上来）：
#   scp src/trimum_core/trimum_client.py guzhujushi@<host>:/tmp/trimum_client.py
#   sudo bash /tmp/sync_opt_client_patch.sh
#   sudo bash /tmp/sync_opt_client_patch.sh --rollback    # 还原最近一次备份
set -euo pipefail

SRC=/tmp/trimum_client.py
DST=/opt/trimum/src/trimum_core/trimum_client.py
BACKUP_ROOT=/var/backups/trimum
TRM=/opt/trimum/venv/bin/trm
SERVICE_USER=guzhujushi

if [ "${1:-}" = "--rollback" ]; then
  BK=$(ls -1d "${BACKUP_ROOT}"/client-patch-* 2>/dev/null | sort | tail -1)
  [ -n "$BK" ] || { echo "没有找到备份" >&2; exit 1; }
  install -m 0644 "$BK/trimum_client.py" "$DST"
  echo "已从 $BK 还原"
  exit 0
fi

[ "$(id -u)" -eq 0 ] || { echo "需要 root：sudo bash $0" >&2; exit 1; }
[ -f "$SRC" ] || { echo "缺少 $SRC —— 先 scp 源文件上来" >&2; exit 1; }
[ -f "$DST" ] || { echo "找不到 $DST —— 部署树结构变了？" >&2; exit 1; }

echo "== 部署前自检（语法 + 改动点）"
python3 - "$SRC" <<'PY'
import ast, sys
path = sys.argv[1]
src = open(path, encoding="utf-8").read()
ast.parse(src)                                  # 语法不过就别装
assert "SYSTEM_RUNTIME_SOCKET" in src, "看起来不是打了 socket 补丁的版本"
print("  语法 OK；含 SYSTEM_RUNTIME_SOCKET 定义")
PY

BK="${BACKUP_ROOT}/client-patch-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
cp -a "$DST" "$BK/trimum_client.py"
echo "== 备份到 $BK"

install -m 0644 "$SRC" "$DST"
echo "== 已部署到 $DST"

echo
echo "== 部署后自检"
/opt/trimum/venv/bin/python -c "from trimum_core.trimum_client import SYSTEM_RUNTIME_SOCKET, socket_candidates; print('  SYSTEM_RUNTIME_SOCKET =', SYSTEM_RUNTIME_SOCKET); print('  候选顺序 =', [str(p) for p in socket_candidates()])"
echo
echo "== 客户端实际走哪条通道（daemon 必须先跑起来）"
if [ -S /run/trimum/trimum.sock ]; then
  runuser -u "$SERVICE_USER" -- "$TRM" status 2>&1 | grep -E 'source:|endpoint:' | sed 's/^/  /'
else
  echo "  /run/trimum/trimum.sock 还不存在 —— 先跑 sudo bash /tmp/harden_trmd_unit.sh --apply"
fi
echo
echo "回滚： sudo bash $0 --rollback"
