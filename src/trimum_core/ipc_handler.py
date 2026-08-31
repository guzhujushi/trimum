"""IPC handler — JSON-RPC 2.0 over Unix Socket (and TCP fallback).

Defines a lightweight JSON-RPC 2.0 server that accepts connections on
the trimum Core Unix socket and proxies requests to the existing
FastAPI handlers (ToolGateway, AgentManager, EventBus, etc.).

Protocol:
    - Newline-delimited JSON (one request/response per line)
    - Request:  {"jsonrpc":"2.0","id":<int>,"method":"<name>","params":{...}}
    - Response: {"jsonrpc":"2.0","id":<int>,"result":{...}}
    - Error:    {"jsonrpc":"2.0","id":<int>,"error":{"code":<int>,"message":"..."}}
    - Notifications: {"jsonrpc":"2.0","method":"<name>","params":{...}}  (no id, no response)

Supported methods:
    - execute             ->  ToolGateway.execute()
    - execute.check       ->  policy check only
    - agents.list         ->  AgentManager.list()
    - agents.get          ->  AgentManager.get()
    - agents.spawn        ->  AgentManager.spawn()
    - agents.stop         ->  AgentManager.stop()
    - events.history      ->  EventBus.get_history()
    - context.get         ->  ContextManager.list_namespace()
    - context.set         ->  ContextManager.set()
    - health              ->  health check
"""

from __future__ import annotations

import asyncio
import json
import os
import socket as stdlib_socket
from typing import Any, Callable, Coroutine

from pydantic import BaseModel

from .logger import get_logger
from .models import (
    ExecuteRequest,
    ExecuteResponse,
    SpawnRequest,
    SpawnResponse,
    SystemEvent,
    ContextEntry,
)

logger = get_logger("ipc_handler")

# ── JSON-RPC Error Codes ────────────────────────────────────────

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
METHOD_TIMEOUT = -32001


# ── RPC request/response helpers ────────────────────────────────

def make_response(id: int | None, result: Any = None, error: dict | None = None) -> str:
    """Build a JSON-RPC 2.0 response string."""
    resp: dict[str, Any] = {"jsonrpc": "2.0"}
    if id is not None:
        resp["id"] = id
    if error:
        resp["error"] = error
    else:
        resp["result"] = result
    return json.dumps(resp, ensure_ascii=False, default=str) + "\n"


def make_error(id: int | None, code: int, message: str) -> str:
    return make_response(id, error={"code": code, "message": message})


# ── RPC Router ──────────────────────────────────────────────────

Handler = Callable[..., Coroutine[Any, Any, Any]]


