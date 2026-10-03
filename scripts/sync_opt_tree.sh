#!/usr/bin/env bash
# 把源码同步到部署树 /opt/trimum（真机、需要 root）
#
#   sudo bash /tmp/sync_opt_tree.sh              # 同步 src/ config/ tests/ scripts/ + 顶层文件
#   sudo bash /tmp/sync_opt_tree.sh --fix-home   # 额外修 /home/guzhujushi/trimum/src 的 root 属主，并用源补齐缺文件
#   sudo bash /tmp/sync_opt_tree.sh --dry-run    # 只报告将要做什么
#   sudo bash /tmp/sync_opt_tree.sh --from-home  # 强制用开发树当源（默认优先用 /tmp/trimum-sync.tar）
#   sudo bash /tmp/sync_opt_tree.sh --restart    # 同步完成后重启 trmd 并冒烟（默认只同步、不动 daemon）
#   bash /tmp/sync_opt_tree.sh --rehearse-only   # 只做导入预演（不装、不改；非 root 也能跑）
#   sudo bash /tmp/sync_opt_tree.sh --rollback   # 还原最近一次 src 备份（装坏了用这个）
#   sudo bash /tmp/sync_opt_tree.sh --no-rehearse # 跳过导入预演（不推荐）
#
# 为什么需要 sudo：/opt/trimum/{config,tests,scripts} 与 src/trimum_core 是 root 属主；
# /home/guzhujushi/trimum/src 也是 root:root（用 --fix-home 修）。
# 为什么默认不重启 daemon：daemon 必须以 guzhujushi 运行（root 跑会把 ~/.trimum 写脏），
# 同步完成后请自己执行：bash /home/guzhujushi/trimum/scripts/restart_trmd.sh
# 要脚本自己重启就加 --restart（systemctl restart 仍按 unit 里的 User=guzhujushi 跑）。
#
# 两条护栏（docs/SANDBOX-PLAN.md §9.3.6 的教训）：
#   ① 装之前先备份现有 /opt/trimum/src 到 /var/backups/trimum/src-<时间戳>（--rollback 还原）；
#   ② 装之前跑导入预演：把候选树每个模块 import 一遍，与「当前部署树」的失败集合对比，
#      出现**新增**失败就一个字都不碰生产（exit 3）。
set -euo pipefail

# 失败现场要能定位：这个脚本我（agent）跑不了 sudo，只能由你跑 ——
# 那就必须在中断时报出「哪一步、哪一行、什么码」，不靠猜。
STEP="初始化"
trap 'rc=$?; echo "[中断] 退出码=$rc｜最后一步：$STEP｜行号：$LINENO" >&2' ERR

SOURCE_DIR="${TRIMUM_SOURCE:-/home/guzhujushi/trimum}"
APP_DIR="${TRIMUM_APP_DIR:-/opt/trimum}"
HOME_SRC="${TRIMUM_HOME_SRC:-/home/guzhujushi/trimum/src}"
TARBALL="${TRIMUM_TARBALL:-/tmp/trimum-sync.tar}"
STAGE="${TRIMUM_STAGE:-/tmp/trimum-sync-stage}"
OWNER_USER="${TRIMUM_OWNER_USER:-root}"
OWNER_GROUP="${TRIMUM_OWNER_GROUP:-root}"
FIX_HOME=0
DRY_RUN=0
FROM_HOME=0
REHEARSE=1
REHEARSE_ONLY=0
ROLLBACK=0
RESTART=0
BACKUP_ROOT="${TRIMUM_BACKUP_ROOT:-/var/backups/trimum}"
UNIT="${TRIMUM_UNIT:-trmd}"
SOCKET_PATH="${TRIMUM_SOCKET:-/run/trimum/trimum.sock}"

BACKUP_DIR=""
WALK_DIR="${TRIMUM_WALK_DIR:-}"

for arg in "$@"; do
    case "$arg" in
        --fix-home) FIX_HOME=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --from-home) FROM_HOME=1 ;;
        --no-rehearse) REHEARSE=0 ;;
        --rehearse-only) REHEARSE_ONLY=1 ;;
        --rollback) ROLLBACK=1 ;;
        --restart) RESTART=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

