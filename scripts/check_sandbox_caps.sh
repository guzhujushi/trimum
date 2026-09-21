#!/usr/bin/env bash
# 真机沙箱能力自检（只读，不需要 root，不改任何配置）
# 用法：bash check_sandbox_caps.sh
# 输出：逐项 PASS / WARN / FAIL + 末尾汇总，供 docs/SANDBOX-PLAN.md 的落地前核对
set -u
PASS=0; WARN=0; FAIL=0
ok()   { printf '  [PASS] %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  [WARN] %s\n' "$1"; WARN=$((WARN+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }
sec()  { printf '\n== %s\n' "$1"; }

sec "1. 内核与发行版"
. /etc/os-release; echo "  $PRETTY_NAME / $(uname -r) / $(uname -m)"

sec "2. Landlock"
if grep -q landlock /sys/kernel/security/lsm 2>/dev/null; then ok "landlock 在 LSM 列表：$(cat /sys/kernel/security/lsm)"; else bad "landlock 不在 LSM 列表"; fi
W=$(mktemp -d); cat > "$W/ll.c" <<'EOF'
#include <stdio.h>
#include <errno.h>
#include <unistd.h>
#include <sys/syscall.h>
#ifndef SYS_landlock_create_ruleset
#define SYS_landlock_create_ruleset 444
#endif
#define LANDLOCK_CREATE_RULESET_VERSION (1U << 0)
int main(void){ errno=0; long r=syscall(SYS_landlock_create_ruleset,(void*)0,(size_t)0,LANDLOCK_CREATE_RULESET_VERSION); if(r<0){printf("ERR %d\n",errno);return 1;} printf("%ld\n",r); return 0; }
EOF
if command -v gcc >/dev/null && gcc -O0 -o "$W/ll" "$W/ll.c" 2>/dev/null; then
  ABI=$("$W/ll" 2>/dev/null || echo ERR)
  case "$ABI" in
    1) warn "LANDLOCK_ABI=1（仅文件读/写/执行，无 TRUNCATE/REFER/IOCTL_DEV）" ;;
    2|3) warn "LANDLOCK_ABI=$ABI（有 REFER/TRUNCATE，无 IOCTL_DEV 与网络域）" ;;
    4) ok "LANDLOCK_ABI=4（含 TRUNCATE / REFER / TRUNCATE_DIR / IOCTL_DEV）" ;;
    5|6|7) ok "LANDLOCK_ABI=$ABI" ;;
    *) bad "无法探测 Landlock ABI（$ABI）" ;;
  esac
else
  warn "无 gcc，跳过 ABI 探测（装 build-essential 后可测）"
fi
rm -rf "$W"

sec "3. seccomp"
if [ -r /proc/sys/kernel/seccomp/actions_avail ]; then
  A=$(cat /proc/sys/kernel/seccomp/actions_avail)
  ok "actions_avail: $A"
  case "$A" in *user_notif*) ok "支持 SECCOMP_RET_USER_NOTIF（可做用户态代理/审计）" ;; *) warn "无 user_notif" ;; esac
  case "$A" in *kill_process*) ok "支持 SECCOMP_RET_KILL_PROCESS" ;; *) warn "无 kill_process" ;; esac
else bad "读不到 actions_avail"; fi
python3 - <<'EOF' 2>/dev/null
import ctypes, ctypes.util
p = ctypes.util.find_library("seccomp")
if not p:
    print("  [WARN] 找不到 libseccomp（Python 侧需改用裸 BPF 或 prctl）"); raise SystemExit
lib = ctypes.CDLL(p)
class V(ctypes.Structure): _fields_=[("major",ctypes.c_uint),("minor",ctypes.c_uint),("micro",ctypes.c_uint)]
lib.seccomp_version.restype = ctypes.POINTER(V)
v = lib.seccomp_version().contents
print(f"  [PASS] libseccomp {v.major}.{v.minor}.{v.micro} 可被 ctypes 加载（{p}）")
EOF

