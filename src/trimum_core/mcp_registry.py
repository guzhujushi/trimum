"""MCP server registry — ``~/.trimum/mcp/<name>.json5`` + a lazy client pool.

File-per-server, same convention as ``~/.trimum/tools/`` and ``~/.trimum/agents/``:
dropping a file in is the whole install step, and nothing needs to be restarted.

Two rules are enforced here rather than in the dispatcher:

* **deny-by-default** — a definition without ``"enabled": true`` is loaded (so
  ``trm mcp list`` can show it) but never started;
* **capability narrowing** — ``allow_tools`` / ``deny_tools`` are glob patterns,
  deny wins, and ``trust: cloud`` servers additionally inherit
  :data:`DEFAULT_DENY_PATTERNS` (delete / exec / shell / eval ...), because a
  remote server must not be able to hand trimum a destructive local tool just by
  naming it that way.

The connection pool keeps one ``MCPClient`` per server name and throws away any
client whose stream broke, so a crashed server self-heals on the next call.
"""

from __future__ import annotations

import asyncio
import json
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .logger import get_logger
from .mcp_client import MCPClient, MCPError, MCPProtocolError
from .paths import trimum_path

log = get_logger("mcp_registry")

#: Point trimum at another directory (tests, provisioning, per-user profiles).
MCP_DIR_ENV = "TRIMUM_MCP_DIR"

DEFAULT_IDLE_TTL = 300.0
RISK_LEVELS = ("low", "medium", "high")

#: <name>.json5 files are addressed by name in ``mcp.tools.call <server> <tool>``.
#: Keep the name shell-safe and lowercase so it can be typed without quoting.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: Extra deny patterns applied to ``trust: cloud`` servers.
DEFAULT_DENY_PATTERNS: tuple[str, ...] = (
    "*delete*",
    "*remove*",
    "*destroy*",
    "*kill*",
    "*exec*",
    "*shell*",
    "*eval*",
    "*command*",
)

try:  # json5 is a hard dependency, the fallback keeps degraded installs loading
    import json5

    HAS_JSON5 = True
except ImportError:  # pragma: no cover - only when the dependency is missing
    HAS_JSON5 = False


def default_mcp_dir() -> Path:
    """Return the MCP definition directory (``TRIMUM_MCP_DIR`` wins)."""
    import os

    override = os.environ.get(MCP_DIR_ENV)
    if override and override.strip():
        return Path(override).expanduser()
    return trimum_path("mcp")


def _strip_json_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments (fallback when json5 is absent)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(^|\s)//[^\n]*", r"\1", text)


def parse_definition_text(text: str) -> dict[str, Any]:
    """Parse a definition file body (json5 when available, else lenient JSON)."""
    if HAS_JSON5:
        return json5.loads(text)
    return json.loads(_strip_json_comments(text))


