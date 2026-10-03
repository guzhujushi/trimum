"""`trm tool` command group — inspect tools, import external CLIs.

``import-cli`` is the E4 on-ramp (`docs/E4-PLAN.md`): probe an already-installed
binary with ``--help``, grade the risk, and write a disabled manifest.  Importing
never enables anything — that is a separate, explicit ``trm tool enable``.
"""

from __future__ import annotations

import argparse

from .._ask import ask_confirm
from .._utils import emit, fail


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tool", help="inspect registered tools")
    nested = parser.add_subparsers(dest="tool_command", title="tool commands")

    list_parser = nested.add_parser("list", help="list all registered tools")
    list_parser.add_argument(
        "--mcp",
        action="store_true",
        help="only tools aggregated from MCP servers (<server>__<tool>)",
    )
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="include manifests that are on disk but disabled",
    )
    list_parser.add_argument("--root", default=None, help="tool root (default <TRIMUM_HOME>/tools)")
    list_parser.set_defaults(handler=handler)

    info_parser = nested.add_parser("info", help="show tool details")
    info_parser.add_argument("name")
    info_parser.set_defaults(handler=handler)

    import_parser = nested.add_parser(
        "import-cli",
        help="register an installed CLI as a trimum tool (probed via --help)",
    )
    import_parser.add_argument("binary", help="binary name on PATH, e.g. gh")
    import_parser.add_argument("--name", default=None, help="tool name (default: binary name)")
    import_parser.add_argument(
        "--trust",
        default="third-party",
        choices=["official", "curated", "third-party", "local"],
    )
    import_parser.add_argument("--source-url", default="", help="where the tool comes from")
    import_parser.add_argument("--author", default="", help="who maintains it")
    import_parser.add_argument(
        "--timeout", type=float, default=None, help="tool timeout in seconds (default 30)"
    )
    import_parser.add_argument(
        "--subcommands",
        type=int,
        default=None,
        help="how many subcommands to expand-probe (default 12, 0 = none)",
    )
    import_parser.add_argument("--root", default=None, help="tool root (default <TRIMUM_HOME>/tools)")
    import_parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    import_parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    import_parser.add_argument("--force", action="store_true", help="overwrite an existing tool")
    import_parser.add_argument(
        "--enable",
        action="store_true",
        help="write the manifest enabled (default: disabled until trm tool enable)",
    )
    import_parser.set_defaults(handler=handler)

    for name, state in (("enable", True), ("disable", False)):
        toggle = nested.add_parser(
            name, help=f"{name} a file-based tool without touching its other settings"
        )
        toggle.add_argument("tool_name")
        toggle.add_argument("--root", default=None)
        toggle.set_defaults(handler=handler, enabled_state=state)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm tool {list,info,import-cli,enable,disable} ...")
    return 0


def _registry(root: str | None = None):
    """Build a registry over the *same* root the importers write to.

    ``ToolRegistry()`` would fall back to the real home directory; resolving the
    root through ``paths.trimum_home`` instead keeps ``import-cli`` / ``enable``
    and ``list`` pointing at one place (production behaviour is unchanged:
    without ``TRIMUM_HOME`` both are ``~/.trimum/tools``).
    """
    from trimum_core.cli_adapter import tools_root
    from trimum_core.tool_gateway import ToolRegistry

    return ToolRegistry(str(tools_root(root)))


def _tool_to_dict(tool, binding: dict | None = None) -> dict:
    """One tool as a JSON-ready dict, tagged with where it came from.

    ``binding`` is the provenance record for aggregated remote tools
    (``ToolRegistry.mcp_binding``); built-in and file-based tools report
    ``source: "local"`` so a caller never has to guess from the name.
    """
    data = tool.model_dump()
    tool_type = getattr(tool.tool_type, "value", tool.tool_type)
    risk_level = getattr(tool.risk_level, "value", tool.risk_level)
    data["tool_type"] = tool_type
    data["risk_level"] = risk_level
    if binding is None:
        data["source"] = "local"
        return data
    data["source"] = "mcp"
    data["mcp"] = {
        "server": binding.get("server"),
        "tool": binding.get("tool"),
        "transport": binding.get("transport"),
        "trust": binding.get("trust"),
        "updated_at": binding.get("updated_at"),
    }
    return data


