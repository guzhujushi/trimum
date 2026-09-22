"""Layer K 的第二半 —— seccomp 档位（S3 落地，2026-09-22）。

设计出处：`docs/SANDBOX-PLAN.md` §6.2（内核层 = Landlock + seccomp + NoNewPrivileges）、
§8 的 S3 行；威胁清单出自 `docs/SECURITY-DEFENSE-PLAN.md` §7.2，**按真机事实校正**（见下）。

与 Landlock 的分工：Landlock 管"能读写哪些路径"，seccomp 管"能调哪些系统调用"。两者
在同一个 `preexec` 钩子里施加（Landlock 先、seccomp 后），施加失败同样 **fail-closed**。

真机事实（2026-09-22 实测，Ubuntu 24.04.1 / kernel 6.8.0-41 / libseccomp 2.5.5）：

1. `ctypes.CDLL("libseccomp.so.2")` 直接可用，**不需要 pip、不需要 -dev**；`seccomp_api_get() = 6`。
2. ⚠️ `seccomp_version()` 走 ctypes **读不出真实版本**（restype 试过 c_uint/c_int/c_ulong 全是垃圾值），
   所以能力口径用 **API level**（`seccomp_api_get()`）而不是版本号 —— 与 Landlock 用 ABI 而不是内核版本同源。
3. 过滤器真能拦：`ptrace(PTRACE_TRACEME)`（正常返回 0）与 `io_uring_setup`（正常返回 fd）在施加后
   都变成 `EPERM`；良性 syscall（`getpid` / 读文件 / 建 socket）不受影响。
   ⇒ **判别器只能选"正常会成功"的 syscall**：`bpf` / `mount` / `setns` 非特权本来就失败，
   拿它们做验收会得出"拦住了"的假结论。
4. 名字解析：`seccomp_syscall_resolve_name()` 对**本架构不存在**的名字返回 `-10190`（`__NR_SCMP_UNDEF`）、
   对**完全不认识**的名字返回 `-1`。文档 §7.2 清单里的 `swapcontext`（libc 函数）与 `poweroff`（命令）
   正落在前者/后者 ⇒ 已从清单里删掉，并且解析失败**不当致命错误**（记进 `unknown` 供审计）。

三档（默认 `l1`）：

| 档 | 形态 | 用途 |
|---|---|---|
| `l1` | 默认放行 + 危险内核面黑名单（`_KERNEL_BLOCK`） | 默认档：编码智能体/工具调用 |
| `strict` | `l1` + 「网络 socket（按地址族过滤，**放 AF_UNIX**）」等追加面；声明了 `whitelist` 则切成**白名单模式** | 未知/第三方 Agent、要显式声明才给的能力 |
| `off` | 不施加 | 排障一键退 |

`strict` 为什么按地址族过滤 `socket` 而不是整条拦：trimum 的子 Agent 靠 **UNIX socket** 跟 daemon
讲话（`/run/trimum/trimum.sock`），整条拦会把 RPC 一起打死。所以只挡 `AF_INET`/`AF_INET6`/
`AF_PACKET`/`AF_NETLINK`，`AF_UNIX` 放行 —— 这条用 libseccomp 的参数比较实现。

白名单模式的**能力边界（写清楚，不吹）**：内置基线只够跑静态小二进制；Python / 动态链接程序
需要 `allow` 里显式补齐（`openat`/`mmap`/`getdents64`/... 一大串）。所以它**不是**默认档，
只给"沙箱内跑未知二进制"这种场景用（§7.1 的 L3 思路）。
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Sequence

from .logger import get_logger

logger = get_logger("trimum_core.seccomp_exec")

# ══════════════════════════════════════════════════════════════════════
# 档位与状态
# ══════════════════════════════════════════════════════════════════════

PROFILE_OFF = "off"
PROFILE_L1 = "l1"
PROFILE_STRICT = "strict"
PROFILES: tuple[str, ...] = (PROFILE_L1, PROFILE_STRICT, PROFILE_OFF)
DEFAULT_PROFILE = PROFILE_L1

#: 从宽到严（数字越小越严）：`agent.json5` 只能往严里收，不能放宽
PROFILE_RANK = {PROFILE_OFF: 2, PROFILE_L1: 1, PROFILE_STRICT: 0}

#: `docs/SECURITY-DEFENSE-PLAN.md` §7.1 的 L0..L3 口径 → 本模块三档
ALIASES: dict[str, str] = {
    "off": PROFILE_OFF,
    "none": PROFILE_OFF,
    "l0": PROFILE_OFF,
    "l0_unrestricted": PROFILE_OFF,
    "l1": PROFILE_L1,
    "l1_standard": PROFILE_L1,
    "standard": PROFILE_L1,
    "l2": PROFILE_STRICT,
    "l2_restricted": PROFILE_STRICT,
    "l3": PROFILE_STRICT,
    "l3_jail": PROFILE_STRICT,
    "jail": PROFILE_STRICT,
    "strict": PROFILE_STRICT,
}

#: 运行时开关（与 `TRIMUM_SANDBOX` 同一套口径：drop-in 写一行生效，删掉即回滚）
ENV_PROFILE = "TRIMUM_SECCOMP"

STATE_OFF = "off"
STATE_UNSUPPORTED = "unsupported"
SUFFIX_FAILED = ":failed"
SUFFIX_DEGRADED = ":degraded"

_FALSEY = {"0", "false", "no", "off"}


def normalize_profile(value: Any) -> Optional[str]:
    """把别名（含 §7.1 的 `L1_standard`）折成三档之一；不认识返回 ``None``。"""
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_")
    if not text:
        return None
    return ALIASES.get(text)


# ══════════════════════════════════════════════════════════════════════
# 系统调用清单
# ══════════════════════════════════════════════════════════════════════

#: `l1` 黑名单：危险内核面。来自 `docs/SECURITY-DEFENSE-PLAN.md` §7.2，**已按真机校正**：
#: 删掉 `swapcontext`（libc 函数，解析 = __NR_SCMP_UNDEF）与 `poweroff`（命令不是 syscall），
#: 补上 `io_uring_register` / `kcmp` / keyring / `open_by_handle_at`（后者能绕过 Landlock 的路径检查）。
KERNEL_BLOCK: tuple[str, ...] = (
    # 内核模块 / 内核热替换
    "init_module", "finit_module", "delete_module", "kexec_load", "kexec_file_load",
    # eBPF / 调试 / 跨进程读写注
    "bpf", "ptrace", "process_vm_readv", "process_vm_writev", "kcmp",
    # 性能监控 / 缺页逃逸面
    "perf_event_open", "userfaultfd",
    # io_uring（内核里最容易出逃逸面的一段）
    "io_uring_setup", "io_uring_enter", "io_uring_register",
    # 命名空间 / 挂载 / 根切换（userns 被 AppArmor 禁了，但别的命名空间还在）
    "setns", "unshare", "mount", "umount", "umount2", "pivot_root", "chroot",
    # 块设备 / 交换 / 重启
    "swapon", "swapoff", "reboot",
    # 硬件端口（x86：直接碰 I/O 端口）
    "iopl", "ioperm",
    # 内核 keyring（凭据囤积）与绕过路径检查的句柄打开
    "add_key", "keyctl", "request_key", "open_by_handle_at",
)

#: `strict` 追加面：按**地址族**挡网络 socket（不是整条 socket —— 见模块 docstring 的 RPC 理由）
_NET_FAMILIES: tuple[tuple[str, int], ...] = (
    ("AF_INET", 2),
    ("AF_INET6", 10),
    ("AF_PACKET", 17),
    ("AF_NETLINK", 16),
)

#: `strict` 追加面：其余要挡的 syscall（整条挡）
STRICT_BLOCK: tuple[str, ...] = (
    "pidfd_getfd",       # 从别的进程偷 fd
    "process_madvise",   # 跨进程内存注
    "kexec_load",        # 双保险（已在 l1）
)

#: **白名单模式**的内置基线：只够跑静态小二进制 / 最小 shell。
#: Python、动态链接程序需要 `allow` 里显式补齐（见模块 docstring 的能力边界）。
WHITELIST_BASELINE: tuple[str, ...] = (
    "read", "write", "close", "openat", "open", "stat", "fstat", "lstat", "newfstatat",
    "lseek", "pread64", "pwrite64", "readv", "writev",
    "mmap", "mprotect", "munmap", "brk", "mremap", "madvise",
    "rt_sigaction", "rt_sigprocmask", "rt_sigreturn", "sigaltstack",
    "execve", "execveat", "exit", "exit_group", "wait4", "waitid",
    "getpid", "getppid", "gettid", "getuid", "geteuid", "getgid", "getegid",
    "clock_gettime", "clock_nanosleep", "nanosleep", "gettimeofday", "times",
    "arch_prctl", "set_tid_address", "set_robust_list", "futex", "sched_yield",
    "prlimit64", "getrlimit", "getrandom", "uname", "fcntl", "dup", "dup2", "dup3",
    "pipe", "pipe2", "faccessat", "faccessat2", "getcwd", "chdir", "fchdir",
    "ioctl", "getdents64", "readlink", "readlinkat", "sysinfo", "umask", "prctl",
)

#: 块动作用的动作码（`SCMP_ACT_*`）
SCMP_ACT_ALLOW = 0x7FFF0000
SCMP_ACT_ERRNO = 0x00050000
EPERM = 1

#: libseccomp 的"本架构没有这个 syscall"哨兵（名字认识，架构没有）
_NR_SCMP_UNDEF = -10190
#: 完全不认识的名字
_NR_SCMP_ERROR = -1


# ══════════════════════════════════════════════════════════════════════
# 能力探测
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SeccompCapability:
    """本机能不能施 seccomp。``supported=False`` 时**不假装**已隔离。"""

    supported: bool
    api_level: int = 0
    library: str = ""
    reason: str = ""

    def summary(self) -> str:
        if self.supported:
            return f"supported api_level={self.api_level} lib={self.library}"
        return f"unsupported ({self.reason})"


_capability: Optional[SeccompCapability] = None
_LIB: Optional[ctypes.CDLL] = None


def _load_library() -> tuple[Optional[ctypes.CDLL], str, str]:
    """加载 libseccomp.so.2；返回 (lib, 库名, 失败原因)。"""
    try:
        lib = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    except OSError as exc:
        return None, "", f"libseccomp:{exc}"
    _declare(lib)
    return lib, "libseccomp.so.2", ""


def _declare(lib: ctypes.CDLL) -> None:
    """声明签名 —— **只有这里**声明，免得各调用点各写一份。"""
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_release.restype = None
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_api_get.restype = ctypes.c_uint
    # 参数比较（按地址族挡 socket 要用）：seccomp_rule_add 的变参版本
    lib.seccomp_rule_add_exact.restype = ctypes.c_int
    lib.seccomp_rule_add_exact.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint,
    ]


def libc_library() -> Optional[ctypes.CDLL]:
    """拿（并缓存）libseccomp 句柄；拿不到返回 ``None``。"""
    global _LIB
    if _LIB is None:
        lib, _, _ = _load_library()
        _LIB = lib
    return _LIB


def probe(refresh: bool = False) -> SeccompCapability:
    """探测 seccomp 能力（进程内缓存）。"""
    global _capability
    if refresh or _capability is None:
        _capability = _probe_uncached()
    return _capability


def _probe_uncached() -> SeccompCapability:
    if not sys.platform.startswith("linux"):
        return SeccompCapability(False, 0, "", f"platform:{sys.platform}")
    lib, name, why = _load_library()
    if lib is None:
        return SeccompCapability(False, 0, "", why)
    try:
        level = int(lib.seccomp_api_get())
    except Exception as exc:  # noqa: BLE001 - 库在但符号不对
        return SeccompCapability(False, 0, name, f"api_get:{exc}")
    if level <= 0:
        return SeccompCapability(False, 0, name, f"api_level={level}")
    return SeccompCapability(True, level, name, f"api_level={level}")


def reset_cache() -> None:
    """丢掉进程内缓存（能力 + 库句柄）。用例之间必须隔离。"""
    global _capability, _LIB
    _capability = None
    _LIB = None
# ══════════════════════════════════════════════════════════════════════
# 档案：规则解析与构建
# ══════════════════════════════════════════════════════════════════════


class SeccompError(Exception):
    """seccomp 没能按计划施加 —— 命令**不执行**（fail-closed）。"""

    def __init__(self, message: str, *, plan: "SeccompPlan | None" = None) -> None:
        super().__init__(message)
        self.plan = plan
        self.state = plan.state if plan is not None else ""

    def __str__(self) -> str:  # pragma: no cover - 直接透传 message
        return self.args[0] if self.args else "seccomp error"


@dataclass
class SeccompRule:
    """一条规则：``name`` 走 ``nr`` 号 syscall，``action`` 生效；``arg_*`` 非空时按参数比较。"""

    name: str
    nr: int
    action: int
    arg_index: Optional[int] = None
    arg_value: Optional[int] = None
    note: str = ""

    def describe(self) -> str:
        verdict = "allow" if self.action == SCMP_ACT_ALLOW else "deny"
        if self.arg_index is None:
            return f"{verdict:5s} {self.name}({self.nr})"
        return f"{verdict:5s} {self.name}({self.nr}) if arg{self.arg_index}=={self.arg_value}"


@dataclass
class SeccompPlan:
    """一轮派生要施的 seccomp 计划（+ 实际结果）。

    ``state`` 与 ``SandboxPlan`` 同词表：
    ``off`` / ``unsupported`` / ``l1|strict`` / ``<profile>:failed`` / ``<profile>:degraded``。
    """

    profile: str = DEFAULT_PROFILE
    supported: bool = False
    api_level: int = 0
    fail_closed: bool = True
    reason: str = ""
    whitelist: bool = False
    default_action: int = SCMP_ACT_ALLOW
    rules: list[SeccompRule] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    state: str = ""
    target: Any = None

    @property
    def enforcing(self) -> bool:
        return self.supported and self.profile != PROFILE_OFF

    @property
    def denied(self) -> int:
        return sum(1 for rule in self.rules if rule.action != SCMP_ACT_ALLOW)

    @property
    def allowed(self) -> int:
        return sum(1 for rule in self.rules if rule.action == SCMP_ACT_ALLOW)

    def summary(self) -> str:
        if self.state == STATE_OFF:
            return "off (seccomp 未施加)"
        if not self.supported:
            return f"unsupported ({self.reason})"
        mode = "whitelist" if self.whitelist else "denylist"
        return (
            f"{self.profile} api_level={self.api_level} mode={mode} "
            f"deny={self.denied} allow={self.allowed} unknown={len(self.unknown)}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "state": self.state,
            "supported": self.supported,
            "api_level": self.api_level,
            "mode": "whitelist" if self.whitelist else "denylist",
            "deny": self.denied,
            "allow": self.allowed,
            "unknown": list(self.unknown),
            "notes": list(self.notes),
        }


def _resolver_default(name: str, lib: Optional[ctypes.CDLL]) -> int:
    """默认解析器：走 libseccomp 的名字表（拿不到库时返回 -1）。"""
    if lib is None:
        return _NR_SCMP_ERROR
    return int(lib.seccomp_syscall_resolve_name(name.encode("utf-8")))


def as_names(value: Any) -> list[str]:
    """把 ``seccomp_allow`` / ``seccomp_block`` 这类声明折成名字列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        value = [item.strip() for item in value.replace(",", " ").split()]
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _add(
    plan: SeccompPlan,
    name: str,
    action: int,
    *,
    resolver: Callable[[str], int],
    arg_index: Optional[int] = None,
    arg_value: Optional[int] = None,
    note: str = "",
) -> None:
    nr = resolver(name)
    if nr in (_NR_SCMP_ERROR, _NR_SCMP_UNDEF):
        # 本架构没有 / 根本不认识 —— **不当致命错误**（文档清单里就有这种名字），
        # 记进 unknown，让审计看得见"这条没施上"。
        plan.unknown.append(name)
        return
    plan.rules.append(
        SeccompRule(name=name, nr=nr, action=action, arg_index=arg_index, arg_value=arg_value, note=note)
    )


