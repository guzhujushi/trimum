#!/usr/bin/env bash
# 系统级（root）沙箱能力核对 —— 只读，不写任何业务文件
# 用法：sudo bash /tmp/check_sandbox_caps_root.sh
# 目的：回答「daemon 保持非特权够不够，还是需要一个特权 helper」
set -u
PASS=0; WARN=0; FAIL=0
ok(){ printf '  [PASS] %s\n' "$1"; PASS=$((PASS+1)); }
warn(){ printf '  [WARN] %s\n' "$1"; WARN=$((WARN+1)); }
bad(){ printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }
sec(){ printf '\n== %s\n' "$1"; }

if [ "$(id -u)" -ne 0 ]; then echo "需要 root：sudo bash $0" >&2; exit 1; fi

sec "1. 宿主挂载现状（对照基线）"
printf '  /usr : %s\n' "$(findmnt -no FSTYPE,OPTIONS /usr 2>/dev/null | head -1)"
printf '  /etc : %s\n' "$(findmnt -no FSTYPE,OPTIONS /etc 2>/dev/null | head -1 || echo '（/etc 非独立挂载）')"
printf '  /home: %s\n' "$(findmnt -no FSTYPE,OPTIONS /home 2>/dev/null | head -1 || echo '（/home 非独立挂载）')"
printf '  /tmp : %s\n' "$(findmnt -no FSTYPE,SOURCE /tmp 2>/dev/null | head -1)"

sec "2. 系统级 systemd-run 的沙箱指令是否真的生效"
OUT=$(systemd-run --wait --pipe --quiet \
  -p ProtectSystem=strict -p ProtectHome=read-only -p PrivateTmp=yes \
  -p NoNewPrivileges=yes -p SystemCallFilter=@system-service \
  -p ProtectProc=invisible -p PrivateDevices=yes \
  -p RestrictAddressFamilies="AF_UNIX AF_INET" -p MemoryMax=268435456 -p CPUQuota=50% \
  /bin/sh -c 'echo "-- /usr : $(findmnt -no FSTYPE,OPTIONS /usr | head -1)";
              echo "-- /home: $(findmnt -no FSTYPE,OPTIONS /home 2>/dev/null | head -1)";
              echo "-- /tmp : $(findmnt -no FSTYPE,SOURCE /tmp | head -1)";
              echo "-- NoNewPrivs: $(grep -m1 NoNewPrivs /proc/self/status)";
              echo "-- Seccomp: $(grep -m1 Seccomp /proc/self/status)";
              echo "-- memory.max: $(cat /sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup)/memory.max 2>/dev/null)";
              touch /etc/trm-probe-root 2>&1 | head -1; echo "-- write /etc rc=$?";
              touch /home/guzhujushi/.trm-probe-root 2>&1 | head -1; echo "-- write \$HOME rc=$?"' 2>&1)
printf '%s\n' "$OUT" | sed 's/^/  /'
case "$OUT" in
  *"ro"*usr*|*usr*ro*) ok "ProtectSystem=strict 生效（/usr 变 ro）" ;;
  *) warn "ProtectSystem 未观察到 ro（看上面输出判断）" ;;
esac
case "$OUT" in *"write /etc rc=1"*) ok "ProtectSystem 拦住 /etc 写" ;; *) warn "未拦住 /etc 写（结合输出判断）" ;; esac
case "$OUT" in *"-- /home: tmpfs"*|*"-- /home: "*ro*) ok "ProtectHome=read-only 生效" ;; *) warn "ProtectHome 未观察到生效" ;; esac
case "$OUT" in *"Seccomp:"*2*) ok "SystemCallFilter 生效（Seccomp mode 2）" ;; *) warn "SystemCallFilter 未观察到生效" ;; esac

sec "3. cgroup v2 直写（root 前提下）"
if mkdir -p /sys/fs/cgroup/trm-probe-root 2>/dev/null; then
  rmdir /sys/fs/cgroup/trm-probe-root; ok "root 可在 /sys/fs/cgroup 建目录（cgroup 直控可用）"
else bad "root 也建不了 cgroup 目录（检查 cgroup2 挂载）"; fi

sec "4. eBPF（非特权下被禁，root 下应可用）"
printf '  unprivileged_bpf_disabled=%s\n' "$(cat /proc/sys/kernel/unprivileged_bpf_disabled)"
if command -v bpftrace >/dev/null; then
  if timeout 20 bpftrace -e 'BEGIN { printf("bpftrace ok\n"); exit(); }' >/dev/null 2>&1; then ok "bpftrace 在 root 下可用"; else warn "bpftrace 失败（看内核/BPF 配置）"; fi
else warn "未装 bpftrace"; fi

sec "5. AppArmor 与用户命名空间"
printf '  apparmor_restrict_unprivileged_userns=%s\n' "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo '?')"
aa-status --count 2>/dev/null && ok "aa-status 可读（root）" || warn "aa-status 不可读"
printf '  /etc/subuid: %s\n' "$(grep -c . /etc/subuid 2>/dev/null || echo '（无文件）')"
printf '  /etc/subgid: %s\n' "$(grep -c . /etc/subgid 2>/dev/null || echo '（无文件）')"
if command -v bwrap >/dev/null; then
  if timeout 10 bwrap --ro-bind / / --dev /dev /bin/true 2>/dev/null; then ok "root 下 bwrap 可用"; else warn "root 下 bwrap 仍失败"; fi
fi

sec "6. Docker（若走容器路线）"
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  ok "docker 可用：$(docker version --format '{{.Server.Version}}' 2>/dev/null)"
  echo "     本地镜像数: $(docker images -q 2>/dev/null | wc -l)（为 0 时用容器需先拉镜像）"
  echo "     默认 seccomp/apparmor 由 docker 自带 profile 提供（docker info 已列 apparmor/seccomp/cgroupns）"
else warn "docker 不可用或未运行"; fi

sec "7. 结论"
printf '  PASS=%d  WARN=%d  FAIL=%d\n' "$PASS" "$WARN" "$FAIL"
echo "  系统级单元能拿到用户级拿不到的文件系统隔离；用户级已经能拿到 cgroup 限额 + seccomp + NoNewPrivileges。"
echo "  eBPF 监控只能在 root（或带 CAP_BPF 的 helper）下工作。"