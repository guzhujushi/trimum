#!/usr/bin/env bash
# trimum eBPF 特权 helper 的部署件：装 / 自检 / 回滚（默认 dry-run，不碰任何东西）
#
# 用法（--apply / --rollback 需要 sudo；dry-run 与 --self-check 不需要 root，非 root 自检会如实报 SKIP）：
#   sudo bash scripts/setup_ebpf_helper.sh                 # dry-run（默认，同 --dry-run）：只打印将要做什么
#   sudo bash scripts/setup_ebpf_helper.sh --dry-run       # 同上（显式写法；默认就是它）
#   sudo bash scripts/setup_ebpf_helper.sh --apply         # 装：备份 → clang 构建 eBPF 产物 + 清单 → 装单元 → daemon-reload → enable --now → restart → 冒烟 → 失败自动回滚
#   sudo bash scripts/setup_ebpf_helper.sh --self-check    # 只做自检（**非 root 也能跑**，缺权限的那几条如实报 SKIP/FAIL 并给出需要 root 的原因）
#   sudo bash scripts/setup_ebpf_helper.sh --rollback      # 卸干净（只删登记过的路径）
#
# 口径（与 scripts/harden_trmd_unit.sh 同风格：dry-run / --apply / --rollback + ERR trap + 失败自动回滚）：
#   * eBPF 产物**不入库**（仓库里只放源码 bpf/*.bpf.c + trimum_bpf.h）：--apply 现场用 clang
#     编 /opt/trimum/bpf/*.bpf.o（root:root 0444）并把 sha256 写进 /etc/trimum/bpf-manifest.txt；
#     helper 侧 loader（src/trimum_core/bpf_loader.py）装载前逐字节校验 sha256。
#     自检看 `bpf.stats` 回 available:true 是**正确**表现（真 loader 已装；没加载任何程序时 programs 为空）。
#   * 红线：--rollback **只删 MANAGED / MANAGED_DIRS 里登记过的路径**，删别的（哪怕看起来是 trimum 的）一律拒绝。
#   * 不许静默降级：装不上 / 冒烟失败 ⇒ 回滚并 exit 非 0，绝不「装一半说成功」。
#
# 客户端组（2026-10-06 真机实测的坑，别删）：
#   单元的 capability 只有 CAP_BPF / CAP_PERFMON，**没有 CAP_DAC_OVERRIDE / CAP_DAC_READ_SEARCH**
#   ⇒ uid 0 也一样守文件权限位。于是单元必须 `Group=<客户端组>`：① 否则 /opt/trimum（drwxr-x--- 客户端用户:组）
#   连 helper 自己的代码都 import 不了（实测 ModuleNotFoundError → 反复重启 → is-active=activating、socket 不出现）；
#   ② RuntimeDirectory 与 priv.sock 也随之成 root:<客户端组>，非 root 的 daemon 才连得上。
#   组不写死：按 trmd.service 的 User= 推导；可用 TRIMUM_BPF_CLIENT_USER / TRIMUM_BPF_CLIENT_GROUP 覆盖。
#   装前有 DAC 预检（dac_preflight），读不到就在碰系统之前 exit 1。
set -euo pipefail

UNIT=trimum-bpf-helper
MODE=dryrun
# 部署根：显式 env > 默认（换机器 / 测试里指向合成树时用 TRIMUM_BPF_DEPLOY_ROOT 覆盖）。
DEPLOY_ROOT="${TRIMUM_BPF_DEPLOY_ROOT:-/opt/trimum}"
VENV_PY="${DEPLOY_ROOT}/venv/bin/python"
SRC_MAIN="${DEPLOY_ROOT}/src/trimum_core/bpf_helper_main.py"
UNIT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../deploy/trimum-bpf-helper.service"
# eBPF 程序**源码**目录（仓库里只放源码；.o 是构建产物，gitignore 掉了）。
# 默认＝脚本同级的 ../bpf（即仓库里的 bpf/）；可用 TRIMUM_BPF_SRC_DIR 覆盖。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BPF_SRC_DIR="${TRIMUM_BPF_SRC_DIR:-${REPO_DIR}/bpf}"

# 本次会碰的**全部**文件 / socket 路径（--rollback 只删这些；红线：删别的一律拒绝）。
MANAGED=(
  "${DEPLOY_ROOT}/bpf"
  "/etc/trimum/bpf-manifest.txt"
  "/etc/systemd/system/trimum-bpf-helper.service"
  "/run/trimum/priv.sock"
)

# 本次会建的**目录**（--rollback 对目录**只用 rmdir，仅当空**；非空一律不删、也不递归删）。
MANAGED_DIRS=(
  "/etc/trimum"
)

BACKUP_ROOT=/var/backups/trimum
TS="$(date -u +%Y%m%d-%H%M%S)"
BK="${BACKUP_ROOT}/ebpf-${TS}"
SOCK=/run/trimum/priv.sock
SOCK_DIR=/run/trimum
LAST_STEP="(未开始)"

# 客户端（发动词的那一方）＝ trmd.service 的 User。理由见 deploy/trimum-bpf-helper.service 顶部：
# 单元的 capability 集里没有 CAP_DAC_OVERRIDE / CAP_DAC_READ_SEARCH ⇒ **uid 0 也守 DAC 权限位**，
# helper 必须以「客户端组」身份跑：① 才读得到 /opt/trimum（helper 自己代码在这儿）；② /run/trimum 与
# priv.sock 才会是 root:<客户端组>，非 root 的 daemon 才连得上。组名不写死在本脚本 / 单元里，按机器推导。
CLIENT_USER="${TRIMUM_BPF_CLIENT_USER:-$(systemctl show trmd -p User --value 2>/dev/null || true)}"
CLIENT_GROUP="${TRIMUM_BPF_CLIENT_GROUP:-}"
if [ -z "$CLIENT_GROUP" ] && [ -n "$CLIENT_USER" ]; then
  CLIENT_GROUP="$(id -gn "$CLIENT_USER" 2>/dev/null || true)"
