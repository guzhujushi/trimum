#!/usr/bin/env bash
# trimum ebpf1e -- ONE script for the three sudo steps that put the real eBPF loader online.
#
# Why this wrapper exists: the three steps are a fixed sequence (config -> deploy tree -> install), and
# step 1 is easy to get wrong by hand. The real host had a hand-written /etc/trimum/config.yaml whose line
# `bpf_helper_allowed_uids:[1000]` is a YAML **scanner error** (no space after ':') => the whole file was
# rejected => the allow-list silently stayed empty => the helper denied every peer (fail-closed, looks like
# "nothing works"). This script renders that file with PyYAML, backs up whatever was there, runs the two
# existing scripts in the right order and parses their verdicts.
#
# NOTE: this script prints ASCII English only (the host is a text console without CJK fonts).
# The two wrapped scripts (sync_opt_tree.sh / setup_ebpf_helper.sh) still print Chinese; their stdout is
# captured into a log file instead of being dumped to the console, and the verdicts are re-printed here.
#
# Usage (--apply / --rollback / --self-check need root; --print-config and dry-run do not):
#   bash scripts/apply_ebpf1e.sh --print-config   # read-only: resolved values + the YAML that would be written
#   bash scripts/apply_ebpf1e.sh                  # dry-run (default): print the plan, touch nothing
#   sudo bash scripts/apply_ebpf1e.sh --apply     # step 1 + 2 + 3, then self-check (FAIL must be 0)
#   sudo bash scripts/apply_ebpf1e.sh --self-check   # step 4 only (checks, no changes)
#   sudo bash scripts/apply_ebpf1e.sh --rollback  # delegate to scripts/setup_ebpf_helper.sh --rollback
#
# Steps (source of truth: docs/SANDBOX-PLAN.md "6.7" / TODO.md "ebpf1e"):
#   0. kernel perf gate -- Ubuntu ships CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y, which makes the
#      perf_event_open(2) syscall that libbpf uses to attach a tracepoint program CAP_SYS_ADMIN-only
#      while kernel.perf_event_paranoid >= 4 (Ubuntu's default; upstream defaults to 2). The helper
#      holds only CAP_BPF+CAP_PERFMON **on purpose**, so the attach comes back EACCES(13) and the
#      end-to-end self-check fails with "bpf_program__attach failed: Permission denied". This step
#      writes /etc/sysctl.d/60-trimum-perf.conf (kernel.perf_event_paranoid=3) and reloads sysctl.
#   1. /etc/trimum/config.yaml -> security.bpf_helper_allowed_uids: [<client uid>]
#      The helper unit runs with XDG_CONFIG_HOME=/etc, so THIS file (not ~/.config/trimum/config.yaml) is
#      what it reads. Missing / broken file = empty set = every peer denied (fail-closed by design).
#   2. sudo bash scripts/sync_opt_tree.sh --from-home   -- deploy the working tree into /opt/trimum.
#      --from-home is deliberate: without it a stale /tmp/trimum-sync.tar would be deployed instead.
#   3. sudo bash scripts/setup_ebpf_helper.sh --apply   -- clang builds /opt/trimum/bpf/*.bpf.o (repo holds
#      sources only), writes the sha256 manifest, installs/restarts the unit; failure auto-rolls back.
#   4. sudo bash scripts/setup_ebpf_helper.sh --self-check   -- must end with FAIL=0 (that includes the
#      end-to-end case "client uid really loads bpf_guard into the kernel").
#
# Overrides (same priority chain as the rest of trimum: flag > env > config value > default):
#   --uid N                            TRIMUM_BPF_ALLOWED_UID   default: id -u of the client user
#   (client user)                      TRIMUM_BPF_CLIENT_USER   default: systemctl show trmd -p User --value
#   (config dir)                       TRIMUM_BPF_ETC_DIR       default: /etc/trimum
#   (backup + log root)                TRIMUM_BPF_BACKUP_ROOT   default: /var/backups/trimum
#   (deploy root)                      TRIMUM_BPF_DEPLOY_ROOT   default: /opt/trimum
#   (eBPF sources)                     TRIMUM_BPF_SRC_DIR       default: <repo>/bpf
#   (paranoid sysctl)                  TRIMUM_BPF_PARANOID_FILE      default: /proc/sys/kernel/perf_event_paranoid
#   (kernel config)                    TRIMUM_BPF_KERNEL_CONFIG      default: /boot/config-$(uname -r)
#   (sysctl drop-in)                   TRIMUM_BPF_PERF_DROPIN        default: /etc/sysctl.d/60-trimum-perf.conf
#   (target value)                     TRIMUM_BPF_PERF_PARANOID      default: 3
#   (sysctl binary)                    TRIMUM_BPF_SYSCTL_BIN         default: sysctl
#   (test seams, not for real runs)    TRIMUM_BPF_ALLOW_NONROOT / TRIMUM_BPF_SYNC_SH / TRIMUM_BPF_SETUP_SH
set -euo pipefail

