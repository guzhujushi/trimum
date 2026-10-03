#!/usr/bin/env bash
# trimum-dev —— 无人值守开发流水线：派活 → 实现(qwen) → 门禁 → 验收(ds) → 提交
#
# 用法：
#   scripts/trimum-dev.sh new    <task>                      新建任务骨架（tmp/trimum-dev/<task>/）
#   scripts/trimum-dev.sh run    <task> [--fg] [--no-commit]  跑全流程（默认后台，立即返回）
#   scripts/trimum-dev.sh verify <task> [--fg] [--no-commit]  只重跑「门禁 → 检查 → 验收 → 提交」（接续已改好的工作区）
#   scripts/trimum-dev.sh fix    <task> [--fg] [--no-commit]  验收判 FAIL 后就地修（用 task-fix.md 再开一次实现窗口，不重跑初版）
#   scripts/trimum-dev.sh status <task>                      看进度
#   scripts/trimum-dev.sh logs   <task>                      列日志文件
#
# 每个任务目录需要有：task.md（实现提示词）verify.md（验收提示词）commit-msg.txt
#                      allowed.txt（白名单：一行一个允许改的文件）targets.txt（pytest 目标与参数）
# 环境变量：TRIMUM_DEV_REPO / TRIMUM_DEV_CODEX_RUN / TRIMUM_DEV_IMPL_TIMEOUT /
#           TRIMUM_DEV_VERIFY_TIMEOUT / TRIMUM_DEV_SANDBOX(=auto|workspace-write|bypass)
#           TRIMUM_DEV_VERIFY_SANDBOX(=bypass|auto|workspace-write，默认 bypass，理由见 VERIFY_SANDBOX 定义处)
set -uo pipefail

REPO="${TRIMUM_DEV_REPO:-$HOME/trimum}"
DEVROOT="$REPO/tmp/trimum-dev"
CODEX_RUN="${TRIMUM_DEV_CODEX_RUN:-$HOME/bin/codex-run}"
IMPL_TIMEOUT="${TRIMUM_DEV_IMPL_TIMEOUT:-1800}"
VERIFY_TIMEOUT="${TRIMUM_DEV_VERIFY_TIMEOUT:-1800}"
# 验收窗口**默认不关沙箱**（bypass）：全量回归必须在真宿主上跑 —— 它要起 API server、绑 socket、连本地端口，
# 而 workspace-write 会 `--unshare-net` 并把 /run/user 之类挂成只读。实测（2026-09-27 q5b）沙箱里
# tests/test_api_server_startup.py 会永远卡在 asyncio select：20 分钟不返回，宿主上同一套 79s 跑完。
# 验收窗口按契约是「只读 + 跑测试」，沙箱对它没有增益却有真实破坏性；要恢复沙箱用 TRIMUM_DEV_VERIFY_SANDBOX=workspace-write。
VERIFY_SANDBOX="${TRIMUM_DEV_VERIFY_SANDBOX:-bypass}"
SANDBOX_REQ="${TRIMUM_DEV_SANDBOX:-auto}"
PY="$REPO/.venv/bin/python"

ts() { date -Is; }
say() { printf "%s %s\n" "$(ts)" "$*"; }
die() { say "FATAL $*"; exit 1; }

usage() { sed -n "/^# 用法：/,/^set -uo/p" "$0" | sed -e "s/^# \{0,1\}//" -e "/^set -uo/d"; exit 2; }

# 沙箱能不能真起来：Ubuntu 24.04 用 AppArmor 禁掉非特权 userns（apparmor_restrict_unprivileged_userns=1）时
# bwrap 会 "setting up uid map: Permission denied"，codex 的 Linux 沙箱随之全程 EPERM。无人值守下没人批准提权，
# 所以探测失败就自动降级 bypass（白名单门禁兜底）。
# codex 的 Linux 沙箱**另外**要解析 /proc/self/mountinfo，且要求第 4 字段（root）是绝对路径；
# docker / snapd 的条目会写成 ``net:[...]`` ⇒ codex 一律报 "mountinfo path is not absolute"。
# bwrap 起得来 ≠ codex 沙箱能用（2026-10-01 实测：本机 bwrap 正常，codex 仍全程不可用）。
codex_sandbox_usable() {
  awk '{ if ($4 !~ /^\//) bad = 1 } END { exit (bad ? 1 : 0) }' /proc/self/mountinfo 2>/dev/null
}

