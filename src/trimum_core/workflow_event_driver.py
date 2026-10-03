"""Workflow Event Driver — bridge between Engine and AgentRuntime.

The driver owns the control channel that sits between the workflow engine
and agent processes:

- a TCP JSON-RPC 2.0 server accepts Engine commands (``start_agent``,
  ``cancel_agent``, ``cancel_workflow``, ``health``);
- a TCP client pushes notifications back to the Engine
  (``engine.node_completed``, ``engine.node_blocked``, ...);
- an in-process :class:`EventBus` is used to observe agent results and
  confirmation events and to fan out ``go`` signals.

The actual agent execution belongs to Agent processes; this driver only
launches/tracks them and keeps their EventBus subscriptions in order.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .agent_manager import AgentManager
from .event_bus import Callback, EventBus
from .logger import get_logger
from .models import (
    ConfirmRequest,
    SpawnRequest,
    SystemEvent,
    WorkflowDriverCommand,
)

log = get_logger("trimum_core.workflow_event_driver")

# JSON-RPC 2.0 error codes (mirrors ipc_handler.py).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _jsonrpc_response(req_id: Any | None, result: Any = None, error: dict[str, Any] | None = None) -> str:
    """Build a newline-terminated JSON-RPC 2.0 response string."""
    resp: dict[str, Any] = {"jsonrpc": "2.0"}
    if req_id is not None:
        resp["id"] = req_id
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    return json.dumps(resp, ensure_ascii=False, default=str) + "\n"


def _jsonrpc_error(req_id: Any | None, code: int, message: str) -> str:
    return _jsonrpc_response(req_id, error={"code": code, "message": message})


class SubManager:
    """Track per-node EventBus subscriptions on behalf of the driver."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._subscriptions: dict[tuple[str, str], list[tuple[str, Callback]]] = {}

    @staticmethod
    def _key(wf_id: str, node_id: str) -> tuple[str, str]:
        return (wf_id, node_id)

    def register(
        self,
        wf_id: str,
        node_id: str,
        topics: list[str],
        callback: Callback,
        replay_count: int = 5,
    ) -> None:
        """Register a node's subscriptions, replacing any previous ones."""
        self.unregister(wf_id, node_id)
        subs = self._subscriptions.setdefault(self._key(wf_id, node_id), [])
        for topic in topics:
            self._bus.subscribe_with_replay(topic, callback, replay_count)
            subs.append((topic, callback))

    def unregister(self, wf_id: str, node_id: str) -> None:
        """Remove every subscription registered for a node."""
        subs = self._subscriptions.pop(self._key(wf_id, node_id), [])
        for topic, callback in subs:
            self._bus.unsubscribe(topic, callback)

    def list_subscriptions(self, wf_id: str) -> list[dict[str, Any]]:
        """List active subscriptions for a workflow."""
        return [
            {
                "wf_id": wf,
                "node_id": node,
                "topics": [topic for topic, _ in subs],
            }
            for (wf, node), subs in self._subscriptions.items()
            if wf == wf_id
        ]