def _manifest_to_dict(record: dict) -> dict:
    """One on-disk manifest (enabled or not) as a JSON-ready dict."""
    manifest = record.get("manifest") or {}
    return {
        "name": record["name"],
        "source": "local",
        "enabled": record["enabled"],
        "path": record["path"],
        "risk_level": manifest.get("risk", ""),
        "trust": manifest.get("trust", ""),
        "requires": manifest.get("requires", []),
        "source_url": manifest.get("source_url", ""),
        "origin": manifest.get("origin", ""),
    }


def _human_import(data: dict) -> None:
    prefix = "dry-run: " if data["dry_run"] else ""
    entry = data["entry"]
    print(f"{prefix}tool {entry['name']} (from {entry['details'].get('binary')})")
    print(f"  risk   : {entry['risk']}")
    for reason in entry["risk_reasons"]:
        print(f"           - {reason}")
    print(f"  trust  : {entry['trust']}   enabled: {entry['enabled']}")
    detected = entry["details"].get("subcommands") or []
    print(f"  subs   : {len(detected)} detected"
          + (f" ({', '.join(detected[:8])}{'…' if len(detected) > 8 else ''})" if detected else ""))
    dropped = data["manifest"]["binding"]["dropped_flags"]
    if dropped:
        print(f"  dropped: {', '.join(dropped)} (免确认旗标不进白名单)")
    print(f"  target : {data['target_dir']}")
    if data["written"]:
        print("  wrote  :")
        for path in data["written"]:
            print(f"           {path}")
        if not entry["enabled"]:
            print(f"  提示   : 默认未启用，确认无误后执行 trm tool enable {entry['name']}")


def _human_toggle(data: dict) -> None:
    state = "enabled" if data["enabled"] else "disabled"
    print(f"{data['name']}: {state}")
    print(f"  {data['path']}")


def _human_list_all(data: dict) -> None:
    for item in data["tools"]:
        state = "on " if item.get("enabled", True) else "off"
        risk = item.get("risk_level") or "-"
        print(f"  [{state}] {item['name']:<24} risk={risk:<8} {item.get('trust', '')}")
        if "path" in item:
            print(f"        {item['path']}")


def _handle_list(args: argparse.Namespace) -> int:
    root = getattr(args, "root", None)
    registry = _registry(root)
    tools = []
    for tool in registry.list_tools():
        binding = registry.mcp_binding(tool.name)
        if getattr(args, "mcp", False) and binding is None:
            continue
        tools.append(_tool_to_dict(tool, binding))

    if not getattr(args, "all", False):
        emit(args, {"tools": tools, "count": len(tools)})
        return 0

    from trimum_core.cli_adapter import tools_root
    from trimum_core.tool_file_loader import list_manifests

    registered = {item["name"] for item in tools}
    manifests = [
        _manifest_to_dict(record)
        for record in list_manifests(str(tools_root(root)))
        if record["name"] not in registered
    ]
    payload = {"tools": tools + manifests, "count": len(tools) + len(manifests)}
    emit(args, payload, _human_list_all)
    return 0


