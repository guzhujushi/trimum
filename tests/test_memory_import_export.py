"""Tests for `trm memory import` / `export` subcommands."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.mark.asyncio
async def test_export_empty_memory(tmp_path):
    """Export from an empty memory directory returns valid structure."""
    from trimum_core.cli.commands.memory import _memory_data

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    os.environ["TRIMUM_MEMORY_DIR"] = str(memory_dir)

    class Args:
        memory_command = "export"
        file = None

    data = await _memory_data(Args())
    os.environ.pop("TRIMUM_MEMORY_DIR", None)

    assert data["command"] == "export"
    assert data["status"] == "ok"
    export = data["data"]
    assert export["version"] == 1
    assert export["global_entries"] == {}
    assert export["agent_entries"] == {}


@pytest.mark.asyncio
async def test_export_with_entries(tmp_path):
    """Export captures global and agent entries."""
    from trimum_core.context_manager import ContextManager
    from trimum_core.memory_classifier import MemoryClassifier
    from trimum_core.cli.commands.memory import _memory_data

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    os.environ["TRIMUM_MEMORY_DIR"] = str(memory_dir)

    # Seed some data
    cm = ContextManager(str(memory_dir))
    clf = MemoryClassifier(str(memory_dir / "memory_classifier.db"), cm=cm)
    await cm.initialize()
    await clf.initialize()
    await cm.set_global("user_name", "Alice")
    await cm.set_global("locale", "zh-CN")
    await cm.initialize("test-agent")
    await cm.set("test-agent", "pref", "dark", namespace="agent_memory")
    await clf.add_category("general", "general", "test")
    await clf.index_memory("user_name", "general", "general", "test-agent")
    await cm.close()
    await clf.close()

    # Export to file
    out_file = tmp_path / "export.json"
    class Args:
        memory_command = "export"
        file = str(out_file)

    data = await _memory_data(Args())
    os.environ.pop("TRIMUM_MEMORY_DIR", None)

    assert data["status"] == "ok"
    assert data["global_entries"] == 2
    assert out_file.exists()

    with open(out_file, encoding="utf-8") as fh:
        export = json.load(fh)
    assert export["version"] == 1
    assert export["global_entries"]["user_name"] == "Alice"
    assert export["global_entries"]["locale"] == "zh-CN"
    assert export["agent_entries"]["test-agent"]["pref"] == "dark"
    assert len(export["categories"]) >= 1


@pytest.mark.asyncio
async def test_import_roundtrip(tmp_path):
    """Export then import into a fresh directory preserves data."""
    from trimum_core.context_manager import ContextManager
    from trimum_core.memory_classifier import MemoryClassifier
    from trimum_core.cli.commands.memory import _memory_data

    # Source memory
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    os.environ["TRIMUM_MEMORY_DIR"] = str(src_dir)

    cm = ContextManager(str(src_dir))
    clf = MemoryClassifier(str(src_dir / "memory_classifier.db"), cm=cm)
    await cm.initialize()
    await clf.initialize()
    await cm.set_global("key1", "value1")
    await cm.set_global("key2", "value2")
    await cm.initialize("agent-x")
    await cm.set("agent-x", "ak", "av", namespace="agent_memory")
    await clf.add_category("general", "general", "test")
    await clf.index_memory("key1", "general", "general", "agent-x")
    await cm.close()
    await clf.close()

    # Export
    export_file = tmp_path / "backup.json"
    class ExportArgs:
        memory_command = "export"
        file = str(export_file)

    await _memory_data(ExportArgs())
    os.environ.pop("TRIMUM_MEMORY_DIR", None)

    # Import into fresh directory
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    os.environ["TRIMUM_MEMORY_DIR"] = str(dst_dir)

    class ImportArgs:
        memory_command = "import"
        file = str(export_file)

    data = await _memory_data(ImportArgs())
    os.environ.pop("TRIMUM_MEMORY_DIR", None)

    assert data["status"] == "ok"
    assert data["imported"]["global"] == 2
    assert data["imported"]["agent_entries"] == 1

    # Verify imported data
    cm2 = ContextManager(str(dst_dir))
    await cm2.initialize()
    assert await cm2.get_global("key1") == "value1"
    assert await cm2.get_global("key2") == "value2"
    await cm2.initialize("agent-x")
    assert await cm2.get("agent-x", "ak", namespace="agent_memory") == "av"
    await cm2.close()


@pytest.mark.asyncio
async def test_import_bad_version(tmp_path):
    """Import rejects unsupported version."""
    from trimum_core.cli.commands.memory import _memory_data

    bad_file = tmp_path / "bad.json"
    bad_file.write_text('{"version": 99}')
    os.environ["TRIMUM_MEMORY_DIR"] = str(tmp_path / "mem")
    (tmp_path / "mem").mkdir()

    class Args:
        memory_command = "import"
        file = str(bad_file)

    data = await _memory_data(Args())
    os.environ.pop("TRIMUM_MEMORY_DIR", None)

    assert data["error"] is not None
    assert "version" in data["error"]