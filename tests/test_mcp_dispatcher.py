"""Tests for ``MCPDispatcher`` and `trm mcp` — the path an Agent actually takes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.audit_store import AuditStore  # noqa: E402
from trimum_core.cli import main  # noqa: E402
from trimum_core.mcp_registry import MCP_DIR_ENV, MCPRegistry, MCPServerPool  # noqa: E402
from trimum_core.models import ExecuteRequest, ToolType  # noqa: E402
from trimum_core.tool_dispatchers import MCPDispatcher  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"


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
    (directory / f"{name}.json5").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


class FakeBus:
    """Minimal EventBus stand-in that records emitted tasks."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit_task(self, task_type, payload=None, source="", severity=None):
        self.events.append(
            {"type": task_type, "payload": payload or {}, "source": source, "severity": severity}
        )


def build_dispatcher(tmp_path, *, servers=("echo",), audit_store=None, event_bus=None):
    directory = tmp_path / "mcp"
    for spec in servers:
        if isinstance(spec, tuple):
            name, overrides = spec
            write_server(directory, name, **overrides)
        else:
            write_server(directory, spec)
    registry = MCPRegistry(directory)
    pool = MCPServerPool(registry, log_dir=tmp_path / "logs")
    return MCPDispatcher(registry=registry, pool=pool, audit_store=audit_store, event_bus=event_bus)


@contextlib.asynccontextmanager
async def dispatcher(tmp_path, **kwargs):
    node = build_dispatcher(tmp_path, **kwargs)
    try:
        yield node
    finally:
        await node.close()


def request(tool: ToolType, *args: str) -> ExecuteRequest:
    return ExecuteRequest(tool=tool, args=list(args))


# ---------------------------------------------------------------------------
# mcp.tools.list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListTools:
    async def test_without_servers_is_denied_with_a_useful_message(self, tmp_path):
        node = MCPDispatcher(registry=MCPRegistry(tmp_path / "empty"))
        response = await node.execute(request(ToolType.MCP_TOOLS_LIST))
        assert response.status == "denied"
        assert "MCP" in response.error and "enabled" in response.error

    async def test_lists_the_tools_of_every_enabled_server(self, tmp_path):
        async with dispatcher(tmp_path) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_LIST))
        assert response.status == "allowed"
        payload = json.loads(response.output)
        server = payload["servers"][0]
        assert server["server"] == "echo" and server["ok"] is True
        assert {tool["name"] for tool in server["tools"]} >= {"echo", "fail", "slow"}

    async def test_a_named_server_is_selected(self, tmp_path):
        async with dispatcher(
            tmp_path,
            servers=[("echo", {}), ("other", {"command": "definitely-not-installed"})],
        ) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_LIST, "echo"))
        payload = json.loads(response.output)
        assert [row["server"] for row in payload["servers"]] == ["echo"]

    async def test_unknown_server_is_denied(self, tmp_path):
        async with dispatcher(tmp_path) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_LIST, "nope"))
        assert response.status == "denied"
        assert "not found" in response.error and "echo" in response.error

    async def test_disabled_server_is_denied(self, tmp_path):
        async with dispatcher(tmp_path, servers=[("echo", {"enabled": False})]) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_LIST, "echo"))
        assert response.status == "denied"
        assert "disabled" in response.error

    async def test_one_broken_server_does_not_hide_the_healthy_one(self, tmp_path):
        async with dispatcher(
            tmp_path,
            servers=[("echo", {}), ("dead", {"args": [str(FIXTURE), "--exit-immediately"]})],
        ) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_LIST))
        assert response.status == "allowed"
        rows = {row["server"]: row for row in json.loads(response.output)["servers"]}
        assert rows["echo"]["ok"] is True
        assert rows["dead"]["ok"] is False and rows["dead"]["error"]

    async def test_all_servers_broken_is_denied(self, tmp_path):
        async with dispatcher(
            tmp_path, servers=[("dead", {"args": [str(FIXTURE), "--exit-immediately"]})]
        ) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_LIST))
        assert response.status == "denied"
        assert "MCP tools/list failed" in response.error