if [[ ${EUID} -ne 0 && ${TRIMUM_ALLOW_NONROOT:-0} != 1 && $REHEARSE_ONLY -ne 1 ]]; then
    echo "请用 sudo 运行：sudo bash $0（只有 --rehearse-only 可以非 root 跑）" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 0. 公共：daemon 用户 / socket 探活 / 导入预演
# ---------------------------------------------------------------------------
unit_user() { systemctl show "$UNIT" -p User --value 2>/dev/null; }

# 没有备份时 ls 会非零退出，而它是在命令替换里被调用的 —— set -e 下会把脚本带走
latest_src_backup() { { ls -1d "${BACKUP_ROOT}"/src-* 2>/dev/null || true; } | sort | tail -1; }

# 预演输出里的失败模块名（没有失败就输出空文件；别让 grep 的返回值把脚本带崩）
bad_names() { { grep '^  BAD ' "$1" || true; } | sed 's/^  BAD //' | cut -f1 | sort -u; }

# 预演产物一律放进**本次运行新建**的目录：/tmp 是 sticky 位目录，内核的
# fs.protected_regular=2 规定「属主不是自己的普通文件，连 root 也不能 O_CREAT 打开」——
# 所以只要有一次是普通用户写的 /tmp/.trm-walk-*.out，后面 sudo 跑就必然 EACCES
# （真机两次失败的真因，见 docs/SANDBOX-PLAN.md §9.3.9）。
ensure_walk_dir() {
    [ -n "$WALK_DIR" ] && return 0
    WALK_DIR="$(mktemp -d /tmp/.trm-walk.XXXXXX)"
    chmod 0755 "$WALK_DIR"
    echo "  预演输出目录：$WALK_DIR"
}

socket_live() {
    python3 - "$SOCKET_PATH" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(0.5)
sys.exit(0 if s.connect_ex(sys.argv[1]) == 0 else 1)
PY
}

# 预演：把整棵树的模块逐个 import，失败的逐行打印。结果一律写在 $2 里，返回 0。
#
# 代码**通过 stdin 喂给 python**，不在 /tmp 落地成脚本文件：真机第一次跑就撞上
# 「/tmp/.trm-walk.py 权限不够」—— root 写、daemon 用户读这条跨用户路径本来就不该存在。
# 输出的第一行必须是 ROOT <加载到的 trimum_core 路径>：venv 的 editable .pth 指向
# /opt/trimum/src，只用 PYTHONPATH 覆盖时，调用方要靠这一行证明「预演真的生效了」。
run_import_walk() {
    local root="$1" out="$2" user runner=() xdg
    user="$(unit_user)"; [[ -n "$user" ]] || user=root
    if [[ ${EUID} -eq 0 ]]; then
        runner=(runuser -u "$user" --)
    fi
    xdg="$(mktemp -d /tmp/.trm-walk-xdg.XXXXXX)"
    mkdir -p "$xdg/config" "$xdg/data" "$xdg/run" "$xdg/home"
    chmod -R 0777 "$xdg"
    # 预演命令失败时**不能让 set -e 直接把脚本带走** —— 那样连一句解释都不会留下
    # （真机第一次跑就是这个下场：一屏「权限不够」+ 没有 traceback + 退出码 1/127，
    #  而且 bash 在「命令找不到」时连 ERR trap 都不打）。这里显式关掉 errexit，
    # 退出码交给下面的调用方判断与打印。
    set +e
    "${runner[@]}" env \
        PYTHONPATH="$root" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
        XDG_CONFIG_HOME="$xdg/config" XDG_DATA_HOME="$xdg/data" \
        XDG_RUNTIME_DIR="$xdg/run" TRIMUM_HOME="$xdg/home" \
        TRIMUM_SOCKET="$xdg/run/probe.sock" \
        "$APP_DIR/venv/bin/python" -B - "$root" > "$out" 2>&1 <<'PYEOF'
import importlib
import pkgutil
import sys

import trimum_core

expect = sys.argv[1] if len(sys.argv) > 1 else ""
root = trimum_core.__file__
print("ROOT %s" % root)
if expect and not root.startswith(expect):
    print("  BAD __root__\t预演没生效：trimum_core 来自 %s，不是 %s" % (root, expect))

names = {"trimum_core.main"}
for mod in pkgutil.walk_packages(trimum_core.__path__, "trimum_core."):
    names.add(mod.name)

bad = []
for name in sorted(names):
    try:
        importlib.import_module(name)
    except BaseException as exc:  # 预演就是要抓所有东西，包括 SystemExit
        bad.append("%s\t%s: %s" % (name, type(exc).__name__, str(exc).replace("\n", " ")[:180]))
print("FAILED %d" % len(bad))
for line in bad:
    print("  BAD %s" % line)
PYEOF
    WALK_RC=$?
    set -e
    if [ "$WALK_RC" -ne 0 ]; then
        echo "  [WARN] 预演命令退出码=$WALK_RC（树：$root），原始输出："
        sed 's/^/    /' "$out"
    fi
    rm -rf "$xdg"
    return 0
}

