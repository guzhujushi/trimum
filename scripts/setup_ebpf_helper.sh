#!/usr/bin/env bash
# trimum eBPF 特权 helper 的部署件：装 / 自检 / 回滚（默认 dry-run，不碰任何东西）
#
# 用法（--apply / --rollback 需要 sudo；dry-run 与 --self-check 不需要 root，非 root 自检会如实报 SKIP）：
#   sudo bash scripts/setup_ebpf_helper.sh                 # dry-run（默认）：只打印将要做什么
#   sudo bash scripts/setup_ebpf_helper.sh --apply         # 装：备份 → 建目录/manifest → 装单元 → daemon-reload → enable --now → 冒烟 → 失败自动回滚
#   sudo bash scripts/setup_ebpf_helper.sh --self-check    # 只做自检（**非 root 也能跑**，缺权限的那几条如实报 SKIP/FAIL 并给出需要 root 的原因）
#   sudo bash scripts/setup_ebpf_helper.sh --rollback      # 卸干净（只删登记过的路径）
#
# 口径（与 scripts/harden_trmd_unit.sh 同风格：dry-run / --apply / --rollback + ERR trap + 失败自动回滚）：
#   * 本单**不写 eBPF 加载本身**：loader 是 UnavailableLoader，bpf.stats 会**如实**回
#     available:false（reason=loader_not_implemented）。真 loader + eBPF C 程序是下一单 ebpf1e。
#     冒烟 / 自检看到 available:false 是**正确**表现，不是失败。
#   * 红线：--rollback **只删 MANAGED / MANAGED_DIRS 里登记过的路径**，删别的（哪怕看起来是 trimum 的）一律拒绝。
#   * 不许静默降级：装不上 / 冒烟失败 ⇒ 回滚并 exit 非 0，绝不「装一半说成功」。
set -euo pipefail

UNIT=trimum-bpf-helper
MODE=dryrun
DEPLOY_ROOT=/opt/trimum
VENV_PY=/opt/trimum/venv/bin/python
SRC_MAIN="${DEPLOY_ROOT}/src/trimum_core/bpf_helper_main.py"
UNIT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../deploy/trimum-bpf-helper.service"

# 本次会碰的**全部**文件 / socket 路径（--rollback 只删这些；红线：删别的一律拒绝）。
MANAGED=(
  "/opt/trimum/bpf"
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

PASS=0; FAIL=0; SKIP=0
ok()   { printf '  [OK]   %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }
skip() { printf '  [SKIP] %s —— %s\n' "$1" "$2"; SKIP=$((SKIP+1)); }

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
  "$VENV_PY" - "$verb" <<'PY' 2>/dev/null || true
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
  echo "    2) 建 /opt/trimum/bpf（放 eBPF 产物，下一单 ebpf1e）+ 空 manifest /etc/trimum/bpf-manifest.txt"
  echo "    3) 装单元 /etc/systemd/system/${UNIT}.service（模板：deploy/trimum-bpf-helper.service）"
  echo "    4) systemctl daemon-reload && systemctl enable --now ${UNIT}"
  echo "    5) 冒烟：active + socket mode 0660 + root 发 bpf.stats 必须 peer_denied；失败自动回滚"
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

# ---- apply ----
LAST_STEP="backup"
install -d -m 0755 "$BK"
for p in "${MANAGED[@]}"; do backup_path "$p"; done
echo "  备份目录：$BK（本次会碰的路径都在 MANAGED / MANAGED_DIRS 里登记）"

LAST_STEP="mkdir+manifest"
install -d -m 0755 /opt/trimum/bpf
if [ ! -f /etc/trimum/bpf-manifest.txt ]; then
  install -d -m 0755 /etc/trimum
  : > /etc/trimum/bpf-manifest.txt
  chmod 0644 /etc/trimum/bpf-manifest.txt
  echo "  建空 manifest /etc/trimum/bpf-manifest.txt（下一单 ebpf1e 填 sha256）"
fi
ok "建目录 /opt/trimum/bpf + manifest 就位"

LAST_STEP="install-unit"
install -m 0644 "$UNIT_SRC" /etc/systemd/system/${UNIT}.service
ok "已装单元 /etc/systemd/system/${UNIT}.service"

LAST_STEP="daemon-reload"
if systemctl daemon-reload; then ok "systemd daemon-reload"
else bad "systemd daemon-reload"; echo "  → 冒烟/重载失败，自动回滚" >&2; do_rollback; exit 1; fi

LAST_STEP="enable-now"
if systemctl enable --now "$UNIT"; then ok "systemctl enable --now ${UNIT}"
else bad "enable --now ${UNIT}"; echo "  → 单元没起来，自动回滚" >&2; do_rollback; exit 1; fi

# 给 unit 一点时间把 socket bind 出来（enable --now 返回时可能还在起）。
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -S "$SOCK" ] && break
  sleep 1
done

LAST_STEP="smoke"
if do_smoke; then
  echo
  echo "== 装好 =="
  echo "  bpf.stats 现在会**如实**回 available:false（真 loader 未实现，ebpf1e 才换）——这是正确表现。"
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