class MCPServerDefinition(BaseModel):
    """One ``<name>.json5`` MCP server definition."""

    name: str
    transport: Literal["stdio", "http"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""
    url: str = ""
    trust: Literal["local", "cloud"] = "local"
    risk: str = "medium"
    timeout: float = 30.0
    idle_ttl: float = DEFAULT_IDLE_TTL
    enabled: bool = False
    allow_tools: list[str] = Field(default_factory=list)
    deny_tools: list[str] = Field(default_factory=list)
    description: str = ""
    source_url: str = ""
    #: Filled in by the registry so error messages can point at the file.
    path: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        candidate = (value or "").strip().lower()
        if not NAME_PATTERN.match(candidate):
            raise ValueError(
                "name must match [a-z0-9][a-z0-9_-]* (used as `mcp.tools.call <server> <tool>`)"
            )
        return candidate

    @field_validator("risk")
    @classmethod
    def _validate_risk(cls, value: str) -> str:
        candidate = (value or "").strip().lower()
        if candidate not in RISK_LEVELS:
            raise ValueError(f"risk must be one of {', '.join(RISK_LEVELS)}")
        return candidate

    @field_validator("args", mode="before")
    @classmethod
    def _coerce_args(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        return [str(value)]

    @field_validator("env", mode="before")
    @classmethod
    def _coerce_env(cls, value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, dict):
            return {str(key): str(item) for key, item in value.items()}
        raise ValueError("env must be an object of string values")

    @model_validator(mode="after")
    def _check_transport_requirements(self) -> "MCPServerDefinition":
        if self.transport == "stdio" and not self.command.strip():
            raise ValueError("transport 'stdio' requires a command")
        if self.transport == "http" and not self.url.strip():
            raise ValueError("transport 'http' requires a url")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        return self

    # ------------------------------------------------------------------
    # Capability narrowing
    # ------------------------------------------------------------------

    def deny_patterns(self) -> list[str]:
        """Effective deny globs (definition's own + cloud defaults)."""
        patterns = list(self.deny_tools)
        if self.trust == "cloud":
            for pattern in DEFAULT_DENY_PATTERNS:
                if pattern not in patterns:
                    patterns.append(pattern)
        return patterns

    def allows_tool(self, tool: str) -> bool:
        """Return whether *tool* may run on this server (deny wins)."""
        name = (tool or "").strip()
        if not name:
            return False
        if any(fnmatch(name.lower(), pattern.lower()) for pattern in self.deny_patterns()):
            return False
        if self.allow_tools:
            return any(fnmatch(name.lower(), pattern.lower()) for pattern in self.allow_tools)
        return True

    def to_dict(self) -> dict[str, Any]:
        """Serialisable view for ``trm mcp list --json``.

        ``env`` values are **never** echoed (they routinely hold API keys); only
        the variable names are reported.
        """
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args),
            "env_keys": sorted(self.env),
            "cwd": self.cwd,
            "url": self.url,
            "trust": self.trust,
            "risk": self.risk,
            "timeout": self.timeout,
            "idle_ttl": self.idle_ttl,
            "enabled": self.enabled,
            "allow_tools": list(self.allow_tools),
            "deny_tools": list(self.deny_tools),
            "deny_patterns": self.deny_patterns(),
            "description": self.description,
            "source_url": self.source_url,
            "path": self.path,
        }


