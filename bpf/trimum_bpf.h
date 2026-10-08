/* trimum eBPF event kinds -- the single source of truth for BOTH sides:
 *   * the C programs (bpf_guard / exec_guard) below use these numbers;
 *   * the Python side (src/trimum_core/bpf_loader.py, KINDS) decodes them.
 * tests/test_bpf_loader.py parses this header and asserts the two tables agree,
 * so changing a number here without changing the Python side fails the suite.
 */
#ifndef TRIMUM_BPF_H
#define TRIMUM_BPF_H

#include <linux/types.h>

enum trimum_bpf_kind {
    TRIMUM_KIND_PROG_LOAD  = 1,  /* bpf(BPF_PROG_LOAD)                -> "prog_load"  */
    TRIMUM_KIND_BPF_ATTACH = 2,  /* bpf(BPF_LINK_CREATE/PROG_ATTACH)  -> "bpf_attach" */
    TRIMUM_KIND_BPF_DETACH = 3,  /* bpf(BPF_PROG_DETACH)              -> "bpf_detach" */
    TRIMUM_KIND_MAP_WRITE  = 4,  /* bpf(BPF_MAP_UPDATE/DELETE_ELEM)   -> "map_write"  */
    TRIMUM_KIND_EXEC       = 5,  /* execve()                          -> "exec"       */
};

/* One audit record, copied to userspace through the "events" ring buffer.
 *
 * The layout is PINNED: bpf_loader.py decodes it with the matching
 * "<III16s64sI" format and tests/test_bpf_loader.py asserts the two agree, so the
 * trailing pad must stay (a ring buffer reservation is always a multiple of 8
 * bytes). Keep this struct free of pointers -- it crosses the kernel boundary.
 */
struct trimum_bpf_event {
    __u32 kind;      /* enum trimum_bpf_kind */
    __u32 pid;       /* thread group id (lower 32 bits of bpf_get_current_pid_tgid are the tgid) */
    __u32 arg0;      /* raw syscall argument 0 (bpf_guard: the bpf() cmd); 0 when unused */
    char  comm[16];  /* task command name */
    char  text[64];  /* optional NUL-terminated detail (exec_guard: the filename) */
    __u32 pad;       /* padding: keep sizeof(struct trimum_bpf_event) a multiple of 8 */
};

/* The tracepoint context of every "syscalls/sys_enter_*" tracepoint.
 *
 * Verified against the running kernel's BTF (`bpftool btf dump file
 * /sys/kernel/btf/vmlinux`): struct trace_event_raw_sys_enter { struct trace_entry
 * ent; long id; unsigned long args[6]; } -- i.e. args[0] lives at offset 16, and
 * args[0] is the first syscall argument (bpf(2) cmd / execve(2) filename).
 * Accessing ctx->args[0] is the canonical tracepoint pattern; reading raw offset 0
 * (the trace_entry header) would be rejected by the verifier.
 */
struct sys_enter_ctx {
    __u64 trace_entry;  /* struct trace_entry, 8 bytes */
    __s64 syscall_id;   /* the syscall number */
    __u64 args[6];      /* offset 16: args[0] = first syscall argument */
};

#endif /* TRIMUM_BPF_H */
