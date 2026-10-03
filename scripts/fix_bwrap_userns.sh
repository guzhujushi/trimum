#!/usr/bin/env bash
# 让 bwrap（以及依赖它的 codex / sandbox-runtime 类沙箱）在 Ubuntu 24.04 上能用。
#
# 背景（真机实测，详见 docs/SANDBOX-PLAN.md §2.4 / §6.4 / §9.1 裁决 2）：
#   Ubuntu 24.04 默认 kernel.apparmor_restrict_unprivileged_userns=1 ⇒ 非特权 userns 要么被拒
#   （`bwrap: setting up uid map: Permission denied`），要么建起来但里面没有能力
#   （`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`）。裁决是**不全局放开**，
#   需要时**定向**给 bwrap 一个 AppArmor profile（= S5-③）。
#
# 用法（全部需要 root）：
#   sudo bash scripts/fix_bwrap_userns.sh                        # dry-run：只体检 + 打印将要做的事
#   sudo bash scripts/fix_bwrap_userns.sh --apply                # 落地：定向 profile（默认，推荐）
#   sudo bash scripts/fix_bwrap_userns.sh --apply --mode sysctl  # 备选：全局放开 sysctl（影响更大）
#   sudo bash scripts/fix_bwrap_userns.sh --rollback             # 回滚到改动前
#
# 安全设计：先落地 → **以真实用户身份实测** bwrap/codex 沙箱 → 实测不过就自动回滚（--keep 可禁）。
set -uo pipefail

MODE=profile; APPLY=0; ROLLBACK=0; KEEP=0
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --rollback) ROLLBACK=1 ;;
    --mode=profile|--mode=sysctl) MODE="${a#--mode=}" ;;
    --mode) ;;
    profile|sysctl) MODE="$a" ;;
    --keep) KEEP=1 ;;
    -h|--help) sed -n "10,16p" "$0" | sed "s/^# \{0,1\}//"; exit 0 ;;
    *) echo "未知参数：$a" >&2; exit 2 ;;
  esac
done
MODE="${MODE#--mode=}"

PROFILE=/etc/apparmor.d/bwrap
PARSER=/sbin/apparmor_parser
SYSCTL_KEY=kernel.apparmor_restrict_unprivileged_userns
SYSCTL_FILE=/etc/sysctl.d/99-trimum-bwrap-userns.conf
STATE=/var/lib/trimum-bwrap-userns.state
TARGET_USER="${SUDO_USER:-$(stat -c %U "$(dirname "$(readlink -f "$0")")/.." 2>/dev/null || echo root)}"

