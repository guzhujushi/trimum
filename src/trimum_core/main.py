"""trimum Core — main entry point.

Usage:
    trmd                  # Run with default config (host 127.0.0.1:8321)
    trmd --config /etc/trimum/config.yaml
    trmd --host 0.0.0.0 --port 8321
    trmd --version        # Show version and exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import sys
import threading

# 启动预检失败（端口 / socket 被占）的退出码，与 systemd 的 exit 3 对齐
EXIT_STARTUP_PRECONDITION = 3

#: 启动初始化阶段的看门狗超时（秒）。env > 配置 core.startup_timeout_seconds > 默认。
STARTUP_TIMEOUT_ENV = "TRIMUM_STARTUP_TIMEOUT_SECONDS"
DEFAULT_STARTUP_TIMEOUT = 60.0


def check_tcp_port(host: str, port: int) -> str | None:
    """预检 TCP 端口能否绑定：可用返回 None，被占返回错误描述。

    原先不预检，端口被占只能等 uvicorn 抛 `[Errno 98] address already in
    use`；在 systemd（`Restart=always`）下就变成每 5s 一次的崩溃循环。
    """
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host

    # 第一步 connect：真有服务在 listen 就直接报占（跨平台都准）
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        conn.settimeout(1.0)
        conn.connect((probe_host, port))
        return "已有服务在监听"
    except OSError:
        pass
    finally:
        conn.close()

    # 第二步 bind：抓「绑了但没 listen」等边角
    binder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name != "nt":
            # Linux 上 SO_REUSEADDR 只放过 TIME_WAIT 残留，不放过在 listen 的
            # socket；Windows 上它反而允许抢占端口，会让探测失灵，故不加。
            binder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        binder.bind((host, port))
        return None
    except OSError as exc:
        return exc.strerror or str(exc)
    finally:
        binder.close()


def abort_startup(reason: str, hint: str, *, hard: bool = False) -> None:
    """启动预检失败：打印清晰提示后退出，不再让 uvicorn 抛底层 errno。

    `hard=True` 留给**启动中途**才判定致命的情形（HTTP 关掉时 IPC socket 起不来）：
    那时 `ContextManager` 的 aiosqlite 连接线程已经是活的，而它是**非 daemon** 线程 ——
    `SystemExit` 只会让解释器停在 `threading._shutdown()` 里等它，进程反而不退。
    真机实测：`timeout 90` 之后靠 SIGKILL 收场，退出码 124 而不是 3；
    faulthandler 线程栈见 docs/SANDBOX-PLAN.md §9.3.8。这条路上一件东西都在服务之外，
    直接 `os._exit` 才是最诚实的行为。
    """
    print(f"trmd: 启动中止 —— {reason}", file=sys.stderr)
    print(f"      建议：{hint}", file=sys.stderr)

    if hard:
        try:
            logging.shutdown()
        except Exception:  # pragma: no cover - 收尾失败也要退
            pass
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(EXIT_STARTUP_PRECONDITION)

    sys.exit(EXIT_STARTUP_PRECONDITION)


def _startup_timeout(config) -> float:
    """看门狗超时：env > 配置 `core.startup_timeout_seconds` > 60。缺失/坏值/<=0 静默走默认。"""
    raw = os.environ.get(STARTUP_TIMEOUT_ENV)
    if raw is None or not str(raw).strip():
        raw = config.get("core.startup_timeout_seconds", None)
    if raw is None:
        return DEFAULT_STARTUP_TIMEOUT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_STARTUP_TIMEOUT
    return value if value > 0 else DEFAULT_STARTUP_TIMEOUT


def _on_startup_timeout(timeout: float) -> None:
    """看门狗触发：初始化没在超时内完成 ⇒ 立刻硬退（§9.3.8：这条路上可能已有非 daemon 线程）。"""
    abort_startup(
        f"启动超时：{timeout:g}s 内安全组件没有初始化完成",
        "多半是 aiosqlite / 外部依赖吊住；看日志定位，或调大 "
        f"`{STARTUP_TIMEOUT_ENV}` / 配置 `core.startup_timeout_seconds`",
        hard=True,
    )


def _arm_startup_watchdog(config) -> threading.Timer:
    """启动看门狗：daemon Timer；正常起来后由 `_attach_watchdog_disarm` 拆掉。"""
    timer = threading.Timer(_startup_timeout(config), _on_startup_timeout,
                            args=(_startup_timeout(config),))
    timer.daemon = True
    timer.name = "trmd-startup-watchdog"
    timer.start()
    return timer


def _attach_watchdog_disarm(app, timer: threading.Timer) -> None:
    """把 `timer.cancel` 挂到 app 的 lifespan startup 上 —— 服务真起来才拆看门狗。

    挂不上（`router.on_startup` 不存在等）⇒ 立即手动 cancel（fail-soft：宁可少一层
    保护，也不能让看门狗在正常运行时把 daemon 打死）。
    """
    try:
        app.router.on_startup.append(timer.cancel)
    except Exception:  # noqa: BLE001
        timer.cancel()


async def _serve_without_http(app, config) -> None:
    """只提供 IPC socket 的 daemon（`core.http_enabled=false`）。

    uvicorn 必须有监听端口才肯起来，所以这条路上由我们自己驱 lifespan：
    `app.router.lifespan_context(app)` 正是 uvicorn 内部走的那一段（跑
    on_startup / on_shutdown handler），不是另起一套启动逻辑。
    """
    from .logger import get_logger

    logger = get_logger("main")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    handled = 0
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
            handled += 1
        except (NotImplementedError, AttributeError, ValueError):
            # Windows 没有 loop 级信号处理；该模式只在 Linux 上用
            break

    async with app.router.lifespan_context(app):
        logger.info(
            "trimum_core_started",
            mode="ipc-only",
            socket=config.socket_path,
        )
        if handled == 0:
            logger.warning("signal_handlers_unavailable", detail="只能靠 SIGKILL 停")
        await stop.wait()


def run() -> None:
    """CLI entry point for trimum Core daemon."""
    from .env_file import ensure_loaded

    # .env 先加载：systemd 单元没配 EnvironmentFile 时，daemon 就靠这里拿到 key 与模型路由
    ensure_loaded()

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

    from pathlib import Path

    from .config import Config
    from .ipc_handler import IpcUnavailableError, socket_is_live

    config = Config()
    if args.config:
        config = Config(Path(args.config))
    if args.host:
        config._raw["core"]["host"] = args.host
    if args.port:
        config._raw["core"]["port"] = args.port

    # ── 启动前预检：被占就立刻退出（碰 socket 之前） ──────────────
    # HTTP 面关掉时不查端口：查了也没用，还会因为「别的进程占着 8321」白拦一刀。
    if config.http_enabled:
        port_error = check_tcp_port(config.host, config.port)
        if port_error:
            abort_startup(
                f"TCP {config.host}:{config.port} 已被占用（{port_error}）",
                "已有 trmd 在跑？先 `trm status` 确认；要停旧实例用"
                " `pkill -f trimum_core.main`，或换端口 `trmd --port 8322`",
            )
    if socket_is_live(config.socket_path):
        abort_startup(
            f"IPC socket {config.socket_path} 已被其它进程监听",
            "本实例拒绝抢占（抢占会让运行中 daemon 的 RPC 通道断裂、"
            "客户端静默降级成 HTTP）；确认后停掉旧实例，或改 core.socket_path",
        )

    from .api_server import create_app
    from .event_bus import EventBus
    from .sec_monitor import SecMonitor
    from .sec_executor import SecurityRuntime
    from .tool_gateway import ToolGateway
    from .logger import setup_logging, get_logger
    import asyncio
    import uvicorn

    # ── 初始化安全组件 ─────────────────────────────────────────
    async def init_security(tool_gateway: ToolGateway, event_bus: EventBus) -> SecMonitor:
        # 装配只有一处定义（SecurityRuntime）：daemon 用全链路版（审计落盘 + 通知 +
        # 阻断 + 工作流触发），覆盖网关自带的 SecurityRuntime.local（不落盘）。
        runtime = SecurityRuntime.daemon(event_bus)
        await runtime.start()
        runtime.attach(tool_gateway)
        return runtime.monitor

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
        return app, logger

    watchdog = _arm_startup_watchdog(config)
    try:
        app, logger = asyncio.run(_init())
    except BaseException as exc:  # noqa: BLE001
        abort_startup(
            f"安全组件初始化失败（{type(exc).__name__}: {exc}）",
            "看日志定位后重启 `trmd`；这条路上可能有非 daemon 线程吊住解释器，故意硬退",
            hard=True,
        )
    _attach_watchdog_disarm(app, watchdog)

    if not config.http_enabled:
        logger.info("starting_ipc_only_daemon", socket=config.socket_path)
        try:
            asyncio.run(_serve_without_http(app, config))
        except IpcUnavailableError as exc:
            abort_startup(
                f"IPC socket 起不来（{exc}），而 core.http_enabled=false"
                " —— 这个 daemon 没有任何入口可服务",
                "检查 core.socket_path 的父目录是否存在且可写（系统单元用 "
                "/run/trimum/trimum.sock + RuntimeDirectory=trimum）；"
                "临时 `TRIMUM_HTTP=1 trmd` 可先把 HTTP 面打开",
                hard=True,
            )
        return

    logger.info("starting_http_server", host=config.host, port=config.port)

    # 使用 uvicorn.run() 替代手动 Server.serve()
    # uvicorn 0.52.4 中 Server.startup() 在手动调用 config.load()
    # 之前不创建 lifespan 属性；server.serve() 也可能因 create_server
    # 卡住。uvicorn.run() 是官方推荐入口，自带完整生命周期管理。
    try:
        uvicorn.run(
            app,
            host=config.host,
            port=config.port,
            log_level=config.log_level.lower(),
            reload=False,
        )
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        if code:
            abort_startup(
                f"HTTP 面启动失败（uvicorn 退出码 {code}）",
                "看日志定位；uvicorn 自己的 sys.exit 可能被非 daemon 线程吊住，这条路上硬退",
                hard=True,
            )
        raise
    except Exception as exc:  # noqa: BLE001
        abort_startup(
            f"HTTP 面异常退出（{type(exc).__name__}: {exc}）",
            "看日志定位后重启 `trmd`",
            hard=True,
        )



if __name__ == "__main__":
    run()