# ---------------------------------------------------------------------------
# mcp.tools.call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCallTool:
    async def test_successful_call_returns_structured_output(self, tmp_path):
        async with dispatcher(tmp_path) as node:
            response = await node.execute(
                request(ToolType.MCP_TOOLS_CALL, "echo", "echo", '{"text": "hi"}')
            )
        assert response.status == "allowed"
        payload = json.loads(response.output)
        assert payload["text"] == "echo: hi"
        assert payload["is_error"] is False
        assert payload["trust"] == "local"

    async def test_arguments_are_split_across_argv_tokens(self, tmp_path):
        async with dispatcher(tmp_path) as node:
            response = await node.execute(
                request(ToolType.MCP_TOOLS_CALL, "echo", "echo", '{"text":', '"spaced"}')
            )
        assert json.loads(response.output)["text"] == "echo: spaced"

    async def test_missing_arguments_show_the_usage(self, tmp_path):
        async with dispatcher(tmp_path) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_CALL, "echo"))
        assert response.status == "denied"
        assert "Usage: mcp.tools.call" in response.error

    async def test_arguments_must_be_a_json_object(self, tmp_path):
        async with dispatcher(tmp_path) as node:
            response = await node.execute(
                request(ToolType.MCP_TOOLS_CALL, "echo", "echo", "[1, 2]")
            )
        assert response.status == "denied"
        assert "JSON object" in response.error

    async def test_unknown_server_is_denied(self, tmp_path):
        async with dispatcher(tmp_path) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_CALL, "ghost", "echo"))
        assert response.status == "denied"
        assert "not found" in response.error

    async def test_deny_pattern_blocks_the_call(self, tmp_path):
        async with dispatcher(tmp_path, servers=[("echo", {"deny_tools": ["delete*"]})]) as node:
            response = await node.execute(
                request(ToolType.MCP_TOOLS_CALL, "echo", "delete_everything", "{}")
            )
        assert response.status == "denied"
        assert "denied" in response.error and "delete*" in response.error

    async def test_cloud_servers_cannot_reach_destructive_tool_names(self, tmp_path):
        async with dispatcher(tmp_path, servers=[("echo", {"trust": "cloud"})]) as node:
            response = await node.execute(
                request(ToolType.MCP_TOOLS_CALL, "echo", "delete_everything", "{}")
            )
        assert response.status == "denied"

    async def test_tool_error_is_reported_as_an_error_response(self, tmp_path):
        async with dispatcher(tmp_path) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_CALL, "echo", "fail", "{}"))
        assert response.status == "error"
        assert response.exit_code == 1
        assert "boom" in response.error
        assert json.loads(response.output)["is_error"] is True

    async def test_unreachable_server_is_reported(self, tmp_path):
        async with dispatcher(
            tmp_path, servers=[("dead", {"args": [str(FIXTURE), "--exit-immediately"]})]
        ) as node:
            response = await node.execute(request(ToolType.MCP_TOOLS_CALL, "dead", "echo", "{}"))
        assert response.status == "denied"
        assert "MCP call failed" in response.error

    async def test_other_tool_types_are_refused(self, tmp_path):
        async with dispatcher(tmp_path) as node:
            response = await node.execute(request(ToolType.SHELL, "ls"))
        assert response.status == "denied"
        assert "Unsupported MCP tool" in response.error


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAudit:
    async def test_successful_call_writes_an_mcp_call_event(self, tmp_path):
        store = AuditStore(tmp_path / "audit.jsonl")
        # 哨兵要用不可能撞上路径/用户名的串：短串 "hi" 会出现在 tmp_path 的
        # 用户名里（例如 guzhujushi），让「参数值不入审计」的断言假失败。
        secret = "argument-value-must-not-be-audited"
        async with dispatcher(tmp_path, audit_store=store) as node:
            await node.execute(
                request(ToolType.MCP_TOOLS_CALL, "echo", "echo", json.dumps({"text": secret}))
            )

        events = store.read()
        assert len(events) == 1
        event = events[0]
        assert event["event_type"] == "mcp_call"
        assert event["tool"] == ToolType.MCP_TOOLS_CALL.value
        assert event["command"] == "echo.echo"
        assert event["action"] == "allowed"
        details = event["details"]
        assert details["server"] == "echo" and details["tool"] == "echo"
        assert details["ok"] is True and details["is_error"] is False
        assert details["duration_ms"] >= 0
        assert details["argument_keys"] == ["text"]
        # 参数值绝不入审计（可能含密钥）
        assert secret not in json.dumps(event, ensure_ascii=False)

    async def test_denied_call_is_audited_and_never_reaches_the_server(self, tmp_path):
        store = AuditStore(tmp_path / "audit.jsonl")
        node = build_dispatcher(
            tmp_path, servers=[("echo", {"deny_tools": ["delete*"]})], audit_store=store
        )
        try:
            denied = await node.execute(
                request(ToolType.MCP_TOOLS_CALL, "echo", "delete_everything", "{}")
            )
            assert denied.status == "denied"
            assert node.pool.clients == {}  # 策略拦下的调用不会拉起任何服务器
        finally:
            await node.close()

        event = store.read()[-1]
        assert event["action"] == "denied"
        assert event["details"]["ok"] is False
        assert event["details"]["duration_ms"] == 0
        assert "denied for server" in event["reason"]

    async def test_failed_call_records_the_error(self, tmp_path):
        store = AuditStore(tmp_path / "audit.jsonl")
        async with dispatcher(
            tmp_path, servers=[("dead", {"args": [str(FIXTURE), "--exit-immediately"]})],
            audit_store=store,
        ) as node:
            await node.execute(request(ToolType.MCP_TOOLS_CALL, "dead", "echo", "{}"))
        event = store.read()[0]
        assert event["details"]["ok"] is False
        assert event["action"] == "denied"
        assert "closed the connection" in event["reason"]

    async def test_audit_is_broadcast_on_the_event_bus(self, tmp_path):
        bus = FakeBus()
        async with dispatcher(tmp_path, event_bus=bus) as node:
            await node.execute(request(ToolType.MCP_TOOLS_CALL, "echo", "echo", '{"text": "x"}'))
            await asyncio.sleep(0.05)  # 广播是 fire-and-forget 任务
        assert bus.events and bus.events[0]["type"] == "audit.mcp_call"
        assert bus.events[0]["payload"]["command"] == "echo.echo"
        assert bus.events[0]["source"] == "mcp"


