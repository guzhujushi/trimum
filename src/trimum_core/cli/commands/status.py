"""`trm status` command — report daemon and runtime status."""

from __future__ import annotations

import argparse
import time

from .._utils import emit, get_daemon_status, http_json, read_pid_file, rpc_call


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


def _find_daemon_pid(config, health: dict | None = None) -> int | None:
    """Return the daemon PID from its own report, pid files, or the listen port.

    `health.pid` 排最前：后面那条 psutil 扫 `127.0.0.1:<port>` 监听者的路子在
    TCP 面关掉之后就没有对象可扫了（没人监听那个端口）。
    """
    reported = (health or {}).get("pid") if isinstance(health, dict) else None
    if reported:
        try:
            return int(reported)
        except (TypeError, ValueError):
            pass

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


def _process_info(pid: int | None) -> dict | None:
    """Return best-effort process information for a PID."""
    if pid is None:
        return None

    try:
        import psutil

        process = psutil.Process(pid)
        with process.oneshot():
            return {
                "pid": pid,
                "status": process.status(),
                "uptime_seconds": round(time.time() - process.create_time(), 1),
                "memory_mb": round(process.memory_info().rss / (1024 * 1024), 1),
                "cpu_percent": round(process.cpu_percent(interval=0.0), 1),
                "cmdline": process.cmdline(),
            }
    except Exception as exc:
        return {"pid": pid, "error": str(exc)}


def _system_snapshot() -> dict:
    """Collect a lightweight host resource snapshot."""
    try:
        import psutil

        memory = psutil.virtual_memory()
        return {
            "cpu_percent": round(psutil.cpu_percent(interval=0.0), 1),
            "memory_percent": round(memory.percent, 1),
            "memory_used_mb": round(memory.used / (1024 * 1024), 1),
            "memory_total_mb": round(memory.total / (1024 * 1024), 1),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _format_uptime(seconds: float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m {secs}s"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def get_status_data(config=None) -> dict:
    """Build a status dictionary for the daemon and host."""
    if config is None:
        from trimum_core.config import Config

        config = Config()

    daemon = get_daemon_status(config)
    health = daemon.get("health") or {}
    pid = _find_daemon_pid(config, health)
    process = _process_info(pid) if daemon["running"] or pid else None
    system = _system_snapshot()

    data = {
        "running": daemon["running"],
        "source": daemon["source"],
        "version": (daemon.get("health") or {}).get("version"),
        "host": config.host,
        "port": config.port,
        "socket": config.socket_path,
        # daemon 自报的两个事实：TCP 面还开不开、IPC socket 起没起来
        "http": health.get("http"),
        "ipc": health.get("ipc"),
        "pid": pid,
        "process": process,
        "system": system,
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
            print("[OK] daemon running")
            print(f"source: {d['source'] or 'unknown'}")
            if d.get("version"):
                print(f"version: {d['version']}")
            print(f"endpoint: {d['host']}:{d['port']} (socket={d['socket']})")
            if d.get("http") is not None:
                print(f"http: {'enabled' if d['http'] else 'disabled'}")
            if d.get("ipc") is not None:
                print(f"ipc socket: {'ok' if d['ipc'] else 'UNAVAILABLE'}")
            if d.get("pid"):
                print(f"pid: {d['pid']}")
            process = d.get("process") or {}
            if process.get("error"):
                print(f"process: {process['error']}")
            else:
                if process.get("uptime_seconds") is not None:
                    print(f"uptime: {_format_uptime(process['uptime_seconds'])}")
                if process.get("memory_mb") is not None:
                    print(f"memory: {process['memory_mb']} MB")
                if process.get("cpu_percent") is not None:
                    print(f"cpu: {process['cpu_percent']}%")
            if d.get("agents") is not None:
                print(f"active agents: {d['agents']}")
        else:
            print("[OFFLINE] daemon is not running")

        system = d.get("system") or {}
        if system.get("error"):
            print(f"[WARN] host resources unavailable: {system['error']}")
        else:
            print(
                f"[INFO] host cpu={system.get('cpu_percent', '?')}% "
                f"memory={system.get('memory_percent', '?')}%"
            )

    emit(args, data, human)
    return 0


__all__ = ["add_subparsers", "handler", "get_status_data"]