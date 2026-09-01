"""Agent Socket — Unix Socket communication layer for Agent Runtime.

Agent ↔ Runtime 通信层，使用 Unix Socket（JSON-RPC 风格）。
只处理 Agent 的 start/stop 信号，不参与业务逻辑。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
from typing import Any, Callable, Coroutine, Optional

log = logging.getLogger("trimum_core.agent_socket")

# ── 协议常量 ──────────────────────────────────────────────

MSG_START = "start"
MSG_STOP = "stop"
MSG_STATUS = "status"
MSG_HEARTBEAT = "heartbeat"

FRAME_HEADER = struct.Struct("!I")  # 4-byte length prefix


# ── 消息 ──────────────────────────────────────────────────


class SocketMessage:
    """A JSON-RPC style message over Unix Socket."""

    def __init__(
        self,
        msg_type: str,
        agent_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.type = msg_type
        self.agent_id = agent_id
        self.payload = payload or {}

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "agent_id": self.agent_id,
            "payload": self.payload,
        })

    @classmethod
    def from_json(cls, data: str) -> "SocketMessage":
        obj = json.loads(data)
        return cls(
            msg_type=obj["type"],
            agent_id=obj.get("agent_id", ""),
            payload=obj.get("payload", {}),
        )


# ── Server ────────────────────────────────────────────────


class AgentSocketServer:
    """Unix Socket server for Agent Runtime ↔ Sub-Agent communication.

    Listens on a Unix socket path, accepts connections from sub-agent
    processes, and dispatches incoming messages to registered handlers.
    """

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._server: Optional[asyncio.AbstractServer] = None
        self._handlers: dict[str, Callable[[SocketMessage], Coroutine]] = {}

    def register_handler(
        self,
        msg_type: str,
        handler: Callable[[SocketMessage], Coroutine],
    ) -> None:
        """Register a handler for *msg_type* messages."""
        self._handlers[msg_type] = handler

    async def start(self) -> None:
        """Start listening on the Unix socket."""
        # Remove stale socket file if it exists
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

        async def handle_client(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            """Handle a single client connection."""
            try:
                while True:
                    # Read length-prefixed frame
                    header = await reader.readexactly(FRAME_HEADER.size)
                    length = FRAME_HEADER.unpack(header)[0]
                    data = await reader.readexactly(length)
                    message = SocketMessage.from_json(data.decode("utf-8"))

                    handler = self._handlers.get(message.type)
                    if handler:
                        await handler(message)
                    else:
                        log.warning("No handler for message type: %s", message.type)
            except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        self._server = await asyncio.start_unix_server(
            handle_client,
            path=self._socket_path,
        )
        log.info("AgentSocketServer started on %s", self._socket_path)

    async def stop(self) -> None:
        """Stop the server and clean up."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
        log.info("AgentSocketServer stopped")


# ── Client ────────────────────────────────────────────────


class AgentSocketClient:
    """Unix Socket client for sub-agent processes.

    Connects to the Agent Runtime's socket server to receive
    start/stop signals and send status updates.
    """

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self) -> None:
        """Connect to the Agent Runtime socket server."""
        self._reader, self._writer = await asyncio.open_unix_connection(
            self._socket_path,
        )
        log.info("AgentSocketClient connected to %s", self._socket_path)

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._reader = None
            self._writer = None

    async def send_message(self, message: SocketMessage) -> None:
        """Send a framed message to the server."""
        if not self._writer:
            raise RuntimeError("Not connected")
        data = message.to_json().encode("utf-8")
        header = FRAME_HEADER.pack(len(data))
        self._writer.write(header + data)
        await self._writer.drain()

    async def send_status(self, agent_id: str, status: str) -> None:
        """Send a status update."""
        await self.send_message(SocketMessage(
            msg_type=MSG_STATUS,
            agent_id=agent_id,
            payload={"status": status},
        ))

    async def receive_signal(self) -> SocketMessage | None:
        """Receive a single signal from the server (start/stop)."""
        try:
            header = await self._reader.readexactly(FRAME_HEADER.size)
            length = FRAME_HEADER.unpack(header)[0]
            data = await self._reader.readexactly(length)
            return SocketMessage.from_json(data.decode("utf-8"))
        except (asyncio.IncompleteReadError, ConnectionResetError):
            return None
