"""`trm doctor` command — environment diagnostics."""

from __future__ import annotations

import argparse
import importlib.util
import platform
import shutil
import sys
from pathlib import Path

from .._utils import emit


_PACKAGES = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "yaml",
    "aiosqlite",
    "structlog",
    "psutil",
    "httpx",
    "json5",
)


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("doctor", help="check environment and dependencies")
    parser.set_defaults(handler=handler)


def _check_python() -> dict:
    ok = sys.version_info >= (3, 12)
    return {
        "version": platform.python_version(),
        "required": ">=3.12",
        "status": "ok" if ok else "fail",
    }


def _check_packages() -> dict:
    packages: list[dict] = []
    ok = True
    for name in _PACKAGES:
        found = importlib.util.find_spec(name) is not None
        packages.append({"name": name, "status": "ok" if found else "fail"})
        ok = ok and found
    return {"status": "ok" if ok else "fail", "packages": packages}


def _check_directories() -> dict:
    base = Path.home() / ".trimum"
    expected = ["agents", "tools", "memory", "logs", "config.yaml"]
    entries: list[dict] = []
    ok = True
    for name in expected:
        path = base / name
        exists = path.exists()
        entries.append({"name": name, "path": str(path), "exists": exists})
        ok = ok and exists
    return {"base": str(base), "status": "ok" if ok else "warn", "entries": entries}


def _check_disk() -> dict:
    try:
        usage = shutil.disk_usage(str(Path.home()))
        free_gb = usage.free / (1024**3)
        return {
            "status": "ok" if free_gb >= 1 else "warn",
            "free_gb": round(free_gb, 2),
            "total_gb": round(usage.total / (1024**3), 2),
        }
    except OSError as exc:
        return {"status": "warn", "error": str(exc)}


def _check_network() -> dict:
    try:
        import httpx

        from trimum_core.security_config import SecurityConfig

        security = SecurityConfig()
        security.load()
        base_url = security.get_llm_config().get(
            "base_url", "https://api.deepseek.com/v1"
        )
        response = httpx.get(base_url.rstrip("/") + "/models", timeout=3.0)
        return {
            "status": "ok" if response.status_code < 500 else "warn",
            "url": base_url,
            "http_status": response.status_code,
        }
    except Exception as exc:
        return {"status": "warn", "error": str(exc)}


def handler(args: argparse.Namespace) -> int:
    """Run environment diagnostics and print a report."""
    python = _check_python()
    packages = _check_packages()
    directories = _check_directories()
    disk = _check_disk()
    network = _check_network()

    critical_ok = python["status"] == "ok" and packages["status"] == "ok"
    data = {
        "status": "ok" if critical_ok else "fail",
        "python": python,
        "packages": packages,
        "directories": directories,
        "disk": disk,
        "network": network,
    }

    def human(d: dict) -> None:
        print(f"[{d['python']['status'].upper()}] Python {d['python']['version']} (requires 3.12+)")
        for item in d["packages"]["packages"]:
            print(f"[{item['status'].upper()}] package {item['name']}")
        print(f"[{d['directories']['status'].upper()}] ~/.trimum directory structure")
        print(f"[{d['disk']['status'].upper()}] disk free {d['disk'].get('free_gb', '?')} GB")
        print(f"[{d['network']['status'].upper()}] LLM API connectivity: {d['network'].get('url', d['network'].get('error', ''))}")
        print(f"[{d['status'].upper()}] trimum doctor")

    emit(args, data, human)
    return 0 if critical_ok else 1


__all__ = ["add_subparsers", "handler"]
