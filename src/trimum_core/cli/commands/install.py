"""`trm install` — official package channel + legacy first-time setup guide.

Four entry points live here on purpose:

* ``trm install`` (no arguments) keeps the original guided flow (systemd service,
  API key, preset agents) implemented by :func:`trimum_core.install_fn.install`;
* ``trm install --setup`` runs the structured first-run wizard (``trm setup``);
* ``trm install <name>`` / ``trm install --file <pkg>`` is the official package
  channel (E5 in ``docs/ECOSYSTEM-STRATEGY.md`` §7): verify the ``.trmpkg`` against
  the built-in trust root, unpack it into the matching data root, and record it.
* ``trm install --remove <name>`` takes a package back off this machine (E5, third slice).

The two cannot be confused: the wizard never takes a positional name, and the
package channel never runs install-time provisioning.  ``--list`` shows what the
channel has put on this machine.

``trm install --remove <name>`` 是这条链的逆操作（E5 第三片）：删掉登记过的落地目录、
划掉登记行。它是**破坏性动作**，所以沿用 ``trm env install`` 的确认约定：交互式问一句，
非交互必须 ``--yes``（stdin 不是 TTY 时 ``ask_confirm`` 直接答 no，不会挂住），
``--dry-run`` 恒不执行。

安装 ≠ 授权：这里只决定「东西怎么可信地到达本机」，能不能执行仍由运行期策略决定。
"""

from __future__ import annotations

import argparse

from .._ask import ask_confirm
from .._utils import emit, fail

__command_meta__ = {
    "install": {
        "summary": "Install, list or remove official-channel packages, or run first-time setup",
        "args": (
            "[name] [--file PKG] [--index SOURCE] [--list] [--remove] [--yes] "
            "[--dry-run] [--allow-untrusted] [--force] [--setup]"
        ),
        "examples": [
            "trm install demo-agent",
            "trm install --file dist/demo-1.0.0.trmpkg",
            "trm install --list --json",
            "trm install --remove demo-agent --yes",
        ],
        "tags": ["pkg", "ecosystem", "trust"],
        "risk": "medium",
    },
}


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "install",
        help="install, list or remove official-channel packages, or run first-time setup",
    )
    parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="package name in the official directory (E5 channel)",
    )
    parser.add_argument(
        "--file",
        default=None,
        metavar="PKG",
        help="install a local .trmpkg instead of a directory name",
    )
    parser.add_argument(
        "--index",
        default=None,
        metavar="SOURCE",
        help=(
            "directory index: path, file:// or https:// "
            "(default: $TRIMUM_PKG_INDEX, then the official URL)"
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="show what the package channel has installed here",
    )
    parser.add_argument(
        "--allow-untrusted",
        action="store_true",
        help="accept a package that does not verify, and register it as untrusted",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an already installed item of the same name",
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="uninstall a package this channel installed (needs a name)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip the confirmation prompt (package channel only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what --remove would delete, without touching disk or ledger",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="run the newer structured wizard (same as trm setup)",
    )
    parser.set_defaults(handler=handler)


def _human_record(data: dict) -> None:
    print(
        f"installed {data['name']} {data['version']} [{data['type']}] "
        f"trust={data['trust']} -> {data['path']}"
    )
    if data.get("signer"):
        print(f"  signed by {data['signer']} ({data['signer_key_id']})")
    if data.get("cert"):
        print(f"  certificate: {data['cert']}")
    print("  install != authorize: the runtime still applies policy to every call")
    if data.get("missing_requires"):
        print(
            f"  [!] missing external dependencies: {', '.join(data['missing_requires'])} "
            "(install them when convenient; nothing has to be reinstalled)"
        )
    if data.get("warning"):
        print(f"[!] {data['warning']}")


def _human_list(data: dict) -> None:
    if not data["packages"]:
        print("no packages installed through the official channel")
        return
    for record in data["packages"]:
        print(
            f"{record['name']} {record.get('version', '')} [{record.get('type', '')}] "
            f"trust={record.get('trust', '?')} {record.get('path', '')}"
        )


def _install(args: argparse.Namespace) -> dict:
    from trimum_core.pkg_install import install_from_index, install_package

    if args.file:
        return install_package(
            args.file,
            allow_untrusted=bool(args.allow_untrusted),
            force=bool(args.force),
            source=str(args.file),
        )
    return install_from_index(
        args.name,
        index_source=args.index,
        allow_untrusted=bool(args.allow_untrusted),
        force=bool(args.force),
    )


def _human_remove(data: dict) -> None:
    prefix = "would remove" if data["dry_run"] else "removed"
    print(f"{prefix} {data['name']} {data['version']} [{data['type']}] {data['path']}")
    if data["dry_run"]:
        print("  dry run: nothing on disk and nothing in the ledger was touched")
        return
    if data.get("path_missing"):
        print("  the registered path was already gone: only the registration was dropped")
    print("  unregistered: the runtime no longer treats it as installed")


def _remove(args: argparse.Namespace, name: str) -> int:
    """Uninstall *name*: validate, confirm, delete the payload, unregister it."""
    from trimum_core.models import TrimumError
    from trimum_core.pkg_install import remove_package

    try:
        if getattr(args, "dry_run", False):
            report = remove_package(name, dry_run=True)
        else:
            # 先干跑一遍：红线过不去就别弹确认（免得用户先点头再被拒）。
            remove_package(name, dry_run=True)
            if not getattr(args, "yes", False) and not ask_confirm(
                f"uninstall {name}? its directory and its registration both go away"
            ):
                return fail("aborted (use --yes for non-interactive runs)")
            report = remove_package(name)
    except TrimumError as exc:
        return fail(f"{exc.code.value} {exc.message}")
    except OSError as exc:
        return fail(f"remove failed: {exc}")

    emit(args, report, _human_remove)
    return 0


def handler(args: argparse.Namespace) -> int:
    """Install from the official channel, list it, remove it, run setup, or the legacy guide."""
    from trimum_core.models import TrimumError
    from trimum_core.pkg_install import installed_records

    if getattr(args, "setup", False):
        from trimum_core.cli.commands.setup import _human
        from trimum_core.setup_wizard import STEPS, run_setup

        report = run_setup(steps=STEPS)
        emit(args, report, _human)
        return 0

    if getattr(args, "list", False):
        records = installed_records()
        emit(
            args,
            {
                "count": len(records),
                "packages": [records[name] for name in sorted(records)],
            },
            _human_list,
        )
        return 0

    name = getattr(args, "name", None)
    if getattr(args, "remove", False):
        if getattr(args, "file", None):
            return fail("--remove and --file cannot be combined")
        if not name:
            return fail("--remove needs a package name (see trm install --list)")
        return _remove(args, name)

    if name and getattr(args, "file", None):
        return fail("give either a package name or --file <pkg>, not both")

    if not name and not getattr(args, "file", None):
        from trimum_core.install_fn import install

        install()
        return 0

    try:
        record = _install(args)
    except TrimumError as exc:
        return fail(f"{exc.code.value} {exc.message}")
    except OSError as exc:
        return fail(str(exc))

    emit(args, record, _human_record)
    return 0


__all__ = ["add_subparsers", "handler"]