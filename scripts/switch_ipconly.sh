#!/usr/bin/env bash
# TCP 收口：把生产 trmd 的 HTTP（TCP）面关掉，只留 IPC socket
#
# 用法（--apply / --rollback 需要 sudo；--check 不需要）：
#   bash /tmp/switch_ipconly.sh --check           # 只体检：现状 + 前置条件（不动任何东西）
#   sudo bash /tmp/switch_ipconly.sh --apply      # 写 drop-in → daemon-reload → 重启 → 冒烟 → 失败自动回滚
#   sudo bash /tmp/switch_ipconly.sh --rollback   # 删 drop-in → 重启（一键退，HTTP 立刻回来）
#   --unit <名字>                                 # 默认 trmd
#
# 为什么另开一个 drop-in（20-http-off.conf）而不是改 10-hardening.conf：
#   ① S1 加固已验收，不再碰它；② 回滚 = 删一个文件 + 重启，不需要记得当初改了什么；
#   ③ config 侧契约（config.HTTP_ENV = TRIMUM_HTTP）本来就是为「能一键退的环境变量开关」写的。
#
# 前置（docs/SANDBOX-PLAN.md §9.3.7）：部署树必须已经整树同步到 HEAD —— 老 main.py 不认识
# core.http_enabled / TRIMUM_HTTP，硬关只会把 daemon 关掉。本脚本先验这一点，缺就拒绝动手。
set -uo pipefail

# 中断时要能定位到「哪一步」（这个脚本同样只能由你 sudo 跑）
STEP="初始化"
trap 'rc=$?; echo "[中断] 退出码=$rc｜最后一步：$STEP｜行号：$LINENO" >&2' ERR

UNIT="${TRIMUM_UNIT:-trmd}"
MODE=check
DEPLOY_ROOT="${TRIMUM_APP_DIR:-/opt/trimum}"
TRM_BIN="$DEPLOY_ROOT/venv/bin/trm"
SOCKET_PATH="${TRIMUM_SOCKET:-/run/trimum/trimum.sock}"
APP_PORT="${TRIMUM_HTTP_PORT:-8321}"
DROPIN_DIR="/etc/systemd/system/${UNIT}.service.d"
DROPIN="$DROPIN_DIR/20-http-off.conf"
DROPIN_HARDEN="$DROPIN_DIR/10-hardening.conf"
EVIDENCE_LOG="${EVIDENCE_LOG:-/tmp/switch-ipconly-$(date +%Y%m%d-%H%M%S).log}"
WORK_DIR="${TRIMUM_WORK_DIR:-}"
ASSERT_PY=""

PASS=0; WARN=0; FAIL=0
ok()   { printf '  [PASS] %s\n' "$1"; printf '  [PASS] %s\n' "$1" >> "$EVIDENCE_LOG"; PASS=$((PASS+1)); }
warn() { printf '  [WARN] %s\n' "$1"; printf '  [WARN] %s\n' "$1" >> "$EVIDENCE_LOG"; WARN=$((WARN+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; printf '  [FAIL] %s\n' "$1" >> "$EVIDENCE_LOG"; FAIL=$((FAIL+1)); }
sec()  { printf '\n== %s\n' "$1"; printf '\n== %s\n' "$1" >> "$EVIDENCE_LOG"; }

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE=check ;;
    --apply) MODE=apply ;;
    --rollback) MODE=rollback ;;
    --unit) shift || true; UNIT="${1:-trmd}"; DROPIN_DIR="/etc/systemd/system/${UNIT}.service.d"; DROPIN="$DROPIN_DIR/20-http-off.conf"; DROPIN_HARDEN="$DROPIN_DIR/10-hardening.conf" ;;
    --unit=*) UNIT="${1#--unit=}"; DROPIN_DIR="/etc/systemd/system/${UNIT}.service.d"; DROPIN="$DROPIN_DIR/20-http-off.conf"; DROPIN_HARDEN="$DROPIN_DIR/10-hardening.conf" ;;
    -h|--help) usage ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
  shift
done

need_root() {
  if [ "${EUID}" -ne 0 ]; then echo "请用 sudo 运行：sudo bash $0 $1" >&2; exit 1; fi
}

unit_user() { systemctl show "$UNIT" -p User --value 2>/dev/null; }
main_pid()  { systemctl show "$UNIT" -p MainPID --value 2>/dev/null; }

# 以 daemon 的身份跑 CLI（root 下必须 runuser，否则 ~/.trimum 归属会变）
as_user() {
  local u; u="$(unit_user)"; [ -n "$u" ] || u=guzhujushi
  if [ "${EUID}" -eq 0 ]; then runuser -u "$u" -- "$@"; else "$@"; fi
}

