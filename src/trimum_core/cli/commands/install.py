"""`trm install` — official package channel + legacy first-time setup guide.

Three entry points live here on purpose:

* ``trm install`` (no arguments) keeps the original guided flow (systemd service,
  API key, preset agents) implemented by :func:`trimum_core.install_fn.install`;
* ``trm install --setup`` runs the structured first-run wizard (``trm setup``);
* ``trm install <name>`` / ``trm install --file <pkg>`` is the official package
  channel (E5 in ``docs/ECOSYSTEM-STRATEGY.md`` §7): verify the ``.trmpkg`` against
  the built-in trust root, unpack it into the matching data root, and record it.

The two cannot be confused: the wizard never takes a positional name, and the
package channel never runs install-time provisioning.  ``--list`` shows what the
channel has put on this machine.

安装 ≠ 授权：这里只决定「东西怎么可信地到达本机」，能不能执行仍由运行期策略决定。
"""

from __future__ import annotations

import argparse

from .._utils import emit, fail

__command_meta__ = {
    "install": {
        "summary": "Install a package from the official channel, or run first-time setup",
        "args": (
            "[name] [--file PKG] [--index SOURCE] [--list] "
            "[--allow-untrusted] [--force] [--setup]"
        ),
        "examples": [
            "trm install demo-agent",
            "trm install --file dist/demo-1.0.0.trmpkg",
            "trm install --list --json",
        ],
        "tags": ["pkg", "ecosystem", "trust"],
        "risk": "medium",
    },
}


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "install",
        help="install a package from the official channel, or run first-time setup",
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


def handler(args: argparse.Namespace) -> int:
    """Install from the official channel, list it, run setup, or run the legacy guide."""
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