STEP="(not started)"
trap 'rc=$?; printf "[ABORT] exit=%s  last step: %s  line: %s\n" "$rc" "$STEP" "$LINENO" >&2' ERR

MODE=dryrun
UID_ARG=""
SKIP_SYNC=0

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ETC_DIR="${TRIMUM_BPF_ETC_DIR:-/etc/trimum}"
CFG="${ETC_DIR}/config.yaml"
BACKUP_ROOT="${TRIMUM_BPF_BACKUP_ROOT:-/var/backups/trimum}"
DEPLOY_ROOT="${TRIMUM_BPF_DEPLOY_ROOT:-/opt/trimum}"
BPF_SRC_DIR="${TRIMUM_BPF_SRC_DIR:-${REPO_DIR}/bpf}"
SYNC_SH="${TRIMUM_BPF_SYNC_SH:-${REPO_DIR}/scripts/sync_opt_tree.sh}"
SETUP_SH="${TRIMUM_BPF_SETUP_SH:-${REPO_DIR}/scripts/setup_ebpf_helper.sh}"
# Same escape hatch as scripts/sync_opt_tree.sh: fake/CI runs only. It downgrades "need root" and the
# preflight verdict to warnings so the plumbing can be exercised without sudo -- real runs never set it.
ALLOW_NONROOT="${TRIMUM_BPF_ALLOW_NONROOT:-0}"
UNIT=trimum-bpf-helper
TS="$(date -u +%Y%m%d-%H%M%S)"
RUN_DIR="${BACKUP_ROOT}/ebpf1e-${TS}"
LOG=""

# Step 0 inputs (all overridable so the plumbing can be tested without root; see the header).
PERF_PARANOID_FILE="${TRIMUM_BPF_PARANOID_FILE:-/proc/sys/kernel/perf_event_paranoid}"
KERNEL_CONFIG="${TRIMUM_BPF_KERNEL_CONFIG:-/boot/config-$(uname -r)}"
PERF_DROPIN="${TRIMUM_BPF_PERF_DROPIN:-/etc/sysctl.d/60-trimum-perf.conf}"
PERF_PARANOID_TARGET="${TRIMUM_BPF_PERF_PARANOID:-3}"
SYSCTL_BIN="${TRIMUM_BPF_SYSCTL_BIN:-sysctl}"

