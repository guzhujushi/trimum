"""trimum Core — main entry point.

Usage:
    trmd                  # Run with default config
    trmd --config /path/to/config.yaml
"""

from __future__ import annotations

import argparse
import sys

from .config import Config
from .policy_engine import PolicyEngine



def run() -> None:
    """CLI entry point for trimum Core daemon."""
    import asyncio
    parser = argparse.ArgumentParser(
        description="trimum Core Daemon - system-level AI agent runtime",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to config YAML file",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Override host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override port (default: 8321)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )

    args = parser.parse_args()

    if args.version:
        from . import __version__
        print(f"trimum-core v{__version__}")
        sys.exit(0)

    from .config import Config
    from .api_server import run_core
    from .event_bus import EventBus
    from .sec_monitor import SecMonitor, ThreatMatcher, OpContextClassifier
    from .sec_executor import SecExecutor, SecAudit, SecNotif

    config = Config()
    if args.config:
        from pathlib import Path
        config = Config(Path(args.config))
    if args.host:
        config._raw["core"]["host"] = args.host
    if args.port:
        config._raw["core"]["port"] = args.port

    # 初始化安全组件
    async def _init_security(event_bus, tool_gateway):
        sec_audit = SecAudit()
        sec_notif = SecNotif(event_bus)
        sec_executor = SecExecutor(event_bus, sec_audit, sec_notif)
        threat_matcher = ThreatMatcher()
        op_context = OpContextClassifier()
        sec_monitor = SecMonitor(event_bus, threat_matcher, op_context, sec_executor)
        await sec_monitor.start()
        # 挂载到 ToolGateway
        tool_gateway.sec_monitor = sec_monitor
        tool_gateway.sec_executor = sec_executor
        tool_gateway.op_context = op_context
        return sec_monitor

    run_core(config)




def health() -> None:
    """trm health — quick system health check.

    Verifies:
    - Config file loads
    - All core modules import
    - Policy engine initializes with default rules
    - Agent registry directory exists
    Returns exit code 0 if all pass, 1 on failures.
    """
    from pathlib import Path
    import os
    import json

    config = Config()
    results = {
        "config": {"status": "ok", "path": str(config.config_path) if hasattr(config, 'config_path') else "default"},
        "imports": {"status": "ok", "modules": []},
    }

    failures = []

    # 检查模块导入
    core_modules = [
        "trimum_core.models",
        "trimum_core.event_bus",
        "trimum_core.tool_gateway",
        "trimum_core.policy_engine",
        "trimum_core.security_rule",
        "trimum_core.behavior_monitor",
        "trimum_core.system_monitor",
        "trimum_core.context_manager",
        "trimum_core.agent_manager",
        "trimum_core.agent_registry",
        "trimum_core.agent_runtime",
        "trimum_core.agent_socket",
        "trimum_core.workflow_engine",
        "trimum_core.skill_loader",
        "trimum_core.skill_router",
        "trimum_core.skill_executor",
        "trimum_core.experience_learner",
        "trimum_core.tarl_parser",
        "trimum_core.transform_agent",
        "trimum_core.planner_agent",
        "trimum_core.tool_file_loader",
        "trimum_core.tool_dispatchers",
        "trimum_core.ipc_handler",
        "trimum_core.memory_bridge",
    ]

    # 引入 sec_monitor/sec_executor（在非 Windows 平台可能不可用）
    try:
        from trimum_core import sec_monitor, sec_executor
        core_modules.append("trimum_core.sec_monitor")
        core_modules.append("trimum_core.sec_executor")
    except ImportError:
        pass

    for mod_name in core_modules:
        try:
            __import__(mod_name)
            results["imports"]["modules"].append(f"{mod_name}: ok")
        except Exception as e:
            failures.append(f"{mod_name}: {e}")
            results["imports"]["modules"].append(f"{mod_name}: FAIL ({e})")

    # 检查 policy 加载
    try:
        policy = PolicyEngine(Path(config.policy_path))
        risk, action, reason = policy.evaluate("ls -la")
        results["policy"] = {"status": "ok", "evaluate_test": f"ls -> {risk.value}/{action.value}"}
    except Exception as e:
        results["policy"] = {"status": "fail", "error": str(e)}
        failures.append(f"policy: {e}")

    # 检查 Agent Registry 目录
    agent_dir = os.path.expanduser("~/.trimum/agents")
    if os.path.isdir(agent_dir):
        results["agents"] = {"status": "ok", "path": agent_dir, "count": len(os.listdir(agent_dir))}
    else:
        results["agents"] = {"status": "warn", "path": agent_dir, "msg": "directory does not exist yet"}

    # 检查 ~/.trimum/tools
    tools_dir = os.path.expanduser("~/.trimum/tools")
    results["tools"] = {}
    if os.path.isdir(tools_dir):
        results["tools"] = {"status": "ok", "path": tools_dir}
    else:
        results["tools"] = {"status": "warn", "path": tools_dir, "msg": "directory does not exist yet"}

    print(json.dumps(results, indent=2, ensure_ascii=False))
    if failures:
        print(f"\n[!] {len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("\n[OK] trimum health: all checks passed")
        sys.exit(0)


def cli_dispatch() -> None:
    """CLI dispatch entry point (``trm`` command).

    Usage::

        trm              -> runs daemon (same as ``trmd``)
        trm health       -> quick health check

    This is registered as the ``trm`` console_scripts entry in ``pyproject.toml``.
    """
    if len(sys.argv) > 1:
        sub = sys.argv[1]
        if sub == "health":
            health()
            return
    # Default: run daemon
    run()

if __name__ == "__main__":
    cli_dispatch()
