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
    """Test that file-based tools are discovered and executable."""

    def setup_method(self):
        self.registry = ToolRegistry()
        self.gateway = ToolGateway(policy_engine=PolicyEngine())

    def test_tools_dir_discovered(self):
        """All 11 tool directories should be discovered."""
        names = {t.name for t in self.registry.list_tools()}
        expected = {"shell", "file", "git", "http", "process", "system",
                    "env", "knowledge", "notification", "mcp", "custom"}
        for name in expected:
            assert name in names, f"Tool {name} not found in registry"
        print(f"All {len(expected)} tools discovered: {sorted(expected)}")

    def test_get_executor_exists(self):
        """Each tool should have a file-based executor (main.py)."""
        tool_names = ["shell", "file", "git", "http", "process", "system",
                      "env", "knowledge", "notification", "mcp", "custom"]
        for name in tool_names:
            executor = self.registry.get_executor(name)
            assert executor is not None, f"No executor for {name}"
            assert callable(executor), f"Executor for {name} not callable"
        print("All 11 tools have callable executors")

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
