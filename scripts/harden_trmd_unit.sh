#!/usr/bin/env bash
# S1：trmd.service 系统级沙箱加固（drop-in + 冒烟 + 失败自动回滚）
#
# 用法（--apply / --rollback 需要 sudo；dry-run 不需要）：
#   sudo bash /tmp/harden_trmd_unit.sh                       # dry-run：打印将要写入的 drop-in 与逐条理由
#   sudo bash /tmp/harden_trmd_unit.sh --apply               # 备份 → 写 drop-in → daemon-reload → 重启 → 冒烟 → 失败自动回滚
#   sudo bash /tmp/harden_trmd_unit.sh --verify              # 只跑冒烟检查（apply 之后复查）
#   sudo bash /tmp/harden_trmd_unit.sh --rollback            # 还原最近一次备份
#   sudo bash /tmp/harden_trmd_unit.sh --stage /tmp/x.conf   # 只生成 drop-in 到文件（不装）
#   --no-readonly-deploy-tree   不给 /opt/trimum 加只读（若 daemon 要往部署树写东西）
#   --allow-debug               不挡 @debug（放开 ptrace/perf_event_open，gdb/strace/perf 才能跑）
#   --unit <名字>               默认 trmd
#
# 设计口径（逐条理由在生成的 drop-in 注释里）：
#   * ProtectSystem=full 而不是 strict：daemon 要在**任意工作区**写盘，strict 的白名单列不全；
#     full 恰好盖住持久化面（/usr /boot /efi /etc 只读）。工作区粒度的边界交给 S2 的 Landlock。
#   * seccomp 用**黑名单**（~）而不是 @system-service 白名单：systemd 255 的白名单里没有
#     seccomp(2) 与 landlock_*(444/445/446)，用白名单会把 S2/S3 自己要装的沙箱挡在门外。
#   * 不设 PrivateDevices=：它会新建 /dev 而**不带 /dev/shm**，Python multiprocessing / 共享内存会挂。
set -uo pipefail

UNIT=trmd
MODE=dryrun
STAGE_FILE=""
READONLY_DEPLOY=1
ALLOW_DEBUG=0
DEPLOY_ROOT=/opt/trimum
TRM_BIN=/opt/trimum/venv/bin/trm
RUNTIME_NAME=trimum
SOCKET_PATH=/run/trimum/trimum.sock
BACKUP_ROOT=/var/backups/trimum
DROPIN_DIR=""
DROPIN=""

PASS=0; WARN=0; FAIL=0
ok()   { printf '  [PASS] %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  [WARN] %s\n' "$1"; WARN=$((WARN+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }
sec()  { printf '\n== %s\n' "$1"; }

usage() { sed -n '2,20p' "$0"; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) MODE=apply ;;
    --rollback) MODE=rollback ;;
    --verify) MODE=verify ;;
    --stage) MODE=stage; shift || true; STAGE_FILE="${1:-}" ;;
    --stage=*) MODE=stage; STAGE_FILE="${1#--stage=}" ;;
    --no-readonly-deploy-tree) READONLY_DEPLOY=0 ;;
    --allow-debug) ALLOW_DEBUG=1 ;;
    --unit) shift || true; UNIT="${1:-trmd}" ;;
    --unit=*) UNIT="${1#--unit=}" ;;
    -h|--help) usage ;;
    *) echo "未知参数：$1（--help 看用法）" >&2; exit 2 ;;
  esac
  shift
done

DROPIN_DIR="/etc/systemd/system/${UNIT}.service.d"
DROPIN="${DROPIN_DIR}/10-hardening.conf"

need_root() { [ "$(id -u)" -eq 0 ] || { echo "需要 root：sudo bash $0 $*" >&2; exit 1; }; }

