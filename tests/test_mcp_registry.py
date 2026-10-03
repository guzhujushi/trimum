"""Tests for ``trimum_core.mcp_registry`` — definitions, narrowing rules, pool."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.mcp_client import MCPError  # noqa: E402
from trimum_core.mcp_registry import (  # noqa: E402
    DEFAULT_DENY_PATTERNS,
    MCP_DIR_ENV,
    MCPRegistry,
    MCPServerDefinition,
    MCPServerPool,
    default_mcp_dir,
    parse_definition_text,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"


def write_definition(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json5"
    path.write_text(body, encoding="utf-8")
    return path


def stdio_body(**overrides) -> str:
    """A valid definition file body (JSON is a subset of JSON5)."""
    data = {
        "name": "echo",
        "command": sys.executable,
        "args": [str(FIXTURE)],
        "enabled": True,
    }
    data.update(overrides)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_defaults_are_deny_by_default(self):
        item = MCPServerDefinition(name="fs", command="uvx")
        assert item.enabled is False  # 未显式开启就永不启动
        assert item.transport == "stdio"
        assert item.trust == "local"
        assert item.risk == "medium"
        assert item.timeout == 30.0
        assert item.idle_ttl == 300.0

    def test_name_is_lowercased_and_validated(self):
        assert MCPServerDefinition(name="FileSystem", command="x").name == "filesystem"
        for bad in ("", "with space", "-leading", "a" * 65, "we!rd"):
            with pytest.raises(Exception):
                MCPServerDefinition(name=bad, command="x")

    def test_risk_must_be_known(self):
        for good in ("low", "medium", "high"):
            assert MCPServerDefinition(name="s", command="x", risk=good).risk == good
        with pytest.raises(Exception):
            MCPServerDefinition(name="s", command="x", risk="catastrophic")

    def test_stdio_requires_command_and_http_requires_url(self):
        with pytest.raises(Exception):
            MCPServerDefinition(name="s", transport="stdio", command="")
        with pytest.raises(Exception):
            MCPServerDefinition(name="s", transport="http", url="")
        assert MCPServerDefinition(name="s", transport="http", url="http://x/mcp").url

    def test_args_and_env_are_coerced_to_strings(self):
        item = MCPServerDefinition(
            name="s", command="x", args=("a", 1), env={"TOKEN": 42}
        )
        assert item.args == ["a", "1"]
        assert item.env == {"TOKEN": "42"}

    def test_timeout_must_be_positive(self):
        with pytest.raises(Exception):
            MCPServerDefinition(name="s", command="x", timeout=0)


class TestCapabilityNarrowing:
    def test_local_server_allows_anything_without_rules(self):
        item = MCPServerDefinition(name="s", command="x")
        assert item.deny_patterns() == []
        assert item.allows_tool("delete_everything") is True

    def test_allow_list_is_exclusive(self):
        item = MCPServerDefinition(name="s", command="x", allow_tools=["read*", "list*"])
        assert item.allows_tool("read_file") is True
        assert item.allows_tool("list_dir") is True
        assert item.allows_tool("write_file") is False

    def test_deny_wins_over_allow(self):
        item = MCPServerDefinition(
            name="s", command="x", allow_tools=["read*"], deny_tools=["read_secret*"]
        )
        assert item.allows_tool("read_file") is True
        assert item.allows_tool("read_secret") is False

    def test_cloud_servers_inherit_default_deny_patterns(self):
        item = MCPServerDefinition(name="s", command="x", trust="cloud")
        assert set(DEFAULT_DENY_PATTERNS).issubset(set(item.deny_patterns()))
        assert item.allows_tool("delete_file") is False
        assert item.allows_tool("shell_exec") is False
        assert item.allows_tool("search") is True

    def test_empty_tool_name_is_denied(self):
        assert MCPServerDefinition(name="s", command="x").allows_tool("") is False

    def test_env_values_are_never_echoed(self):
        item = MCPServerDefinition(name="s", command="x", env={"API_KEY": "super-secret"})
        dumped = item.to_dict()
        assert dumped["env_keys"] == ["API_KEY"]
        assert "super-secret" not in str(dumped)


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_missing_directory_is_empty_not_an_error(self, tmp_path):
        registry = MCPRegistry(tmp_path / "nope")
        assert registry.servers() == {}
        described = registry.describe()
        assert described["exists"] is False and described["count"] == 0
        assert registry.problems == []

    def test_loads_json5_with_comments_and_name_from_filename(self, tmp_path):
        directory = tmp_path / "mcp"
        write_definition(
            directory,
            "fs",
            "{\n"
            "  // 只读文件系统服务器\n"
            '  command: "uvx",\n'
            '  args: ["mcp-server-filesystem", "/tmp"],\n'
            "  /* 默认不启用 */\n"
            "  enabled: true,\n"
            "}\n",
        )
        registry = MCPRegistry(directory)
        servers = registry.load()
        assert list(servers) == ["fs"]
        item = servers["fs"]
        assert item.name == "fs"
        assert item.args == ["mcp-server-filesystem", "/tmp"]
        assert str(item.path).endswith("fs.json5")
        assert registry.problems == []

    def test_enabled_filters_and_sorts(self, tmp_path):
        directory = tmp_path / "mcp"
        write_definition(directory, "zeta", '{command: "x", enabled: true}')
        write_definition(directory, "alpha", '{command: "x", enabled: false}')
        registry = MCPRegistry(directory)
        assert registry.names() == ["alpha", "zeta"]
        assert [item.name for item in registry.enabled()] == ["zeta"]

    def test_broken_files_become_problems(self, tmp_path):
        directory = tmp_path / "mcp"
        write_definition(directory, "good", '{command: "x"}')
        write_definition(directory, "broken", '{"command": ')
        write_definition(directory, "nocommand", '{"name": "nocommand", "transport": "stdio"}')
        write_definition(directory, "badrisk", '{"command": "x", "risk": "catastrophic"}')

        registry = MCPRegistry(directory)
        assert registry.names() == ["good"]
        errors = " ".join(problem["error"] for problem in registry.problems)
        assert "invalid json5" in errors
        assert "requires a command" in errors
        assert "risk must be one of" in errors
        assert len(registry.problems) == 3

    def test_duplicate_name_is_reported(self, tmp_path):
        directory = tmp_path / "mcp"
        write_definition(directory, "one", '{"name": "shared", "command": "x"}')
        write_definition(directory, "two", '{"name": "shared", "command": "y"}')
        registry = MCPRegistry(directory)
        assert registry.names() == ["shared"]
        assert "duplicate server name" in registry.problems[0]["error"]

    def test_describe_reports_state_and_problems(self, tmp_path):
        directory = tmp_path / "mcp"
        write_definition(directory, "echo", stdio_body())
        write_definition(directory, "bad", "not json at all")
        described = MCPRegistry(directory).describe()
        assert described["exists"] is True
        assert described["count"] == 1
        assert described["enabled"] == ["echo"]
        assert described["servers"][0]["env_keys"] == []
        assert described["problems"]

    def test_default_dir_honours_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MCP_DIR_ENV, str(tmp_path / "elsewhere"))
        assert default_mcp_dir() == tmp_path / "elsewhere"
        monkeypatch.delenv(MCP_DIR_ENV)
        assert default_mcp_dir().name == "mcp"

    def test_parse_definition_text_fallback_shape(self):
        assert parse_definition_text('{"a": 1}') == {"a": 1}
        assert parse_definition_text("{a: 1}") == {"a": 1}  # json5 语法


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------


class FakeClient:
    """Stand-in for ``MCPClient`` (no subprocess)."""

    def __init__(self, definition):
        self.definition = definition
        self.name = definition.name
        self.alive = False
        self.connects = 0
        self.closes = 0

    async def connect(self):
        self.connects += 1
        self.alive = True
        return {"serverInfo": {"name": self.name}}

    async def close(self):
        self.closes += 1
        self.alive = False

    def to_dict(self):
        return {"server": self.name, "alive": self.alive}


class TestPool:
    @staticmethod
    def pool(tmp_path, *, enabled=True, name="echo"):
        directory = tmp_path / "mcp"
        write_definition(directory, name, stdio_body(name=name, enabled=enabled))
        registry = MCPRegistry(directory)
        made: list[FakeClient] = []

        def factory(definition):
            client = FakeClient(definition)
            made.append(client)
            return client

        return MCPServerPool(registry, client_factory=factory), made

    @pytest.mark.asyncio
    async def test_client_starts_lazily_and_is_reused(self, tmp_path):
        pool, made = self.pool(tmp_path)
        assert made == []  # 构造 pool 不启动任何东西
        first = await pool.client("echo")
        second = await pool.client("echo")
        assert first is second
        assert first.connects == 1
        assert made == [first]

    @pytest.mark.asyncio
    async def test_unknown_and_disabled_servers_are_refused(self, tmp_path):
        pool, made = self.pool(tmp_path, enabled=False)
        with pytest.raises(MCPError) as unknown:
            await pool.client("nope")
        assert "not found" in str(unknown.value)
        with pytest.raises(MCPError) as disabled:
            await pool.client("echo")
        assert "disabled" in str(disabled.value)
        assert made == []

    @pytest.mark.asyncio
    async def test_broken_client_is_replaced(self, tmp_path):
        pool, made = self.pool(tmp_path)
        first = await pool.client("echo")
        first.alive = False  # 模拟流被打断
        second = await pool.client("echo")
        assert second is not first
        assert first.closes == 1
        assert second.connects == 1
        assert len(made) == 2

    @pytest.mark.asyncio
    async def test_refresh_forces_a_new_client(self, tmp_path):
        pool, made = self.pool(tmp_path)
        first = await pool.client("echo")
        second = await pool.client("echo", refresh=True)
        assert second is not first and first.closes == 1

    @pytest.mark.asyncio
    async def test_close_and_close_all(self, tmp_path):
        pool, _ = self.pool(tmp_path)
        client = await pool.client("echo")
        await pool.close("echo")
        assert client.closes == 1
        assert pool.clients == {}
        client2 = await pool.client("echo")
        await pool.close_all()
        assert client2.closes == 1 and pool.clients == {}

    @pytest.mark.asyncio
    async def test_status_reports_live_state(self, tmp_path):
        pool, _ = self.pool(tmp_path)
        before = await pool.status()
        assert before[0]["server"] == "echo" and before[0]["connected"] is False
        await pool.client("echo")
        after = await pool.status()
        assert after[0]["connected"] is True and after[0]["client"]["alive"] is True

    @pytest.mark.asyncio
    async def test_pool_with_the_real_fixture_server(self, tmp_path):
        directory = tmp_path / "mcp"
        write_definition(directory, "echo", stdio_body())
        pool = MCPServerPool(MCPRegistry(directory), log_dir=tmp_path / "logs")
        try:
            client = await pool.client("echo")
            tools = await client.list_tools()
            assert [tool.name for tool in tools][:2] == ["echo", "fail"]
            assert client.to_dict()["server_info"]["name"] == "echo"
        finally:
            await pool.close_all()