detect_sandbox() {
  local r
  case "$SANDBOX_REQ" in
    workspace-write|bypass) echo "$SANDBOX_REQ"; return ;;
  esac
  if ! command -v bwrap >/dev/null 2>&1 || ! bwrap --dev-bind / / --chdir /tmp true >/dev/null 2>&1; then
    r="$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo "?")"
    say "沙箱探测失败（bwrap 起不来；apparmor_restrict_unprivileged_userns=$r）⇒ 本次降级 bypass，用白名单门禁兜底" >&2
    echo "bypass"
    return
  fi
  if ! codex_sandbox_usable; then
    say "bwrap 正常但 /proc/self/mountinfo 里有非绝对 root 字段（docker/snapd）⇒ codex 沙箱会报 mountinfo path is not absolute，本次降级 bypass，用白名单门禁兜底" >&2
    echo "bypass"
    return
  fi
  echo "workspace-write"
}

do_codex() { # profile prompt_file logfile timeout sandbox
  local profile="$1" prompt="$2" out="$3" tmo="$4" sb="$5"
  if [ "$sb" = "bypass" ]; then
    ( cd "$REPO" && timeout "$tmo" "$CODEX_RUN" "$profile" exec --skip-git-repo-check \
        --dangerously-bypass-approvals-and-sandbox "$(cat "$prompt")" </dev/null ) >>"$out" 2>&1
  else
    ( cd "$REPO" && timeout "$tmo" "$CODEX_RUN" "$profile" exec --skip-git-repo-check \
        -s "$sb" "$(cat "$prompt")" </dev/null ) >>"$out" 2>&1
  fi
}

run_codex() { # profile prompt_file logfile timeout [sandbox]
  local profile="$1" prompt="$2" out="$3" tmo="$4" sb="${5:-$SANDBOX}" rc
  do_codex "$profile" "$prompt" "$out" "$tmo" "$sb"; rc=$?
  if [ "$rc" -ne 0 ] && [ "$sb" != "bypass" ] \
     && grep -qiE "bubblewrap|linux_sandbox|operation_not_permitted|sandbox violation|mountinfo" "$out" 2>/dev/null; then
    say "$profile 窗口被系统沙箱挡住（rc=$rc），本次改用 bypass 重试一次"
    do_codex "$profile" "$prompt" "$out" "$tmo" bypass; rc=$?
  fi
  return "$rc"
}

changed_files() {
  # ``-uall`` 必须带：默认的 porcelain 会把「整个新目录」折叠成一行 ``dir/``，
  # 于是新建目录里的文件过不了白名单门禁（E7s3a 实测：skills/code-review/ 被判越界）。
  git -C "$REPO" status --porcelain=v1 -uall 2>/dev/null | sed -e "s/^...//" -e "s/.* -> //" | grep -v "^$"
}

stage_implement() { # dir [prompt] [logname]
  local dir="$1" prompt="${2:-task.md}" logname="${3:-implement}" log
  log="$dir/logs/$logname.log"
  say "STAGE 实现(qwen) 开始 → $log（提示词 $prompt，超时 ${IMPL_TIMEOUT}s，沙箱=$SANDBOX）"
  run_codex qwen "$dir/$prompt" "$log" "$IMPL_TIMEOUT"; local rc=$?
  say "STAGE 实现(qwen) 结束 rc=$rc"
  return "$rc"
}

