"""Tests for the MCP → ToolRegistry bridge (``mcp_bridge.py``, M4.5).

Remote tools are aggregated into the registry as ``<server>__<tool>`` so an
agent reads one list instead of two.  The constraint that shapes every test
here: aggregating must not undo M4's lazy start / idle reaping, so the bridge
only ever reads a *cache* that a successful ``mcp.tools.list`` leaves behind.
Nothing below starts a server except the dispatcher calls that mean to.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import mcp_bridge  # noqa: E402
from trimum_core.api_server import (  # noqa: E402
    build_mcp_tool_index,
    prune_mcp_index,
    wire_mcp_index,
)
from trimum_core.cli import main  # noqa: E402
from trimum_core.mcp_bridge import MCPToolIndex, flat_name, split_name  # noqa: E402
from trimum_core.mcp_registry import (  # noqa: E402
    MCP_DIR_ENV,
    MCPServerDefinition,
    MCPServerPool,
    MCPRegistry,
    definitions_readable,
)
from trimum_core.models import (  # noqa: E402
    ExecuteRequest,
    RiskLevel,
    ToolDefinition,
    ToolType,
)
from trimum_core.tool_dispatchers import MCPDispatcher  # noqa: E402
from trimum_core.tool_gateway import ToolRegistry  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"

#: What the echo fixture answers to ``tools/list``, trimmed to the fields the
#: bridge keeps (name / description / input_schema).
ECHO_TOOLS = [
    {
        "name": "echo",
        "description": "Return the text you send",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    {
        "name": "fail",
        "description": "Always answers with isError",
        "input_schema": {"type": "object"},
    },
]


def definition(name: str = "echo", **overrides) -> MCPServerDefinition:
    data = {
        "name": name,
        "command": sys.executable,
        "args": [str(FIXTURE)],
        "enabled": True,
        "timeout": 10.0,
    }
    data.update(overrides)
    return MCPServerDefinition(**data)


def write_server(directory: Path, name: str = "echo", **overrides) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "command": sys.executable,
        "args": [str(FIXTURE)],
        "enabled": True,
        "timeout": 10.0,
    }
    data.update(overrides)
    (directory / f"{name}.json5").write_text(json.dumps(data, indent=2), encoding="utf-8")


def index_at(tmp_path: Path) -> MCPToolIndex:
    """A cache owned by the test — never the real ``~/.trimum/mcp-tools.json``."""
    return MCPToolIndex(tmp_path / "mcp-tools.json")


def registry_at(tmp_path: Path, *, index=None) -> ToolRegistry:
    """A registry with an empty tools dir and a cache that belongs to the test."""
    return ToolRegistry(str(tmp_path / "tools"), mcp_index=index)


def request(tool: ToolType, *args: str) -> ExecuteRequest:
    return ExecuteRequest(tool=tool, args=list(args))


@contextlib.asynccontextmanager
async def dispatcher(directory: Path, *, index=None, **kwargs):
    registry = MCPRegistry(directory)
    node = MCPDispatcher(
        registry=registry,
        pool=MCPServerPool(registry, log_dir=directory.parent / "logs"),
        tool_index=index,
        **kwargs,
    )
    try:
        yield node
    finally:
        await node.close()


def parser_for(tmp_path: Path, *names: str) -> MCPDispatcher:
    """A dispatcher used only for ``_split_call`` (no pool, no process)."""
    directory = tmp_path / "mcp"
    for name in names:
        write_server(directory, name)
    return MCPDispatcher(registry=MCPRegistry(directory))


class RecordingAudit:
    """Audit sink that keeps the events instead of writing them."""

    def __init__(self) -> None:
        self.events: list = []

    def append(self, event) -> None:
        self.events.append(event)


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------


class TestFlatName:
    def test_joins_server_and_tool(self):
        assert flat_name("filesystem", "read_file") == "filesystem__read_file"


class TestSplitName:
    @pytest.mark.parametrize(
        "server,tool",
        [("echo", "echo"), ("filesystem", "read_file"), ("a", "b__c"), ("s", "t__u__v")],
    )
    def test_round_trips_what_flat_name_built(self, server, tool):
        assert split_name(flat_name(server, tool)) == (server, tool)

    def test_only_the_first_separator_counts(self):
        assert split_name("a__b__c") == ("a", "b__c")

    def test_a_single_underscore_is_not_a_separator(self):
        assert split_name("file_read") is None

    @pytest.mark.parametrize("name", ["echo", "", "   ", None, "server__", "__tool", "__"])
    def test_names_that_are_not_aggregated(self, name):
        assert split_name(name) is None

    def test_surrounding_whitespace_is_ignored(self):
        assert split_name("  echo__echo  ") == ("echo", "echo")


# ---------------------------------------------------------------------------
# fingerprints
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_is_stable_across_instances(self):
        first = mcp_bridge.fingerprint(definition())
        assert first == mcp_bridge.fingerprint(definition())
        assert len(first) == 16

    @pytest.mark.parametrize(
        "override",
        [
            {"command": "somewhere-else"},
            {"args": ["--different"]},
            {"transport": "http", "command": "", "url": "https://example.invalid/mcp"},
            {"enabled": False},
            {"allow_tools": ["echo"]},
            {"deny_tools": ["fail"]},
            {"trust": "cloud"},
        ],
    )
    def test_changes_whenever_the_tool_set_could_change(self, override):
        assert mcp_bridge.fingerprint(definition(**override)) != mcp_bridge.fingerprint(
            definition()
        )

    def test_env_values_rotate_without_invalidating_but_new_keys_do_not(self):
        base = definition(env={"TOKEN": "secret-a"})
        assert mcp_bridge.fingerprint(definition(env={"TOKEN": "secret-b"})) == (
            mcp_bridge.fingerprint(base)
        )
        assert mcp_bridge.fingerprint(definition(env={"OTHER": "secret-a"})) != (
            mcp_bridge.fingerprint(base)
        )

    def test_header_values_do_not_invalidate_but_new_headers_do(self):
        base = definition(headers={"Authorization": "Bearer a"})
        assert mcp_bridge.fingerprint(
            definition(headers={"Authorization": "Bearer b"})
        ) == mcp_bridge.fingerprint(base)
        assert mcp_bridge.fingerprint(definition(headers={"X-Trace": "a"})) != (
            mcp_bridge.fingerprint(base)
        )

    def test_secrets_never_reach_the_cache_file(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition(env={"TOKEN": "super-secret"}, headers={"X-Key": "also-secret"}), ECHO_TOOLS)
        written = node.path.read_text(encoding="utf-8")
        assert "super-secret" not in written and "also-secret" not in written


# ---------------------------------------------------------------------------
# cache: writing, reading, invalidating
# ---------------------------------------------------------------------------


class TestRecord:
    def test_a_fresh_instance_sees_what_was_recorded(self, tmp_path):
        index_at(tmp_path).record(definition(), ECHO_TOOLS)
        assert set(index_at(tmp_path).entries()) == {"echo__echo", "echo__fail"}

    def test_the_entry_carries_its_provenance(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition(risk="high", timeout=7.0, trust="cloud"), ECHO_TOOLS)
        entry = node.entries()["echo__echo"]
        assert entry["server"] == "echo" and entry["tool"] == "echo"
        assert entry["risk"] == "high" and entry["timeout"] == 7.0
        assert entry["trust"] == "cloud" and entry["transport"] == "stdio"
        assert entry["input_schema"] == {"type": "object", "properties": {"text": {"type": "string"}}}
        assert entry["updated_at"] is not None

    def test_it_returns_the_number_of_tools(self, tmp_path):
        assert index_at(tmp_path).record(definition(), ECHO_TOOLS) == 2

    def test_a_second_list_replaces_the_server_wholesale(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition(), ECHO_TOOLS)
        node.record(definition(), [ECHO_TOOLS[0]])
        assert set(node.entries()) == {"echo__echo"}, "撤掉的工具不该留成僵尸名字"

    def test_tools_without_a_name_are_dropped(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition(), [{"name": ""}, {"description": "no name"}, ECHO_TOOLS[0]])
        assert set(node.entries()) == {"echo__echo"}

    def test_two_servers_coexist(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition("echo"), ECHO_TOOLS)
        node.record(definition("other"), [ECHO_TOOLS[0]])
        assert set(node.entries()) == {"echo__echo", "echo__fail", "other__echo"}


class TestLoading:
    def test_a_missing_file_is_an_empty_cache(self, tmp_path):
        assert index_at(tmp_path).entries() == {}

    def test_a_corrupt_file_is_an_empty_cache(self, tmp_path):
        path = tmp_path / "mcp-tools.json"
        path.write_text("{not json at all", encoding="utf-8")
        assert MCPToolIndex(path).entries() == {}

    def test_a_corrupt_file_recovers_on_the_next_write(self, tmp_path):
        path = tmp_path / "mcp-tools.json"
        path.write_text("{not json at all", encoding="utf-8")
        MCPToolIndex(path).record(definition(), ECHO_TOOLS)
        assert set(MCPToolIndex(path).entries()) == {"echo__echo", "echo__fail"}

    def test_a_wrong_shape_is_ignored_rather_than_fatal(self, tmp_path):
        path = tmp_path / "mcp-tools.json"
        path.write_text(json.dumps({"servers": {"echo": "not-a-dict"}}), encoding="utf-8")
        assert MCPToolIndex(path).entries() == {}

    def test_saving_leaves_no_temp_file_behind(self, tmp_path):
        index_at(tmp_path).record(definition(), ECHO_TOOLS)
        assert [p.name for p in tmp_path.iterdir()] == ["mcp-tools.json"]

    def test_an_unwritable_location_is_not_fatal(self, tmp_path):
        blocker = tmp_path / "blocked"
        blocker.write_text("a file, not a directory", encoding="utf-8")
        node = MCPToolIndex(blocker / "nested" / "mcp-tools.json")
        node.record(definition(), ECHO_TOOLS)
        assert set(node.entries()) == {"echo__echo", "echo__fail"}


class TestForgetAndPrune:
    def test_forget_drops_one_server_and_persists(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition("echo"), ECHO_TOOLS)
        node.record(definition("other"), ECHO_TOOLS)
        assert node.forget("echo") is True
        assert node.forget("echo") is False
        assert {e["server"] for e in index_at(tmp_path).entries().values()} == {"other"}

    def test_prune_drops_servers_whose_definition_is_gone(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition("echo"), ECHO_TOOLS)
        node.record(definition("other"), ECHO_TOOLS)
        assert node.prune(["echo"]) == 1
        assert {e["server"] for e in index_at(tmp_path).entries().values()} == {"echo"}

    def test_prune_keeps_servers_that_still_have_a_definition(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition("echo"), ECHO_TOOLS)
        assert node.prune(["echo", "other"]) == 0
        assert len(node.entries()) == 2


class TestDefaultPath:
    def test_the_env_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv(mcp_bridge.INDEX_ENV, str(tmp_path / "custom.json"))
        assert mcp_bridge.default_index_path() == tmp_path / "custom.json"

    def test_a_blank_override_falls_back_to_the_data_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv(mcp_bridge.INDEX_ENV, "   ")
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
        assert mcp_bridge.default_index_path() == tmp_path / "mcp-tools.json"


class TestToolDefinition:
    def test_aggregated_entries_go_through_mcp_tools_call(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition(risk="high", timeout=7.0), ECHO_TOOLS)
        made = {item.name: item for item in node.to_tool_definitions()}
        assert made["echo__echo"].tool_type == ToolType.MCP_TOOLS_CALL
        assert made["echo__echo"].risk_level == RiskLevel.HIGH
        assert made["echo__echo"].timeout_default == 7.0

    def test_the_description_names_the_server_and_the_tool(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition(), ECHO_TOOLS)
        made = {item.name: item for item in node.to_tool_definitions()}
        assert made["echo__echo"].description == "MCP echo.echo — Return the text you send"

    def test_a_tool_without_a_description_still_says_where_it_comes_from(self, tmp_path):
        node = index_at(tmp_path)
        node.record(definition(), [{"name": "bare", "description": ""}])
        assert node.to_tool_definitions()[0].description == "MCP echo.bare"


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class TestToolRegistryAggregation:
    def test_aggregated_tools_are_registered(self, tmp_path):
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)
        registry = registry_at(tmp_path, index=index)
        assert registry.get("echo__echo") is not None
        assert registry.get("echo__echo").tool_type == ToolType.MCP_TOOLS_CALL

    def test_an_empty_cache_registers_nothing(self, tmp_path):
        registry = registry_at(tmp_path, index=index_at(tmp_path))
        assert registry.list_mcp_tools() == []
        assert registry.get("shell") is not None, "本地工具不受影响"

    def test_bindings_expose_the_provenance(self, tmp_path):
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)
        registry = registry_at(tmp_path, index=index)
        binding = registry.mcp_binding("echo__echo")
        assert binding["server"] == "echo" and binding["tool"] == "echo"
        assert registry.mcp_binding("shell") is None

    def test_list_mcp_tools_only_reports_aggregated_ones(self, tmp_path):
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)
        registry = registry_at(tmp_path, index=index)
        names = {row["name"] for row in registry.list_mcp_tools()}
        assert names == {"echo__echo", "echo__fail"}
        assert "shell" not in names

    def test_refreshing_drops_tools_the_server_stopped_offering(self, tmp_path):
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)
        registry = registry_at(tmp_path, index=index)
        index.record(definition(), [ECHO_TOOLS[0]])
        registry.load_mcp_tools()
        assert registry.get("echo__echo") is not None
        assert registry.get("echo__fail") is None
        assert registry.mcp_binding("echo__fail") is None

    def test_a_local_tool_wins_a_name_collision(self, tmp_path):
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)
        registry = registry_at(tmp_path, index=index)
        local = ToolDefinition(name="echo__echo", description="mine", tool_type=ToolType.SHELL)
        registry.register(local)
        assert registry.load_mcp_tools() == 1
        assert registry.get("echo__echo").description == "mine"
        assert registry.mcp_binding("echo__echo") is None

    def test_unregistering_forgets_the_binding(self, tmp_path):
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)
        registry = registry_at(tmp_path, index=index)
        assert registry.unregister("echo__echo") is True
        assert registry.mcp_binding("echo__echo") is None

    def test_load_all_rebuilds_the_aggregated_set(self, tmp_path):
        index = index_at(tmp_path)
        index.record(definition("echo"), ECHO_TOOLS)
        registry = registry_at(tmp_path, index=index)
        index.record(definition("other"), ECHO_TOOLS)
        registry.load_all()
        assert registry.get("other__echo") is not None
        assert {row["name"] for row in registry.list_mcp_tools()} == {
            "echo__echo",
            "echo__fail",
            "other__echo",
            "other__fail",
        }


# ---------------------------------------------------------------------------
# parsing: both spellings of a call
# ---------------------------------------------------------------------------


class TestSplitCall:
    def test_the_classic_two_argument_form(self, tmp_path):
        node = parser_for(tmp_path)
        assert node._split_call(["echo", "echo", '{"text": "hi"}']) == (
            "echo",
            "echo",
            '{"text": "hi"}',
        )

    def test_the_aggregated_form_shown_by_tool_list(self, tmp_path):
        node = parser_for(tmp_path)
        assert node._split_call(["echo__echo", '{"text": "hi"}']) == (
            "echo",
            "echo",
            '{"text": "hi"}',
        )

    def test_the_aggregated_form_without_arguments(self, tmp_path):
        node = parser_for(tmp_path)
        assert node._split_call(["echo__echo"]) == ("echo", "echo", "")

    def test_json_split_across_argv_tokens_is_rejoined(self, tmp_path):
        node = parser_for(tmp_path)
        assert node._split_call(["echo__echo", '{"text":', '"hi"}']) == (
            "echo",
            "echo",
            '{"text": "hi"}',
        )

    def test_a_server_actually_named_a__b_wins_the_classic_reading(self, tmp_path):
        node = parser_for(tmp_path, "echo", "echo__x")
        assert node._split_call(["echo__x", "echo"]) == ("echo__x", "echo", "")

    @pytest.mark.parametrize("args", [[], ["echo"], ["echo__"], ["__echo"], ["_"]])
    def test_arguments_that_cannot_be_parsed(self, tmp_path, args):
        node = parser_for(tmp_path)
        assert node._split_call(args) is None


# ---------------------------------------------------------------------------
# dispatcher: listing feeds the cache, calling accepts the flat name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListingFeedsTheRegistry:
    async def test_a_listed_server_is_visible_in_the_registry(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory)
        index = index_at(tmp_path)
        async with dispatcher(directory, index=index) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_LIST))
        assert response.status == "allowed"

        registry = registry_at(tmp_path, index=index)
        assert {row["name"] for row in registry.list_mcp_tools()} == {
            "echo__echo",
            "echo__fail",
            "echo__slow",
            "echo__delete_everything",
        }
        assert registry.get("echo__echo").tool_type == ToolType.MCP_TOOLS_CALL

    async def test_listing_one_server_records_only_that_server(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory, "echo")
        write_server(directory, "other")
        index = index_at(tmp_path)
        async with dispatcher(directory, index=index) as node:
            await node.execute(request(ToolType.MCP_TOOLS_LIST, "other"))
        assert {row["server"] for row in index.entries().values()} == {"other"}

    async def test_a_failed_listing_records_nothing(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory, "dead", args=[str(FIXTURE), "--exit-immediately"])
        index = index_at(tmp_path)
        async with dispatcher(directory, index=index) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_LIST, "dead"))
        assert response.status == "denied"
        assert index.entries() == {}

    async def test_an_empty_cache_needs_no_server_to_read(self, tmp_path):
        """读缓存不启动进程：这正是它能和懒启动共存的原因。"""
        registry = registry_at(tmp_path, index=index_at(tmp_path))
        assert registry.list_mcp_tools() == []


@pytest.mark.asyncio
class TestAggregatedCalls:
    async def test_the_flat_name_reaches_the_same_tool(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory)
        async with dispatcher(directory) as node:
            flat = await node.execute(request(ToolType.MCP_TOOLS_CALL, "echo__echo", '{"text": "hi"}'))
            classic = await node.execute(
                request(ToolType.MCP_TOOLS_CALL, "echo", "echo", '{"text": "hi"}')
            )
        assert flat.status == "allowed" and classic.status == "allowed"
        assert json.loads(flat.output)["text"] == json.loads(classic.output)["text"] == "echo: hi"

    async def test_an_argument_that_names_a_real_server_still_works(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory, "echo")
        write_server(directory, "echo__x")
        async with dispatcher(directory) as node:
            response = await node.execute(
                request(ToolType.MCP_TOOLS_CALL, "echo__x", "echo", '{"text": "hi"}')
            )
        assert response.status == "allowed"

    async def test_a_flat_name_for_an_unknown_server_just_says_so(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory)
        async with dispatcher(directory) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_CALL, "ghost__echo", "{}"))
        assert response.status == "denied"
        assert "ghost" in response.error and "not found" in response.error

    async def test_the_audit_event_names_the_real_server_and_tool(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory)
        audit = RecordingAudit()
        async with dispatcher(directory, audit_store=audit) as node:
            await node.execute(request(ToolType.MCP_TOOLS_CALL, "echo__echo", '{"text": "hi"}'))
        event = audit.events[-1]
        assert event.details["server"] == "echo" and event.details["tool"] == "echo"
        assert event.details["argument_keys"] == ["text"]
        assert event.command == "echo.echo"

    async def test_an_unparseable_call_shows_the_usage(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory)
        async with dispatcher(directory) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_CALL, "echo"))
        assert response.status == "denied"
        assert "Usage: mcp.tools.call" in response.error
        assert "__" in response.error, "用法里要给出聚合名的写法"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cli_json(capsys) -> dict:
    """Parse ``trm --json`` output.

    A tool module that prints on import (PyMuPDF's ``fitz`` notice, on some
    boxes) puts a banner in front of the document; the JSON is still the last
    thing printed, so read from the first brace.
    """
    out = capsys.readouterr().out
    return json.loads(out[out.index("{") :])


def cli_registry(tmp_path: Path, monkeypatch) -> None:
    """Point ``trm tool list`` at a private tools directory.

    The cache stays env-driven (``TRIMUM_MCP_INDEX``) — that is the part under
    test.  Only the tools directory is pinned, so the result does not depend on
    whatever the host keeps in its real ``~/.trimum/tools``.
    """
    from trimum_core.cli.commands import tool as tool_mod

    monkeypatch.setattr(tool_mod, "_registry", lambda: ToolRegistry(str(tmp_path / "tools")))


class TestToolListCli:
    def test_aggregated_tools_are_tagged_with_their_source(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(mcp_bridge.INDEX_ENV, str(tmp_path / "mcp-tools.json"))
        index_at(tmp_path).record(definition(), ECHO_TOOLS)
        cli_registry(tmp_path, monkeypatch)

        assert main(["--json", "tool", "list"]) == 0
        payload = cli_json(capsys)
        rows = {row["name"]: row for row in payload["tools"]}
        assert rows["echo__echo"]["source"] == "mcp"
        assert rows["echo__echo"]["mcp"]["server"] == "echo"
        assert rows["echo__echo"]["mcp"]["tool"] == "echo"
        assert rows["shell"]["source"] == "local"
        assert payload["count"] == len(payload["tools"])

    def test_the_mcp_flag_hides_local_tools(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(mcp_bridge.INDEX_ENV, str(tmp_path / "mcp-tools.json"))
        index_at(tmp_path).record(definition(), ECHO_TOOLS)
        cli_registry(tmp_path, monkeypatch)

        assert main(["--json", "tool", "list", "--mcp"]) == 0
        payload = cli_json(capsys)
        assert payload["count"] == 2
        assert {row["name"] for row in payload["tools"]} == {"echo__echo", "echo__fail"}
        assert all(row["source"] == "mcp" for row in payload["tools"])

    def test_info_of_an_aggregated_tool_points_back_at_the_server(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv(mcp_bridge.INDEX_ENV, str(tmp_path / "mcp-tools.json"))
        index_at(tmp_path).record(definition(), ECHO_TOOLS)
        cli_registry(tmp_path, monkeypatch)

        assert main(["--json", "tool", "info", "echo__echo"]) == 0
        tool = cli_json(capsys)["tool"]
        assert tool["source"] == "mcp" and tool["mcp"]["tool"] == "echo"

    def test_an_empty_cache_leaves_the_local_tools_alone(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(mcp_bridge.INDEX_ENV, str(tmp_path / "mcp-tools.json"))
        cli_registry(tmp_path, monkeypatch)

        assert main(["--json", "tool", "list"]) == 0
        payload = cli_json(capsys)
        assert payload["tools"] and all(row["source"] == "local" for row in payload["tools"])

class TestDefinitionsReadable:
    """清缓存前的三种「一个 server 都没有」必须分得开。"""

    def test_a_populated_directory_is_readable(self, tmp_path):
        write_server(tmp_path / "mcp")
        assert definitions_readable(tmp_path / "mcp") is True

    def test_an_empty_directory_is_readable(self, tmp_path):
        directory = tmp_path / "mcp"
        directory.mkdir()
        assert definitions_readable(directory) is True

    def test_a_missing_directory_counts_as_no_definitions(self, tmp_path):
        assert definitions_readable(tmp_path / "does-not-exist") is True

    def test_a_path_that_is_not_a_directory_is_not_readable(self, tmp_path):
        """`TRIMUM_MCP_DIR` 指到一个普通文件：配错了，不能拿它去清缓存。"""
        path = tmp_path / "mcp"
        path.write_text("not a directory", encoding="utf-8")
        assert definitions_readable(path) is False

    def test_a_directory_that_raises_oserror_is_not_readable(self, tmp_path, monkeypatch):
        directory = tmp_path / "mcp"
        directory.mkdir()

        import trimum_core.mcp_registry as registry_module

        def boom(*args, **kwargs):
            raise OSError(5, "Input/output error")

        monkeypatch.setattr(registry_module.os, "scandir", boom)
        assert definitions_readable(directory) is False


# ---------------------------------------------------------------------------
# daemon wiring (api_server)
# ---------------------------------------------------------------------------


class TestDaemonWiring:
    def test_the_daemon_index_follows_the_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv(mcp_bridge.INDEX_ENV, str(tmp_path / "daemon.json"))
        assert build_mcp_tool_index().path == tmp_path / "daemon.json"

    def test_wiring_hands_the_same_index_to_the_dispatcher_and_the_registry(self, tmp_path):
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)
        node = parser_for(tmp_path)
        tools = ToolRegistry(
            str(tmp_path / "tools"), mcp_index=MCPToolIndex(tmp_path / "elsewhere.json")
        )
        assert tools.mcp_binding("echo__echo") is None, "这一份注册表起手是空的"

        state = SimpleNamespace(
            tool_gateway=SimpleNamespace(
                dispatchers={
                    ToolType.MCP_TOOLS_LIST: node,
                    ToolType.MCP_TOOLS_CALL: node,
                },
                tools=tools,
            ),
            mcp_index=None,
        )
        assert wire_mcp_index(state, index) == [node], "同一个实例只接一次"
        assert node._tool_index is index
        assert tools.mcp_binding("echo__echo")["server"] == "echo"

    def test_prune_drops_the_servers_whose_definition_is_gone(self, tmp_path):
        directory = tmp_path / "mcp"
        write_server(directory, "echo")
        index = index_at(tmp_path)
        index.record(definition("echo"), ECHO_TOOLS)
        index.record(definition("other"), ECHO_TOOLS)
        assert prune_mcp_index(index, MCPRegistry(directory)) == 1
        assert {e["server"] for e in index.entries().values()} == {"echo"}

    def test_prune_clears_the_cache_when_the_whole_directory_is_gone(self, tmp_path):
        """目录整个没了 = 一个 server 都没配 → 缓存里每条都是幽灵条目。"""
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)
        assert prune_mcp_index(index, MCPRegistry(tmp_path / "does-not-exist")) == 1
        assert index.entries() == {}

    def test_prune_keeps_everything_when_the_directory_cannot_be_listed(self, tmp_path, monkeypatch):
        """目录在、却列不出来（权限 / IO）才是「不知道」；那时别碰缓存。"""
        directory = tmp_path / "mcp"
        directory.mkdir()
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)

        import trimum_core.mcp_registry as registry_module

        def boom(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(registry_module.os, "scandir", boom)
        assert prune_mcp_index(index, MCPRegistry(directory)) == 0
        assert set(index.entries()) == {"echo__echo", "echo__fail"}

    def test_prune_without_a_directory_to_check(self, tmp_path):
        index = index_at(tmp_path)
        index.record(definition(), ECHO_TOOLS)
        assert prune_mcp_index(index, object()) == 0
        assert index.entries()

# ---------------------------------------------------------------------------
# CLI: trm mcp call with an aggregated name
# ---------------------------------------------------------------------------


class TestMcpCallCli:
    def _server_dir(self, tmp_path, monkeypatch) -> Path:
        directory = tmp_path / "mcp"
        write_server(directory)
        monkeypatch.setenv(MCP_DIR_ENV, str(directory))
        return directory

    def test_the_aggregated_name_calls_the_tool(self, tmp_path, monkeypatch, capsys):
        self._server_dir(tmp_path, monkeypatch)
        assert main(["--json", "mcp", "call", "echo__echo", '{"text": "cli"}', "--yes"]) == 0
        assert json.loads(capsys.readouterr().out)["text"] == "echo: cli"

    def test_the_classic_two_argument_form_still_works(self, tmp_path, monkeypatch, capsys):
        self._server_dir(tmp_path, monkeypatch)
        assert main(["--json", "mcp", "call", "echo", "echo", '{"text": "cli"}', "--yes"]) == 0
        assert json.loads(capsys.readouterr().out)["text"] == "echo: cli"

    def test_an_aggregated_name_needs_no_json_argument(self, tmp_path, monkeypatch, capsys):
        """工具可能一个参数都不要；argparse 不该把聚合名当成缺了 TOOL。"""
        self._server_dir(tmp_path, monkeypatch)
        assert main(["--json", "mcp", "call", "echo__echo", "--yes"]) == 0
        assert json.loads(capsys.readouterr().out)["text"] == "echo: "

    def test_a_piped_run_never_waits_for_input(self, tmp_path, monkeypatch, capsys):
        """stdin 不是 tty 时不能等人：直接按「没确认」处理，并提示 --yes。"""
        from trimum_core.cli.commands import mcp as mcp_mod

        self._server_dir(tmp_path, monkeypatch)

        class NotATty:
            def isatty(self):
                return False

            def readline(self, *args):
                return ""

        monkeypatch.setattr(mcp_mod.sys, "stdin", NotATty())
        assert main(["mcp", "call", "echo__echo", '{"text": "x"}']) == 1
        assert "use --yes" in capsys.readouterr().err

    def test_an_interactive_run_still_asks(self, tmp_path, monkeypatch, capsys):
        from trimum_core.cli.commands import mcp as mcp_mod

        self._server_dir(tmp_path, monkeypatch)

        class Tty:
            def isatty(self):
                return True

        monkeypatch.setattr(mcp_mod.sys, "stdin", Tty())
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")
        assert main(["mcp", "call", "echo__echo", '{"text": "x"}']) == 1
        assert "aborted" in capsys.readouterr().err

        monkeypatch.setattr("builtins.input", lambda prompt="": "y")
        assert main(["--json", "mcp", "call", "echo__echo", '{"text": "x"}']) == 0
        assert json.loads(capsys.readouterr().out)["text"] == "echo: x"