class ConfirmMgr:
    """Manage a queue of nodes waiting for user confirmation.

    Lifecycle:
      1. ``add`` creates a :class:`ConfirmRequest` and emits
         ``confirm.<wf_id>.<node_id>.required``.
      2. The frontend accepts/rejects through the EventBus
         (``confirm.<wf_id>.<node_id>.accepted`` / ``.rejected``).
      3. ``resolve`` updates the queue state and emits the matching event.
      4. ``_timeout_check`` automatically rejects expired requests.
    """

    def __init__(self, bus: EventBus, timeout: float = 300.0) -> None:
        self._bus = bus
        self._timeout = timeout
        self._pending: dict[str, ConfirmRequest] = {}

    def _emit(self, event: SystemEvent) -> None:
        """Fire an event without blocking the caller (best effort)."""
        try:
            asyncio.create_task(self._bus.publish(event))
        except RuntimeError:
            # No running event loop (e.g. called from a plain sync context).
            log.debug("confirm_mgr.emit_skipped", event_type=event.event_type)

    def add(self, req: ConfirmRequest) -> None:
        """Add a pending confirmation request and emit ``required``."""
        now = time.time()
        if req.created_at <= 0.0:
            req.created_at = now
        if req.expires_at <= 0.0:
            req.expires_at = now + self._timeout
        req.status = "pending"
        self._pending[req.confirm_id] = req
        self._emit(
            SystemEvent(
                event_type=f"confirm.{req.wf_id}.{req.node_id}.required",
                source="driver",
                payload=req.model_dump(),
            )
        )

    def resolve(self, confirm_id: str, accepted: bool) -> None:
        """Accept or reject a confirmation request."""
        req = self._pending.pop(confirm_id, None)
        if req is None:
            return
        req.status = "accepted" if accepted else "rejected"
        self._emit(
            SystemEvent(
                event_type=f"confirm.{req.wf_id}.{req.node_id}.{req.status}",
                source="driver",
                payload=req.model_dump(),
            )
        )

    def get_pending(self, wf_id: str | None = None) -> list[ConfirmRequest]:
        """Return pending confirmation requests, optionally filtered."""
        if wf_id is None:
            return list(self._pending.values())
        return [req for req in self._pending.values() if req.wf_id == wf_id]

    def _discard(self, confirm_id: str) -> None:
        """Remove a pending request without emitting an event."""
        self._pending.pop(confirm_id, None)

    async def _timeout_check(self) -> None:
        """Reject every request whose expiry time has passed."""
        now = time.time()
        expired = [
            confirm_id
            for confirm_id, req in self._pending.items()
            if req.expires_at > 0.0 and req.expires_at <= now
        ]
        for confirm_id in expired:
            req = self._pending.pop(confirm_id)
            req.status = "timeout"
            await self._bus.publish(
                SystemEvent(
                    event_type=f"confirm.{req.wf_id}.{req.node_id}.rejected",
                    source="driver",
                    payload=req.model_dump(),
                )
            )


