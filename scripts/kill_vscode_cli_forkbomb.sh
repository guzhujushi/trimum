#!/usr/bin/env bash
# 清理真机上 `code --list-extensions` 触发的 fork 炸弹。
#
# 背景：真机有两个版本不同的 VS Code CLI（~/.local/bin/code = 1.139/commit 2242ebbb、
#       ~/.vscode-server/code-<commit> = 1.138），跑 --list-extensions 时两者**互相委派**，
#       形成父子交替、指数级膨胀的进程树（实测 8 秒 420 个、十来分钟上万），
#       一次把 load average 顶到 1334。详见 docs/OPERATIONS.md 对应小节。
#
# 要点：**先 SIGSTOP 冻结再 SIGKILL**。直接杀 PID 追不上（树的增速 > kill 循环，
#       实测杀 2003 个后 4 秒又长回 200 个）；冻结之后就断掉了派生源。
#
# 用法（真机侧）：
#   bash kill_vscode_cli_forkbomb.sh            # 只报告，不动手
#   bash kill_vscode_cli_forkbomb.sh --apply    # 真杀
set -uo pipefail

PATTERN="${PATTERN:-list-extensions}"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

# 用首字符加中括号的形式写模式，避免 grep 匹配到自己
GREP_PAT="[${PATTERN:0:1}]${PATTERN:1}"

snap() { ps -eo pid,pgid,args --no-headers | grep -- "$GREP_PAT"; }
count() { snap | grep -c "" ; }

echo "== 当前匹配 '$PATTERN' 的进程数: $(count) =="
[ "$(count)" = "0" ] && { echo "没有需要清理的进程"; exit 0; }

echo "== 进程组分布（pgid 组内进程数）=="
snap | awk '{print $2}' | sort | uniq -c | sort -rn | head -5 | sed 's/^/  /'

if [ "$APPLY" != "1" ]; then
  echo "(dry-run：加 --apply 才真杀)"
  exit 0
fi

for round in 1 2 3 4 5 6 7 8; do
  PIDS=$(snap | awk '{print $1}' | tr '\n' ' ')
  [ -z "$PIDS" ] && { echo "第 $round 轮: 已清零"; break; }
  # 第一遍：冻结（掐断派生源），不再新增进程
  kill -STOP $PIDS 2>/dev/null || true
  sleep 1
  # 第二遍：连冻结期间新生的一起冻结，再一并 SIGKILL
  PIDS=$(snap | awk '{print $1}' | tr '\n' ' ')
  [ -n "$PIDS" ] && { kill -STOP $PIDS 2>/dev/null || true; kill -KILL $PIDS 2>/dev/null || true; }
  sleep 2
  echo "第 $round 轮后残留: $(count)"
done

echo "== 结果 =="
echo "  残留: $(count)"
echo "  总进程数: $(ps -e --no-headers | grep -c "")"
echo "  load: $(cat /proc/loadavg)"
