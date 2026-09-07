"""Security Executor — defense actions, audit, and notifications.

Responsibilities:
1. SecBlocker: deny/freeze/kill/isolate primitives.
2. SecAudit: append-only JSON-lines audit log with HMAC hash chain.
3. SecNotif: publish security alerts/block notifications to the Event Bus.
4. SecExecutor: orchestrate audit, blocking, notifications, and workflow
   triggers for a detected threat.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from .event_bus import (
    EVENT_SEC_ALERT,
    EVENT_SEC_BLOCKED,
    EVENT_WORKFLOW_TRIGGER,
    EventBus,
)
from .models import (
    AuditRecord,
    DefenseAction,
    EventSeverity,
    SystemEvent,
    ThreatMatch,
)
from .sec_monitor import AuditChainVerifier


class SecBlocker:
    """Process-level defense actions."""

    @staticmethod
    async def deny(pid: int = 0, reason: str = "") -> None:
        """DENY is enforced in ToolGateway; this stub keeps the API uniform."""
        _ = pid, reason
        return None

    @staticmethod
    async def freeze(pid: int) -> bool:
        """SIGSTOP the process (ransomware/miner in progress)."""
        if pid <= 0:
            return False
        try:
            os.kill(pid, signal.SIGSTOP)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    @staticmethod
    async def kill(pid: int) -> bool:
        """SIGKILL the process (confirmed backdoor/rootkit)."""
        if pid <= 0:
            return False
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    @staticmethod
    async def isolate_network(pid: int) -> None:
        """Temporary network isolation stub (iptables REJECT in Phase 4)."""
        _ = pid
        return None


class SecAudit:
    """Append-only audit log with HMAC hash-chain integrity."""

    def __init__(
        self,
        audit_path: str = "~/.trimum/audit/security.log",
        hmac_key: str = "",
    ) -> None:
        self.audit_path = Path(audit_path).expanduser()
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.hmac_key = hmac_key or "default-dev-key"
        self._verifier = AuditChainVerifier(self.hmac_key)

    def _read_last_hash(self) -> str:
        """Return the HMAC of the last audit record (empty if no log)."""
        if not self.audit_path.exists():
            return ""
        last_line = ""
        with open(self.audit_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    last_line = line
        if not last_line:
            return ""
        try:
            record = __import__("json").loads(last_line)
        except Exception:
            return ""
        return record.get("hmac", "")

    async def log(self, record: AuditRecord) -> None:
        """Write an audit record and link it into the hash chain."""
        record.prev_hash = self._read_last_hash()
        dict_record = record.model_dump()
        dict_record.pop("hmac", None)
        dict_record["hmac"] = self._verifier.compute_hash(dict_record)

        with open(self.audit_path, "a", encoding="utf-8") as handle:
            handle.write(
                __import__("json").dumps(dict_record, default=str) + "\n"
            )

    def verify_chain(self) -> tuple[bool, list[str]]:
        """Verify the full audit log hash chain and HMAC signatures."""
        return self._verifier.verify_chain(self.audit_path)


class SecNotif:
    """Event Bus notifications for security outcomes."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    @staticmethod
    def _defense_value(threat: ThreatMatch) -> str:
        defense = threat.defense
        return defense.value if hasattr(defense, "value") else str(defense)

    async def alert(self, threat: ThreatMatch, event: SystemEvent) -> None:
        """Publish ``security.alert``."""
        await self.event_bus.publish(
            SystemEvent(
                event_type=EVENT_SEC_ALERT,
                source="sec_executor",
                severity=EventSeverity.WARNING,
                payload={
                    "threat_name": threat.threat_name,
                    "defense": self._defense_value(threat),
                    "agent_id": event.payload.get("agent_id", ""),
                    "command": event.payload.get("command", ""),
                    "reason": threat.reason,
                },
            )
        )

    async def blocked(self, threat: ThreatMatch, event: SystemEvent) -> None:
        """Publish ``security.blocked``."""
        await self.event_bus.publish(
            SystemEvent(
                event_type=EVENT_SEC_BLOCKED,
                source="sec_executor",
                severity=EventSeverity.CRITICAL,
                payload={
                    "threat_name": threat.threat_name,
                    "defense": self._defense_value(threat),
                    "agent_id": event.payload.get("agent_id", ""),
                    "command": event.payload.get("command", ""),
                    "reason": threat.reason,
                },
            )
        )


class SecExecutor:
    """Security executor main class."""

    def __init__(
        self,
        event_bus: EventBus,
        audit: SecAudit,
        notif: SecNotif,
    ) -> None:
        self.event_bus = event_bus
        self.audit = audit
        self.notif = notif
        self.blocker = SecBlocker()

    async def execute(self, threat: ThreatMatch, event: SystemEvent) -> None:
        """Execute the highest-priority defense action for a threat."""
        agent_id = event.payload.get("agent_id", "unknown")
        command = event.payload.get("command", "")
        pid = int(event.payload.get("pid", 0) or 0)
        defense = threat.defense
        defense = defense.value if hasattr(defense, "value") else str(defense)

        audit_record = AuditRecord(
            timestamp=time.time(),
            event_id=f"sec_{uuid4().hex[:8]}",
            agent_id=agent_id,
            command=command,
            threat=threat.threat_name,
            verdict=str(defense),
            reason=threat.reason,
            context=event.payload.get("context", "normal"),
            sandbox=event.payload.get("sandbox", "default"),
            layer_hit=event.payload.get("layer_hit", "L2"),
        )
        await self.audit.log(audit_record)

        if defense == DefenseAction.DENY.value:
            await self.notif.blocked(threat, event)
        elif defense == DefenseAction.FREEZE.value:
            await self.blocker.freeze(pid)
            await self.notif.alert(threat, event)
        elif defense == DefenseAction.KILL.value:
            await self.blocker.kill(pid)
            await self.notif.blocked(threat, event)
        elif defense == DefenseAction.ISOLATE.value:
            await self.blocker.isolate_network(pid)
            await self.notif.alert(threat, event)
        else:
            await self.notif.alert(threat, event)

        if threat.workflow_name:
            await self.event_bus.publish(
                SystemEvent(
                    event_type=EVENT_WORKFLOW_TRIGGER,
                    source="sec_executor",
                    severity=EventSeverity.INFO,
                    payload={
                        "workflow_name": threat.workflow_name,
                        "threat_name": threat.threat_name,
                        "agent_id": agent_id,
                    },
                )
            )