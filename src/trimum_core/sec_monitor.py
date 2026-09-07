"""Security Monitor — Layer 4 threat matching and context tracking.

Responsibilities:
1. ThreatMatcher: regex-based threat signature matching.
2. OpContextClassifier: per-agent command history and sequence analysis.
3. AuditChainVerifier: HMAC-signed audit hash-chain integrity checks.
4. SecMonitor: Event Bus subscriber that scans ``agent.executing`` events and
   dispatches detected threats to SecExecutor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .event_bus import EVENT_SEC_ALERT, EVENT_SEC_MONITOR, EventBus
from .models import (
    DefenseAction,
    EventSeverity,
    OpContext,
    SystemEvent,
    ThreatCategory,
    ThreatMatch,
)


@dataclass
class ThreatSignature:
    """A named threat signature with regex patterns and defense action."""

    name: str
    category: ThreatCategory
    defense: DefenseAction
    patterns: list[str]
    description: str = ""
    min_confidence: float = 0.7
    trigger_workflow: str = ""


_BUILTIN_SIGNATURES: list[ThreatSignature] = [
    ThreatSignature(
        name="ld_preload",
        category=ThreatCategory.PRIV_ESCAPE,
        defense=DefenseAction.DENY,
        patterns=[
            r"\bld\.so\.preload\b",
            r"\bLD_PRELOAD\b",
            r"echo\s+[^>]*>>\s*/etc/ld\.so\.preload",
        ],
        description="LD_PRELOAD 预加载劫持",
        trigger_workflow="threat-prelink-check",
    ),
    ThreatSignature(
        name="ebpf_hijack",
        category=ThreatCategory.PRIV_ESCAPE,
        defense=DefenseAction.KILL,
        patterns=[
            r"\bbpftool\b",
            r"\bbpffs\b",
            r"/sys/fs/bpf",
            r"\blibbpf\b",
        ],
        description="eBPF 程序劫持",
        trigger_workflow="threat-ebpf-scan",
    ),
    ThreatSignature(
        name="kernel_module",
        category=ThreatCategory.PRIV_ESCAPE,
        defense=DefenseAction.DENY,
        patterns=[
            r"\binsmod\b",
            r"\bmodprobe\b",
            r"\brmmod\b",
            r"\.ko\b",
        ],
        description="内核模块加载/卸载",
        trigger_workflow="threat-kernel-scan",
    ),
    ThreatSignature(
        name="reverse_shell",
        category=ThreatCategory.C2_BOTNET,
        defense=DefenseAction.KILL,
        patterns=[
            r"/dev/tcp/",
            r"\bnc\s+(-e|-c)\b",
            r"\bncat\s+(-e|-c)\b",
            r"python\S*\s+-c\s+[^;]*socket",
            r"bash\s+-i\s*>\s*&\s*/dev/tcp/",
        ],
        description="反弹 shell",
        trigger_workflow="threat-revshell-cleanup",
    ),
    ThreatSignature(
        name="curl_pipe_bash",
        category=ThreatCategory.SUPPLY_CHAIN,
        defense=DefenseAction.DENY,
        patterns=[
            r"curl\s+\S+\s*\|\s*(ba)?sh",
            r"wget\s+\S+\s*\|\s*(ba)?sh",
        ],
        description="curl|bash 远程脚本执行",
        trigger_workflow="threat-pipe-download-check",
    ),
    ThreatSignature(
        name="crypto_miner",
        category=ThreatCategory.MALWARE,
        defense=DefenseAction.FREEZE,
        patterns=[
            r"\bxmrig\b",
            r"\bminerd\b",
            r"\bcpuminer\b",
            r"\bstratum\b",
            r"\bnicehash\b",
        ],
        description="挖矿程序",
        trigger_workflow="threat-crypto-scan",
    ),
    ThreatSignature(
        name="ssh_key_steal",
        category=ThreatCategory.DATA_THEFT,
        defense=DefenseAction.DENY,
        patterns=[
            r"~/.ssh/",
            r"\.ssh[/\\]id_(rsa|ed25519|ecdsa)",
            r"authorized_keys",
            r"\bssh-rsa\b",
        ],
        description="SSH 私钥/凭证窃取",
        trigger_workflow="threat-ssh-audit",
    ),
    ThreatSignature(
        name="supply_chain",
        category=ThreatCategory.SUPPLY_CHAIN,
        defense=DefenseAction.CONFIRM,
        patterns=[
            r"\bpip\s+install\b",
            r"\bnpm\s+install\b",
            r"\bpostinstall\b",
            r"\bPKGBUILD\b",
        ],
        description="供应链投毒特征",
        trigger_workflow="threat-supply-chain-audit",
    ),
    ThreatSignature(
        name="cron_persistence",
        category=ThreatCategory.MALWARE,
        defense=DefenseAction.DENY,
        patterns=[
            r"\bcrontab\b",
            r"/etc/cron",
            r"@reboot",
            r"\bcron\.d\b",
        ],
        description="cron 持久化",
        trigger_workflow="threat-cron-audit",
    ),
    ThreatSignature(
        name="systemd_persistence",
        category=ThreatCategory.MALWARE,
        defense=DefenseAction.DENY,
        patterns=[
            r"systemctl\s+enable",
            r"/etc/systemd/system/",
            r"\bsystemd\b",
        ],
        description="systemd 持久化",
        trigger_workflow="threat-systemd-audit",
    ),
    ThreatSignature(
        name="prompt_injection",
        category=ThreatCategory.LLM_ATTACK,
        defense=DefenseAction.CONFIRM,
        patterns=[
            r"ignore\s+(all\s+)?previous\s+instructions",
            r"disregard\s+(all\s+)?instructions",
            r"bypass\s+(the\s+)?(security\s+)?policy",
            r"reveal\s+(your\s+)?system\s+prompt",
        ],
        description="LLM 提示注入",
        trigger_workflow="threat-prompt-injection-check",
    ),
    ThreatSignature(
        name="memfd_exec",
        category=ThreatCategory.MALWARE,
        defense=DefenseAction.ISOLATE,
        patterns=[
            r"memfd_create",
            r"\bmemfd\b",
            r"/proc/self/fd/",
        ],
        description="memfd 内存文件执行",
        trigger_workflow="threat-memfd-scan",
    ),
]


class OpContextClassifier:
    """Per-agent operation context tracker.

    Keeps a bounded history (default window 20) per ``agent_id`` and classifies
    the current operation sequence into an :class:`OpContext` marker.
    """

    def __init__(self, maxlen: int = 20) -> None:
        self._cache: dict[str, deque[str]] = {}
        self._maxlen = maxlen

    def record(self, agent_id: str, command: str) -> None:
        """Record one command into the agent history ring buffer."""
        agent_id = agent_id or "unknown"
        if not command:
            return
        queue = self._cache.setdefault(agent_id, deque(maxlen=self._maxlen))
        queue.append(command)

    def get_history(self, agent_id: str) -> list[str]:
        """Return the recent command history for an agent (oldest first)."""
        return list(self._cache.get(agent_id or "unknown", []))

    def get_context(self, agent_id: str) -> OpContext:
        """Classify the current agent operation context."""
        history = self.get_history(agent_id)
        if not history:
            return OpContext.NORMAL
        return self.classify(history)

    def classify(self, history: list[str]) -> OpContext:
        """Analyze a command sequence and return the best-matching context."""
        joined = " ".join(history).lower()
        last = history[-1].lower() if history else ""

        if re.search(r"(curl|wget)\s+\S+\s*\|\s*(ba)?sh", joined):
            return OpContext.DOWNLOAD_THEN_EXEC

        if re.search(r"git\s+clone", joined) and re.search(
            r"\b(make|cmake|\./configure|\./build)\b", joined
        ):
            return OpContext.CLONE_THEN_BUILD

        if re.search(r"\b(gcc|g\+\+|clang)\b", joined) and re.search(
            r"\./[\w./-]+|make", last
        ):
            return OpContext.COMPILE_THEN_EXEC

        if re.search(r"(chmod\s+\+s|\bsetuid\b)", joined):
            return OpContext.SUID_STORM

        if re.search(r"(gpg|openssl|ccrypt)\b", joined) and re.search(
            r"\bencrypt\b|>>|tee", joined
        ):
            return OpContext.WRITE_THEN_ENCRYPT

        if re.search(r"\.ssh[/\\]|id_(rsa|ed25519)|authorized_keys", joined):
            return OpContext.KEY_STEAL

        if re.search(r"(cat|echo|tee)\b[^;]*>", joined) and re.search(
            r"\./|bash\s+\S+\.sh|chmod\s+\+x", joined
        ):
            return OpContext.WRITE_THEN_EXEC

        return OpContext.NORMAL


class ThreatMatcher:
    """Regex-based threat matcher built on :class:`ThreatSignature`."""

    def __init__(self, signatures: Optional[list[ThreatSignature]] = None) -> None:
        self.signatures = list(signatures) if signatures else list(_BUILTIN_SIGNATURES)
        self._compiled: list[tuple[ThreatSignature, list[re.Pattern[str]]]] = [
            (sig, [re.compile(pattern, re.IGNORECASE) for pattern in sig.patterns])
            for sig in self.signatures
        ]

    def match(
        self,
        agent_id: str,
        command: str,
        context: str | OpContext = OpContext.NORMAL,
    ) -> list[ThreatMatch]:
        """Match a single command against all signatures.

        Returns matching threats sorted by confidence (highest first).
        """
        matches: list[ThreatMatch] = []
        for signature, compiled in self._compiled:
            matched_pattern = ""
            for pattern, regex in zip(signature.patterns, compiled):
                if regex.search(command):
                    matched_pattern = pattern
                    break
            if matched_pattern:
                matches.append(
                    ThreatMatch(
                        threat_name=signature.name,
                        category=signature.category,
                        defense=signature.defense,
                        confidence=signature.min_confidence,
                        matched_pattern=matched_pattern,
                        workflow_name=signature.trigger_workflow,
                        reason=f"{signature.name} detected: {matched_pattern}",
                    )
                )

        matches.sort(key=lambda item: item.confidence, reverse=True)
        return matches

    def match_sequence(
        self,
        agent_id: str,
        ops: list[dict] | list[str],
    ) -> Optional[ThreatMatch]:
        """Match a sequence of operations and return one sequence threat."""
        if not ops:
            return None

        if isinstance(ops[0], str):
            commands = [op for op in ops if isinstance(op, str)]
        else:
            commands = [
                op.get("command", "")
                for op in ops
                if isinstance(op, dict) and op.get("command")
            ]
        joined = " ".join(commands).lower()

        for signature, compiled in self._compiled:
            for pattern, regex in zip(signature.patterns, compiled):
                if regex.search(joined):
                    return ThreatMatch(
                        threat_name=signature.name,
                        category=signature.category,
                        defense=signature.defense,
                        confidence=min(1.0, signature.min_confidence + 0.05),
                        matched_pattern=pattern,
                        workflow_name=signature.trigger_workflow,
                        reason=f"{signature.name} sequence detected: {pattern}",
                    )
        return None


class AuditChainVerifier:
    """HMAC-signed audit hash-chain integrity verifier."""

    def __init__(self, hmac_key: str = "default-dev-key") -> None:
        self.hmac_key = hmac_key

    def compute_hash(self, record: dict[str, Any]) -> str:
        """Compute an HMAC-SHA256 signature for a serializable record dict."""
        data = json.dumps(record, sort_keys=True, default=str, separators=(",", ":"))
        return hmac.new(
            self.hmac_key.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_chain(self, audit_path: str | Path) -> tuple[bool, list[str]]:
        """Verify a JSON-lines audit file's hash chain and HMAC signatures."""
        path = Path(audit_path).expanduser()
        errors: list[str] = []
        if not path.exists():
            return True, errors

        prev_hmac = ""
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    errors.append("Malformed audit record")
                    continue

                event_id = record.get("event_id", "?")
                if record.get("prev_hash") != prev_hmac:
                    errors.append(f"Hash chain broken at {event_id}")
                expected = self.compute_hash(
                    {key: value for key, value in record.items() if key != "hmac"}
                )
                if record.get("hmac") != expected:
                    errors.append(f"HMAC mismatch at {event_id}")
                prev_hmac = record.get("hmac", "")

        return len(errors) == 0, errors


