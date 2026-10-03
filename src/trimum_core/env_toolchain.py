"""Opt-in developer toolchain — what is installed, and how to install more.

This is L0 of the ecosystem strategy (``docs/ECOSYSTEM-STRATEGY.md`` §3): trimum
does **not** build a package repository.  It detects the package managers the
machine actually has, reports what is already installed, and — only after an
explicit confirmation — hands the selected catalog entries to the right system
package manager.

Two invariants:

* detection and inventory are **read-only** (probing ``--version`` and listing
  installed packages);
* installation never happens implicitly: :func:`plan_install` produces the exact
  command, and :func:`run_install` refuses to execute unless the caller passes
  ``dry_run=False`` *and* the plan was confirmed upstream (the CLI asks, or
  ``--yes`` was given).

The curated list itself lives in ``config/setup-catalog.yaml`` so the wizard and
the installer read the same source.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Managers trimum knows how to query and (some) drive.
INSTALLABLE_IDS = frozenset(
    {"pacman", "apt", "dnf", "zypper", "apk", "brew", "winget", "scoop"}
)


@dataclass(frozen=True)
class PackageManager:
    """One system package manager and the three commands trimum needs."""

    id: str
    label: str
    catalog_key: str
    probe: tuple[str, ...]
    list_cmd: tuple[str, ...] | None
    install_cmd: tuple[str, ...] | None
    needs_sudo: bool = True
    platforms: tuple[str, ...] = ()
    note: str = ""

    def supports(self, platform_id: str) -> bool:
        return not self.platforms or platform_id in self.platforms

    @property
    def installable(self) -> bool:
        return self.install_cmd is not None and self.id in INSTALLABLE_IDS

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "catalog_key": self.catalog_key,
            "needs_sudo": self.needs_sudo,
            "installable": self.installable,
            "list_cmd": list(self.list_cmd) if self.list_cmd else None,
            "install_cmd": list(self.install_cmd) if self.install_cmd else None,
            "note": self.note,
        }


#: Order matters: the first match wins when auto-selecting a manager.
KNOWN_MANAGERS: tuple[PackageManager, ...] = (
    PackageManager(
        "pacman", "pacman (Arch)", "pacman",
        ("pacman", "--version"), ("pacman", "-Qq"), ("pacman", "-S", "--noconfirm"),
        needs_sudo=True, platforms=("linux",),
    ),
    PackageManager(
        "apt", "APT (Debian/Ubuntu)", "apt",
        ("apt-get", "--version"),
        ("dpkg-query", "-W", "-f", "${binary:Package}\n"),
        ("apt-get", "install", "-y"),
        needs_sudo=True, platforms=("linux",),
    ),
    PackageManager(
        "dnf", "DNF (Fedora/RHEL)", "dnf",
        ("dnf", "--version"), ("rpm", "-qa"), ("dnf", "install", "-y"),
        needs_sudo=True, platforms=("linux",),
    ),
    PackageManager(
        "zypper", "Zypper (openSUSE)", "zypper",
        ("zypper", "--version"), ("rpm", "-qa"),
        ("zypper", "--non-interactive", "install"),
        needs_sudo=True, platforms=("linux",),
    ),
    PackageManager(
        "apk", "apk (Alpine)", "apk",
        ("apk", "--version"), ("apk", "info"), ("apk", "add"),
        needs_sudo=True, platforms=("linux",),
    ),
    PackageManager(
        "brew", "Homebrew", "brew",
        ("brew", "--version"), ("brew", "list", "-1"), ("brew", "install"),
        needs_sudo=False, platforms=("darwin", "linux"),
    ),
    PackageManager(
        "winget", "winget (Windows)", "winget",
        ("winget", "--version"), ("winget", "list"), ("winget", "install", "-e", "--id"),
        needs_sudo=False, platforms=("win32",),
        note="winget 的包 ID 与包名不同，目录里存的是 ID",
    ),
    PackageManager(
        "scoop", "Scoop (Windows)", "scoop",
        ("scoop", "--version"), ("scoop", "list"), ("scoop", "install"),
        needs_sudo=False, platforms=("win32",),
    ),
    PackageManager(
        "mise", "mise (语言运行时)", "mise",
        ("mise", "--version"), ("mise", "ls"), None,
        needs_sudo=False,
        note="mise 管的是运行时版本，清单里登记但它不代装",
    ),
)


@dataclass
class ManagerStatus:
    """Detection outcome for one package manager."""

    manager: PackageManager
    available: bool
    path: str = ""
    version: str = ""
    platform_supported: bool = True

    @property
    def id(self) -> str:
        return self.manager.id

    def to_dict(self) -> dict:
        data = self.manager.to_dict()
        data.update(
            {
                "available": self.available,
                "path": self.path,
                "version": self.version,
                "platform_supported": self.platform_supported,
            }
        )
        return data


def _default_runner(cmd, timeout: float):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def platform_id() -> str:
    """Return the current platform id (``linux`` / ``darwin`` / ``win32``)."""
    import sys

    return sys.platform


def detect_managers(
    *,
    which=None,
    runner=None,
    platform: str | None = None,
    timeout: float = 5.0,
    managers: tuple[PackageManager, ...] = KNOWN_MANAGERS,
) -> list[ManagerStatus]:
    """Probe every known package manager; never raises."""
    which = shutil.which if which is None else which
    runner = _default_runner if runner is None else runner
    platform = platform_id() if platform is None else platform

    statuses: list[ManagerStatus] = []
    for manager in managers:
        status = ManagerStatus(
            manager=manager,
            available=False,
            platform_supported=manager.supports(platform),
        )
        if status.platform_supported:
            found = which(manager.probe[0])
            if found:
                status.path = found
                status.available = True
                try:
                    result = runner(list(manager.probe), timeout)
                    status.version = _first_line(getattr(result, "stdout", "") or "")
                except Exception:
                    status.version = ""
        statuses.append(status)
    return statuses


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


_COLUMN_SPLIT = re.compile(r"\s{2,}")


def parse_installed(manager_id: str, text: str) -> set[str]:
    """Parse a package listing command's output into a set of package names."""
    names: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.lower()
        if lowered.startswith(("name ", "---", "listing", "warning", "'")):
            continue
        if manager_id == "winget":
            # winget 的列表按列对齐（列间至少两个空格）：Name / Id / Version
            columns = [part for part in _COLUMN_SPLIT.split(line) if part]
            token = columns[1] if len(columns) > 1 else line.split()[0]
        else:
            token = line.split()[0]
        if not token:
            continue
        # dpkg 会给出 name:arch
        names.add(token.split(":")[0].lower())
    return names