# ---------------------------------------------------------------------------
# 0b. --rollback：还原最近一次 src 备份（不需要同步源）
# ---------------------------------------------------------------------------
if [[ $ROLLBACK -eq 1 ]]; then
    [[ ${EUID} -eq 0 ]] || { echo "请用 sudo 运行：sudo bash $0 --rollback" >&2; exit 1; }
    b="$(latest_src_backup)"
    [[ -n "$b" ]] || { echo "没找到备份：${BACKUP_ROOT}/src-*" >&2; exit 1; }
    [[ -f "$b/trimum_core/__init__.py" ]] || { echo "备份不完整（缺 trimum_core/__init__.py）：$b" >&2; exit 1; }
    echo "== 回滚 src：$b -> $APP_DIR/src =="
    if [[ -d "$APP_DIR/src" ]]; then
        mv "$APP_DIR/src" "$APP_DIR/.src-broken-$(date +%Y%m%d-%H%M%S)"
        echo "  原树改名保留（没删）：$(ls -1d "$APP_DIR"/.src-broken-* | tail -1)"
    fi
    cp -a "$b" "$APP_DIR/src"
    chown -R root:root "$APP_DIR/src"
    ensure_walk_dir
    run_import_walk "$APP_DIR/src" "$WALK_DIR/rollback.out"
    chmod -R a+rX "$WALK_DIR" 2>/dev/null || true
    sed -n '1p;/^FAILED/p' "$WALK_DIR/rollback.out" | sed 's/^/  /'
    systemctl restart "$UNIT"
    for i in $(seq 1 60); do if socket_live; then break; fi; sleep 0.5; done
    if socket_live; then echo "  [PASS] socket 已就绪：$SOCKET_PATH"
    else echo "  [FAIL] socket 还没起来，看 journalctl -u $UNIT" >&2; fi
    u="$(unit_user)"; [[ -n "$u" ]] || u=guzhujushi
    runuser -u "$u" -- "$APP_DIR/venv/bin/trm" status 2>&1 | head -8 | sed 's/^/  /'
    exit 0
fi

# ---------------------------------------------------------------------------
# 1. 选源：tar 包优先（开发树可能缺文件，例如 root 属主导致 src/agent-sdk 建不出来）
# ---------------------------------------------------------------------------
STEP="[1/5] 同步源"
echo "== [1/5] 同步源 =="
if [[ $FROM_HOME -eq 1 || ! -f "$TARBALL" ]]; then
    SRC="$SOURCE_DIR"
    STAGE=""
    [[ -f "$SRC/pyproject.toml" ]] || { echo "同步源不可用：$SRC/pyproject.toml 不存在" >&2; exit 1; }
    echo "  源：开发树 $SRC"
else
    # 真机 /tmp 上会有「另一次 root 运行」留下的 root 属主同名目录：删不掉就换一个，
    # 别让一个 /tmp 残留把整条同步链卡死（第一版就是这么死的：一屏 rm 权限不够）。
    OLD_STAGE="$STAGE"
    if ! rm -rf "$STAGE" 2>/dev/null; then
        STAGE="$(mktemp -d /tmp/.trm-sync-stage.XXXXXX)"
        echo "  注意：$OLD_STAGE 删不掉（多半是 root 属主的残留），改用 $STAGE"
    fi
    mkdir -p "$STAGE"
    # 远端不一定有 tar（真机就没有）：用 python3 -m tarfile 兜底，别再装包。
    if command -v tar >/dev/null 2>&1; then
        tar -xf "$TARBALL" -C "$STAGE"
    else
        python3 -m tarfile -e "$TARBALL" "$STAGE"
    fi
    # 解出来的树要能被 daemon 用户读到、能遍历：root 的 umask 一旦收紧（077），
    # 预演里以 guzhujushi 身份跑的 python 连目录都进不去。
    chmod -R a+rX "$STAGE"
    SRC="$STAGE"
    echo "  源：tar 包 $TARBALL（$(du -sh "$STAGE" | cut -f1)）"
