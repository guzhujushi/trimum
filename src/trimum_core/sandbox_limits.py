"""S4 子 Agent 资源边界：`systemd-run --user` 命令的**纯计算**口径。

本模块只做两件事：算单元名、拼 `systemd-run` 的 argv（含 `-p` 资源属性）。
**纯计算、不派生进程** —— 源码里没有任何派生调用，
派生与验收都交给调用方（`scripts/accept_s4.py` 真跑，`tests/` 只验字符串）。

两个状态的口径：

* `STATE_SYSTEMD` —— `systemd-run --user` 可用（二进制在、`/run/systemd/system` 在），
  命令包成一次性 user 单元，`MemoryMax` / `CPUQuota` / `TasksMax` 等真正生效；
* `STATE_UNSUPPORTED` —— 不可用时**如实降级**：argv 原样返回、一个 `-p` 都不加。
  这是「没资源边界」的诚实声明，**不是失败**，不该被当成错误上报。

真机踩过的坑（2026-09-27，详见 `docs/SANDBOX-PLAN.md` §9）：

* `MemoryMax` 与 `MemorySwapMax` **必须成对出现** —— 本机 4 GiB swap，只设
  `MemoryMax` 时灌内存的进程照样成功（`oom_kill 0`）；`MemorySwapMax=0` 之后
  才真的 `oom-kill`；
* `--wait --pipe` 是唯一可信口径（不带 `--wait` 测到的是竞态）；
* `--quiet` 去掉 `Running as unit: ...` 那行，父进程 `rc` 就是单元真实退出码。
* 单元上**不再装第二套 syscall 过滤器**：唯一的 syscall 口径 = `seccomp_exec` 的档位
  （`@system-service` 白名单**不含** `seccomp(2)` 与 `landlock_create_ruleset/add_rule/restrict_self`，
  谁在单元内装 Layer K 谁被内核 `SIGSYS(31)` 打死 —— 真机实测，见 `docs/SANDBOX-PLAN.md` §6.6 / §12.5）。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

STATE_SYSTEMD = "systemd"
STATE_UNSUPPORTED = "unsupported"
UNIT_PREFIX = "trimum-agent-"
SYSTEMD_RUN_BIN = "systemd-run"
SYSTEMD_RUN_DIR = Path("/run/systemd/system")
MAX_UNIT_LENGTH = 255

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9:_.-]")


@dataclass(frozen=True)
class Limits:
    """一次子 Agent 执行的资源上限（默认值即「宽」档，收紧靠调用方显式给）。

    **只有资源与特权位**（内存 / swap / CPU / 任务数 / `NoNewPrivileges`）——
    系统调用那一维**不在这里**：单元上不加 `SystemCallFilter=`（第二套口径会把
    单元内的 Layer K 施加打成 `SIGSYS`），syscall 边界唯一由 `seccomp_exec` 的档位负责。
    """

    memory_max_bytes: int = 1 << 30
    memory_swap_max_bytes: int = 0
    cpu_quota_percent: int = 100
    tasks_max: int = 128
    no_new_privileges: bool = True

    def __post_init__(self) -> None:
        if self.memory_max_bytes <= 0:
            raise ValueError(
                "memory_max_bytes 必须 > 0（收到 %r）：0 或负数没有语义" % (self.memory_max_bytes,)
            )
        if self.memory_swap_max_bytes < 0:
            raise ValueError(
                "memory_swap_max_bytes 必须 >= 0（收到 %r）：下限是 0，不是负数" % (self.memory_swap_max_bytes,)
            )
        if self.cpu_quota_percent <= 0:
            raise ValueError(
                "cpu_quota_percent 必须 > 0（收到 %r）：0 表示不给 CPU，没有意义" % (self.cpu_quota_percent,)
            )
        if self.tasks_max <= 0:
            raise ValueError(
                "tasks_max 必须 > 0（收到 %r）：单元里至少要容得下主进程" % (self.tasks_max,)
            )


    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "Limits":
        """从配置映射构造 Limits（S6① 键名与单位收敛后的唯一入口，**本片不接线**）。

        只认四个键：``memory_max`` / ``memory_swap_max``（人读单位，走 ``parse_size``）/
        ``cpu_quota_percent`` / ``tasks_max``；缺失的键用 ``Limits()`` 的内置默认值。
        未知键一律 ``ValueError``（拼错必须当场炸）；数值合法性交给 ``__post_init__``。
        """
        raw = raw or {}
        known = {
            "memory_max": "memory_max_bytes",
            "memory_swap_max": "memory_swap_max_bytes",
            "cpu_quota_percent": "cpu_quota_percent",
            "tasks_max": "tasks_max",
        }
        for key in raw:
            if key not in known:
                raise ValueError(f"Limits.from_mapping 遇到未知键: {key!r}（只认 {sorted(known)}）")
        kwargs: dict[str, Any] = {}
        if "memory_max" in raw:
            kwargs["memory_max_bytes"] = parse_size(raw["memory_max"])
        if "memory_swap_max" in raw:
            kwargs["memory_swap_max_bytes"] = parse_size(raw["memory_swap_max"])
        if "cpu_quota_percent" in raw:
            kwargs["cpu_quota_percent"] = raw["cpu_quota_percent"]
        if "tasks_max" in raw:
            kwargs["tasks_max"] = raw["tasks_max"]
        return cls(**kwargs)


@dataclass(frozen=True)
class Command:
    """`build_command` 的产物：待派生的 argv + 状态 +（systemd 档的）单元名。"""

    argv: tuple[str, ...]
    state: str
    unit: str | None = None


def unit_name(agent_name: str) -> str:
    """把 Agent 名净化成一个 user 单元名：`trimum-agent-<净化名>.service`。

    净化 = 把 `[^A-Za-z0-9:_.-]` 全部换成 `-`；名字为空 / 净化后为空 → `anon`。
    结果长度保证 ≤ `MAX_UNIT_LENGTH`（超长就截净化名再补后缀）。
    """
    suffix = ".service"
    cleaned = _SANITIZE_RE.sub("-", agent_name or "")
    if not cleaned:
        cleaned = "anon"
    head = UNIT_PREFIX + cleaned
    if len(head) + len(suffix) > MAX_UNIT_LENGTH:
        cleaned = cleaned[: MAX_UNIT_LENGTH - len(UNIT_PREFIX) - len(suffix)]
        head = UNIT_PREFIX + cleaned
    return head + suffix


def properties(limits: Limits) -> tuple[str, ...]:
    """`-p` 的取值，**顺序固定**（不许改成字典序）：

    MemoryMax → MemorySwapMax → CPUQuota → TasksMax → NoNewPrivileges。

    `MemoryMax` 与 `MemorySwapMax` 成对出现是硬口径：本机有 swap，只设前者拦不住
    灌内存的进程（真机实测 `oom_kill 0`）。

    **这里没有 `SystemCallFilter=`**：`@system-service` 是白名单，实测**不含**
    `seccomp(2)` 与 `landlock_create_ruleset/add_rule/restrict_self`（444/445/446），
    单元内再装 Layer K 会被内核 `SIGSYS(31)` 打死；而另写一套黑名单就是第二套 syscall
    口径（见 §12.5「别各写一套」）。syscall 边界唯一由 `seccomp_exec` 的档位负责。
    """
    return (
        f"MemoryMax={limits.memory_max_bytes}",
        f"MemorySwapMax={limits.memory_swap_max_bytes}",
        f"CPUQuota={limits.cpu_quota_percent}%",
        f"TasksMax={limits.tasks_max}",
        f"NoNewPrivileges={'yes' if limits.no_new_privileges else 'no'}",
    )


def plan_unit(agent_name: str, systemd_ok: bool | None = None) -> tuple[str, str]:
    """(state, unit)：与 ``build_command`` 的分支口径一致（接线方用它先拿到单元名）。

    可用 → ``(STATE_SYSTEMD, unit_name(agent_name))``；不可用 → ``(STATE_UNSUPPORTED, "")``。
    """
    if systemd_ok is None:
        systemd_ok = systemd_available()
    if not systemd_ok:
        return STATE_UNSUPPORTED, ""
    return STATE_SYSTEMD, unit_name(agent_name)


def systemd_available() -> bool:
    """`systemd-run` 二进制在 **且** `/run/systemd/system` 存在 ⇒ 可用。从不抛异常。"""
    try:
        return shutil.which(SYSTEMD_RUN_BIN) is not None and SYSTEMD_RUN_DIR.is_dir()
    except Exception:  # noqa: BLE001
        return False


def current_state() -> str:
    """当前宿主能力：`STATE_SYSTEMD` / `STATE_UNSUPPORTED`。从不抛异常。"""
    try:
        return STATE_SYSTEMD if systemd_available() else STATE_UNSUPPORTED
    except Exception:  # noqa: BLE001
        return STATE_UNSUPPORTED


def build_command(
    argv: list[str] | tuple[str, ...],
    agent_name: str = "anon",
    limits: Limits | None = None,
    systemd_ok: bool | None = None,
    env: Mapping[str, str] | None = None,
    workdir: str | None = None,
    unit: str | None = None,
) -> Command:
    """把 `argv` 包成 `systemd-run --user` 命令；不可用时原样返回。

    * `systemd_ok is None` 时现算 `systemd_available()`（便于单测注入）；
    * `limits is None` 时用默认 `Limits()`；
    * `argv` 为空 → `ValueError`；
    * `unit is None` 时现算 `unit_name(agent_name)`；显式传入则原样用作 `--unit=<unit>`
      （接线方要先把单元名交给终止流程，再拼 argv）；
    * 不可用 → `Command(argv=tuple(argv), state=unsupported, unit=None)`：
      这是**如实降级**（没资源边界），不是失败；**`env` / `workdir` 在降级档一律
      忽略，argv 原样返回**（不偷偷加 `--setenv` / `--working-directory`）；
    * 可用 → **argv 顺序固定**：
      `("systemd-run","--user","--quiet","--wait","--pipe","--collect",
      "--unit=<unit>",
      "--working-directory=<workdir>"（workdir 非空才加）,
      各 "--setenv=K=V"（env 非空才加，**只透传键以 `TRIMUM_` 开头的项、按 key 升序**）,
      "-p", p0, ..., "--", *argv)`；**不改动传入的 argv**。
      **严禁全量透传 env**（`BASH_FUNC_*%%` 之类会让 systemd-run 直接报错），
      也严禁透传非 `TRIMUM_` 前缀的键。
    """
    argv_t = tuple(argv)
    if not argv_t:
        raise ValueError("argv 为空：build_command 没有可包的东西")
    if systemd_ok is None:
        systemd_ok = systemd_available()
    if limits is None:
        limits = Limits()
    if not systemd_ok:
        return Command(argv=argv_t, state=STATE_UNSUPPORTED, unit=None)
    unit = unit or unit_name(agent_name)
    props = properties(limits)
    head = (SYSTEMD_RUN_BIN, "--user", "--quiet", "--wait", "--pipe", "--collect", f"--unit={unit}")
    middle = ()
    if workdir:
        middle = middle + (f"--working-directory={workdir}",)
    if env:
        env = {k: str(v) for k, v in env.items() if str(k).startswith("TRIMUM_")}
        env = dict(sorted(env.items(), key=lambda kv: kv[0]))
        middle = middle + tuple(f"--setenv={k}={v}" for k, v in env.items())
    wrapped = (
        head
        + middle
        + tuple(p for prop in props for p in ("-p", prop))
        + ("--", *argv_t)
    )
    return Command(argv=wrapped, state=STATE_SYSTEMD, unit=unit)


__all__ = [
    "STATE_SYSTEMD",
    "STATE_UNSUPPORTED",
    "UNIT_PREFIX",
    "SYSTEMD_RUN_BIN",
    "SYSTEMD_RUN_DIR",
    "MAX_UNIT_LENGTH",
    "Limits",
    "Command",
    "unit_name",
    "properties",
    "systemd_available",
    "current_state",
    "plan_unit",
    "build_command",
    "parse_size",
]


_SIZE_UNITS: dict[str, int] = {
    "kib": 1024,
    "mib": 1024 ** 2,
    "gib": 1024 ** 3,
    "tib": 1024 ** 4,
    "k": 1024,
    "m": 1024 ** 2,
    "g": 1024 ** 3,
    "t": 1024 ** 4,
}


def parse_size(value: object) -> int:
    """把人读的尺寸单位解析成字节数（**一律 1024 进制**：``1G`` == ``1GiB``）。

    * 入参 int（bool 除外）直接返回，必须 ``>= 0``；
    * 入参 str 支持纯数字与 ``KiB/MiB/GiB/TiB``、``K/M/G/T`` 后缀，允许小数（``1.5GiB``）；
    * 其他一切（负数、空串、纯字母、不认识的单位、float、None）``ValueError``，
      消息里带上原值。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise ValueError(f"parse_size 无法解析 {value!r}：空字符串")
            match = re.fullmatch(r"(\d+(?:\.\d+)?)([A-Za-z]*)", text)
            if match is None:
                raise ValueError(f"parse_size 无法解析 {value!r}：不是『数字+单位』")
            number_text, unit_text = match.group(1), match.group(2).lower()
            if not unit_text:
                multiplier = 1  # 无后缀 = 裸字节
            else:
                multiplier = _SIZE_UNITS.get(unit_text)
                if multiplier is None:
                    raise ValueError(
                        f"parse_size 无法解析 {value!r}：不认识的单位 {unit_text!r}"
                        "（只认 KiB/MiB/GiB/TiB 与 K/M/G/T，1024 进制）"
                    )
            return int(float(number_text) * multiplier)
        raise ValueError(f"parse_size 无法解析 {value!r}：只接受 int 或带单位的字符串")
    if value < 0:
        raise ValueError(f"parse_size 无法解析 {value!r}：字节数不能为负")
    return value
