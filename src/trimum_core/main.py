"""trimum Core — main entry point.

Usage:
    trmd                  # Run with default config (host 127.0.0.1:8321)
    trmd --config /etc/trimum/config.yaml
    trmd --host 0.0.0.0 --port 8321
    trmd --version        # Show version and exit
"""

from __future__ import annotations

import argparse
import sys


def run() -> None:
    """CLI entry point for trimum Core daemon."""
    parser = argparse.ArgumentParser(
        description="trimum Core Daemon - system-level AI agent runtime",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to config YAML file",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Override host (default from config: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override port (default from config: 8321)",
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
    from .api_server import create_app
    from .event_bus import EventBus
    from .sec_monitor import SecMonitor, ThreatMatcher, OpContextClassifier
    from .sec_executor import SecExecutor, SecAudit, SecNotif
    from .tool_gateway import ToolGateway
    from .logger import setup_logging, get_logger
    from pathlib import Path
    import asyncio
    import uvicorn

    config = Config()
    if args.config:
        config = Config(Path(args.config))
    if args.host:
        config._raw["core"]["host"] = args.host
    if args.port:
        config._raw["core"]["port"] = args.port

    # ── 初始化安全组件 ─────────────────────────────────────────
    async def init_security(tool_gateway: ToolGateway, event_bus: EventBus) -> SecMonitor:
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

    # ── 启动 ───────────────────────────────────────────────────
    # 先初始化安全组件（同步包装）
    import asyncio

    async def _init():
        setup_logging(config)
        logger = get_logger("main")
        app = create_app(config)
        state = app.state.trimum
        logger.info("initializing_security_components")
        sec_monitor = await init_security(state.tool_gateway, state.event_bus)
        state.sec_monitor = sec_monitor
        logger.info("security_components_ready", monitor=type(sec_monitor).__name__)
        logger.info("starting_http_server", host=config.host, port=config.port)
        return app, config

    app, config = asyncio.run(_init())

    # 使用 uvicorn.run() 替代手动 Server.serve()
    # uvicorn 0.52.4 中 Server.startup() 在手动调用 config.load()
    # 之前不创建 lifespan 属性；server.serve() 也可能因 create_server
    # 卡住。uvicorn.run() 是官方推荐入口，自带完整生命周期管理。
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        reload=False,
    )



if __name__ == "__main__":
    run()
