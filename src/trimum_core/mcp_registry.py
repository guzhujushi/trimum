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
import contextlib
import json
import os
import re
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .logger import get_logger
from .mcp_client import (
    HTTP_TRANSPORTS,
    MCPClient,
    MCPError,
    MCPProtocolError,
)
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


def definitions_readable(directory: str | Path) -> bool:
    """``~/.trimum/mcp/`` 里的定义**列不列得出来**？

    清缓存前必须分清三种情况，它们看起来都是「一个 server 都没有」：

    * 目录存在、列得出来 → ``True``：照 ``names()`` 正常对账；
    * 目录**不存在** → ``True``：那就是「一个 server 都没配」。缓存里那些
      ``a__b`` 已经没有定义可指，留着只会变成调用必然失败的幽灵条目；
    * 目录在、却列不出来（权限 / IO）→ ``False``：「读不到」不等于「没有」，
      拿空名单去清缓存，等于因为一次 chmod 丢掉整份清单。

    缓存是派生数据、本来可重建，但重建要把每个 server 逐个拉起来列工具
    （`uvx` / `npx` 冷启动很贵），所以「不知道」时宁可不动作。
    """
    try:
        with os.scandir(directory) as entries:
            next(entries, None)
    except FileNotFoundError:
        return True
    except OSError as exc:
        log.debug(
            "mcp_registry.definitions_unreadable",
            directory=str(directory),
            error=str(exc),
        )
        return False
    return True


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
    transport: Literal["stdio", "http", "streamable-http", "streamable_http"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""
    url: str = ""
    #: Extra HTTP headers (auth tokens for ``trust: cloud`` servers).  Values are
    #: never echoed by ``to_dict()``, exactly like ``env``.
    headers: dict[str, str] = Field(default_factory=dict)
    trust: Literal["local", "cloud"] = "local"
    risk: str = "medium"
    timeout: float = 30.0
    idle_ttl: float = DEFAULT_IDLE_TTL
    #: cgroup caps for the stdio process (0 = keep the controller's default).
    max_memory_mb: float = 0.0
    max_cpu_percent: float = 0.0
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

    @field_validator("headers", mode="before")
    @classmethod
    def _coerce_headers(cls, value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, dict):
            return {str(key): str(item) for key, item in value.items()}
        raise ValueError("headers must be an object of string values")

    @model_validator(mode="after")
    def _check_transport_requirements(self) -> "MCPServerDefinition":
        if self.transport == "stdio" and not self.command.strip():
            raise ValueError("transport 'stdio' requires a command")
        if self.transport in HTTP_TRANSPORTS and not self.url.strip():
            raise ValueError(f"transport '{self.transport}' requires a url")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.idle_ttl < 0:
            raise ValueError("idle_ttl must not be negative (0 = never reap)")
        return self

    @property
    def limits(self) -> "ResourceLimits":
        """cgroup limits for this server (defaults kept when nothing is set)."""
        from .resource_controller import ResourceLimits

        limits = ResourceLimits()
        if self.max_memory_mb > 0:
            limits.max_memory_mb = float(self.max_memory_mb)
        if self.max_cpu_percent > 0:
            limits.max_cpu_percent = float(self.max_cpu_percent)
        return limits

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
            "header_keys": sorted(self.headers),
            "cwd": self.cwd,
            "url": self.url,
            "trust": self.trust,
            "risk": self.risk,
            "timeout": self.timeout,
            "idle_ttl": self.idle_ttl,
            "max_memory_mb": self.max_memory_mb,
            "max_cpu_percent": self.max_cpu_percent,
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
        self._fingerprint_seen: tuple[tuple[str, int, int], ...] = ()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> dict[str, MCPServerDefinition]:
        """(Re)read the directory; never raises, broken files become problems."""
        self._fingerprint_seen = self._fingerprint()
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

    def _fingerprint(self) -> tuple[tuple[str, int, int], ...]:
        """Directory fingerprint:每份定义的名字、mtime 与大小。"""
        try:
            entries: list[tuple[str, int, int]] = []
            for path in sorted(
                [*self.directory.glob("*.json5"), *self.directory.glob("*.json")]
            ):
                try:
                    stat = path.stat()
                    entries.append((path.name, stat.st_mtime_ns, stat.st_size))
                except OSError:
                    entries.append((path.name, 0, 0))
            return tuple(entries)
        except OSError:  # pragma: no cover - 目录消失等极端情况
            return ()

    def _ensure_fresh(self) -> None:
        """Re-read when the directory changed under us.

        daemon 会**长时间持有**同一个 registry，而 `~/.trimum/mcp/` 的承诺是
        「放一个文件就是全部安装步骤，不用重启任何东西」。只靠 `_loaded` 缓存
        的话，M4 之后新加的定义要等 daemon 重启才可见（真机验收时踩到：
        新增的 httpdemo.json5 一直报 not found）。
        """
        if not self._loaded or self._fingerprint() != self._fingerprint_seen:
            self.load()

    def servers(self) -> dict[str, MCPServerDefinition]:
        self._ensure_fresh()
        return dict(self._servers)

    def reload(self) -> dict[str, MCPServerDefinition]:
        return self.load()

    def get(self, name: str) -> MCPServerDefinition | None:
        key = (name or "").strip().lower()
        self._ensure_fresh()
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

    Three responsibilities deliberately live here instead of in the client:

    * **lazy start / self-heal** — a server is started on first use, and any client
      whose stream broke is dropped and rebuilt on the next call (a desynchronised
      stream cannot be reused safely);
    * **idle reaping** (M4) — a client untouched for its ``idle_ttl`` is closed, so
      a fleet of MCP servers does not stay resident forever;
    * **cgroup binding** (M4) — stdio children are handed to the same resource
      controller the child agents use.  Best effort by design: without root the
      controller cannot write ``/sys/fs/cgroup``, and that degrades to a recorded
      ``unavailable`` state rather than a failed call.

    ``client_factory``, ``cgroup`` and ``clock`` are injectable so tests can drive
    lifecycle without spawning processes or waiting wall-clock time.
    """

    def __init__(
        self,
        registry: MCPRegistry | None = None,
        *,
        client_factory: Callable[[MCPServerDefinition], Any] | None = None,
        log_dir: str | Path | None = None,
        cgroup: Any = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.registry = registry or MCPRegistry()
        self.log_dir = Path(log_dir) if log_dir is not None else None
        self._factory = client_factory
        self._cgroup = cgroup
        self._clock = clock or time.monotonic
        self._clients: dict[str, Any] = {}
        self._last_used: dict[str, float] = {}
        self._cgroup_state: dict[str, str] = {}
        self._reaper: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def clients(self) -> dict[str, Any]:
        return dict(self._clients)

    @property
    def cgroup_state(self) -> dict[str, str]:
        """Per-server cgroup outcome (``bound`` / ``unavailable`` / ``error``)."""
        return dict(self._cgroup_state)

    def idle_seconds(self, name: str) -> float | None:
        """Seconds since *name* was last used (None when it is not running)."""
        key = (name or "").strip().lower()
        if key not in self._clients:
            return None
        return round(self._clock() - self._last_used.get(key, self._clock()), 1)

    def _touch(self, name: str) -> None:
        self._last_used[name] = self._clock()

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
                    self._touch(definition.name)
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
            self._touch(definition.name)
            await self._bind_cgroup(definition, client)
            return client

    async def restart(self, name: str) -> bool:
        """Close and immediately reconnect one server (``trm mcp restart``)."""
        await self.client(name, refresh=True)
        return True

    async def _discard(self, name: str) -> None:
        client = self._clients.pop(name, None)
        self._last_used.pop(name, None)
        self._cgroup_state.pop(name, None)
        if client is not None:
            await _safe_close(client)

    def _make_client(self, definition: MCPServerDefinition) -> Any:
        if self._factory is not None:
            return self._factory(definition)
        return MCPClient(definition, log_dir=self.log_dir)

    # ------------------------------------------------------------------
    # cgroup binding (M4)
    # ------------------------------------------------------------------

    async def _bind_cgroup(self, definition: MCPServerDefinition, client: Any) -> None:
        """Put a freshly started stdio child under the resource controller."""
        pid = getattr(client, "pid", None)
        apply_cgroup = getattr(self._cgroup, "apply_cgroup", None)
        if self._cgroup is None or not pid or not callable(apply_cgroup):
            return

        agent_id = f"mcp-{definition.name}"
        pid = int(pid)
        try:
            await apply_cgroup(agent_id, pid, definition.limits)
        except Exception as exc:  # pragma: no cover - controller is defensive
            self._cgroup_state[definition.name] = f"error: {exc}"
            log.warning("mcp.cgroup_failed", server=definition.name, error=str(exc))
            return

        self._cgroup_state[definition.name] = await self._verify_cgroup(agent_id, pid)
        log.info(
            "mcp.cgroup_bound",
            server=definition.name,
            pid=pid,
            state=self._cgroup_state[definition.name],
        )

    async def _verify_cgroup(self, agent_id: str, pid: int) -> str:
        """Read the cgroup back: report what is *true*, not what was attempted.

        ``apply_cgroup`` swallows its own permission errors, so a controller that
        cannot write ``/sys/fs/cgroup`` would otherwise look successful.
        """
        reader = getattr(self._cgroup, "assigned_pids", None)
        if not callable(reader):
            return "applied (unverified)"
        try:
            pids = await reader(agent_id)
        except Exception:  # pragma: no cover - defensive
            return "applied (unverified)"
        if not pids:
            return "unavailable (not bound: needs root + cgroup v2 on Linux)"
        return "bound" if pid in pids else "applied (pid not listed)"

    # ------------------------------------------------------------------
    # Idle reaping (M4)
    # ------------------------------------------------------------------

    async def reap(self, now: float | None = None) -> list[str]:
        """Close clients idle longer than their ``idle_ttl``.

        ``idle_ttl <= 0`` means "never reap" — a server the user wants resident.
        A server whose definition disappeared from the registry is closed right
        away: it can no longer be reached, so ``idle_ttl`` is beside the point.
        """
        moment = self._clock() if now is None else float(now)
        reaped: list[str] = []
        for name in list(self._clients):
            definition = self.registry.get(name)
            if definition is None:
                # 定义被删掉或写坏了：这个 client 已经不可达（dispatcher 也查不到
                # 它），留着只会白占一个进程，别等 DEFAULT_IDLE_TTL 才收。
                await self._discard(name)
                reaped.append(name)
                continue
            ttl = float(getattr(definition, "idle_ttl", DEFAULT_IDLE_TTL) or 0.0)
            if ttl <= 0:
                continue
            if moment - self._last_used.get(name, moment) < ttl:
                continue
            await self._discard(name)
            reaped.append(name)

        if reaped:
            log.info("mcp.idle_reaped", servers=sorted(reaped))
        return reaped

    def start_reaper(self, *, interval: float = 30.0) -> asyncio.Task | None:
        """Start the background reaper (idempotent; returns the task).

        The interval is floored at 50 ms: a sub-millisecond sweep would spin the
        event loop for no benefit, while tests still need something fast.
        """
        if self._reaper is not None and not self._reaper.done():
            return self._reaper
        self._reaper = asyncio.create_task(
            self._reaper_loop(max(0.05, float(interval))), name="mcp-idle-reaper"
        )
        return self._reaper

    async def stop_reaper(self) -> None:
        """Cancel the background reaper (safe to call when it never started)."""
        task, self._reaper = self._reaper, None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _reaper_loop(self, interval: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.reap()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # a failed sweep must not kill the loop
                    log.warning("mcp.reaper_failed", error=str(exc))
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    async def status(self) -> list[dict[str, Any]]:
        """Configured servers plus the live state of any running client."""
        moment = self._clock()
        rows: list[dict[str, Any]] = []
        for _, definition in sorted(self.registry.servers().items()):
            client = self._clients.get(definition.name)
            connected = bool(client is not None and getattr(client, "alive", False))
            last = self._last_used.get(definition.name)
            row = {
                "server": definition.name,
                "enabled": definition.enabled,
                "trust": definition.trust,
                "transport": definition.transport,
                "url": definition.url,
                "connected": connected,
                "idle_ttl": definition.idle_ttl,
                "idle_seconds": (
                    round(moment - last, 1) if connected and last is not None else None
                ),
                "pid": getattr(client, "pid", None) if connected else None,
                "cgroup": self._cgroup_state.get(definition.name, ""),
            }
            if client is not None:
                row["client"] = client.to_dict() if hasattr(client, "to_dict") else {}
            rows.append(row)
        return rows

    async def close(self, name: str) -> None:
        await self._discard((name or "").strip().lower())

    async def close_all(self) -> None:
        await self.stop_reaper()
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
    "definitions_readable",
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