# ASCII-only helpers: the wrapped scripts are Chinese, the console here is not.
say()  { printf '%s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
die()  { printf '[FAIL] %s\n' "$*" >&2; exit 1; }
is_root() { [ "$(id -u)" -eq 0 ]; }
need_root() {
  is_root || [ "$ALLOW_NONROOT" = "1" ] || die "$1 needs root: sudo bash $0 $2"
}
# Ownership is applied only when we really are root (the non-root escape hatch must not try to chown).
install_dir()  { if is_root; then install -d -o root -g root "$@"; else install -d "$@"; fi; }
install_file() { if is_root; then install -o root -g root "$@"; else install "$@"; fi; }
own_root()     { if is_root; then chown root:root "$@"; fi; }

usage() { sed -n '/^# Usage/,/^# Steps/p' "$0" | sed '/^# Steps/d' | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --print-config) MODE=printconfig ;;
    --dry-run) MODE=dryrun ;;
    --apply) MODE=apply ;;
    --self-check) MODE=selfcheck ;;
    --rollback) MODE=rollback ;;
    --skip-sync) SKIP_SYNC=1 ;;
    --uid) shift; [ $# -gt 0 ] || die "--uid needs a value: --uid <n>"; UID_ARG="$1" ;;
    --uid=*) UID_ARG="${1#--uid=}" ;;
    -h|--help) usage; exit 0 ;;
    *) warn "unknown argument: $1"; usage; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# 0. Resolve values (read-only; runs for every mode)
# ---------------------------------------------------------------------------
CLIENT_USER="${TRIMUM_BPF_CLIENT_USER:-}"
if [ -z "$CLIENT_USER" ]; then
  CLIENT_USER="$(systemctl show trmd -p User --value 2>/dev/null || true)"
fi
if [ -z "$CLIENT_USER" ]; then
  CLIENT_USER="${SUDO_USER:-$(id -un)}"
  warn "trmd unit not found -> client user falls back to ${CLIENT_USER}"
fi

if [ -n "$UID_ARG" ]; then
  ALLOWED_UID="$UID_ARG"
elif [ -n "${TRIMUM_BPF_ALLOWED_UID:-}" ]; then
  ALLOWED_UID="${TRIMUM_BPF_ALLOWED_UID}"
else
  ALLOWED_UID="$(id -u "$CLIENT_USER" 2>/dev/null || true)"
fi
case "$ALLOWED_UID" in
  ''|*[!0-9]*) die "cannot resolve a numeric uid (client user=${CLIENT_USER:-<empty>}); pass --uid <n> or TRIMUM_BPF_ALLOWED_UID=<n>" ;;
esac

# PyYAML is needed to render the config; system python usually has it, the deploy venv always does.
MERGE_PY=""
for cand in "${DEPLOY_ROOT}/venv/bin/python" python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import yaml' >/dev/null 2>&1; then
    MERGE_PY="$cand"; break
  fi
done
[ -n "$MERGE_PY" ] || die "no python with PyYAML found (tried ${DEPLOY_ROOT}/venv/bin/python, python3)"

RENDER_STATE="unknown"
RENDER_NOTE=""

# Render the merged config into $3. Sets RENDER_STATE (absent|ok|broken|not-mapping) and RENDER_NOTE.
# A broken existing file is NEVER an error: it is backed up by the caller and replaced (the old behaviour
# -- crashing on it -- is exactly what left the allow-list empty on the real host).
render_config_into() {  # $1 = existing path (may not exist), $2 = uid, $3 = output file
  local st="$3.st"
  EXISTING="$1" UID_V="$2" "$MERGE_PY" - >"$3" 2>"$st" <<'PY'
import os, sys, yaml

path = os.environ["EXISTING"]
uid = int(os.environ["UID_V"])
state = "absent"
data = {}
if os.path.exists(path):
    state = "ok"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
    except Exception:
        loaded, state = None, "broken"
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        loaded, state = {}, "not-mapping"
    data = loaded

security = data.get("security")
if not isinstance(security, dict):
    security = {}
    data["security"] = security
security["bpf_helper_allowed_uids"] = [uid]

print("STATE=%s" % state, file=sys.stderr)
sys.stdout.write(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=None))
PY
  RENDER_STATE="$(sed -n 's/^STATE=//p' "$st" | head -1)"
  rm -f "$st"
  case "$RENDER_STATE" in
    broken) RENDER_NOTE="existing file is not valid YAML -> kept as a backup, replaced" ;;
    not-mapping) RENDER_NOTE="existing file is not a YAML mapping -> kept as a backup, replaced" ;;
    absent) RENDER_NOTE="no existing file" ;;
    *) RENDER_NOTE="existing file merges cleanly (other keys are preserved)" ;;
  esac
}

