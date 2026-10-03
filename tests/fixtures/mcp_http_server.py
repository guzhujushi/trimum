"""A tiny streamable-HTTP MCP server used by the test suite — real protocol, no network.

Loopback only (``127.0.0.1``) and stdlib only: the tests exercise real HTTP POSTs,
real ``text/event-stream`` framing, real session headers and real ``202``/``404``/``500``
replies instead of mocks.

Tools mirror ``mcp_echo_server.py`` (``echo`` / ``fail`` / ``slow`` / ``delete_everything``)
so both transports answer the same way, plus a few test-only ones:

* ``accepted``  answer ``202`` even though the request carried an id (protocol break)
* ``boom``      answer with HTTP ``500``
* ``hang``      sleep far past any client timeout

``State`` knobs let a test change the reply shape mid-run:
``state.reply_mode`` is ``json`` | ``sse`` | ``noisy-sse`` | ``empty-sse``;
``state.require_session`` (default on) enforces the ``Mcp-Session-Id`` handshake.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "echo",
        "description": "Return the text you send",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "fail",
        "description": "Always answers with isError",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "slow",
        "description": "Sleeps before answering",
        "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}},
    },
    {
        "name": "delete_everything",
        "description": "Dangerous name, used by the deny-pattern tests",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "accepted",
        "description": "Answers 202 without a reply (protocol break)",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "boom",
        "description": "Answers HTTP 500",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "hang",
        "description": "Never answers in time",
        "inputSchema": {"type": "object"},
    },
]


class State:
    """Behaviour knobs + request log shared with the test."""

    def __init__(self) -> None:
        self.reply_mode = "json"
        self.require_session = True
        self.sessions: dict[str, bool] = {}
        self.requests: list[dict[str, Any]] = []
        self.notifications: list[str] = []
        self.terminated: list[str] = []

    # -- helpers -------------------------------------------------------

    def new_session(self) -> str:
        session = uuid.uuid4().hex
        self.sessions[session] = True
        return session

    def saw(self, method: str) -> bool:
        return any(item["method"] == method for item in self.requests)

    def last(self, method: str) -> dict[str, Any] | None:
        for item in reversed(self.requests):
            if item["method"] == method:
                return item
        return None

    # -- protocol ------------------------------------------------------

    def handle(self, message: dict[str, Any]) -> tuple[int, bytes, str, dict[str, str]]:
        """Return ``(status, body, content_type, extra_headers)`` for one message."""
        method = message.get("method")
        params = message.get("params") or {}

        if method == "initialize":
            result: Any = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo-http", "version": "0.0.1"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "ping":
            result = {}
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name == "echo":
                result = {"content": [{"type": "text", "text": "echo: " + str(arguments.get("text", ""))}]}
            elif name == "fail":
                result = {"isError": True, "content": [{"type": "text", "text": "boom"}]}
            elif name == "slow":
                time.sleep(float(arguments.get("seconds", 0.5)))
                result = {"content": [{"type": "text", "text": "slept"}]}
            elif name == "hang":
                time.sleep(float(arguments.get("seconds", 5.0)))
                result = {"content": [{"type": "text", "text": "late"}]}
            elif name == "accepted":
                return 202, b"", "application/json", {}
            elif name == "boom":
                return 500, b"kaboom", "text/plain", {}
            elif name == "delete_everything":
                result = {"content": [{"type": "text", "text": "deleted"}]}
            else:
                return self._json(
                    {"jsonrpc": "2.0", "id": message.get("id"),
                     "error": {"code": -32602, "message": "unknown tool: %s" % name}}
                )
        else:
            return self._json(
                {"jsonrpc": "2.0", "id": message.get("id"),
                 "error": {"code": -32601, "message": "method not found: %s" % method}}
            )

        reply = {"jsonrpc": "2.0", "id": message.get("id"), "result": result}
        if self.reply_mode == "sse":
            return self._sse([reply])
        if self.reply_mode == "noisy-sse":
            return self._sse(
                [{"jsonrpc": "2.0", "method": "notifications/message",
                  "params": {"level": "info", "data": "warming up"}}, reply]
            )
        if self.reply_mode == "empty-sse":
            return self._sse(
                [{"jsonrpc": "2.0", "method": "notifications/message",
                  "params": {"level": "info", "data": "nothing follows"}}]
            )
        return self._json(reply)

    # -- encoders ------------------------------------------------------

    @staticmethod
    def _json(payload: dict[str, Any]) -> tuple[int, bytes, str, dict[str, str]]:
        return 200, json.dumps(payload).encode("utf-8"), "application/json", {}

    @staticmethod
    def _sse(messages: list[dict[str, Any]]) -> tuple[int, bytes, str, dict[str, str]]:
        body = "".join(
            "event: message\ndata: %s\n\n" % json.dumps(item) for item in messages
        )
        return 200, body.encode("utf-8"), "text/event-stream", {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: State
    server_version = "trimum-test-mcp"

    def log_message(self, *args: Any) -> None:  # keep pytest output clean
        return

    # -- plumbing ------------------------------------------------------

    def _respond(self, status: int, body: bytes, content_type: str, extra: dict[str, str]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_message(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return None

    # -- verbs ---------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        message = self._read_message()
        if message is None:
            self._respond(400, b"bad json", "text/plain", {})
            return

        method = str(message.get("method") or "")
        session = self.headers.get("Mcp-Session-Id") or ""
        self.state.requests.append(
            {
                "method": method,
                "session": session,
                "accept": self.headers.get("Accept", ""),
                "protocol": self.headers.get("MCP-Protocol-Version", ""),
                "authorization": self.headers.get("Authorization", ""),
                "content_type": self.headers.get("Content-Type", ""),
            }
        )

        if message.get("id") is None:  # notification
            self.state.notifications.append(method)
            self._respond(202, b"", "application/json", {})
            return

        extra: dict[str, str] = {}
        if method == "initialize":
            session = self.state.new_session()
            extra["Mcp-Session-Id"] = session
        elif self.state.require_session and session not in self.state.sessions:
            self._respond(404, b"unknown session", "text/plain", {})
            return

        status, body, content_type, headers = self.state.handle(message)
        headers.update(extra)
        self._respond(status, body, content_type, headers)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        # trimum never opens the server-initiated stream; a real server may answer 405.
        self._respond(405, b"no server-initiated stream", "text/plain", {})

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib naming
        session = self.headers.get("Mcp-Session-Id") or ""
        self.state.terminated.append(session)
        self.state.sessions.pop(session, None)
        self._respond(200, b"", "application/json", {})


class HttpMCPServer:
    """A loopback MCP server running in a background thread."""

    def __init__(self) -> None:
        self.state = State()

        class _Handler(Handler):
            state = self.state

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="mcp-http-fixture", daemon=True
        )

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/mcp"

    def start(self) -> "HttpMCPServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def start_server() -> HttpMCPServer:
    return HttpMCPServer().start()


if __name__ == "__main__":  # manual poking: python tests/fixtures/mcp_http_server.py
    server = start_server()
    print(server.url, flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()