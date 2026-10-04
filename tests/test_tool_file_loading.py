"""Integration tests: file-based tool loading and execution."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from trimum_core.tool_gateway import ToolRegistry, ToolGateway
from trimum_core.models import ExecuteRequest, ToolType, SourceType
from trimum_core.policy_engine import PolicyEngine


class TestToolFileLoading:
    """Test that file-based tools are discovered and executable.

    The registry is pointed at a self-contained tmp tool tree (shell + git)
    via ``TRIMUM_TOOLS_DIR`` so the file-based executors never depend on the
    host ``~/.trimum/tools`` layout.
    """

    @pytest.fixture(autouse=True)
    def _registry_with_tools(self, tmp_path, monkeypatch):
        tree = tmp_path / "tools"
        for name, dispatcher in (("shell", "ShellDispatcher"), ("git", "GitDispatcher")):
            d = tree / name
            d.mkdir(parents=True)
            (d / "tool.json5").write_text(
                f"""
                {{
                    name: "{name}",
                    description: "Fixture {name} tool",
                    kind: "{name}",
                    entry: "./main.py",
                    language: "python",
                    timeout: 30.0,
                    risk: "medium",
                    permissions: {{ filesystem: [], network: false }},
                    tools: []
                }}
                """,
                encoding="utf-8",
            )
            (d / "main.py").write_text(
                "from trimum_core.models import ExecuteRequest\n"
                f"from trimum_core.tool_dispatchers import {dispatcher}\n"
                "\n"
                "async def execute(request):\n"
                f"    return (await {dispatcher}().execute(ExecuteRequest(**request))).model_dump()\n",
                encoding="utf-8",
            )
        monkeypatch.setenv("TRIMUM_TOOLS_DIR", str(tree))
        self.registry = ToolRegistry()
        self.gateway = ToolGateway(policy_engine=PolicyEngine())

    def test_tools_dir_discovered(self):
        """All 11 built-in tool definitions are present; the file-based
        shell tool actually resolves an executor from the fixture tmp tree
        (not the host ``~/.trimum/tools``)."""
        names = {t.name for t in self.registry.list_tools()}
        expected = {"shell", "file", "git", "http", "process", "system",
                    "env", "knowledge", "notification", "mcp", "custom"}
        for name in expected:
            assert name in names, f"Tool {name} not found in registry"
        assert self.registry.get_executor("shell") is not None
        print(f"All {len(expected)} tools discovered: {sorted(expected)}")

    def test_get_executor_exists(self, tmp_path):
        """Every file-based tool must expose a callable executor.

        Uses a self-contained tool tree under ``tmp_path`` so the assertion
        never depends on the host ``~/.trimum/tools`` layout.
        """
        tools_root = tmp_path / "tools"
        for tool_name in ("fixture-a", "fixture-b"):
            tool_dir = tools_root / tool_name
            tool_dir.mkdir(parents=True)
            (tool_dir / "tool.json5").write_text(
                f"""
                {{
                    name: "{tool_name}",
                    description: "Fixture {tool_name}",
                    kind: "shell",
                    entry: "./main.py",
                    language: "python",
                    timeout: 30.0,
                    risk: "medium",
                    permissions: {{ filesystem: [], network: false }},
                    tools: []
                }}
                """,
                encoding="utf-8",
            )
            (tool_dir / "main.py").write_text(
                "async def execute(request):\n    return {'status': 'allowed'}\n",
                encoding="utf-8",
            )

        registry = ToolRegistry(str(tools_root))
        listed = {t.name for t in registry.list_tools()}
        assert {"fixture-a", "fixture-b"} <= listed, f"fixture tools not discovered: {sorted(listed)}"
        for name in ("fixture-a", "fixture-b"):
            executor = registry.get_executor(name)
            assert executor is not None, f"No executor for {name}"
            assert callable(executor), f"Executor for {name} not callable"
        print("Both fixture tools have callable executors: fixture-a, fixture-b")

    @pytest.mark.asyncio
    async def test_shell_executor(self):
        """shell tool main.py should return a valid ExecuteResponse."""
        executor = self.registry.get_executor("shell")
        assert executor is not None
        result = await executor(ExecuteRequest(
            tool=ToolType.SHELL,
            args=["echo", "hello_file_tool"],
            agent_id="test",
            source_type=SourceType.UNKNOWN,
        ).model_dump())
        assert result["status"] in ("allowed", "confirmed")
        print(f"Shell executor returned status={result['status']}, exit_code={result.get('exit_code')}")

    @pytest.mark.asyncio
    async def test_git_executor(self):
        """git tool main.py should return a valid ExecuteResponse."""
        executor = self.registry.get_executor("git")
        assert executor is not None
        result = await executor(ExecuteRequest(
            tool=ToolType.GIT,
            args=["--version"],
            agent_id="test",
            source_type=SourceType.UNKNOWN,
        ).model_dump())
        assert result["exit_code"] == 0
        print(f"Git executor returned: {result.get('output', '')[:100]}")

    @pytest.mark.asyncio
    async def test_gateway_file_execution_path(self):
        """ToolGateway.execute() should go through the file-based path."""
        result = await self.gateway.execute(ExecuteRequest(
            tool=ToolType.SHELL,
            args=["echo", "gateway_file_path_test"],
            agent_id="test",
            source_type=SourceType.UNKNOWN,
        ))
        assert result.exit_code == 0
        assert result.status in ("allowed", "confirmed")
        print(f"Gateway file path: status={result.status}, output={result.output.strip()}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