# ── 渲染 drop-in ────────────────────────────────────────────────
render_dropin() {
  cat <<EOF
# trimum S1 加固 —— 由 scripts/harden_trmd_unit.sh 生成，别手改（重跑脚本即可）
# 生成时间：$(date -Is)
# 回滚：sudo bash scripts/harden_trmd_unit.sh --rollback
[Service]
# ── 文件系统 ───────────────────────────────────────────────────
# full = /usr /boot /efi **与 /etc** 只读（systemd 文档），挡的是持久化面：
# 写 systemd 单元、改 PAM、塞 cron、换掉已安装的二进制 —— 「恶意高危指令」最想动的地方。
# 刻意不用 strict：strict 把整个文件系统挂成只读，而 daemon 要在任意工作区写盘，
# 白名单列不全（列漏 = 运行时才炸）；工作区粒度的边界交给 S2 的 Landlock（按路径，才是对的工具）。
ProtectSystem=full
# 显式写出来：/home 与 ~/.trimum 必须可写（数据根 + 工作区都在 HOME 下），这里明确放弃「HOME 只读」。
ProtectHome=no
# daemon 的临时文件（tempfile.gettempdir()：skill 导入 / workflow 工作根）关进私有 /tmp + /var/tmp。
PrivateTmp=yes
EOF
  if [ "$READONLY_DEPLOY" -eq 1 ]; then
    printf '# 部署树只读：S1 之后 daemon 不该再往自己的代码目录写东西（pyc 由 PYTHONDONTWRITEBYTECODE 关掉）。\n'
    printf 'ReadOnlyPaths=%s\n' "$DEPLOY_ROOT"
  else
    printf '# ReadOnlyPaths=%s 已按 --no-readonly-deploy-tree 关闭。\n' "$DEPLOY_ROOT"
  fi
  cat <<EOF
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
# 刻意不设 ProtectProc=：trimum 的 process 工具要看同机进程（invisible 会让它瞎）。
LockPersonality=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
KeyringMode=private
# ── 权限与系统调用 ─────────────────────────────────────────────
NoNewPrivileges=yes
CapabilityBoundingSet=
AmbientCapabilities=
SystemCallArchitectures=native
# socket 家族：AF_UNIX 是 IPC 命脉；AF_NETLINK 留给 ip/ss；AF_PACKET / AF_BLUETOOTH / AF_VSOCK 一律不给。
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
# 命名空间一律不许自建（bwrap / rootless 容器本来也被 AppArmor 挡着）。逃生阀：改成 RestrictNamespaces=~user。
RestrictNamespaces=yes
UMask=0022
TasksMax=4096
# seccomp 用**黑名单**（~）：白名单会把 seccomp(2) 与 landlock_*(444/445/446) 一起挡掉
# —— systemd 255 的 @system-service 里没有这三个，而 S2/S3 正是要靠它们装沙箱。
# 被挡的调用返回 EPERM（不是默认的 SIGSYS 杀进程）：工具能自己报错，不会莫名消失。
SystemCallErrorNumber=EPERM
SystemCallFilter=~@clock @module @raw-io @reboot @swap @obsolete @mount @keyring @cpu-emulation
# 故意的例外：@privileged 里的 @chown、setuid/setresuid/setreuid/setgroups、setfsuid **不禁**。
# 理由：daemon 没有 CAP_CHOWN / CAP_SETUID，这些调用对它本来就什么都做不了（越权不可能），
# 禁掉只会给正常工具添堵（cp -a / rsync -a / mv 跨设备 / newgrp 会报 EPERM）。
SystemCallFilter=~acct bpf capset chroot fanotify_init fanotify_mark nfsservctl open_by_handle_at pivot_root quotactl quotactl_fd setdomainname sethostname vhangup
# 跨进程内存与近年的 exploit 面：userfaultfd（经典利用原语）、io_uring、process_vm_*。
SystemCallFilter=~userfaultfd io_uring_setup process_vm_readv process_vm_writev
EOF
  if [ "$ALLOW_DEBUG" -eq 1 ]; then
    printf '# @debug 已按 --allow-debug 放行（ptrace / perf_event_open / pidfd_getfd 可用）。\n'
  else
    cat <<EOF
# @debug：挡 ptrace / perf_event_open / pidfd_getfd —— 跨进程读写别人内存、改寄存器、
# 读性能计数器（「劫持本机其它进程」的两条主路之一）。代价：daemon 派生的 gdb/strace/perf 会失败，
# 要用就带 --allow-debug 重跑本脚本。
SystemCallFilter=~@debug
EOF
  fi
  cat <<EOF
# ── runtime 目录与 IPC socket ──────────────────────────────────
# 真机现状：daemon 的 IPC socket **根本没起来**（默认路径 /run/user/<uid> 下没有文件），
# 客户端一路静默降级成 HTTP，而 HTTP 端口同机任何用户都能连（见 docs/SANDBOX-PLAN.md §6.6）。
# 名字固定为 /run/${RUNTIME_NAME}：客户端 trimum_client.SYSTEM_RUNTIME_SOCKET 认的就是这条路。
RuntimeDirectory=${RUNTIME_NAME}
RuntimeDirectoryMode=0750
Environment=XDG_RUNTIME_DIR=/run/${RUNTIME_NAME}
# ── 环境 ───────────────────────────────────────────────────────
Environment=PYTHONDONTWRITEBYTECODE=1
EOF
}