socket_live() {
  python3 - "$SOCKET_PATH" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(0.5)
sys.exit(0 if s.connect_ex(sys.argv[1]) == 0 else 1)
PY
}

wait_active() {
  local i
  for i in $(seq 1 30); do
    [ "$(systemctl is-active "$UNIT" 2>/dev/null)" = active ] && return 0
    sleep 1
  done
  return 1
}

# 就绪门：断言之前必须先等 daemon 真能服务（§9.3 那两次白回滚就是抢跑导致的）
wait_ready() {
  local i
  for i in $(seq 1 60); do
    if socket_live; then printf '  [PASS] daemon 就绪（等了约 %s 秒）：socket %s 可连接\n' "$((i / 2))" "$SOCKET_PATH"; return 0; fi
    sleep 0.5
  done
  return 1
}

dump_context() {
  local u home log ctx
  u="$(unit_user)"; [ -n "$u" ] || u=root
  home="$(getent passwd "$u" 2>/dev/null | cut -d: -f6)"
  log="${home:-/home/$u}/.local/share/trimum/trimum.log"
  ctx="$( {
    echo "--- systemctl status $UNIT ---"
    systemctl status "$UNIT" --no-pager -n 15 2>&1
    echo "--- journalctl -u $UNIT（最近 40 行）---"
    journalctl -u "$UNIT" -n 40 --no-pager 2>&1
    echo "--- $log：socket / 错误相关（最近 30 条）---"
    grep -E 'unix_socket|socket_start_failed|Traceback|"level": ?"error"|ipc-only' "$log" 2>/dev/null | tail -30
    echo "--- $log：tail 20 ---"
    tail -20 "$log" 2>/dev/null
  } 2>&1 )"
  printf '%s\n' "$ctx" | sed 's/^/     /'
  printf '%s\n' "$ctx" >> "$EVIDENCE_LOG"
  return 0
}

# 冒烟产物一律落进**本次运行新建**的目录：/tmp 是 sticky 位目录，
# fs.protected_regular=2 规定「属主不是自己的普通文件，连 root 也不能 O_CREAT 打开」——
# 混用普通用户与 root 跑同一个固定文件名必然 EACCES（真机已踩，见 SANDBOX-PLAN §9.3.9）。
ensure_work_dir() {
  [ -n "$WORK_DIR" ] && return 0
  WORK_DIR="$(mktemp -d /tmp/.switch-ipconly.XXXXXX)"
  chmod 0755 "$WORK_DIR"
  echo "  工作目录：$WORK_DIR"
}

write_assert_py() {
  ensure_work_dir
  ASSERT_PY="$WORK_DIR/assert_status.py"
  cat > "$ASSERT_PY" <<'PYEOF'
import json
import sys

path, pid = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
problems = []
if data.get("running") is not True:
    problems.append("running != true")
if data.get("source") != "rpc":
    problems.append("source=%r（不是 rpc，说明没走 socket）" % data.get("source"))
if data.get("http") is not False:
    problems.append("http=%r（应为 false）" % data.get("http"))
if data.get("ipc") is not True:
    problems.append("ipc=%r（应为 true）" % data.get("ipc"))
if pid.isdigit() and int(pid) > 0 and data.get("pid") != int(pid):
    problems.append("pid=%r 与 systemd MainPID=%s 不符" % (data.get("pid"), pid))
if problems:
    print("  status 断言失败：" + "；".join(problems))
    sys.exit(1)
print("  status 断言通过：running + source=rpc + http=false + ipc=true + pid 对得上")
PYEOF
}

# 前置：部署树必须认识这个开关（否则关的是 daemon 而不是 TCP）
precheck_deploy_tree() {
  local cfg="$DEPLOY_ROOT/src/trimum_core/config.py" main="$DEPLOY_ROOT/src/trimum_core/main.py"
  if [ -f "$cfg" ] && grep -q 'TRIMUM_HTTP' "$cfg"; then ok "部署树 config.py 认识 TRIMUM_HTTP 开关"
  else bad "部署树 config.py 里没有 TRIMUM_HTTP —— 先整树同步（sudo bash /tmp/sync_opt_tree.sh --restart）"; fi
  if [ -f "$main" ] && grep -q '_serve_without_http' "$main"; then ok "部署树 main.py 有关掉 HTTP 时的服务路径（_serve_without_http）"
  else bad "部署树 main.py 里没有 _serve_without_http —— 先整树同步（否则 TRIMUM_HTTP 关不掉 HTTP）"; fi
  if command -v ss >/dev/null 2>&1; then ok "ss 可用（用来做「进程真的没在监听」的决定性检查）"
  else warn "没有 ss，端口断言会退化成只看配置值"; fi
}

