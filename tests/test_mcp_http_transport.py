"""Tests for the streamable-HTTP MCP transport (M4).

Every test talks to ``tests/fixtures/mcp_http_server.py`` over real loopback
HTTP: real POSTs, real ``text/event-stream`` bodies, real session headers and
real ``202`` / ``404`` / ``500`` replies.  No external network, no mocks.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures.mcp_http_server import start_server  # noqa: E402
from trimum_core.mcp_client import (  # noqa: E402
    PROTOCOL_VERSION,
    SESSION_HEADER,
    MCPClient,
    MCPDisconnected,
    MCPProtocolError,
    MCPRemoteError,
    MCPTimeout,
    parse_sse_messages,
)
from trimum_core.mcp_registry import MCPServerDefinition, MCPServerPool  # noqa: E402


@pytest.fixture()
def mcp_server():
    server = start_server()
    try:
        yield server
    finally:
        server.stop()


def definition(url: str, **overrides) -> MCPServerDefinition:
    data = {
        "name": "echo",
        "transport": "http",
        "url": url,
        "enabled": True,
        "timeout": 10.0,
    }
    data.update(overrides)
    return MCPServerDefinition(**data)


@contextlib.asynccontextmanager
async def connected(url: str, **overrides):
    client = MCPClient(definition(url, **overrides))
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Handshake, session and headers
# ---------------------------------------------------------------------------


class TestHandshake:
    @pytest.mark.asyncio
    async def test_initialize_negotiates_and_keeps_the_session(self, mcp_server):
        async with connected(mcp_server.url) as client:
            assert client.initialized is True
            assert client.server_info["name"] == "echo-http"
            assert client.protocol_version == PROTOCOL_VERSION
            assert client.pid is None
            assert client._http.session_id in mcp_server.state.sessions

    @pytest.mark.asyncio
    async def test_client_asks_for_both_reply_shapes(self, mcp_server):
        async with connected(mcp_server.url):
            pass
        first = mcp_server.state.requests[0]
        assert first["method"] == "initialize"
        assert "application/json" in first["accept"]
        assert "text/event-stream" in first["accept"]
        assert first["content_type"] == "application/json"

    @pytest.mark.asyncio
    async def test_protocol_version_header_is_sent_after_initialize(self, mcp_server):
        async with connected(mcp_server.url):
            pass
        listed = mcp_server.state.last("tools/list") or mcp_server.state.last(
            "notifications/initialized"
        )
        assert listed["protocol"] == PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_definition_headers_are_sent(self, mcp_server):
        async with connected(
            mcp_server.url, headers={"Authorization": "Bearer test-token"}
        ):
            pass
        assert mcp_server.state.requests[0]["authorization"] == "Bearer test-token"

    @pytest.mark.asyncio
    async def test_initialized_notification_is_posted(self, mcp_server):
        async with connected(mcp_server.url):
            pass
        assert "notifications/initialized" in mcp_server.state.notifications


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


class TestCalls:
    @pytest.mark.asyncio
    async def test_tools_list_over_http(self, mcp_server):
        async with connected(mcp_server.url) as client:
            tools = await client.list_tools()
        names = [tool.name for tool in tools]
        assert "echo" in names and "slow" in names
        assert tools[0].input_schema["type"] == "object"

    @pytest.mark.asyncio
    async def test_call_tool_json_reply(self, mcp_server):
        async with connected(mcp_server.url) as client:
            result = await client.call_tool("echo", {"text": "hi"})
        assert result.text == "echo: hi"
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_call_tool_sse_reply(self, mcp_server):
        mcp_server.state.reply_mode = "sse"
        async with connected(mcp_server.url) as client:
            result = await client.call_tool("echo", {"text": "sse"})
        assert result.text == "echo: sse"

    @pytest.mark.asyncio
    async def test_notifications_inside_the_sse_stream_are_kept(self, mcp_server):
        mcp_server.state.reply_mode = "noisy-sse"
        async with connected(mcp_server.url) as client:
            result = await client.call_tool("echo", {"text": "noisy"})
            seen = client.notifications
        assert result.text == "echo: noisy"
        assert any(item.get("method") == "notifications/message" for item in seen)

    @pytest.mark.asyncio
    async def test_is_error_result_is_reported_not_raised(self, mcp_server):
        async with connected(mcp_server.url) as client:
            result = await client.call_tool("fail", {})
        assert result.is_error is True
        assert result.text == "boom"

    @pytest.mark.asyncio
    async def test_remote_error_for_unknown_tool(self, mcp_server):
        async with connected(mcp_server.url) as client:
            with pytest.raises(MCPRemoteError) as excinfo:
                await client.call_tool("nope", {})
        assert "unknown tool" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_ping_over_http(self, mcp_server):
        async with connected(mcp_server.url) as client:
            assert await client.ping() == {}

    @pytest.mark.asyncio
    async def test_to_dict_reports_transport_and_url(self, mcp_server):
        async with connected(mcp_server.url) as client:
            data = client.to_dict()
        assert data["transport"] == "http"
        assert data["url"] == mcp_server.url
        assert data["pid"] is None and data["alive"] is True


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


class TestFailures:
    @pytest.mark.asyncio
    async def test_expired_session_is_detected(self, mcp_server):
        async with connected(mcp_server.url) as client:
            mcp_server.state.sessions.clear()  # server forgot the session
            with pytest.raises(MCPDisconnected) as excinfo:
                await client.call_tool("echo", {"text": "gone"})
            assert "expired" in str(excinfo.value)
            assert client.alive is False and "404" in client.broken

    @pytest.mark.asyncio
    async def test_http_500_becomes_a_remote_error(self, mcp_server):
        async with connected(mcp_server.url) as client:
            with pytest.raises(MCPRemoteError) as excinfo:
                await client.call_tool("boom", {})
        assert "500" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_timeout_marks_the_client_broken(self, mcp_server):
        async with connected(mcp_server.url, timeout=0.3) as client:
            with pytest.raises(MCPTimeout):
                await client.call_tool("hang", {"seconds": 2.0})
            assert client.alive is False

    @pytest.mark.asyncio
    async def test_202_for_a_request_is_a_protocol_error(self, mcp_server):
        async with connected(mcp_server.url) as client:
            with pytest.raises(MCPProtocolError) as excinfo:
                await client.call_tool("accepted", {})
        assert "without a reply" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_sse_stream_without_a_reply_is_a_protocol_error(self, mcp_server):
        async with connected(mcp_server.url) as client:
            # flip after the handshake: the stream carries a notification, no reply
            mcp_server.state.reply_mode = "empty-sse"
            with pytest.raises(MCPProtocolError) as excinfo:
                await client.call_tool("echo", {"text": "x"})
            assert "no reply" in str(excinfo.value)
            assert client.alive is False

    @pytest.mark.asyncio
    async def test_calls_before_start_are_rejected(self, mcp_server):
        client = MCPClient(definition(mcp_server.url))
        with pytest.raises(MCPDisconnected):
            await client.call_tool("echo", {"text": "x"})

    @pytest.mark.asyncio
    async def test_close_terminates_the_session(self, mcp_server):
        client = MCPClient(definition(mcp_server.url))
        await client.connect()
        session = client._http.session_id
        await client.close()
        assert session in mcp_server.state.terminated
        assert client.alive is False


# ---------------------------------------------------------------------------
# Pool integration
# ---------------------------------------------------------------------------


class TestPool:
    @pytest.mark.asyncio
    async def test_pool_reuses_and_restarts_http_clients(self, mcp_server, tmp_path):
        registry = _registry(tmp_path, mcp_server.url)
        pool = MCPServerPool(registry)
        try:
            first = await pool.client("echo")
            assert await pool.client("echo") is first

            mcp_server.state.sessions.clear()
            restarted = await pool.restart("echo")
            assert restarted is True

            fresh = await pool.client("echo")
            assert fresh is not first
            assert fresh.alive is True
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_status_reports_http_state(self, mcp_server, tmp_path):
        registry = _registry(tmp_path, mcp_server.url)
        pool = MCPServerPool(registry)
        try:
            await pool.client("echo")
            row = (await pool.status())[0]
            assert row["connected"] is True
            assert row["transport"] == "http"
            assert row["url"] == mcp_server.url
            assert row["pid"] is None
            assert row["idle_seconds"] is not None
        finally:
            await pool.close_all()


def _registry(tmp_path: Path, url: str):
    from trimum_core.mcp_registry import MCPRegistry

    directory = tmp_path / "mcp"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "echo.json5").write_text(
        '{ name: "echo", transport: "http", url: "%s", enabled: true }' % url,
        encoding="utf-8",
    )
    return MCPRegistry(directory)


# ---------------------------------------------------------------------------
# SSE framing (unit level — the HTTP tests above use the same parser)
# ---------------------------------------------------------------------------


class TestSseParsing:
    def test_single_event(self):
        body = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
        assert parse_sse_messages(body) == [{"jsonrpc": "2.0", "id": 1, "result": {}}]

    def test_multiple_events_and_keep_alive_comments(self):
        body = (
            ': keep-alive\n\n'
            'data: {"jsonrpc":"2.0","method":"notifications/message"}\n\n'
            'event: message\n'
            'id: 7\n'
            'data: {"jsonrpc":"2.0","id":3,"result":{"ok":true}}\n\n'
        )
        messages = parse_sse_messages(body)
        assert [item.get("id") for item in messages] == [None, 3]

    def test_multi_line_data_is_joined(self):
        body = 'data: {"jsonrpc":"2.0",\ndata: "id":1,"result":{}}\n\n'
        assert parse_sse_messages(body)[0]["id"] == 1

    def test_batches_are_flattened(self):
        body = 'data: [{"jsonrpc":"2.0","id":1,"result":{}},{"jsonrpc":"2.0","id":2,"result":{}}]\n\n'
        assert [item["id"] for item in parse_sse_messages(body)] == [1, 2]

    def test_invalid_json_is_a_protocol_error(self):
        with pytest.raises(MCPProtocolError):
            parse_sse_messages("data: not-json\n\n")

    def test_empty_body_has_no_messages(self):
        assert parse_sse_messages("") == []


@pytest.mark.asyncio
async def test_definition_validation_requires_a_url_for_http():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MCPServerDefinition(name="x", transport="http", url="")
    assert MCPServerDefinition(name="x", transport="http", url="http://h/mcp").url
    assert MCPServerDefinition(name="x", transport="streamable-http", url="http://h/mcp").transport