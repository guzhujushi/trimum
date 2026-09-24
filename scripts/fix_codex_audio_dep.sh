#!/usr/bin/env bash
# 修 VS Code「浏览器侧」（serve-web / tunnel / vscode.dev）Codex 扩展无法激活的问题。
#
# 症状：在浏览器里的 VS Code 点 Codex 图标 → `command 'chatgpt.openSidebar' not found`
#       （VS Code 另报：Cannot activate the 'Codex' extension because it depends on
#        the 'Codex Audio' extension which is disabled）
# 根因：openai.chatgpt 清单里写了 extensionDependencies: ["openai.codex-audio"]，
#       而 openai.codex-audio 是 extensionKind: ["ui"]（桌面专用，无 browser 入口）⇒
#       浏览器侧没有 UI 扩展宿主，依赖恒不满足 ⇒ Codex 整体不激活 ⇒ 命令没注册。
#       上游 issue：openai/codex#47357（2026-09-24 仍 open，官方未修）。
# 做法：把 server 侧这份清单里的 extensionDependencies 去掉（备份原文件，可一键还原）。
# 注意：扩展被自动更新/重装后会复原，需要重跑本脚本（建议更新后复查一次）。
#
# 用法：bash fix_codex_audio_dep.sh [--apply]      # 默认 dry-run；--apply 才写
#       EXTDIR=/path/to/extensions bash fix_codex_audio_dep.sh --apply
set -uo pipefail

EXTDIR="${EXTDIR:-$HOME/.vscode-server/extensions}"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

if [ ! -d "$EXTDIR" ]; then
  echo "[error] 扩展目录不存在：$EXTDIR" >&2
  exit 1
fi

shopt -s nullglob
found=0
for dir in "$EXTDIR"/openai.chatgpt-*; do
  pkg="$dir/package.json"
  [ -f "$pkg" ] || continue
  found=1
  echo "--- $dir"
  python3 - "$pkg" "$APPLY" <<'PY'
import json, sys, shutil, datetime

pkg, apply_ = sys.argv[1], sys.argv[2] == "1"
data = json.load(open(pkg, encoding="utf-8"))

deps = data.get("extensionDependencies") or []
if "openai.codex-audio" not in deps:
    print("    [skip] 清单里没有 openai.codex-audio 依赖，无需处理")
    raise SystemExit(0)

rest = [d for d in deps if d != "openai.codex-audio"]
print(f"    [plan] extensionDependencies: {deps} -> {rest or '(删除该键)'}")
if not apply_:
    print("    [dry-run] 未写盘；加 --apply 生效")
    raise SystemExit(0)

bak = pkg + ".bak_trimum_" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(pkg, bak)
if rest:
    data["extensionDependencies"] = rest
else:
    data.pop("extensionDependencies", None)
with open(pkg, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=2)
print(f"    [done] 已改；备份 {bak}")
PY
done

if [ "$found" = 0 ]; then
  echo "[error] 没找到 openai.chatgpt 安装目录（EXTDIR=$EXTDIR）" >&2
  exit 1
fi