# ---------------------------------------------------------------------------
# --print-config: read-only view of everything that decides the outcome
# ---------------------------------------------------------------------------
do_print_config() {
  STEP="print-config"
  local tmp
  tmp="$(mktemp)"; render_config_into "$CFG" "$ALLOWED_UID" "$tmp"
  printf 'client_user=%s\n' "$CLIENT_USER"
  printf 'allowed_uid=%s\n' "$ALLOWED_UID"
  printf 'config_path=%s\n' "$CFG"
  printf 'existing_config=%s\n' "$RENDER_STATE"
  printf 'existing_config_note=%s\n' "$RENDER_NOTE"
  printf 'backup_root=%s\n' "$BACKUP_ROOT"
  printf 'deploy_root=%s\n' "$DEPLOY_ROOT"
  printf 'bpf_src_dir=%s\n' "$BPF_SRC_DIR"
  printf 'perf_gate=%s\n' "$(perf_gate_kind)"
  printf 'perf_gate_note=%s\n' "$(perf_gate_line)"
  printf 'perf_dropin=%s\n' "$PERF_DROPIN"
  printf 'sync_cmd=bash %s --from-home\n' "$SYNC_SH"
  printf 'apply_cmd=bash %s --apply\n' "$SETUP_SH"
  printf 'self_check_cmd=bash %s --self-check\n' "$SETUP_SH"
  printf '%s\n' "--- would write to ${CFG}:"
  cat "$tmp"
  rm -f "$tmp"
}

# ---------------------------------------------------------------------------
# Preflight for the mutating modes
# ---------------------------------------------------------------------------
preflight() {
  STEP="preflight"
  local missing=0
  for f in "$SYNC_SH" "$SETUP_SH" "${BPF_SRC_DIR}/bpf_guard.bpf.c" "${BPF_SRC_DIR}/trimum_bpf.h" \
           "${REPO_DIR}/deploy/trimum-bpf-helper.service"; do
    if [ -e "$f" ]; then say "  [ok]   $f"; else warn "missing: $f"; missing=1; fi
  done
  if [ ! -e "${BPF_SRC_DIR}/bpf_guard.bpf.c" ]; then
    warn "eBPF sources are not in ${BPF_SRC_DIR}: run this from the SOURCE tree (repo root), e.g."
    warn "  sudo bash ~/trimum/scripts/apply_ebpf1e.sh --apply   (the /opt/trimum copy has .o artifacts, not sources)"
  fi
  if [ -x "${DEPLOY_ROOT}/venv/bin/python" ]; then
    say "  [ok]   ${DEPLOY_ROOT}/venv/bin/python"
  else
    warn "missing: ${DEPLOY_ROOT}/venv/bin/python (was /opt/trimum ever installed?)"; missing=1
  fi
  if command -v clang >/dev/null 2>&1; then
    say "  [ok]   clang: $(clang --version | head -1)"
  else
    warn "clang not found -- step 3 will fail (see docs/SANDBOX-PLAN.md toolchain script)"; missing=1
  fi
  if [ "$missing" -ne 0 ]; then
    if [ "$ALLOW_NONROOT" = "1" ]; then
      warn "preflight problems ignored (TRIMUM_BPF_ALLOW_NONROOT=1)"
    else
      die "preflight failed (fix the lines above)"
    fi
  fi
}

read_paranoid() { tr -dc '0-9' <"$PERF_PARANOID_FILE" 2>/dev/null || true; }

