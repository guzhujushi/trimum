"""`trm status` command — report daemon and runtime status."""

from __future__ import annotations

import argparse

from .._utils import emit, get_daemon_status, http_json, rpc_call


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "status",
        help="show daemon status and active agent count",
    )
    parser.set_defaults(handler=handler)


def _agent_count(config) -> int | None:
    """Return active agent count when available, otherwise ``None``."""
    result = rpc_call(config, "agents.list")
    if result is not None:
        return len(result)

    result = http_json(config, "GET", "/api/agents")
    if isinstance(result, list):
        return len(result)
    return None


def get_status_data(config=None) -> dict:
    """Build a status dictionary for the daemon."""
    if config is None:
        from trimum_core.config import Config

        config = Config()

    daemon = get_daemon_status(config)
    data = {
        "running": daemon["running"],
        "source": daemon["source"],
        "version": (daemon.get("health") or {}).get("version"),
        "agents": None,
    }

    if daemon["running"]:
        data["agents"] = _agent_count(config)
    return data


def handler(args: argparse.Namespace) -> int:
    """Print daemon status."""
    data = get_status_data()

    def human(d: dict) -> None:
        if d["running"]:
            source = d["source"] or "unknown"
            print(f"[OK] daemon running (source={source})")
            if d.get("version"):
                print(f"version: {d['version']}")
            if d.get("agents") is not None:
                print(f"active agents: {d['agents']}")
        else:
            print("[OFFLINE] daemon is not running")

    emit(args, data, human)
    return 0


__all__ = ["add_subparsers", "handler", "get_status_data"]