fi
echo "  目标：$APP_DIR（属主 $OWNER_USER:$OWNER_GROUP）"

# ---------------------------------------------------------------------------
# 1b. 导入预演（先做，改不动任何东西；失败就 exit 3，一个字都不碰生产）
# ---------------------------------------------------------------------------
if [[ $REHEARSE -eq 1 ]]; then
    STEP="[1b/5] 导入预演"
    echo "== [1b/5] 导入预演（基线=当前部署树，候选=$SRC/src）=="
    ensure_walk_dir
    if [[ -d "$APP_DIR/src" ]]; then
        run_import_walk "$APP_DIR/src" "$WALK_DIR/base.out"
        echo "  基线：$(grep -m1 '^FAILED' "$WALK_DIR/base.out" || echo 'FAILED ?')（$WALK_DIR/base.out）"
    else
        echo "  基线：$APP_DIR/src 不存在，跳过对比"
        : > "$WALK_DIR/base.out"
    fi
    run_import_walk "$SRC/src" "$WALK_DIR/cand.out"
    chmod -R a+rX "$WALK_DIR" 2>/dev/null || true
    { grep -m1 '^FAILED' "$WALK_DIR/cand.out" || echo 'FAILED ?'; } | sed 's/^/  候选：/'
    # 没有 BAD 行时 grep 返回 1，set -o pipefail 会把整行判失败 —— 所以统一走 bad_names()
    bad_names "$WALK_DIR/base.out" > "$WALK_DIR/base.names"
    bad_names "$WALK_DIR/cand.out" > "$WALK_DIR/cand.names"
    NEW_BAD="$(comm -13 "$WALK_DIR/base.names" "$WALK_DIR/cand.names")"
    if [[ -n "$NEW_BAD" ]]; then
        echo "  预演不通过 —— 这些模块在候选树里 import 失败，而当前部署树里是好的：" >&2
        grep '^  BAD ' "$WALK_DIR/cand.out" | sed 's/^/    /' >&2
        echo "  一个字都没碰生产。完整输出：$WALK_DIR/cand.out" >&2
        exit 3
    fi
    # 反向护栏：预演自己失败（python 起不来 / 读不到那棵树）时一行 BAD 都不会有，
    # 上面那段就会「无新增失败」地放行 —— 所以必须要求候选输出里有预期的 ROOT 行。
    if ! grep -q "^ROOT $SRC/src/trimum_core/__init__\.py$" "$WALK_DIR/cand.out"; then
        echo "  预演没有产出预期结果（看不到 ROOT $SRC/src/trimum_core/__init__.py）" >&2
        echo "  —— 预演本身失败了，拒绝继续。原始输出：" >&2
        sed 's/^/    /' "$WALK_DIR/cand.out" >&2
        exit 3
    fi
    if grep -q '^  BAD __root__' "$WALK_DIR/cand.out"; then
        echo "  预演没生效（trimum_core 没从候选树加载），拒绝继续" >&2
        exit 3
    fi
    echo "  [PASS] 候选树相对当前部署树没有新增 import 失败"
fi

if [[ $REHEARSE_ONLY -eq 1 ]]; then
    echo
    echo "--rehearse-only：到此为止，没装任何东西。"
    exit 0
fi

# ---------------------------------------------------------------------------
# 1c. 备份现有部署树（装坏了用 --rollback 整体还原）
# ---------------------------------------------------------------------------
STEP="[1c/5] 备份现有部署树"
BACKUP_DIR="${BACKUP_ROOT}/src-$(date +%Y%m%d-%H%M%S)"
if [[ $DRY_RUN -eq 0 ]]; then
    install -d -o root -g root -m 0755 "$BACKUP_ROOT"
    if [[ -d "$APP_DIR/src" ]]; then
        cp -a "$APP_DIR/src" "$BACKUP_DIR"
        echo "== [1c/5] 已备份 $APP_DIR/src -> $BACKUP_DIR（$(du -sh "$BACKUP_DIR" | cut -f1)）"
    else
        echo "== [1c/5] $APP_DIR/src 不存在，跳过备份"
    fi
