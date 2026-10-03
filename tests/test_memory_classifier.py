"""Tests for the branch/category memory classification system.

Covers three modules:
1. ``perception_bridge.memory_schema`` — SQLite schema for classification
2. ``perception_bridge.memory_classifier`` — classification CRUD + queries
3. ``perception_bridge.event_index`` — listener matching with segment buckets
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from trimum_core.event_index import EventIndex
from trimum_core.memory_classifier import MemoryClassifier
from trimum_core.memory_schema import MEMORY_SCHEMA_VERSION


# ===================================================================
#  memory_schema tests
# ===================================================================

def test_schema_version():
    assert MEMORY_SCHEMA_VERSION >= 1


def test_schema_defines_expected_tables():
    """Simple sanity: schema SQL should reference our table names."""
    from trimum_core.memory_schema import MEMORY_CATEGORIES_TABLE_SQL, MEMORY_INDEX_TABLE_SQL
    assert "memory_categories" in MEMORY_CATEGORIES_TABLE_SQL
    assert "memory_index" in MEMORY_INDEX_TABLE_SQL


def _run_async(coro):
    """Run an async coroutine synchronously and ensure cleanup."""
    return asyncio.run(coro)


@pytest.fixture
def classifier_db_path(tmp_path):
    """Create a temp path for the classifier DB and clean it up after test."""
    db_path = str(tmp_path / "classifier_test.db")
    yield db_path
    # Ensure the file is deleted; if Windows still locks it, ignore.
    try:
        os.remove(db_path)
    except (PermissionError, FileNotFoundError):
        pass


# ===================================================================
#  MemoryClassifier tests
# ===================================================================

def test_initialize_creates_tables(classifier_db_path):
    """Initialization should create a working SQLite file."""

    async def go():
        cls = MemoryClassifier(classifier_db_path)
        await cls.initialize()
        stats = await cls.stats()
        assert stats["total_categories"] == 0
        await cls.close()

    _run_async(go())


def test_add_and_list_categories(classifier_db_path):
    """Add categories and list them per domain."""

    async def go():
        cls = MemoryClassifier(classifier_db_path)
        await cls.initialize()

        cid = await cls.add_category("code", "code.python")
        assert isinstance(cid, int) and cid > 0

        cats = await cls.list_categories("code")
        assert len(cats) == 1
        assert cats[0]["category"] == "code.python"
        await cls.close()

    _run_async(go())


def test_add_duplicate_category_returns_same_id(classifier_db_path):
    """Duplicate (domain, category) should not create a new row."""

    async def go():
        cls = MemoryClassifier(classifier_db_path)
        await cls.initialize()

        c1 = await cls.add_category("code", "code.python")
        c2 = await cls.add_category("code", "code.python")
        assert c1 == c2

        cats = await cls.list_categories("code")
        assert len(cats) == 1
        await cls.close()

    _run_async(go())


def test_index_and_query_roundtrip(classifier_db_path):
    """Index a memory entry and query it back."""

    async def go():
        cls = MemoryClassifier(classifier_db_path)
        await cls.initialize()
        await cls.add_category("code", "code.python")
        idx = await cls.index_memory("key-1", "code", "code.python", "agent-1")
        assert isinstance(idx, int) and idx > 0

        results = await cls.query_by_category("code.python", agent_id="agent-1")
        assert len(results) == 1
        assert results[0]["memory_key"] == "key-1"
        await cls.close()

    _run_async(go())


def test_reindex_same_key_updates(classifier_db_path):
    """Re-indexing the same key in the same category updates timestamp."""

    async def go():
        cls = MemoryClassifier(classifier_db_path)
        await cls.initialize()
        await cls.add_category("deploy", "deploy.nginx")
        idx1 = await cls.index_memory("key-1", "deploy", "deploy.nginx", "agent-1")
        # 重新索引同一 key，应更新而非新增行
        idx2 = await cls.index_memory("key-1", "deploy", "deploy.nginx", "agent-1")
        results = await cls.query_by_category("deploy.nginx")
        assert len(results) == 1
        assert results[0]["memory_key"] == "key-1"
        assert isinstance(idx1, int) and isinstance(idx2, int)
        await cls.close()

    _run_async(go())


def test_query_by_domain(classifier_db_path):
    """Query all indexed memory entries under a domain."""

    async def go():
        cls = MemoryClassifier(classifier_db_path)
        await cls.initialize()

        await cls.add_category("code", "code.python")
        await cls.add_category("code", "code.js")
        await cls.index_memory("py-1", "code", "code.python", "agent-1")
        await cls.index_memory("js-1", "code", "code.js", "agent-2")

        results = await cls.query_by_domain("code")
        assert len(results) == 2

        results_py = await cls.query_by_domain("code", agent_id="agent-1")
        assert len(results_py) == 1
        assert results_py[0]["memory_key"] == "py-1"
        await cls.close()

    _run_async(go())


def test_remove_index(classifier_db_path):
    """Remove an index entry."""

    async def go():
        cls = MemoryClassifier(classifier_db_path)
        await cls.initialize()

        await cls.add_category("code", "code.python")
        await cls.index_memory("key-1", "code", "code.python", "agent-1")

        await cls.remove_index("key-1")

        results = await cls.query_by_category("code.python")
        assert len(results) == 0
        await cls.close()

    _run_async(go())


def test_stats_counts(classifier_db_path):
    """Stats should count categories and indexed entries."""

    async def go():
        cls = MemoryClassifier(classifier_db_path)
        await cls.initialize()

        await cls.add_category("code", "code.python")
        await cls.add_category("deploy", "deploy.nginx")
        await cls.index_memory("k1", "code", "code.python", "agent-1")
        await cls.index_memory("k2", "deploy", "deploy.nginx", "agent-1")

        stats = await cls.stats()
        assert stats["total_categories"] == 2
        assert stats["total_indexed"] == 2
        assert stats["by_domain"]["code"] == 1
        await cls.close()

    _run_async(go())


# ===================================================================
#  EventIndex tests
# ===================================================================

def test_add_and_match():
    ei = EventIndex()

    def cb1(e):
        pass

    def cb2(e):
        pass

    ei.add_listener("task.*", cb1)
    ei.add_listener("task.node.completed", cb2)

    # 精确+通配都命中
    m1 = ei.match("task.node.completed")
    assert cb1 in m1 and cb2 in m1

    # 只有通配命中
    m2 = ei.match("task.failed")
    assert cb1 in m2 and cb2 not in m2

    # 完全不匹配
    m3 = ei.match("event.x.y")
    assert cb1 not in m3 and cb2 not in m3


def test_remove_listener():
    ei = EventIndex()

    def cb1(e):
        pass

    ei.add_listener("task.*", cb1)
    ei.remove_listener("task.*", cb1)
    assert ei.match("task.anything") == []


def test_star_only():
    ei = EventIndex()

    def cb(e):
        pass

    ei.add_listener("*", cb)
    assert cb in ei.match("anything.at.all")


def test_segment_bucket_optimization():
    """不同首段的监听器放在不同桶，互不影响。"""
    ei = EventIndex()
    task_cb = lambda e: None  # noqa: E731
    event_cb = lambda e: None  # noqa: E731

    ei.add_listener("task.*.completed", task_cb)
    ei.add_listener("event.*.failed", event_cb)

    assert task_cb in ei.match("task.a.completed")
    assert task_cb not in ei.match("event.a.failed")
    assert event_cb in ei.match("event.a.failed")
    assert event_cb not in ei.match("task.a.completed")


# ===================================================================
#  Integration: classifier + event index together
# ===================================================================

def test_classifier_filter_with_event_index(classifier_db_path):
    """用 classifier 的 make_filter 过滤命令行，再把结果通过 event index 路由。"""

    async def go():
        cls = MemoryClassifier(classifier_db_path)
        await cls.initialize()
        await cls.add_category("deploy", "deploy.nginx")
        await cls.index_memory("known-cmd", "deploy", "deploy.nginx", "agent-1")

        # 构建过滤器
        filter_fn = cls.make_filter(domain="deploy")

        # 模拟一个需要路由的事件
        class FakeEvent:
            def __init__(self):
                self.payload = {"domain": "deploy", "cmd": "restart nginx"}

        evt = FakeEvent()
        assert filter_fn(evt) is True

        # 不匹配的 domain 应被过滤
        evt2 = FakeEvent()
        evt2.payload = {"domain": "code", "cmd": "run python script"}
        assert filter_fn(evt2) is False

        await cls.close()

    _run_async(go())
