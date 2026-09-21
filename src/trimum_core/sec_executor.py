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
from .sec_monitor import (
    AuditChainVerifier,
    OpContextClassifier,
    SecMonitor,
    ThreatMatcher,
)


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
    """Append-only audit log with HMAC hash-chain integrity.

    ``audit_path=None`` 表示**不落盘**：裸 CLI 进程（``trm ask`` / ``trm exec``）
    没有 daemon 的审计链，也不该往 ``~/.trimum`` 写文件，就地发事件、由网关自己的
    AuditStore 记账即可。默认仍是 :data:`DEFAULT_PATH`。
    """

    DEFAULT_PATH = "~/.trimum/audit/security.log"

    def __init__(
        self,
        audit_path: Optional[str] = DEFAULT_PATH,
        hmac_key: str = "",
    ) -> None:
        self.audit_path = Path(audit_path).expanduser() if audit_path else None
        if self.audit_path is not None:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.hmac_key = hmac_key or "default-dev-key"
        self._verifier = AuditChainVerifier(self.hmac_key)

    def _read_last_hash(self) -> str:
        """Return the HMAC of the last audit record (empty if no log)."""
        if self.audit_path is None or not self.audit_path.exists():
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
        if self.audit_path is None:
            return
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
        if self.audit_path is None:
            return True, []
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


class SecurityRuntime:
    """L4 全链路装配（**一处定义**，所有入口都用它）。

    存在的理由：L4 以前是「谁记得注入 ``sec_monitor`` 谁才有」的可选依赖 —— daemon
    之外的入口（``trm ask`` / ``trm exec`` / workflow 的兜底网关）悄悄没有 L4，
    命中威胁既不广播也不阻断。

    - :meth:`daemon`：审计落盘 + 通知 + 阻断 + 工作流触发，daemon 用；
    - :meth:`local`：同一条事件链，但**审计不落盘**，``ToolGateway`` 没被注入监控时
      自动用它兜底。

    两者只差「审计是否落盘」：``security.monitor_result`` / ``security.alert`` /
    ``security.blocked`` / ``workflow.trigger`` 都照发，所以内置剧本与实时控制台在
    任何入口看到的行为一致。
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        *,
        audit_path: Optional[str] = None,
        hmac_key: str = "",
        threat_matcher: Optional[ThreatMatcher] = None,
        context_tracker: Optional[OpContextClassifier] = None,
    ) -> None:
        self.event_bus = event_bus or EventBus()
        self.threat_matcher = threat_matcher or ThreatMatcher()
        self.context_tracker = context_tracker or OpContextClassifier()
        self.audit = SecAudit(audit_path, hmac_key)
        self.notif = SecNotif(self.event_bus)
        self.executor = SecExecutor(self.event_bus, self.audit, self.notif)
        self.monitor = SecMonitor(
            self.event_bus, self.threat_matcher, self.context_tracker, self.executor
        )

    @classmethod
    def daemon(
        cls,
        event_bus: EventBus,
        *,
        audit_path: Optional[str] = SecAudit.DEFAULT_PATH,
        hmac_key: str = "",
    ) -> "SecurityRuntime":
        """daemon 装配：审计落 ``~/.trimum/audit/security.log``。"""
        return cls(event_bus, audit_path=audit_path, hmac_key=hmac_key)

    @classmethod
    def local(cls, event_bus: Optional[EventBus] = None) -> "SecurityRuntime":
        """单进程装配（CLI）：同一条事件链，审计不落盘。"""
        return cls(event_bus, audit_path=None)

    async def start(self) -> None:
        """生命周期钩子（幂等）。"""
        await self.monitor.start()

    def attach(self, gateway: Any) -> None:
        """把监控 / 执行器 / 操作上下文接到一个已建好的网关上。"""
        gateway.sec_monitor = self.monitor
        gateway.sec_executor = self.executor
        gateway.op_context = self.context_tracker