say(){ printf "%s\n" "$*"; }
ok(){ printf "  [ok] %s\n" "$*"; }
warn(){ printf "  [!!] %s\n" "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "需要 root：sudo bash $0 $*" >&2; exit 1; }
[ -n "$TARGET_USER" ] && [ "$TARGET_USER" != root ] || warn "拿不到真实用户名（SUDO_USER 为空），实测将跳过"

# ── 体检 ─────────────────────────────────────────────────────────────
say "== 现状 =="
say "  用户            : $TARGET_USER"
say "  userns sysctl   : $SYSCTL_KEY=$(cat /proc/sys/$SYSCTL_KEY 2>/dev/null || echo ?)"
say "  apparmor 服务   : $(systemctl is-active apparmor 2>/dev/null || echo ?)"
say "  apparmor_parser : $([ -x $PARSER ] && echo 有 || echo 缺)"
say "  现有 profile    : $([ -f $PROFILE ] && echo "$PROFILE 已存在" || echo 无（将新建）)"
[ -f "$STATE" ] && say "  上次改动记录    : $(cat "$STATE")"

probe() {  # 以真实用户身份实测：$1 = 标签
  [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != root ] || return 1
  local label="$1"
  if su - "$TARGET_USER" -c "bwrap --dev-bind / / --chdir /tmp true" >/dev/null 2>&1; then
    ok "$label：bwrap 可用"
    if su - "$TARGET_USER" -c "command -v codex >/dev/null && codex sandbox -- /bin/echo sandbox-ok" >/dev/null 2>&1; then
      ok "$label：codex sandbox 可用"
    else
      warn "$label：codex sandbox 仍不可用（bwrap 通但 codex 侧未通，看下面提示）"
    fi
    return 0
  fi
  warn "$label：bwrap 仍不可用"
  return 1
}

say
say "== 改动前实测 =="
probe "before" || true

# ── 回滚 ─────────────────────────────────────────────────────────────
if [ "$ROLLBACK" -eq 1 ]; then
  say; say "== 回滚 =="
  if [ "$APPLY" -eq 0 ]; then say "  （dry-run：加 --apply 才真回滚）"; exit 0; fi
  if [ -f "$PROFILE" ]; then
    [ -x "$PARSER" ] && "$PARSER" -R "$PROFILE" 2>/dev/null
    rm -f "$PROFILE" && ok "已删除 $PROFILE 并卸载 profile"
  else
    say "  无 $PROFILE，跳过"
  fi
  if [ -f "$SYSCTL_FILE" ]; then rm -f "$SYSCTL_FILE"; ok "已删 $SYSCTL_FILE"; fi
  [ -f "$STATE" ] && grep -q "mode=sysctl" "$STATE" && { echo 1 > "/proc/sys/$SYSCTL_KEY"; ok "已恢复 $SYSCTL_KEY=1"; }
  rm -f "$STATE"
  say; say "== 回滚后实测 =="; probe "after-rollback" || true
  exit 0
fi

# ── 计划 ─────────────────────────────────────────────────────────────
say
say "== 计划（mode=$MODE）=="
if [ "$MODE" = profile ]; then
  say "  新建 $PROFILE ：给 /usr/bin/bwrap 定向授予 userns（不动全局 sysctl）"
  say "  加载：$PARSER -r $PROFILE"
else
  say "  写 $SYSCTL_FILE ：$SYSCTL_KEY=0（全局放开，影响本机所有非特权 userns 使用者）"
  say "  立即生效：echo 0 > /proc/sys/$SYSCTL_KEY"
fi
say "  记录到 $STATE ；实测不过自动回滚（--keep 可禁）"
if [ "$APPLY" -eq 0 ]; then say; say "（dry-run：确认后加 --apply）"; exit 0; fi

# ── 落地 ─────────────────────────────────────────────────────────────
say
say "== 落地 =="
if [ "$MODE" = profile ]; then
  [ -x "$PARSER" ] || { warn "缺 apparmor_parser（apt install apparmor apparmor-utils 后再跑）"; exit 1; }
  [ -f "$PROFILE" ] && cp -a "$PROFILE" "$PROFILE.bak_trimum_$(date +%Y%m%d-%H%M%S)" && ok "已备份原 profile"
  cat > "$PROFILE" <<"PROF"
# 由 trimum scripts/fix_bwrap_userns.sh 生成（S5-③：定向给 bwrap 放开非特权 userns）
# 回滚：sudo bash scripts/fix_bwrap_userns.sh --apply --rollback
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
PROF
  "$PARSER" -r "$PROFILE" || { warn "profile 加载失败，已回滚文件"; grep -q "^#" "$PROFILE" && rm -f "$PROFILE"; exit 1; }
  ok "profile 已加载：$PROFILE"
  echo "mode=profile ts=$(date -Is)" > "$STATE"
else
  printf "%s = 0\n" "$SYSCTL_KEY" > "$SYSCTL_FILE"
  echo 0 > "/proc/sys/$SYSCTL_KEY" || { warn "写 /proc/sys/$SYSCTL_KEY 失败"; exit 1; }
  ok "已写入 $SYSCTL_FILE 并即时生效"
  echo "mode=sysctl ts=$(date -Is)" > "$STATE"
fi

# ── 验证（以真实用户身份）─────────────────────────────────────────────
say
say "== 改动后实测 =="
if probe "after"; then
  say
  say "成功。下一步（用户侧，一次性）："
  say "  1) 把 .codex/config.toml 里 sandbox_mode=\"danger-full-access\" 换成注释里那段"
  say "     （approval_policy=\"never\" + sandbox_mode=\"workspace-write\" + [sandbox_workspace_write] writable_roots=[\"\$HOME/trimum\", \"/tmp\"]）"
  say "  2) reload Codex 窗口/新开会话 ⇒ 零审批 + 真隔离 + 工作空间显式"
  exit 0
fi

warn "验证未通过。"
if [ "$KEEP" -eq 0 ]; then
  say "  自动回滚（要保留改动请重跑并加 --keep）"
  if [ "$MODE" = profile ]; then
    "$PARSER" -R "$PROFILE" 2>/dev/null; rm -f "$PROFILE"
  else
    echo 1 > "/proc/sys/$SYSCTL_KEY"; rm -f "$SYSCTL_FILE"
  fi
  rm -f "$STATE"; ok "已回滚到改动前状态"
else
  say "  已保留改动（--keep）；若要回滚：sudo bash $0 --apply --rollback"
fi
say "  另一条路：换成 --mode sysctl 重试（全局放开 userns，代价是影响本机其它使用者）。"
exit 1
