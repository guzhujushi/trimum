"""`trm memory` command group — list/get/set/search/stats."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from .._utils import emit, fail, run_async


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("memory", help="inspect and update memory")
    nested = parser.add_subparsers(dest="memory_command", title="memory commands")

    list_parser = nested.add_parser("list", help="list memory categories")
    list_parser.add_argument("--category", help="filter by category/domain")
    list_parser.set_defaults(handler=handler)

    get_parser = nested.add_parser("get", help="get one memory entry")
    get_parser.add_argument("key")
    get_parser.set_defaults(handler=handler)

    set_parser = nested.add_parser("set", help="write and classify a memory entry")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.set_defaults(handler=handler)

    search_parser = nested.add_parser("search", help="semantic full-text search")
    search_parser.add_argument("query")
    search_parser.set_defaults(handler=handler)

    stats_parser = nested.add_parser("stats", help="memory statistics")
    stats_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm memory {list,get,set,search,stats} ...")
    return 0


def _resolve_memory_root(config) -> Path:
    """Choose a writable memory directory.

    The primary location follows trimum's user-directory convention
    (``~/.trimum/memory``).  In restricted environments such as sandboxed
    test runners, fall back to a temporary directory so read-only commands
    still work.
    """
    candidates: list[Path] = []
    env_path = os.environ.get("TRIMUM_MEMORY_DIR")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.home() / ".trimum" / "memory")
    candidates.append(Path(config.context_db_path).parent / "memory")
    candidates.append(Path(tempfile.gettempdir()) / "trimum-memory")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path(tempfile.gettempdir()) / "trimum-memory"


async def _memory_data(args: argparse.Namespace) -> dict:
    from trimum_core.config import Config
    from trimum_core.context_manager import ContextManager
    from trimum_core.memory_classifier import MemoryClassifier

    config = Config()
    memory_root = _resolve_memory_root(config)
    db_dir = str(memory_root)
    classifier_path = str(memory_root / "memory_classifier.db")

    context = ContextManager(db_dir)
    classifier = MemoryClassifier(classifier_path, cm=context)
    try:
        await context.initialize()
        await classifier.initialize()

        command = getattr(args, "memory_command", None)
        if command == "list":
            categories = await classifier.list_categories(
                domain=getattr(args, "category", None)
            )
            return {"command": "list", "categories": categories}

        if command == "get":
            key = args.key
            value = await context.get_global(key)
            if value is None:
                await context.initialize("trm-exec")
                value = await context.get("trm-exec", key, namespace="agent_memory")
            return {"command": "get", "key": key, "value": value}

        if command == "set":
            key = args.key
            value = args.value
            await context.initialize("trm-exec")
            await context.set_global(key, value)
            await context.set("trm-exec", key, value, namespace="agent_memory")
            await classifier.add_category("general", "general")
            await classifier.index_memory(key, "general", "general", "trm-exec")
            return {"command": "set", "key": key, "value": value, "status": "ok"}

        if command == "search":
            results = await context.search(args.query)
            return {"command": "search", "query": args.query, "results": results}

        if command == "stats":
            stats = await classifier.stats()
            global_entries = await context.list_global()
            stats["global_entries"] = len(global_entries)
            return {"command": "stats", "stats": stats}

        return {"command": command, "error": "unknown memory subcommand"}
    finally:
        await context.close()
        await classifier.close()


def handler(args: argparse.Namespace) -> int:
    """Execute the requested memory subcommand."""
    try:
        data = run_async(_memory_data(args))
    except Exception as exc:
        return fail(f"memory operation failed: {exc}")

    emit(args, data)
    if isinstance(data, dict) and data.get("error"):
        return 1
    return 0


__all__ = ["add_subparsers", "handler"]