show_state() {
  sec "现状（$UNIT）"
  printf '  is-active   : %s\n' "$(systemctl is-active "$UNIT" 2>/dev/null)"
  printf '  MainPID     : %s\n' "$(main_pid)"
  printf '  NRestarts   : %s\n' "$(systemctl show "$UNIT" -p NRestarts --value 2>/dev/null)"
  printf '  Environment : %s\n' "$(systemctl show "$UNIT" -p Environment --value 2>/dev/null)"
  printf '  10-hardening.conf : %s\n' "$([ -f "$DROPIN_HARDEN" ] && echo 在 || echo 不在)"
  printf '  20-http-off.conf  : %s\n' "$([ -f "$DROPIN" ] && echo 在 || echo 不在)"
  printf '  socket      : %s %s\n' "$SOCKET_PATH" "$(socket_live && echo '（可连接）' || echo '（连不上/不存在）')"
  if command -v ss >/dev/null 2>&1; then
    local listeners
    listeners="$(ss -ltnpH 2>/dev/null | grep -E ":${APP_PORT} " || true)"
    printf '  TCP %s 监听 : %s\n' "$APP_PORT" "${listeners:-无}"
  fi
  sec "trm status"
  as_user "$TRM_BIN" status 2>&1 | sed 's/^/  /'
}

smoke() {
  PASS=0; WARN=0; FAIL=0
  sec "冒烟检查（任一 FAIL 就自动回滚）"
  if wait_active; then ok "$UNIT 已 active（重启后 30s 内起得来）"
  else bad "$UNIT 没起来（systemctl status $UNIT / journalctl -u $UNIT）"; dump_context; return 1; fi

  if ! wait_ready; then
    bad "30s 内没就绪：$SOCKET_PATH 连不上（socket 没建出来？路径对不上？）"
    dump_context; return 1
  fi

  # 决定性①：daemon 自报「HTTP 关、IPC 开」，且 pid 与 systemd 对得上
  write_assert_py
  if as_user "$TRM_BIN" --json status > "$WORK_DIR/status.json" 2>"$WORK_DIR/status.err"; then
    if python3 "$ASSERT_PY" "$WORK_DIR/status.json" "$(main_pid)"; then ok "trm --json status：http=false / ipc=true / source=rpc / pid 对得上"
    else bad "trm status 断言不过（见 $WORK_DIR/status.json）"; sed 's/^/     /' "$WORK_DIR/status.err"; fi
  else
    bad "trm --json status 执行失败：$(head -3 "$WORK_DIR/status.err" | tr '\n' ' ')"
  fi

  # 决定性②：不看配置，直接看进程与全机的监听
  local pid ports port
  pid="$(main_pid)"
  if command -v ss >/dev/null 2>&1; then
    if ss -ltnH 2>/dev/null | grep -qE ":${APP_PORT} "; then
      bad "全机仍有进程在听 TCP $APP_PORT（HTTP 没真关掉）"
    else ok "全机在 TCP $APP_PORT 上没有任何监听"; fi
    # 没有监听时 grep 返回 1，pipefail 会让整条替换失败并触发 ERR trap（假报警）——
    # 所以每一段都显式收口。
    ports="$( { ss -ltnpH 2>/dev/null || true; } | { grep "pid=${pid}," || true; } | awk '{print $4}' | tr '\n' ' ')"
    # 只看「是不是 HTTP 端口」——别拿端口号区间猜：workflow event driver 会开一个
    # 内核分配的临时端口（§9.3.8 已记录），那是正常的，不该判 FAIL。
    owned="$(printf '%s' "$ports" | tr ' ' '\n' | { grep -E ':[0-9]+$' || true; } | sed 's/.*://' | sort -u | tr '\n' ' ')"
    printf '     daemon(pid=%s) 的 TCP 监听端口：%s\n' "$pid" "${owned:-无}"
    if printf ' %s ' "$owned" | grep -qE " (${APP_PORT}|$((APP_PORT + 8))) "; then
      bad "daemon 自己还在听 HTTP 端口（$APP_PORT / $((APP_PORT + 8))）：$owned"
    else
      ok "daemon 自己没在听 HTTP 端口（剩下的 ${owned:-无} 是 workflow driver 的临时端口）"
    fi
  else
    warn "没有 ss，跳过端口实测"
  fi

  # 命令面：这些以前 HTTP-only 或依赖 HTTP 的命令必须仍然可用
  local cmd
  for cmd in "tool list" "agent list" "security tokens" "security learning"; do
    if as_user "$TRM_BIN" $cmd >"$WORK_DIR/cmd.out" 2>&1; then ok "trm $cmd 通过"
    else bad "trm $cmd 失败：$(head -2 "$WORK_DIR/cmd.out" | tr '\n' ' ')"; fi
  done
  STEP="冒烟：security learn"
  if as_user timeout 60 "$TRM_BIN" security learn >"$WORK_DIR/learn.out" 2>&1; then
    ok "trm security learn 通过（LLM 未配置时也应当正常返回）"
  else warn "trm security learn 非零退出（看 $WORK_DIR/learn.out，可能是没配 LLM key）"
  fi

  # 日志里不能有 traceback / socket 失败
  if journalctl -u "$UNIT" --since '-3 min' --no-pager 2>/dev/null | grep -qE 'Traceback|socket_start_failed'; then
    bad "最近 3 分钟 journal 里有 Traceback / socket_start_failed"
  else ok "最近 3 分钟 journal 里没有 Traceback / socket_start_failed"; fi

  printf '\n  冒烟小结：PASS=%d WARN=%d FAIL=%d\n' "$PASS" "$WARN" "$FAIL"
  printf '  冒烟小结：PASS=%d WARN=%d FAIL=%d\n' "$PASS" "$WARN" "$FAIL" >> "$EVIDENCE_LOG"
  if [ "$FAIL" -gt 0 ]; then
    printf '  证据：%s\n' "$EVIDENCE_LOG"
    dump_context
  fi
  [ "$FAIL" -eq 0 ]
}

