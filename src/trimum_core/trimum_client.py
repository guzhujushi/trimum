#!/usr/bin/env python3
"""trimum-client — CLI for calling trimum Core over Unix Socket JSON-RPC.

Usage:
    trimum-client health
    trimum-client execute --args ls -la
    trimum-client agents.list
    trimum-client events.history --limit 10
    trimum-client --tcp 18321 health

Environment:
    TRIMUM_SOCKET   Unix socket path (default: $XDG_RUNTIME_DIR/trimum.sock,
                    else /run/trimum/trimum.sock —— 系统级 trmd.service 的
                    RuntimeDirectory=trimum 建的（S1 加固后的默认位置）,
                    else /run/user/<uid>/trimum.sock, else ~/.local/share/...)
    TRIMUM_TCP      TCP port for fallback (default: none)
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any


#: 系统级 daemon 的 socket 位置（trmd.service 的 RuntimeDirectory=trimum）。
SYSTEM_RUNTIME_SOCKET = Path("/run/trimum/trimum.sock")

#: 显式指定 socket 路径的环境变量（与 daemon 侧 `config.SOCKET_ENV` 同名，
#: 单元里 `Environment=TRIMUM_SOCKET=...` 一处生效、两端都认）。
SOCKET_ENV = "TRIMUM_SOCKET"


def socket_candidates() -> list[Path]:
    """按优先级列出候选 socket 路径（与 daemon 侧口径逐条对齐）。

    顺序：`TRIMUM_SOCKET` → `XDG_RUNTIME_DIR` → `/run/trimum`（系统 daemon）
    → `/run/user/<uid>`（登录会话）→ 数据目录。daemon 那边是
    `trimum_core.config.socket_candidates()`，两边必须一致 ——
    不一致就是 daemon 绑 A、客户端连 B、然后静默降级成 HTTP。
    """
    candidates: list[Path] = []

    env = os.environ.get(SOCKET_ENV)
    if env:
        candidates.append(Path(env))

    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        candidates.append(Path(xdg) / "trimum.sock")

    # 系统级 daemon（trmd.service）的单元里有 RuntimeDirectory=trimum，
    # socket 落在 /run/trimum/trimum.sock；客户端的 XDG_RUNTIME_DIR 是登录
    # 会话的 /run/user/<uid>，两者不同名。
    candidates.append(SYSTEM_RUNTIME_SOCKET)

    if hasattr(os, "getuid"):
        candidates.append(Path("/run") / "user" / str(os.getuid()) / "trimum.sock")

    data_home = os.environ.get("XDG_DATA_HOME") or str(
        Path.home() / ".local" / "share"
    )
    candidates.append(Path(data_home) / "trimum" / "trimum.sock")
    return candidates


def _is_live(path: Path) -> bool:
    """连得上才算有服务（socket 文件存在 ≠ 有进程在 listen）。

    SIGKILL 会留下无人监听的 stale 文件；只按 exists() 挑会选中它，客户端连不上
    就降级成 HTTP。Windows 无 AF_UNIX，恒 False。
    """
    if os.name == "nt":
        return False

    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.5)
        probe.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def discover_socket() -> str:
    """Find the trimum socket path from env or default locations."""
    env = os.environ.get(SOCKET_ENV)
    if env:
        return env

    candidates = socket_candidates()
    # 先挑**真能连上**的那条，再退回「文件存在」的那条：真机上就是被 stale
    # 文件坑了 —— 客户端以为在走 RPC，其实连的是死 socket，然后静默走 HTTP。
    for candidate in candidates:
        if _is_live(candidate):
            return str(candidate)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    # 都不存在时返回优先级最高的候选，报错信息才指得准；原先会退到
    # 数据目录，与 daemon 实际绑定的 `$XDG_RUNTIME_DIR/trimum.sock` 对不上。
    return str(candidates[0])


class RpcClient:
    """JSON-RPC 2.0 client over Unix Socket."""

    def __init__(self, socket_path: str | None = None, tcp_port: int | None = None, timeout: float = 10.0):
        self.socket_path = socket_path
        self.tcp_port = tcp_port
        self.timeout = timeout
        self._req_id = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send JSON-RPC request, return result."""
        self._req_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params or {},
        }
        payload = json.dumps(request, ensure_ascii=False) + "\n"

        sock = self._connect()
        try:
            sock.settimeout(self.timeout)
            sock.sendall(payload.encode("utf-8"))

            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk

            line = buf.split(b"\n", 1)[0]
            if not line:
                return None

            response = json.loads(line)
            if "error" in response:
                err = response["error"]
                print(f"RPC error [{err.get('code')}]: {err.get('message')}", file=sys.stderr)
                sys.exit(1)
            return response.get("result")
        finally:
            sock.close()

    def _connect(self) -> socket.socket:
        if self.tcp_port:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("127.0.0.1", self.tcp_port))
            return sock
        if self.socket_path:
            if os.name == "nt":
                print("Unix Socket not supported on Windows; use --tcp", file=sys.stderr)
                sys.exit(1)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.socket_path)
            return sock
        raise RuntimeError("No socket path or TCP port provided")


def main() -> None:
    from .env_file import ensure_loaded

    ensure_loaded()

    parser = argparse.ArgumentParser(description="trimum JSON-RPC client")
    parser.add_argument("method", help="RPC method name (e.g. health, execute, agents.list)")
    parser.add_argument("--socket", "-s", default=None, help="Unix socket path")
    parser.add_argument("--tcp", "-t", type=int, default=None, help="TCP port fallback")
    parser.add_argument("--args", nargs=argparse.REMAINDER, default=None, help="Positional args for execute method")
    parser.add_argument("--data", "-d", default=None, help="JSON params string")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty-print JSON output")

    args = parser.parse_args()
    socket_path = args.socket or discover_socket()

    # Build params
    params: dict[str, Any] = {}
    if args.data:
        params = json.loads(args.data)
    if args.args:
        params["args"] = args.args
    if args.method == "execute" and "args" not in params:
        print("Error: execute method requires --args", file=sys.stderr)
        sys.exit(1)

    client = RpcClient(socket_path=socket_path, tcp_port=args.tcp)
    result = client.call(args.method, params)

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent, default=str))


if __name__ == "__main__":
    main()