class RpcRouter:
    """Simple method-name -> handler dict with validation."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    def get(self, method: str) -> Handler | None:
        return self._handlers.get(method)


# ── IPC Handler ─────────────────────────────────────────────────

class IpcHandler:
    """JSON-RPC 2.0 server over Unix Socket.

    Usage:
        handler = IpcHandler(socket_path="/run/user/1000/trimum.sock")
        handler.router.register("health", lambda: {"status": "ok"})
        asyncio.create_task(handler.start())
    """

    def __init__(
        self,
        socket_path: str,
        *,
        max_conn: int = 5,
        request_timeout: float = 30.0,
        tcp_fallback_port: int | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.max_conn = max_conn
        self.request_timeout = request_timeout
        self.tcp_fallback_port = tcp_fallback_port

        self.router = RpcRouter()
        self._server: stdlib_socket.socket | None = None
        self._tcp_server: stdlib_socket.socket | None = None

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Start the Unix Socket server (and optional TCP fallback)."""
        await self._start_unix_socket()
        if self.tcp_fallback_port:
            await self._start_tcp_fallback()

    async def _start_unix_socket(self) -> None:
        if os.name == "nt":
            logger.info("unix_socket_skipped_windows")
            return

        path = self.socket_path
        if os.path.exists(path):
            os.unlink(path)

        try:
            sock = stdlib_socket.socket(
                stdlib_socket.AF_UNIX, stdlib_socket.SOCK_STREAM
            )
            sock.bind(path)
            sock.listen(self.max_conn)
            os.chmod(path, 0o700)
            self._server = sock
            logger.info("unix_socket_listening", path=path)
        except Exception as e:
            logger.warning("unix_socket_start_failed", error=str(e))
            return

        loop = asyncio.get_event_loop()

        async def accept_loop() -> None:
            while True:
                try:
                    conn, addr = await loop.sock_accept(self._server)
                    asyncio.create_task(self._handle_connection(conn, addr))
                except (OSError, AttributeError):
                    break

        asyncio.create_task(accept_loop())

    async def _start_tcp_fallback(self) -> None:
        port = self.tcp_fallback_port
        try:
            sock = stdlib_socket.socket(
                stdlib_socket.AF_INET, stdlib_socket.SOCK_STREAM
            )
            sock.setsockopt(stdlib_socket.SOL_SOCKET, stdlib_socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(self.max_conn)
            self._tcp_server = sock
            logger.info("tcp_ipc_listening", port=port)
        except Exception as e:
            logger.warning("tcp_ipc_start_failed", error=str(e))
            return

        loop = asyncio.get_event_loop()

        async def accept_loop() -> None:
            while True:
                try:
                    conn, addr = await loop.sock_accept(self._tcp_server)
                    asyncio.create_task(
                        self._handle_connection(conn, f"tcp:{addr}")
                    )
                except (OSError, AttributeError):
                    break

        asyncio.create_task(accept_loop())

    async def stop(self) -> None:
        """Stop the IPC server and clean up socket file."""
        if self._server:
            self._server.close()
            self._server = None
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        if self._tcp_server:
            self._tcp_server.close()
            self._tcp_server = None
        logger.info("ipc_handler_stopped")

    # ── Connection handling ────────────────────────────────────

    async def _handle_connection(
        self, conn: stdlib_socket.socket, addr: Any
    ) -> None:
        """Read NDJSON lines, dispatch, write responses."""
        reader = None
        writer = None
        try:
            conn.settimeout(self.request_timeout)
            loop = asyncio.get_event_loop()

            buf = b""
            while True:
                try:
                    chunk = await loop.sock_recv(conn, 4096)
                except (OSError, TimeoutError):
                    break
                if not chunk:
                    break
                buf += chunk

                # Process complete lines
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    response = await self._dispatch_line(line)
                    if response:
                        try:
                            await loop.sock_sendall(conn, response.encode("utf-8"))
                        except OSError:
                            break
        except Exception as e:
            logger.debug("ipc_connection_error", error=str(e))
        finally:
            try:
                conn.close()
            except OSError:
                pass

    async def _dispatch_line(self, line: bytes) -> str | None:
        """Parse and dispatch a single JSON-RPC request line."""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return make_error(None, PARSE_ERROR, "Parse error: invalid JSON")

        # Validate structure
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return make_error(
                msg.get("id"), INVALID_REQUEST, "Invalid Request: must be JSON-RPC 2.0"
            )

        method = msg.get("method", "")
        params = msg.get("params", {})
        req_id = msg.get("id")  # None for notifications

        if not method or not isinstance(method, str):
            return make_error(req_id, INVALID_REQUEST, "Method name required")

        # Notifications have no id, no response expected
        is_notification = req_id is None

        # Route
        handler = self.router.get(method)
        if handler is None:
            err = make_error(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")
            return err if not is_notification else None

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(params)
            else:
                result = handler(params)
        except TypeError as e:
            err = make_error(req_id, INVALID_PARAMS, f"Invalid params: {e}")
            return err if not is_notification else None
        except Exception as e:
            logger.exception("rpc_handler_error", method=method)
            err = make_error(req_id, INTERNAL_ERROR, str(e))
            return err if not is_notification else None

        return make_response(req_id, result) if not is_notification else None


# ── JSON-RPC Client (for trimum-client CLI) ─────────────────────

class RpcClient:
    """Synchronous JSON-RPC client for Unix Socket.

    Used by trimum-client CLI and external scripts.
    """

    def __init__(self, socket_path: str, timeout: float = 10.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC request and wait for response."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        payload = json.dumps(request, ensure_ascii=False) + "\n"

        sock = stdlib_socket.socket(stdlib_socket.AF_UNIX, stdlib_socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.socket_path)
            sock.sendall(payload.encode("utf-8"))

            # Read response
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
                raise RpcError(
                    response["error"].get("code", -1),
                    response["error"].get("message", "Unknown error"),
                )
            return response.get("result")
        finally:
            sock.close()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (fire-and-forget)."""
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        payload = json.dumps(request, ensure_ascii=False) + "\n"

        sock = stdlib_socket.socket(stdlib_socket.AF_UNIX, stdlib_socket.SOCK_STREAM)
        sock.settimeout(2.0)
        try:
            sock.connect(self.socket_path)
            sock.sendall(payload.encode("utf-8"))
        finally:
            sock.close()


class RpcError(Exception):
    """JSON-RPC error response."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