# on      = perf_event_open(2) is CAP_SYS_ADMIN-only here -> the helper cannot attach, step 0 is needed
# off      = the helper's CAP_BPF+CAP_PERFMON is enough (paranoid < 4, or no RESTRICT=y in the kernel)
# unknown  = cannot read the sysctl / the kernel config -> change nothing, only warn
perf_gate_kind() {
  local paranoid
  paranoid="$(read_paranoid)"
  [ -n "$paranoid" ] || { printf 'unknown'; return 0; }
  [ "$paranoid" -lt 4 ] && { printf 'off'; return 0; }
  [ -r "$KERNEL_CONFIG" ] || { printf 'unknown'; return 0; }
  if grep -qs '^CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y' "$KERNEL_CONFIG"; then
    printf 'on'
  else
    printf 'off'
  fi
}

# One ASCII line for the plan/summary views.
perf_gate_line() {
  local kind paranoid
  kind="$(perf_gate_kind)"
  paranoid="$(read_paranoid)"
  case "$kind" in
    on)  printf 'perf_event_open is CAP_SYS_ADMIN-only (RESTRICT=y, paranoid=%s); step 0 lowers it to %s' \
                  "$paranoid" "$PERF_PARANOID_TARGET" ;;
    off) printf 'perf_event_open accepts CAP_PERFMON (paranoid=%s); nothing to do' "${paranoid:-?}" ;;
    *)   printf 'unknown (cannot read %s / %s)' "$PERF_PARANOID_FILE" "$KERNEL_CONFIG" ;;
  esac
}

# ---------------------------------------------------------------------------
# Step 0 -- the kernel perf gate (see the header)
# ---------------------------------------------------------------------------
step_perf_gate() {
  STEP="[0/4] kernel perf gate"
  say "== [0/4] kernel perf gate: $(perf_gate_line) =="
  local kind now
  kind="$(perf_gate_kind)"
  case "$kind" in
    off)
      say "  [ok] the helper's CAP_BPF+CAP_PERFMON is enough (kernel.perf_event_paranoid=$(read_paranoid))"
      ;;
    unknown)
      warn "cannot read ${PERF_PARANOID_FILE} / ${KERNEL_CONFIG} -- skipping the perf gate check"
      ;;
    on)
      if [ -f "$PERF_DROPIN" ] && grep -qs "^kernel\.perf_event_paranoid=${PERF_PARANOID_TARGET}\$" "$PERF_DROPIN"; then
        say "  drop-in already in place: ${PERF_DROPIN}"
      else
        install_dir -m 0755 "$(dirname "$PERF_DROPIN")"
        if [ -e "$PERF_DROPIN" ]; then
          install_file -m 0644 "$PERF_DROPIN" "${RUN_DIR}/$(basename "$PERF_DROPIN")"
          say "  backup: ${RUN_DIR}/$(basename "$PERF_DROPIN")"
        fi
        {
          printf '# trimum ebpf1e step 0: let the CAP_BPF+CAP_PERFMON helper use perf_event_open tracepoints.\n'
          printf '# Ubuntu builds kernels with CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y: perf_event_open needs\n'
          printf '# CAP_SYS_ADMIN while kernel.perf_event_paranoid >= 4 (Ubuntu default). %s keeps the\n' "$PERF_PARANOID_TARGET"
          printf '# upstream-default behaviour; unprivileged_bpf_disabled=2 and every perfmon_capable gate stay.\n'
          printf 'kernel.perf_event_paranoid=%s\n' "$PERF_PARANOID_TARGET"
        } >"$PERF_DROPIN"
        own_root "$PERF_DROPIN"; chmod 0644 "$PERF_DROPIN"
        say "  wrote ${PERF_DROPIN} (kernel.perf_event_paranoid=${PERF_PARANOID_TARGET};"
        say "  a host-wide knob -- rationale + tradeoff in docs/SANDBOX-PLAN.md section 6.7)"
      fi
      "$SYSCTL_BIN" --system >>"$LOG" 2>&1 || warn "${SYSCTL_BIN} --system rc=$? (see ${LOG})"
      now="$(read_paranoid)"
      if [ -n "$now" ] && [ "$now" -lt 4 ]; then
        say "  [ok] kernel.perf_event_paranoid=${now} -- the tracepoint attach no longer needs CAP_SYS_ADMIN"
      else
        die "kernel.perf_event_paranoid is still ${now:-?}; write ${PERF_DROPIN} and run '${SYSCTL_BIN} --system'"
      fi
      ;;
  esac
}