def _dedupe(plan: SeccompPlan) -> None:
    """同名同参数的规则只留第一条（先加的优先，便于"声明 > 内置"）。"""
    seen: set[tuple[str, Optional[int], Optional[int]]] = set()
    kept: list[SeccompRule] = []
    for rule in plan.rules:
        key = (rule.name, rule.arg_index, rule.arg_value)
        if key in seen:
            continue
        seen.add(key)
        kept.append(rule)
    plan.rules = kept


def build_plan(
    profile: Any = None,
    *,
    allow: Iterable[str] = (),
    block: Iterable[str] = (),
    resolver: Optional[Callable[[str], int]] = None,
    lib: Optional[ctypes.CDLL] = None,
    capability: Optional[SeccompCapability] = None,
    fail_closed: bool = True,
    target: Any = None,
) -> SeccompPlan:
    """按档位 + 声明构建档案（**纯计算**，不施加；施加是 ``apply_current``）。

    ``resolver`` / ``lib`` / ``capability`` 都可注入，用例才能在 Windows 上把逻辑跑全
    （真机那条路用默认值）。
    """
    capability = capability if capability is not None else probe()
    resolved = normalize_profile(profile) if profile is not None else DEFAULT_PROFILE

    plan = SeccompPlan(
        profile=resolved or str(profile),
        supported=capability.supported,
        api_level=capability.api_level,
        fail_closed=fail_closed,
        reason=capability.reason,
        target=target,
    )

    if resolved is None:
        plan.state = f"{plan.profile}{SUFFIX_FAILED}"
        plan.notes.append(f"未知的 seccomp 档位 '{plan.profile}'（可选：{', '.join(PROFILES)}）")
        return plan

    plan.profile = resolved

    if resolved == PROFILE_OFF:
        plan.state = STATE_OFF
        return plan

    if not capability.supported:
        plan.state = STATE_UNSUPPORTED
        return plan

    if resolver is None:
        handle = lib if lib is not None else libc_library()
        resolver = lambda name: _resolver_default(name, handle)  # noqa: E731 - 单一闭包，便于注入

    allow_names = as_names(allow)
    block_names = as_names(block)

    if resolved == PROFILE_STRICT and allow_names:
        # 白名单模式：默认拒绝 + 内置基线 + 声明放行
        plan.whitelist = True
        plan.default_action = SCMP_ACT_ERRNO | EPERM
        plan.notes.append(
            "白名单模式（seccomp_allow 非空）：内置基线只够跑静态小二进制，"
            "Python / 动态链接程序需要显式补齐 syscall"
        )
        for name in allow_names:
            _add(plan, name, SCMP_ACT_ALLOW, resolver=resolver, note="声明放行")
        for name in WHITELIST_BASELINE:
            _add(plan, name, SCMP_ACT_ALLOW, resolver=resolver, note="内置基线")
    elif allow_names:
        # 非 strict 档要"额外放行" = 放宽，不认
        plan.notes.append(
            f"seccomp_allow 只在 strict 档有效（当前 {resolved}）；已忽略：{', '.join(allow_names)}"
        )

    if not plan.whitelist:
        # 黑名单形态：先加声明的拦截（声明优先），再加内置清单
        for name in block_names:
            _add(plan, name, SCMP_ACT_ERRNO | EPERM, resolver=resolver, note="声明拦截")
        for name in KERNEL_BLOCK:
            _add(plan, name, SCMP_ACT_ERRNO | EPERM, resolver=resolver, note="内置危险内核面")

        # strict 追加的部分只属于黑名单形态：白名单模式下默认动作已经是 EPERM，
        # 再叠拦截规则是纯噪声（还会让 summary 的 deny 计数误导人）
        if resolved == PROFILE_STRICT:
            for name in STRICT_BLOCK:
                _add(plan, name, SCMP_ACT_ERRNO | EPERM, resolver=resolver, note="strict 追加")
            # 网络 socket：**按地址族**挡，AF_UNIX 放行（子 Agent 的 RPC 靠它）
            for family_name, family_value in _NET_FAMILIES:
                _add(
                    plan,
                    "socket",
                    SCMP_ACT_ERRNO | EPERM,
                    resolver=resolver,
                    arg_index=0,
                    arg_value=family_value,
                    note=f"strict：挡 {family_name}（AF_UNIX 仍放行）",
                )

    _dedupe(plan)

    if not plan.rules:
        plan.state = f"{plan.profile}{SUFFIX_FAILED}"
        plan.notes.append("档案是空的（一条规则都没施上）")
        return plan

    plan.state = plan.profile
    return plan


