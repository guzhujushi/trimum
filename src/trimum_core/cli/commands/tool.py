"""`trm tool` command group — list and inspect registered tools."""

from __future__ import annotations

import argparse

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
    list_parser.set_defaults(handler=handler)

    info_parser = nested.add_parser("info", help="show tool details")
    info_parser.add_argument("name")
    info_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm tool {list,info} ...")
    return 0


def _registry():
    from trimum_core.tool_gateway import ToolRegistry

    return ToolRegistry()


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


def handler(args: argparse.Namespace) -> int:
    """Execute the requested tool subcommand."""
    command = getattr(args, "tool_command", None)
    if command == "list":
        registry = _registry()
        tools = []
        for tool in registry.list_tools():
            binding = registry.mcp_binding(tool.name)
            if getattr(args, "mcp", False) and binding is None:
                continue
            tools.append(_tool_to_dict(tool, binding))
        emit(args, {"tools": tools, "count": len(tools)})
        return 0

    if command == "info":
        registry = _registry()
        tool = registry.get(args.name)
        if tool is None:
            return fail(f"unknown tool: {args.name}")
        emit(args, {"tool": _tool_to_dict(tool, registry.mcp_binding(tool.name))})
        return 0

    return _show_help(args)


__all__ = ["add_subparsers", "handler"]
