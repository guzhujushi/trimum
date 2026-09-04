"""#22: AgentManifest depends_on + AgentRegistry.check_dependencies 测试。"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

from trimum_core.models import AgentManifest, AgentPermissions, AgentEvents, RiskLevel


def _make_manifest(name: str, depends_on: list[str] | None = None) -> AgentManifest:
    return AgentManifest(
        name=name,
        version="1",
        description="test agent",
        capabilities=["test"],
        depends_on=depends_on or [],
        entry="",
        permissions=AgentPermissions(exec=[], deny_exec=[], read=[], write=[]),
        events=AgentEvents(),
    )


class TestAgentManifestDependsOn:
    """depends_on 字段测试."""

    def test_depends_on_default_empty(self):
        m = _make_manifest("test")
        assert m.depends_on == []

    def test_depends_on_custom(self):
        m = _make_manifest("test", ["git", "curl"])
        assert m.depends_on == ["git", "curl"]

    def test_depends_on_serialization(self):
        m = _make_manifest("test", ["python", "node"])
        data = m.model_dump()
        assert data["depends_on"] == ["python", "node"]

    def test_manifest_repr(self):
        m = _make_manifest("test", ["git"])
        r = repr(m)
        assert "depends_on" in r
        assert "git" in r


class TestAgentRegistryCheckDependencies:
    """AgentRegistry.check_dependencies 测试."""

    def test_no_deps_returns_empty(self):
        from trimum_core.agent_registry import AgentRegistry
        reg = AgentRegistry()
        m = _make_manifest("test-no-deps")
        missing = reg.check_dependencies(m)
        assert missing == []

    def test_existing_dep_returns_empty(self):
        from trimum_core.agent_registry import AgentRegistry
        reg = AgentRegistry()
        # python 一定在 PATH 中
        m = _make_manifest("test", ["python"])
        if os.name == "nt":
            m = _make_manifest("test", ["python.exe"])
        missing = reg.check_dependencies(m)
        assert missing == [], f"Missing: {missing}"

    @pytest.mark.skipif(os.name == "nt", reason="Unix-specific executable name")
    def test_nonexistent_dep_returns_name(self):
        from trimum_core.agent_registry import AgentRegistry
        reg = AgentRegistry()
        m = _make_manifest("test", ["this_exe_should_not_exist_xyzabc"])
        missing = reg.check_dependencies(m)
        assert "this_exe_should_not_exist_xyzabc" in missing

    def test_multiple_missing(self):
        from trimum_core.agent_registry import AgentRegistry
        reg = AgentRegistry()
        m = _make_manifest("test", [
            "xyz_not_exist_1",
            "xyz_not_exist_2",
        ])
        missing = reg.check_dependencies(m)
        assert len(missing) == 2

    def test_mixed_existing_and_missing(self):
        from trimum_core.agent_registry import AgentRegistry
        reg = AgentRegistry()
        # git 应该存在
        m = _make_manifest("test", ["git", "xyz_not_exist_3"])
        missing = reg.check_dependencies(m)
        assert "xyz_not_exist_3" in missing
        assert "git" not in missing

    def test_register_does_not_fail_on_missing_deps(self):
        from trimum_core.agent_registry import AgentRegistry
        reg = AgentRegistry()
        m = _make_manifest("test-ok", ["xyz_not_exist_4"])
        # register 应该不抛出异常
        reg.register(m)
        assert any(a.name == m.name for a in reg.list_agents())
