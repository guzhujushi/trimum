"""`trm health` command — local checks that do not require a daemon."""

from __future__ import annotations

import argparse
import importlib
import platform
import sys
from pathlib import Path

from .._utils import check_env_keys, emit


_CORE_MODULES = (
    "trimum_core.models",
    "trimum_core.config",
    "trimum_core.event_bus",
    "trimum_core.policy_engine",
    "trimum_core.tool_gateway",
    "trimum_core.agent_loop",
    "trimum_core.ipc_handler",
    "trimum_core.context_manager",
    "trimum_core.workflow_engine",
)

_ENV_KEYS = (
    "DEEPSEEK_API_KEY",
    "JIAOWOISAN_API_KEY",
    "GROQ_API_KEY",
    "KIMI_2.7_code_API_KEY",
    "API_KEY",
)


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "health",
        help="run a local health check without starting the daemon",
    )
    parser.set_defaults(handler=handler)


def _check_imports() -> dict:
    modules: list[dict] = []
    failures: list[str] = []
    for name in _CORE_MODULES:
        try:
            importlib.import_module(name)
            modules.append({"name": name, "status": "ok"})
        except Exception as exc:  # pragma: no cover - depends on environment
            modules.append({"name": name, "status": "fail", "error": str(exc)})
            failures.append(name)
    return {"modules": modules, "ok": not failures, "failures": failures}


def _check_config() -> dict:
    from trimum_core.config import Config

    config = Config()
    configured = config.config_path
    windows_fallback = Path.home() / ".trimum" / "config.yaml"
    exists = configured.exists() or windows_fallback.exists()
    return {
        "path": str(configured),
        "exists": exists,
        "status": "ok" if exists else "warn",
    }


def handler(args: argparse.Namespace) -> int:
    """Run local health checks and print a human or JSON report."""
    python_version = platform.python_version()
    python_ok = sys.version_info >= (3, 12)
    imports = _check_imports()
    config = _check_config()
    api_keys = check_env_keys(_ENV_KEYS)
    missing_keys = [item["name"] for item in api_keys if not item["present"]]

    ok = python_ok and imports["ok"]
    data = {
        "status": "ok" if ok else "fail",
        "version": {
            "python": python_version,
            "required": ">=3.12",
            "status": "ok" if python_ok else "fail",
        },
        "config": config,
        "imports": imports,
        "api_keys": api_keys,
        "missing_api_keys": missing_keys,
    }

    def human(_: dict) -> None:
        print(f"[{'OK' if python_ok else 'FAIL'}] Python {python_version} (requires >=3.12)")
        print(f"[{config['status'].upper()}] config: {config['path']}")
        for item in imports["modules"]:
            marker = "OK" if item["status"] == "ok" else "FAIL"
            error = f" - {item.get('error', '')}" if item.get("error") else ""
            print(f"[{marker}] {item['name']}{error}")
        for item in api_keys:
            marker = "OK" if item["present"] else "MISSING"
            print(f"[{marker}] env {item['name']}")
        print(f"[{'OK' if ok else 'FAIL'}] trimum health")

    emit(args, data, human)
    return 0 if ok else 1


__all__ = ["add_subparsers", "handler"]