new_run_log() {
  install_dir -m 0755 "$RUN_DIR"
  LOG="${RUN_DIR}/ebpf1e.log"
  : > "$LOG"; chmod 0644 "$LOG"
  say "  run dir (backup + log): $RUN_DIR"
}

# ASCII-only view of the wrapped script's failing checks: the log is UTF-8 (Chinese messages) and this
# console has no CJK font, so replace every non-printable byte with '?' -- the ASCII tokens that matter
# (paths, perms, "ERR ...", uid numbers, "peer_denied", "socket") stay readable.
print_fail_lines() {
  local n
  n="$(LC_ALL=C grep -ac '\[FAIL\]' "$LOG" 2>/dev/null || true)"
  if [ "${n:-0}" -eq 0 ]; then
    say "  (no [FAIL] line in the log -- see ${LOG})"
    return 0
  fi
  say "  failing checks (non-ASCII bytes shown as '?', total ${n}):"
  LC_ALL=C grep -a '\[FAIL\]' "$LOG" | head -20 | LC_ALL=C tr -c '[:print:]\n' '?' | sed 's/^/    /'
}

# ---------------------------------------------------------------------------
# Step 1 -- the config file
# ---------------------------------------------------------------------------
step_config() {
  STEP="[1/4] config"
  say "== [1/4] ${CFG} -> security.bpf_helper_allowed_uids: [${ALLOWED_UID}] (${CLIENT_USER}) =="
  install_dir -m 0755 "$ETC_DIR"
  own_root "$ETC_DIR"; chmod 0755 "$ETC_DIR"

  local tmp_new="${ETC_DIR}/.config.yaml.new"
  render_config_into "$CFG" "$ALLOWED_UID" "$tmp_new"
  say "  existing: ${RENDER_STATE} -- ${RENDER_NOTE}"

  if [ -e "$CFG" ] && cmp -s "$CFG" "$tmp_new"; then
    say "  already up to date (byte-identical) -- file left untouched"
    rm -f "$tmp_new"
  else
    if [ -e "$CFG" ]; then
      install_file -m 0600 "$CFG" "${RUN_DIR}/config.yaml"
      sha256sum "$CFG" > "${RUN_DIR}/config.yaml.sha256"
      say "  backup: ${RUN_DIR}/config.yaml (restore with: install -m 0644 -o root -g root ${RUN_DIR}/config.yaml ${CFG})"
    fi
    own_root "$tmp_new"; chmod 0644 "$tmp_new"
    mv -f "$tmp_new" "$CFG"
    say "  wrote ${CFG} (root:root 0644)"
  fi

  # Verify by reading it back the way the helper does (PyYAML + the exact key path).
  if CONFIG_PATH="$CFG" EXPECT_UID="$ALLOWED_UID" "$MERGE_PY" - <<'PY'
import os, sys, yaml

path = os.environ["CONFIG_PATH"]
want = [int(os.environ["EXPECT_UID"])]
with open(path, "r", encoding="utf-8") as fh:
    data = yaml.safe_load(fh)
if not isinstance(data, dict):
    sys.exit("config did not parse into a mapping")
got = data.get("security", {}).get("bpf_helper_allowed_uids") if isinstance(data.get("security"), dict) else None
if got != want:
    sys.exit("security.bpf_helper_allowed_uids is %r, expected %r" % (got, want))
print("  verified: security.bpf_helper_allowed_uids == %r" % (got,))
PY
  then
    say "  [ok] config verified"
  else
    die "config verification failed -- ${CFG} is not what the helper will read"
  fi
}

