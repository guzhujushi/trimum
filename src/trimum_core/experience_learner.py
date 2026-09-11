"""Experience Learner — learn from failures and store structured advice.

Listens to ``event.*.failed`` events on the Event Bus, calls an LLM to
analyze the failure, and stores structured experience entries in the
offending Agentʼs private memory (``agent_memory/experience`` namespace).

Flow::

    EventBus publish ``event.agent.failed`` / ``event.tool.failed``
        → ExperienceLearner._on_failure()
            → Compose LLM prompt from event payload + recent history
            → Call OpenAI-compatible API
            → Parse structured experience from LLM response
            → Store via MemoryBridge (``memory.agent.set`` event)
            → Deduplicate by pattern before storing

Design principles:
    - **No token waste** — LLM only invoked on failure events.
    - **Best-effort** — failures in ExperienceLearner itself are logged
      and silently swallowed (never cascade back to the caller).
    - **Deduplication** — same ``pattern`` increments ``count`` instead
      of creating duplicate entries.
    - **Experience format** — structured JSON stored under
      ``agent_memory/experience.{fingerprint}`` keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

from .event_bus import EventBus
from .models import SystemEvent, EventSeverity

log = logging.getLogger("trimum_core.experience_learner")

# ── 默认 LLM 配置（可通过环境变量覆盖） ────────────────────
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://models.sjtu.edu.cn/api/v1"
ENV_MODEL = "EXPERIENCE_LLM_MODEL"
ENV_BASE_URL = "EXPERIENCE_LLM_BASE_URL"
ENV_API_KEY = "EXPERIENCE_LLM_API_KEY"
FALLBACK_ENV_API_KEY = "TRIMUM_LLM_API_KEY"

# ── 经验去重窗口（秒） ──────────────────────────────────
DEDUP_WINDOW_SECONDS = 3600  # 1小时内同一 pattern 只累加计数
EXPERIENCE_NAMESPACE = "experience"


class ExperienceEntry:
    """A structured experience entry learned from a failure.

    Stored as JSON in Agent memory under ``experience.<fingerprint>``.

    Fields:
        pattern:  Normalized pattern string used for deduplication.
        advice:   Actionable advice (what to do next time).
        severity: 'info', 'warning', 'error' (based on original event).
        count:    How many times this pattern has been observed.
        first_seen: Unix timestamp of first occurrence.
        last_seen:  Unix timestamp of most recent occurrence.
        source_events: List of event types that triggered this pattern.
    """

    __slots__ = (
        "pattern", "advice", "severity", "count",
        "first_seen", "last_seen", "source_events",
    )

    def __init__(
        self,
        pattern: str,
        advice: str,
        severity: str = "warning",
        count: int = 1,
        first_seen: Optional[float] = None,
        last_seen: Optional[float] = None,
        source_events: Optional[list[str]] = None,
    ) -> None:
        self.pattern = pattern
        self.advice = advice
        self.severity = severity
        self.count = count
        self.first_seen = first_seen or time.time()
        self.last_seen = last_seen or time.time()
        self.source_events = source_events or []

    @property
    def fingerprint(self) -> str:
        """Unique fingerprint for deduplication (SHA-256 of pattern)."""
        return hashlib.sha256(self.pattern.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "advice": self.advice,
            "severity": self.severity,
            "count": self.count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "source_events": self.source_events,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperienceEntry":
        return cls(
            pattern=data["pattern"],
            advice=data.get("advice", ""),
            severity=data.get("severity", "warning"),
            count=data.get("count", 1),
            first_seen=data.get("first_seen"),
            last_seen=data.get("last_seen"),
            source_events=data.get("source_events", []),
        )


# ═══════════════════════════════════════════════════════════════════
# ExperienceLearner
# ═══════════════════════════════════════════════════════════════════


class ExperienceLearner:
    """Learn from failure events and store structured experience.

    Usage::

        learner = ExperienceLearner(event_bus)
        await learner.start()
        # ... later ...
        await learner.stop()
    """

    # Event patterns to subscribe to
    FAILURE_EVENT_PATTERNS = [
        "event.agent.failed",
        "event.tool.failed",
        "event.task.failed",
        "event.workflow.failed",
        "event.planner.failed",
        "event.transform.failed",
    ]

    def __init__(
        self,
        event_bus: EventBus,
        *,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        dedup_window: float = DEDUP_WINDOW_SECONDS,
    ) -> None:
        self._bus = event_bus
        self._model = model or os.environ.get(ENV_MODEL, DEFAULT_MODEL)
        self._base_url = base_url or os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL)
        self._api_key = api_key or os.environ.get(ENV_API_KEY) or os.environ.get(FALLBACK_ENV_API_KEY, "")
        self._dedup_window = dedup_window

        # In-memory dedup cache: agent_id -> {fingerprint: last_seen}
        self._dedup_cache: dict[str, dict[str, float]] = {}

        # Registered subscription patterns (for stop/cleanup)
        self._subscribed: list[str] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Subscribe to all failure event patterns."""
        for pattern in self.FAILURE_EVENT_PATTERNS:
            self._bus.subscribe(pattern, self._on_failure)
            self._subscribed.append(pattern)
        log.info(
            "ExperienceLearner started",
            extra={"patterns": self.FAILURE_EVENT_PATTERNS},
        )

    async def stop(self) -> None:
        """Unsubscribe all registered callbacks."""
        for pattern in self._subscribed:
            self._bus.unsubscribe(pattern, self._on_failure)
        self._subscribed.clear()
        log.info("ExperienceLearner stopped")

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    async def _on_failure(self, event: SystemEvent) -> None:
        """Handle a failure event — best-effort, never raise."""
        try:
            await self._process_failure(event)
        except Exception:
            log.exception("ExperienceLearner._on_failure: unexpected error (swallowed)")

    async def _process_failure(self, event: SystemEvent) -> None:
        """Core logic: extract context, call LLM, deduplicate, store."""
        payload = event.payload or {}
        agent_id = payload.get("agent_id") or payload.get("source", "unknown")
        event_type = event.event_type

        # ── 1. Build LLM prompt ──────────────────────
        system_prompt = (
            "You are a senior software engineer debugging a failure. "
            "Given the event details below, produce ONE structured experience entry "
            "that will help the same agent avoid this failure in the future.\n\n"
            "Respond in JSON format ONLY (no markdown, no extra text):\n"
            "{\n"
            '  "pattern": "short normalized description of the failure pattern",\n'
            '  "advice": "actionable advice (1-2 sentences, what to do differently)",\n'
            '  "severity": "info|warning|error"\n'
            "}\n\n"
            "If the event payload is empty or uninformative, set pattern='unknown' "
            "and advice='Event payload was empty — consider adding more context to events'."
        )

        user_prompt = self._build_user_prompt(event)

        # ── 2. Call LLM ──────────────────────────────
        raw = await self._call_llm(system_prompt, user_prompt)
        if raw is None:
            log.warning("ExperienceLearner: LLM returned nothing, skipping")
            return

        entry = self._parse_llm_response(raw, event_type)
        if entry is None:
            log.warning("ExperienceLearner: failed to parse LLM response", extra={"raw": raw[:200]})
            return

        # ── 3. Deduplicate ───────────────────────────
        if self._is_duplicate(agent_id, entry):
            log.debug(
                "ExperienceLearner: dedup hit (pattern=%s, agent=%s)",
                entry.pattern[:60],
                agent_id,
            )
            # Still update last_seen and count via the stored entry
            await self._update_existing(agent_id, entry)
            return

        # ── 4. Store via MemoryBridge (Event Bus) ────
        await self._store_experience(agent_id, entry)
        log.info(
            "ExperienceLearner: stored experience",
            extra={
                "agent": agent_id,
                "pattern": entry.pattern[:80],
                "severity": entry.severity,
            },
        )

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_user_prompt(self, event: SystemEvent) -> str:
        """Compose a concise user prompt from the failure event."""
        payload = event.payload or {}
        lines: list[str] = [
            f"Event type: {event.event_type}",
            f"Source: {event.source}",
            f"Severity: {event.severity.value}",
        ]

        # Include relevant payload fields
        useful_keys = [
            "error", "message", "reason", "stderr", "exit_code",
            "tool", "command", "args", "agent_type", "task_type",
            "exception", "traceback",
        ]
        payload_section = []
        for key in useful_keys:
            val = payload.get(key)
            if val is not None:
                payload_section.append(f"  {key}: {json.dumps(val, ensure_ascii=False)[:500]}")
        if payload_section:
            lines.append("Payload:")
            lines.extend(payload_section)

        # Include a few recent events for context
        recent = self._bus.get_history(limit=5)
        if recent:
            lines.append("\nRecent events (for context):")
            for ev in recent:
                lines.append(
                    f"  [{ev.event_type}] src={ev.source} "
                    f"sev={ev.severity.value}"
                )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout: float = 15.0,
    ) -> Optional[str]:
        """Call OpenAI-compatible chat completions API via urllib.

        Runs in a thread executor to avoid blocking the event loop.
        """
        if not self._api_key:
            log.warning(
                "ExperienceLearner: no API key configured. "
                "Set %s or %s environment variable.",
                ENV_API_KEY,
                FALLBACK_ENV_API_KEY,
            )
            return None

        url = f"{self._base_url.rstrip('/')}/chat/completions"
        body = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }).encode("utf-8")

        def _do_request() -> Optional[str]:
            """Synchronous HTTP request via urllib."""
            import urllib.error  # noqa: F811
            import urllib.request  # noqa: F811

            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                # Navigate OpenAI-compatible response
                choices = data.get("choices", [])
                if not choices:
                    return None
                return choices[0].get("message", {}).get("content", "")
            except urllib.error.HTTPError as e:
                log.warning(
                    "ExperienceLearner: LLM HTTP %s — %s",
                    e.code,
                    e.read().decode("utf-8", errors="replace")[:200],
                )
                return None
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
                log.warning("ExperienceLearner: LLM request failed — %s", e)
                return None

        return await asyncio.to_thread(_do_request)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_llm_response(
        raw: str,
        event_type: str,
    ) -> Optional[ExperienceEntry]:
        """Extract JSON from LLM response and build ExperienceEntry.

        Handles:
        - Pure JSON response
        - JSON wrapped in markdown code fences (```json ... ```)
        - Truncation recovery (closes incomplete JSON)
        """
        text = raw.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            # Find the first { after ```
            brace_idx = text.find("{")
            if brace_idx >= 0:
                text = text[brace_idx:]
            # Remove trailing fence
            end_idx = text.rfind("```")
            if end_idx >= 0:
                text = text[:end_idx]
            text = text.strip().rstrip("`").strip()

        # Try to parse
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON substring
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    return None
            else:
                return None

        pattern = data.get("pattern", "unknown")
        advice = data.get("advice", "")
        severity = data.get("severity", "warning")

        # Validate severity
        if severity not in ("info", "warning", "error"):
            severity = "warning"

        return ExperienceEntry(
            pattern=pattern,
            advice=advice,
            severity=severity,
            source_events=[event_type],
        )

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _is_duplicate(self, agent_id: str, entry: ExperienceEntry) -> bool:
        """Check if a similar experience already exists in memory cache."""
        agent_cache = self._dedup_cache.get(agent_id)
        if agent_cache is None:
            return False

        last_seen = agent_cache.get(entry.fingerprint)
        if last_seen is None:
            return False

        return (time.time() - last_seen) < self._dedup_window

    async def _update_existing(
        self,
        agent_id: str,
        new_entry: ExperienceEntry,
    ) -> None:
        """Increment count and update last_seen for an existing experience."""
        # Update in-memory cache
        self._dedup_cache.setdefault(agent_id, {})[new_entry.fingerprint] = time.time()

        # Try to update stored entry via MemoryBridge
        # We emit a memory.agent.get to retrieve current, then memory.agent.set to update
        key = f"experience.{new_entry.fingerprint}"

        class _ReplyCollector:
            """Simple collector for memory reply events."""
            def __init__(self):
                self.result = None

            async def __call__(self, event) -> None:
                p = event.payload or {}
                self.result = p.get("result")

        collector = _ReplyCollector()
        reply_topic = f"event.experience.update.reply.{new_entry.fingerprint}"

        self._bus.subscribe(reply_topic, collector)
        try:
            await self._bus.emit_event(
                f"memory.agent.get",
                "experience_learner",
                {
                    "agent_id": agent_id,
                    "key": key,
                    "reply_topic": reply_topic,
                    "request_id": new_entry.fingerprint,
                },
            )
            # Brief wait for reply
            for _ in range(5):
                if collector.result is not None:
                    break
                await asyncio.sleep(0.1)

            if collector.result is not None:
                existing = ExperienceEntry.from_dict(collector.result)
                existing.count += 1
                existing.last_seen = time.time()
                if new_entry.source_events:
                    for ev in new_entry.source_events:
                        if ev not in existing.source_events:
                            existing.source_events.append(ev)

                # Write back
                await self._bus.emit_event(
                    f"memory.agent.set",
                    "experience_learner",
                    {
                        "agent_id": agent_id,
                        "key": key,
                        "value": existing.to_dict(),
                    },
                )
        finally:
            self._bus.unsubscribe(reply_topic, collector)

    # ------------------------------------------------------------------
    # Store via MemoryBridge
    # ------------------------------------------------------------------

    async def _store_experience(
        self,
        agent_id: str,
        entry: ExperienceEntry,
    ) -> None:
        """Store a new experience entry via MemoryBridge (memory.agent.set event)."""
        # Update in-memory dedup cache
        self._dedup_cache.setdefault(agent_id, {})[entry.fingerprint] = time.time()

        key = f"experience.{entry.fingerprint}"
        await self._bus.emit_event(
            f"memory.agent.set",
            "experience_learner",
            {
                "agent_id": agent_id,
                "key": key,
                "value": entry.to_dict(),
                "ttl_seconds": None,  # permanent
            },
        )

    # ------------------------------------------------------------------
    # Public query helpers
    # ------------------------------------------------------------------

    async def get_experiences(
        self,
        agent_id: str,
    ) -> list[ExperienceEntry]:
        """Retrieve all experiences for an agent via MemoryBridge."""
        class _ReplyCollector:
            def __init__(self):
                self.result = None

            async def __call__(self, event) -> None:
                p = event.payload or {}
                self.result = p.get("result")

        collector = _ReplyCollector()
        reply_topic = f"event.experience.list.reply.{agent_id}"

        # We use memory.agent.get with a special key to list all experience entries
        # Since ContextManager only supports get-by-key, we need to list all
        # by searching the agent's memory for "experience." prefix.
        # For now, we emit a search event and parse results.
        self._bus.subscribe(reply_topic, collector)
        try:
            await self._bus.emit_event(
                "memory.search",
                "experience_learner",
                {
                    "query": f"agent_id:{agent_id} namespace:{EXPERIENCE_NAMESPACE}",
                    "limit": 100,
                    "reply_topic": reply_topic,
                },
            )
            for _ in range(5):
                if collector.result is not None:
                    break
                await asyncio.sleep(0.2)

            if collector.result is None:
                return []

            results = collector.result
            if isinstance(results, list):
                entries = []
                for item in results:
                    try:
                        entries.append(ExperienceEntry.from_dict(item))
                    except (KeyError, ValueError, TypeError):
                        continue
                return entries
            return []
        finally:
            self._bus.unsubscribe(reply_topic, collector)

    def clear_cache(self, agent_id: Optional[str] = None) -> None:
        """Clear in-memory dedup cache for testing or reset."""
        if agent_id:
            self._dedup_cache.pop(agent_id, None)
        else:
            self._dedup_cache.clear()


__all__ = ["ExperienceLearner", "ExperienceEntry"]