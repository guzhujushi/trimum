#!/usr/bin/env bash
# 把「socket 收口」补丁同步进部署树 /opt/trimum/src（需 sudo）
#
# 为什么不是只补 trimum_client.py：这次动的是**两端共用的路径契约**，散在 5 个文件里
# （config / trimum_client / ipc_handler / api_server / cli/_utils）。只补一半，就还是
# 「daemon 绑 A、客户端连 B、静默降级成 HTTP」那个老毛病。
#
# 用法（先在本机 scp 源文件上来）：
#   ssh <host> 'mkdir -p /tmp/trimum-socket-patch/trimum_core/cli'
#   scp src/trimum_core/{config.py,trimum_client.py,ipc_handler.py,api_server.py} \
#       guzhujushi@<host>:/tmp/trimum-socket-patch/trimum_core/
#   scp src/trimum_core/cli/_utils.py guzhujushi@<host>:/tmp/trimum-socket-patch/trimum_core/cli/
#   sudo bash /tmp/sync_opt_socket_patch.sh                  # 同步到 /opt/trimum/src
#   sudo bash /tmp/sync_opt_socket_patch.sh --also-home-src  # 顺带修开发树 /home/guzhujushi/trimum/src
#   sudo bash /tmp/sync_opt_socket_patch.sh --dry-run        # 只报告
#   sudo bash /tmp/sync_opt_socket_patch.sh --rollback       # 还原最近一次
set -uo pipefail

SRC_DIR="${TRIMUM_SOCKET_PATCH_SRC:-/tmp/trimum-socket-patch}"
APP_SRC=/opt/trimum/src
HOME_SRC=/home/guzhujushi/trimum/src
BACKUP_ROOT=/var/backups/trimum
VENV_PY=/opt/trimum/venv/bin/python

FILES=(
  trimum_core/config.py
  trimum_core/trimum_client.py
  trimum_core/ipc_handler.py
  trimum_core/api_server.py
  trimum_core/cli/_utils.py
)

MODE=apply
DRY=0
ALSO_HOME=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --also-home-src) ALSO_HOME=1 ;;
    --rollback) MODE=rollback ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "未知参数：$a" >&2; exit 2 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "需要 root：sudo bash $0" >&2; exit 1; }

# ── 回滚 ────────────────────────────────────────────────────────
if [ "$MODE" = rollback ]; then
  BK="$(ls -1d "${BACKUP_ROOT}"/socket-patch-* 2>/dev/null | sort | tail -1)"
  [ -n "$BK" ] || { echo "没找到备份（${BACKUP_ROOT}/socket-patch-*）" >&2; exit 1; }
  echo "从 $BK 还原"
  ( cd "$BK/src" && find . -type f -print0 | while IFS= read -r -d '' f; do
      install -D -o root -g root -m 0644 "$f" "$APP_SRC/${f#./}"; echo "  $APP_SRC/${f#./}"; done )
  if [ "$ALSO_HOME" -eq 1 ]; then
    ( cd "$BK/src" && find . -type f -print0 | while IFS= read -r -d '' f; do
        install -D -o root -g root -m 0644 "$f" "$HOME_SRC/${f#./}"; echo "  $HOME_SRC/${f#./}"; done )
  fi
  echo "还原完成。daemon 需自己重启（旧代码还在内存里）。"
  exit 0
fi

# ── 源自检 ──────────────────────────────────────────────────────
missing=0
for rel in "${FILES[@]}"; do
  [ -f "$SRC_DIR/$rel" ] || { echo "缺少源文件：$SRC_DIR/$rel" >&2; missing=1; }
done
[ "$missing" -eq 0 ] || { echo "先把补丁文件 scp 上来（用法见脚本头部）。" >&2; exit 1; }

