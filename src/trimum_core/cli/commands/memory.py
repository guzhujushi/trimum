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

    list_parser = nested.add_parser("list", help="list memory categories and entries")
    list_parser.add_argument("--domain", help="filter by domain")
    list_parser.add_argument("--category", help="filter by category")
    list_parser.add_argument("--entries", action="store_true", help="include indexed entries")
    list_parser.add_argument("--limit", type=int, default=50, help="max entries (default: 50)")
    list_parser.set_defaults(handler=handler)

    get_parser = nested.add_parser("get", help="get one memory entry")
    get_parser.add_argument("key")
    get_parser.set_defaults(handler=handler)

    set_parser = nested.add_parser("set", help="write and classify a memory entry")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.set_defaults(handler=handler)

    search_parser = nested.add_parser("search", help="full-text search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=20, help="max results (default: 20)")
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


def _format_value(value) -> str:
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=False)
    return str(value)


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
            domain = getattr(args, "domain", None)
            category = getattr(args, "category", None)
            limit = int(getattr(args, "limit", 50) or 50)
            categories = await classifier.list_categories(domain=domain)
            if category:
                categories = [item for item in categories if item.get("category") == category]

            entries: list[dict] = []
            if getattr(args, "entries", False):
                if domain:
                    entries = await classifier.query_by_domain(domain, limit=limit)
                elif category:
                    entries = await classifier.query_by_category(category, domain=domain, limit=limit)
            return {
                "command": "list",
                "domain": domain,
                "category": category,
                "categories": categories,
                "entries": entries,
            }

        if command == "get":
            key = args.key
            value = await context.get_global(key)
            if value is None:
                await context.initialize("trm-exec")
                value = await context.get("trm-exec", key, namespace="agent_memory")
            return {
                "command": "get",
                "key": key,
                "value": value,
                "found": value is not None,
            }

        if command == "set":
            key = args.key
            value = args.value
            await context.initialize("trm-exec")
            await context.set_global(key, value)
            await context.set("trm-exec", key, value, namespace="agent_memory")
            await classifier.add_category("general", "general", "Auto classified by trm memory set")
            await classifier.index_memory(key, "general", "general", "trm-exec")
            return {"command": "set", "key": key, "value": value, "status": "ok"}

        if command == "search":
            limit = int(getattr(args, "limit", 20) or 20)
            results = await context.search(args.query, limit=limit)
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


def _human(data: dict) -> None:
    command = data.get("command")
    if command == "list":
        categories = data.get("categories") or []
        if not categories:
            print("(no categories)")
        else:
            by_domain: dict[str, list[str]] = {}
            for item in categories:
                by_domain.setdefault(item.get("domain", "unknown"), []).append(item.get("category", ""))
            for domain, names in by_domain.items():
                print(f"[{domain}] {', '.join(names)}")
        for entry in data.get("entries") or []:
            key = entry.get("memory_key") or entry.get("key", "?")
            value = entry.get("value")
            print(f"  {entry.get('domain', '')}/{entry.get('category', '')} {key}: {_format_value(value)}")
    elif command == "get":
        if data.get("found"):
            print(f"{data['key']}: {_format_value(data.get('value'))}")
        else:
            print(f"(not found) {data['key']}")
    elif command == "set":
        print(f"stored {data['key']} = {_format_value(data.get('value'))}")
    elif command == "search":
        results = data.get("results") or []
        if not results:
            print("(no results)")
        for item in results:
            agent = item.get("agent_id") or item.get("project_id") or "-"
            print(f"{item.get('key')} [{agent}]: {_format_value(item.get('value'))}")
    elif command == "stats":
        stats = data.get("stats") or {}
        print(f"categories: {stats.get('total_categories', 0)}")
        print(f"indexed: {stats.get('total_indexed', 0)}")
        print(f"global entries: {stats.get('global_entries', 0)}")
        by_domain = stats.get("by_domain") or {}
        for domain, count in by_domain.items():
            print(f"  {domain}: {count}")


def handler(args: argparse.Namespace) -> int:
    """Execute the requested memory subcommand."""
    try:
        data = run_async(_memory_data(args))
    except Exception as exc:
        return fail(f"memory operation failed: {exc}")

    emit(args, data, _human)
    if isinstance(data, dict) and data.get("error"):
        return 1
    if isinstance(data, dict) and data.get("command") == "get" and data.get("found") is False:
        return 1
    return 0


__all__ = ["add_subparsers", "handler"]