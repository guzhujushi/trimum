"""Memory Classifier SQLite schema.

This module defines the SQL schema for the branch/category memory index
system.  The schema is intentionally independent from ``ContextManager``:
all classifier data lives in its own database and its own tables.
"""

from __future__ import annotations

import aiosqlite

__all__ = [
    "MEMORY_SCHEMA_SQL",
    "MEMORY_SCHEMA_VERSION",
    "create_schema",
]

MEMORY_SCHEMA_VERSION: int = 1

MEMORY_CATEGORIES_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS memory_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain      TEXT NOT NULL,
    category    TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  REAL NOT NULL,
    UNIQUE(domain, category)
);
"""

MEMORY_INDEX_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS memory_index (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_key  TEXT NOT NULL,
    domain      TEXT NOT NULL,
    category    TEXT NOT NULL,
    agent_id    TEXT,
    created_at  REAL NOT NULL,
    UNIQUE(memory_key, domain, category, agent_id)
);
"""

MEMORY_INDEX_DOMAIN_IDX_SQL: str = """
CREATE INDEX IF NOT EXISTS idx_mem_idx_domain ON memory_index (domain);
"""

MEMORY_INDEX_CATEGORY_IDX_SQL: str = """
CREATE INDEX IF NOT EXISTS idx_mem_idx_cat ON memory_index (category);
"""

MEMORY_INDEX_AGENT_IDX_SQL: str = """
CREATE INDEX IF NOT EXISTS idx_mem_idx_agent ON memory_index (agent_id);
"""

MEMORY_SCHEMA_SQL: str = "\n".join(
    statement.strip()
    for statement in (
        MEMORY_CATEGORIES_TABLE_SQL,
        MEMORY_INDEX_TABLE_SQL,
        MEMORY_INDEX_DOMAIN_IDX_SQL,
        MEMORY_INDEX_CATEGORY_IDX_SQL,
        MEMORY_INDEX_AGENT_IDX_SQL,
    )
)


async def create_schema(conn: aiosqlite.Connection) -> None:
    """Create the classifier tables and indexes on *conn*.

    Args:
        conn: An open :class:`aiosqlite.Connection`.
    """
    await conn.executescript(MEMORY_SCHEMA_SQL)
    await conn.commit()
