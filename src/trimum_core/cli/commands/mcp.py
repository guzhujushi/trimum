"""`trm mcp` — MCP servers: what is configured, what they expose, and calling one.

Server definitions are files: ``~/.trimum/mcp/<name>.json5`` (deny-by-default, see
``mcp_registry.py``).  This module is a thin shell over ``mcp_registry`` and
``tool_dispatchers.MCPDispatcher`` so the CLI and the Tool Gateway run *one*
implementation — the same code path an Agent takes.

Risk split mirrors the rest of the ecosystem work: reading definitions and listing
tools is ``low`` (nothing is written, nothing is sent), calling a tool is ``high``
and asks for confirmation unless ``--yes`` is given.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .._utils import emit, fail, run_async

__command_meta__ = {
    "mcp": {
        "summary": "MCP servers: list, inspect and call",
        "args": "{list,tools,call,paths}",
        "tags": ["mcp", "ecosystem"],
        "risk": "low",
    },
    "mcp list": {
        "summary": "List configured MCP servers and their state",
        "args": "[--dir PATH] [--enabled]",
        "examples": ["trm mcp list --json", "trm mcp list --enabled"],
        "tags": ["mcp"],
        "risk": "low",
    },
    "mcp tools": {
        "summary": "Show the tools a server exposes (starts the server)",
        "args": "[server] [--dir PATH]",
        "examples": ["trm mcp tools", "trm mcp tools filesystem"],
        "tags": ["mcp"],
        "risk": "low",
    },
    "mcp call": {
        "summary": "Call one MCP tool (asks for confirmation first)",
        "args": "<server> <tool> [json-arguments] [--yes] [--dir PATH]",
        "examples": [
            "trm mcp call echo echo '{\"text\": \"hi\"}' --yes",
            "trm mcp call filesystem read_file '{\"path\": \"/etc/hosts\"}'",
        ],
        "tags": ["mcp"],
        "risk": "high",
    },
    "mcp paths": {
        "summary": "Show where MCP server definitions are read from",
        "args": "",
        "tags": ["mcp"],
        "risk": "low",
    },
    "mcp catalog": {
        "summary": "Curated MCP candidate list (import from a README snapshot)",
        "args": "{import,list}",
        "tags": ["mcp", "ecosystem"],
        "risk": "low",
    },
    "mcp catalog import": {
        "summary": "Turn a local awesome-mcp-servers snapshot into config/mcp-catalog.yaml",
        "args": "[--source PATH] [--catalog PATH] [--dry-run] [--force] [--limit N]",
        "examples": [
            "trm mcp catalog import --dry-run",
            "trm mcp catalog import --category developer-tools --limit 50",
            "trm mcp catalog import --force",
        ],
        "tags": ["mcp", "ecosystem"],
        "risk": "medium",
    },
    "mcp catalog list": {
        "summary": "Review catalog candidates (nothing is enabled by this)",
        "args": "[--catalog PATH] [--unreviewed] [--reviewed] [--category ID] [--dist D] [--lang L] [--limit N]",
        "examples": [
            "trm mcp catalog list --unreviewed --category developer-tools",
            "trm --json mcp catalog list --dist uvx",
        ],
        "tags": ["mcp", "ecosystem"],
        "risk": "low",
    },
}


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("mcp", help="MCP servers: list, inspect and call")
    nested = parser.add_subparsers(dest="mcp_command", title="mcp commands")

    list_parser = nested.add_parser("list", help="list configured MCP servers")
    list_parser.add_argument("--dir", default="", metavar="PATH", help="read definitions elsewhere")
    list_parser.add_argument("--enabled", action="store_true", help="only enabled servers")
    list_parser.set_defaults(handler=handler)

    tools_parser = nested.add_parser("tools", help="show the tools a server exposes")
    tools_parser.add_argument("server", nargs="?", default="", metavar="SERVER", help="one server (default: all enabled)")
    tools_parser.add_argument("--dir", default="", metavar="PATH", help="read definitions elsewhere")
    tools_parser.set_defaults(handler=handler)

    call_parser = nested.add_parser("call", help="call one MCP tool")
    call_parser.add_argument("server", metavar="SERVER", help="server name (the definition's file name)")
    call_parser.add_argument("tool", metavar="TOOL", help="tool name as exposed by the server")
    call_parser.add_argument("arguments", nargs="*", metavar="JSON", help="tool arguments as a JSON object")
    call_parser.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    call_parser.add_argument("--dir", default="", metavar="PATH", help="read definitions elsewhere")
    call_parser.set_defaults(handler=handler)

    paths_parser = nested.add_parser("paths", help="show where definitions are read from")
    paths_parser.add_argument("--dir", default="", metavar="PATH", help="read definitions elsewhere")
    paths_parser.set_defaults(handler=handler)

    catalog_parser = nested.add_parser(
        "catalog", help="curated candidate list (import / review)"
    )
    catalog_nested = catalog_parser.add_subparsers(dest="catalog_command", title="catalog commands")

    import_parser = catalog_nested.add_parser(
        "import", help="turn a local awesome-mcp-servers snapshot into the catalog"
    )
    import_parser.add_argument(
        "--source", default="", metavar="PATH", help="README snapshot (default: tmp/research/awesome-README.md)"
    )
    import_parser.add_argument(
        "--catalog", default="", metavar="PATH", help="catalog file to write (default: config/mcp-catalog.yaml)"
    )
    import_parser.add_argument("--dry-run", action="store_true", help="report the selection without writing")
    import_parser.add_argument(
        "--force", action="store_true", help="overwrite an existing catalog (keeps reviewed/name/note)"
    )
    import_parser.add_argument(
        "--all-languages", action="store_true", help="drop the language red line (keeps TS/Java/... too)"
    )
    import_parser.add_argument(
        "--include-npx", action="store_true", help="also accept npx/npm/deno entries (Node toolchain)"
    )
    import_parser.add_argument(
        "--include-unknown-dist", action="store_true", help="also accept entries with no install hint"
    )
    import_parser.add_argument(
        "--category", action="append", metavar="ID", help="keep only these categories (repeatable)"
    )
    import_parser.add_argument(
        "--exclude-category", action="append", metavar="ID", help="drop these categories (repeatable)"
    )
    import_parser.add_argument("--limit", type=int, default=0, metavar="N", help="keep only the first N candidates")
    import_parser.set_defaults(handler=handler)

    catalog_list_parser = catalog_nested.add_parser(
        "list", help="review catalog candidates"
    )
    catalog_list_parser.add_argument(
        "--catalog", default="", metavar="PATH", help="catalog file to read (default: config/mcp-catalog.yaml)"
    )
    catalog_list_parser.add_argument("--reviewed", action="store_true", help="only human-reviewed entries")
    catalog_list_parser.add_argument("--unreviewed", action="store_true", help="only entries still to review")
    catalog_list_parser.add_argument("--category", default="", metavar="ID", help="filter by category id or label")
    catalog_list_parser.add_argument("--dist", default="", metavar="D", help="filter by distribution")
    catalog_list_parser.add_argument("--lang", default="", metavar="L", help="filter by language")
    catalog_list_parser.add_argument("--limit", type=int, default=0, metavar="N", help="show at most N entries")
    catalog_list_parser.set_defaults(handler=handler)

    catalog_parser.set_defaults(handler=_catalog_help)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm mcp {list,tools,call,paths} ...")
    return 0


# ---------------------------------------------------------------------------
# Shared plumbing
# ---------------------------------------------------------------------------


def _dispatcher(args: argparse.Namespace):
    """Build an MCP dispatcher (same object the Tool Gateway uses)."""
    from trimum_core.mcp_registry import MCPRegistry
    from trimum_core.tool_dispatchers import MCPDispatcher

    directory = (getattr(args, "dir", "") or "").strip()
    registry = MCPRegistry(directory) if directory else MCPRegistry()
    return MCPDispatcher(registry=registry)


async def _run_once(dispatcher, request):
    """Execute one request and always stop the servers this run started."""
    try:
        return await dispatcher.execute(request)
    finally:
        await dispatcher.close()


def _confirm(question: str) -> bool:
    """Ask before running a high-risk call; never prompt in a piped run."""
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        print()
        return False
    return answer in ("y", "yes")


def _structured(output: str):
    """Return parsed JSON when the dispatcher emitted JSON, else the raw text."""
    text = (output or "").strip()
    if not text.startswith("{"):
        return text
    try:
        return json.loads(text)
    except ValueError:
        return text


# ---------------------------------------------------------------------------
# Human output
# ---------------------------------------------------------------------------


def _human_list(data: dict) -> None:
    print(f"definitions: {data['directory']}" + ("" if data["exists"] else "  (missing)"))
    if not data["servers"]:
        print("no MCP server configured (deny-by-default; drop a <name>.json5 there)")
    for item in data["servers"]:
        state = "enabled" if item["enabled"] else "disabled"
        print(
            f"  {item['name']:<16}{state:<9}{item['trust']:<7}{item['transport']:<6}"
            f"{item['risk']:<7}{item['command'] or item['url']}"
        )
        if item["description"]:
            print(f"    {item['description']}")
        if item["deny_patterns"]:
            print(f"    deny: {', '.join(item['deny_patterns'])}")
    for problem in data["problems"]:
        print(f"  [!] {problem['path']}: {problem['error']}")


def _human_tools(data: dict) -> None:
    for server in data.get("servers", []):
        if not server.get("ok"):
            print(f"{server['server']}: error: {server.get('error', '')}")
            continue
        print(f"{server['server']} ({server['count']} tools, trust={server['trust']})")
        for tool in server["tools"]:
            print(f"  {tool['name']:<28}{tool['description']}")


def _human_call(data: dict) -> None:
    state = "error" if data.get("is_error") else "ok"
    print(f"{data['server']}.{data['tool']} [{state}] {data['duration_ms']}ms")
    if data.get("text"):
        print(data["text"])


def _human_paths(data: dict) -> None:
    print(f"definitions : {data['directory']}" + ("" if data["exists"] else "  (missing)"))
    print(f"override    : export {data['config_env']}=/path/to/dir")
    print(f"servers     : {data['count']} configured, {len(data['enabled'])} enabled")


# ---------------------------------------------------------------------------
# `trm mcp catalog` — the curation importer (M3, docs/MCP-INTEGRATION-PLAN.md)
# ---------------------------------------------------------------------------


def _catalog_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm mcp catalog {import,list} ...")
    return 0


def _catalog_selection(args: argparse.Namespace):
    """Build the red-line selection from the flags of `catalog import`."""
    from trimum_core.mcp_catalog import (
        ALL_LANGUAGES,
        ALLOWED_DISTRIBUTIONS,
        ALLOWED_LANGUAGES,
        NODE_DISTRIBUTIONS,
        SelectOptions,
    )

    languages = ALL_LANGUAGES if getattr(args, "all_languages", False) else ALLOWED_LANGUAGES
    distributions = list(ALLOWED_DISTRIBUTIONS)
    if getattr(args, "include_npx", False):
        distributions += list(NODE_DISTRIBUTIONS)
    if getattr(args, "include_unknown_dist", False):
        distributions.append("unknown")

    return SelectOptions(
        languages=tuple(languages),
        distributions=tuple(distributions),
        categories=tuple(getattr(args, "category", None) or ()),
        exclude_categories=tuple(getattr(args, "exclude_category", None) or ()),
        limit=int(getattr(args, "limit", 0) or 0),
    )


def _catalog_path(args: argparse.Namespace) -> Path:
    """Return the catalog file to read or write (`--catalog` wins)."""
    from trimum_core.mcp_catalog import DEFAULT_CATALOG

    custom = (getattr(args, "catalog", "") or "").strip()
    return Path(custom).expanduser() if custom else DEFAULT_CATALOG


def _catalog_source(args: argparse.Namespace) -> Path:
    """Return the README snapshot to import from."""
    from trimum_core.mcp_catalog import DEFAULT_SOURCE

    custom = (getattr(args, "source", "") or "").strip()
    return Path(custom).expanduser() if custom else DEFAULT_SOURCE


def _human_catalog_import(data: dict) -> None:
    state = "written" if data["written"] else "dry-run, nothing written"
    print(f"source    : {data['source']}")
    print(f"catalog   : {data['catalog']}  [{state}]")
    print(
        f"selection : {data['parsed']} entries -> {data['candidates']} candidates"
        f"  ({data['reviewed_carried']} reviewed carried over, {data['bytes']} bytes)"
    )
    print("excluded (red line + narrowing):")
    for reason, count in sorted(data["excluded"].items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count:>6}  {reason}")
    if data["preview"]:
        print("first candidates:")
        for item in data["preview"]:
            print(f"  {item['name']:<30}{item['dist']:<7}{item['trust']:<7}{item['repo']}")
    if data["written"]:
        print("next: 人工审核该文件 —— 把要启用的条目 reviewed 改成 true，再转成 ~/.trimum/mcp/<name>.json5")


def _human_catalog_list(data: dict) -> None:
    from trimum_core.mcp_catalog import display_path

    state = f"{data['total']} candidates" if data["exists"] else "missing"
    print(f"catalog   : {display_path(data['path'])}  ({state})")
    print(f"reviewed  : {data['reviewed']} / {data['total']}   shown: {data['shown']}")
    for item in data["entries"]:
        mark = "x" if item.get("reviewed") else " "
        label = str(item.get("category_label", ""))[:26]
        flags = ",".join(item.get("flags") or [])
        print(
            f"  [{mark}] {str(item.get('name', ''))[:30]:<30}{str(item.get('dist', '')):<7}"
            f"{str(item.get('trust', '')):<7}{label:<27}{item.get('repo', '')}"
            + (f"  [{flags}]" if flags else "")
        )


def _catalog_import(args: argparse.Namespace) -> int:
    """Parse a local README snapshot into the candidate catalog."""
    from trimum_core import mcp_catalog as catalog

    source = _catalog_source(args)
    target = _catalog_path(args)
    if not source.is_file():
        return fail(
            f"README snapshot not found: {source}"
            "（导入器不联网：先把 awesome-mcp-servers 的 README 落到该路径）"
        )

    previous = catalog.load_catalog(target)
    if previous.exists and not args.force and not args.dry_run:
        return fail(
            f"{target} 已存在（{previous.reviewed} 条已人工审核）——"
            "确认覆盖请加 --force（会按 repo 保留 reviewed/name/note）"
        )

    options = _catalog_selection(args)
    selection, entries = catalog.import_catalog(source, options=options, previous=previous)
    document = catalog.render_catalog(
        entries, source=source, selection=selection, options=options
    )
    if not args.dry_run:
        catalog.write_catalog(target, document, force=True)

    emit(
        args,
        {
            **selection.to_dict(),
            "source": catalog.display_path(source),
            "catalog": catalog.display_path(target),
            "written": not args.dry_run,
            "reviewed_carried": sum(1 for entry in entries if entry.reviewed),
            "bytes": len(document.encode("utf-8")),
            "options": options.to_dict(),
            "preview": [entry.to_dict() for entry in entries[:8]],
        },
        _human_catalog_import,
    )
    return 0


def _catalog_list(args: argparse.Namespace) -> int:
    """Show catalog entries, optionally filtered — the review entry point."""
    from trimum_core import mcp_catalog as catalog

    target = _catalog_path(args)
    document = catalog.load_catalog(target)
    if not document.exists:
        return fail(f"catalog not found: {target}（先跑 `trm mcp catalog import`）")

    only_reviewed = bool(getattr(args, "reviewed", False))
    only_unreviewed = bool(getattr(args, "unreviewed", False))
    category = (getattr(args, "category", "") or "").strip().lower()
    dist = (getattr(args, "dist", "") or "").strip().lower()
    lang = (getattr(args, "lang", "") or "").strip().lower()

    shown: list[dict] = []
    for entry in document.entries:
        reviewed = bool(entry.get("reviewed"))
        if only_reviewed and not reviewed:
            continue
        if only_unreviewed and reviewed:
            continue
        if category and category not in {
            str(entry.get("category", "")).lower(),
            str(entry.get("category_label", "")).lower(),
        }:
            continue
        if dist and str(entry.get("dist", "")).lower() != dist:
            continue
        if lang and str(entry.get("lang", "")).lower() != lang:
            continue
        shown.append(entry)

    limit = int(getattr(args, "limit", 0) or 0)
    if limit:
        shown = shown[:limit]

    emit(
        args,
        {**document.to_dict(), "total": len(document.entries), "shown": len(shown), "entries": shown},
        _human_catalog_list,
    )
    return 0


def _catalog_dispatch(args: argparse.Namespace) -> int:
    """Route `trm mcp catalog ...` to its handler."""
    command = getattr(args, "catalog_command", None)
    if command == "import":
        return _catalog_import(args)
    if command == "list":
        return _catalog_list(args)
    return _catalog_help(args)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(args: argparse.Namespace) -> int:
    """Run one of the `trm mcp` subcommands."""
    from trimum_core.models import ExecuteRequest, ToolType

    command = getattr(args, "mcp_command", None)
    if command == "catalog":
        return _catalog_dispatch(args)

    dispatcher = _dispatcher(args)

    if command == "list":
        data = dispatcher.status()
        if getattr(args, "enabled", False):
            data = {
                **data,
                "servers": [item for item in data["servers"] if item["enabled"]],
            }
        emit(args, data, _human_list)
        return 0

    if command == "paths":
        emit(args, dispatcher.status(), _human_paths)
        return 0

    if command == "tools":
        server = (getattr(args, "server", "") or "").strip()
        request = ExecuteRequest(
            tool=ToolType.MCP_TOOLS_LIST,
            args=[server] if server else [],
        )
        response = run_async(_run_once(dispatcher, request))
        if response.status == "denied":
            return fail(response.error)
        emit(args, _structured(response.output), _human_tools)
        return 0

    if command == "call":
        server = args.server
        tool = args.tool
        arguments = " ".join(args.arguments).strip()
        if not args.yes and not _confirm(
            f"调用 MCP 工具 {server}.{tool}，确定继续？"
        ):
            return fail("aborted (use --yes for non-interactive runs)")

        request = ExecuteRequest(
            tool=ToolType.MCP_TOOLS_CALL,
            args=[server, tool, arguments] if arguments else [server, tool],
        )
        response = run_async(_run_once(dispatcher, request))
        if response.status == "denied":
            return fail(response.error)

        emit(args, _structured(response.output), _human_call)
        if response.status == "error":
            return fail(response.error or f"MCP tool '{tool}' reported an error")
        return 0

    return _show_help(args)


__all__ = ["add_subparsers", "handler"]