# ── 冒烟 ────────────────────────────────────────────────────────
unit_user() { systemctl show "$UNIT" -p User --value; }

wait_active() {
  local i
  for i in $(seq 1 30); do
    [ "$(systemctl is-active "$UNIT" 2>/dev/null)" = active ] && return 0
    sleep 1
  done
  return 1
}

smoke() {
  PASS=0; WARN=0; FAIL=0
  sec "冒烟检查（任一 FAIL 就回滚）"
  local u; u="$(unit_user)"
  [ -n "$u" ] || u=root

  if wait_active; then ok "$UNIT 已 active（重启后 30s 内起得来）"
  else bad "$UNIT 没起来（看 systemctl status $UNIT / journalctl -u $UNIT）"; return 1; fi

  local eff; eff="$(systemctl show "$UNIT" -p ProtectSystem --value)"
  if [ "$eff" = full ]; then ok "ProtectSystem=full 已生效"; else bad "ProtectSystem 实际是 '$eff'"; fi
  local scf; scf="$(systemctl show "$UNIT" -p SystemCallFilter --value | tr '\n' ' ')"
  if [ -n "$scf" ]; then ok "SystemCallFilter 已装载"; else bad "SystemCallFilter 是空的（没生效）"; fi
  [ "$(systemctl show "$UNIT" -p NoNewPrivileges --value)" = yes ] && ok "NoNewPrivileges=yes" || bad "NoNewPrivileges 没生效"
  [ "$(systemctl show "$UNIT" -p RestrictNamespaces --value)" = yes ] && ok "RestrictNamespaces=yes" || bad "RestrictNamespaces 没生效"
  [ "$(systemctl show "$UNIT" -p PrivateTmp --value)" = yes ] && ok "PrivateTmp=yes" || bad "PrivateTmp 没生效"
  if [ -z "$(systemctl show "$UNIT" -p CapabilityBoundingSet --value)" ]; then ok "CapabilityBoundingSet 已清空"
  else bad "CapabilityBoundingSet 没清空：$(systemctl show "$UNIT" -p CapabilityBoundingSet --value)"; fi

  # 决定性口径：别只看「配置值」，直接读进程的 /proc（systemd 也会静默降级）
  local pid mi n
  pid="$(systemctl show "$UNIT" -p MainPID --value)"
  if [ -n "$pid" ] && [ "$pid" != 0 ] && [ -r "/proc/$pid/status" ]; then
    if grep -q '^NoNewPrivs:[[:space:]]*1' "/proc/$pid/status"; then ok "进程内实测 NoNewPrivs=1"
    else bad "进程内 NoNewPrivs 不是 1（$(grep -m1 '^NoNewPrivs:' "/proc/$pid/status")）"; fi
    if grep -q '^Seccomp:[[:space:]]*2' "/proc/$pid/status"; then ok "进程内实测 Seccomp=2（过滤器真的装上了）"
    else bad "进程内 Seccomp 不是 2（$(grep -m1 '^Seccomp:' "/proc/$pid/status")）"; fi

    mi="/proc/$pid/mountinfo"
    local mnt
    for mnt in /usr /etc; do
      if awk -v m="$mnt" '$5==m {print $6}' "$mi" | grep -q '^ro'; then ok "$mnt 在 daemon 命名空间里是 ro"
      else bad "$mnt 不是 ro —— 文件系统加固没生效（用户级单元的老问题）"; fi
    done
    if awk '$5=="/home" {print $6}' "$mi" | grep -q '^ro'; then
      bad "/home 被挂成 ro —— 工作区会写不进去（ProtectHome 设错了？）"
    else ok "/home 仍可写（工作区写盘不受影响）"; fi
    n="$(wc -l < "$mi" 2>/dev/null || echo 0)"
    if [ "$n" -gt 50 ]; then ok "mountinfo 条目数=$n（> 宿主的 47：命名空间真的建了）"
    else warn "mountinfo 条目数=$n（与宿主同量级：可能没建命名空间，人工看一眼）"; fi
  else
    warn "读不到 /proc/$pid/status，跳过进程内实测"
  fi

  if [ -S "$SOCKET_PATH" ]; then ok "IPC socket 存在：$SOCKET_PATH"
  else bad "IPC socket 不存在：$SOCKET_PATH（日志里找 unix_socket_start_failed）"; fi

  if [ -x "$TRM_BIN" ]; then
    if runuser -u "$u" -- "$TRM_BIN" status >/tmp/.trm-status.out 2>&1; then
      ok "trm status（用户 $u）通过"
      if grep -q 'daemon running' /tmp/.trm-status.out; then ok "  且报告 daemon running"; else warn "  没看到 daemon running"; fi
      if grep -q 'source: rpc' /tmp/.trm-status.out; then ok "  传输：rpc（socket 通了）"
      else warn "  传输仍是 http —— 客户端改动还没部署到 $DEPLOY_ROOT/src（见 docs/SANDBOX-PLAN.md §6.6）"; fi
    else
      bad "trm status（用户 $u）失败：$(head -3 /tmp/.trm-status.out | tr '\n' ' ')"
    fi
    if runuser -u "$u" -- "$TRM_BIN" tool list >/dev/null 2>&1; then ok "trm tool list 通过"
    else bad "trm tool list 失败"; fi
  else
    warn "找不到 $TRM_BIN，跳过 CLI 冒烟"
  fi

  local probe=/tmp/.probe_sandbox_syscalls.py
  cat > "$probe" <<'PY'
import ctypes, os
libc = ctypes.CDLL("libc.so.6", use_errno=True)
for name, nr in (("landlock_create_ruleset", 444), ("landlock_add_rule", 445),
                 ("landlock_restrict_self", 446), ("seccomp", 317),
                 ("prctl", 157), ("bpf", 321)):
    ctypes.set_errno(0)
    libc.syscall(nr, 0, 0, 0)
    e = ctypes.get_errno()
    print("%s errno=%d %s" % (name, e, os.strerror(e) if e else ""))
PY
  chmod 0644 "$probe"
  local out
  out="$(systemd-run --wait --pipe --quiet -p SystemCallErrorNumber=EPERM \
          -p "SystemCallFilter=~@clock @module @raw-io @reboot @swap @obsolete @mount @keyring @cpu-emulation @debug" \
          -p "SystemCallFilter=~acct bpf capset chroot fanotify_init fanotify_mark nfsservctl open_by_handle_at pivot_root quotactl quotactl_fd setdomainname sethostname vhangup" \
          -p "SystemCallFilter=~userfaultfd io_uring_setup process_vm_readv process_vm_writev" \
          python3 "$probe" 2>&1)"
  printf '%s\n' "$out" | sed 's/^/     /'
  if printf '%s' "$out" | grep -qE '^(landlock_create_ruleset|landlock_add_rule|landlock_restrict_self|seccomp|prctl) errno=1 '; then
    bad "同一个黑名单把 S2/S3 要用的 syscall 挡了（errno=1 EPERM）—— 这正是不能用 @system-service 白名单的原因"
  else
    ok "landlock_* / seccomp / prctl 未被自己的过滤器误伤（S2/S3 前提成立）"
  fi
  if [ "$ALLOW_DEBUG" -eq 0 ]; then
    if printf '%s' "$out" | grep -qE '^(bpf|ptrace|mount) errno=1 '; then ok "该挡的确实挡住了（bpf / ptrace / mount → EPERM）"
    else bad "黑名单没挡住 bpf/ptrace/mount（过滤器没生效）"; fi
  else
    ok "--allow-debug 已放行 @debug（ptrace/perf_event_open 可用，bpf 仍挡）"
  fi

  if journalctl -u "$UNIT" --since '-3 min' --no-pager 2>/dev/null | grep -q 'unix_socket_start_failed'; then
    bad "日志里有 unix_socket_start_failed"
  else
    ok "日志里没有 unix_socket_start_failed"
  fi

  printf '\n  冒烟小结：PASS=%d WARN=%d FAIL=%d\n' "$PASS" "$WARN" "$FAIL"
  [ "$FAIL" -eq 0 ]
}