class MCPRegistry:
    """Loads ``<dir>/<name>.json5`` definitions and reports broken files."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else default_mcp_dir()
        self.problems: list[dict[str, str]] = []
        self._servers: dict[str, MCPServerDefinition] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> dict[str, MCPServerDefinition]:
        """(Re)read the directory; never raises, broken files become problems."""
        self._servers = {}
        self.problems = []
        self._loaded = True

        if not self.directory.is_dir():
            return {}

        seen: set[str] = set()
        for path in sorted(
            [*self.directory.glob("*.json5"), *self.directory.glob("*.json")]
        ):
            if path.name in seen:
                continue
            seen.add(path.name)
            definition = self._load_file(path)
            if definition is None:
                continue
            if definition.name in self._servers:
                self.problems.append(
                    {
                        "path": str(path),
                        "error": f"duplicate server name: {definition.name}",
                    }
                )
                continue
            self._servers[definition.name] = definition

        log.debug(
            "mcp_registry.loaded",
            directory=str(self.directory),
            servers=len(self._servers),
            problems=len(self.problems),
        )
        return dict(self._servers)

    def _load_file(self, path: Path) -> MCPServerDefinition | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.problems.append({"path": str(path), "error": f"unreadable: {exc}"})
            return None

        try:
            data = parse_definition_text(raw)
        except Exception as exc:  # json5 raises its own error type
            self.problems.append({"path": str(path), "error": f"invalid json5: {exc}"})
            return None

        if not isinstance(data, dict):
            self.problems.append({"path": str(path), "error": "definition must be an object"})
            return None

        data = dict(data)
        data.setdefault("name", path.stem)
        data["path"] = str(path)
        try:
            return MCPServerDefinition(**data)
        except ValidationError as exc:
            self.problems.append({"path": str(path), "error": _short_validation_error(exc)})
            return None

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def servers(self) -> dict[str, MCPServerDefinition]:
        if not self._loaded:
            self.load()
        return dict(self._servers)

    def reload(self) -> dict[str, MCPServerDefinition]:
        return self.load()

    def get(self, name: str) -> MCPServerDefinition | None:
        key = (name or "").strip().lower()
        if not self._loaded:
            self.load()
        return self._servers.get(key)

    def names(self) -> list[str]:
        return sorted(self.servers())

    def enabled(self) -> list[MCPServerDefinition]:
        return [item for _, item in sorted(self.servers().items()) if item.enabled]

    def describe(self) -> dict[str, Any]:
        """Everything ``trm mcp list`` needs, in one serialisable dict."""
        servers = [item.to_dict() for _, item in sorted(self.servers().items())]
        return {
            "directory": str(self.directory),
            "exists": self.directory.is_dir(),
            "count": len(servers),
            "enabled": [item["name"] for item in servers if item["enabled"]],
            "servers": servers,
            "problems": list(self.problems),
            "config_env": MCP_DIR_ENV,
        }


def _short_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        message = str(error.get("msg", "invalid"))
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts) or "invalid definition"


class MCPServerPool:
    """Lazy ``MCPClient`` per enabled server, keyed by server name.

    ``client_factory`` is injectable so tests (and future transports) can supply
    their own client without spawning a process.
    """

    def __init__(
        self,
        registry: MCPRegistry | None = None,
        *,
        client_factory: Callable[[MCPServerDefinition], Any] | None = None,
        log_dir: str | Path | None = None,
    ) -> None:
        self.registry = registry or MCPRegistry()
        self.log_dir = Path(log_dir) if log_dir is not None else None
        self._factory = client_factory
        self._clients: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    @property
    def clients(self) -> dict[str, Any]:
        return dict(self._clients)

    async def client(self, name: str, *, refresh: bool = False) -> Any:
        """Return a connected client for *name* (starting it when needed)."""
        definition = self.registry.get(name)
        if definition is None:
            raise MCPError(
                f"MCP server not found: {name or '(empty)'} "
                f"(looked in {self.registry.directory})"
            )
        if not definition.enabled:
            raise MCPError(
                f"MCP server '{definition.name}' is disabled "
                f"(set \"enabled\": true in {definition.path or self.registry.directory})"
            )

        async with self._lock:
            existing = self._clients.get(definition.name)
            if existing is not None:
                if not refresh and getattr(existing, "alive", False):
                    return existing
                # broken stream, or an explicit refresh: drop it (and its process)
                await self._discard(definition.name)

            client = self._make_client(definition)
            try:
                await client.connect()
            except Exception:
                await _safe_close(client)
                raise
            self._clients[definition.name] = client
            return client

    async def _discard(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client is not None:
            await _safe_close(client)

    def _make_client(self, definition: MCPServerDefinition) -> Any:
        if self._factory is not None:
            return self._factory(definition)
        return MCPClient(definition, log_dir=self.log_dir)

    async def status(self) -> list[dict[str, Any]]:
        """Configured servers plus the state of any live client."""
        rows: list[dict[str, Any]] = []
        for _, definition in sorted(self.registry.servers().items()):
            client = self._clients.get(definition.name)
            row = {
                "server": definition.name,
                "enabled": definition.enabled,
                "trust": definition.trust,
                "transport": definition.transport,
                "connected": bool(client is not None and getattr(client, "alive", False)),
            }
            if client is not None:
                row["client"] = client.to_dict() if hasattr(client, "to_dict") else {}
            rows.append(row)
        return rows

    async def close(self, name: str) -> None:
        await self._discard((name or "").strip().lower())

    async def close_all(self) -> None:
        for name in list(self._clients):
            await self._discard(name)


async def _safe_close(client: Any) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    try:
        await close()
    except Exception as exc:  # closing must never mask the real error
        log.debug("mcp_registry.close_failed", error=str(exc))


def iter_enabled(registry: MCPRegistry) -> Iterable[MCPServerDefinition]:
    """Convenience iterator (kept small on purpose; used by the CLI)."""
    return iter(registry.enabled())


__all__ = [
    "MCP_DIR_ENV",
    "DEFAULT_IDLE_TTL",
    "RISK_LEVELS",
    "NAME_PATTERN",
    "DEFAULT_DENY_PATTERNS",
    "default_mcp_dir",
    "parse_definition_text",
    "MCPServerDefinition",
    "MCPRegistry",
    "MCPServerPool",
    "iter_enabled",
]