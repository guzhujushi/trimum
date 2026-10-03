"""Context Manager — SQLite-persisted Agent context storage.

Provides ContextManager for storing/retrieving agent context data
and session tracking, using aiosqlite for async SQLite operations.

#20 — Each agent gets its own memory DB:

  {db_dir}/
  ├── global.db              # global_context + sessions
  ├── fts.db                 # FTS5 unified index (cross-agent search)
  ├── agents/
  │   └── {agent_id}/
  │       └── memory/
  │           └── agent.db   # context (agent_memory namespace only)
  └── projects/
      └── {project_id}.db    # project_ctx (shared)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from pydantic import BaseModel


class ContextEntry(BaseModel):
    """A single context entry with optional TTL expiry."""
    key: str
    value: Any
    namespace: str = "default"
    ttl_seconds: float | None = None  # None = permanent


class ContextManager:
    """Async SQLite-backed context & session manager for agents.

    Manages multiple SQLite files:
    - One ``agent.db`` per agent (private memory)
    - One DB per project (shared project context)
    - ``global.db`` (Planner long-term memory + session records)
    - ``fts.db`` (unified FTS5 index for cross-agent search)

    Usage::

        cm = ContextManager("/path/to/memory/dir")
        await cm.initialize("agent-1")
        await cm.set("agent-1", "my_key", {"nested": "data"}, ttl_seconds=3600)
        val = await cm.get("agent-1", "my_key")
        await cm.close()
    """

    def __init__(self, db_dir: str) -> None:
        self._db_dir = Path(db_dir)
        # Connection cache: key -> aiosqlite.Connection
        self._agent_conns: dict[str, aiosqlite.Connection] = {}
        self._project_conns: dict[str, aiosqlite.Connection] = {}
        self._global_conn: aiosqlite.Connection | None = None
        self._fts_conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _agent_db_path(self, agent_id: str) -> Path:
        return self._db_dir / "agents" / agent_id / "memory" / "agent.db"

    def _project_db_path(self, project_id: str) -> Path:
        return self._db_dir / "projects" / f"{project_id}.db"

    def _global_db_path(self) -> Path:
        return self._db_dir / "global.db"

    def _fts_db_path(self) -> Path:
        return self._db_dir / "fts.db"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self, agent_id: str | None = None) -> None:
        """Open **or ensure** DB connections and create tables.

        If *agent_id* is given, only initialise that agent's DB (lazy init).
        If *agent_id* is omitted, global + FTS connections are ensured.
        """
        # Global DB (always)
        if self._global_conn is None:
            self._global_conn = await self._connect_and_init_global()

        # FTS DB (always)
        if self._fts_conn is None:
            self._fts_conn = await self._connect_and_init_fts()

        # Agent-specific
        if agent_id is not None and agent_id not in self._agent_conns:
            db_path = self._agent_db_path(agent_id)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(str(db_path))
            conn.row_factory = aiosqlite.Row
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS context (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace      TEXT    NOT NULL,
                    key            TEXT    NOT NULL,
                    value          TEXT    NOT NULL,     -- JSON-encoded
                    created_at     REAL   NOT NULL,
                    expires_at     REAL   DEFAULT NULL,  -- NULL = never expires
                    UNIQUE(namespace, key)
                );
                """
            )
            await conn.commit()
            self._agent_conns[agent_id] = conn

    async def ensure_project_db(self, project_id: str) -> aiosqlite.Connection:
        """Lazy-init and return a project DB connection."""
        if project_id not in self._project_conns:
            db_path = self._project_db_path(project_id)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(str(db_path))
            conn.row_factory = aiosqlite.Row
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS context (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace      TEXT    NOT NULL DEFAULT 'project_ctx',
                    key            TEXT    NOT NULL,
                    value          TEXT    NOT NULL,
                    created_at     REAL   NOT NULL,
                    expires_at     REAL   DEFAULT NULL,
                    UNIQUE(namespace, key)
                );
                """
            )
            await conn.commit()
            self._project_conns[project_id] = conn
        return self._project_conns[project_id]

    async def close(self) -> None:
        """Close all database connections."""
        for conn in self._agent_conns.values():
            await conn.close()
        self._agent_conns.clear()

        for conn in self._project_conns.values():
            await conn.close()
        self._project_conns.clear()

        if self._global_conn is not None:
            await self._global_conn.close()
            self._global_conn = None

        if self._fts_conn is not None:
            await self._fts_conn.close()
            self._fts_conn = None

    # ------------------------------------------------------------------
    # Internal connection builders
    # ------------------------------------------------------------------

    async def _connect_and_init_global(self) -> aiosqlite.Connection:
        db_path = self._global_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS global_context (
                key            TEXT   PRIMARY KEY,
                value          TEXT   NOT NULL,
                updated_at     REAL   NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                agent_id       TEXT   PRIMARY KEY,
                type           TEXT   NOT NULL,
                created_at     REAL  NOT NULL,
                last_active    REAL  NOT NULL,
                metadata       TEXT   DEFAULT '{}'  -- JSON-encoded
            );
            """
        )
        await conn.commit()
        return conn

    async def _connect_and_init_fts(self) -> aiosqlite.Connection:
        db_path = self._fts_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        await conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS context_fts USING fts5(
                agent_id, project_id, namespace, key, value,
                tokenize="unicode61"
            );
            """
        )
        await conn.commit()
        return conn

    def _get_agent_conn(self, agent_id: str) -> aiosqlite.Connection:
        """Get or lazily open an agent DB connection."""
        if agent_id not in self._agent_conns:
            raise RuntimeError(
                f"Agent '{agent_id}' DB not initialised. "
                "Call cm.initialize(agent_id) first."
            )
        return self._agent_conns[agent_id]

    # ------------------------------------------------------------------
    # Context CRUD — Agent private memory
    # ------------------------------------------------------------------

    async def set(
        self,
        agent_id: str,
        key: str,
        value: Any,
        namespace: str = "default",
        ttl_seconds: float | None = None,
    ) -> None:
        """Store a value for *agent_id* under *namespace* / *key*.

        If *ttl_seconds* is provided, the entry will be considered expired
        that many seconds after creation (or last update).
        """
        conn = self._get_agent_conn(agent_id)
        now = time.time()
        expires_at: float | None = None
        if ttl_seconds is not None:
            expires_at = now + ttl_seconds

        await conn.execute(
            """
            INSERT INTO context (namespace, key, value, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(namespace, key) DO UPDATE SET
                value      = excluded.value,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            (namespace, key, json.dumps(value, ensure_ascii=False), now, expires_at),
        )
        await conn.commit()

        # Sync FTS5 index (shared fts.db)
        fts = self._fts_conn
        if fts is not None:
            try:
                await fts.execute(
                    "DELETE FROM context_fts WHERE agent_id = ? AND namespace = ? AND key = ?",
                    (agent_id, namespace, key),
                )
                await fts.execute(
                    "INSERT INTO context_fts (agent_id, project_id, namespace, key, value) VALUES (?, ?, ?, ?, ?)",
                    (agent_id, "", namespace, key, json.dumps(value, ensure_ascii=False)),
                )
                await fts.commit()
            except Exception:
                pass

    async def get(
        self,
        agent_id: str,
        key: str,
        namespace: str = "default",
    ) -> Any | None:
        """Retrieve a value, returning *None* if missing or expired."""
        conn = self._get_agent_conn(agent_id)
        row = await conn.execute(
            """
            SELECT value, expires_at
            FROM context
            WHERE namespace = ? AND key = ?
            """,
            (namespace, key),
        )
        row_data = await row.fetchone()
        if row_data is None:
            return None

        value_raw, expires_at = row_data["value"], row_data["expires_at"]
        # Expired check
        if expires_at is not None and time.time() > expires_at:
            await conn.execute(
                "DELETE FROM context WHERE namespace = ? AND key = ?",
                (namespace, key),
            )
            await conn.commit()
            return None

        return json.loads(value_raw)

    async def delete(
        self,
        agent_id: str,
        key: str,
        namespace: str = "default",
    ) -> None:
        """Delete a single context entry."""
        conn = self._get_agent_conn(agent_id)
        await conn.execute(
            "DELETE FROM context WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        await conn.commit()

        # Remove from FTS5 as well
        fts = self._fts_conn
        if fts is not None:
            try:
                await fts.execute(
                    "DELETE FROM context_fts WHERE agent_id = ? AND namespace = ? AND key = ?",
                    (agent_id, namespace, key),
                )
                await fts.commit()
            except Exception:
                pass

    async def list_namespace(
        self,
        agent_id: str,
        namespace: str,
    ) -> dict[str, Any]:
        """List all non-expired key-value pairs under *namespace*."""
        conn = self._get_agent_conn(agent_id)
        cursor = await conn.execute(
            """
            SELECT key, value, expires_at
            FROM context
            WHERE namespace = ?
            """,
            (namespace,),
        )
        now = time.time()
        result: dict[str, Any] = {}
        rows = await cursor.fetchall()
        to_delete: list[str] = []

        for row in rows:
            expires_at = row["expires_at"]
            if expires_at is not None and now > expires_at:
                to_delete.append(row["key"])
                continue
            result[row["key"]] = json.loads(row["value"])

        # Clean up expired entries in batch
        if to_delete:
            placeholders = ",".join("?" for _ in to_delete)
            await conn.execute(
                f"DELETE FROM context WHERE namespace = ? AND key IN ({placeholders})",
                (namespace, *to_delete),
            )
            await conn.commit()

        return result

    # ------------------------------------------------------------------
    # Project context (shared, requires confirmation to read)
    # ------------------------------------------------------------------

    _MEMORY_NAMESPACE = "agent_memory"   # private per-agent
    _PROJECT_NAMESPACE = "project_ctx"    # shared project context

    async def set_project_context(
        self,
        project_id: str,
        key: str,
        value: Any,
        ttl_seconds: float | None = None,
    ) -> None:
        """Store a project-level context entry."""
        conn = await self.ensure_project_db(project_id)
        now = time.time()
        expires_at: float | None = None
        if ttl_seconds is not None:
            expires_at = now + ttl_seconds

        await conn.execute(
            """
            INSERT INTO context (namespace, key, value, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(namespace, key) DO UPDATE SET
                value      = excluded.value,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            (self._PROJECT_NAMESPACE, key, json.dumps(value, ensure_ascii=False), now, expires_at),
        )
        await conn.commit()

        # Sync FTS5
        fts = self._fts_conn
        if fts is not None:
            try:
                await fts.execute(
                    "DELETE FROM context_fts WHERE project_id = ? AND namespace = ? AND key = ?",
                    (project_id, self._PROJECT_NAMESPACE, key),
                )
                await fts.execute(
                    "INSERT INTO context_fts (agent_id, project_id, namespace, key, value) VALUES (?, ?, ?, ?, ?)",
                    ("", project_id, self._PROJECT_NAMESPACE, key, json.dumps(value, ensure_ascii=False)),
                )
                await fts.commit()
            except Exception:
                pass

    async def get_project_context(
        self, project_id: str, key: str
    ) -> Any | None:
        """Retrieve a project-level context entry (requires confirmation)."""
        conn = await self.ensure_project_db(project_id)
        row = await conn.execute(
            "SELECT value, expires_at FROM context WHERE namespace = ? AND key = ?",
            (self._PROJECT_NAMESPACE, key),
        )
        row_data = await row.fetchone()
        if row_data is None:
            return None

        value_raw, expires_at = row_data["value"], row_data["expires_at"]
        if expires_at is not None and time.time() > expires_at:
            await conn.execute(
                "DELETE FROM context WHERE namespace = ? AND key = ?",
                (self._PROJECT_NAMESPACE, key),
            )
            await conn.commit()
            return None

        return json.loads(value_raw)

    async def list_project_context(
        self, project_id: str
    ) -> dict[str, Any]:
        """List all project context entries."""
        conn = await self.ensure_project_db(project_id)
        cursor = await conn.execute(
            "SELECT key, value, expires_at FROM context WHERE namespace = ?",
            (self._PROJECT_NAMESPACE,),
        )
        now = time.time()
        result: dict[str, Any] = {}
        rows = await cursor.fetchall()
        to_delete: list[str] = []

        for row in rows:
            expires_at = row["expires_at"]
            if expires_at is not None and now > expires_at:
                to_delete.append(row["key"])
                continue
            result[row["key"]] = json.loads(row["value"])

        if to_delete:
            placeholders = ",".join("?" for _ in to_delete)
            await conn.execute(
                f"DELETE FROM context WHERE namespace = ? AND key IN ({placeholders})",
                (self._PROJECT_NAMESPACE, *to_delete),
            )
            await conn.commit()

        return result

    async def requires_confirmation(self, agent_id: str, key: str) -> bool:
        """Check if reading a context entry should prompt the user.

        Rule: reading shared/project context owned by *other* agents
        or the global project namespace requires confirmation.
        Reading one's own agent_memory does NOT.
        """
        # Agent's own private memory: no confirmation needed
        if key.startswith("agent_memory.") or key == "agent_memory":
            return False
        # Shared project context: always confirm
        if key.startswith("project_ctx.") or key == "project_ctx":
            return True
        # Cross-agent read: confirm
        return True

    def confirm_read(
        self, agent_id: str, key: str, namespace: str = "default"
    ) -> None:
        """Signal that the user has confirmed a context read.

        This is a no-op placeholder; the actual confirmation flow is
        handled by the caller (e.g. a UI prompt). Marking it here
        for audit trail in future implementations.
        """
        pass

    async def clear_agent(self, agent_id: str) -> None:
        """Delete **all** context entries for *agent_id* (every namespace)."""
        conn = self._get_agent_conn(agent_id)
        await conn.execute("DELETE FROM context")
        await conn.commit()

        # Also clear from FTS5
        fts = self._fts_conn
        if fts is not None:
            try:
                await fts.execute(
                    "DELETE FROM context_fts WHERE agent_id = ?",
                    (agent_id,),
                )
                await fts.commit()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Global context (Planner long-term memory)
    # ------------------------------------------------------------------

    async def set_global(
        self,
        key: str,
        value: Any,
    ) -> None:
        """Store a global context entry."""
        conn = self._global_conn
        if conn is None:
            conn = await self._connect_and_init_global()
            self._global_conn = conn
        now = time.time()
        await conn.execute(
            """
            INSERT INTO global_context (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), now),
        )
        await conn.commit()

        # Sync FTS5
        fts = self._fts_conn
        if fts is not None:
            try:
                await fts.execute(
                    "DELETE FROM context_fts WHERE agent_id = ? AND namespace = ? AND key = ?",
                    ("__global__", "global_ctx", key),
                )
                await fts.execute(
                    "INSERT INTO context_fts (agent_id, project_id, namespace, key, value) VALUES (?, ?, ?, ?, ?)",
                    ("__global__", "", "global_ctx", key, json.dumps(value, ensure_ascii=False)),
                )
                await fts.commit()
            except Exception:
                pass

    async def get_global(self, key: str) -> Any | None:
        """Retrieve a global context entry."""
        conn = self._global_conn
        if conn is None:
            return None
        row = await conn.execute(
            "SELECT value FROM global_context WHERE key = ?",
            (key,),
        )
        row_data = await row.fetchone()
        if row_data is None:
            return None
        return json.loads(row_data["value"])

    async def list_global(self) -> dict[str, Any]:
        """List all global context entries."""
        conn = self._global_conn
        if conn is None:
            return {}
        cursor = await conn.execute(
            "SELECT key, value FROM global_context"
        )
        result: dict[str, Any] = {}
        rows = await cursor.fetchall()
        for row in rows:
            result[row["key"]] = json.loads(row["value"])
        return result

    async def delete_global(self, key: str) -> None:
        """Delete a global context entry."""
        conn = self._global_conn
        if conn is None:
            return
        await conn.execute(
            "DELETE FROM global_context WHERE key = ?",
            (key,),
        )
        await conn.commit()

        # Also remove from FTS5
        fts = self._fts_conn
        if fts is not None:
            try:
                await fts.execute(
                    "DELETE FROM context_fts WHERE agent_id = ? AND namespace = ? AND key = ?",
                    ("__global__", "global_ctx", key),
                )
                await fts.commit()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Session management (global.db `sessions` table)
    # ------------------------------------------------------------------

    async def register_session(
        self,
        agent_id: str,
        session_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a session for *agent_id* in global DB."""
        conn = self._global_conn
        if conn is None:
            conn = await self._connect_and_init_global()
            self._global_conn = conn
        now = time.time()
        await conn.execute(
            """
            INSERT INTO sessions (agent_id, type, created_at, last_active, metadata)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                type        = excluded.type,
                last_active = excluded.last_active,
                metadata    = excluded.metadata
            """,
            (agent_id, session_type, now, now, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        await conn.commit()

    async def get_session(self, agent_id: str) -> dict[str, Any] | None:
        """Get session info for *agent_id* from global DB."""
        conn = self._global_conn
        if conn is None:
            return None
        row = await conn.execute(
            "SELECT type, created_at, last_active, metadata FROM sessions WHERE agent_id = ?",
            (agent_id,),
        )
        row_data = await row.fetchone()
        if row_data is None:
            return None
        return {
            "type": row_data["type"],
            "created_at": row_data["created_at"],
            "last_active": row_data["last_active"],
            "metadata": json.loads(row_data["metadata"]),
        }

    async def update_session(self, agent_id: str, metadata_updates: dict[str, Any]) -> None:
        """Update session metadata (merge) and touch last_active."""
        conn = self._global_conn
        if conn is None:
            return
        row = await conn.execute(
            "SELECT metadata FROM sessions WHERE agent_id = ?",
            (agent_id,),
        )
        row_data = await row.fetchone()
        if row_data is None:
            return
        existing = json.loads(row_data["metadata"])
        existing.update(metadata_updates)
        now = time.time()
        await conn.execute(
            "UPDATE sessions SET metadata = ?, last_active = ? WHERE agent_id = ?",
            (json.dumps(existing, ensure_ascii=False), now, agent_id),
        )
        await conn.commit()

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all active sessions."""
        conn = self._global_conn
        if conn is None:
            return []
        cursor = await conn.execute(
            "SELECT agent_id, type, created_at, last_active, metadata FROM sessions"
        )
        results: list[dict[str, Any]] = []
        rows = await cursor.fetchall()
        for row in rows:
            results.append({
                "agent_id": row["agent_id"],
                "type": row["type"],
                "created_at": row["created_at"],
                "last_active": row["last_active"],
                "metadata": json.loads(row["metadata"]),
            })
        return results

    # ------------------------------------------------------------------
    # Cross-agent search via FTS5
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 20,
        namespace_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text search across all indexed context entries.

        Uses FTS5 on ``context_fts`` virtual table.

        Args:
            query: FTS5 query string (uses unicode61 tokenizer).
            limit: Maximum number of results.
            namespace_filter: Optional namespace restriction.

        Returns:
            List of dicts with keys: agent_id, project_id, namespace, key, value.
        """
        fts = self._fts_conn
        if fts is None:
            return []

        if namespace_filter:
            sql = """
                SELECT agent_id, project_id, namespace, key, value
                FROM context_fts
                WHERE context_fts MATCH ?
                  AND namespace = ?
                LIMIT ?
            """
            params = (query, namespace_filter, limit)
        else:
            sql = """
                SELECT agent_id, project_id, namespace, key, value
                FROM context_fts
                WHERE context_fts MATCH ?
                LIMIT ?
            """
            params = (query, limit)

        results: list[dict[str, Any]] = []
        try:
            cursor = await fts.execute(sql, params)
            rows = await cursor.fetchall()
            for row in rows:
                try:
                    val = json.loads(row["value"])
                except (json.JSONDecodeError, TypeError):
                    val = row["value"]
                results.append({
                    "agent_id": row["agent_id"],
                    "project_id": row["project_id"],
                    "namespace": row["namespace"],
                    "key": row["key"],
                    "value": val,
                })
        except Exception:
            pass

        return results