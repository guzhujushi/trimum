#!/usr/bin/env bash
# 修好 VS Code Codex 扩展的「沙箱已损坏」。
#
# 背景（2026-10-02 真机实测）：
#   Ubuntu 24.04 默认 kernel.apparmor_restrict_unprivileged_userns=1 ⇒ 非特权 userns 被禁。
#   已有的 scripts/fix_bwrap_userns.sh（S5-③）只给 **/usr/bin/bwrap** 定向放了 AppArmor profile，
#   于是系统 codex（`codex sandbox -- ...`）已可用；但 VS Code Codex 扩展用的是**自带的**
#     ~/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex-resources/bwrap
#   该路径不在 profile 覆盖范围 ⇒ 实测 `bwrap: setting up uid map: Permission denied`
#   ⇒ 新会话仍显示「沙箱已损坏」。
#
# 本脚本给扩展自带的 bwrap 路径也补一条 AppArmor profile（默认；扩展升级后路径通配符仍生效）。
#
# 用法：
#   sudo bash scripts/fix_codex_ext_sandbox.sh                 # dry-run：体检 + 打印计划
#   sudo bash scripts/fix_codex_ext_sandbox.sh --apply         # 落地（AppArmor 定向 profile，推荐）
#   sudo bash scripts/fix_codex_ext_sandbox.sh --apply --mode symlink   # 备选：把自带 bwrap 软链到 /usr/bin/bwrap（无需动 AppArmor）
#   sudo bash scripts/fix_codex_ext_sandbox.sh --apply --rollback       # 回滚
#
# 安全：先落地 → 以真实用户实测 → 不过自动回滚（--keep 可禁）。
set -uo pipefail

MODE=profile; APPLY=0; ROLLBACK=0; KEEP=0
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --rollback) ROLLBACK=1 ;;
    --mode=profile|--mode=symlink) MODE="${a#--mode=}" ;;
    --mode) ;;
    profile|symlink) MODE="$a" ;;
    --keep) KEEP=1 ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$a" >&2; exit 2 ;;
  esac
done
MODE="${MODE#--mode=}"

PROFILE=/etc/apparmor.d/bwrap-codex-ext
PARSER=/sbin/apparmor_parser
TARGET_USER="${SUDO_USER:-$(id -un)}"
GLOB='/home/*/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex-resources/bwrap'

say(){ printf "%s\n" "$*"; }
ok(){ printf "  [ok] %s\n" "$*"; }
warn(){ printf "  [!!] %s\n" "$*"; }

IS_ROOT=0; [ "$(id -u)" -eq 0 ] && IS_ROOT=1
if [ "$APPLY" -eq 1 ] && [ "$IS_ROOT" -eq 0 ]; then
  echo "需要 root 才能落地：sudo bash $0 $*" >&2; exit 1
fi

TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"; [ -n "$TARGET_HOME" ] || TARGET_HOME="$HOME"
bundle_paths(){ ls -1 "$TARGET_HOME"/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex-resources/bwrap 2>/dev/null; }

probe(){  # 以真实用户身份跑「扩展自带 bwrap」
  local label="$1" p
  p="$(ls -1 "$HOME"/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex-resources/bwrap 2>/dev/null | head -1)"
  [ -n "$p" ] || p="$(su - "$TARGET_USER" -c 'ls -1 $HOME/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex-resources/bwrap 2>/dev/null | head -1' 2>/dev/null)"
  [ -n "$p" ] || { warn "$label：找不到扩展自带 bwrap"; return 1; }
  if [ "$IS_ROOT" -eq 1 ]; then
    su - "$TARGET_USER" -c "\"$p\" --dev-bind / / --chdir /tmp true" >/dev/null 2>&1 && { ok "$label：扩展自带 bwrap 可用（$p）"; return 0; }
  else
    "$p" --dev-bind / / --chdir /tmp true >/dev/null 2>&1 && { ok "$label：扩展自带 bwrap 可用（$p）"; return 0; }
  fi
  warn "$label：扩展自带 bwrap 仍不可用（$p）"; return 1
}