class TestGatewayWiring:
    def test_tool_gateway_binds_its_audit_sinks(self, tmp_path):
        from trimum_core.tool_gateway import ToolGateway

        store = AuditStore(tmp_path / "audit.jsonl")
        bus = FakeBus()
        gateway = ToolGateway(audit_store=store, event_bus=bus)
        node = gateway.dispatchers.get(ToolType.MCP_TOOLS_CALL)
        assert node is not None
        assert node.audit_store is store
        assert node.event_bus is bus


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    @pytest.fixture()
    def mcp_dir(self, tmp_path, monkeypatch):
        directory = tmp_path / "mcp"
        write_server(directory)
        monkeypatch.setenv(MCP_DIR_ENV, str(directory))
        return directory

    def test_list_json(self, mcp_dir, capsys):
        assert main(["--json", "mcp", "list"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["count"] == 1 and data["enabled"] == ["echo"]
        assert data["servers"][0]["transport"] == "stdio"

    def test_list_human_and_enabled_filter(self, mcp_dir, capsys):
        write_server(mcp_dir, "off", enabled=False)
        assert main(["mcp", "list", "--enabled"]) == 0
        out = capsys.readouterr().out
        assert "echo" in out and "off" not in out

    def test_paths_shows_the_override(self, mcp_dir, capsys):
        assert main(["mcp", "paths"]) == 0
        out = capsys.readouterr().out
        assert MCP_DIR_ENV in out and str(mcp_dir) in out

    def test_tools_lists_the_server_tools(self, mcp_dir, capsys):
        assert main(["mcp", "tools", "echo"]) == 0
        out = capsys.readouterr().out
        assert "echo (4 tools" in out and "delete_everything" in out

    def test_call_with_yes_runs_the_tool(self, mcp_dir, capsys):
        assert main(["mcp", "call", "echo", "echo", '{"text": "cli"}', "--yes"]) == 0
        out = capsys.readouterr().out
        assert "echo: cli" in out

    def test_call_without_yes_aborts(self, mcp_dir, capsys):
        assert main(["mcp", "call", "echo", "echo", '{"text": "cli"}']) == 1
        assert "aborted" in capsys.readouterr().err

    def test_tools_without_servers_fails(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(MCP_DIR_ENV, str(tmp_path / "empty"))
        assert main(["mcp", "tools"]) == 1
        assert "MCP" in capsys.readouterr().err

    def test_unknown_subcommand_prints_usage(self, mcp_dir, capsys):
        assert main(["mcp"]) == 0
        assert "usage: trm mcp" in capsys.readouterr().out