# ── 备份 / 回滚 ─────────────────────────────────────────────────
latest_backup() { ls -1d "${BACKUP_ROOT}"/harden-* 2>/dev/null | sort | tail -1; }

do_rollback_backup() {
  local b; b="$(latest_backup)"
  if [ -z "$b" ]; then
    echo "没找到备份（${BACKUP_ROOT}/harden-*），改为直接移除 drop-in"
    rm -f "$DROPIN"; rmdir "$DROPIN_DIR" 2>/dev/null
  else
    echo "从 $b 还原"
    if [ -f "$b/10-hardening.conf" ]; then
      install -m 0644 "$b/10-hardening.conf" "$DROPIN"
    else
      rm -f "$DROPIN"; rmdir "$DROPIN_DIR" 2>/dev/null
    fi
  fi
  systemctl daemon-reload
  systemctl restart "$UNIT" || true
  if wait_active; then echo "回滚后 $UNIT 已 active"
  else echo "回滚后 $UNIT 仍未起来，看 journalctl -u $UNIT" >&2; fi
}

# ── 主流程 ──────────────────────────────────────────────────────
case "$MODE" in
  stage)
    [ -n "$STAGE_FILE" ] || { echo "--stage 需要一个文件路径" >&2; exit 2; }
    render_dropin > "$STAGE_FILE"
    echo "已生成：$STAGE_FILE"
    exit 0
    ;;
  verify) smoke; exit $? ;;
  rollback)
    need_root --rollback
    sec "回滚 $UNIT 的 S1 加固"
    do_rollback_backup
    exit 0
    ;;