# ---------------------------------------------------------------------------
# Step 2 -- deploy the working tree into /opt/trimum
# ---------------------------------------------------------------------------
step_sync() {
  STEP="[2/4] sync_opt_tree"
  if [ "$SKIP_SYNC" -eq 1 ]; then
    say "== [2/4] skipped (--skip-sync) =="
    return 0
  fi
  say "== [2/4] bash scripts/sync_opt_tree.sh --from-home =="
  local rc=0
  bash "$SYNC_SH" --from-home >>"$LOG" 2>&1 || rc=$?
  if [ "$rc" -eq 0 ]; then
    say "  [ok] deploy tree updated (output in ${LOG})"
  else
    say "  [FAIL] sync_opt_tree.sh rc=${rc} -- nothing else was touched"
    printf '  raw output: %s\n' "$LOG"
    tail -20 "$LOG" >&2
    exit "$rc"
  fi
  # Stale-bytecode guard: CPython validates a .pyc by the source's **integer-second** mtime, so a file
  # copied within the same second as an older compile is silently ignored in favour of the old bytecode.
  # The helper imports trimum_core from the deploy tree, so drop its __pycache__ and let it recompile.
  if [ -d "${DEPLOY_ROOT}/src" ]; then
    local purged
    purged="$(find "${DEPLOY_ROOT}/src" -type d -name __pycache__ -print 2>/dev/null | wc -l)"
    find "${DEPLOY_ROOT}/src" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    say "  [ok] purged ${purged} stale __pycache__ dir(s) under ${DEPLOY_ROOT}/src (pyc mtime granularity trap)"
  fi
}

# ---------------------------------------------------------------------------
# Step 3 -- clang build + unit install (auto-rollback inside the wrapped script)
# ---------------------------------------------------------------------------
step_apply() {
  STEP="[3/4] setup_ebpf_helper --apply"
  say "== [3/4] bash scripts/setup_ebpf_helper.sh --apply =="
  local rc=0
  bash "$SETUP_SH" --apply >>"$LOG" 2>&1 || rc=$?
  local fails
  fails="$(grep -c '\[FAIL\]' "$LOG" || true)"
  if [ "$rc" -eq 0 ]; then
    say "  [ok] installed (rc=0, FAIL-lines=${fails}; output in ${LOG})"
  else
    say "  [FAIL] setup_ebpf_helper.sh --apply rc=${rc} (FAIL-lines=${fails}) -- it rolls back by itself"
    print_fail_lines
    printf '  raw output: %s\n' "$LOG"
    exit "$rc"
  fi
}

