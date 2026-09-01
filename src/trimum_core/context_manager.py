"""Context Manager — SQLite-persisted Agent context storage.

Provides ContextManager for storing/retrieving agent context data
and session tracking, using aiosqlite for async SQLite operations.
"""

from __future__ import annotations

import json
import time
from typing import Any

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

    Usage::

        cm = ContextManager("path/to/db.sqlite")
        await cm.initialize()
        await cm.set("agent-1", "my_key", {"nested": "data"}, ttl_seconds=3600)
        val = await cm.get("agent-1", "my_key")
        await cm.close()
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open db connection and create tables if they don't exist."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row

        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS context (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id       TEXT    NOT NULL,
                namespace      TEXT    NOT NULL,
                key            TEXT    NOT NULL,
                value          TEXT    NOT NULL,     -- JSON-encoded
                created_at     REAL   NOT NULL,
                expires_at     REAL   DEFAULT NULL,  -- NULL = never expires
                UNIQUE(agent_id, namespace, key)
            );

            CREATE TABLE IF NOT EXISTS global_context (
                key            TEXT   PRIMARY KEY,
                value          TEXT   NOT NULL,
                updated_at     REAL   NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS context_fts USING fts5(
                agent_id, namespace, key, value,
                tokenize="unicode61"
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
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Context CRUD
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
        now = time.time()
        expires_at: float | None = None
        if ttl_seconds is not None:
            expires_at = now + ttl_seconds

        await self._conn.execute(
            """
            INSERT INTO context (agent_id, namespace, key, value, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, namespace, key) DO UPDATE SET
                value      = excluded.value,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            (agent_id, namespace, key, json.dumps(value, ensure_ascii=False), now, expires_at),
        )
        await self._conn.commit()

    async def get(
        self,
        agent_id: str,
        key: str,
        namespace: str = "default",
    ) -> Any | None:
        """Retrieve a value, returning *None* if missing or expired."""
        row = await self._conn.execute(
            """
            SELECT value, expires_at
            FROM context
            WHERE agent_id = ? AND namespace = ? AND key = ?
            """,
            (agent_id, namespace, key),
        )
        row_data = await row.fetchone()
        if row_data is None:
            return None

        value_raw, expires_at = row_data["value"], row_data["expires_at"]
        # Expired check
        if expires_at is not None and time.time() > expires_at:
            await self._conn.execute(
                "DELETE FROM context WHERE agent_id = ? AND namespace = ? AND key = ?",
                (agent_id, namespace, key),
            )
            await self._conn.commit()
            return None

        return json.loads(value_raw)

    async def delete(
        self,
        agent_id: str,
        key: str,
        namespace: str = "default",
    ) -> None:
        """Delete a single context entry."""
        await self._conn.execute(
            "DELETE FROM context WHERE agent_id = ? AND namespace = ? AND key = ?",
            (agent_id, namespace, key),
        )
        await self._conn.commit()

    async def list_namespace(
        self,
        agent_id: str,
        namespace: str,
    ) -> dict[str, Any]:
        """List all non-expired key-value pairs under *namespace*."""
        cursor = await self._conn.execute(
            """
            SELECT key, value, expires_at
            FROM context
            WHERE agent_id = ? AND namespace = ?
            """,
            (agent_id, namespace),
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
            await self._conn.execute(
                f"DELETE FROM context WHERE agent_id = ? AND namespace = ? AND key IN ({placeholders})",
                (agent_id, namespace, *to_delete),
            )
            await self._conn.commit()

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
        """Store a project-level context entry.

        Uses agent_id = f"project:{project_id}" to namespace project data.
        """
        await self.set(
            agent_id=f"project:{project_id}",
            key=key,
            value=value,
            namespace=self._PROJECT_NAMESPACE,
            ttl_seconds=ttl_seconds,
        )

    async def get_project_context(
        self, project_id: str, key: str
    ) -> Any | None:
        """Retrieve a project-level context entry (requires confirmation)."""
        return await self.get(
            agent_id=f"project:{project_id}",
            key=key,
            namespace=self._PROJECT_NAMESPACE,
        )

    async def list_project_context(
        self, project_id: str
    ) -> dict[str, Any]:
        """List all project context entries."""
        return await self.list_namespace(
            agent_id=f"project:{project_id}",
            namespace=self._PROJECT_NAMESPACE,
        )

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
        await self._conn.execute(
            "DELETE FROM context WHERE agent_id = ?",
            (agent_id,),
        )
        await self._conn.execute(
            "DELETE FROM context_fts WHERE agent_id = ?",
            (agent_id,),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def register_session(
        self,
        agent_id: str,
        agent_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register (or upsert) a session record for *agent_id*."""
        now = time.time()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        await self._conn.execute(
            """
            INSERT INTO sessions (agent_id, type, created_at, last_active, metadata)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                type        = excluded.type,
                last_active = excluded.last_active,
                metadata    = excluded.metadata
            """,
            (agent_id, agent_type, now, now, meta_json),
        )
        await self._conn.commit()

    async def update_session(
        self,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update *last_active* timestamp and optionally merge *metadata*.

        If *metadata* is provided, the existing metadata dict is shallow-merged
        (new keys overwrite old ones).
        """
        now = time.time()

        if metadata is not None:
            # Read existing metadata, merge, then write back
            existing = await self._get_session_metadata(agent_id)
            existing.update(metadata)
            meta_json = json.dumps(existing, ensure_ascii=False)
            await self._conn.execute(
                "UPDATE sessions SET last_active = ?, metadata = ? WHERE agent_id = ?",
                (now, meta_json, agent_id),
            )
        else:
            await self._conn.execute(
                "UPDATE sessions SET last_active = ? WHERE agent_id = ?",
                (now, agent_id),
            )
        await self._conn.commit()

    async def get_session(self, agent_id: str) -> dict[str, Any] | None:
        """Get session info for *agent_id*, or *None* if not registered."""
        cursor = await self._conn.execute(
            "SELECT * FROM sessions WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        return {
            "agent_id":   row["agent_id"],
            "type":       row["type"],
            "created_at": row["created_at"],
            "last_active": row["last_active"],
            "metadata":   json.loads(row["metadata"]),
        }

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions active within the last 24 hours."""
        cutoff = time.time() - 86400  # 24 hours
        cursor = await self._conn.execute(
            "SELECT * FROM sessions WHERE last_active >= ?",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "agent_id":   row["agent_id"],
                "type":       row["type"],
                "created_at": row["created_at"],
                "last_active": row["last_active"],
                "metadata":   json.loads(row["metadata"]),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # FTS5 Full-text search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search across all context entries.

        Uses FTS5 with unicode61 tokenizer.
        Supports standard FTS5 query syntax (AND, OR, NOT, phrases).
        Returns list of {agent_id, namespace, key, value, rank}.
        """
        try:
            cursor = await self._conn.execute(
                """SELECT c.agent_id, c.namespace, c.key, c.value, fts.rank
                FROM context_fts fts
                JOIN context c ON c.agent_id = fts.agent_id
                    AND c.namespace = fts.namespace
                    AND c.key = fts.key
                WHERE context_fts MATCH ?
                ORDER BY rank
                LIMIT ?""",
                (query, limit),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "agent_id": r["agent_id"],
                    "namespace": r["namespace"],
                    "key": r["key"],
                    "value": json.loads(r["value"]),
                    "rank": r[4],
                }
                for r in rows
            ] if rows else []
        except Exception:
            return []

    async def search_by_namespace(
        self,
        query: str,
        namespace: str,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search scoped to a specific namespace."""
        return await self.search(f"namespace:\"{namespace}\" AND ({query})", limit=limit)

    # ------------------------------------------------------------------
    # Global context (Planner long-term / 总上下文)
    # ------------------------------------------------------------------

    async def set_global(
        self,
        key: str,
        value: Any,
    ) -> None:
        """Store a global context entry (Planner long-term / 总上下文)."""
        await self._conn.execute(
            """INSERT INTO global_context (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at""",
            (key, json.dumps(value, ensure_ascii=False), time.time()),
        )
        await self._conn.commit()

    async def get_global(self, key: str) -> Any | None:
        """Retrieve a global context entry."""
        cursor = await self._conn.execute(
            "SELECT value FROM global_context WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    async def list_global(self) -> dict[str, Any]:
        """List all global context entries."""
        cursor = await self._conn.execute(
            "SELECT key, value FROM global_context",
        )
        rows = await cursor.fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    async def delete_global(self, key: str) -> None:
        """Delete a global context entry."""
        await self._conn.execute(
            "DELETE FROM global_context WHERE key = ?",
            (key,),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_session_metadata(self, agent_id: str) -> dict[str, Any]:
        """Read the existing metadata dict for *agent_id* (internal)."""
        cursor = await self._conn.execute(
            "SELECT metadata FROM sessions WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return {}
        return json.loads(row["metadata"])