fi
# 单元里的占位**注释**行（必须是注释：这样 `systemd-analyze verify` 直接验模板仍是合法单元）。
UNIT_GROUP_MARKER="# TRIMUM_UNIT_GROUP_PLACEHOLDER"

PASS=0; FAIL=0; SKIP=0
ok()   { printf '  [OK]   %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }
skip() { printf '  [SKIP] %s —— %s\n' "$1" "$2"; SKIP=$((SKIP+1)); }

# 端到端失败的**归属诊断**（ASCII：这台机的控制台没有中文字形，apply_ebpf1e.sh 的 print_fail_lines
# 还会把非 ASCII 字节换成 '?'，只有 ASCII 才过得去）。命中时给出「为什么」+「怎么修」。
# 背景（2026-10-08 真机定案）：Ubuntu 内核带 CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y ⇒ 只要
# kernel.perf_event_paranoid >= 4（Ubuntu 默认），libbpf 挂 tracepoint 用的 perf_event_open(2)
# 就**强制 CAP_SYS_ADMIN**；helper 按设计只给 CAP_BPF+CAP_PERFMON ⇒ EACCES / "Permission denied"。
perf_gate_hint() {
  local paranoid config
  # 两个路径也可覆盖（同 apply_ebpf1e.sh 的口径）：/boot/config-* 在某些机器上读不到，测试也需要注入。
  paranoid="$(tr -dc '0-9' <"${TRIMUM_BPF_PARANOID_FILE:-/proc/sys/kernel/perf_event_paranoid}" 2>/dev/null || true)"
  [ -n "$paranoid" ] && [ "$paranoid" -ge 4 ] || return 0
  config="${TRIMUM_BPF_KERNEL_CONFIG:-/boot/config-$(uname -r)}"
  grep -qs '^CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y' "$config" || return 0
  printf ' -- LIKELY CAUSE: perf_event_open needs CAP_SYS_ADMIN here (CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y + kernel.perf_event_paranoid=%s) but the helper only holds CAP_BPF+CAP_PERFMON; fix: sudo bash scripts/apply_ebpf1e.sh --apply (step 0 sets kernel.perf_event_paranoid<=3)' "$paranoid"
}

# helper 的 DAC 视角检查：helper = **uid 0** + gid $3，cap 集里没有 CAP_DAC_OVERRIDE / CAP_DAC_READ_SEARCH
# ⇒ **全按权限位算**（uid 0 没有豁免）。逐段判 $1：中间段要 x（目录也要 x）；末段是文件则要 r。
# 命中哪一类只认两条（红线，2026-10-06 验收抓的错）：
#   `属主 == root`（uid 0 才是 owner 类）→ u 位；`属组 == 客户端组` → g 位；其余 → o 位。
#   **别把「属主 == 客户端用户」当 owner 类**：helper 不是那个 uid，那样会把这个检查变成恒真。
# 可读返回 0；不可读返回 1 并打印卡点（$2 只用于报错文案）。
dac_readable() { # <path> <client_user> <client_group>
  local path="$1" cu="$2" cg="$3" cur="" seg meta owner group oct d parts i n
  IFS='/' read -r -a parts <<< "${path#/}"
  n=${#parts[@]}; i=0
  for seg in "${parts[@]}"; do
    i=$((i + 1)); cur="$cur/$seg"
    if ! meta="$(stat -c '%U %G %a' "$cur" 2>/dev/null)"; then
      printf '  卡点：%s（不存在或读不到）\n' "$cur" >&2; return 1
    fi
    read -r owner group oct <<< "$meta"
    oct="${oct: -3}"            # 去掉 setuid/setgid/sticky 位；剩下三位八进制数字本身就是位掩码（r=4 w=2 x=1）
    if [ "$owner" = root ]; then d="${oct:0:1}"
    elif [ "$group" = "$cg" ]; then d="${oct:1:1}"
    else d="${oct:2:1}"; fi
    d=$((10#$d))
    if [ "$i" -lt "$n" ] || [ -d "$cur" ]; then
      if [ $((d & 1)) -eq 0 ]; then
        printf '  卡点：%s（mode %s，属主 %s:%s；helper 是 uid 0 + 组 %s，该类无 x 就穿不过去）\n' "$cur" "$oct" "$owner" "$group" "$cg" >&2
        return 1
      fi
    elif [ $((d & 4)) -eq 0 ]; then
      printf '  卡点：%s（mode %s，属主 %s:%s；helper 是 uid 0 + 组 %s，该类无 r 就读不到）\n' "$cur" "$oct" "$owner" "$group" "$cg" >&2
      return 1
    fi
  done
  return 0
}

# helper 从 exec 到「能 import 自己的代码」要穿过的路径（含 editable 安装的 .pth；python 版本号不钉死）。
dac_preflight() { # <client_user> <client_group>
  local cu="$1" cg="$2" p f sp rc=0
  local paths=(
    "$DEPLOY_ROOT" "$DEPLOY_ROOT/src" "$DEPLOY_ROOT/src/trimum_core" "$SRC_MAIN"
    "$DEPLOY_ROOT/venv" "$DEPLOY_ROOT/venv/bin" "$VENV_PY"
  )
  for sp in "$DEPLOY_ROOT"/venv/lib/python3*/site-packages; do
    [ -d "$sp" ] || continue
    paths+=("$sp")
    for f in "$sp"/*.pth; do [ -e "$f" ] && paths+=("$f"); done
  done
  for p in "${paths[@]}"; do
    dac_readable "$p" "$cu" "$cg" || { rc=1; break; }   # 首个卡点就停，别刷屏
  done
  return "$rc"
}

usage() { sed -n '2,12p' "$0"; exit 0; }

err_trap() {
  local code=$?
  echo >&2
  echo "[ERR] 退出码=${code}  最后一步=${LAST_STEP}  行号=${BASH_LINENO[0]:-?}" >&2
  echo "[ERR] 若 --apply 中途失败：已尝试自动回滚；手工回滚 sudo bash scripts/setup_ebpf_helper.sh --rollback" >&2
}
trap err_trap ERR

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) MODE=dryrun ;;
    --apply) MODE=apply ;;
    --self-check) MODE=selfcheck ;;
    --rollback) MODE=rollback ;;
    -h|--help) usage ;;
    *) echo "未知参数：$1（--help 看用法）" >&2; exit 2 ;;
  esac
  shift
done

is_root() { [ "$(id -u)" -eq 0 ]; }
need_root() { is_root || { echo "需要 root：sudo bash $0 $1" >&2; exit 1; }; }

# 取 socket mode（八进制），文件不存在/读不了返回空。
sock_mode() { stat -c '%a' "$SOCK" 2>/dev/null || true; }

# 以调用者 uid 发一条 verb 请求，打印应答里 "error":"..." 的值（拿不到就打印原始行）。
send_priv() {
  local verb="$1"
  # 第二个实参是 socket 路径：显式当 argv[2] 传进去（脚本里的取法是
  # `sys.argv[2] if len(sys.argv) > 2 else 默认`）。之前这个实参被悄悄忽略、一直走默认值 ——
  # 路径碰巧相同才没暴露；显式传递后换 TRIMUM_BPF_SOCKET / $SOCK 就不会各说各话。
  "$VENV_PY" - "$verb" "${2:-$SOCK}" <<'PY' 2>/dev/null || true
import json, socket, sys
import trimum_core.bpf_helper_protocol as P
verb = sys.argv[1]
req = json.dumps({"verb": verb}).encode()
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(sys.argv[2] if len(sys.argv) > 2 else "/run/trimum/priv.sock")
    s.sendall(req)
    data = s.recv(65536)
except Exception as e:
    print("ERR", e)
    sys.exit(0)
finally:
    s.close()
try:
    r = P.parse_response(data)
except Exception:
    print(data.decode("utf-8", "replace").strip())
    sys.exit(0)
print(r.get("error") or ("OK data=" + json.dumps(r.get("data"), ensure_ascii=False)))
PY
}

# 自检：逐项打印 OK/FAIL/SKIP + 证据。非 root 会如实报 SKIP（并说明需要 root 的原因）。
# 退出码契约：有 FAIL ⇒ 返回非 0；无 FAIL（全 OK/SKIP）⇒ 返回 0。
do_selfcheck() {
  LAST_STEP="self-check"
  echo "== 自检 ${UNIT} =="
  echo "   （非 root 也能跑；缺权限/缺单元的那几条会如实报 SKIP/FAIL 并给出原因）"

  # 1. 单元 active
  if is_root; then
    local st; st="$(systemctl is-active "$UNIT" 2>/dev/null || true)"
    if [ "$st" = "active" ]; then ok "单元 active（systemctl is-active=${st}）"
    else bad "单元 active（systemctl is-active=${st:-<无>}；需 sudo ... --apply 装好）"; fi
  else
    skip "单元 active" "需 root 读 systemd 状态；非 root 跑不了，装好后用 sudo 复查"
  fi

  # 2. CapabilityBoundingSet 只有两枚
  if [ -r "/etc/systemd/system/${UNIT}.service" ]; then
    local caps; caps="$(grep -E '^CapabilityBoundingSet=' /etc/systemd/system/${UNIT}.service | head -1 | sed 's/^CapabilityBoundingSet=//')"
    if [ "$caps" = "CAP_BPF CAP_PERFMON" ]; then
      ok "CapabilityBoundingSet 只有两枚（${caps}）"
    else
      bad "CapabilityBoundingSet 只有两枚（实际：${caps:-<无>}；期望 CAP_BPF CAP_PERFMON）"
    fi
  elif is_root; then
    bad "CapabilityBoundingSet 只有两枚（单元文件不存在：/etc/systemd/system/${UNIT}.service）"
  else
    skip "CapabilityBoundingSet 只有两枚" "需 root 读单元文件 /etc/systemd/system/trimum-bpf-helper.service；非 root 读不到"
  fi

  # 2b. 单元必须给 XDG_CONFIG_HOME（ProtectHome=yes 下 /root 不可达 ⇒ uid 0 的 ~/.config 读不到还会抛 EACCES）
  if [ -r "/etc/systemd/system/${UNIT}.service" ]; then
    local xdg; xdg="$(grep -E '^Environment=XDG_CONFIG_HOME=' "/etc/systemd/system/${UNIT}.service" | head -1 | sed 's/^Environment=XDG_CONFIG_HOME=//')"
    if [ -n "$xdg" ]; then
      ok "单元给了 XDG_CONFIG_HOME=${xdg}（helper 的系统级配置放 ${xdg}/trimum/config.yaml）"
    else
      bad "单元给了 XDG_CONFIG_HOME（缺这行 ⇒ ProtectHome=yes 下 /root 不可达，Config() 抛 EACCES → crash-loop）"
    fi
  elif is_root; then
    bad "单元给了 XDG_CONFIG_HOME（单元文件不存在：/etc/systemd/system/${UNIT}.service）"
  else
    skip "单元给了 XDG_CONFIG_HOME" "需 root 读单元文件 /etc/systemd/system/${UNIT}.service；非 root 读不到"
  fi

  # 3. NoNewPrivs 与 Seccomp（读运行中进程的 /proc/Pid/status）
  if is_root; then
    local pid; pid="$(systemctl show "$UNIT" -p MainPID --value 2>/dev/null || true)"
    if [ -n "$pid" ] && [ "$pid" != "0" ] && [ -r "/proc/${pid}/status" ]; then
      local nnp secc; nnp="$(awk '/^NoNewPrivs:/{print $2}' /proc/${pid}/status)"; secc="$(awk '/^Seccomp:/{print $2}' /proc/${pid}/status)"
      if [ "$nnp" = "1" ] && [ "$secc" = "2" ]; then
        ok "NoNewPrivs=1 且 Seccomp=2（filter 已装；MainPID=${pid}）"
      else
        bad "NoNewPrivs/Seccomp（NoNewPrivs=${nnp:-?} 期望 1；Seccomp=${secc:-?} 期望 2；MainPID=${pid}）"
      fi
    else
      bad "NoNewPrivs 与 Seccomp（主进程不在，取不到 /proc/Pid/status；MainPID=${pid:-<无>}）"
    fi
  else
    skip "NoNewPrivs 与 Seccomp" "需 root 读运行中进程的 /proc/Pid/status"
  fi

  # 4. socket 存在且 mode 0660
  if [ -S "$SOCK" ]; then
    local m; m="$(sock_mode)"
    if [ "$m" = "660" ]; then ok "socket 存在且 mode=0660（${SOCK}）"
    else bad "socket 存在且 mode=0660（${SOCK} mode=${m:-?}，期望 660）"; fi
  else
    if is_root; then
      bad "socket 存在（${SOCK} 不存在；单元没起来？journalctl -u ${UNIT}）"
    else
      skip "socket 存在与 mode" "需 root 看 ${SOCK_DIR}（RuntimeDirectory 0750，非 root 进不去）"
    fi
  fi

  # 5/6/7/8 走 socket 发请求：先判断能不能连（连不上就如实报，不假装）
  local canconn=0
  if [ -S "$SOCK" ] && [ "$(id -un)" = "root" ]; then canconn=1; fi
  # 说明：协议是「先过 uid 门，未授权直接 peer_denied、不给解析反馈」。
  # 因此 peer_denied 的 root 能证明 socket 活着 + uid 门在起作用；
  # bad_verb / unknown_field 只有在「发送方 uid 被允许」时才会回（root 不在默认允许 uid 里）。

  if [ "$canconn" -eq 1 ]; then
    # 5. bpf.stats：若 root 被拒→如实报 peer_denied（说明 uid 门生效）；否则应回 available:false
    local r5; r5="$(send_priv bpf.stats "$SOCK")"
    if [ "$r5" = "peer_denied" ]; then
      ok "bpf.stats：root 被拒 peer_denied（uid 门在起作用；可用 uid 发则回 available:false）"
    elif printf '%s' "$r5" | grep -q 'available'; then
      if printf '%s' "$r5" | grep -q 'False'; then ok "bpf.stats 回 available:false（真 loader 未装时的正确表现）"
      else bad "bpf.stats 回 available:true（**不许假装在监控**；loader 不该报可用）"; fi
    else
      bad "bpf.stats 应答异常（实际：${r5:-<空>}；期望 peer_denied 或 available:false）"
    fi
    # 6. bpf.exec 应被拒 bad_verb（需允许 uid 才走到解析层；root 会被 peer_denied 抢先）
    local r6; r6="$(send_priv bpf.exec "$SOCK")"
    if [ "$r6" = "bad_verb" ]; then ok "bpf.exec 被拒 bad_verb（允许 uid 发送）"
    elif [ "$r6" = "peer_denied" ]; then skip "bpf.exec 被拒 bad_verb" "发送方（root）先被 peer_denied，未走到动词校验；用允许 uid 才回 bad_verb"
    else bad "bpf.exec 被拒 bad_verb（实际：${r6:-<空>}）"; fi
    # 7. 多一个 cmd 键应被拒 unknown_field（同上，需允许 uid）
    r6="$(send_priv_with_extra_cmd "$SOCK")"
    if [ "$r6" = "unknown_field" ]; then ok "多一个 cmd 键被拒 unknown_field（允许 uid 发送）"
    elif [ "$r6" = "peer_denied" ]; then skip "多一个 cmd 键被拒 unknown_field" "发送方（root）先被 peer_denied；用允许 uid 才回 unknown_field"
    else bad "多一个 cmd 键被拒 unknown_field（实际：${r6:-<空>}）"; fi
    # 8. root 被拒 peer_denied（默认允许 uid 里没有 root）——这是本单要如实证明的一条
    local r8; r8="$(send_priv bpf.stats "$SOCK")"
    if [ "$r8" = "peer_denied" ]; then ok "root 被拒 peer_denied（默认允许 uid 里没有 root，uid 门真的在起作用）"
    else bad "root 被拒 peer_denied（实际：${r8:-<空>}；root 不该被放行）"; fi
  else
    skip "bpf.stats 打印 available:false" "需 root 且 socket 存在才能连（协议先过 uid 门，root 不在默认允许 uid 里）"
    skip "bpf.exec 被拒 bad_verb" "同上：需允许 uid 连 socket 才走到动词校验"
    skip "多一个 cmd 键被拒 unknown_field" "同上：需允许 uid 连 socket 才走到字段校验"
    skip "root 被拒 peer_denied" "需 root 且 socket 存在；装好后用 root 发 bpf.stats 应回 peer_denied"
  fi

  # 9. 部署树对 helper 可读（真机真因：丢 CAP_DAC_* 后 uid 0 也守权限位；纯 stat，非 root 也能查）
  if [ -n "$CLIENT_GROUP" ] && [ -d "$DEPLOY_ROOT" ]; then
    if dac_preflight "$CLIENT_USER" "$CLIENT_GROUP" 2>/dev/null; then
      ok "部署树对 helper 可读（uid 0 + 组 ${CLIENT_GROUP} 能穿过 ${DEPLOY_ROOT} 到 bpf_helper_main.py）"
    else
      bad "部署树对 helper 可读（组 ${CLIENT_GROUP} 读不到；卡点如下）"
      dac_preflight "$CLIENT_USER" "$CLIENT_GROUP" >&2 || true
      echo "  → 修：sudo chgrp ${CLIENT_GROUP} ${DEPLOY_ROOT} && sudo chmod g+rx ${DEPLOY_ROOT}（或 sudo chmod o+x ${DEPLOY_ROOT}）" >&2
    fi
  else
    skip "部署树对 helper 可读" "取不到客户端组（systemctl show trmd -p User / id -gn 都没结果）或 ${DEPLOY_ROOT} 不在本机"
  fi

  # 10. 非 root 客户端能连上 socket 并拿到**协议应答**（证明 /run/trimum 与 priv.sock 的组/位对；root 才能 runuser）
  if [ "$canconn" -eq 1 ] && [ -n "$CLIENT_USER" ]; then
    local r10; r10="$(send_priv_as "$CLIENT_USER" bpf.stats)"
    case "$r10" in
      peer_denied) ok "客户端（${CLIENT_USER}）能连 socket 并拿到应答 peer_denied —— 权限面对；该 uid 不在允许列表（生产要配 security.bpf_helper_allowed_uids）" ;;
      *available*) ok "客户端（${CLIENT_USER}）能连 socket 并拿到 bpf.stats 应答（${r10}）" ;;
      "")          bad "客户端（${CLIENT_USER}）连 socket 拿不到应答（空）—— 权限面不通或单元没起来" ;;
      ERR*)        bad "客户端（${CLIENT_USER}）连 socket 失败（实际：${r10}）" ;;
      *)           bad "客户端（${CLIENT_USER}）应答异常（实际：${r10}）" ;;
    esac
  else
    skip "非 root 客户端连 socket" "需 root 且 socket 存在（以 ${CLIENT_USER:-<客户端用户>} 身份发 bpf.stats）"
  fi

  # 11. eBPF 产物 + 清单逐条对齐（纯静态检查，非 root 也能跑：/etc 清单 0644、/opt/trimum/bpf 0755）
  local obj_glob=("${DEPLOY_ROOT}"/bpf/*.bpf.o)
  if [ -e "${obj_glob[0]}" ] && [ -s /etc/trimum/bpf-manifest.txt ]; then
    local obj_count name digest actual bad_count
    obj_count="${#obj_glob[@]}"
    bad_count=0
    while read -r name digest; do
      [ -n "$name" ] || continue
      actual="$(sha256sum "${DEPLOY_ROOT}/bpf/${name}.bpf.o" 2>/dev/null | awk '{print $1}')"
      if [ "$actual" != "$digest" ]; then
        bad_count=$((bad_count+1))
        bad "清单与产物不一致：${name}（manifest=${digest:0:12}… actual=${actual:0:12}…）"
      fi
    done < /etc/trimum/bpf-manifest.txt
    if [ "$bad_count" -eq 0 ]; then
      ok "eBPF 产物与清单一致（${obj_count} 个 .o，sha256 逐条对齐）"
    fi
  else
    skip "eBPF 产物与清单" "没有 ${DEPLOY_ROOT}/bpf/*.bpf.o 或清单为空；跑 sudo bash $0 --apply 会 clang 现场构建"
  fi

  # 12. 端到端：以客户端身份 bpf.load → 内核**真的**挂上了（要客户端 uid 在允许列表里，否则跳过）
  if [ "$canconn" -eq 1 ] && [ -n "$CLIENT_USER" ]; then
    local r12
    r12="$(send_priv_as "$CLIENT_USER" bpf.load bpf_guard)"
    case "$r12" in
      *"OK data="*)
        ok "端到端 bpf.load bpf_guard 成功（客户端 uid 已放行，程序真的加载进内核）"
        local r12b; r12b="$(send_priv_as "$CLIENT_USER" bpf.unload bpf_guard)"
        case "$r12b" in
          *"OK data="*) ok "端到端 bpf.unload bpf_guard 成功" ;;
          *) bad "端到端 bpf.unload 应答异常（实际：${r12b:-<空>}）" ;;
        esac ;;
      peer_denied)
        skip "端到端 bpf.load" "客户端 uid（${CLIENT_USER}）不在允许列表：写 /etc/trimum/config.yaml 的 security.bpf_helper_allowed_uids: [$(id -u "$CLIENT_USER" 2>/dev/null || echo '<uid>')]，再跑 --self-check" ;;
      *hash_mismatch*)
        bad "端到端 bpf.load：sha256 不匹配（产物与清单不同源；重跑 --apply）" ;;
      *unknown_program*)
        bad "端到端 bpf.load：清单里没有该程序（重跑 --apply）" ;;
      "")
        bad "端到端 bpf.load 拿不到应答（空：权限面不通 / 单元没起来）" ;;
      ERR*)
        bad "端到端 bpf.load 连接失败（实际：${r12}）" ;;
      *)
        bad "端到端 bpf.load 失败（实际：${r12}）—— 看 journalctl -u ${UNIT} 里 libbpf 的报错（seccomp 过滤器 / capability / 内核 BTF）$(perf_gate_hint)" ;;
    esac
  else
    skip "端到端 bpf.load" "需 root 且 socket 存在（以 ${CLIENT_USER:-<客户端用户>} 身份真加载一次）"
  fi

  echo
  printf '  小结：OK=%d  FAIL=%d  SKIP=%d\n' "$PASS" "$FAIL" "$SKIP"
  if [ "$FAIL" -eq 0 ]; then
    return 0
  fi
  echo "  自检失败：FAIL=${FAIL} 项（详见上面的 [FAIL] 行）" >&2
  return 1
}

# 发一条「多一个 cmd 键」的 bpf.stats，取 error 值（多用于 unknown_field 用例）。
send_priv_with_extra_cmd() {
  local sock="$1"
  "$VENV_PY" - "$sock" <<'PY' 2>/dev/null || true
import json, socket, sys
import trimum_core.bpf_helper_protocol as P
req = json.dumps({"verb": "bpf.stats", "cmd": "ls"}).encode()
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(sys.argv[1])
    s.sendall(req)
    data = s.recv(65536)
except Exception as e:
    print("ERR", e); sys.exit(0)
finally:
    s.close()
try:
    r = P.parse_response(data)
except Exception:
    print(data.decode("utf-8", "replace").strip()); sys.exit(0)
print(r.get("error") or ("OK data=" + json.dumps(r.get("data"), ensure_ascii=False)))
PY
}

# 以指定**非 root 客户端**身份发一条 verb（root 才能 runuser）：证明「目录/socket 权限面」对非 root 是通的。
# 带可选 program（bpf.load / bpf.unload 要）。拿得到协议应答（peer_denied / OK data=… / 错误码）就算通；
# ERR 或空 ⇒ 权限面不通（EACCES / ENOENT）。
send_priv_as() { # <user> <verb> [program]
  # `$3`（program）是**可选**的：bpf.stats / bpf.tail 不带 program，调用点只给两个实参。
  # 裸写 `$3` 在 `set -u` 下会当场报「未绑定的变量」并**整条 runuser 命令都不执行** ——
  # 2026-10-08 真机冒烟就是这么把「非 root 客户端能不能连上」判成 FAIL 的（脚本本身是好的，
  # 命令根本没跑）。所以必须写 `${3:-}`，空串由下面的 `if program:` 兜住。
  runuser -u "$1" -- "$VENV_PY" - "$2" "${3:-}" "$SOCK" <<'PY' 2>/dev/null || true
import json, socket, sys
import trimum_core.bpf_helper_protocol as P
verb, program, sock = sys.argv[1], sys.argv[2], sys.argv[3]
body = {"verb": verb}
if program:
    body["program"] = program
req = json.dumps(body).encode()
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(sock)
    s.sendall(req)
    data = s.recv(65536)
except Exception as e:
    print("ERR", e)
    sys.exit(0)
finally:
    s.close()
try:
    r = P.parse_response(data)
except Exception:
    print(data.decode("utf-8", "replace").strip())
    sys.exit(0)
print(r.get("error") or ("OK data=" + json.dumps(r.get("data"), ensure_ascii=False)))
PY
}

# 备份已存在的同名件到 $BK（目录不存在就先建）。
backup_path() {
  local p="$1"
  [ -e "$p" ] || return 0
  local rel; rel="$(echo "$p" | sed 's#/#__#g')"
  install -d -m 0755 "$BK"
  cp -a "$p" "$BK/${rel}" 2>/dev/null || cp -a "$p" "${BK}/${rel}.copy" 2>/dev/null || true
  echo "  备份：$p → $BK"
}

# 冒烟：单元 active + socket mode 0660 + root 发 bpf.stats 必须被拒 peer_denied（证明 uid 门在起作用）。
do_smoke() {
  LAST_STEP="smoke"
  echo "== 冒烟 =="
  local st; st="$(systemctl is-active "$UNIT" 2>/dev/null || true)"
  if [ "$st" = "active" ]; then ok "systemctl is-active=${st}"
  else bad "单元 active（systemctl is-active=${st:-<无>}）"; fi
  if [ -S "$SOCK" ]; then
    local m; m="$(sock_mode)"
    if [ "$m" = "660" ]; then ok "socket 存在且 mode=0660（${SOCK}）"
    else bad "socket mode（${SOCK} mode=${m:-?}，期望 660）"; fi
  else
    bad "socket 存在（${SOCK} 不存在）"
  fi
  local r; r="$(send_priv bpf.stats "$SOCK")"
  if [ "$r" = "peer_denied" ]; then
    ok "root 发 bpf.stats 被拒 peer_denied（uid 门真的在起作用；默认允许 uid 里没有 root）"
  else
    bad "root 发 bpf.stats 应被拒 peer_denied（实际：${r:-<空>}；**root 不该被放行**）"
  fi
  # socket 属组＝客户端组（丢了这条，非 root 的 daemon 连不上：RuntimeDirectory 会把组写进目录与 socket）
  if [ -S "$SOCK" ] && [ -n "$CLIENT_GROUP" ]; then
    local sg; sg="$(stat -c '%G' "$SOCK" 2>/dev/null || true)"
    if [ "$sg" = "$CLIENT_GROUP" ]; then ok "socket 属组=客户端组（${sg}）"
    else bad "socket 属组（实际 ${sg:-?}，期望 ${CLIENT_GROUP}；单元是不是没插 Group=？）"; fi
  fi
  # 非 root 客户端真发一条：拿得到协议应答才算「权限面通了」（EACCES/ENOENT 会走 ERR 分支）
  if [ -S "$SOCK" ] && [ -n "$CLIENT_USER" ]; then
    local rc; rc="$(send_priv_as "$CLIENT_USER" bpf.stats)"
    case "$rc" in
      peer_denied) ok "客户端（${CLIENT_USER}）能连 socket 并拿到应答 peer_denied" ;;
      *available*) ok "客户端（${CLIENT_USER}）能连 socket 并拿到 bpf.stats 应答（${rc}）" ;;
      "")          bad "客户端（${CLIENT_USER}）连 socket 拿不到应答（空）" ;;
      ERR*)        bad "客户端（${CLIENT_USER}）连 socket 失败（实际：${rc}）" ;;
      *)           bad "客户端（${CLIENT_USER}）应答异常（实际：${rc}）" ;;
    esac
  fi
  [ "$FAIL" -eq 0 ]
}

# 回滚：卸干净，**只删 MANAGED / MANAGED_DIRS 里登记过的路径**（红线：删别的拒绝）。
do_rollback() {
  LAST_STEP="rollback"
  need_root --rollback
  echo "== 回滚 ${UNIT} =="
  # 卸载前先停 + 取消开机自启（单元不在也没关系，|| true 兜住）。
  systemctl disable --now "$UNIT" 2>/dev/null || true
  ok "systemctl disable --now ${UNIT}（单元不在也会安全返回）"
  # 逐个删 MANAGED 文件/socket（只删这些；其它路径碰都不碰）。目录归 MANAGED_DIRS 单独处理。
  local p
  for p in "${MANAGED[@]}"; do
    if [ -d "$p" ]; then
      # MANAGED 里若出现目录（如 /opt/trimum/bpf）：一律 rmdir（仅当空），非空/含内容不删、不递归。
      if rmdir "$p" 2>/dev/null; then
        ok "已删空目录（MANAGED）：$p"
      else
        echo "  跳过（非空或删不动，不递归删）：$p"
      fi
    elif [ -e "$p" ] || [ -S "$p" ]; then
      rm -f "$p"
      ok "已删（MANAGED）：$p"
    else
      echo "  跳过（不存在）：$p"
    fi
  done
  # 目录单独走：只对 MANAGED_DIRS 里登记过的用 rmdir（**仅当空**）；非空一律不删、也不递归删。
  local d
  for d in "${MANAGED_DIRS[@]}"; do
    if [ -d "$d" ]; then
      if [ -z "$(ls -A "$d" 2>/dev/null)" ]; then
        if rmdir "$d" 2>/dev/null; then ok "已删空目录（MANAGED_DIRS）：$d"
        else echo "  跳过（删不动）：$d"; fi
      else
        echo "  跳过（非空，不删、不递归删）：$d"
      fi
    fi
  done
  systemctl daemon-reload 2>/dev/null || true
  ok "systemd daemon-reload"
  echo "  回滚完成。只删了 MANAGED / MANAGED_DIRS 登记过的路径，没碰别的。"
}

# ── 主流程 ─────────────────────────────────────────────────────
case "$MODE" in
  selfcheck)
    # 自检的退出码契约：有 FAIL ⇒ 非 0；无 FAIL（全 OK/SKIP）⇒ 0。用 if 兜住 set -e。
    if do_selfcheck; then
      exit 0
    else
      echo "自检失败：FAIL=${FAIL} 项" >&2
      exit 1
    fi
    ;;
  rollback)
    do_rollback
    exit 0
    ;;
esac

# dry-run：在**任何**需要 root / 需要源文件的校验之前无条件 exit 0（对齐 harden_trmd_unit.sh 风格）。
# 源文件还没同步到 /opt/trimum 也不影响 dry-run 的退出码，只如实打一句提示。
if [ "$MODE" = dryrun ]; then
  echo "== dry-run：什么都没改 =="
  if [ ! -f "$SRC_MAIN" ]; then
    echo "  （注意：${SRC_MAIN} 下还未同步 bpf_helper_main.py，真装前需先同步——不影响本次 dry-run 退出码）"
  fi
  echo "  将要做的（--apply 才真跑）："
  echo "    1) 备份已存在的同名件 → ${BACKUP_ROOT}/ebpf-<UTC 时间戳>/"
  for p in "${MANAGED[@]}"; do
    if [ -e "$p" ] || [ -S "$p" ]; then echo "       - 备份已存在：$p"; else echo "       - 新建：$p"; fi
  done
  echo "    2) clang 现场构建 eBPF 产物（源码在 ${BPF_SRC_DIR}）→ 装 /opt/trimum/bpf/*.bpf.o（root:root 0444）"
  echo "       + 写 /etc/trimum/bpf-manifest.txt（每行「程序名  sha256」，root:root 0644）"
  echo "    3) 装单元 /etc/systemd/system/${UNIT}.service（模板 deploy/trimum-bpf-helper.service；把占位注释换成 Group=${CLIENT_GROUP:-<取不到！>}）"
  echo "    4) systemctl daemon-reload && systemctl enable --now ${UNIT} && systemctl restart ${UNIT}"
  echo "    5) 冒烟：active + socket 0660 且属组=${CLIENT_GROUP:-?}（客户端组）+ root 发 bpf.stats 必须 peer_denied"
  echo "       + 非 root 客户端能连上拿到协议应答；失败自动回滚"
  echo "    6) helper 的系统级配置在 /etc/trimum/config.yaml（单元里 XDG_CONFIG_HOME=/etc；ProtectHome=yes 下不能用 /root/.config）"
  echo "       要放行客户端 uid，就在那文件里写：security.bpf_helper_allowed_uids: [<uid>]（缺文件=空集=fail-closed）"
  echo "  客户端组：按 trmd.service 的 User= 推导（CLIENT_USER=${CLIENT_USER:-<取不到>}）；"
  echo "           可用 TRIMUM_BPF_CLIENT_USER=<用户> / TRIMUM_BPF_CLIENT_GROUP=<组> 覆盖。"
  if [ -n "$CLIENT_GROUP" ] && [ -d "$DEPLOY_ROOT" ]; then
    if dac_preflight "$CLIENT_USER" "$CLIENT_GROUP" 2>/dev/null; then
      echo "  [预检] 部署树对 helper 可读：OK（uid 0 + 组 ${CLIENT_GROUP}）"
    else
      echo "  [预检] 部署树对 helper 可读：**--apply 会失败**（组 ${CLIENT_GROUP} 读不到）；卡点："
      { dac_preflight "$CLIENT_USER" "$CLIENT_GROUP" 2>&1 || true; } | sed 's/^/           /'
      echo "         → 先修：sudo chgrp ${CLIENT_GROUP} ${DEPLOY_ROOT} && sudo chmod g+rx ${DEPLOY_ROOT}"
    fi
  else
    echo "  [预检] 部署树对 helper 可读：跳过（取不到客户端组或 ${DEPLOY_ROOT} 不在本机）"
  fi
  echo "  只看自检：  sudo bash scripts/setup_ebpf_helper.sh --self-check"
  echo "  真装：      sudo bash scripts/setup_ebpf_helper.sh --apply"
  echo "  卸干净：    sudo bash scripts/setup_ebpf_helper.sh --rollback"
  exit 0
fi

# ---- apply / rollback 才需要 root；--self-check 已在上面 return，dry-run 也已 exit ----
need_root --apply

# 校验源文件在场（干不了活就早退，不假装能装）。放在 need_root **之后**（先报「需要 root」再报「缺源」）。
if [ ! -f "$SRC_MAIN" ]; then
  echo "缺 ${SRC_MAIN}：先同步源码到 /opt/trimum 再装" >&2; exit 1
fi
if [ ! -f "$UNIT_SRC" ]; then
  echo "缺单元模板 ${UNIT_SRC}" >&2; exit 1
fi

# 硬前提（真机实测踩过）：单元的 capability 集里没有 CAP_DAC_OVERRIDE / CAP_DAC_READ_SEARCH ⇒ uid 0 也守
# DAC 权限位。先证明「helper 的身份真读得到自己那份代码」，不满足就**早退**，别装出一个 crash-loop 的单元
# （实测表现：is-active 一直 activating、socket 永不出现、自检三连 FAIL 再自动回滚）。
LAST_STEP="dac-preflight"
if [ -z "$CLIENT_GROUP" ]; then
  echo "取不到客户端组：systemctl show trmd -p User / id -gn 都没结果（现在 CLIENT_USER='${CLIENT_USER:-<空>}'）" >&2
  echo "  → 显式指定：TRIMUM_BPF_CLIENT_USER=<用户> 或 TRIMUM_BPF_CLIENT_GROUP=<组> 再跑 --apply" >&2
  exit 1
fi
if dac_preflight "$CLIENT_USER" "$CLIENT_GROUP"; then
  ok "部署树对 helper 可读（uid 0 + 组 ${CLIENT_GROUP}）"
else
  bad "部署树对 helper 可读（组 ${CLIENT_GROUP} 读不到；卡点见上）"
  echo "  → 修：sudo chgrp ${CLIENT_GROUP} ${DEPLOY_ROOT} && sudo chmod g+rx ${DEPLOY_ROOT}（或 sudo chmod o+x ${DEPLOY_ROOT}）" >&2
  exit 1
fi

# ---- apply ----
LAST_STEP="backup"
install -d -m 0755 "$BK"
for p in "${MANAGED[@]}"; do backup_path "$p"; done
echo "  备份目录：$BK（本次会碰的路径都在 MANAGED / MANAGED_DIRS 里登记）"

LAST_STEP="build-bpf"
# 真机现场 clang 编译（仓库里**只放源码**，.o 是构建产物、不入库）⇒ 产物与源码永远同源。
if [ ! -f "${BPF_SRC_DIR}/bpf_guard.bpf.c" ] || [ ! -f "${BPF_SRC_DIR}/exec_guard.bpf.c" ]; then
  echo "  缺 eBPF 源码：${BPF_SRC_DIR}/bpf_guard.bpf.c（TRIMUM_BPF_SRC_DIR 可覆盖）" >&2
  echo "  → 本脚本要在**仓库**里跑（bpf/ 与 scripts/ 同级）：sudo bash ~/trimum/scripts/setup_ebpf_helper.sh --apply" >&2
  exit 1
fi
if [ ! -f "${SCRIPT_DIR}/build_bpf.sh" ]; then
  echo "  缺构建脚本：${SCRIPT_DIR}/build_bpf.sh" >&2; exit 1
fi
install -d -m 0755 "${DEPLOY_ROOT}/bpf"
install -d -m 0755 /etc/trimum
rm -f "${DEPLOY_ROOT}"/bpf/*.bpf.o
if bash "${SCRIPT_DIR}/build_bpf.sh" --out-dir "${DEPLOY_ROOT}/bpf" \
        --manifest /etc/trimum/bpf-manifest.txt 2>&1 | sed 's/^/    /'; then
  :
else
  bad "clang 构建 eBPF 产物失败（见上面 build_bpf.sh 的输出）"
  echo "  → 自检工具链：bash scripts/build_bpf.sh --check" >&2
  exit 1
fi
chown root:root "${DEPLOY_ROOT}"/bpf/*.bpf.o
chmod 0444 "${DEPLOY_ROOT}"/bpf/*.bpf.o
chown root:root /etc/trimum/bpf-manifest.txt
chmod 0644 /etc/trimum/bpf-manifest.txt
ok "已装 eBPF 产物（root:root 0444）+ 清单 /etc/trimum/bpf-manifest.txt（sha256 逐条登记）"

LAST_STEP="install-unit"
RENDERED="${BK}/trimum-bpf-helper.service.rendered"
if ! grep -qF "$UNIT_GROUP_MARKER" "$UNIT_SRC"; then
  echo "单元模板缺占位注释「${UNIT_GROUP_MARKER}」：${UNIT_SRC}" >&2; exit 1
fi
sed "s|^${UNIT_GROUP_MARKER}\$|Group=${CLIENT_GROUP}|" "$UNIT_SRC" > "$RENDERED"
if ! grep -qx "Group=${CLIENT_GROUP}" "$RENDERED"; then
  echo "渲染后的单元里没有 Group=${CLIENT_GROUP}（占位替换没生效）：${RENDERED}" >&2; exit 1
fi
install -m 0644 "$RENDERED" /etc/systemd/system/${UNIT}.service
ok "已装单元 /etc/systemd/system/${UNIT}.service（Group=${CLIENT_GROUP}；渲染件留存：${RENDERED}）"

LAST_STEP="daemon-reload"
if systemctl daemon-reload; then ok "systemd daemon-reload"
else bad "systemd daemon-reload"; echo "  → 冒烟/重载失败，自动回滚" >&2; do_rollback; exit 1; fi

LAST_STEP="enable-now"
if systemctl enable --now "$UNIT"; then ok "systemctl enable --now ${UNIT}"
else bad "enable --now ${UNIT}"; echo "  → 单元没起来，自动回滚" >&2; do_rollback; exit 1; fi

# 重启一次：`enable --now` 对**已在跑**的单元是空操作，不重启就还是旧代码 / 旧产物。
LAST_STEP="restart"
if systemctl restart "$UNIT"; then ok "systemctl restart ${UNIT}（换上新代码 + 新产物）"
else bad "restart ${UNIT}"; echo "  → 单元重启失败，自动回滚" >&2; do_rollback; exit 1; fi

# 给 unit 一点时间把 socket bind 出来（enable --now 返回时可能还在起）。
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -S "$SOCK" ] && break
  sleep 1
done

LAST_STEP="smoke"
if do_smoke; then
  echo
  echo "== 装好 =="
  echo "  bpf.stats 现在回 available:true（真 loader 已装；未加载任何程序时 programs 为空）——这是正确表现。"
  echo "  放行客户端：写 /etc/trimum/config.yaml"
  echo "    security:"
  echo "      bpf_helper_allowed_uids: [$(id -u "${CLIENT_USER:-root}" 2>/dev/null || echo '<客户端 uid>')]     # ${CLIENT_USER:-<客户端用户>}"
  echo "  （现在为空集，所有对端都会被拒 —— fail-closed，不是故障）"
  echo "  自检：  sudo bash scripts/setup_ebpf_helper.sh --self-check"
  echo "  回滚：  sudo bash scripts/setup_ebpf_helper.sh --rollback"
  exit 0
else
  echo
  echo "冒烟失败 —— 自动回滚（没装一半说成功）" >&2
  do_rollback
  echo "原因见上面的 FAIL 项；看 journalctl -u ${UNIT}" >&2
  exit 1
fi