# ---------------------------------------------------------------------------
# Step 4 -- self-check; FAIL must be 0
# ---------------------------------------------------------------------------
step_selfcheck() {
  STEP="[4/4] setup_ebpf_helper --self-check"
  say "== [4/4] bash scripts/setup_ebpf_helper.sh --self-check =="
  local rc=0
  bash "$SETUP_SH" --self-check >>"$LOG" 2>&1 || rc=$?
  local summary fails oks skips
  summary="$(grep -o 'OK=[0-9]*  FAIL=[0-9]*  SKIP=[0-9]*' "$LOG" | tail -1 || true)"
  oks="$(printf '%s' "$summary" | sed -n 's/^OK=\([0-9]*\).*/\1/p')"
  fails="$(printf '%s' "$summary" | sed -n 's/.*FAIL=\([0-9]*\).*/\1/p')"
  skips="$(printf '%s' "$summary" | sed -n 's/.*SKIP=\([0-9]*\).*/\1/p')"
  if [ -z "$fails" ]; then
    die "could not parse the self-check summary (rc=${rc}); raw output: ${LOG}"
  fi
  say "  verdict: OK=${oks:-?}  FAIL=${fails}  SKIP=${skips:-?}  (rc=${rc})"
  if [ "$fails" -eq 0 ] && [ "$rc" -eq 0 ]; then
    say "  [ok] FAIL=0 -- the real loader is online"
  else
    say "  [FAIL] ${fails} check(s) failed -- log: ${LOG}"
    print_fail_lines
    if [ "$(perf_gate_kind)" = on ]; then
      say "  hint: kernel.perf_event_paranoid=$(read_paranoid) + CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y makes"
      say "        perf_event_open(2) CAP_SYS_ADMIN-only, but the helper holds only CAP_BPF+CAP_PERFMON"
      say "        (by design) => libbpf's tracepoint attach returns EACCES / 'Permission denied'."
      say "        fix: sudo bash $0 --apply     # step 0 writes ${PERF_DROPIN}"
    fi
    say "  journal: journalctl -u ${UNIT} -n 50 --no-pager"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
case "$MODE" in
  printconfig)
    do_print_config
    ;;

  dryrun)
    _probe="$(mktemp)"; render_config_into "$CFG" "$ALLOWED_UID" "$_probe"; rm -f "$_probe"
    say "dry-run (nothing is written; use --apply to execute)"
    say
    say "resolved:"
    say "  client user / allowed uid : ${CLIENT_USER} / ${ALLOWED_UID}"
    say "  config                    : ${CFG} (existing: ${RENDER_STATE})"
    say "  backup + log dir           : ${RUN_DIR}"
    say "  deploy root                : ${DEPLOY_ROOT}"
    say "  kernel perf gate           : $(perf_gate_line)"
    say
    say "plan:"
    say "  [0/4] kernel perf gate: write ${PERF_DROPIN} -> kernel.perf_event_paranoid=${PERF_PARANOID_TARGET} (only if the gate applies) + sysctl --system"
    say "  [1/4] write ${CFG} -> security.bpf_helper_allowed_uids: [${ALLOWED_UID}]  (backup first if it exists)"
    say "  [2/4] bash ${SYNC_SH} --from-home"
    say "  [3/4] bash ${SETUP_SH} --apply"
    say "  [4/4] bash ${SETUP_SH} --self-check   (must print FAIL=0)"
    say
    say "config body that step 1 would write:"
    do_print_config | sed -n '/^--- would write/,$p'
    say
    say "execute with: sudo bash $0 --apply"
    ;;

  apply)
    need_root "apply" "--apply"
    say "== ebpf1e apply (run dir ${RUN_DIR}) =="
    preflight
    new_run_log
    step_perf_gate
    step_config
    step_sync
    step_apply
    step_selfcheck
    say
    say "== done =="
    say "  service          : ${UNIT} = $(systemctl is-active "$UNIT" 2>/dev/null || true)"
    say "  allow-list       : ${ALLOWED_UID} (${CLIENT_USER}) via ${CFG}"
    say "  perf gate        : kernel.perf_event_paranoid=$(read_paranoid) (drop-in: ${PERF_DROPIN})"
    say "  log              : ${LOG}"
    say "  rollback (unit)  : sudo bash ${SETUP_SH} --rollback"
    say "  rollback (config): see the backup path printed in step 1"
    say "  note: nothing in the daemon consumes the alerts yet (TODO 'ebpf1f': BpfAlertTailer has no caller)."
    ;;

  selfcheck)
    need_root "self-check" "--self-check"
    mkdir -p "$RUN_DIR" 2>/dev/null || RUN_DIR="$(mktemp -d)"
    LOG="${RUN_DIR}/ebpf1e-self-check.log"
    : > "$LOG"
    say "kernel perf gate: $(perf_gate_line)"
    step_selfcheck
    ;;

  rollback)
    need_root "rollback" "--rollback"
    say "== rollback: bash scripts/setup_ebpf_helper.sh --rollback =="
    bash "$SETUP_SH" --rollback
    say
    say "config backups taken by this script (oldest first):"
    ls -1d "${BACKUP_ROOT}"/ebpf1e-* 2>/dev/null || say "  (none)"
    say "  restore one: install -m 0644 -o root -g root <run-dir>/config.yaml ${CFG}"
    ;;
esac
