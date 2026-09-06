"""trimum Core — main entry point.

Usage:
    trmd                  # Run with default config
    trmd --config /path/to/config.yaml
"""

from __future__ import annotations

import argparse
import sys


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


if __name__ == "__main__":
    run()
