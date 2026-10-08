/* exec_guard -- audit source for process execution.
 *
 * Attaches to the sys_enter_execve tracepoint and emits one ring-buffer record
 * carrying pid / comm / the (best-effort) executable path. AUDIT SOURCE ONLY:
 * it never blocks or alters the exec; if the path cannot be read the record is
 * still emitted with an empty text field.
 *
 * NOTE: this program is high volume (one record per execve on the machine); load
 * it only when you really want that stream (bpf.load exec_guard).
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

SEC("tracepoint/syscalls/sys_enter_execve")
int exec_guard(struct sys_enter_ctx *ctx)
{
    /* tracepoint arg0 == const char __user *filename */
    void *filename = (void *)ctx->args[0];
    struct trimum_bpf_event *e;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;  /* ring full: drop, never block the exec */

    e->kind = TRIMUM_KIND_EXEC;
    e->pid = bpf_get_current_pid_tgid() >> 32;
    e->arg0 = 0;
    e->pad = 0;
    e->text[0] = 0;
    bpf_get_current_comm(&e->comm, sizeof(e->comm));
    if (filename)
        bpf_probe_read_user_str(&e->text, sizeof(e->text), filename);
    bpf_ringbuf_submit(e, 0);
    return 0;
}
