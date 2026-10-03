#!/usr/bin/env bash
# 把 M4（HTTP/SSE 传输 + 空闲回收 + cgroup 绑定 + mcp status/restart）装进部署树 /opt/trimum
#
#   sudo bash /tmp/sync_opt_m4.sh --check   # 只报告现状，不写任何文件
#   sudo bash /tmp/sync_opt_m4.sh           # 装补丁（12 个文件：6 src + 6 tests）
#
# 为什么需要 sudo：/opt/trimum/src/trimum_core 与 /opt/trimum/tests 是 root 属主。
# 为什么脚本不重启 daemon：daemon 必须以 guzhujushi 运行（root 跑会把 ~/.trimum 写脏）。
# 装完请自己执行（不要加 sudo）：
#   bash /home/guzhujushi/trimum/scripts/restart_trmd.sh
# 然后验收：
#   .venv/bin/python /home/guzhujushi/trimum/scripts/accept_m4.py   # 隔离 daemon，16 项断言
#   trm mcp status                                                  # source 应为 daemon
set -euo pipefail

TARBALL="${TRIMUM_PATCH_TARBALL:-/tmp/m4-opt.tar}"
APP_DIR="${TRIMUM_APP_DIR:-/opt/trimum}"
EXPECT_SHA="${TRIMUM_PATCH_SHA:-a146fb41605f5eda23ebc52e9273738389bf803347994a50adbc8b55ca070152}"
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
echo "== 写入 $APP_DIR（属主保持 root，daemon 以 guzhujushi 只读运行）=="
install -d "$APP_DIR/tests/fixtures"
while read -r rel; do
    install -m 644 "$STAGE/$rel" "$APP_DIR/$rel"
done < <(cd "$STAGE" && find . -name '*.py' -printf '%P\n' | sort)
ls -l "$APP_DIR/src/trimum_core/mcp_registry.py" "$APP_DIR/tests/test_mcp_daemon.py"

echo
echo "== 装后自检（部署树 venv 直接 import）=="
"$APP_DIR/venv/bin/python" - <<'PYEOF'
import asyncio

from trimum_core import __version__
from trimum_core.api_server import AppState, _register_ipc_routes, build_mcp_pool  # noqa: F401
from trimum_core.cli.registry import check_commands
from trimum_core.mcp_client import HTTP_TRANSPORTS, parse_sse_messages
from trimum_core.mcp_registry import MCPServerPool
from trimum_core.models import ToolType
from trimum_core.tool_dispatchers import DispatcherRegistry

pool = MCPServerPool()
print("  version            =", __version__)
print("  HTTP_TRANSPORTS    =", sorted(HTTP_TRANSPORTS))
print("  SSE 解析           =", parse_sse_messages("data: {\"jsonrpc\":\"2.0\",\"id\":1}"))
print("  pool.reap/start    =", callable(pool.reap), asyncio.iscoroutinefunction(pool.reap))
print("  idle/restart       =", callable(pool.restart), callable(pool.reap))
registry = DispatcherRegistry()
disp = registry.get(ToolType.MCP_TOOLS_CALL)
print("  set_pool           =", callable(getattr(disp, "set_pool", None)))
print("  list is call       =", registry.get(ToolType.MCP_TOOLS_LIST) is disp)
print("  CLI 元数据契约     =", check_commands() or "OK")
PYEOF

"$APP_DIR/venv/bin/python" - <<'PYEOF'
from trimum_core.cli.registry import collect_commands
keys = {info.key for info in collect_commands()}
print("  mcp 子命令         =", sorted(k for k in keys if k.startswith("mcp")))
PYEOF

echo
echo "== 下一步（以 guzhujushi 身份，不要 sudo）=="
echo "  bash /home/guzhujushi/trimum/scripts/restart_trmd.sh   # 生产 daemon 换上新代码"
echo "  trm mcp status                                         # 期望 source: daemon"
echo "  trm mcp status --help                                  # 期望列出 status/restart"