esac

sec "现状（改之前）"
printf '  单元文件：%s\n' "$(systemctl show "$UNIT" -p FragmentPath --value)"
printf '  用户：%s / 工作目录：%s\n' "$(unit_user)" "$(systemctl show "$UNIT" -p WorkingDirectory --value)"
printf '  现有 drop-in：%s\n' "$(ls -1 "$DROPIN_DIR" 2>/dev/null | tr '\n' ' ')"
printf '  部署树：%s（目标：只读）\n' "$DEPLOY_ROOT"
if [ -S "$SOCKET_PATH" ]; then printf '  IPC socket：%s（现在已存在）\n' "$SOCKET_PATH"
else printf '  IPC socket：%s（现在不存在）\n' "$SOCKET_PATH"; fi
_nowpid="$(systemctl show "$UNIT" -p MainPID --value)"
if [ -n "$_nowpid" ] && [ "$_nowpid" != 0 ] && [ -r "/proc/$_nowpid/mountinfo" ]; then
  printf '  daemon 当前 mountinfo 条目数：%s（宿主基线 47 = 没有命名空间）\n' "$(wc -l < "/proc/$_nowpid/mountinfo")"
fi
if command -v systemd-analyze >/dev/null; then
  printf '  加固评分（改之前）：%s\n' "$(systemd-analyze security "$UNIT" 2>/dev/null | tail -1)"