def _handle_import_cli(args: argparse.Namespace) -> int:
    from trimum_core import cli_adapter
    from trimum_core.ecosystem import validate_entry

    limit = (
        cli_adapter.DEFAULT_SUBCOMMAND_LIMIT
        if getattr(args, "subcommands", None) is None
        else max(0, args.subcommands)
    )
    probe = cli_adapter.probe_binary(args.binary, subcommand_limit=limit)
    if not probe.found:
        return fail(f"cannot probe {args.binary}: {probe.error or 'unknown error'}")

    plan = cli_adapter.plan_import(
        probe,
        name=args.name,
        trust=args.trust,
        source_url=args.source_url,
        author=args.author,
        root=args.root,
        timeout=args.timeout or cli_adapter.DEFAULT_TOOL_TIMEOUT,
    )
    entry = plan["entry"]
    problems = validate_entry(entry)
    if problems:
        return fail("invalid entry: " + "; ".join(problems))

    written: list[str] = []
    if not args.dry_run:
        if not args.yes:
            question = (
                f"import {entry.name} (risk={entry.risk}, "
                f"{'enabled' if args.enable else 'disabled'}) into {plan['target_dir']}?"
            )
            if not ask_confirm(question):
                return fail("aborted (use --yes for non-interactive runs)")
        try:
            written = cli_adapter.write_tool(
                plan, force=args.force, enable=args.enable
            )
        except cli_adapter.ImportRefused as exc:
            return fail(str(exc))
        if args.enable:
            entry.enabled = True

    payload = {
        "dry_run": bool(args.dry_run),
        "binary": probe.to_dict(),
        "entry": entry.to_dict(),
        "manifest": plan["manifest"],
        "target_dir": plan["target_dir"],
        "files": plan["files"],
        "warnings": plan["warnings"],
        "written": written,
    }
    emit(args, payload, _human_import)
    return 0


def _handle_toggle(args: argparse.Namespace) -> int:
    from trimum_core.cli_adapter import tools_root
    from trimum_core.tool_file_loader import load_manifest, set_manifest_enabled

    name = args.tool_name
    path = tools_root(getattr(args, "root", None)) / name / "tool.json5"
    if not path.is_file():
        return fail(f"no tool manifest at {path}")
    if load_manifest(path) is None:
        return fail(f"cannot parse {path}")
    if not set_manifest_enabled(path, bool(args.enabled_state)):
        return fail(f"cannot update {path}")

    payload = {
        "name": name,
        "enabled": bool(args.enabled_state),
        "path": str(path),
    }
    emit(args, payload, _human_toggle)
    return 0


def handler(args: argparse.Namespace) -> int:
    """Execute the requested tool subcommand."""
    command = getattr(args, "tool_command", None)

    if command == "list":
        return _handle_list(args)

    if command == "info":
        registry = _registry(getattr(args, "root", None))
        tool = registry.get(args.name)
        if tool is None:
            return fail(f"unknown tool: {args.name}")
        emit(args, {"tool": _tool_to_dict(tool, registry.mcp_binding(tool.name))})
        return 0

    if command == "import-cli":
        return _handle_import_cli(args)

    if command in ("enable", "disable"):
        return _handle_toggle(args)

    return _show_help(args)


__command_meta__ = {
    "tool import-cli": {
        "summary": "Register an installed CLI as a tool by probing its --help",
        "args": "<binary> [--name N] [--trust T] [--root DIR] [--dry-run] [--yes] [--force] [--enable]",
        "examples": [
            "trm tool import-cli gh --dry-run",
            "trm tool import-cli fd --yes",
        ],
        "risk": "medium",
        "tags": ["tool", "ecosystem"],
        "since": "0.6.0",
    },
    "tool enable": {
        "summary": "Enable a file-based tool (flips one field in tool.json5)",
        "args": "<name> [--root DIR]",
        "examples": ["trm tool enable gh"],
        "risk": "medium",
        "tags": ["tool", "trust"],
        "since": "0.6.0",
    },
    "tool disable": {
        "summary": "Disable a file-based tool without deleting it",
        "args": "<name> [--root DIR]",
        "examples": ["trm tool disable gh"],
        "risk": "low",
        "tags": ["tool", "trust"],
        "since": "0.6.0",
    },
    "tool list": {
        "summary": "List registered tools (--all also shows disabled manifests)",
        "args": "[--mcp] [--all] [--root DIR]",
        "examples": ["trm tool list --json", "trm tool list --all"],
        "risk": "low",
        "tags": ["tool"],
    },
}


__all__ = ["add_subparsers", "handler"]
