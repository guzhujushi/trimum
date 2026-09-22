"""Layer K —— 内核层沙箱「施加点」（S2 落地，2026-09-22）。

设计出处：``docs/SANDBOX-PLAN.md`` §6.1（六个派生点必须收到一处）、§6.2（内核层与
既有四层网关**串联**而不是并列）、§6.5（平台降级「明确报不支持」，不许「不知道就放行」）。

三条已实测的事实决定了这个模块的形状（PoC 见该文 §5）：

1. **零依赖**：Landlock 三个 syscall（444/445/446）+ ``prctl(PR_SET_NO_NEW_PRIVS)``
   全走 ``ctypes`` —— 不要 pip 包、不要 root、不要 ``-dev`` 头文件。
2. **跨 execve 继承**：限制施加在施加者**及其后代**上。所以只要在「派生子进程的那个点」
   施一次，整棵进程树（shell → 测试进程 → 编译器）都被覆盖；反过来，**绝不能在 daemon
   自己身上施** —— Landlock 只能收紧、不可逆。
3. **只能收紧、不可逆**：进程无法自我放宽，多层规则叠加（上限 16 层）。

因此施加点是 **preexec 钩子**（``subprocess`` 的 ``preexec_fn``）：fork 之后、exec 之前，
在**子进程里**施一次。分工是刻意的：

* 父进程只做判定（模式合法性 / 平台与内核能力 / 路径是否存在），判定不过**就不再派生**；
* 子进程里施失败 → ``SubprocessError`` → 命令**根本不会被执行**（fail-closed）。

已知取舍（写进文档，不装作没有）：

* ``preexec_fn`` 在多线程进程里调用是 CPython 文档点名的「不保证安全」。缓解：能失败的
  判定都在父进程做完，子进程里只剩 syscall；ctypes 结构体也在父进程预先建好。
* ABI 4 没有 ``FS_IOCTL_DEV``（设备 ioctl 不设限），也没有抽象 UNIX socket / signal 域
  （ABI 6 / kernel 6.12+ 才有）⇒ **不承诺 socket 维度隔离**（含 trimum 自己的 RPC socket）。
* 允许清单**列漏 = 运行时才炸**：默认只放开「工作区 + 临时目录 + trimum 数据目录 + 设备面」，
  pip/npm 之类的包缓存（``~/.cache`` / ``~/.local``）**故意不放**（那是持久化面）。
  用到时用 ``sandbox.write_paths`` 显式加，或 ``TRIMUM_SANDBOX=off`` 一键退。
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .logger import get_logger
from .paths import trimum_home

logger = get_logger("trimum_core.sandbox_exec")


# ══════════════════════════════════════════════════════════════════════
# 模式与状态
# ══════════════════════════════════════════════════════════════════════

MODE_OFF = "off"
MODE_READONLY = "readonly"
MODE_WORKSPACE = "workspace-write"
MODE_STRICT = "strict"
MODES: tuple[str, ...] = (MODE_READONLY, MODE_WORKSPACE, MODE_STRICT, MODE_OFF)
DEFAULT_MODE = MODE_WORKSPACE

#: 从宽到严（数字越小越严）。agent.json5 的 sandbox 段只能往严里收，不能放宽 ——
#: 否则一个 `trm install` 来的包就能在 manifest 里写 `mode: off` 把自己放出来。
_MODE_RANK = {MODE_OFF: 3, MODE_WORKSPACE: 2, MODE_STRICT: 1, MODE_READONLY: 0}

#: 运行时开关（systemd drop-in 一行生效，删掉即回滚，与 TRIMUM_HTTP 同一口径）。
ENV_MODE = "TRIMUM_SANDBOX"
ENV_FAIL_CLOSED = "TRIMUM_SANDBOX_FAIL_CLOSED"

STATE_OFF = "off"
STATE_UNSUPPORTED = "unsupported"
SUFFIX_FAILED = ":failed"
SUFFIX_DEGRADED = ":degraded"

_FALSEY = {"0", "false", "no", "off"}


# ══════════════════════════════════════════════════════════════════════
# Landlock 常量（uapi/linux/landlock.h）
# ══════════════════════════════════════════════════════════════════════

_SYS_CREATE_RULESET = 444
_SYS_ADD_RULE = 445
_SYS_RESTRICT_SELF = 446
_PR_SET_NO_NEW_PRIVS = 38

_RULE_PATH_BENEATH = 1
_CREATE_RULESET_VERSION = 1

_A_EXECUTE = 1 << 0
_A_WRITE_FILE = 1 << 1
_A_READ_FILE = 1 << 2
_A_READ_DIR = 1 << 3
_A_REMOVE_DIR = 1 << 4
_A_REMOVE_FILE = 1 << 5
_A_MAKE_CHAR = 1 << 6
_A_MAKE_DIR = 1 << 7
_A_MAKE_REG = 1 << 8
_A_MAKE_SOCK = 1 << 9
_A_MAKE_FIFO = 1 << 10
_A_MAKE_BLOCK = 1 << 11
_A_MAKE_SYM = 1 << 12
_A_REFER = 1 << 13      # ABI >= 2
_A_TRUNCATE = 1 << 14   # ABI >= 3
_A_IOCTL_DEV = 1 << 15  # ABI >= 5（6.8 = ABI 4，所以默认拿不到）

_ABI1_FS = (
    _A_EXECUTE | _A_WRITE_FILE | _A_READ_FILE | _A_READ_DIR
    | _A_REMOVE_DIR | _A_REMOVE_FILE
    | _A_MAKE_CHAR | _A_MAKE_DIR | _A_MAKE_REG | _A_MAKE_SOCK
    | _A_MAKE_FIFO | _A_MAKE_BLOCK | _A_MAKE_SYM
)


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    # 内核里是 `__attribute__((packed))`：u64 + s32 = 12 字节
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


_LIBC: Optional[ctypes.CDLL] = None


def _libc() -> ctypes.CDLL:
    """载入 libc（``syscall`` 走它；带 ``use_errno`` 才能读 errno）。"""
    global _LIBC
    if _LIBC is None:
        lib = ctypes.CDLL(None, use_errno=True)
        lib.syscall.restype = ctypes.c_long
        lib.prctl.restype = ctypes.c_int
        lib.prctl.argtypes = [
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        _LIBC = lib
    return _LIBC


def _handled_mask(abi: int) -> int:
    mask = _ABI1_FS
    if abi >= 2:
        mask |= _A_REFER
    if abi >= 3:
        mask |= _A_TRUNCATE
    if abi >= 5:
        mask |= _A_IOCTL_DEV
    return mask


def _read_rights(abi: int) -> int:
    # EXECUTE 是给 /usr/bin 这类东西用的（Landlock 的 EXECUTE 只是「允许执行」，
    # 文件本身还得有 x 位），读根一律带上，否则连 cat 都起不来。
    _ = abi
    return _A_EXECUTE | _A_READ_FILE | _A_READ_DIR


def _write_rights(abi: int) -> int:
    mask = _read_rights(abi) | _A_WRITE_FILE | _A_REMOVE_DIR | _A_REMOVE_FILE
    mask |= (
        _A_MAKE_CHAR | _A_MAKE_DIR | _A_MAKE_REG | _A_MAKE_SOCK
        | _A_MAKE_FIFO | _A_MAKE_BLOCK | _A_MAKE_SYM
    )
    if abi >= 2:
        mask |= _A_REFER
    if abi >= 3:
        mask |= _A_TRUNCATE
    return mask


def _file_write_rights(abi: int) -> int:
    # 非目录只能给文件级权限：给 MAKE_*/REMOVE_* 会被内核判 EINVAL
    mask = _A_EXECUTE | _A_WRITE_FILE | _A_READ_FILE
    if abi >= 3:
        mask |= _A_TRUNCATE
    if abi >= 5:
        mask |= _A_IOCTL_DEV
    return mask


# ══════════════════════════════════════════════════════════════════════
# 路径档案（三档）
# ══════════════════════════════════════════════════════════════════════

#: strict 档的读白名单（读写都不放开「任意路径」）
_SYSTEM_READ = (
    "/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/proc", "/sys", "/dev",
)

#: 任何档都保留的最小可写面 —— 否则连 `cmd 2>/dev/null` 都跑不了。
_ALWAYS_WRITE = (
    "/dev/null", "/dev/zero", "/dev/full", "/dev/random", "/dev/urandom",
    "/dev/tty", "/dev/console", "/dev/ptmx", "/dev/pts", "/dev/shm",
    "/dev/fd", "/dev/stdin", "/dev/stdout", "/dev/stderr",
)

#: 落在这些前缀下的 cwd **不当作工作区**（系统面 + 持久化面）
_NEVER_WORKSPACE = (
    "/", "/etc", "/usr", "/boot", "/efi", "/bin", "/sbin", "/lib", "/lib64",
    "/proc", "/sys", "/dev", "/run", "/var",
)

#: 临时面
_TMP_ROOTS = ("/tmp", "/var/tmp")


# ══════════════════════════════════════════════════════════════════════
# 能力探测
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SandboxCapability:
    """本机能不能施内核层沙箱。``supported=False`` 时**不假装**已隔离。"""

    supported: bool
    abi: int = 0
    reason: str = ""

    def summary(self) -> str:
        if self.supported:
            return f"supported abi={self.abi}"
        return f"unsupported ({self.reason})"


_capability: Optional[SandboxCapability] = None
_unsupported_warned = False


def probe(refresh: bool = False) -> SandboxCapability:
    """探测 Landlock 能力（进程内缓存）。"""
    global _capability
    if refresh or _capability is None:
        _capability = _probe_uncached()
    return _capability


def _probe_uncached() -> SandboxCapability:
    if not sys.platform.startswith("linux"):
        return SandboxCapability(False, 0, f"platform:{sys.platform}")
    try:
        lib = _libc()
    except OSError as exc:  # pragma: no cover - libc 一定在
        return SandboxCapability(False, 0, f"libc:{exc}")
    ctypes.set_errno(0)
    abi = lib.syscall(
        ctypes.c_long(_SYS_CREATE_RULESET),
        ctypes.c_void_p(0),
        ctypes.c_size_t(0),
        ctypes.c_uint(_CREATE_RULESET_VERSION),
    )
    if abi < 0:
        err = ctypes.get_errno()
        detail = os.strerror(err) if err else "unknown"
        return SandboxCapability(False, 0, f"landlock errno={err} ({detail})")
    return SandboxCapability(True, int(abi), f"abi={int(abi)}")


# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

_CONFIG: Optional[dict[str, Any]] = None


def load_config() -> dict[str, Any]:
    """读 ``security.yaml`` 的 ``sandbox:`` 段（缓存；失败退回内置默认）。"""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = _read_config()
    return _CONFIG


def _read_config() -> dict[str, Any]:
    try:
        from .security_config import SecurityConfig

        raw = SecurityConfig().get_sandbox_config()
    except Exception as exc:  # noqa: BLE001 - 配置坏了不该让派生点炸掉
        logger.warning("sandbox.config_load_failed", error=str(exc))
        return {}
    return raw if isinstance(raw, dict) else {}


def reset_cache() -> None:
    """丢掉进程内缓存（能力探测 + 配置 + 一次性告警）。用例之间必须隔离。"""
    global _CONFIG, _capability, _unsupported_warned
    _CONFIG = None
    _capability = None
    _unsupported_warned = False


def _resolve_fail_closed(cfg: dict[str, Any]) -> bool:
    """fail_closed 口径：内置 ``true`` < ``security.yaml`` < 环境变量。

    环境变量必须**最后**说话：它是「一键退」的抓手（``TRIMUM_SANDBOX_FAIL_CLOSED=0``
    在 systemd drop-in 里写一行就生效），而 security.yaml 的默认值永远是 ``true``。
    """
    value = True
    raw_cfg = cfg.get("fail_closed")
    if isinstance(raw_cfg, bool):
        value = raw_cfg
    raw_env = os.environ.get(ENV_FAIL_CLOSED)
    if raw_env is not None and str(raw_env).strip():
        value = str(raw_env).strip().lower() not in _FALSEY
    return value


def _warn_unsupported_once(mode: str, reason: str) -> None:
    """「本机不支持」只喊一次 —— 它是环境属性，不是每次派生都要喊的事。"""
    global _unsupported_warned
    if _unsupported_warned:
        return
    _unsupported_warned = True
    logger.warning(
        "sandbox.unsupported",
        mode=mode,
        reason=reason,
        detail="内核层未施加：命令照跑，但审计里如实记 unsupported（不是放行）",
    )


# ══════════════════════════════════════════════════════════════════════
# 档案与计划
# ══════════════════════════════════════════════════════════════════════


class SandboxError(Exception):
    """沙箱没能按计划施加 —— 命令**不执行**（fail-closed）。

    ``plan`` 带上现场（模式 / 原因 / 哪一步），审计与排障都从这里取。
    """

    def __init__(self, message: str, *, plan: "SandboxPlan | None" = None) -> None:
        super().__init__(message)
        self.plan = plan
        self.state = plan.state if plan is not None else ""

    def __str__(self) -> str:  # pragma: no cover - 直接透传 message
        return self.args[0] if self.args else "sandbox error"


@dataclass
class SandboxPlan:
    """一轮派生要施的沙箱计划（+ 实际结果）。

    ``state`` 是审计口径的唯一来源：
    ``off`` / ``unsupported`` / ``readonly|workspace-write|strict`` /
    ``<mode>:failed``（施加失败、命令没跑）/ ``<mode>:degraded``（关了 fail-closed、没施上照跑）。
    """

    mode: str = DEFAULT_MODE
    supported: bool = False
    abi: int = 0
    fail_closed: bool = True
    reason: str = ""
    read_roots: list[str] = field(default_factory=list)
    write_roots: list[str] = field(default_factory=list)
    rules: list[tuple[str, int]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    state: str = ""
    target: Any = None

    @property
    def enforcing(self) -> bool:
        """该不该真的施加（关掉 / 平台不支持 / 有 blocker 时都不施）。"""
        return self.supported and self.mode != MODE_OFF and not self.blockers

    def summary(self) -> str:
        if self.state == STATE_OFF:
            return "off (内核层未施加)"
        if not self.supported:
            return f"unsupported ({self.reason})"
        return (
            f"{self.mode} abi={self.abi} fail_closed={str(self.fail_closed).lower()} "
            f"read={len(self.read_roots)} write={len(self.write_roots)}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "state": self.state,
            "supported": self.supported,
            "abi": self.abi,
            "fail_closed": self.fail_closed,
            "reason": self.reason,
            "read_roots": list(self.read_roots),
            "write_roots": list(self.write_roots),
            "blockers": list(self.blockers),
        }


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _sync(plan: SandboxPlan) -> None:
    """把 ``plan.state`` 写回绑定的目标（``ExecuteRequest.sandbox`` / 同名字典键）。"""
    target = plan.target
    if target is None:
        return
    try:
        if isinstance(target, dict):
            target["sandbox"] = plan.state
        else:
            setattr(target, "sandbox", plan.state)
    except Exception:  # noqa: BLE001 - 回写失败不该影响是否施加
        logger.debug("sandbox.state_writeback_failed", state=plan.state)


def _declared(manifest: Any) -> dict[str, Any]:
    raw = _field(manifest, "sandbox", None)
    return raw if isinstance(raw, dict) else {}


def _as_paths(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, os.PathLike)):
        value = [value]
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(str(Path(text).expanduser()))
    return out


def _resolve_mode(*, explicit: Optional[str], env: Optional[str], declared: dict[str, Any], cfg: dict[str, Any]) -> str:
    base = (explicit or env or cfg.get("mode") or DEFAULT_MODE)
    base = str(base).strip() or DEFAULT_MODE
    declared_mode = declared.get("mode") or declared.get("profile")
    if isinstance(declared_mode, str) and declared_mode.strip():
        # manifest 只能收紧：rank 更小才采用
        if declared_mode.strip() in _MODE_RANK and base in _MODE_RANK:
            if _MODE_RANK[declared_mode.strip()] < _MODE_RANK[base]:
                return declared_mode.strip()
    return base


def _is_workspace(path: str) -> bool:
    """这个 cwd 配不配当「工作区」（可以给写权限）？"""
    resolved = Path(path).resolve()
    text = str(resolved)
    for blocked in _NEVER_WORKSPACE:
        if text == blocked or text == blocked.rstrip("/"):
            return False
        if blocked != "/" and text.startswith(blocked.rstrip("/") + "/"):
            return False
    return True


def _collect(candidates: Iterable[str], *, kind: str, seen: set[str]) -> list[str]:
    """过滤掉不存在的路径（**不** fail-closed：默认档案里的路径允许缺席）。"""
    out: list[str] = []
    for raw in candidates:
        if not raw:
            continue
        path = str(Path(raw).expanduser())
        if path in seen:
            continue
        if not os.path.exists(path):
            logger.debug("sandbox.root_missing", path=path, kind=kind)
            continue
        seen.add(path)
        out.append(path)
    return out


def _socket_dirs() -> list[str]:
    """RPC socket 所在目录：子进程连 daemon 需要 socket 文件上的写权限。"""
    dirs: list[str] = []
    env_socket = os.environ.get("TRIMUM_SOCKET")
    if env_socket:
        dirs.append(str(Path(env_socket).parent))
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        dirs.append(str(Path(runtime_dir)))
    try:
        from .config import SYSTEM_RUNTIME_SOCKET

        dirs.append(str(SYSTEM_RUNTIME_SOCKET.parent))
    except Exception:  # noqa: BLE001
        dirs.append("/run/trimum")
    return dirs


def plan_for(
    request: Any = None,
    *,
    cwd: str | os.PathLike[str] | None = None,
    mode: Optional[str] = None,
    extra_read: Iterable[str] = (),
    extra_write: Iterable[str] = (),
    base: str | os.PathLike[str] | None = None,
) -> SandboxPlan:
    """解析本轮该施的沙箱档案，并把初始状态回写到 ``request.sandbox``。

    ``request`` 可以是 ``ExecuteRequest``（对象）或 dict（``cli_adapter`` 那条路拿到的
    是 dump 出来的 dict）。工作区取 ``request.cwd`` → manifest 的 ``work_dir`` →
    ``cwd`` 参数 → 进程 cwd，且必须是「配当工作区」的路径。
    """
    cfg = load_config()
    manifest = _field(request, "agent_manifest", None)
    declared = _declared(manifest)
    capability = probe()
    fail_closed = _resolve_fail_closed(cfg)

    resolved = _resolve_mode(
        explicit=mode,
        env=os.environ.get(ENV_MODE),
        declared=declared,
        cfg=cfg,
    )

    plan = SandboxPlan(
        mode=resolved,
        supported=capability.supported,
        abi=capability.abi,
        fail_closed=fail_closed,
        reason=capability.reason,
        target=request,
    )

    if resolved not in MODES:
        plan.blockers.append(
            f"未知的沙箱档位 '{resolved}'（可选：{', '.join(MODES)}）"
        )
        plan.state = resolved + SUFFIX_FAILED
        _sync(plan)
        logger.error("sandbox.bad_mode", mode=resolved)
        return plan

    if resolved == MODE_OFF:
        plan.state = STATE_OFF
        _sync(plan)
        return plan

    if not capability.supported:
        # 平台 / 内核不支持：**不解析档案、不假装** —— 如实报 unsupported。
        # 默认路径集是 Linux 形状的，在别的平台上算出来只会是一堆不存在的路径。
        plan.state = STATE_UNSUPPORTED
        _warn_unsupported_once(resolved, capability.reason)
        _sync(plan)
        return plan

    workspace_candidates = [
        _field(request, "cwd", None),
        cwd,
        base,
        _field(manifest, "work_dir", None),
        os.getcwd(),
    ]
    workspace = ""
    for item in workspace_candidates:
        if not item:
            continue
        text = str(Path(str(item)).expanduser())
        if os.path.isdir(text) and _is_workspace(text):
            workspace = str(Path(text).resolve())
            break

    cfg_write = _as_paths(cfg.get("write_paths")) + _as_paths(extra_write)
    cfg_read = _as_paths(cfg.get("read_paths")) + _as_paths(extra_read)
    declared_read = _as_paths(declared.get("read") or declared.get("fs_read") or declared.get("allowed_read"))
    declared_write = _as_paths(
        declared.get("write") or declared.get("fs_write") or declared.get("allowed_write")
    )
    if declared_write:
        # 包的 manifest 不许放宽可写面（见 _MODE_RANK 的注释）
        logger.warning(
            "sandbox.manifest_write_ignored",
            agent=_field(manifest, "name", "?"),
            paths=declared_write,
        )

    data_root = str(trimum_home())
    trimum_data_dir = str(Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "trimum")
    readonly = resolved == MODE_READONLY
    strict = resolved == MODE_STRICT

    if strict:
        read_candidates = [*_SYSTEM_READ, workspace, data_root, trimum_data_dir, *declared_read, *cfg_read]
    else:
        read_candidates = ["/", workspace, data_root, trimum_data_dir, *declared_read, *cfg_read]

    write_candidates = [
        *_ALWAYS_WRITE,
        *_socket_dirs(),
        workspace,
        data_root,
        trimum_data_dir,
    ]
    if not readonly:
        # readonly 档故意连临时面都不放开：审阅 / 探索类任务不该有落盘面
        write_candidates.extend(_TMP_ROOTS)
        write_candidates.extend(cfg_write)

    read_seen: set[str] = set()
    plan.read_roots = _collect(read_candidates, kind="read", seen=read_seen)
    write_seen: set[str] = set()
    plan.write_roots = _collect(write_candidates, kind="write", seen=write_seen)
    # 既是读根又是写根 → 只留写规则（写权限是读权限的超集）
    plan.read_roots = [path for path in plan.read_roots if path not in write_seen]
    plan.rules = _build_rules(plan)

    if not plan.read_roots:
        plan.blockers.append("没有任何可用的只读根（连 / 都不可访问？）")

    plan.state = resolved + SUFFIX_FAILED if plan.blockers else resolved
    _sync(plan)
    return plan


def _build_rules(plan: SandboxPlan) -> list[tuple[str, int]]:
    rules: dict[str, int] = {}
    for path in plan.read_roots:
        rules[path] = _read_rights(plan.abi)
    for path in plan.write_roots:
        rights = (
            _write_rights(plan.abi)
            if os.path.isdir(path)
            else _file_write_rights(plan.abi)
        )
        rules[path] = rights
    # 父目录先加、子目录后加：语义上不要求顺序，排序只为日志好读
    return sorted(rules.items(), key=lambda item: (item[0].count("/"), item[0]))


# ══════════════════════════════════════════════════════════════════════
# 施加（**只在子进程 / `python -m` 里调用**）
# ══════════════════════════════════════════════════════════════════════


def apply_current(plan: SandboxPlan) -> None:
    """在**当前进程**里施加 ``plan`` 的规则（不可逆！）。

    只准两个地方调：preexec 钩子（子进程里）与 ``python -m trimum_core.sandbox_exec``。
    **绝不要在 daemon 自己身上调** —— Landlock 只能收紧，施上就退不下来了。
    """
    if not plan.rules:
        raise SandboxError("沙箱档案是空的（没有可加的规则）", plan=plan)

    lib = _libc()
    handled = _handled_mask(plan.abi)

    ctypes.set_errno(0)
    if lib.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        err = ctypes.get_errno()
        raise SandboxError(
            f"prctl(PR_SET_NO_NEW_PRIVS) 失败：errno={err} ({os.strerror(err)})",
            plan=plan,
        )

    attr = _RulesetAttr(handled)
    ctypes.set_errno(0)
    ruleset_fd = lib.syscall(
        ctypes.c_long(_SYS_CREATE_RULESET),
        ctypes.byref(attr),
        ctypes.c_size_t(ctypes.sizeof(attr)),
        ctypes.c_uint(0),
    )
    if ruleset_fd < 0:
        err = ctypes.get_errno()
        raise SandboxError(
            f"landlock_create_ruleset 失败：errno={err} ({os.strerror(err)})", plan=plan
        )

    try:
        for path, rights in plan.rules:
            try:
                path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            except OSError as exc:
                raise SandboxError(f"打开规则路径失败 {path}：{exc}", plan=plan) from exc
            try:
                rule = _PathBeneathAttr(rights, path_fd)
                ctypes.set_errno(0)
                rc = lib.syscall(
                    ctypes.c_long(_SYS_ADD_RULE),
                    ctypes.c_int(ruleset_fd),
                    ctypes.c_uint(_RULE_PATH_BENEATH),
                    ctypes.byref(rule),
                    ctypes.c_uint(0),
                )
                if rc != 0:
                    err = ctypes.get_errno()
                    raise SandboxError(
                        f"landlock_add_rule 失败 {path}：errno={err} ({os.strerror(err)})",
                        plan=plan,
                    )
            finally:
                os.close(path_fd)

        ctypes.set_errno(0)
        rc = lib.syscall(
            ctypes.c_long(_SYS_RESTRICT_SELF),
            ctypes.c_int(ruleset_fd),
            ctypes.c_uint(0),
        )
        if rc != 0:
            err = ctypes.get_errno()
            raise SandboxError(
                f"landlock_restrict_self 失败：errno={err} ({os.strerror(err)})", plan=plan
            )
    finally:
        try:
            os.close(ruleset_fd)
        except OSError:  # pragma: no cover
            pass


def _make_hook(plan: SandboxPlan):
    """构造 preexec 钩子：只在**子进程**里跑，只做 syscall。"""

    def _hook() -> None:  # pragma: no cover - 子进程里跑，父进程测不到
        try:
            apply_current(plan)
        except BaseException as exc:
            # 子进程里没有别的地方能报：留一行给日志/agent 日志文件
            try:
                os.write(2, f"trimum: sandbox apply failed: {exc}\n".encode("utf-8", "replace"))
            except OSError:
                pass
            raise

    return _hook


# ══════════════════════════════════════════════════════════════════════
# 派生（六个 spawn 点的唯一入口）
# ══════════════════════════════════════════════════════════════════════


async def _spawn_process(shell: bool, args: Sequence[Any], kwargs: dict[str, Any]):
    """唯一真正落到 asyncio 的地方（测试替换点）。"""
    if shell:
        return await asyncio.create_subprocess_shell(*args, **kwargs)
    return await asyncio.create_subprocess_exec(*args, **kwargs)


async def spawn_exec(plan: SandboxPlan, *args: Any, **kwargs: Any):
    """``asyncio.create_subprocess_exec`` 的安全版：先施沙箱，失败不执行。"""
    return await _spawn(plan, shell=False, args=args, kwargs=kwargs)


async def spawn_shell(plan: SandboxPlan, cmd: str, **kwargs: Any):
    """``asyncio.create_subprocess_shell`` 的安全版。"""
    return await _spawn(plan, shell=True, args=(cmd,), kwargs=kwargs)


async def _spawn(plan: SandboxPlan, *, shell: bool, args: Sequence[Any], kwargs: dict[str, Any]):
    """派生 + 施加的唯一实现。**任一分支都不许绕过** ``plan.state`` 的如实记录。

    四种结局：``off``（开关关了）/ ``unsupported``（平台或内核不支持，如实标记、
    照旧执行）/ ``<mode>:failed``（档案不可用或施加失败 —— 命令**不执行**）/
    ``<mode>``（施加成功）。``fail_closed=false`` 时第三种降级成 ``<mode>:degraded``
    并记一条 ERROR。
    """
    call_kwargs = dict(kwargs)

    if plan.mode == MODE_OFF:
        plan.state = STATE_OFF
        _sync(plan)
        return await _spawn_process(shell, args, call_kwargs)

    if not plan.supported:
        # 平台 / 内核不支持：如实报 unsupported，绝不假装已隔离（§6.5）
        plan.state = STATE_UNSUPPORTED
        _sync(plan)
        _warn_unsupported_once(plan.mode, plan.reason)
        return await _spawn_process(shell, args, call_kwargs)

    if plan.blockers:
        if plan.fail_closed:
            plan.state = plan.mode + SUFFIX_FAILED
            _sync(plan)
            logger.error("sandbox.plan_blocked", mode=plan.mode, blockers=plan.blockers)
            raise SandboxError(f"沙箱档案不可用：{plan.blockers[0]}", plan=plan)
        plan.state = plan.mode + SUFFIX_DEGRADED
        _sync(plan)
        logger.error(
            "sandbox.plan_blocked_degraded",
            mode=plan.mode,
            blockers=plan.blockers,
            detail="fail_closed=false：降级为无沙箱执行",
        )
        return await _spawn_process(shell, args, call_kwargs)

    call_kwargs["preexec_fn"] = _make_hook(plan)
    try:
        proc = await _spawn_process(shell, args, call_kwargs)
    except subprocess.SubprocessError as exc:
        # 只可能来自 preexec 钩子（命令根本没 exec）；FileNotFoundError 之类照旧向上抛
        if plan.fail_closed:
            plan.state = plan.mode + SUFFIX_FAILED
            _sync(plan)
            logger.error(
                "sandbox.apply_failed", mode=plan.mode, error=str(exc), rules=plan.rules
            )
            raise SandboxError(
                f"沙箱施加失败（{plan.mode}）：命令未执行（{exc}）", plan=plan
            ) from exc
        plan.state = plan.mode + SUFFIX_DEGRADED
        _sync(plan)
        logger.error(
            "sandbox.apply_failed_degraded",
            mode=plan.mode,
            error=str(exc),
            detail="fail_closed=false：降级为无沙箱执行",
        )
        return await _spawn_process(shell, args, dict(kwargs))

    plan.state = plan.mode
    _sync(plan)
    return proc


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m trimum_core.sandbox_exec`` —— 独立施加，供真机验收与排障。

    ``--status`` 只打印档案（不施加）；给了命令则**先施加再 exec**（本进程被替换，
    PID / 信号 / 管道语义都不变），因此可以直接拿来对照「同一棵树里哪条路径被拒」。

    用法::

        python -m trimum_core.sandbox_exec --status
        python -m trimum_core.sandbox_exec --profile readonly -- cat /etc/hostname
        python -m trimum_core.sandbox_exec --profile workspace-write \
            --cwd /tmp/ws -- sh -c 'echo hi > a.txt'
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m trimum_core.sandbox_exec",
        description="trimum Layer K —— 在子进程里施加 Landlock（不可逆）",
    )
    parser.add_argument("--status", action="store_true", help="只打印档案，不施加")
    parser.add_argument("--profile", default=None, help="readonly | workspace-write | strict | off")
    parser.add_argument("--cwd", default=None, help="当作「工作区」的目录（默认进程 cwd）")
    parser.add_argument("--read", action="append", default=[], help="额外只读路径（可多次）")
    parser.add_argument("--write", action="append", default=[], help="额外可写路径（可多次）")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="要执行的命令")
    args = parser.parse_args(list(argv) if argv is not None else None)

    plan = plan_for(
        cwd=args.cwd,
        mode=args.profile,
        extra_read=args.read,
        extra_write=args.write,
    )

    if args.status or not args.cmd:
        capability = probe()
        print(f"capability : {capability.summary()}")
        print(f"plan       : {plan.summary()}")
        print(f"state      : {plan.state}")
        for path, rights in plan.rules:
            print(f"  rule     : 0o{rights:05o} {path}")
        return 0

    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        parser.error("没有可执行的命令")

    try:
        apply_current(plan)
    except SandboxError as exc:
        print(f"trimum sandbox: {exc}", file=sys.stderr)
        return 126
    os.execvp(cmd[0], cmd)
    return 0  # pragma: no cover - execvp 不返回


def current_state() -> str:
    """给审计/CLI 用的一句话状态（含能力探测）。"""
    capability = probe()
    mode = os.environ.get(ENV_MODE) or load_config().get("mode") or DEFAULT_MODE
    if str(mode).strip() == MODE_OFF:
        return STATE_OFF
    if not capability.supported:
        return STATE_UNSUPPORTED
    return str(mode).strip()


__all__ = [
    "DEFAULT_MODE",
    "ENV_FAIL_CLOSED",
    "ENV_MODE",
    "MODES",
    "MODE_OFF",
    "MODE_READONLY",
    "MODE_STRICT",
    "MODE_WORKSPACE",
    "STATE_OFF",
    "STATE_UNSUPPORTED",
    "SandboxCapability",
    "SandboxError",
    "SandboxPlan",
    "apply_current",
    "current_state",
    "load_config",
    "main",
    "plan_for",
    "probe",
    "reset_cache",
    "spawn_exec",
    "spawn_shell",
]


if __name__ == "__main__":  # pragma: no cover - 独立入口
    raise SystemExit(main())
