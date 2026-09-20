"""`trm env` — 选装开发者工具链：现状清单 / 计划 / 安装（L0 环境层）。

设计红线（``docs/ECOSYSTEM-STRATEGY.md`` §3）：

* trimum **不自建包仓库**，只调用机器的系统包管理器；
* 清单与探测是只读的；
* 安装必须显式确认（交互确认或 ``--yes``），``--dry-run`` 只打印将要执行的命令；
* 已经装好的条目是幂等的：不重装、不弹确认、退出码 0（不算失败）。
"""

from __future__ import annotations

import argparse

from .._utils import emit, fail
from trimum_core.env_toolchain import (
    KNOWN_MANAGERS,
    commands_for,
    detect_managers,
    inventory,
    plan_install,
    run_install,
)
from trimum_core.setup_wizard import load_catalog

__command_meta__ = {
    "env": {
        "summary": "Inspect and install the opt-in developer toolchain",
        "args": "{inventory,install}",
        "tags": ["env", "setup"],
        "risk": "low",
    },
    "env inventory": {
        "summary": "Report package managers, installed packages and catalog coverage",
        "args": "[--manager ID] [--catalog PATH]",
        "examples": ["trm env inventory --json"],
        "tags": ["env"],
        "risk": "low",
    },
    "env install": {
        "summary": "Install catalog entries through the system package manager (asks first)",
        "args": "<name>... [--manager ID] [--dry-run] [--yes] [--catalog PATH]",
        "examples": [
            "trm env install python --dry-run",
            "trm env install python,ripgrep --yes",
        ],
        "tags": ["env", "setup"],
        "risk": "high",
        "requires_sudo": True,
    },
}


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("env", help="opt-in developer toolchain")
    nested = parser.add_subparsers(dest="env_command", title="env commands")

    inventory_parser = nested.add_parser(
        "inventory", help="report managers, installed packages and catalog coverage"
    )
    inventory_parser.add_argument(
        "--manager", default="", metavar="ID", help="only report this package manager"
    )
    inventory_parser.add_argument(
        "--catalog", default="", metavar="PATH", help="use an alternative catalog"
    )
    inventory_parser.set_defaults(handler=handler)

    install_parser = nested.add_parser(
        "install", help="install catalog entries via the system package manager"
    )
    install_parser.add_argument("names", nargs="+", metavar="NAME", help="catalog entry names")
    install_parser.add_argument(
        "--manager", default="", metavar="ID", help="force a package manager"
    )
    install_parser.add_argument(
        "--dry-run", action="store_true", help="print the plan without executing it"
    )
    install_parser.add_argument(
        "-y", "--yes", action="store_true", help="skip the confirmation prompt"
    )
    install_parser.add_argument(
        "--catalog", default="", metavar="PATH", help="use an alternative catalog"
    )
    install_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm env {inventory,install} ...")
    return 0


def _catalog_from(args: argparse.Namespace) -> dict | None:
    custom = (getattr(args, "catalog", "") or "").strip()
    if not custom:
        return load_catalog()
    catalog = load_catalog(custom)
    if not catalog.get("loaded"):
        return None
    return catalog


def _human_inventory(data: dict) -> None:
    print(f"platform: {data['platform']}")
    print("package managers:")
    for item in data["managers"]:
        if item["available"]:
            state = f"ok  {item['version'] or item['path']}"
        elif item["platform_supported"]:
            state = "not installed"
        else:
            state = "n/a on this platform"
        extra = " (not driven by trimum)" if not item["installable"] else ""
        print(f"  {item['id']:<8} {state}{extra}")

    print(f"toolchain: {len(data['toolchain'])} entries in catalog")
    for row in data["toolchain"]:
        marks = []
        if row["installed"]:
            marks.append("installed")
        if row["selected"]:
            marks.append("selected")
        if row["available_via"]:
            marks.append("via " + ",".join(row["available_via"]))
        print(f"  {row['name']:<14}{row['label']:<22}{'; '.join(marks) or '-'}")
    if data["selected"]:
        print(f"selected by trm setup: {', '.join(data['selected'])}")


def _human_install(data: dict) -> None:
    plan = data["plan"]
    if plan["already_installed"]:
        print(f"already installed: {', '.join(plan['already_installed'])}")
    if plan["unavailable"]:
        print(f"not available via {plan['manager']}: {', '.join(plan['unavailable'])}")
    if plan["unknown"]:
        print(f"unknown catalog entries: {', '.join(plan['unknown'])}")
    if not plan["packages"]:
        print("nothing to install")
    else:
        print(f"manager : {plan['manager']} ({plan['manager_label']})")
        print(f"packages: {' '.join(plan['packages'])}")
        for command in data["commands"]:
            print(f"command : {' '.join(command)}")
    for item in data["results"]:
        state = "dry-run" if not item.get("executed") else f"exit={item.get('returncode')}"
        if item.get("error"):
            state = f"error: {item['error']}"
        print(f"  [{state}] {' '.join(item['command'])}")


def _confirm(question: str) -> bool:
    """Ask before running a high-risk command; never prompt in a piped run."""
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        print()
        return False
    return answer in ("y", "yes")


def handler(args: argparse.Namespace) -> int:
    """Run `trm env inventory` or `trm env install`."""
    command = getattr(args, "env_command", None)
    catalog = _catalog_from(args)
    if catalog is None:
        return fail(f"cannot read catalog: {getattr(args, 'catalog', '')}")

    statuses = detect_managers()

    if command == "inventory":
        wanted = (getattr(args, "manager", "") or "").strip()
        if wanted and wanted not in {item.id for item in statuses}:
            return fail(
                f"unknown manager: {wanted} (known: {', '.join(item.id for item in KNOWN_MANAGERS)})"
            )
        data = inventory(catalog=catalog, statuses=statuses)
        if wanted:
            data["managers"] = [item for item in data["managers"] if item["id"] == wanted]
        emit(args, data, _human_inventory)
        return 0

    if command == "install":
        forced = (getattr(args, "manager", "") or "").strip()
        candidates = [item for item in statuses if item.available and item.manager.installable]
        if forced:
            candidates = [item for item in candidates if item.id == forced]
            if not candidates:
                return fail(f"package manager not usable: {forced}")
        if not candidates:
            available = ", ".join(item.id for item in statuses if item.available) or "(none)"
            return fail(
                f"no usable package manager found (detected: {available}); "
                "use --manager to select one explicitly"
            )

        chosen = candidates[0]
        data = inventory(catalog=catalog, include_package_names=True, statuses=statuses)
        installed: set[str] = set()
        for item in data["managers"]:
            if item["id"] == chosen.id:
                installed = set(item.get("installed") or [])
                break

        plan = plan_install(
            catalog,
            list(args.names),
            manager=chosen,
            installed=installed,
            selected=data["selected"],
        )
        if plan["unknown"]:
            return fail(f"unknown toolchain entries: {', '.join(plan['unknown'])}")
        if plan["unavailable"]:
            return fail(
                f"no {chosen.id} package for: {', '.join(plan['unavailable'])}"
            )

        commands = commands_for(chosen, plan["packages"])
        if commands and not args.dry_run:
            if not args.yes and not _confirm(
                f"将执行 {len(commands)} 条命令，确定继续？"
            ):
                return fail("aborted (use --yes for non-interactive runs)")

        result = run_install(commands, dry_run=bool(args.dry_run))
        payload = {"plan": plan, "commands": commands, **result}
        emit(args, payload, _human_install)
        return 0 if (result["dry_run"] or result["ok"]) else 1

    return _show_help(args)


__all__ = ["add_subparsers", "handler"]