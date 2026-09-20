#!/usr/bin/env bash
# 把开发树同步到部署树 /opt/trimum（真机、需要 root）
#
#   sudo bash /tmp/sync_opt_tree.sh              # 同步 src/ config/ tests/ scripts/ + 顶层文档
#   sudo bash /tmp/sync_opt_tree.sh --fix-home   # 额外修正 /home/guzhujushi/trimum/src 的 root 属主
#   sudo bash /tmp/sync_opt_tree.sh --dry-run    # 只报告将要做什么
#
# 为什么需要 sudo：/opt/trimum/{config,tests,scripts} 与 src/trimum_core 是 root 属主。
# 为什么脚本不重启 daemon：daemon 必须以 guzhujushi 运行（root 跑会把 ~/.trimum 写脏），
# 同步完成后请自己执行：bash /home/guzhujushi/trimum/scripts/restart_trmd.sh
set -euo pipefail

SOURCE_DIR="${TRIMUM_SOURCE:-/home/guzhujushi/trimum}"
APP_DIR="${TRIMUM_APP_DIR:-/opt/trimum}"
HOME_SRC="${TRIMUM_HOME_SRC:-/home/guzhujushi/trimum/src}"
FIX_HOME=0
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --fix-home) FIX_HOME=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

if [[ ${EUID} -ne 0 ]]; then
    echo "请用 sudo 运行：sudo bash $0" >&2
    exit 1
fi

if [[ ! -f "$SOURCE_DIR/pyproject.toml" ]]; then
    echo "同步源不可用：$SOURCE_DIR/pyproject.toml 不存在" >&2
    exit 1
fi

echo "== [1/5] 同步源 =="
echo "  源目录 : $SOURCE_DIR"
echo "  目标   : $APP_DIR"

echo "== [2/5] src/ config/ tests/ scripts/ -> root:root =="
if [[ $DRY_RUN -eq 0 ]]; then
    install -d -o root -g root -m 0755 \
        "$APP_DIR/src" "$APP_DIR/config" "$APP_DIR/tests" "$APP_DIR/scripts"
fi

sync_tree() {
    local rel="$1" mode="$2" count=0 file dest
    if [[ ! -d "$SOURCE_DIR/$rel" ]]; then
        echo "  $rel: 源目录缺失，跳过"
        return 0
    fi
    while IFS= read -r -d '' file; do
        dest="$APP_DIR/$rel/${file#"$SOURCE_DIR/$rel/"}"
        if [[ $DRY_RUN -eq 0 ]]; then
            install -D -o root -g root -m "$mode" "$file" "$dest"
        fi
        count=$((count + 1))
    done < <(find "$SOURCE_DIR/$rel" -type f \
        -not -path '*__pycache__*' -not -name '*.pyc' -print0)
    echo "  $rel: $count 个文件 (mode $mode)"
}

sync_tree src 0644
sync_tree config 0644
sync_tree tests 0644
sync_tree scripts 0755

echo "== [3/5] 顶层文档（沿用目标目录既有属主）=="
DOC_OWNER="$(stat -c '%U:%G' "$APP_DIR")"
for doc in AGENTS.md ARCH.md PRD.md STATUS.md TODO.md; do
    if [[ -f "$SOURCE_DIR/$doc" ]]; then
        if [[ $DRY_RUN -eq 0 ]]; then
            install -o "${DOC_OWNER%%:*}" -g "${DOC_OWNER##*:}" -m 0644 \
                "$SOURCE_DIR/$doc" "$APP_DIR/$doc"
        fi
        echo "  $doc -> $APP_DIR/$doc ($DOC_OWNER)"
    fi
done
if [[ -f "$SOURCE_DIR/docs/OPERATIONS.md" ]]; then
    if [[ $DRY_RUN -eq 0 ]]; then
        install -o "${DOC_OWNER%%:*}" -g "${DOC_OWNER##*:}" -m 0644 \
            "$SOURCE_DIR/docs/OPERATIONS.md" "$APP_DIR/OPERATIONS.md"
    fi
    echo "  docs/OPERATIONS.md -> $APP_DIR/OPERATIONS.md ($DOC_OWNER)"
fi

echo "== [4/5] 校验关键文件 =="
status=0
for f in \
    src/trimum_core/mcp_catalog.py \
    src/trimum_core/mcp_client.py \
    src/trimum_core/mcp_registry.py \
    src/trimum_core/cli/commands/mcp.py \
    src/trimum_core/cli/commands/setup.py \
    src/trimum_core/setup_wizard.py \
    src/trimum_core/identity.py \
    config/mcp-catalog.yaml; do
    if [[ -f "$APP_DIR/$f" ]]; then
        echo "  OK   $f ($(stat -c '%U:%G %s' "$APP_DIR/$f"))"
    else
        echo "  MISS $f"
        status=1
    fi
done
echo "  tests/*.py : $(find "$APP_DIR/tests" -maxdepth 1 -name '*.py' | wc -l) 个"
echo "  src/trimum_core/*.py : $(find "$APP_DIR/src/trimum_core" -maxdepth 1 -name '*.py' | wc -l) 个"
echo "  src/trimum_core 属主分布："
find "$APP_DIR/src/trimum_core" -maxdepth 1 -printf '    %u:%g\n' 2>/dev/null | sort | uniq -c

echo "== [5/5] 可选：修正开发树 src 属主 =="
if [[ $FIX_HOME -eq 1 ]]; then
    echo "  chown -R ${DOC_OWNER%%:*}:${DOC_OWNER##*:} $HOME_SRC"
    if [[ $DRY_RUN -eq 0 ]]; then
        chown -R "${DOC_OWNER%%:*}:${DOC_OWNER##*:}" "$HOME_SRC"
        ls -ld "$HOME_SRC" "$HOME_SRC/trimum_core"
    fi
else
    echo "  跳过（用 --fix-home 启用）。当前："
    ls -ld "$HOME_SRC" 2>&1 | sed 's/^/    /'
fi

echo
echo "完成。daemon 仍跑旧代码，请以 guzhujushi 身份执行："
echo "  bash /home/guzhujushi/trimum/scripts/restart_trmd.sh"
exit $status