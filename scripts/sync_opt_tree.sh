#!/usr/bin/env bash
# 把源码同步到部署树 /opt/trimum（真机、需要 root）
#
#   sudo bash /tmp/sync_opt_tree.sh              # 同步 src/ config/ tests/ scripts/ + 顶层文件
#   sudo bash /tmp/sync_opt_tree.sh --fix-home   # 额外修 /home/guzhujushi/trimum/src 的 root 属主，并用源补齐缺文件
#   sudo bash /tmp/sync_opt_tree.sh --dry-run    # 只报告将要做什么
#   sudo bash /tmp/sync_opt_tree.sh --from-home  # 强制用开发树当源（默认优先用 /tmp/trimum-sync.tar）
#
# 为什么需要 sudo：/opt/trimum/{config,tests,scripts} 与 src/trimum_core 是 root 属主；
# /home/guzhujushi/trimum/src 也是 root:root（用 --fix-home 修）。
# 为什么脚本不重启 daemon：daemon 必须以 guzhujushi 运行（root 跑会把 ~/.trimum 写脏），
# 同步完成后请自己执行：bash /home/guzhujushi/trimum/scripts/restart_trmd.sh
set -euo pipefail

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

for arg in "$@"; do
    case "$arg" in
        --fix-home) FIX_HOME=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --from-home) FROM_HOME=1 ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

if [[ ${EUID} -ne 0 && ${TRIMUM_ALLOW_NONROOT:-0} != 1 ]]; then
    echo "请用 sudo 运行：sudo bash $0" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. 选源：tar 包优先（开发树可能缺文件，例如 root 属主导致 src/agent-sdk 建不出来）
# ---------------------------------------------------------------------------
echo "== [1/5] 同步源 =="
if [[ $FROM_HOME -eq 1 || ! -f "$TARBALL" ]]; then
    SRC="$SOURCE_DIR"
    STAGE=""
    [[ -f "$SRC/pyproject.toml" ]] || { echo "同步源不可用：$SRC/pyproject.toml 不存在" >&2; exit 1; }
    echo "  源：开发树 $SRC"
else
    rm -rf "$STAGE"
    mkdir -p "$STAGE"
    tar -xf "$TARBALL" -C "$STAGE"
    SRC="$STAGE"
    echo "  源：tar 包 $TARBALL（$(du -sh "$STAGE" | cut -f1)）"
fi
echo "  目标：$APP_DIR（属主 $OWNER_USER:$OWNER_GROUP）"

# ---------------------------------------------------------------------------
# 2. 代码与配置
# ---------------------------------------------------------------------------
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
echo "== [3/5] 顶层文件 =="
DOC_OWNER="$(stat -c '%U:%G' "$APP_DIR")"
for doc in AGENTS.md ARCH.md PRD.md STATUS.md TODO.md pyproject.toml; do
    if [[ -f "$SRC/$doc" ]]; then
        [[ $DRY_RUN -eq 0 ]] && install -o "${DOC_OWNER%%:*}" -g "${DOC_OWNER##*:}" -m 0644 \
            "$SRC/$doc" "$APP_DIR/$doc"
        echo "  $doc -> $APP_DIR/$doc ($DOC_OWNER)"
    fi
done
if [[ -f "$SRC/docs/OPERATIONS.md" ]]; then
    [[ $DRY_RUN -eq 0 ]] && install -o "${DOC_OWNER%%:*}" -g "${DOC_OWNER##*:}" -m 0644 \
        "$SRC/docs/OPERATIONS.md" "$APP_DIR/OPERATIONS.md"
    echo "  docs/OPERATIONS.md -> $APP_DIR/OPERATIONS.md ($DOC_OWNER)"
fi

# ---------------------------------------------------------------------------
# 4. 校验
# ---------------------------------------------------------------------------
echo "== [4/5] 校验 =="
status=0
for f in \
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
# 5. 可选：修开发树 src 属主，并把源里缺的文件补回去
# ---------------------------------------------------------------------------
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
echo "完成。daemon 仍跑旧代码，请以 guzhujushi 身份执行："
echo "  bash /home/guzhujushi/trimum/scripts/restart_trmd.sh"
exit $status