class WorkflowEventDriver:
    """Bridge control channel between Engine and Agent processes."""

    def __init__(
        self,
        bus: EventBus,
        agent_manager: AgentManager,
        engine_host: str = "127.0.0.1",
        engine_port: int = 0,
        driver_host: str = "127.0.0.1",
        driver_port: int = 0,
        confirm_timeout: float = 300.0,
    ) -> None:
        self.bus = bus
        self.agent_manager = agent_manager
        self.engine_host = engine_host
        self.engine_port = engine_port
        self.driver_host = driver_host
        self.driver_port = driver_port
        self.confirm_timeout = confirm_timeout

        self.sub_manager = SubManager(bus)
        self.confirm_mgr = ConfirmMgr(bus, confirm_timeout)

        self._agents: dict[str, dict[str, str]] = {}  # wf_id -> node_id -> agent_id
        self._server: asyncio.AbstractServer | None = None
        self._client_reader: asyncio.StreamReader | None = None
        self._client_writer: asyncio.StreamWriter | None = None
        self._client_lock = asyncio.Lock()
        self._confirm_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._work_root = Path(tempfile.gettempdir()) / "trimum-workflow"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the driver socket server and connect to the Engine."""
        self._stopped = False
        self._server = await asyncio.start_server(
            self._handle_connection, self.driver_host, self.driver_port
        )
        if self.driver_port == 0 and self._server.sockets:
            self.driver_port = self._server.sockets[0].getsockname()[1]

        if self.engine_port:
            self._client_reader, self._client_writer = await asyncio.open_connection(
                self.engine_host, self.engine_port
            )

        self.bus.subscribe("*", self._on_agent_completed)
        self.bus.subscribe("*", self._on_confirm_accepted)
        self.bus.subscribe("*", self._on_confirm_rejected)

        self._confirm_task = asyncio.create_task(self._check_confirm_timeouts())
        log.info(
            "workflow_event_driver.started",
            driver_host=self.driver_host,
            driver_port=self.driver_port,
            engine_port=self.engine_port,
        )

    async def stop(self) -> None:
        """Stop all agents, cancel background work, and close connections."""
        self._stopped = True

        if self._confirm_task is not None:
            self._confirm_task.cancel()
            try:
                await self._confirm_task
            except asyncio.CancelledError:
                pass
            self._confirm_task = None

        for wf_id in list(self._agents):
            await self._handle_cancel_workflow(wf_id)

        self.bus.unsubscribe("*", self._on_agent_completed)
        self.bus.unsubscribe("*", self._on_confirm_accepted)
        self.bus.unsubscribe("*", self._on_confirm_rejected)

        if self._client_writer is not None:
            self._client_writer.close()
            try:
                await self._client_writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._client_writer = None
            self._client_reader = None

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        log.info("workflow_event_driver.stopped")

    # ------------------------------------------------------------------
    # Socket server
    # ------------------------------------------------------------------

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve newline-delimited JSON-RPC requests from the Engine."""
        try:
            while not self._stopped:
                line = await reader.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    writer.write(_jsonrpc_error(None, PARSE_ERROR, "Parse error").encode("utf-8"))
                    await writer.drain()
                    continue

                response = await self._handle_request(data)
                if response:
                    writer.write(response.encode("utf-8"))
                    await writer.drain()
        except Exception:  # noqa: BLE001
            log.exception("workflow_event_driver.connection_error")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def _handle_request(self, data: dict[str, Any]) -> str | None:
        """Parse and dispatch a single JSON-RPC request."""
        if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
            req_id = data.get("id") if isinstance(data, dict) else None
            return _jsonrpc_error(req_id, INVALID_REQUEST, "Invalid Request")

        method = data.get("method", "")
        params = data.get("params") or {}
        req_id = data.get("id")
        is_notification = req_id is None

        if not isinstance(method, str) or not method:
            return None if is_notification else _jsonrpc_error(req_id, INVALID_REQUEST, "Method name required")

        try:
            if method == "start_agent":
                cmd = WorkflowDriverCommand.model_validate(params)
                result = await self._handle_start_agent(cmd)
            elif method == "cancel_agent":
                wf_id = params.get("wf_id", "")
                node_id = params.get("node_id", "")
                result = await self._handle_cancel_agent(wf_id, node_id)
            elif method == "cancel_workflow":
                result = await self._handle_cancel_workflow(params.get("wf_id", ""))
            elif method == "health":
                result = await self._handle_health()
            else:
                return None if is_notification else _jsonrpc_error(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        except Exception as exc:  # noqa: BLE001
            log.exception("workflow_event_driver.handle_error", method=method)
            return None if is_notification else _jsonrpc_error(req_id, INTERNAL_ERROR, str(exc))

        if is_notification:
            return None
        return _jsonrpc_response(req_id, result)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _handle_start_agent(self, cmd: WorkflowDriverCommand) -> dict[str, Any]:
        """Launch an Agent, write its input, and register its subscriptions."""
        if not cmd.wf_id or not cmd.node_id:
            raise ValueError("wf_id and node_id are required")
        if not cmd.agent_type:
            raise ValueError("agent_type is required")

        node_map = self._agents.setdefault(cmd.wf_id, {})
        old_agent_id = node_map.get(cmd.node_id)
        if old_agent_id:
            await self.agent_manager.stop(old_agent_id)

        work_dir = self._work_root / cmd.wf_id / cmd.node_id
        work_dir.mkdir(parents=True, exist_ok=True)
        input_file = work_dir / "input.json"
        result_file = work_dir / "result.json"
        input_file.write_text(
            json.dumps(cmd.input_data, ensure_ascii=False), encoding="utf-8"
        )

        env = {
            "TRIMUM_WF_ID": cmd.wf_id,
            "TRIMUM_NODE_ID": cmd.node_id,
            "TRIMUM_INPUT_FILE": str(input_file),
            "TRIMUM_RESULT_FILE": str(result_file),
            "TRIMUM_EVENTBUS_TOPICS": ",".join(cmd.subscribe_topics),
            "TRIMUM_AGENT_TIMEOUT": str(cmd.timeout_seconds),
        }
        if cmd.confirm_required:
            env["TRIMUM_GO_EVENT"] = f"agent.{cmd.wf_id}.{cmd.node_id}.go"

        agent_id = f"{cmd.wf_id}__{cmd.node_id}"
        request = SpawnRequest(
            agent_type=cmd.agent_type,
            agent_id=agent_id,
            config={"env": env},
        )
        resp = await self.agent_manager.spawn(request)

        node_map[cmd.node_id] = resp.agent_id
        self.sub_manager.register(
            cmd.wf_id,
            cmd.node_id,
            cmd.subscribe_topics,
            self._make_node_callback(cmd.wf_id, cmd.node_id),
        )

        if cmd.confirm_required:
            now = time.time()
            confirm_id = f"confirm-{uuid.uuid4().hex[:12]}"
            req = ConfirmRequest(
                confirm_id=confirm_id,
                wf_id=cmd.wf_id,
                node_id=cmd.node_id,
                prompt=cmd.confirm_prompt
                or f"Confirm agent '{cmd.agent_type}' for node '{cmd.node_id}'?",
                created_at=now,
                expires_at=now + self.confirm_timeout,
            )
            self.confirm_mgr.add(req)
            await self.notify_engine(
                "engine.node_blocked",
                wf_id=cmd.wf_id,
                node_id=cmd.node_id,
                status="blocked",
                reason="confirm",
                confirm_id=confirm_id,
            )

        return {
            "agent_id": resp.agent_id,
            "status": resp.status.value,
            "message": resp.message,
        }

    async def _handle_cancel_agent(self, wf_id: str, node_id: str) -> bool:
        """Stop a specific Agent and remove its subscriptions."""
        node_map = self._agents.get(wf_id)
        agent_id = node_map.get(node_id) if node_map else None
        if agent_id is None:
            return False
        await self.agent_manager.stop(agent_id)
        self.sub_manager.unregister(wf_id, node_id)
        node_map.pop(node_id, None)
        return True

    async def _handle_cancel_workflow(self, wf_id: str) -> dict[str, Any]:
        """Stop every Agent belonging to a workflow."""
        node_map = self._agents.get(wf_id, {})
        stopped = 0
        for node_id, agent_id in list(node_map.items()):
            await self.agent_manager.stop(agent_id)
            self.sub_manager.unregister(wf_id, node_id)
            stopped += 1
        self._agents.pop(wf_id, None)
        return {"wf_id": wf_id, "stopped": stopped}

    async def _handle_health(self) -> dict[str, Any]:
        """Report driver health for Engine polling."""
        agents = await self.agent_manager.list()
        return {
            "status": "ok",
            "driver_port": self.driver_port,
            "agents": len(agents),
            "pending_confirms": len(self.confirm_mgr.get_pending()),
        }

    # ------------------------------------------------------------------
    # Event listeners
    # ------------------------------------------------------------------

    async def _on_agent_completed(self, event: SystemEvent) -> None:
        """Forward ``node.<wf>.<node>.completed`` back to the Engine."""
        if not self._matches("node.*.*.completed", event.event_type):
            return
        payload = event.payload
        wf_id = payload.get("wf_id") or self._segment(event.event_type, 1)
        node_id = payload.get("node_id") or self._segment(event.event_type, 2)
        await self.notify_engine(
            "engine.node_completed",
            wf_id=wf_id,
            node_id=node_id,
            status=payload.get("status", "completed"),
            result=payload.get("result"),
            output_data=payload.get("output_data") or {},
            error=payload.get("error", ""),
        )
        self.sub_manager.unregister(wf_id, node_id)
        node_map = self._agents.get(wf_id)
        if node_map:
            node_map.pop(node_id, None)

    async def _on_confirm_accepted(self, event: SystemEvent) -> None:
        """On confirmation accept, publish the node's ``go`` signal."""
        if not self._matches("confirm.*.*.accepted", event.event_type):
            return
        payload = event.payload
        confirm_id = payload.get("confirm_id", "")
        if confirm_id:
            self.confirm_mgr._discard(confirm_id)
        wf_id = payload.get("wf_id") or self._segment(event.event_type, 1)
        node_id = payload.get("node_id") or self._segment(event.event_type, 2)
        await self.bus.publish(
            SystemEvent(
                event_type=f"agent.{wf_id}.{node_id}.go",
                source="driver",
                payload={
                    "wf_id": wf_id,
                    "node_id": node_id,
                    "confirm_id": payload.get("confirm_id", ""),
                },
            )
        )
        await self.notify_engine(
            "engine.workflow_progress",
            wf_id=wf_id,
            node_id=node_id,
            pct=0.0,
            message="confirmation accepted",
        )

    async def _on_confirm_rejected(self, event: SystemEvent) -> None:
        """On confirmation reject, fail the node back to the Engine."""
        if not self._matches("confirm.*.*.rejected", event.event_type):
            return
        payload = event.payload
        confirm_id = payload.get("confirm_id", "")
        if confirm_id:
            self.confirm_mgr._discard(confirm_id)
        wf_id = payload.get("wf_id") or self._segment(event.event_type, 1)
        node_id = payload.get("node_id") or self._segment(event.event_type, 2)
        error = payload.get("error") or (
            "Confirmation timed out" if payload.get("status") == "timeout" else "Confirmation rejected"
        )
        await self.notify_engine(
            "engine.node_completed",
            wf_id=wf_id,
            node_id=node_id,
            status="failed",
            result=None,
            output_data={},
            error=error,
        )
        await self.bus.publish(
            SystemEvent(
                event_type=f"agent.{wf_id}.{node_id}.cancel",
                source="driver",
                payload={"wf_id": wf_id, "node_id": node_id},
            )
        )

    # ------------------------------------------------------------------
    # Engine callback client
    # ------------------------------------------------------------------

    async def notify_engine(self, method: str, **kwargs: Any) -> None:
        """Send a JSON-RPC notification to the Engine."""
        if self._client_writer is None:
            log.debug("workflow_event_driver.notify_skipped", method=method)
            return
        line = (
            json.dumps(
                {"jsonrpc": "2.0", "method": method, "params": kwargs},
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )
        async with self._client_lock:
            self._client_writer.write(line.encode("utf-8"))
            await self._client_writer.drain()

    async def _check_confirm_timeouts(self) -> None:
        """Periodically reject expired confirmation requests."""
        interval = min(max(self.confirm_timeout, 0.1), 10.0) if self.confirm_timeout > 0 else 10.0
        while not self._stopped:
            try:
                await asyncio.sleep(interval)
                await self.confirm_mgr._timeout_check()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("workflow_event_driver.confirm_timeout_error")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_node_callback(self, wf_id: str, node_id: str) -> Callback:
        """Build a callback that logs events observed for a node."""

        async def callback(event: SystemEvent) -> None:
            log.debug(
                "workflow_event_driver.node_event",
                wf_id=wf_id,
                node_id=node_id,
                event_type=event.event_type,
            )

        return callback

    @staticmethod
    def _matches(pattern: str, actual: str) -> bool:
        """Match a dot-separated wildcard pattern against an event type."""
        if pattern == "*":
            return True
        pattern_parts = pattern.split(".")
        actual_parts = actual.split(".")
        if len(pattern_parts) != len(actual_parts):
            return False
        return all(p == "*" or p == a for p, a in zip(pattern_parts, actual_parts))

    @staticmethod
    def _segment(event_type: str, index: int) -> str:
        """Return a dot-separated segment or an empty string."""
        parts = event_type.split(".")
        return parts[index] if 0 <= index < len(parts) else ""