"""AgentRunner — standard entry point for Agent processes.

An Agent process uses it like::

    from trimum_core.agent_runner import AgentRunner

    def my_handler(input_data, event_bus, wf_id, node_id):
        return {"result": "ok"}

    if __name__ == "__main__":
        AgentRunner(handler=my_handler).run()

The runner reads its configuration from environment variables, optionally
waits for a ``go`` event, executes the handler, publishes the completion
event, and writes the result file.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .event_bus import EventBus
from .logger import get_logger
from .models import SystemEvent

__all__ = ["AgentRunner", "get_agent_config"]

log = get_logger("trimum_core.agent_runner")


@dataclass
class AgentConfig:
    """Configuration parsed from Agent environment variables."""

    wf_id: str
    node_id: str
    input_file: str
    result_file: str
    subscribe_topics: list[str]
    go_event: str = ""
    timeout: float = 120.0


def get_agent_config() -> AgentConfig:
    """Read Agent configuration from environment variables."""
    topics = [
        topic.strip()
        for topic in os.environ.get("TRIMUM_EVENTBUS_TOPICS", "").split(",")
        if topic.strip()
    ]
    try:
        timeout = float(os.environ.get("TRIMUM_AGENT_TIMEOUT", "120.0"))
    except ValueError:
        timeout = 120.0

    return AgentConfig(
        wf_id=os.environ.get("TRIMUM_WF_ID", ""),
        node_id=os.environ.get("TRIMUM_NODE_ID", ""),
        input_file=os.environ.get("TRIMUM_INPUT_FILE", ""),
        result_file=os.environ.get("TRIMUM_RESULT_FILE", ""),
        subscribe_topics=topics,
        go_event=os.environ.get("TRIMUM_GO_EVENT", ""),
        timeout=timeout,
    )


class AgentRunner:
    """Standard in-process entry point for an Agent."""

    def __init__(
        self,
        handler: Callable,
        bus: EventBus | None = None,
        config: AgentConfig | None = None,
    ) -> None:
        self._handler = handler
        self._bus = bus
        self._config = config or get_agent_config()

    def run(self) -> Any:
        """Synchronous entry point (used by Agent subprocesses)."""
        return asyncio.run(self.arun())

    async def arun(self) -> Any:
        """Asynchronous entry point."""
        bus = self._bus or EventBus()
        config = self._config
        wf_id = config.wf_id
        node_id = config.node_id

        input_data = self._load_input(config.input_file)

        if config.go_event:
            await self._wait_for_go(bus, config.go_event, config.timeout)

        status = "completed"
        result: Any = None
        error = ""
        try:
            result = self._handler(input_data, bus, wf_id, node_id)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error = str(exc)
            log.exception("agent_runner.handler_failed", wf_id=wf_id, node_id=node_id)

        output_data = result if isinstance(result, dict) else {}
        self._write_result(config.result_file, wf_id, node_id, status, result, error)

        await bus.publish(
            SystemEvent(
                event_type=f"node.{wf_id}.{node_id}.completed",
                source="agent",
                payload={
                    "wf_id": wf_id,
                    "node_id": node_id,
                    "status": status,
                    "result": result,
                    "output_data": output_data,
                    "error": error,
                },
            )
        )
        return result

    @staticmethod
    def _load_input(input_file: str) -> dict[str, Any]:
        """Load the Agent input payload from disk."""
        if not input_file or not Path(input_file).exists():
            return {}
        try:
            data = json.loads(Path(input_file).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"value": data}
        except Exception:  # noqa: BLE001
            log.exception("agent_runner.input_read_failed", input_file=input_file)
            return {}

    @staticmethod
    def _write_result(
        result_file: str,
        wf_id: str,
        node_id: str,
        status: str,
        result: Any,
        error: str,
    ) -> None:
        """Write the Agent result payload to disk."""
        if not result_file:
            return
        payload = {
            "wf_id": wf_id,
            "node_id": node_id,
            "status": status,
            "result": result,
            "error": error,
            "timestamp": time.time(),
        }
        path = Path(result_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")

    @staticmethod
    async def _wait_for_go(bus: EventBus, go_event: str, timeout: float) -> None:
        """Wait until the configured ``go`` event is published."""
        received = asyncio.Event()

        def on_event(_event: SystemEvent) -> None:
            received.set()

        bus.subscribe(go_event, on_event)
        try:
            await asyncio.wait_for(received.wait(), timeout=timeout)
        finally:
            bus.unsubscribe(go_event, on_event)