def query_installed(
    status: ManagerStatus,
    *,
    runner=None,
    timeout: float = 20.0,
) -> set[str] | None:
    """Return installed package names, or ``None`` when the manager cannot list."""
    if not status.available:
        return None
    command = status.manager.list_cmd
    if not command:
        return None
    runner = _default_runner if runner is None else runner
    try:
        result = runner(list(command), timeout)
    except Exception:
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    return parse_installed(status.manager.id, getattr(result, "stdout", "") or "")


def load_selection(state_file: Path | None = None) -> list[str]:
    """Read the toolchain selection recorded by ``trm setup``."""
    if state_file is None:
        from .setup_wizard import state_path as _state_path

        state_file = _state_path()
    try:
        import json

        data = json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    toolchain = (data.get("steps") or {}).get("toolchain") or {}
    return list(toolchain.get("selected") or [])


def _packages_for(entry: dict, manager: PackageManager) -> list[str]:
    packages = entry.get("packages") or {}
    value = packages.get(manager.catalog_key)
    if value is None:
        return []
    if isinstance(value, str):
        return [part for part in value.split() if part]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    return [str(value)]


def plan_install(
    catalog: dict,
    names,
    *,
    manager: ManagerStatus,
    installed: set[str] | None = None,
    selected: list[str] | None = None,
) -> dict:
    """Build the exact install command for *names* using *manager*."""
    from .setup_wizard import catalog_entries

    by_name = {entry["name"]: entry for entry in catalog_entries(catalog)}
    wanted = [str(name).strip() for name in names if str(name).strip()]

    packages: list[str] = []
    already: list[str] = []
    unavailable: list[str] = []
    unknown: list[str] = []

    for name in wanted:
        entry = by_name.get(name.lower())
        if entry is None:
            unknown.append(name)
            continue
        found = _packages_for(entry, manager.manager)
        if not found:
            unavailable.append(name)
            continue
        if installed is not None and all(pkg.lower() in installed for pkg in found):
            already.append(name)
            continue
        for pkg in found:
            if pkg not in packages:
                packages.append(pkg)

    command = build_command(manager, packages) if packages else []
    return {
        "manager": manager.id,
        "manager_label": manager.manager.label,
        "requested": wanted,
        "packages": packages,
        "already_installed": already,
        "unavailable": unavailable,
        "unknown": unknown,
        "command": command,
        "installable": manager.manager.installable,
        "selected_before": list(selected or []),
        "note": manager.manager.note,
    }


def _is_root() -> bool:
    """True when this process already has root package-manager rights."""
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid) and geteuid() == 0


