"""Agent Registry for trimum Core.

Loads agent.json manifests from ~/.trimum/agents/<name>/agent.json
and maintains an in-memory capability table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from trimum_core.agent_cert import (
    CertTrustLevel,
    check_agent_trust,
    confirm_and_trust,
    ensure_cert_dirs,
)
from trimum_core.models import AgentManifest

# Try json5 for comment support
HAS_JSON5 = False
try:
    import json5  # noqa: F401
    HAS_JSON5 = True
except ImportError:
    pass


def _strip_json_comments(text: str) -> str:
    """Strip JS-style comments from JSON text."""
    import re
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return text


class AgentRegistry:
    """In-memory agent type registry backed by agent.json manifests.

    Features:
    - Load manifests from disk (``load_from_dir``)
    - Register/unregister manifests programmatically
    - Look up agents by name or by capability (with dot-notation prefix)
    - Idempotent reloading (replaces previous entries)
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentManifest] = {}
        # capability -> list of agent names (dot-notation expanded)
        self._capability_index: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, manifest: AgentManifest) -> None:
        """Register (or replace) an agent type.

        If an agent with the same name already exists, the previous entry
        is replaced and all capability index entries for it are rebuilt.

        Certificate check:
        - Official cert → automatic trust, no prompt
        - Self-signed cert (same machine) → automatic trust
        - No cert → calls confirm_and_trust (stub, pending Phase 6 UI)
        """
        # Remove old capability entries if re-registering
        if manifest.name in self._agents:
            self._remove_from_capability_index(manifest.name)

        # ── 证书校验 ──────────────────────────────────
        ensure_cert_dirs()
        trust_level, _cert = check_agent_trust(manifest.name)
        if trust_level == CertTrustLevel.CONFIRM:
            entry_path = manifest.entry or ""
            if not confirm_and_trust(manifest.name, entry_path):
                import logging
                log = logging.getLogger("trimum_core.agent_registry")
                log.warning("cert.registration_rejected", agent=manifest.name)
                return  # 用户拒绝，不注册

        self._agents[manifest.name] = manifest
        self._add_to_capability_index(manifest)

    def unregister(self, name: str) -> bool:
        """Remove an agent type by name. Returns True if removed."""
        if name not in self._agents:
            return False
        self._remove_from_capability_index(name)
        del self._agents[name]
        return True

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_agents(self) -> list[AgentManifest]:
        """Return all registered agent manifests."""
        return list(self._agents.values())

    def get_agent(self, name: str) -> Optional[AgentManifest]:
        """Get a single agent manifest by name."""
        return self._agents.get(name)

    def find_by_capability(self, capability: str) -> list[AgentManifest]:
        """Find all agents that claim the given capability.

        Dot-notation prefix matching is supported: querying
        ``system.diagnose`` also matches agents registered with
        ``system.diagnose``, and querying ``system`` matches any agent
        whose capability starts with ``system.``.
        """
        seen: set[str] = set()

        # 1. Exact match
        for name in self._capability_index.get(capability, []):
            seen.add(name)

        # 2. Prefix match: "system" matches "system.*"
        for cap_key, names in self._capability_index.items():
            if cap_key.startswith(capability + ".") or cap_key == capability:
                for name in names:
                    seen.add(name)

        return [self._agents[name] for name in seen if name in self._agents]

    # ------------------------------------------------------------------
    # Disk loading
    # ------------------------------------------------------------------

    def load_from_dir(self, base_path: Optional[str] = None) -> int:
        """Scan a directory for agent manifests and register them.

        Scans ``<base_path>/<name>/agent.json5`` (preferred) or
        ``<base_path>/<name>/agent.json`` for each subdirectory.
        Returns the number of manifests successfully loaded.

        Loading is idempotent: reloading a directory replaces previously
        registered entries for the same agent names.
        """
        if base_path is None:
            base_path = str(Path.home() / ".trimum" / "agents")

        agents_dir = Path(base_path)
        if not agents_dir.is_dir():
            return 0

        count = 0
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            # Try .json5 first, fallback to .json
            manifest_path = agent_dir / "agent.json5"
            is_json5 = True
            if not manifest_path.is_file():
                manifest_path = agent_dir / "agent.json"
                is_json5 = False
            if not manifest_path.is_file():
                continue
            try:
                raw = manifest_path.read_text(encoding="utf-8")
                if is_json5 and not HAS_JSON5:
                    raw = _strip_json_comments(raw)
                if HAS_JSON5:
                    data = json5.loads(raw) if is_json5 else json.loads(raw)
                else:
                    data = json.loads(raw) if not is_json5 else json.loads(_strip_json_comments(raw))
                manifest = AgentManifest(**data)
                self.register(manifest)
                count += 1
            except (json.JSONDecodeError, ValueError, OSError):
                # Skip malformed manifests silently
                continue

        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_to_capability_index(self, manifest: AgentManifest) -> None:
        """Build capability index entries for an agent manifest.

        Each capability is entered verbatim. Dot-notation prefixes are
        also tracked: registering ``system.diagnose`` adds an entry for
        ``system.diagnose`` and ensures ``system.*`` lookups match.
        """
        for cap in manifest.capabilities:
            # Exact capability
            self._capability_index.setdefault(cap, []).append(manifest.name)
            # Dot-notation prefix for "system.*" style lookups
            dot_idx = cap.rfind(".")
            if dot_idx > 0:
                prefix = cap[:dot_idx]
                self._capability_index.setdefault(prefix, []).append(manifest.name)

    def _remove_from_capability_index(self, name: str) -> None:
        """Remove an agent from the capability index."""
        for cap_key in list(self._capability_index.keys()):
            self._capability_index[cap_key] = [
                n for n in self._capability_index[cap_key] if n != name
            ]
            if not self._capability_index[cap_key]:
                del self._capability_index[cap_key]


__all__ = ["AgentRegistry"]