say "== 现状 =="
say "  用户            : $TARGET_USER"
say "  userns sysctl   : kernel.apparmor_restrict_unprivileged_userns=$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo ?)"
say "  /usr/bin/bwrap  : $( [ -f /etc/apparmor.d/bwrap ] && echo '已有独立 profile（系统 codex 应已可用）' || echo '无 profile' )"
say "  扩展自带 bwrap  : $(bundle_paths | head -1 || echo '未找到' )"
say "  现有本脚本 profile: $( [ -f $PROFILE ] && echo $PROFILE || echo 无 )"
say
say "== 改动前实测 =="; probe "before" || true

if [ "$ROLLBACK" -eq 1 ]; then
  say; say "== 回滚 =="
  [ "$APPLY" -eq 1 ] || { say "  （dry-run：加 --apply 才真回滚）"; exit 0; }
  if [ -f "$PROFILE" ]; then "$PARSER" -R "$PROFILE" 2>/dev/null; rm -f "$PROFILE" && ok "已卸载并删除 $PROFILE"; fi
  while read -r p; do [ -n "$p" ] || continue; [ -e "$p.orig" ] && { mv -f "$p.orig" "$p" && ok "已还原 $p"; }; done < <(bundle_paths)
  say; say "== 回滚后实测 =="; probe "after-rollback" || true
  exit 0
fi

say; say "== 计划（mode=$MODE）=="
if [ "$MODE" = profile ]; then
  say "  新建 $PROFILE ：给扩展自带 bwrap 的**通配路径**定向授予 userns"
  say "    $GLOB"
  say "  加载：$PARSER -r $PROFILE"
else
  say "  把每个扩展自带 bwrap 备份并软链到 /usr/bin/bwrap（命中已有 profile；扩展升级后需重跑）"
fi
[ "$APPLY" -eq 1 ] || { say; say "（dry-run：确认后加 --apply）"; exit 0; }

say; say "== 落地 =="
if [ "$MODE" = profile ]; then
  [ -x "$PARSER" ] || { warn "缺 apparmor_parser（apt install apparmor apparmor-utils）"; exit 1; }
  cat > "$PROFILE" <<PROF
# 由 trimum scripts/fix_codex_ext_sandbox.sh 生成
# 给 VS Code Codex 扩展自带的 bwrap 定向放开非特权 userns。
# 回滚：sudo bash scripts/fix_codex_ext_sandbox.sh --apply --rollback
abi <abi/4.0>,
include <tunables/global>

profile bwrap-codex-ext $GLOB flags=(unconfined) {
  userns,
  include if exists <local/bwrap-codex-ext>
}
PROF
  "$PARSER" -r "$PROFILE" || { warn "profile 加载失败（可能不支持通配 attachment）⇒ 改用 --mode symlink"; rm -f "$PROFILE"; exit 1; }
  ok "profile 已加载：$PROFILE"
else
  while read -r p; do
    [ -n "$p" ] || continue
    [ -e "$p.orig" ] || cp -a "$p" "$p.orig"
    ln -sf /usr/bin/bwrap "$p" && ok "已软链：$p -> /usr/bin/bwrap"
  done < <(bundle_paths)
fi

say; say "== 改动后实测 =="
if probe "after"; then
  say; say "成功。下一步："
  say "  1) VS Code 里 Reload Window（或重开 Codex 会话）⇒ 新会话不再报「沙箱已损坏」"
  say "  2) 想恢复真隔离：~/.codex/config.toml 设 sandbox_mode=\"workspace-write\" + approval_policy=\"never\""
  say "     + [sandbox_workspace_write] writable_roots=[\"\$HOME/trimum\", \"/tmp\"]"
  say "  3) ⚠️ 扩展升级会换目录名；profile 用通配路径 ⇒ 升级后一般仍有效（symlink 模式需重跑）"
  exit 0
fi

warn "验证未通过。"
if [ "$KEEP" -eq 0 ]; then
  say "  自动回滚（保留请加 --keep）"
  if [ "$MODE" = profile ]; then "$PARSER" -R "$PROFILE" 2>/dev/null; rm -f "$PROFILE"; fi
  while read -r p; do [ -n "$p" ] || continue; [ -e "$p.orig" ] && mv -f "$p.orig" "$p"; done < <(bundle_paths)
  ok "已回滚"
else
  say "  已保留（--keep）；回滚：sudo bash $0 --apply --rollback"
fi
exit 1