# ══════════════════════════════════════════════════════════════════════
# 施加（**只在子进程 / `python -m` 里调用**）
# ══════════════════════════════════════════════════════════════════════


class _ScmpArgCmp(ctypes.Structure):
    """`struct scmp_arg_cmp`（libseccomp 头文件）：u32 + enum(int) + u64 + u64 = 24 字节。"""

    _fields_ = [
        ("arg", ctypes.c_uint),
        ("op", ctypes.c_int),
        ("datum_a", ctypes.c_uint64),
        ("datum_b", ctypes.c_uint64),
    ]


#: `SCMP_CMP_EQ` —— `enum scmp_compare` 是从 `_SCMP_CMP_MIN = 0` 起算的，所以 **EQ 是 4 不是 0**。
#: 填 0 会被 libseccomp 判成非法算子，`seccomp_rule_add` 直接返回 `-EINVAL`（真机实测：
#: op=0 → rc=-22，op=4 → rc=0；见 docs/SANDBOX-PLAN.md §11.3）。
_SCMP_CMP_EQ = 4


#: `seccomp_rule_add` 有两个原型（0 个 / 1 个参数比较）—— ctypes 的 argtypes 必须在调用前
#: 切到对应的那个，否则带参数的那条会因为「参数多一个」被 ctypes 直接拒掉（根本落不到 C 里）。
_ARG_NO_CMP = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
_ARG_ONE_CMP = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint, _ScmpArgCmp]


