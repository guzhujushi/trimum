"""MCP client — stdio transport, JSON-RPC 2.0 over newline-delimited messages.

Scope (``docs/MCP-INTEGRATION-PLAN.md`` M1): spawn one MCP server process, do the
``initialize`` handshake, then expose ``tools/list`` and ``tools/call``.  Whether a
call is *allowed* is not decided here — that stays in ToolGateway; this module only
speaks the protocol.

Four deliberate choices:

* **no new dependency**: MCP's stdio framing is one JSON object per line (the same
  convention LSP uses), which ``asyncio`` streams read directly.  No Node, no SDK.
* **stderr goes to a log file**, never a pipe: a chatty server must not deadlock on
  a full 64 KB pipe, and a short-lived process must not raise ``Event loop is
  closed`` while flushing — the convention ``agent_launcher.py`` already uses.
* **stdio only for now**: ``transport: http`` (streamable HTTP + SSE) is M4 and
  fails loudly instead of pretending to work.
* **one request in flight per client**: requests are serialized, so a server that
  answers in order cannot be desynchronised by concurrent callers.

The server definition itself (``~/.trimum/mcp/<name>.json5``) lives in
``mcp_registry.py``; this module only needs an object with ``name``, ``transport``,
``command``, ``args``, ``env``, ``cwd`` and ``timeout`` attributes.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .logger import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a circular import
    from .mcp_registry import MCPServerDefinition

logger = get_logger("mcp_client")

#: Protocol revision trimum speaks.  A server may answer with an older revision;
#: that is accepted and recorded (``MCPClient.protocol_version``).
PROTOCOL_VERSION = "2024-11-05"

CLIENT_NAME = "trimum"
DEFAULT_TIMEOUT = 30.0

#: Guard against a server that never sends a newline.
MAX_MESSAGE_BYTES = 4 * 1024 * 1024

#: Notifications kept for diagnostics (``MCPClient.notifications``).
MAX_PENDING_NOTIFICATIONS = 20


class MCPError(Exception):
    """Base class for MCP failures (``TRM-4007`` in the trimum error table)."""

    code = "TRM-4007"


class MCPTimeout(MCPError):
    """The server did not answer within the deadline."""


class MCPProtocolError(MCPError):
    """The server sent something that is not valid JSON-RPC 2.0."""


class MCPRemoteError(MCPError):
    """The server answered with a JSON-RPC ``error`` object."""

    def __init__(self, message: str, *, code: int | str | None = None, data: Any = None) -> None:
        super().__init__(message)
        self.remote_code = code
        self.data = data


class MCPDisconnected(MCPError):
    """The server never started, exited, or was closed (``TRM-4008``)."""

    code = "TRM-4008"


@dataclass
class MCPTool:
    """One entry of a ``tools/list`` reply."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> "MCPTool":
        schema = payload.get("inputSchema", payload.get("input_schema"))
        return cls(
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            input_schema=schema if isinstance(schema, dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class MCPCallResult:
    """Normalised ``tools/call`` reply."""

    server: str
    tool: str
    is_error: bool = False
    text: str = ""
    content: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "tool": self.tool,
            "is_error": self.is_error,
            "text": self.text,
            "content": self.content,
            "duration_ms": self.duration_ms,
        }


def flatten_content(content: Any) -> str:
    """Turn an MCP ``content`` array into plain text for agents and logs.

    Text parts are joined with newlines; anything else is kept as compact JSON so
    that non-text parts (images, resources) stay visible instead of vanishing.
    """
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            if item.get("type") == "text" or "text" in item:
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(json.dumps(item, ensure_ascii=False, default=str))
        elif item is not None:
            parts.append(str(item))
    return "\n".join(part for part in parts if part)


def _client_version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:  # pragma: no cover - packaging edge case
        return "0.0.0"


class MCPClient:
    """One stdio MCP server connection.

    Lifecycle::

        client = MCPClient(definition)
        await client.connect()          # start + initialize
        tools = await client.list_tools()
        result = await client.call_tool("echo", {"text": "hi"})
        await client.close()

    A protocol failure (timeout, invalid JSON, unexpected EOF) marks the client
    ``broken``; the pool owning it throws it away and starts a fresh process on
    the next call, because a desynchronised stream cannot be reused safely.
    """

    def __init__(
        self,
        definition: "MCPServerDefinition",
        *,
        log_dir: str | Path | None = None,
        timeout: float | None = None,
    ) -> None:
        self.definition = definition
        self.name = str(getattr(definition, "name", "") or "")
        self.timeout = float(timeout or getattr(definition, "timeout", 0.0) or DEFAULT_TIMEOUT)
        self._log_dir = Path(log_dir) if log_dir is not None else None
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_handle: Any = None
        self._stderr_path: Path | None = None
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()
        self._seen: list[dict[str, Any]] = []
        self._server_info: dict[str, Any] = {}
        self._capabilities: dict[str, Any] = {}
        self._protocol_version = ""
        self._initialized = False
        self._broken = ""

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def alive(self) -> bool:
        """True while the process runs and the stream is still trustworthy."""
        return (
            self._proc is not None
            and self._proc.returncode is None
            and not self._broken
        )

    @property
    def broken(self) -> str:
        """Why this connection must be discarded (empty when healthy)."""
        return self._broken

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def server_info(self) -> dict[str, Any]:
        return dict(self._server_info)

    @property
    def capabilities(self) -> dict[str, Any]:
        return dict(self._capabilities)

    @property
    def protocol_version(self) -> str:
        return self._protocol_version

    @property
    def notifications(self) -> list[dict[str, Any]]:
        """Server-initiated messages seen while waiting for a reply."""
        return list(self._seen)

    @property
    def stderr_log(self) -> Path | None:
        """Where the server's stderr is being captured, if anywhere."""
        return self._stderr_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": self.name,
            "transport": getattr(self.definition, "transport", ""),
            "alive": self.alive,
            "initialized": self._initialized,
            "pid": self.pid,
            "protocol_version": self._protocol_version,
            "server_info": self._server_info,
            "broken": self._broken,
            "timeout": self.timeout,
            "stderr_log": str(self._stderr_path) if self._stderr_path else "",
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> dict[str, Any]:
        """Start the server (if needed) and run the ``initialize`` handshake."""
        await self.start()
        return await self.initialize()

    async def start(self) -> None:
        """Spawn the server process.  No-op when it already runs."""
        if self.alive:
            return

        transport = str(getattr(self.definition, "transport", "stdio") or "stdio")
        if transport != "stdio":
            raise MCPProtocolError(
                f"MCP transport '{transport}' is not implemented yet "
                "(stdio only; HTTP/SSE is M4)"
            )

        command = str(getattr(self.definition, "command", "") or "")
        if not command:
            raise MCPProtocolError(f"MCP server '{self.name}' defines no command")
        if shutil.which(command) is None and not Path(command).exists():
            raise MCPDisconnected(f"MCP server command not found: {command}")

        argv = [command, *[str(arg) for arg in (getattr(self.definition, "args", None) or [])]]
        env = os.environ.copy()
        for key, value in (getattr(self.definition, "env", None) or {}).items():
            env[str(key)] = str(value)
        cwd = str(getattr(self.definition, "cwd", "") or "") or None

        stderr = self._open_stderr()
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
                env=env,
                cwd=cwd,
            )
        except OSError as exc:
            self._close_stderr()
            raise MCPDisconnected(f"MCP server '{self.name}' failed to start: {exc}") from exc

        self._broken = ""
        self._initialized = False
        logger.info(
            "mcp.started",
            server=self.name,
            command=command,
            pid=self._proc.pid,
        )

    async def initialize(self) -> dict[str, Any]:
        """Perform the MCP handshake and the ``initialized`` notification."""
        if not self.alive:
            await self.start()

        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": CLIENT_NAME, "version": _client_version()},
            },
        )
        self._server_info = dict(result.get("serverInfo") or {})
        self._capabilities = dict(result.get("capabilities") or {})
        self._protocol_version = str(result.get("protocolVersion") or "")
        self._initialized = True

        if self._protocol_version and self._protocol_version != PROTOCOL_VERSION:
            logger.warning(
                "mcp.protocol_version_mismatch",
                server=self.name,
                server_version=self._protocol_version,
                client_version=PROTOCOL_VERSION,
            )

        await self._notify("notifications/initialized", {})
        return result

    async def close(self) -> None:
        """Terminate the server process and release the log file."""
        proc = self._proc
        self._proc = None
        self._initialized = False

        if proc is not None:
            try:
                if proc.stdin is not None and not proc.stdin.is_closing():
                    proc.stdin.close()
            except (OSError, RuntimeError):
                pass
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except (asyncio.TimeoutError, ProcessLookupError):
                        pass
        self._close_stderr()

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Protocol calls
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[MCPTool]:
        """Return the server's tool list (``tools/list``)."""
        result = await self._request("tools/list", {})
        raw = result.get("tools")
        if not isinstance(raw, list):
            return []
        tools: list[MCPTool] = []
        for item in raw:
            if isinstance(item, dict) and item.get("name"):
                tools.append(MCPTool.from_wire(item))
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> MCPCallResult:
        """Invoke one tool (``tools/call``)."""
        started = time.monotonic()
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=timeout,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        content = result.get("content")
        return MCPCallResult(
            server=self.name,
            tool=name,
            is_error=bool(result.get("isError")),
            text=flatten_content(content),
            content=content if isinstance(content, list) else [],
            duration_ms=duration_ms,
        )

    async def ping(self) -> dict[str, Any]:
        """Round-trip a ``ping``; used by ``trm mcp status``."""
        return await self._request("ping", {})

    # ------------------------------------------------------------------
    # Wire helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a request and wait for the reply with the matching id."""
        async with self._lock:
            if not self.alive:
                raise MCPDisconnected(
                    f"MCP server '{self.name}' is not running"
                    + (f" ({self._broken})" if self._broken else "")
                )

            request_id = next(self._ids)
            await self._send(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
            )

            deadline = self.timeout if timeout is None else float(timeout)
            while True:
                reply = await self._read_message(deadline)
                if reply.get("id") != request_id:
                    self._remember(reply)
                    continue
                if "error" in reply:
                    error = reply.get("error")
                    if isinstance(error, dict):
                        raise MCPRemoteError(
                            f"MCP '{method}' failed: {error.get('message') or error}",
                            code=error.get("code"),
                            data=error.get("data"),
                        )
                    raise MCPRemoteError(f"MCP '{method}' failed: {error}")
                result = reply.get("result")
                return result if isinstance(result, dict) else {"value": result}

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a notification (no reply expected)."""
        if not self.alive:
            return
        try:
            await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})
        except MCPError as exc:  # a dead server during shutdown is not fatal
            logger.debug("mcp.notify_failed", server=self.name, method=method, error=str(exc))

    async def _send(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise MCPDisconnected(f"MCP server '{self.name}' is not running")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            proc.stdin.write(payload.encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            self._mark_broken("stdin closed")
            raise MCPDisconnected(f"MCP server '{self.name}' closed its stdin") from exc

    async def _read_message(self, timeout: float) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise MCPDisconnected(f"MCP server '{self.name}' is not running")

        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError as exc:
                self._mark_broken(f"no reply within {timeout:g}s")
                raise MCPTimeout(
                    f"MCP server '{self.name}' did not answer within {timeout:g}s"
                ) from exc

            if not line:
                self._mark_broken("server closed the connection")
                raise MCPDisconnected(
                    f"MCP server '{self.name}' closed the connection "
                    f"(exit code {proc.returncode})"
                )
            if len(line) > MAX_MESSAGE_BYTES:
                self._mark_broken("oversized message")
                raise MCPProtocolError(
                    f"MCP server '{self.name}' sent a message larger than "
                    f"{MAX_MESSAGE_BYTES} bytes"
                )

            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except ValueError as exc:
                self._mark_broken("invalid JSON")
                raise MCPProtocolError(
                    f"MCP server '{self.name}' sent invalid JSON: {text[:200]}"
                ) from exc
            if not isinstance(message, dict):
                self._mark_broken("non-object message")
                raise MCPProtocolError(
                    f"MCP server '{self.name}' sent a non-object message"
                )

            if message.get("method") and "id" in message:
                # Server -> client request.  trimum advertises no such capability,
                # so answer politely (and keep the stream in sync) instead of hanging.
                await self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {
                            "code": -32601,
                            "message": f"client does not implement {message.get('method')}",
                        },
                    }
                )
                continue

            return message

    def _remember(self, message: dict[str, Any]) -> None:
        """Keep a bounded record of out-of-band messages (notifications)."""
        self._seen.append(message)
        if len(self._seen) > MAX_PENDING_NOTIFICATIONS:
            del self._seen[: len(self._seen) - MAX_PENDING_NOTIFICATIONS]
        logger.debug(
            "mcp.out_of_band_message",
            server=self.name,
            method=message.get("method", ""),
        )

    def _mark_broken(self, reason: str) -> None:
        if not self._broken:
            self._broken = reason
            logger.warning("mcp.connection_broken", server=self.name, reason=reason)

    # ------------------------------------------------------------------
    # stderr capture
    # ------------------------------------------------------------------

    def _open_stderr(self) -> Any:
        """Open ``<log_dir>/mcp-<name>.log`` for the server's stderr."""
        if self._log_dir is None:
            return asyncio.subprocess.DEVNULL
        path = self._log_dir / f"mcp-{self.name or 'unnamed'}.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._stderr_handle = path.open("ab")
            self._stderr_path = path
            return self._stderr_handle
        except OSError as exc:  # never block a call because logging failed
            logger.debug("mcp.stderr_log_unavailable", server=self.name, error=str(exc))
            self._stderr_handle = None
            self._stderr_path = None
            return asyncio.subprocess.DEVNULL

    def _close_stderr(self) -> None:
        handle, self._stderr_handle = self._stderr_handle, None
        if handle is None:
            return
        try:
            handle.close()
        except OSError:  # pragma: no cover - closing a broken handle
            pass


__all__ = [
    "PROTOCOL_VERSION",
    "CLIENT_NAME",
    "DEFAULT_TIMEOUT",
    "MAX_MESSAGE_BYTES",
    "MCPError",
    "MCPTimeout",
    "MCPProtocolError",
    "MCPRemoteError",
    "MCPDisconnected",
    "MCPTool",
    "MCPCallResult",
    "MCPClient",
    "flatten_content",
]