echo "== 语法与改动点自检（$SRC_DIR）"
python3 - "$SRC_DIR" <<'PY'
import ast, os, sys
root = sys.argv[1]
need = {
    "trimum_core/config.py": ["SOCKET_ENV", "def socket_candidates", "def discover_socket"],
    "trimum_core/trimum_client.py": ["_is_live", "SOCKET_ENV"],
    "trimum_core/ipc_handler.py": ["socket_start_error", "makedirs"],
    "trimum_core/api_server.py": ["await ipc.start()"],
    "trimum_core/cli/_utils.py": ["discover_socket"],
}
bad = 0
for rel, tokens in need.items():
    path = os.path.join(root, rel)
    # 必须用 utf-8-sig 解码：仓库里 api_server.py / secrets_redactor.py 带 UTF-8 BOM
    # （既有状态，Python 自己编译没问题，但 ast.parse 会把 U+FEFF 当非法字符）。
    # 用 encoding="utf-8" 读会把 BOM 留在字符串里 —— 自检会假报语法错，把人挡在门外。
    raw = open(path, "rb").read()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    src = raw.decode("utf-8-sig")
    ast.parse(src)
    for token in tokens:
        if token not in src:
            print("  缺改动点：%s ← %r" % (rel, token))
            bad = 1
    print("  OK   %s%s" % (rel, "（带 UTF-8 BOM，既有状态）" if has_bom else ""))
sys.exit(bad)
PY
if [ "$?" -ne 0 ]; then echo "自检不过，不装。" >&2; exit 1; fi

# ── 备份 + 安装 ─────────────────────────────────────────────────
TS=$(date +%Y%m%d-%H%M%S)
BK="${BACKUP_ROOT}/socket-patch-${TS}"
mkdir -p "$BK/src"
echo "== 安装（备份 $BK）"
for rel in "${FILES[@]}"; do
  if [ -f "$APP_SRC/$rel" ]; then
    install -D -o root -g root -m 0644 "$APP_SRC/$rel" "$BK/src/$rel"
  else
    echo "  [警告] 部署树里没有 $APP_SRC/$rel —— 当新文件装（备份里不会有它，回滚也删不掉）"
  fi
  [ "$DRY" -eq 0 ] && install -D -o root -g root -m 0644 "$SRC_DIR/$rel" "$APP_SRC/$rel"
  echo "  $rel -> $APP_SRC/$rel"
done
if [ "$ALSO_HOME" -eq 1 ]; then
  echo "== 顺带修开发树 $HOME_SRC"
  for rel in "${FILES[@]}"; do
    [ "$DRY" -eq 0 ] && install -D -o root -g root -m 0644 "$SRC_DIR/$rel" "$HOME_SRC/$rel"
    echo "  $rel -> $HOME_SRC/$rel"
  done
fi
cp -a "$SRC_DIR" "$BK/source" 2>/dev/null || true

# ── 部署后自检 ──────────────────────────────────────────────────
if [ "$DRY" -eq 0 ] && [ -x "$VENV_PY" ]; then
  echo "== 部署后自检（$VENV_PY）"
  "$VENV_PY" - <<'PY'
from trimum_core.config import SOCKET_ENV, SYSTEM_RUNTIME_SOCKET, discover_socket, socket_candidates
from trimum_core.trimum_client import socket_candidates as client_candidates

daemon_list = [str(p) for p in socket_candidates()]
client_list = [str(p) for p in client_candidates()]
print("  SOCKET_ENV          =", SOCKET_ENV)
print("  SYSTEM_RUNTIME_SOCK =", SYSTEM_RUNTIME_SOCKET)
print("  daemon 候选         =", daemon_list)
print("  client 候选         =", client_list)
print("  两端逐条一致        =", daemon_list == client_list)
print("  discover_socket()   =", discover_socket())
PY
fi

echo
echo "== 下一步"
echo "  daemon 还在跑旧代码（重启前这些改动不生效）："
echo "    sudo bash /tmp/harden_trmd_unit.sh --apply   # 加固 + 重启 + 冒烟（推荐，一步到位）"
echo "    bash /home/guzhujushi/trimum/scripts/restart_trmd.sh   # 或只重启"
echo "  回滚： sudo bash $0 --rollback"