gate_diff() { # dir
  local dir="$1" f changed
  changed="$(changed_files)"
  if [ -z "$changed" ]; then say "GATE 失败：实现窗口没有产生任何改动"; return 1; fi
  while read -r f; do
    [ -n "$f" ] || continue
    if ! grep -qxF "$f" "$dir/allowed.txt"; then
      say "GATE 失败：越界改动 $f（不在 allowed.txt）"; return 1
    fi
  done <<< "$changed"
  say "GATE 通过：改动 = $(echo "$changed" | tr "\n" " ")"
  return 0
}

stage_checks() { # dir
  local dir="$1" log="$1/logs/checks.log" f rc=0
  : > "$log"
  {
    echo "== $(ts) py_compile =="
    while read -r f; do
      case "$f" in *.py) "$PY" -m py_compile "$REPO/$f" && echo "  ok $f" || { echo "  FAIL $f"; rc=1; } ;; esac
    done < <(changed_files)
    echo "== $(ts) 目标测试 =="
    ( cd "$REPO" && "$PY" -m pytest $(cat "$dir/targets.txt") --basetemp tmp/pytest-tmp-dev -p no:cacheprovider ) || rc=1
    echo "== $(ts) ruff（有就用，只记录不改）=="
    ( cd "$REPO" && "$PY" -m ruff check $(sed -n "s/^\(.*\.py\)$/\1/p" "$dir/allowed.txt" | tr "\n" " ") ) 2>&1 || echo "  (ruff 不可用或有问题，见上)"
    echo "== $(ts) diffstat =="
    git -C "$REPO" diff --stat
  } >> "$log" 2>&1
  say "STAGE 确定性检查 rc=$rc → $log"
  return "$rc"
}

stage_verify() { # dir
  local dir="$1" log="$1/logs/verify.log" before after rc
  local head_before head_after
  : > "$log"   # 重跑就重开一份，别把上一次的裁决和新内容混在一起
  head_before="$(git -C "$REPO" rev-parse HEAD)"
  before="$(changed_files | sort)"
  say "STAGE 验收(ds) 开始 → $log（超时 ${VERIFY_TIMEOUT}s，沙箱=$VERIFY_SANDBOX）"
  run_codex ds "$dir/verify.md" "$log" "$VERIFY_TIMEOUT" "$VERIFY_SANDBOX"; rc=$?
  VERDICT="$(grep -oE "^VERDICT: [A-Za-z]+" "$log" 2>/dev/null | tail -1 | awk "{print \$2}")"
  say "STAGE 验收(ds) 结束 rc=$rc verdict=${VERDICT:-未知}"
  # 护栏：验收窗口跑在 bypass 下，契约是只读 —— 动了文件或产生了提交就直接判 FAIL
  head_after="$(git -C "$REPO" rev-parse HEAD)"
  after="$(changed_files | sort)"
  if [ "$head_before" != "$head_after" ]; then
    say "GATE 失败：验收窗口产生了提交（契约是只读）"
    return 1
  fi
  if [ "$before" != "$after" ]; then
    say "GATE 失败：验收窗口改动了工作区（契约是只读）"
    printf "%s\n" "$after" | sed "s/^/  /"
    return 1
  fi
  [ "$rc" -eq 0 ] || return 1
  [ "${VERDICT:-}" = "PASS" ] || return 1
  return 0
}

stage_commit() { # dir
  local dir="$1" f
  while read -r f; do [ -n "$f" ] || continue; git -C "$REPO" add -- "$f"; done < "$dir/allowed.txt"
  if git -C "$REPO" diff --cached --quiet; then say "STAGE 提交：暂存区为空，跳过"; return 1; fi
  git -C "$REPO" commit -F "$dir/commit-msg.txt" >> "$dir/logs/commit.log" 2>&1 || { say "STAGE 提交失败 → $dir/logs/commit.log"; return 1; }
  COMMIT_SHA="$(git -C "$REPO" rev-parse --short HEAD)"
  say "STAGE 提交完成 $COMMIT_SHA"
  return 0
}

