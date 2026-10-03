#!/usr/bin/env bash
# 把「daemon 单实例加固」补丁装进部署树 /opt/trimum（真机、需要 root）
#
#   sudo bash /tmp/sync_opt_singleton_fix.sh --check   # 只报告现状，不写任何文件
#   sudo bash /tmp/sync_opt_singleton_fix.sh           # 装补丁（9 个文件：5 src + 4 tests）
#
# 为什么需要 sudo：/opt/trimum/src/trimum_core 与 /opt/trimum/tests 是 root 属主。
# 为什么脚本不重启 daemon：daemon 必须以 guzhujushi 运行（root 跑会把 ~/.trimum 写脏）。
# 装完请自己执行（不要加 sudo）：
#   bash /home/guzhujushi/trimum/scripts/restart_trmd.sh
# 预期：trm status 的 version 从 0.2.1 变成 0.5.0，source 仍是 rpc。
set -euo pipefail

TARBALL="${TRIMUM_PATCH_TARBALL:-/tmp/m3-singleton-fix.tar}"
APP_DIR="${TRIMUM_APP_DIR:-/opt/trimum}"
EXPECT_SHA="${TRIMUM_PATCH_SHA:-699962399d2a6783b64bf56dd5b849d5bc46bba39d3aadfbdaae33d7aaffea9e}"
MODE="${1:-install}"

if [[ ${EUID} -ne 0 && ${TRIMUM_ALLOW_NONROOT:-0} != 1 ]]; then
    echo "请用 sudo 运行：sudo bash $0 [--check]" >&2
    exit 1
fi
[[ -f "$TARBALL" ]] || { echo "补丁包不存在：$TARBALL" >&2; exit 1; }

ACTUAL_SHA=$(sha256sum "$TARBALL" | cut -d' ' -f1)
if [[ "$ACTUAL_SHA" != "$EXPECT_SHA" ]]; then
    echo "补丁包 sha256 不符，拒绝执行" >&2
    echo "  期望 $EXPECT_SHA" >&2
    echo "  实际 $ACTUAL_SHA" >&2
    exit 1
fi
echo "补丁包 sha256 校验通过：$ACTUAL_SHA"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
tar -xf "$TARBALL" -C "$STAGE"

echo
echo "== 补丁内容 vs 已装版本 =="
changed=0
while read -r rel; do
    src="$STAGE/$rel"; dst="$APP_DIR/$rel"
    if [[ ! -f "$dst" ]]; then
        echo "  [新增] $rel"; changed=$((changed + 1))
    elif cmp -s "$src" "$dst"; then
        echo "  [相同] $rel"
    else
        echo "  [替换] $rel"; changed=$((changed + 1))
    fi
done < <(cd "$STAGE" && find . -name '*.py' -printf '%P\n' | sort)
echo "  需要写入的文件数：$changed"

if [[ "$MODE" == "--check" ]]; then
    echo
    echo "(--check 模式，未写入任何文件)"
    exit 0
fi

echo
echo "== 写入 $APP_DIR =="
tar -xf "$TARBALL" -C "$APP_DIR"
ls -l "$APP_DIR/src/trimum_core/main.py" "$APP_DIR/src/trimum_core/ipc_handler.py" "$APP_DIR/tests/test_daemon_singleton.py"

echo
echo "== 装后自检（部署树 venv 直接 import）=="
"$APP_DIR/venv/bin/python" - <<'PYEOF'
from trimum_core import __version__
from trimum_core.config import DEFAULT_SOCKET_PATH, default_socket_path
from trimum_core.api_server import _core_version
from trimum_core.ipc_handler import socket_is_live
import trimum_core.main as m
print("  socket_path      =", DEFAULT_SOCKET_PATH)
print("  uid=1001 预览    =", default_socket_path(runtime_dir="", uid=1001))
print("  version          =", __version__, "/", _core_version())
print("  socket_is_live   =", socket_is_live("/run/user/1000/trimum.sock"), "(真 daemon 在跑 → 期望 True)")
print("  check_tcp_port   =", m.check_tcp_port("127.0.0.1", 8321), "(占用 → 期望非 None)")
PYEOF

echo
echo "== 下一步（以 guzhujushi 身份，不要 sudo）=="
echo "  bash /home/guzhujushi/trimum/scripts/restart_trmd.sh"
echo "  trm status | head -4    # 期望 source: rpc / version: 0.5.0"