sec "4. namespace（非特权）"
printf '  user ns: '; if unshare --user --map-root-user true 2>/dev/null; then ok "可用"; else warn "被拒（Ubuntu 24.04 默认 AppArmor 限制）"; fi
printf '  mount ns: '; if unshare --mount true 2>/dev/null; then ok "可用"; else warn "被拒（非特权下正常）"; fi
printf '  net ns:   '; if unshare --net true 2>/dev/null; then ok "可用"; else warn "被拒（非特权下正常）"; fi
printf '  apparmor_restrict_unprivileged_userns=%s\n' "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo '?')"
printf '  unprivileged_userns_clone=%s\n' "$(cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null || echo '?')"
if command -v bwrap >/dev/null; then
  if timeout 10 bwrap --ro-bind / / /bin/true 2>/dev/null; then ok "bwrap 非特权可用"; else warn "bwrap 非特权被拒（uid map permission denied）"; fi
else warn "未装 bwrap"; fi

sec "5. cgroup v2"
T=$(stat -fc %T /sys/fs/cgroup 2>/dev/null || echo "?")
[ "$T" = "cgroup2fs" ] && ok "cgroup2 已挂载" || warn "cgroup 挂载类型=$T（非 v2 统一层级）"
echo "  控制器: $(cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null || echo '?')"
echo "  用户 slice 委派控制器: $(cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/cgroup.controllers 2>/dev/null || echo '不可读')"
if mkdir "/sys/fs/cgroup/trm-probe-$$" 2>/dev/null; then rmdir "/sys/fs/cgroup/trm-probe-$$"; ok "能直接写 /sys/fs/cgroup"; else warn "不能直接写 /sys/fs/cgroup（需 root；可改走 systemd 用户级）"; fi

sec "6. systemd 用户级沙箱（非特权可用）"
if timeout 15 systemd-run --user -p ProtectSystem=strict -p NoNewPrivileges=yes -p PrivateTmp=yes -p SystemCallFilter=@system-service /bin/true >/dev/null 2>&1; then
  ok "systemd-run --user 可用：ProtectSystem/NoNewPrivileges/PrivateTmp/SystemCallFilter"
else warn "systemd-run --user 不可用（检查 user manager）"; fi
if timeout 15 systemd-run --user -p MemoryMax=256M -p CPUQuota=50% /bin/true >/dev/null 2>&1; then ok "systemd-run --user 的 cgroup 限额（MemoryMax/CPUQuota）可用"; else warn "用户级 cgroup 限额不可用"; fi
echo "  systemd 版本: $(systemctl --version | head -1)"

sec "7. 容器运行时（可选路线）"
for c in docker podman runc crun bwrap nsjail runsc firecracker; do printf '  %-12s %s\n' "$c" "$(command -v "$c" || echo '（无）')"; done
if command -v docker >/dev/null; then
  echo "  docker 服务: $(systemctl is-active docker 2>/dev/null)"
  echo "  docker 安全项: $(docker info 2>/dev/null | grep -iE 'seccomp|apparmor|rootless|cgroupns' | tr -s ' ' | tr '\n' ';')"
  echo "  本地镜像数: $(( $(docker images -q 2>/dev/null | wc -l) ))"
fi

sec "8. eBPF / 观测"
echo "  unprivileged_bpf_disabled=$(cat /proc/sys/kernel/unprivileged_bpf_disabled 2>/dev/null || echo '?')  （2 = 非特权完全禁用 BPF）"
echo "  perf_event_paranoid=$(cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null || echo '?')"
echo "  BTF: $(ls /sys/kernel/btf/vmlinux 2>/dev/null || echo '（无）')"
for t in bpftrace bpftool perf strace clang; do printf '  %-10s %s\n' "$t" "$(command -v "$t" || echo '（无）')"; done
if [ "$(id -u)" -ne 0 ] && [ "$(cat /proc/sys/kernel/unprivileged_bpf_disabled 2>/dev/null || echo 2)" = "2" ]; then
  warn "非特权下 eBPF 不可用 → 走 eBPF 的监控必须提权（root 单元或带 CAP_BPF 的 helper）"
fi

sec "9. 结论"
printf '  PASS=%d  WARN=%d  FAIL=%d\n' "$PASS" "$WARN" "$FAIL"
echo "  内核级主干（Landlock + seccomp + systemd 用户级 + cgroup v2）在非特权下可落地；"
echo "  受影响的是：非特权 user namespace（bwrap/rootless 容器）与 eBPF 监控 —— 见 docs/SANDBOX-PLAN.md。"