else
    echo "== [1c/5] [dry-run] 将备份 $APP_DIR/src -> $BACKUP_DIR"
fi

# ---------------------------------------------------------------------------
# 2. 代码与配置
# ---------------------------------------------------------------------------
STEP="[2/5] 代码与配置"
echo "== [2/5] src/ config/ tests/ scripts/ =="
if [[ $DRY_RUN -eq 0 ]]; then
    install -d -o "$OWNER_USER" -g "$OWNER_GROUP" -m 0755 \
        "$APP_DIR/src" "$APP_DIR/config" "$APP_DIR/tests" "$APP_DIR/scripts"
fi

sync_tree() {
    local rel="$1" mode="$2" count=0 file dest
    if [[ ! -d "$SRC/$rel" ]]; then
        echo "  $rel: 源目录缺失，跳过"
        return 0
    fi
    while IFS= read -r -d '' file; do
        dest="$APP_DIR/$rel/${file#"$SRC/$rel/"}"
        [[ $DRY_RUN -eq 0 ]] && install -D -o "$OWNER_USER" -g "$OWNER_GROUP" -m "$mode" "$file" "$dest"
        count=$((count + 1))
    done < <(find "$SRC/$rel" -type f \
        -not -path '*__pycache__*' -not -name '*.pyc' -print0)
    echo "  $rel: $count 个文件 (mode $mode)"
}

sync_tree src 0644
sync_tree config 0644
sync_tree tests 0644
sync_tree scripts 0755

# ---------------------------------------------------------------------------
# 3. 顶层文件（沿用目标目录既有属主）
# ---------------------------------------------------------------------------
STEP="[3/5] 顶层文件"
echo "== [3/5] 顶层文件 =="
DOC_OWNER="$(stat -c '%U:%G' "$APP_DIR")"
for doc in AGENTS.md STATUS.md TODO.md pyproject.toml; do
    if [[ -f "$SRC/$doc" ]]; then
        [[ $DRY_RUN -eq 0 ]] && install -o "${DOC_OWNER%%:*}" -g "${DOC_OWNER##*:}" -m 0644 \
            "$SRC/$doc" "$APP_DIR/$doc"
        echo "  $doc -> $APP_DIR/$doc ($DOC_OWNER)"
    fi
done
if [[ -f "$SRC/docs/ARCH.md" ]]; then
    [[ $DRY_RUN -eq 0 ]] && install -o "${DOC_OWNER%%:*}" -g "${DOC_OWNER##*:}" -m 0644 \
        "$SRC/docs/ARCH.md" "$APP_DIR/ARCH.md"
    echo "  docs/ARCH.md -> $APP_DIR/ARCH.md ($DOC_OWNER)"
fi
if [[ -f "$SRC/docs/OPERATIONS.md" ]]; then
    [[ $DRY_RUN -eq 0 ]] && install -o "${DOC_OWNER%%:*}" -g "${DOC_OWNER##*:}" -m 0644 \
        "$SRC/docs/OPERATIONS.md" "$APP_DIR/OPERATIONS.md"
    echo "  docs/OPERATIONS.md -> $APP_DIR/OPERATIONS.md ($DOC_OWNER)"
fi

# ---------------------------------------------------------------------------
# 4. 校验
# ---------------------------------------------------------------------------
STEP="[4/5] 校验"
echo "== [4/5] 校验 =="
status=0
for f in \
    src/trimum_core/mcp_bridge.py \
    src/trimum_core/mcp_catalog.py \
    src/trimum_core/mcp_client.py \
    src/trimum_core/mcp_registry.py \
    src/trimum_core/cli/commands/mcp.py \
    src/trimum_core/cli/commands/setup.py \
    src/trimum_core/setup_wizard.py \
    src/trimum_core/identity.py \
    src/agent-sdk/trimum_agent.py \
    config/mcp-catalog.yaml; do
    if [[ -f "$APP_DIR/$f" ]]; then
        echo "  OK   $f"
    else
        echo "  MISS $f"
        status=1
    fi
