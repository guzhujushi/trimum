"""审计结构化查询与 EventBus 广播测试（Phase 3 收尾 P1）。"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.audit_store import AuditStore
from trimum_core.cli.commands import log as log_cmd
from trimum_core.event_bus import EventBus
from trimum_core.models import (
    AuditEvent,
    ExecuteRequest,
    SourceType,
    ToolType,
)
from trimum_core.tool_gateway import ToolGateway


def event(event_type="tool_executed", agent="t", risk="low", command="echo hi", ts=None):
    return AuditEvent(
        event_id="e1",
        event_type=event_type,
        agent_id=agent,
        tool="shell",
        command=command,
        risk=risk,
        action="auto",
        reason="r",
        timestamp=ts if ts is not None else time.time(),
    )


class TestAuditStore:
    def test_append_and_read_roundtrip(self, tmp_path):
        store = AuditStore(tmp_path / "audit.jsonl")
        assert store.append(event()) is True
        events = store.read()
        assert len(events) == 1
        assert events[0]["command"] == "echo hi"

    def test_missing_file_returns_empty(self, tmp_path):
        assert AuditStore(tmp_path / "nope.jsonl").read() == []

    def test_bad_lines_are_skipped(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        store = AuditStore(path)
        store.append(event())
        with path.open("a", encoding="utf-8") as fh:
            fh.write("not json\n\n")
        assert len(store.read()) == 1

    def test_query_filters(self, tmp_path):
        store = AuditStore(tmp_path / "audit.jsonl")
        now = time.time()
        store.append(event(event_type="tool_executed", agent="a", ts=now))
        store.append(event(event_type="policy_denied", agent="a", risk="high", ts=now - 100))
        store.append(event(event_type="tool_executed", agent="b", ts=now - 200))

        assert len(store.query()) == 3
        assert len(store.query(event_type="tool_executed")) == 2
        assert len(store.query(agent_id="a")) == 2
        assert len(store.query(risk="high")) == 1
        assert len(store.query(since=now - 50)) == 1

    def test_query_returns_most_recent_with_limit(self, tmp_path):
        store = AuditStore(tmp_path / "audit.jsonl")
        for i in range(5):
            store.append(event(command=f"cmd-{i}"))

        recent = store.query(limit=2)
        assert [e["command"] for e in recent] == ["cmd-3", "cmd-4"]

    def test_rotation_keeps_one_backup(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        store = AuditStore(path, max_bytes=200)
        for i in range(6):
            store.append(event(command="x" * 40 + str(i)))

        assert path.exists()
        assert (tmp_path / "audit.jsonl.1").exists()
        assert len(store.read()) < 6


class TestGatewayAuditEmission:
    @pytest.mark.asyncio
    async def test_audit_written_to_store_and_event_bus(self, tmp_path):
        seen = []
        bus = EventBus()
        bus.subscribe("task.audit.*", lambda ev: seen.append(ev))

        store = AuditStore(tmp_path / "audit.jsonl")
        gw = ToolGateway(audit_store=store, event_bus=bus)
        req = ExecuteRequest(
            tool=ToolType.SHELL,
            args=["echo", "audited"],
            agent_id="t",
            source_type=SourceType.AI,
            skip_cwd_check=True,
        )
        await gw.execute(req)
        await asyncio.sleep(0.05)

        events = store.read()
        assert events and events[0]["event_type"] == "tool_executed"
        assert events[0]["command"] == "echo audited"

        types = [e.event_type for e in seen]
        assert "task.audit.tool_executed" in types
        assert seen[0].source == "tool_gateway"

    @pytest.mark.asyncio
    async def test_denied_event_is_warning_severity(self, tmp_path):
        seen = []
        bus = EventBus()
        bus.subscribe("task.audit.*", lambda ev: seen.append(ev))

        class DenyRule:
            async def can_execute(self, agent_id, command, sandbox="default", resource_ctx=None, source_type=None):
                from trimum_core.security_rule import DecisionResult

                return DecisionResult("deny", "nope", risk_level="high")

        gw = ToolGateway(security_rule=DenyRule(), event_bus=bus, audit_store=AuditStore(tmp_path / "a.jsonl"))
        req = ExecuteRequest(
            tool=ToolType.SHELL,
            args=["echo", "x"],
            agent_id="t",
            source_type=SourceType.AI,
            skip_cwd_check=True,
        )
        await gw.execute(req)
        await asyncio.sleep(0.05)

        assert [e.event_type for e in seen] == ["task.audit.security_blocked"]
        assert seen[0].severity.value == "warning"

    @pytest.mark.asyncio
    async def test_no_event_bus_is_safe(self):
        gw = ToolGateway()
        req = ExecuteRequest(
            tool=ToolType.SHELL,
            args=["echo", "hi"],
            agent_id="t",
            source_type=SourceType.AI,
            skip_cwd_check=True,
        )
        resp = await gw.execute(req)
        assert resp.status in ("allowed", "confirmed")


class TestLogAuditCommand:
    def _run(self, monkeypatch, tmp_path, argv):
        store = AuditStore(tmp_path / "audit.jsonl")
        store.append(event(event_type="tool_executed", agent="a", command="echo one"))
        store.append(
            event(event_type="policy_denied", agent="b", risk="high", command="rm -rf /")
        )
        monkeypatch.setattr(log_cmd, "AuditStore", lambda *a, **k: store)

        from trimum_core.cli import parser as cli_parser

        parser = cli_parser.build_parser()
        args = parser.parse_args(argv)
        return log_cmd.handler(args)

    def test_human_output_lists_events(self, monkeypatch, tmp_path, capsys):
        rc = self._run(monkeypatch, tmp_path, ["log", "audit"])
        out = capsys.readouterr().out

        assert rc == 0
        assert "tool_executed" in out
        assert "policy_denied" in out
        assert "rm -rf /" in out

    def test_json_output(self, monkeypatch, tmp_path, capsys):
        rc = self._run(monkeypatch, tmp_path, ["log", "audit", "--json"])
        out = capsys.readouterr().out

        assert rc == 0
        payload = json.loads(out)
        assert [e["event_type"] for e in payload] == ["tool_executed", "policy_denied"]

    def test_event_type_filter(self, monkeypatch, tmp_path, capsys):
        rc = self._run(monkeypatch, tmp_path, ["log", "audit", "--event-type", "policy_denied"])
        out = capsys.readouterr().out

        assert rc == 0
        assert "policy_denied" in out
        assert "tool_executed" not in out

    def test_risk_filter(self, monkeypatch, tmp_path, capsys):
        rc = self._run(monkeypatch, tmp_path, ["log", "audit", "--risk", "high"])
        out = capsys.readouterr().out

        assert rc == 0
        assert "rm -rf /" in out
        assert "echo one" not in out

    def test_no_match_message(self, monkeypatch, tmp_path, capsys):
        rc = self._run(monkeypatch, tmp_path, ["log", "audit", "--agent", "zzz"])
        out = capsys.readouterr().out

        assert rc == 0
        assert "no audit events matched" in out

    def test_falls_back_to_text_log_when_audit_file_missing(self, monkeypatch, tmp_path, capsys):
        text_log = tmp_path / "trimum.log"
        text_log.write_text(
            json.dumps({"timestamp": time.time(), "event": "gateway.audit", "event_type": "tool_executed"}) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(log_cmd, "AuditStore", lambda *a, **k: AuditStore(tmp_path / "missing.jsonl"))
        monkeypatch.setattr(log_cmd, "_log_path", lambda: text_log)

        from trimum_core.cli import parser as cli_parser

        args = cli_parser.build_parser().parse_args(["log", "audit", "--json"])
        rc = log_cmd.handler(args)
        out = capsys.readouterr().out

        assert rc == 0
        assert "gateway.audit" in out