fi

sec "将要写入的 drop-in：$DROPIN"
render_dropin | sed 's/^/    /'

if [ "$MODE" = dryrun ]; then
  sec "dry-run：什么都没改"
  echo "  真装：       sudo bash $0 --apply"
  echo "  只生成不装： sudo bash $0 --stage /tmp/trmd-10-hardening.conf"
  exit 0
fi

need_root --apply

sec "语法与语义预检（systemd-analyze verify）"
EFF=/tmp/.${UNIT}-effective.service
{ systemctl cat "$UNIT" 2>/dev/null; echo; render_dropin; } > "$EFF"
if systemd-analyze verify "$EFF" > /tmp/.trmd-verify.out 2>&1; then
  ok "verify 通过"
elif grep -qiE 'unknown (lvalue|directive|system call|key)' /tmp/.trmd-verify.out; then
  bad "verify 报错（未知指令或未知 syscall）："; sed 's/^/     /' /tmp/.trmd-verify.out; echo; exit 1
else
  warn "verify 有非致命输出："; sed 's/^/     /' /tmp/.trmd-verify.out | head -10
fi

sec "备份"
TS=$(date +%Y%m%d-%H%M%S)
BK="${BACKUP_ROOT}/harden-${TS}"
mkdir -p "$BK"
systemctl cat "$UNIT" > "$BK/unit-before.txt" 2>&1 || true
if [ -f "$DROPIN" ]; then cp -a "$DROPIN" "$BK/10-hardening.conf"; fi
{
  echo "#!/usr/bin/env bash"
  echo "# 回滚这次加固（${TS}）"
  echo "rm -f '$DROPIN'"
  echo "systemctl daemon-reload"
  echo "systemctl restart $UNIT"
} > "$BK/rollback.sh"
chmod +x "$BK/rollback.sh"
ok "备份到 $BK"

sec "写入 drop-in 并重启"
install -d -m 0755 "$DROPIN_DIR"
render_dropin > "${DROPIN}.tmp" && mv "${DROPIN}.tmp" "$DROPIN"
ok "已写入 $DROPIN"
if systemctl daemon-reload; then ok "daemon-reload 完成"; else bad "daemon-reload 失败"; fi
if systemctl restart "$UNIT"; then ok "已重启 $UNIT"; else bad "restart 失败"; fi

PASS=0; WARN=0; FAIL=0
if smoke; then
  sec "完成"
  if command -v systemd-analyze >/dev/null; then
    printf '  加固评分（改之后）：%s\n' "$(systemd-analyze security "$UNIT" 2>/dev/null | tail -1)"
  fi
  echo "  文档：docs/SANDBOX-PLAN.md §6.6（口径与取舍）/ §8（S1 验收）"
  echo "  回滚： sudo bash $0 --rollback"
  exit 0
else
  sec "冒烟失败 —— 自动回滚"
  do_rollback_backup
  echo >&2
  echo "加固没装上，已回滚到改动前的状态。上面的 FAIL 项就是原因。" >&2
  exit 1
fi
