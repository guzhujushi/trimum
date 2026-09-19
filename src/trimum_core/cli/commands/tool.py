"""`trm tool` command group — list and inspect registered tools."""

from __future__ import annotations

import argparse

from .._utils import emit, fail


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tool", help="inspect registered tools")
    nested = parser.add_subparsers(dest="tool_command", title="tool commands")

    list_parser = nested.add_parser("list", help="list all registered tools")
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


def _tool_to_dict(tool) -> dict:
    data = tool.model_dump()
    tool_type = getattr(tool.tool_type, "value", tool.tool_type)
    risk_level = getattr(tool.risk_level, "value", tool.risk_level)
    data["tool_type"] = tool_type
    data["risk_level"] = risk_level
    return data


def handler(args: argparse.Namespace) -> int:
    """Execute the requested tool subcommand."""
    command = getattr(args, "tool_command", None)
    if command == "list":
        registry = _registry()
        tools = [_tool_to_dict(tool) for tool in registry.list_tools()]
        emit(args, {"tools": tools})
        return 0

    if command == "info":
        registry = _registry()
        tool = registry.get(args.name)
        if tool is None:
            return fail(f"unknown tool: {args.name}")
        emit(args, {"tool": _tool_to_dict(tool)})
        return 0

    return _show_help(args)


__all__ = ["add_subparsers", "handler"]
