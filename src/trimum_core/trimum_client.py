#!/usr/bin/env python3
"""trimum-client — CLI for calling trimum Core over Unix Socket JSON-RPC.

Usage:
    trimum-client health
    trimum-client execute --args ls -la
    trimum-client agents.list
    trimum-client events.history --limit 10
    trimum-client --tcp 18321 health

Environment:
    TRIMUM_SOCKET   Unix socket path (default: ~/.local/share/trimum/trimum.sock)
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


def discover_socket() -> str:
    """Find the trimum socket path from env or default locations."""
    env = os.environ.get("TRIMUM_SOCKET")
    if env:
        return env

    # Linux XDG
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        candidate = Path(xdg) / "trimum.sock"
        if candidate.exists():
            return str(candidate)

    # Default
    return str(Path.home() / ".local" / "share" / "trimum" / "trimum.sock")


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
