#!/usr/bin/env bash
# accept_ipc_only.sh —— TCP 收口（core.http_enabled=false）的真机验收
#
# 隔离跑法：不碰生产 daemon、不碰 ~/.trimum、不需要 sudo。
#   1) 把 HEAD 的整棵 src 解到 $SRCHEAD（默认 /tmp/ipconly-head/src）：
#        git archive --format=tar HEAD src > /tmp/src.tar
#        python3 -m tarfile -e /tmp/src.tar /tmp/ipconly-head
#      **别只覆盖「本轮改的几个文件」** —— 旧树缺模块会让 daemon 起不来（§9.3.8 发现 2）。
#      远端没有 tar 时，用 python3 -m tarfile 解；tar 本身可用 bsdtar 打。
#   2) bash scripts/accept_ipc_only.sh   （可覆盖 BASE / SRCHEAD / PY）
#
# 15 项断言（逐条 PASS/FAIL），全过退出码 0。真机 2026-09-21：15 PASS / 0 FAIL。
# 证据与两个真发现见 docs/SANDBOX-PLAN.md §9.3.8。
set -u
BASE=${BASE:-/tmp/ipconly}
SRCHEAD=${SRCHEAD:-/tmp/ipconly-head/src}
PY=${PY:-/opt/trimum/venv/bin/python}
PASS=0
FAIL=0
ok(){ echo "  [PASS] $1"; PASS=$((PASS+1)); }
bad(){ echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
cli(){ "$PY" -c "import sys; from trimum_core.cli import main; sys.exit(main($1))"; }
wait_sock(){
  for i in $(seq 1 120); do
    if "$PY" - "$1" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(0.5)
try:
    s.connect(sys.argv[1])
except OSError:
    sys.exit(1)
PY
    then return 0; fi
    if [ -n "$2" ] && ! kill -0 "$2" 2>/dev/null; then return 1; fi
    sleep 0.5
  done
  return 1
}

rm -rf "$BASE"
mkdir -p "$BASE/xdg/trimum" "$BASE/data" "$BASE/run" "$BASE/home"
cp -a "$SRCHEAD" "$BASE/src"

cat > "$BASE/xdg/trimum/config.yaml" <<EOF
core:
  host: "127.0.0.1"
  port: 8329
  socket_path: "$BASE/run/trimum.sock"
  workers: 1
  http_enabled: false
logging:
  level: info
  file: "$BASE/trimum.log"
  format: json
context:
  db_path: "$BASE/context.db"
policy:
  path: "$BASE/policy.yaml"
EOF

# 故意起不来的 socket：HTTP 也关掉，端口换成没人占的 8329（否则先撞端口预检）
cat > "$BASE/bad.yaml" <<EOF
core:
  host: "127.0.0.1"
  port: 8329
  socket_path: "/proc/self/nope/trimum.sock"
  http_enabled: false
logging:
  level: info
  file: "$BASE/trimum-bad.log"
  format: json
context:
  db_path: "$BASE/context-bad.db"
policy:
  path: "$BASE/policy.yaml"
EOF

export XDG_CONFIG_HOME="$BASE/xdg" XDG_DATA_HOME="$BASE/data" XDG_RUNTIME_DIR="$BASE/run"
export TRIMUM_HOME="$BASE/home" TRIMUM_SOCKET="$BASE/run/trimum.sock"
export PYTHONPATH="$BASE/src"

echo "== A. 只走 IPC 的 daemon（core.http_enabled: false，不给任何环境变量）"
"$PY" -m trimum_core.main >"$BASE/daemon.out" 2>&1 &
DPID=$!
if wait_sock "$BASE/run/trimum.sock" "$DPID"; then ok "socket 60s 内可就绪（pid=$DPID）"; else bad "socket 没起来"; tail -8 "$BASE/daemon.out"; fi

echo "== B. trm status 只走 RPC"
cli "['--json','status']" >"$BASE/status.json" 2>"$BASE/status.err"
cat "$BASE/status.json"
if "$PY" - "$BASE/status.json" "$DPID" "$BASE/run/trimum.sock" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("running") is True, "running"
assert d.get("source") == "rpc", ("source", d.get("source"))
assert d.get("socket") == sys.argv[3], ("socket", d.get("socket"))
assert d.get("http") is False, ("http", d.get("http"))
assert d.get("ipc") is True, ("ipc", d.get("ipc"))
assert d.get("pid") == int(sys.argv[2]), ("pid", d.get("pid"))
assert d.get("version"), "version"
PY
then ok "status: running + source=rpc + http=false + ipc=true + pid/socket 对得上自己的 daemon"; else bad "status 断言不过（见 $BASE/status.json / status.err）"; fi

echo "== C. security 三个命令（HTTP 已关，只能走 socket）"
cli "['--json','security','learning']" >"$BASE/learning.json" 2>&1
cli "['--json','security','tokens']" >"$BASE/tokens.json" 2>&1
cli "['--json','security','learn']" >"$BASE/learn.json" 2>&1
cat "$BASE/tokens.json"; cat "$BASE/learn.json"
if "$PY" - "$BASE/learning.json" "$BASE/tokens.json" "$BASE/learn.json" <<'PY'
import json, sys
learning = json.load(open(sys.argv[1]))
tokens = json.load(open(sys.argv[2]))
learn = json.load(open(sys.argv[3]))
assert "summary" in learning and "profiles" in learning, learning
assert "daemon_running" not in learning, learning
assert tokens == {"tokens": []}, tokens
assert learn.get("mode"), learn
assert "summary" in learn and "injected" in learn, learn
PY
then ok "security learning/tokens/learn 三个 RPC 都通"; else bad "security RPC 断言不过"; fi

echo "== D. 只看「本进程」的监听（8321 上跑的是生产 trmd，不算）"
probe_tcp=$(ss -ltnp 2>/dev/null | grep "pid=$DPID," | awk '{print $4}' | tr '\n' ' ')
echo "  本进程 TCP 监听：${probe_tcp:-无}"
if echo "$probe_tcp" | grep -qE ':(8321|8329) '; then bad "本进程在 HTTP 端口上有监听"; else ok "本进程没有 HTTP 监听（只有 driver 的临时端口）"; fi
if ss -ltn 2>/dev/null | grep -q ":8329"; then bad "8329（core.port）被监听"; else ok "8329（core.port）没人监听"; fi
if ss -xl 2>/dev/null | grep -q "$BASE/run/trimum.sock"; then ok "unix socket 在 listen"; else bad "unix socket 不在 listen"; fi

echo "== E. socket 起不来 + 无 HTTP 时必须 exit 3"
timeout 90 "$PY" -m trimum_core.main --config "$BASE/bad.yaml" >"$BASE/fatal.out" 2>&1
rc=$?
if [ "$rc" = 3 ]; then ok "exit 3 对上（EXIT_STARTUP_PRECONDITION）"; else bad "期望 exit 3，实得 $rc"; fi
if grep -q "IPC socket 起不来" "$BASE/fatal.out"; then ok "stderr 是「IPC socket 起不来」这条致命路径"; else bad "stderr 没走致命路径"; fi
head -2 "$BASE/fatal.out" | sed 's/^/  /'

echo "== F. SIGTERM 干净收摊"
sock_before=no
[ -S "$BASE/run/trimum.sock" ] && sock_before=yes
kill -TERM "$DPID" 2>/dev/null
for i in $(seq 1 40); do kill -0 "$DPID" 2>/dev/null || break; sleep 0.5; done
if kill -0 "$DPID" 2>/dev/null; then bad "SIGTERM 后 20s 没退出"; kill -9 "$DPID" 2>/dev/null; else ok "SIGTERM 后正常退出"; fi
[ "$sock_before" = yes ] && ok "退出前 socket 文件在" || bad "退出前 socket 文件就不在"
[ -e "$BASE/run/trimum.sock" ] && bad "socket 文件没被收走" || ok "socket 文件已清理"
grep -q "ipc-only" "$BASE/trimum.log" 2>/dev/null && ok "日志有 mode=ipc-only" || bad "日志没有 mode=ipc-only"
grep -q "trimum_core_stopped" "$BASE/trimum.log" 2>/dev/null && ok "日志有 trimum_core_stopped" || bad "日志没记录停止"

echo "== G. TRIMUM_HTTP=1 把 HTTP 打开（同一份 config，验证可逆）"
TRIMUM_HTTP=1 "$PY" -m trimum_core.main >"$BASE/daemon-http.out" 2>&1 &
GPID=$!
gp_ok=no
for i in $(seq 1 120); do
  if ss -ltn 2>/dev/null | grep -q ":8329"; then gp_ok=yes; break; fi
  kill -0 "$GPID" 2>/dev/null || break
  sleep 0.5
done
[ "$gp_ok" = yes ] && ok "8329 起来了（TRIMUM_HTTP=1 压过 config 的 false）" || { bad "8329 没起来"; tail -5 "$BASE/daemon-http.out"; }
cli "['--json','status']" >"$BASE/status-http.json" 2>&1
"$PY" - "$BASE/status-http.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("  http field:", d.get("http"), "| source:", d.get("source"), "| ipc:", d.get("ipc"))
assert d.get("http") is True, d.get("http")
PY
[ $? = 0 ] && ok "status 报 http=true" || bad "status 没报 http=true"
kill -TERM "$GPID" 2>/dev/null
for i in $(seq 1 40); do kill -0 "$GPID" 2>/dev/null || break; sleep 0.5; done
kill -0 "$GPID" 2>/dev/null && kill -9 "$GPID" 2>/dev/null

echo
echo "==== 汇总：PASS=$PASS FAIL=$FAIL  （工作目录 $BASE）"
[ "$FAIL" = 0 ]