class SecMonitor:
    """Security monitor main class.

    Subscribes to the Event Bus and bridges ThreatMatcher/OpContextClassifier
    with SecExecutor.
    """

    def __init__(
        self,
        event_bus: EventBus,
        threat_matcher: ThreatMatcher,
        context_tracker: OpContextClassifier,
        executor: "SecExecutor",
    ) -> None:
        self.event_bus = event_bus
        self.threat_matcher = threat_matcher
        self.context_tracker = context_tracker
        self.executor = executor
        self._started = False

    async def start(self) -> None:
        """Subscribe to Event Bus security-relevant events."""
        if self._started:
            return
        self.event_bus.subscribe("agent.executing", self._on_executing)
        self.event_bus.subscribe("agent.executed", self._on_executed)
        self._started = True

    async def scan_command(
        self,
        agent_id: str,
        command: str,
        pid: int = 0,
        layer_hit: str = "L2",
        sandbox: str = "default",
    ) -> list[ThreatMatch]:
        """Public convenience method: scan one command and return threats."""
        agent_id = agent_id or "unknown"
        context = self.context_tracker.get_context(agent_id)
        self.context_tracker.record(agent_id, command)

        threats = self.threat_matcher.match(agent_id, command, context)
        sequence_threat = self.threat_matcher.match_sequence(
            agent_id, self.context_tracker.get_history(agent_id)
        )
        if sequence_threat and not any(
            item.threat_name == sequence_threat.threat_name for item in threats
        ):
            threats.append(sequence_threat)

        threats.sort(key=lambda item: item.confidence, reverse=True)
        return threats

    async def _on_executing(self, event: SystemEvent) -> None:
        """Handle ``agent.executing`` events: scan command, dispatch threats."""
        agent_id = event.payload.get("agent_id", "unknown")
        command = event.payload.get("command", "")
        pid = int(event.payload.get("pid", 0) or 0)
        sandbox = event.payload.get("sandbox", "default")
        layer_hit = event.payload.get("layer_hit", "L2")

        threats = await self.scan_command(agent_id, command, pid, layer_hit, sandbox)
        if threats:
            await self._dispatch(threats[0], event)
            return

        await self.event_bus.publish(
            SystemEvent(
                event_type=EVENT_SEC_ALERT,
                source="sec_monitor",
                severity=EventSeverity.INFO,
                payload={
                    "agent_id": agent_id,
                    "command": command,
                    "reason": "no_threat_match",
                    "needs_llm": True,
                },
            )
        )

    async def _on_executed(self, event: SystemEvent) -> None:
        """Handle ``agent.executed`` events.

        Reserved for post-execution analysis. Command history is already
        recorded by :meth:`scan_command`, so this handler intentionally does
        not record again to avoid duplicating context entries.
        """
        return None

    async def _dispatch(self, threat: ThreatMatch, event: SystemEvent) -> None:
        """Publish a monitor result and hand the threat to SecExecutor."""
        await self.event_bus.publish(
            SystemEvent(
                event_type=EVENT_SEC_MONITOR,
                source="sec_monitor",
                severity=EventSeverity.WARNING,
                payload={
                    "threat": threat.model_dump(),
                    "original_event": event.model_dump(),
                },
            )
        )
        await self.executor.execute(threat, event)