def _rule_add(lib: ctypes.CDLL, ctx: Any, rule: SeccompRule) -> int:
    """加一条规则；带参数比较时传 ``scmp_arg_cmp``（libseccomp 的变参接口）。"""
    if rule.arg_index is None:
        lib.seccomp_rule_add.argtypes = _ARG_NO_CMP
        return int(
            lib.seccomp_rule_add(
                ctypes.c_void_p(ctx),
                ctypes.c_uint32(rule.action),
                ctypes.c_int(rule.nr),
                ctypes.c_uint(0),
            )
        )
    cmp_struct = _ScmpArgCmp(
        arg=rule.arg_index, op=_SCMP_CMP_EQ, datum_a=rule.arg_value or 0, datum_b=0
    )
    lib.seccomp_rule_add.argtypes = _ARG_ONE_CMP
    return int(
        lib.seccomp_rule_add(
            ctypes.c_void_p(ctx),
            ctypes.c_uint32(rule.action),
            ctypes.c_int(rule.nr),
            ctypes.c_uint(1),
            cmp_struct,
        )
    )

def apply_current(plan: SeccompPlan, *, lib: Optional[ctypes.CDLL] = None) -> None:
    """在**当前进程**里施加 ``plan``（不可逆，且会被后代继承）。

    只准两个地方调：`sandbox_exec` 的 preexec 钩子（子进程里）与 ``python -m``。
    """
    if not plan.rules:
        raise SeccompError("seccomp 档案是空的（没有可加的规则）", plan=plan)

    lib = lib if lib is not None else libc_library()
    if lib is None:
        raise SeccompError("libseccomp 不可用", plan=plan)

    ctx = lib.seccomp_init(ctypes.c_uint32(plan.default_action))
    if not ctx:
        err = ctypes.get_errno()
        raise SeccompError(
            f"seccomp_init 失败：errno={err} ({os.strerror(err) if err else 'unknown'})", plan=plan
        )

    try:
        for rule in plan.rules:
            rc = _rule_add(lib, ctx, rule)
            if rc != 0:
                raise SeccompError(f"seccomp_rule_add 失败 {rule.name}：rc={rc}", plan=plan)
        rc = int(lib.seccomp_load(ctypes.c_void_p(ctx)))
        if rc != 0:
            err = ctypes.get_errno()
            raise SeccompError(
                f"seccomp_load 失败：rc={rc} errno={err} ({os.strerror(err) if err else 'unknown'})",
                plan=plan,
            )
    finally:
        try:
            lib.seccomp_release(ctypes.c_void_p(ctx))
        except Exception:  # noqa: BLE001 - 释放失败不该盖住真错误
            pass