render_dropin() {
  cat > "$1" <<'EOF'
# trimum TCP 收口 —— 由 scripts/switch_ipconly.sh 生成，别手改（重跑脚本即可）
# 作用：这个 daemon 实例只提供 IPC socket，不再监听 TCP（HTTP）。
# 与 config 侧契约一致：config.HTTP_ENV = TRIMUM_HTTP，只认 0/false/no/off 为「关」。
# 回滚：sudo bash scripts/switch_ipconly.sh --rollback（= 删掉本文件 + 重启）
[Service]
Environment=TRIMUM_HTTP=0
EOF
}

do_rollback() {
  sec "回滚：删掉 HTTP 收口 drop-in"
  if [ -f "$DROPIN" ]; then
    rm -f "$DROPIN"
    rmdir "$DROPIN_DIR" 2>/dev/null || true
    echo "  已删除 $DROPIN"
  else
    echo "  $DROPIN 本来就不存在（无需回滚）"
  fi
  systemctl daemon-reload
  systemctl restart "$UNIT"
  if wait_active && wait_ready; then
    echo "  回滚后 $UNIT 已 active 且 socket 就绪"
  else
    echo "  回滚后 $UNIT 仍未就绪，看 journalctl -u $UNIT" >&2
  fi
  echo "  当前 HTTP 状态（应为 enabled）："
  as_user "$TRM_BIN" status 2>&1 | { grep -E '^http:|^ipc socket:|^\[OK\]|^\[OFFLINE\]' || true; } | sed 's/^/    /'
  if command -v ss >/dev/null 2>&1; then
    ss -ltnpH 2>/dev/null | grep -E ":${APP_PORT} " | sed 's/^/    /' || echo "    TCP $APP_PORT：仍无监听（回滚没生效？）"
  fi
}

case "$MODE" in
  check)
    show_state
    sec "前置条件"
    precheck_deploy_tree
    printf '\n  证据文件：%s\n' "$EVIDENCE_LOG"
    exit 0
    ;;
  apply)
    need_root --apply
    sec "切换前的现状"
    show_state
    sec "前置条件（fail-closed：缺一条就不动手）"
    PASS=0; WARN=0; FAIL=0
    precheck_deploy_tree
    if ! socket_live; then bad "IPC socket 现在就连不上（$SOCKET_PATH）—— 先修 socket，别关 HTTP"; fi
    if [ -f "$DROPIN" ]; then warn "drop-in 已存在（重复 --apply？）$DROPIN"; fi
    if [ "$FAIL" -gt 0 ]; then
      echo
      echo "前置不满足，一个字都没改。证据：$EVIDENCE_LOG" >&2
      exit 1
    fi
    ensure_work_dir
    install -d -m 0755 "$DROPIN_DIR"
    render_dropin "$DROPIN"
    echo "  已写入 $DROPIN"
    systemctl daemon-reload
    systemctl restart "$UNIT"
    if smoke; then
      sec "完成"
      echo "  结果：daemon 只跑 IPC socket，不再监听 TCP（HTTP）"
      echo "  证据：$EVIDENCE_LOG"
      echo "  回滚：sudo bash $0 --rollback"
      exit 0
    fi
    echo
    echo "  冒烟 FAIL —— 自动回滚" >&2
    do_rollback
    echo "  已回滚。证据：$EVIDENCE_LOG" >&2
    exit 1
    ;;
  rollback)
    need_root --rollback
    do_rollback
    exit 0
    ;;
esac
