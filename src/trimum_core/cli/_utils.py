"""Shared helpers for the `trm` command-line interface.

The helpers in this module intentionally avoid importing any heavy trimum
modules at import time.  Command handlers are responsible for lazily
importing project internals, so building the parser stays cheap and testable.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import pprint
import sys
from pathlib import Path
from typing import Any, Callable


def get_version() -> str:
    """Return the installed trimum version.

    Prefer the in-tree ``trimum_core.__version__`` so source checkouts and
    installed distributions stay consistent with the package module.
    """

    try:
        from trimum_core import __version__

        return __version__
    except Exception:
        return importlib.metadata.version("trimum-core")


def wants_json(args: argparse.Namespace) -> bool:
    """Return whether the parsed command requested JSON output."""
    return bool(getattr(args, "json", False))


def print_json(data: Any) -> None:
    """Write *data* to stdout as pretty JSON."""
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def emit(
    args: argparse.Namespace,
    data: Any,
    human_printer: Callable[[Any], None] | None = None,
) -> None:
    """Emit a command result as JSON or via the optional human printer."""
    if wants_json(args):
        print_json(data)
    elif human_printer is not None:
        human_printer(data)
    else:
        if isinstance(data, str):
            print(data)
        elif data is not None:
            pprint.pprint(data, sort_dicts=False, width=120)


def fail(message: str, code: int = 1) -> int:
    """Print an error message to stderr and return the exit code."""
    print(f"[!] {message}", file=sys.stderr)
    return code


def run_async(coro: Any) -> Any:
    """Run a coroutine synchronously in a fresh event loop."""
    return asyncio.run(coro)


def parse_duration(value: str | None) -> float:
    """Parse a compact duration string such as ``1h``, ``30m``, ``90s``."""
    if not value:
        return 0.0

    value = value.strip().lower()
    units = {
        "s": 1.0,
        "m": 60.0,
        "h": 60.0 * 60.0,
        "d": 24.0 * 60.0 * 60.0,
        "w": 7.0 * 24.0 * 60.0 * 60.0,
    }
    if value[-1] in units:
        number = value[:-1]
        unit = value[-1]
    else:
        number = value
        unit = "s"

    try:
        return float(number) * units[unit]
    except ValueError:
        return 0.0


def rpc_call(
    config: Any,
    method: str,
    params: dict[str, Any] | None = None,
    timeout: float = 2.0,
) -> Any | None:
    """Call a JSON-RPC method on the daemon socket, returning ``None`` offline."""
    try:
        from trimum_core.ipc_handler import RpcClient

        client = RpcClient(config.socket_path, timeout=timeout)
        return client.call(method, params)
    except Exception:
        return None


def http_json(
    config: Any,
    method: str,
    path: str,
    *,
    json_data: dict[str, Any] | None = None,
    timeout: float = 2.0,
) -> Any | None:
    """Call the daemon HTTP API, returning ``None`` when it is unavailable."""
    try:
        import httpx

        host = config.host
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        url = f"http://{host}:{config.port}{path}"
        response = httpx.request(method, url, json=json_data, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def get_daemon_status(config: Any) -> dict[str, Any]:
    """Return daemon status without raising when the daemon is offline.

    Checks the JSON-RPC socket first, then falls back to the FastAPI HTTP
    health endpoint.  The returned dictionary always contains ``running``.
    """

    health = rpc_call(config, "health", timeout=1.5)
    if health:
        return {"running": True, "source": "rpc", "health": health}

    health = http_json(config, "GET", "/health", timeout=1.5)
    if health is not None:
        return {"running": True, "source": "http", "health": health}

    return {"running": False, "source": None, "health": None}


def read_pid_file(config: Any) -> int | None:
    """Return a daemon PID from a conventional pid file, if available."""
    candidates = [
        Path.home() / ".trimum" / "trimum.pid",
        Path.home() / ".trimum" / "trmd.pid",
        Path("/run/trimum/trimum.pid"),
        Path("/tmp/trimum.pid"),
    ]

    configured = getattr(config, "get", lambda *_: None)("daemon.pid_path")
    if configured:
        candidates.insert(0, Path(str(configured)))

    for candidate in candidates:
        try:
            if candidate.is_file():
                return int(candidate.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
    return None
