"""Memory Classifier — 分支/分类记忆索引系统。

``MemoryClassifier`` 是独立于 ``ContextManager`` 的记忆分类层。
``ContextManager`` 负责原始 memory 数据的存储与检索，本模块则在其之上
维护 domain/category 分类索引，用于快速过滤和检索。

设计原则：

- 不修改 ``ContextManager`` 任何现有代码。
- 不在 ``ContextManager`` 中新增表，分类数据全部存放在独立数据库中。
- 分类数据库可以独立于 ``ContextManager`` 的数据库文件。
- 不导入 ``ContextManager``；若构造函数收到一个带 ``get`` 方法的对象，
  查询结果中的 ``value`` 会通过该对象按需读取。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

import aiosqlite

from .memory_schema import create_schema

__all__ = ["MemoryClassifier"]


class MemoryClassifier:
    """Async classification index over ContextManager memory entries.

    Usage::

        classifier = MemoryClassifier("classifier.db", cm=context_manager)
        await classifier.initialize()
        await classifier.add_category("code", "code.python")
        await classifier.index_memory("key-1", "code", "code.python", "agent-1")
        results = await classifier.query_by_category("code.python")
    """

    def __init__(self, db_path: str, cm: Any | None = None) -> None:
        """Initialise the classifier.

        Args:
            db_path: Path to the classification SQLite database.  It may be
                independent from ``ContextManager`` databases.
            cm: Optional memory source.  If provided and it has a ``get``
                method, query methods use it to resolve memory values.
        """
        self._db_path: Path = Path(db_path)
        self._cm: Any | None = cm
        self._conn: aiosqlite.Connection | None = None
        self._init_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the classifier tables and indexes if needed."""
        if self._conn is not None:
            return

        async with self._init_lock:
            if self._conn is not None:
                return

            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(str(self._db_path))
            conn.row_factory = aiosqlite.Row
            try:
                await create_schema(conn)
            except Exception:
                await conn.close()
                raise
            self._conn = conn

    async def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _get_conn(self) -> aiosqlite.Connection:
        """Return the SQLite connection, initialising it lazily if needed."""
        if self._conn is None:
            await self.initialize()
        assert self._conn is not None
        return self._conn

    # ------------------------------------------------------------------
    # Category management
    # ------------------------------------------------------------------

    async def add_category(
        self,
        domain: str,
        category: str,
        description: str = "",
    ) -> int:
        """Add a category and return its id.

        If the ``(domain, category)`` pair already exists, the existing id is
        returned and ``description`` is left unchanged.
        """
        conn = await self._get_conn()
        now = time.time()

        async with self._write_lock:
            await conn.execute(
                """
                INSERT INTO memory_categories (domain, category, description, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(domain, category) DO NOTHING
                """,
                (domain, category, description, now),
            )
            await conn.commit()

            cursor = await conn.execute(
                """
                SELECT id
                FROM memory_categories
                WHERE domain = ? AND category = ?
                """,
                (domain, category),
            )
            row = await cursor.fetchone()
            assert row is not None
            return int(row["id"])

    async def list_categories(self, domain: str | None = None) -> list[dict]:
        """List categories, optionally filtered by *domain*.

        Returns a list of dictionaries containing ``id``, ``domain``,
        ``category``, and ``description``.
        """
        conn = await self._get_conn()
        sql = (
            "SELECT id, domain, category, description "
            "FROM memory_categories"
        )
        params: tuple[Any, ...] = ()
        if domain is not None:
            sql += " WHERE domain = ?"
            params = (domain,)
        sql += " ORDER BY domain, category"

        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [
            {
                "id": int(row["id"]),
                "domain": row["domain"],
                "category": row["category"],
                "description": row["description"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Memory tagging
    # ------------------------------------------------------------------

    async def index_memory(
        self,
        memory_key: str,
        domain: str,
        category: str,
        agent_id: str | None = None,
    ) -> int:
        """Tag a memory entry with a category and return the index id.

        If the same ``(memory_key, domain, category, agent_id)`` index already
        exists, its timestamp is refreshed and the existing id is returned.
        """
        conn = await self._get_conn()
        now = time.time()

        async with self._write_lock:
            cursor = await conn.execute(
                """
                SELECT id
                FROM memory_index
                WHERE memory_key = ? AND domain = ? AND category = ?
                  AND agent_id IS ?
                """,
                (memory_key, domain, category, agent_id),
            )
            row = await cursor.fetchone()

            if row is None:
                cursor = await conn.execute(
                    """
                    INSERT INTO memory_index
                        (memory_key, domain, category, agent_id, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (memory_key, domain, category, agent_id, now),
                )
                await conn.commit()

                index_id = cursor.lastrowid
                if index_id is None:
                    cursor = await conn.execute(
                        """
                        SELECT id
                        FROM memory_index
                        WHERE memory_key = ? AND domain = ? AND category = ?
                          AND agent_id IS ?
                        """,
                        (memory_key, domain, category, agent_id),
                    )
                    row = await cursor.fetchone()
                    assert row is not None
                    index_id = row["id"]
                return int(index_id)

            index_id = int(row["id"])
            await conn.execute(
                "UPDATE memory_index SET created_at = ? WHERE id = ?",
                (now, index_id),
            )
            await conn.commit()
            return index_id

    async def remove_index(
        self,
        memory_key: str,
        agent_id: str | None = None,
        category: str | None = None,
    ) -> None:
        """Remove classification indexes for a memory entry.

        ``agent_id`` and ``category`` are optional filters.  A ``None`` value
        means that dimension is not filtered.
        """
        conn = await self._get_conn()
        clauses = ["memory_key = ?"]
        params: list[Any] = [memory_key]
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if category is not None:
            clauses.append("category = ?")
            params.append(category)

        sql = f"DELETE FROM memory_index WHERE {' AND '.join(clauses)}"
        async with self._write_lock:
            await conn.execute(sql, tuple(params))
            await conn.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def query_by_category(
        self,
        category: str,
        domain: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query indexed memories by category.

        Returns dictionaries containing ``memory_key``, ``domain``,
        ``category``, ``agent_id``, and ``value``.  ``value`` is ``None``
        unless a compatible ``cm`` was supplied.
        """
        if limit <= 0:
            return []

        conn = await self._get_conn()
        clauses = ["category = ?"]
        params: list[Any] = [category]
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)

        sql = (
            "SELECT memory_key, domain, category, agent_id "
            "FROM memory_index WHERE "
            + " AND ".join(clauses)
            + " ORDER BY id LIMIT ?"
        )
        params.append(limit)

        cursor = await conn.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        return [
            {
                "memory_key": row["memory_key"],
                "domain": row["domain"],
                "category": row["category"],
                "agent_id": row["agent_id"],
                "value": await self._resolve_value(row["memory_key"], row["agent_id"]),
            }
            for row in rows
        ]

    async def query_by_domain(
        self,
        domain: str,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query all indexed memories under a domain.

        The returned dictionaries have the same shape as
        :meth:`query_by_category`.
        """
        if limit <= 0:
            return []

        conn = await self._get_conn()
        clauses = ["domain = ?"]
        params: list[Any] = [domain]
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)

        sql = (
            "SELECT memory_key, domain, category, agent_id "
            "FROM memory_index WHERE "
            + " AND ".join(clauses)
            + " ORDER BY category, id LIMIT ?"
        )
        params.append(limit)

        cursor = await conn.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        return [
            {
                "memory_key": row["memory_key"],
                "domain": row["domain"],
                "category": row["category"],
                "agent_id": row["agent_id"],
                "value": await self._resolve_value(row["memory_key"], row["agent_id"]),
            }
            for row in rows
        ]

    async def get_memory_categories(
        self,
        memory_key: str,
        agent_id: str | None = None,
    ) -> list[dict]:
        """Return all category tags attached to a memory entry."""
        conn = await self._get_conn()
        clauses = ["memory_key = ?"]
        params: list[Any] = [memory_key]
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)

        sql = (
            "SELECT domain, category, agent_id "
            "FROM memory_index WHERE "
            + " AND ".join(clauses)
            + " ORDER BY domain, category, agent_id"
        )
        cursor = await conn.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        return [
            {
                "domain": row["domain"],
                "category": row["category"],
                "agent_id": row["agent_id"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def stats(self) -> dict:
        """Return category/index statistics."""
        conn = await self._get_conn()

        category_cursor = await conn.execute(
            "SELECT COUNT(*) AS total FROM memory_categories"
        )
        category_row = await category_cursor.fetchone()

        index_cursor = await conn.execute(
            "SELECT COUNT(*) AS total FROM memory_index"
        )
        index_row = await index_cursor.fetchone()

        group_cursor = await conn.execute(
            """
            SELECT domain, COUNT(*) AS count
            FROM memory_index
            GROUP BY domain
            ORDER BY domain
            """
        )
        group_rows = await group_cursor.fetchall()

        return {
            "total_categories": int(category_row["total"] if category_row else 0),
            "total_indexed": int(index_row["total"] if index_row else 0),
            "by_domain": {
                row["domain"]: int(row["count"])
                for row in group_rows
            },
        }

    # ------------------------------------------------------------------
    # Listener filter hook
    # ------------------------------------------------------------------

    def make_filter(
        self,
        domain: str | None = None,
        category: str | None = None,
    ) -> Callable[[Any], bool]:
        """Return a predicate for routing items by category.

        The returned function accepts a mapping or object carrying
        ``domain``/``category`` attributes (optionally inside ``payload``),
        and returns ``True`` only when both filters match.  ``None`` means no
        constraint for that dimension.
        """

        def matches(item: Any) -> bool:
            item_domain = self._read_field(item, "domain")
            item_category = self._read_field(item, "category")
            if domain is not None and item_domain != domain:
                return False
            if category is not None and item_category != category:
                return False
            return True

        return matches

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_value(
        self,
        memory_key: str,
        agent_id: str | None,
    ) -> Any:
        """Resolve a memory value through the optional ``cm`` object.

        This method deliberately avoids importing or depending on
        ``ContextManager``.  It only checks for a callable ``get`` method and,
        when the index has no agent owner, falls back to ``get_global`` if
        available.
        """
        cm = self._cm
        if cm is None:
            return None

        getter = getattr(cm, "get", None)
        if not callable(getter):
            return None

        try:
            if agent_id is None:
                get_global = getattr(cm, "get_global", None)
                if callable(get_global):
                    result = get_global(memory_key)
                else:
                    result = getter(memory_key)
            else:
                result = getter(agent_id, memory_key)
        except TypeError:
            # Support generic memory sources whose ``get`` accepts only a key.
            try:
                result = getter(memory_key)
            except Exception:
                return None
        except Exception:
            return None

        if inspect.isawaitable(result):
            try:
                return await result
            except Exception:
                return None
        return result

    @staticmethod
    def _read_field(item: Any, field: str) -> Any:
        """Read *field* from a mapping, object, or its ``payload``."""
        if isinstance(item, Mapping):
            if field in item:
                return item[field]
            payload = item.get("payload")
            if isinstance(payload, Mapping):
                return payload.get(field)
            return None

        value = getattr(item, field, None)
        if value is not None:
            return value

        payload = getattr(item, "payload", None)
        if isinstance(payload, Mapping):
            return payload.get(field)
        if payload is not None:
            return getattr(payload, field, None)
        return None