write_report() { # dir status
  local dir="$1" status="$2" r="$1/report.md"
  {
    echo "# trimum-dev report — $(basename "$dir")"
    echo
    echo "- 时间：$(ts)"
    echo "- 起始 HEAD：${BASE_SHA:-?}  结束 HEAD：$(git -C "$REPO" rev-parse --short HEAD)"
    echo "- 结果：**$status**"
    echo "- 沙箱：$SANDBOX"
    echo "- 改动文件：${CHANGED:-（见 diffstat）}"
    echo "- commit：${COMMIT_SHA:-（未提交）}"
    echo
    echo "## 日志"
    for f in "$dir"/logs/*.log; do [ -e "$f" ] && echo "- \`${f#$REPO/}\`"; done
    echo
    echo "## checks 末尾"
    tail -25 "$dir/logs/checks.log" 2>/dev/null
    echo
    echo "## 验收裁决"
    grep -E "^VERDICT:" "$dir/logs/verify.log" 2>/dev/null | tail -5
  } > "$r"
  say "报告：$r"
}

run_task() { # name [--no-commit]
  local name="$1" nocommit="$2" dir="$DEVROOT/$name"
  [ -d "$dir" ] || die "任务目录不存在：$dir"
  for f in task.md verify.md commit-msg.txt allowed.txt targets.txt; do
    [ -s "$dir/$f" ] || die "缺文件：$dir/$f"
  done
  mkdir -p "$dir/logs"
  SANDBOX="$(detect_sandbox)"
  if [ -n "$(changed_files)" ]; then
    say "工作区已有改动，拒绝开跑（先处理干净）："; changed_files | sed "s/^/  /"; exit 3
  fi
  BASE_SHA="$(git -C "$REPO" rev-parse --short HEAD)"
  say "=== 开跑 $name，起点 $BASE_SHA，沙箱=$SANDBOX ==="
  if ! stage_implement "$dir"; then write_report "$dir" "FAIL（实现阶段失败）"; exit 1; fi
  if ! gate_diff "$dir"; then write_report "$dir" "FAIL（越界改动）"; exit 1; fi
  CHANGED="$(changed_files | tr "\n" " ")"
  say "本次改动清单：$CHANGED"
  if ! stage_checks "$dir"; then write_report "$dir" "FAIL（确定性检查不过）"; exit 1; fi
  if ! stage_verify "$dir"; then write_report "$dir" "FAIL（验收不通过，未提交）"; exit 1; fi
  if [ "$nocommit" = "--no-commit" ]; then
    write_report "$dir" "PASS（--no-commit，未提交）"; exit 0
  fi
  if stage_commit "$dir"; then write_report "$dir" "PASS（已提交 $COMMIT_SHA）"; exit 0; fi
  write_report "$dir" "PASS（验收通过但提交失败）"; exit 1
}

cmd_new() { # name
  local name="${1:-}" dir
  [ -n "$name" ] || usage
  dir="$DEVROOT/$name"; mkdir -p "$dir/logs"
  [ -s "$dir/allowed.txt" ]   || printf "%s\n" "src/CHANGEME.py" > "$dir/allowed.txt"
  [ -s "$dir/targets.txt" ]   || printf "%s\n" "tests/test_changeme.py" "-q" > "$dir/targets.txt"
  [ -s "$dir/commit-msg.txt" ] || printf "%s\n" "fix(x): 待填" > "$dir/commit-msg.txt"
  if [ ! -s "$dir/task.md" ]; then
    cat > "$dir/task.md" <<"EOT"
【任务】只改 <文件A>（必要时加 <文件B>），其余一律不许动。

【落点】<文件A>:<行号区间> 的 <函数名>；口径按 <现有签名>。

【硬约束】① 不许全仓搜索 / 不许读 <模块X> 之外的源码，找不到落点就停下报告；
         ② 不许跑 pytest 全量、不许 git 提交，只允许 python -m py_compile <文件A>；
         ③ 改完即停，不做顺手优化、不重构无关行。

【输出】固定三段：① 改动清单（文件:行号 + 一句话）② 为什么这样改（≤3 行）
         ③ 交接给验收窗口：建议的测试命令 + 需人工确认的点。
EOT
  fi
  if [ ! -s "$dir/verify.md" ]; then
    cat > "$dir/verify.md" <<"EOT"
【角色】你是验收窗口，只验收、不许改实现；发现问题只报告 + 给最小复现。

【要做的三件事】1) 跑目标测试与全量回归并与基线对比；2) 实测公开接口/边界行为；3) 代码质量与越界改动复查。

【硬约束】① 不许改代码、不许 git 提交、只读 + 跑测试；② 拿不到证据就写「无法核实」，不许猜；
         ③ 最后一行必须是 `VERDICT: PASS` 或 `VERDICT: FAIL`。
EOT
  fi
  echo "任务骨架：$dir"; ls -l "$dir"
}

fix_task() { # name [--no-commit]
  # 就地修：验收判 FAIL 后，树里留着上一轮的改动，再用 task-fix.md 开一次实现窗口（不重跑初版实现）。
  local name="$1" nocommit="$2" dir="$DEVROOT/$name"
  [ -d "$dir" ] || die "任务目录不存在：$dir"
  for f in task-fix.md verify.md commit-msg.txt allowed.txt targets.txt; do
    [ -s "$dir/$f" ] || die "缺文件：$dir/$f"
  done
  mkdir -p "$dir/logs"
  SANDBOX="$(detect_sandbox)"
  if [ -z "$(changed_files)" ]; then say "GATE 失败：工作区没有改动 —— 这是「就地修」通道，从头做请用 run"; exit 3; fi
  BASE_SHA="$(git -C "$REPO" rev-parse --short HEAD)"
  say "=== 就地修 $name（不重跑初版实现），起点 $BASE_SHA，沙箱=$SANDBOX ==="
  if ! stage_implement "$dir" task-fix.md implement-fix; then write_report "$dir" "FAIL（修复实现阶段失败）"; exit 1; fi
  if ! gate_diff "$dir"; then write_report "$dir" "FAIL（越界改动）"; exit 1; fi
  CHANGED="$(changed_files | tr "\n" " ")"
  say "本次改动清单：$CHANGED"
  if ! stage_checks "$dir"; then write_report "$dir" "FAIL（确定性检查不过）"; exit 1; fi
  if ! stage_verify "$dir"; then write_report "$dir" "FAIL（验收不通过，未提交）"; exit 1; fi
  if [ "$nocommit" = "--no-commit" ]; then write_report "$dir" "PASS（--no-commit，未提交）"; exit 0; fi
  if stage_commit "$dir"; then write_report "$dir" "PASS（已提交 $COMMIT_SHA）"; exit 0; fi
  write_report "$dir" "PASS（验收通过但提交失败）"; exit 1
}

resume_verify() { # name [--no-commit]
  # 接续模式：实现窗口的改动已经在工作区里（比如验收阶段被卡死/中断），只重跑门禁 + 检查 + 验收 + 提交
  local name="$1" nocommit="$2" dir="$DEVROOT/$name"
  [ -d "$dir" ] || die "任务目录不存在：$dir"
  for f in verify.md commit-msg.txt allowed.txt targets.txt; do
    [ -s "$dir/$f" ] || die "缺文件：$dir/$f"
  done
  mkdir -p "$dir/logs"
  SANDBOX="$(detect_sandbox)"
  if [ -z "$(changed_files)" ]; then say "GATE 失败：工作区没有改动，没什么可接续的（改用 run 从头跑）"; exit 3; fi
  BASE_SHA="$(git -C "$REPO" rev-parse --short HEAD)"
  say "=== 接续校验 $name（跳过实现），起点 $BASE_SHA，实现沙箱=$SANDBOX，验收沙箱=$VERIFY_SANDBOX ==="
  if ! gate_diff "$dir"; then write_report "$dir" "FAIL（越界改动）"; exit 1; fi
  CHANGED="$(changed_files | tr "\n" " ")"
  say "本次改动清单：$CHANGED"
  if ! stage_checks "$dir"; then write_report "$dir" "FAIL（确定性检查不过）"; exit 1; fi
  if ! stage_verify "$dir"; then write_report "$dir" "FAIL（验收不通过，未提交）"; exit 1; fi
  if [ "$nocommit" = "--no-commit" ]; then write_report "$dir" "PASS（--no-commit，未提交）"; exit 0; fi
  if stage_commit "$dir"; then write_report "$dir" "PASS（已提交 $COMMIT_SHA）"; exit 0; fi
  write_report "$dir" "PASS（验收通过但提交失败）"; exit 1
}

cmd_status() { # name
  local dir="$DEVROOT/${1:-}" name
  [ -d "$dir" ] || die "任务目录不存在：$dir"
  name="$(basename "$dir")"
  echo "== 任务 $name =="
  if [ -f "$dir/report.md" ]; then echo "--- report.md ---"; cat "$dir/report.md"; else echo "(还没有 report.md，仍在跑)"; fi
  echo "--- run.log 末尾 ---"; tail -15 "$dir/logs/run.log" 2>/dev/null
  echo "--- 当前工作区 ---"; git -C "$REPO" status --porcelain=v1 -b
  if pgrep -af "[t]rimum-dev.sh run $name" >/dev/null; then echo "--- 进程：仍在跑 ---"; else echo "--- 进程：已结束 ---"; fi
}

case "${1:-}" in
  new)    shift; cmd_new "${1:-}" ;;
  run)    name="${2:-}"; [ -n "$name" ] || usage
          case " ${*:-} " in *" --fg "*) fg=1 ;; *) fg="" ;; esac
          case " ${*:-} " in *" --no-commit "*) nc="--no-commit" ;; *) nc="" ;; esac
          dir="$DEVROOT/$name"; mkdir -p "$dir/logs"
          if [ -n "$fg" ]; then run_task "$name" "$nc"; else
            setsid nohup "$0" run "$name" --fg $nc >>"$dir/logs/run.log" 2>&1 </dev/null &
            sleep 1
            echo "已在后台开跑（PID $!）"
            echo "  进度：$0 status $name"
            echo "  日志：$dir/logs/run.log"
          fi ;;
  verify) name="${2:-}"; [ -n "$name" ] || usage
          case " ${*:-} " in *" --fg "*) fg=1 ;; *) fg="" ;; esac
          case " ${*:-} " in *" --no-commit "*) nc="--no-commit" ;; *) nc="" ;; esac
          dir="$DEVROOT/$name"; mkdir -p "$dir/logs"
          if [ -n "$fg" ]; then resume_verify "$name" "$nc"; else
            setsid nohup "$0" verify "$name" --fg $nc >>"$dir/logs/run.log" 2>&1 </dev/null &
            sleep 1
            echo "已在后台接续校验（PID $!）"
            echo "  进度：$0 status $name"
            echo "  日志：$dir/logs/run.log"
          fi ;;
  status) shift; cmd_status "${1:-}" ;;
  fix)    name="${2:-}"; [ -n "$name" ] || usage
          case " ${*:-} " in *" --fg "*) fg=1 ;; *) fg="" ;; esac
          case " ${*:-} " in *" --no-commit "*) nc="--no-commit" ;; *) nc="" ;; esac
          dir="$DEVROOT/$name"; mkdir -p "$dir/logs"
          if [ -n "$fg" ]; then fix_task "$name" "$nc"; else
            setsid nohup "$0" fix "$name" --fg $nc >>"$dir/logs/run.log" 2>&1 </dev/null &
            sleep 1
            echo "已在后台就地修（PID $!）"
            echo "  进度：$0 status $name"
            echo "  日志：$dir/logs/run.log"
          fi ;;
  logs)   ls -l "$DEVROOT/${2:-}/logs" 2>/dev/null || usage ;;
  *)      usage ;;
esac
