#!/usr/bin/env bash
# 把 Codex 扩展（openai.chatgpt）webview 的「渲染器就绪」硬超时从 30 秒放大。
#
# 背景（2026-09-25 真机实测）：
#   Codex 的侧边栏 UI 是一个 webview，生产分支读 webview/index.html，
#   而它起步就要拉 **15.4 MB** JS/CSS（app-initial 4.2M + 5.7M + 4.8M + CSS 1.1M），
#   webview 目录总共 356 MB / 11115 个分块。扩展里写死 30 秒没就绪就放弃，
#   于是浏览器侧报「Codex could not start its user interface」：
#     [CodexWebviewProvider] Webview renderer did not become ready elapsedMs=30001
#       reason=renderer_ready_timeout receivedWebviewMessage=false
#   经中继链路（Tailscale DERP / vscode.dev 隧道）实测吞吐只有 200~400 KB/s
#   ⇒ 15.4 MB 需要 40~80 秒以上，30 秒必然超时。**根因是链路，不是配置错。**
#   治本是走 VPS/frp 那条低延迟通路（见 TODO.md §10）；本脚本只是让慢链路能加载完。
#
# 改动点（唯一锚点，非唯一就中止）：
#   receivedWebviewMessage:this.receivedWebviewMessage,timeoutMs:<X>})},<X>)
#   <X> 由 3e4(30s) 改为 6e5(600s)；重复执行会按当前值再改，幂等。
#
# 用法（真机侧）：
#   bash fix_codex_webview_timeout.sh                  # dry-run
#   bash fix_codex_webview_timeout.sh --apply          # 写入（自动备份，失败还原）
#   WEBVIEW_TIMEOUT_MS=900000 bash ... --apply         # 自定义毫秒数
# 注意：**扩展自动更新会覆盖 extension.js ⇒ 更新完要重跑本脚本。**
#       还原：把 out/extension.js.bak_trimum_* 拷回去。
set -uo pipefail

EXTDIR="${EXTDIR:-$HOME/.vscode-server/extensions}"
TARGET_MS="${WEBVIEW_TIMEOUT_MS:-600000}"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

shopt -s nullglob
dirs=("$EXTDIR"/openai.chatgpt-*)
[ ${#dirs[@]} -eq 0 ] && { echo "[error] 没找到 openai.chatgpt-* 目录（EXTDIR=$EXTDIR）" >&2; exit 1; }

for dir in "${dirs[@]}"; do
  f="$dir/out/extension.js"
  [ -f "$f" ] || { echo "[skip] 没有 $f"; continue; }
  echo "--- $dir"
  if [ "$APPLY" != "1" ]; then
    node -e '
const fs=require("fs"), s=fs.readFileSync(process.argv[1],"utf8");
const m=s.match(/receivedWebviewMessage:this\.receivedWebviewMessage,timeoutMs:([0-9]+(?:e[0-9]+)?)\}\)\},([0-9]+(?:e[0-9]+)?)\)/);
if(!m){console.log("  [warn] 没找到超时锚点（扩展可能已换实现）");process.exit(0);}
console.log("  当前超时 = "+Number(m[1])+" ms  目标 = "+process.argv[2]+" ms");
' "$f" "$TARGET_MS"
    echo "  (dry-run，加 --apply 才写)"
    continue
  fi
  TS=$(date +%Y%m%d-%H%M%S)
  BAK="$f.bak_trimum_$TS"
  cp -p "$f" "$BAK"
  if node -e '
const fs=require("fs"), f=process.argv[1], ms=process.argv[2];
const s=fs.readFileSync(f,"utf8");
const re=/receivedWebviewMessage:this\.receivedWebviewMessage,timeoutMs:([0-9]+(?:e[0-9]+)?)\}\)\},([0-9]+(?:e[0-9]+)?)\)/g;
const n=(s.match(re)||[]).length;
if(n!==1){console.error("  [abort] 锚点出现 "+n+" 次（要求 1 次）");process.exit(3);}
if(Number(s.match(re)[1])===Number(ms)){console.log("  已是 "+ms+" ms，无需改动");process.exit(0);}
fs.writeFileSync(f, s.replace(re, "receivedWebviewMessage:this.receivedWebviewMessage,timeoutMs:"+ms+"})},"+ms+")"), {encoding:"utf8"});
console.log("  已改为 "+ms+" ms");
' "$f" "$TARGET_MS"; then
    echo "  备份: $BAK"
    node --check "$f" >/dev/null 2>&1 && echo "  语法自检 OK" || { echo "  [error] 语法自检失败，还原"; cp -p "$BAK" "$f"; }
  else
    cp -p "$BAK" "$f"
    echo "  [error] 改动失败，已还原"
  fi
done
