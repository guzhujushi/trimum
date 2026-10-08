#!/usr/bin/env bash
# build_bpf.sh -- compile the eBPF audit programs under bpf/ into .bpf.o objects.
#
# Usage (no root needed; does NOT install anything):
#   bash scripts/build_bpf.sh                       # -> bpf/<name>.bpf.o
#   bash scripts/build_bpf.sh --out-dir DIR         # write objects to DIR
#   bash scripts/build_bpf.sh --manifest FILE       # also write "<name>  <sha256>" lines
#   bash scripts/build_bpf.sh --check               # only verify the toolchain, compile nothing
#
# stdout is ASCII English on purpose: this is meant to be readable on the real host's
# text console (which cannot render UTF-8). See docs/GRAPHICS-STACK-PLAN.md for the rule.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${TRIMUM_BPF_SRC_DIR:-${REPO_ROOT}/bpf}"
OUT_DIR="${SRC_DIR}"
MANIFEST=""
CHECK_ONLY=no

CC="${TRIMUM_BPF_CLANG:-clang}"
ARCH_INC="/usr/include/$(uname -m)-linux-gnu"

die() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }
ok()  { printf '  [OK]   %s\n' "$1"; }
log() { printf '%s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --out-dir)  OUT_DIR="${2:?--out-dir needs a directory}"; shift 2 ;;
    --manifest) MANIFEST="${2:?--manifest needs a file}"; shift 2 ;;
    --check)    CHECK_ONLY=yes; shift ;;
    -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    *)          die "unknown argument: $1 (-h for usage)" ;;
  esac
done

# ---- toolchain check (every piece has to be there; a missing one is a hard failure) ----
command -v "$CC" >/dev/null 2>&1 || die "${CC} not found (install: clang)"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum not found (install: coreutils)"
[ -d "$ARCH_INC" ] || die "missing ${ARCH_INC} (install: libc6-dev) -- asm/types.h comes from there"
[ -r /usr/include/bpf/bpf_helpers.h ] || die "missing /usr/include/bpf/bpf_helpers.h (install: libbpf-dev)"
[ -r "${SRC_DIR}/trimum_bpf.h" ] || die "missing ${SRC_DIR}/trimum_bpf.h"
log "toolchain:"
ok "$($CC --version | head -1)"
ok "include: ${ARCH_INC} + /usr/include/bpf + ${SRC_DIR}"
[ "$CHECK_ONLY" = yes ] && { log "check only; nothing compiled."; exit 0; }

install -d -m 0755 "$OUT_DIR"

CFLAGS=(-target bpf -D__TARGET_ARCH_x86 -O2 -g -Wall
        -I"$ARCH_INC" -I/usr/include -I"$SRC_DIR")

: > "${OUT_DIR}/.sha256.tmp"
built=0
for src in "$SRC_DIR"/*.bpf.c; do
  [ -e "$src" ] || die "no *.bpf.c under ${SRC_DIR}"
  name="$(basename "$src" .bpf.c)"
  out="${OUT_DIR}/${name}.bpf.o"
  if ! "$CC" "${CFLAGS[@]}" -c "$src" -o "$out" 2>&1 | sed 's/^/    /'; then
    die "compile failed: ${src}"
  fi
  # the compiler writes the object; make sure it really is an eBPF relocatable
  if ! file -b "$out" 2>/dev/null | grep -q 'eBPF'; then
    die "not an eBPF object (compiler produced something unexpected): ${out}"
  fi
  chmod 0644 "$out"
  digest="$(sha256sum "$out" | awk '{print $1}')"
  ok "${name}: $(basename "$out") sha256=${digest}"
  printf '%s  %s\n' "$name" "$digest" >> "${OUT_DIR}/.sha256.tmp"
  built=$((built+1))
done
[ "$built" -gt 0 ] || die "nothing was built"

if [ -n "$MANIFEST" ]; then
  man_dir="$(dirname "$MANIFEST")"
  [ -d "$man_dir" ] || install -d -m 0755 "$man_dir"
  sort -u "${OUT_DIR}/.sha256.tmp" > "$MANIFEST"
  chmod 0644 "$MANIFEST"
  ok "manifest: ${MANIFEST} ($(wc -l < "$MANIFEST") program(s))"
fi
rm -f "${OUT_DIR}/.sha256.tmp"
log ""
log "built ${built} program(s) into ${OUT_DIR}; install with: sudo bash scripts/setup_ebpf_helper.sh --apply"