done
echo "  tests/*.py          : $(find "$APP_DIR/tests" -maxdepth 1 -name '*.py' | wc -l)"
echo "  src/trimum_core/*.py: $(find "$APP_DIR/src/trimum_core" -maxdepth 1 -name '*.py' | wc -l)"
echo "  属主分布："
find "$APP_DIR/src/trimum_core" -maxdepth 1 -printf '    %u:%g\n' 2>/dev/null | sort | uniq -c

# ---------------------------------------------------------------------------
# 4b. M4.5 自检：聚合模块真的能被部署树的 venv 导入
# ---------------------------------------------------------------------------
if [[ $DRY_RUN -eq 0 ]]; then
    STEP="[4b/5] M4.5 自检"
echo "== [4b/5] M4.5 自检（$APP_DIR/venv）=="
    "$APP_DIR/venv/bin/python" - <<'PYEOF'
from trimum_core.mcp_bridge import MCPToolIndex, flat_name, split_name
from trimum_core.tool_gateway import ToolRegistry

print("  flat / split       =", flat_name("echo", "echo"), split_name("a__b__c"))
registry = ToolRegistry()
print("  load_mcp_tools     =", callable(registry.load_mcp_tools), callable(registry.list_mcp_tools))
print("  聚合条目           =", len(registry.list_mcp_tools()), "条（读缓存，不启动 server）")
print("  index 路径         =", MCPToolIndex().path)
PYEOF
else
    echo "== [4b/5] 跳过 M4.5 自检（--dry-run）=="
fi

# ---------------------------------------------------------------------------
# 5. 可选：修开发树 src 属主，并把源里缺的文件补回去
# ---------------------------------------------------------------------------
STEP="[5/5] 开发树"
echo "== [5/5] 开发树 $HOME_SRC =="
if [[ $FIX_HOME -eq 1 ]]; then
    echo "  chown -R ${DOC_OWNER%%:*}:${DOC_OWNER##*:} $HOME_SRC"
    if [[ $DRY_RUN -eq 0 ]]; then
        chown -R "${DOC_OWNER%%:*}:${DOC_OWNER##*:}" "$HOME_SRC"
        if [[ -n "$STAGE" ]]; then
            tar -C "$STAGE" -cf - src | tar -C "$SOURCE_DIR" -xf -
            chown -R "${DOC_OWNER%%:*}:${DOC_OWNER##*:}" "$HOME_SRC"
        fi
        ls -ld "$HOME_SRC" "$HOME_SRC"/* 2>&1
    fi
else
    echo "  跳过（用 --fix-home 启用）。当前："
    ls -ld "$HOME_SRC" 2>&1 | sed 's/^/    /'
fi

echo
if [[ $DRY_RUN -eq 0 ]]; then
    echo "备份：$BACKUP_DIR"
    echo "回滚：sudo bash $0 --rollback"
fi
if [[ $RESTART -eq 1 && $DRY_RUN -eq 0 ]]; then
    echo
    STEP="重启 + 冒烟"
    echo "== 重启 $UNIT 并冒烟 =="
    systemctl restart "$UNIT"
    for i in $(seq 1 60); do if socket_live; then break; fi; sleep 0.5; done
    if socket_live; then
        echo "  [PASS] socket 已就绪：$SOCKET_PATH"
        u="$(unit_user)"; [[ -n "$u" ]] || u=guzhujushi
        runuser -u "$u" -- "$APP_DIR/venv/bin/trm" status 2>&1 | head -8 | sed 's/^/  /'
        if runuser -u "$u" -- "$APP_DIR/venv/bin/trm" status 2>&1 | grep -q "daemon running"; then
            echo "  [PASS] trm status 报告 daemon running"
        else
            echo "  [FAIL] trm status 没报告 daemon running" >&2
            status=1
        fi
    else
        echo "  [FAIL] $UNIT 重启后 socket 没就绪（journalctl -u $UNIT）；要退：sudo bash $0 --rollback" >&2
        status=1
    fi
else
    echo
    echo "完成。daemon 仍跑旧代码，请以 guzhujushi 身份执行："
    echo "  bash /home/guzhujushi/trimum/scripts/restart_trmd.sh"
    echo "（或加 --restart 让本脚本自己重启并冒烟）"
fi
exit $status
