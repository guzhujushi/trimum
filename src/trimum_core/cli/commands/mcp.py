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
# Handler
# ---------------------------------------------------------------------------


def handler(args: argparse.Namespace) -> int:
    """Run one of the `trm mcp` subcommands."""
    from trimum_core.models import ExecuteRequest, ToolType

    command = getattr(args, "mcp_command", None)
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