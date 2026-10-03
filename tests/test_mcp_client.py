"""Tests for the stdio MCP client (``trimum_core.mcp_client``).

Every test spawns ``tests/fixtures/mcp_echo_server.py`` — a real MCP server over
real pipes — so framing, timeouts, out-of-band notifications and process teardown
are exercised for real.  No network, no Node, no mocks.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.mcp_client import (  # noqa: E402
    PROTOCOL_VERSION,
    MCPClient,
    MCPDisconnected,
    MCPProtocolError,
    MCPRemoteError,
    MCPTimeout,
    MCPTool,
    flatten_content,
)
from trimum_core.mcp_registry import MCPServerDefinition  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"


def definition(**overrides) -> MCPServerDefinition:
    data = {
        "name": "echo",
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(FIXTURE)],
        "enabled": True,
        "timeout": 10.0,
    }
    data.update(overrides)
    return MCPServerDefinition(**data)


@contextlib.asynccontextmanager
async def connected(tmp_path, **overrides):
    client = MCPClient(definition(**overrides), log_dir=tmp_path / "logs")
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


def test_tool_from_wire_accepts_both_schema_spellings():
    wire = MCPTool.from_wire({"name": "read", "description": "d", "inputSchema": {"type": "object"}})
    legacy = MCPTool.from_wire({"name": "read", "input_schema": {"type": "object"}})
    assert wire.input_schema == {"type": "object"} == legacy.input_schema
    assert MCPTool.from_wire({"name": "x", "inputSchema": "nonsense"}).input_schema == {}


def test_flatten_content_variants():
    assert flatten_content("plain") == "plain"
    assert flatten_content(None) == ""
    assert flatten_content([{"type": "text", "text": "a"}, {"text": "b"}]) == "a\nb"
    assert "image" in flatten_content([{"type": "image", "data": "x"}])
    assert flatten_content([None, "raw"]) == "raw"


@pytest.mark.asyncio
class TestHandshake:
    async def test_initialize_records_server_info(self, tmp_path):
        async with connected(tmp_path) as client:
            assert client.alive and client.initialized
            assert client.pid is not None
            assert client.server_info["name"] == "echo"
            assert client.protocol_version == PROTOCOL_VERSION
            assert client.capabilities == {"tools": {}}
            assert client.to_dict()["alive"] is True

    async def test_stderr_is_captured_in_a_log_file(self, tmp_path):
        async with connected(tmp_path, args=[str(FIXTURE), "--stderr-noise"]) as client:
            await client.ping()
            log = client.stderr_log
            assert log is not None and log.is_file()
            content = ""
            for _ in range(40):
                content = log.read_text(encoding="utf-8", errors="replace")
                if "server is starting" in content:
                    break
                await asyncio.sleep(0.05)
            assert "server is starting" in content

    async def test_close_is_idempotent(self, tmp_path):
        client = MCPClient(definition(), log_dir=tmp_path / "logs")
        await client.connect()
        assert client.alive
        await client.close()
        assert not client.alive
        await client.close()
        assert not client.alive and client.initialized is False


@pytest.mark.asyncio
class TestToolCalls:
    async def test_list_tools_parses_schemas(self, tmp_path):
        async with connected(tmp_path) as client:
            tools = await client.list_tools()
            names = [tool.name for tool in tools]
            assert names == ["echo", "fail", "slow", "delete_everything"]
            echo = next(tool for tool in tools if tool.name == "echo")
            assert echo.input_schema["properties"]["text"]["type"] == "string"
            assert echo.to_dict()["description"] == "Return the text you send"

    async def test_call_tool_returns_text_and_duration(self, tmp_path):
        async with connected(tmp_path) as client:
            result = await client.call_tool("echo", {"text": "hi"})
            assert result.is_error is False
            assert result.text == "echo: hi"
            assert result.duration_ms >= 0
            assert result.to_dict()["server"] == "echo"

    async def test_is_error_reply_is_reported_not_raised(self, tmp_path):
        async with connected(tmp_path) as client:
            result = await client.call_tool("fail", {})
            assert result.is_error is True
            assert result.text == "boom"
            assert client.alive  # 工具报错不是连接故障

    async def test_remote_error_becomes_an_exception(self, tmp_path):
        async with connected(tmp_path) as client:
            with pytest.raises(MCPRemoteError) as excinfo:
                await client.call_tool("nope", {})
            assert "unknown tool" in str(excinfo.value)
            assert excinfo.value.remote_code == -32602
            assert client.alive

    async def test_unknown_method_uses_the_same_path(self, tmp_path):
        async with connected(tmp_path) as client:
            with pytest.raises(MCPRemoteError):
                await client._request("does/not/exist", {})

    async def test_out_of_band_notifications_do_not_desync(self, tmp_path):
        async with connected(tmp_path, args=[str(FIXTURE), "--noisy"]) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools][0] == "echo"
            assert client.notifications  # 通知被记录而不是当成回复


@pytest.mark.asyncio
class TestFailures:
    async def test_timeout_marks_the_connection_broken(self, tmp_path):
        async with connected(tmp_path, timeout=0.4) as client:
            with pytest.raises(MCPTimeout):
                await client.call_tool("slow", {"seconds": 2})
            assert not client.alive
            assert "no reply" in client.broken
            # 坏掉的连接不能再发请求
            with pytest.raises(MCPDisconnected):
                await client.call_tool("echo", {"text": "x"})

    async def test_server_that_exits_is_reported(self, tmp_path):
        client = MCPClient(
            definition(args=[str(FIXTURE), "--exit-immediately"]), log_dir=tmp_path / "logs"
        )
        with pytest.raises(MCPDisconnected):
            await client.connect()
        await client.close()

    async def test_missing_command_is_reported(self, tmp_path):
        client = MCPClient(
            definition(command="trimum-mcp-does-not-exist"), log_dir=tmp_path / "logs"
        )
        with pytest.raises(MCPDisconnected) as excinfo:
            await client.connect()
        assert "command not found" in str(excinfo.value)

    async def test_unknown_transport_names_are_refused(self, tmp_path):
        """传输名有白名单：注册层（pydantic）与客户端各拦一道。"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            definition(transport="carrier-pigeon", command="")

        stub = SimpleNamespace(name="odd", transport="carrier-pigeon", timeout=5.0)
        client = MCPClient(stub, log_dir=tmp_path / "logs")
        with pytest.raises(MCPProtocolError) as excinfo:
            await client.connect()
        assert "carrier-pigeon" in str(excinfo.value)

    async def test_http_transport_needs_a_url(self, tmp_path):
        from trimum_core.mcp_client import MCPHttpTransport

        transport = MCPHttpTransport("")
        with pytest.raises(MCPProtocolError) as excinfo:
            await transport.start()
        assert "no url" in str(excinfo.value)

        with pytest.raises(MCPProtocolError) as excinfo:
            await MCPHttpTransport("ftp://example.invalid/mcp").start()
        assert "must be http(s)" in str(excinfo.value)

    async def test_calls_without_a_server_are_rejected(self, tmp_path):
        client = MCPClient(definition(), log_dir=tmp_path / "logs")
        with pytest.raises(MCPDisconnected):
            await client.call_tool("echo", {"text": "x"})
        assert client.pid is None