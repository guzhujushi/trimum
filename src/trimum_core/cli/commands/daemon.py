"""`trm daemon` command group — start/stop/restart/status."""

from __future__ import annotations

import argparse
import sys

from .._utils import emit, fail, get_daemon_status, read_pid_file


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("daemon", help="control the trimum daemon")
    nested = parser.add_subparsers(dest="daemon_command", title="daemon commands")

    start_parser = nested.add_parser("start", help="start the daemon in the foreground")
    start_parser.add_argument("--config", type=str, default=None, help="path to config YAML")
    start_parser.set_defaults(handler=handler)

    stop_parser = nested.add_parser("stop", help="stop the daemon")
    stop_parser.set_defaults(handler=handler)

    restart_parser = nested.add_parser("restart", help="restart the daemon")
    restart_parser.add_argument("--config", type=str, default=None, help="path to config YAML")
    restart_parser.set_defaults(handler=handler)

    status_parser = nested.add_parser("status", help="show daemon status")
    status_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm daemon {start,stop,restart,status} ...")
    return 0


def _start_daemon(config_path: str | None) -> int:
    """Invoke the existing ``trimum_core.main.run`` with adjusted argv."""
    from trimum_core import main as main_module

    old_argv = sys.argv[:]
    try:
        argv = ["trmd"]
        if config_path:
            argv.extend(["--config", str(config_path)])
        sys.argv = argv
        main_module.run()
    finally:
        sys.argv = old_argv
    return 0


def _find_daemon_pid(config) -> int | None:
    """Find the daemon PID via pid files or the configured listening port."""
    pid = read_pid_file(config)
    if pid is not None:
        return pid

    try:
        import psutil

        for connection in psutil.net_connections(kind="inet"):
            if (
                connection.status == "LISTEN"
                and connection.laddr is not None
                and connection.laddr.port == int(config.port)
            ):
                return connection.pid
    except Exception:
        return None
    return None


def _stop_daemon() -> tuple[bool, int | None, str]:
    from trimum_core.config import Config

    config = Config()
    pid = _find_daemon_pid(config)
    if pid is None:
        return False, None, "daemon pid not found"

    try:
        import psutil

        process = psutil.Process(pid)
        process.terminate()
        process.wait(timeout=10)
        return True, pid, "daemon stopped"
    except psutil.NoSuchProcess:
        return True, pid, "daemon was not running"
    except Exception as exc:
        return False, pid, str(exc)


def _status_data() -> dict:
    from trimum_core.config import Config

    return get_daemon_status(Config())


def handler(args: argparse.Namespace) -> int:
    """Execute the requested daemon subcommand."""
    command = getattr(args, "daemon_command", None)

    if command == "start":
        return _start_daemon(getattr(args, "config", None))

    if command == "stop":
        ok, pid, message = _stop_daemon()
        data = {"stopped": ok, "pid": pid, "message": message}
        emit(args, data)
        return 0 if ok else 1

    if command == "restart":
        ok, pid, message = _stop_daemon()
        if not ok:
            return fail(f"could not stop daemon: {message}")
        return _start_daemon(getattr(args, "config", None))

    if command == "status":
        data = _status_data()
        emit(args, data)
        return 0

    return _show_help(args)


__all__ = ["add_subparsers", "handler"]
