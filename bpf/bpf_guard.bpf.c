/* bpf_guard -- audit source for "somebody is loading / attaching / changing BPF objects".
 *
 * Attaches to the sys_enter_bpf tracepoint and emits ONE ring-buffer record per
 * interesting bpf(2) command (prog load, attach, detach, map write). It is an
 * AUDIT SOURCE ONLY: it never blocks, never filters, never writes user memory.
 *
 * Build:  bash scripts/build_bpf.sh            (clang -target bpf)
 * Install: bash scripts/setup_ebpf_helper.sh --apply
 */
#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>

#include "trimum_bpf.h"

_Static_assert(sizeof(struct trimum_bpf_event) == 96, "event record layout drift");
_Static_assert(__builtin_offsetof(struct sys_enter_ctx, args) == 16,
               "sys_enter tracepoint layout drift (args[0] must be at offset 16)");

char LICENSE[] SEC("license") = "GPL";

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 16);
} events SEC(".maps");

/* bpf(2) commands we audit (linux/bpf.h); everything else is ignored on purpose. */
static __always_inline __u32 classify(__u32 cmd)
{
    switch (cmd) {
    case BPF_PROG_LOAD:        /* 5  */
        return TRIMUM_KIND_PROG_LOAD;
    case BPF_LINK_CREATE:      /* 28 */
    case BPF_PROG_ATTACH:      /* 8  */
        return TRIMUM_KIND_BPF_ATTACH;
    case BPF_PROG_DETACH:      /* 9  */
        return TRIMUM_KIND_BPF_DETACH;
    case BPF_MAP_UPDATE_ELEM:  /* 2  */
    case BPF_MAP_DELETE_ELEM:  /* 3  */
        return TRIMUM_KIND_MAP_WRITE;
    default:
        return 0;
    }
}

SEC("tracepoint/syscalls/sys_enter_bpf")
int bpf_guard(struct sys_enter_ctx *ctx)
{
    /* tracepoint arg0 == bpf(2) cmd */
    __u32 cmd = (__u32)ctx->args[0];
    __u32 kind = classify(cmd);
    struct trimum_bpf_event *e;

    if (kind == 0)
        return 0;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;  /* ring full: drop, never block the syscall */

    e->kind = kind;
    e->pid = bpf_get_current_pid_tgid() >> 32;
    e->arg0 = cmd;
    e->pad = 0;
    e->text[0] = 0;
    bpf_get_current_comm(&e->comm, sizeof(e->comm));
    bpf_ringbuf_submit(e, 0);
    return 0;
}
