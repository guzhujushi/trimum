# bpf/ — eBPF audit programs (source only)

Source of truth for the privileged helper's eBPF programs. **Only sources live here**;
the compiled objects (`bpf/*.bpf.o`) are build products and are gitignored.

| file | program | attaches to | emits `kind` |
|---|---|---|---|
| `bpf_guard.bpf.c` | `bpf_guard` | `tracepoint/syscalls/sys_enter_bpf` | `prog_load` / `bpf_attach` / `bpf_detach` / `map_write` |
| `exec_guard.bpf.c` | `exec_guard` | `tracepoint/syscalls/sys_enter_execve` | `exec` |

* `trimum_bpf.h` holds the numeric kind table; `src/trimum_core/bpf_loader.py` mirrors it and
  a unit test parses this header to keep the two in sync.
* Build (host, needs `clang` + `libbpf-dev` + `linux-headers`):
  `bash scripts/build_bpf.sh` → `bpf/<program>.bpf.o` (+ sha256 on stdout).
* Install: `sudo bash scripts/setup_ebpf_helper.sh --apply` (compiles, installs to
  `/opt/trimum/bpf/*.bpf.o` as `root:root 0444`, and writes `/etc/trimum/bpf-manifest.txt`).
* The programs are **audit sources only**: they never block, filter, or write user memory.
* `exec_guard` is **high volume** (one record per `execve` on the box): load it explicitly
  (`bpf.load exec_guard`) only when you want that stream. All five kinds are accepted by the
  daemon side (`src/trimum_core/bpf_audit.py`, `HELPER_ALERT_KINDS`).
* The loader (`src/trimum_core/bpf_loader.py`) drains the ring buffers in a background thread and
  appends one JSON line per event to `security.bpf_alerts` (default `/run/trimum/bpf-alerts.jsonl`);
  `bpf.tail` additionally peeks the last `security.bpf_recent_events` records. Every knob is
  configurable (`security.bpf_program_dir` / `..._drain_interval_ms` / `..._alerts_max_bytes` /
  `..._recent_events` + matching `TRIMUM_BPF_*` env vars) -- key table in `docs/SANDBOX-PLAN.md` §6.7.
* The tracepoint context offsets are pinned by `_Static_assert` against the kernel BTF
  (`args[0]` at offset 16); reading raw offset 0 (the `trace_entry` header) is rejected by the verifier.