def build_command(
    status: ManagerStatus,
    packages: list[str],
    *,
    use_sudo: bool | None = None,
) -> list[str]:
    """Return the argv for installing *packages*.

    ``sudo`` is prefixed when the manager needs it and trimum is not root
    already; an explicit *use_sudo* always wins.
    """
    install_cmd = status.manager.install_cmd
    if not packages or not install_cmd:
        return []
    argv = list(install_cmd) + list(packages)
    if use_sudo is None:
        use_sudo = status.manager.needs_sudo and not _is_root()
    if use_sudo:
        argv = ["sudo"] + argv
    return argv


def commands_for(
    status: ManagerStatus,
    packages: list[str],
    *,
    use_sudo: bool | None = None,
) -> list[list[str]]:
    """Return one argv per invocation (winget installs one package at a time)."""
    if not packages or not status.manager.install_cmd:
        return []
    if status.manager.id == "winget":
        return [
            build_command(status, [pkg], use_sudo=use_sudo) for pkg in packages
        ]
    return [build_command(status, packages, use_sudo=use_sudo)]


def run_install(
    commands: list[list[str]],
    *,
    dry_run: bool = False,
    runner=None,
    timeout: float = 1800.0,
) -> dict:
    """Execute the planned commands; ``dry_run`` reports without running."""
    runner = _default_runner if runner is None else runner
    results: list[dict] = []
    for command in commands:
        if dry_run:
            results.append({"command": command, "executed": False, "returncode": None})
            continue
        try:
            completed = runner(list(command), timeout)
            results.append(
                {
                    "command": command,
                    "executed": True,
                    "returncode": getattr(completed, "returncode", None),
                    "stdout": (getattr(completed, "stdout", "") or "")[-2000:],
                    "stderr": (getattr(completed, "stderr", "") or "")[-2000:],
                }
            )
        except Exception as exc:  # 缺 sudo / 命令不存在 / 超时
            results.append(
                {"command": command, "executed": True, "returncode": None, "error": str(exc)}
            )
    ok = all(item.get("returncode") == 0 for item in results if item["executed"]) and not dry_run
    return {"dry_run": dry_run, "ok": ok, "results": results}


def inventory(
    *,
    catalog: dict | None = None,
    which=None,
    runner=None,
    platform: str | None = None,
    state_file: Path | None = None,
    include_package_names: bool = False,
    statuses: list[ManagerStatus] | None = None,
) -> dict:
    """Report managers, installed packages and catalog coverage.

    *include_package_names* adds the (potentially long) package list per manager;
    it is off by default so the report stays readable for agents.  Pass *statuses*
    to reuse a detection pass the caller already ran (the CLI does, so a single
    ``trm env install`` probes each manager exactly once).
    """
    from .setup_wizard import catalog_entries, load_catalog

    catalog = load_catalog() if catalog is None else catalog
    entries = catalog_entries(catalog)
    if statuses is None:
        statuses = detect_managers(which=which, runner=runner, platform=platform)
    selection = load_selection(state_file)

    installed_by_manager: dict[str, list[str]] = {}
    managers: list[dict] = []
    for status in statuses:
        names = query_installed(status, runner=runner) if status.available else None
        installed_by_manager[status.id] = sorted(names) if names else []
        data = status.to_dict()
        data["installed_count"] = len(names) if names is not None else None
        if include_package_names:
            data["installed"] = sorted(names) if names else []
        managers.append(data)

    usable = [status for status in statuses if status.available and status.manager.installable]
    coverage: list[dict] = []
    for entry in entries:
        row = {
            "name": entry["name"],
            "label": entry.get("label", ""),
            "group": entry.get("group", ""),
            "kind": entry.get("kind", "tool"),
            "selected": entry["name"] in selection,
            "available_via": [
                manager.id
                for manager in KNOWN_MANAGERS
                if _packages_for(entry, manager)
                and any(status.id == manager.id and status.available for status in statuses)
            ],
        }
        installed_here = False
        for manager in KNOWN_MANAGERS:
            packages = _packages_for(entry, manager)
            if not packages:
                continue
            known = set(installed_by_manager.get(manager.id) or [])
            if known and all(pkg.lower() in known for pkg in packages):
                installed_here = True
                break
        row["installed"] = installed_here
        coverage.append(row)

    return {
        "platform": platform_id() if platform is None else platform,
        "catalog": catalog.get("path", ""),
        "managers": managers,
        "installable_managers": [status.id for status in usable],
        "preferred_manager": usable[0].id if usable else "",
        "toolchain": coverage,
        "selected": selection,
        "installed_totals": {
            manager_id: len(names) for manager_id, names in installed_by_manager.items()
        },
    }


__all__ = [
    "INSTALLABLE_IDS",
    "PackageManager",
    "ManagerStatus",
    "KNOWN_MANAGERS",
    "detect_managers",
    "parse_installed",
    "query_installed",
    "load_selection",
    "plan_install",
    "build_command",
    "commands_for",
    "run_install",
    "inventory",
    "platform_id",
]