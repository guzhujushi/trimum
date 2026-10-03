"""沙箱档位现算快照：`trm status` / `trm doctor` 展示用。

档位只来自运行时真实配置的单一口径（`sandbox_exec.current_state` /
`seccomp_exec.current_state`，见 `docs/SANDBOX-PLAN.md` §10.3）；
S1 daemon 加固只看 systemd drop-in 文件在不在。
全部只读、从不抛异常，拿不到就 `unknown`。
"""

from __future__ import annotations

from pathlib import Path

from . import sandbox_exec
from . import seccomp_exec

STATE_PRESENT = "present"
STATE_ABSENT = "absent"
STATE_UNKNOWN = "unknown"
DEFAULT_UNIT = "trmd"
SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")
DROPIN_FILENAME = "10-hardening.conf"


def landlock_state() -> str:
    """Landlock 档：`sandbox_exec.current_state()`，异常 → unknown。"""
    try:
        state = sandbox_exec.current_state()
    except Exception:
        return STATE_UNKNOWN
    return str(state) if state else STATE_UNKNOWN


def seccomp_state() -> str:
    """seccomp 档：`seccomp_exec.current_state()`，异常 → unknown。"""
    try:
        state = seccomp_exec.current_state()
    except Exception:
        return STATE_UNKNOWN
    return str(state) if state else STATE_UNKNOWN


def daemon_hardening_state(unit: str = DEFAULT_UNIT) -> str:
    """S1 加固 drop-in 状态。

    present = drop-in 在；absent = 目录在但没这个文件；
    unknown = 目录都不在 / 读不动。
    """
    unit_dir = SYSTEMD_UNIT_DIR
    try:
        if not unit_dir.is_dir():
            return STATE_UNKNOWN
        dropin = unit_dir / f"{unit}.service.d" / DROPIN_FILENAME
        return STATE_PRESENT if dropin.is_file() else STATE_ABSENT
    except OSError:
        return STATE_UNKNOWN


def snapshot(unit: str = DEFAULT_UNIT) -> dict[str, str]:
    """当前宿主的沙箱三件套，键固定：landlock / seccomp / daemon_hardening。"""
    return {
        "landlock": landlock_state(),
        "seccomp": seccomp_state(),
        "daemon_hardening": daemon_hardening_state(unit),
    }


__all__ = [
    "STATE_PRESENT",
    "STATE_ABSENT",
    "STATE_UNKNOWN",
    "DEFAULT_UNIT",
    "SYSTEMD_UNIT_DIR",
    "DROPIN_FILENAME",
    "landlock_state",
    "seccomp_state",
    "daemon_hardening_state",
    "snapshot",
]