def _config_profile() -> Optional[str]:
    """读 ``security.yaml`` 的 ``sandbox.seccomp``（拿不到就 None，让调用方用默认）。"""
    try:
        from .security_config import SecurityConfig

        raw = SecurityConfig().get_sandbox_config()
        return raw.get("seccomp") if isinstance(raw, dict) else None
    except Exception:  # noqa: BLE001 - 配置坏了不该让状态查询炸掉
        return None


def current_state() -> str:
    """给审计/CLI 用的一句话状态（含能力探测）。"""
    capability = probe()
    raw = os.environ.get(ENV_PROFILE)
    if raw is None or not str(raw).strip():
        raw = _config_profile()
    profile = normalize_profile(raw) if raw else DEFAULT_PROFILE
    if profile is None:
        return str(raw)
    if profile == PROFILE_OFF:
        return STATE_OFF
    if not capability.supported:
        return STATE_UNSUPPORTED
    return profile


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m trimum_core.seccomp_exec`` —— 独立施加，供真机验收与排障。

    用法::

        python -m trimum_core.seccomp_exec --status
        python -m trimum_core.seccomp_exec --profile l1 -- python3 -c 'print(1)'
        python -m trimum_core.seccomp_exec --profile strict -- python3 -c 'import socket; socket.socket(socket.AF_INET)'
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m trimum_core.seccomp_exec",
        description="trimum Layer K —— 在子进程里施加 seccomp（不可逆）",
    )
    parser.add_argument("--status", action="store_true", help="只打印档案，不施加")
    parser.add_argument("--profile", default=None, help="l1 | strict | off（也认 L1_standard 等别名）")
    parser.add_argument("--allow", action="append", default=[], help="声明放行（strict 下非空 ⇒ 白名单模式）")
    parser.add_argument("--block", action="append", default=[], help="额外拦截（可多次）")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="要执行的命令")
    args = parser.parse_args(list(argv) if argv is not None else None)

    capability = probe()
    plan = build_plan(
        args.profile,
        allow=args.allow,
        block=args.block,
        capability=capability,
        fail_closed=True,
    )

    if args.status or not args.cmd:
        print(f"capability : {capability.summary()}")
        print(f"plan       : {plan.summary()}")
        print(f"state      : {plan.state}")
        for name in plan.unknown:
            print(f"  unknown  : {name}（本架构没有 / libseccomp 不认识）")
        for note in plan.notes:
            print(f"  note     : {note}")
        for rule in plan.rules:
            print(f"  rule     : {rule.describe()}")
        return 0

    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        parser.error("没有可执行的命令")

    if plan.profile == PROFILE_OFF or plan.state == STATE_UNSUPPORTED:
        # off 档 / 平台不支持：明确**不施加**，照旧执行（与 apply_plan 同一口径：
        # 「没施」不等于「施失败」—— 别把一键退变成起不来）
        os.execvp(cmd[0], cmd)

    if not plan.rules:
        print(
            f"trimum seccomp: 档案不可用（state={plan.state}）："
            f"{'; '.join(plan.notes) or '没有可加的规则'}",
            file=sys.stderr,
        )
        return 126

    try:
        apply_current(plan)
    except SeccompError as exc:
        print(f"trimum seccomp: {exc}", file=sys.stderr)
        return 126
    os.execvp(cmd[0], cmd)
    return 0  # pragma: no cover - execvp 不返回


__all__ = [
    "ALIASES",
    "DEFAULT_PROFILE",
    "ENV_PROFILE",
    "KERNEL_BLOCK",
    "PROFILES",
    "PROFILE_RANK",
    "PROFILE_L1",
    "PROFILE_OFF",
    "PROFILE_STRICT",
    "STRICT_BLOCK",
    "STATE_OFF",
    "STATE_UNSUPPORTED",
    "WHITELIST_BASELINE",
    "SeccompCapability",
    "SeccompError",
    "SeccompPlan",
    "SeccompRule",
    "as_names",
    "apply_current",
    "build_plan",
    "current_state",
    "main",
    "normalize_profile",
    "probe",
    "reset_cache",
]


if __name__ == "__main__":  # pragma: no cover - 独立入口
    raise SystemExit(main())
