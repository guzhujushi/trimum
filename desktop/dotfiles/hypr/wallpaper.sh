#!/usr/bin/env bash
# =============================================================================
# trimum — 应用活动主题壁纸
#
# 由 hyprland.conf 的 exec-once 调用（登录时设置壁纸），
# 也可由 scripts/trimum-theme set 直接调用。
# 优先使用 swww；swww 不可用时回退 hyprctl hyprpaper。
# =============================================================================
set -euo pipefail

# ---- 定位 TRIMUM_HOME（/opt/trimum > 脚本相对路径）----
TRIMUM_HOME="${TRIMUM_HOME:-}"
if [ -z "$TRIMUM_HOME" ]; then
  if [ -d /opt/trimum ]; then
    TRIMUM_HOME=/opt/trimum
  else
    TRIMUM_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  fi
fi
export TRIMUM_HOME

# 活动壁纸目录：优先 ~/.config 已安装副本，其次仓库 dotfiles
wall_dir="${HOME}/.config/wallpapers/current"
[ -d "$wall_dir" ] || wall_dir="${TRIMUM_HOME}/desktop/dotfiles/wallpapers/current"

# 选取第一张壁纸（按文件名排序，跳过占位图 omarchy.webp）
wallpaper="$(find -L "$wall_dir" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' \) \
  2>/dev/null | sort | head -n 1 || true)"

if [ -z "$wallpaper" ]; then
  echo "[trimum] 未找到壁纸: $wall_dir"
  exit 0
fi

if command -v swww >/dev/null 2>&1 && pgrep -x swww-daemon >/dev/null 2>&1; then
  swww img "$wallpaper" --transition-type wipe --transition-fps 60 || true
  echo "[trimum] 壁纸已应用 (swww): $(basename "$wallpaper")"
elif command -v hyprctl >/dev/null 2>&1 && hyprctl hyprpaper >/dev/null 2>&1; then
  hyprctl hyprpaper wallpaper ",$wallpaper" || true
  echo "[trimum] 壁纸已应用 (hyprpaper): $(basename "$wallpaper")"
else
  echo "[trimum] 未检测到 swww/hyprpaper，跳过壁纸设置: $wallpaper"
fi
