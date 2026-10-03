"""CLI tests for `trm exec --code` (E7 第 5 片 · B)."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.cli import main  # noqa: E402


@pytest.fixture
def fake_session(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    created = {}

    class FakeRecord:
        def __init__(self, ok=True):
            self.task = "改个东西"
            self.session_id = "sid123"
            self.cwd = "/tmp"
            self.dry_run = False
            self.steps = [{"kind": "run", "status": "ok"}]
            self.changes = []
            self.verifications = []
            self.started_at = ""
            self.ended_at = ""
            self.ok = ok
            self.reason = "" if ok else "step_failed"
            self.record_path = ""
            self.skills = []
            self.instructions = ""

        def to_dict(self):
            return {"task": self.task, "session_id": self.session_id, "cwd": self.cwd,
                    "dry_run": self.dry_run, "steps": self.steps, "changes": self.changes,
                    "verifications": self.verifications, "started_at": self.started_at,
                    "ended_at": self.ended_at, "ok": self.ok, "reason": self.reason,
                    "record_path": self.record_path, "skills": self.skills,
                    "instructions": self.instructions}

    class FakeSession:
        def __init__(self, task, **kwargs):
            created["task"] = task
            created["kwargs"] = kwargs
            self.record = FakeRecord()

        async def run(self):
            return self.record

    monkeypatch.setattr("trimum_core.coding_agent.CodingSession", FakeSession)
    return created


def _set_ok(monkeypatch, fake_session, ok):
    from trimum_core import coding_agent

    orig = coding_agent.CodingSession

    class Wrapped(orig):  # type: ignore[misc, valid-type]
        def __init__(self, task, **kwargs):
            super().__init__(task, **kwargs)
            self.record.ok = ok
            self.record.reason = "" if ok else "step_failed"

    monkeypatch.setattr("trimum_core.coding_agent.CodingSession", Wrapped)


def test_code_json_success(fake_session, monkeypatch, capsys):
    rc = main(["exec", "--code", "改个东西", "--yes", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    for key in ("session_id", "task", "steps", "changes", "verifications", "ok"):
        assert key in data
    kwargs = fake_session["kwargs"]
    assert kwargs["yes"] is True
    assert kwargs["dry_run"] is False
    assert kwargs["skill"] is None
    assert kwargs["agent_id"] == "trm-code"
    assert kwargs["cwd"] == os.getcwd()


def test_code_failed_record(fake_session, monkeypatch, capsys):
    _set_ok(monkeypatch, fake_session, ok=False)
    rc = main(["exec", "--code", "x"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "failed" in out


@pytest.mark.parametrize(
    "argv,checks",
    [
        (["exec", "--code", "x", "--dry-run", "--skill", "tdd", "--agent", "mine", "--timeout", "7"],
         {"dry_run": True, "skill": "tdd", "agent_id": "mine", "command_timeout": 7.0}),
    ],
)
def test_code_flag_passthrough(fake_session, monkeypatch, capsys, argv, checks):
    rc = main(argv)
    assert rc == 0
    kwargs = fake_session["kwargs"]
    for key, value in checks.items():
        if key == "dry_run":
            assert kwargs[key] is value
        else:
            assert kwargs[key] == value


@pytest.mark.parametrize("flag", ["--yes", "--dry-run", "--skill"])
def test_code_only_flags_rejected(fake_session, monkeypatch, capsys, flag):
    argv = ["exec", flag]
    if flag == "--skill":
        argv.append("tdd")
    argv += ["echo", "hi"]
    rc = main(argv)
    err = capsys.readouterr().err
    assert rc != 0
    assert "只在 --code 模式" in err
    assert fake_session == {} or "task" not in fake_session


def test_code_empty_task(fake_session, monkeypatch, capsys):
    rc = main(["exec", "--code", ""])
    err = capsys.readouterr().err
    assert rc != 0
    assert "usage: trm exec --code" in err


def test_code_no_model_error(fake_session, monkeypatch, capsys):
    from trimum_core import coding_agent

    class Boom(coding_agent.CodingSession):  # type: ignore[misc, valid-type]
        async def run(self):
            raise coding_agent.NoModelError("no model")

    monkeypatch.setattr("trimum_core.coding_agent.CodingSession", Boom)
    rc = main(["exec", "--code", "x"])
    err = capsys.readouterr().err
    assert rc != 0
    assert "无法开始" in err


def test_code_trimum_error(fake_session, monkeypatch, capsys):
    from trimum_core import coding_agent
    from trimum_core.models import TrimumError, TRMErrorCode

    class Boom(coding_agent.CodingSession):  # type: ignore[misc, valid-type]
        async def run(self):
            raise TrimumError(TRMErrorCode.RUNTIME_INIT_FAILED, message="boom 原文")

    monkeypatch.setattr("trimum_core.coding_agent.CodingSession", Boom)
    rc = main(["exec", "--code", "x"])
    err = capsys.readouterr().err
    assert rc != 0
    assert "boom 原文" in err


def _fake_gateway_execute(monkeypatch, captured):
    from trimum_core.models import ExecuteResponse

    async def fake_execute(self, request):
        captured["request"] = request
        return ExecuteResponse(status="success", exit_code=0, output="hi\n")

    from trimum_core.tool_gateway import ToolGateway

    monkeypatch.setattr(ToolGateway, "execute", fake_execute)


def test_shell_path_unchanged(monkeypatch, capsys):
    captured = {}
    _fake_gateway_execute(monkeypatch, captured)
    rc = main(["exec", "echo", "hi"])
    out = capsys.readouterr().out
    from trimum_core.models import SourceType, ToolType

    assert rc == 0
    assert "hi" in out
    req = captured["request"]
    assert req.agent_id == "trm-exec"
    assert req.args == ["echo", "hi"]
    assert req.tool == ToolType.SHELL
    assert req.source_type == SourceType.HUMAN


def test_shell_path_json(monkeypatch, capsys):
    captured = {}
    _fake_gateway_execute(monkeypatch, captured)
    rc = main(["exec", "echo", "hi", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert "exit_code" in data
    assert captured["request"].args == ["echo", "hi"]


def test_code_quiet(fake_session, monkeypatch, capsys):
    rc = main(["exec", "--code", "x", "--quiet"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == ""


def test_command_surface_unchanged():
    from trimum_core.cli.registry import check_commands, collect_commands

    assert check_commands() == []
    cmds = collect_commands()
    assert not any(c.path == ("code",) for c in cmds)
    assert any(c.path == ("exec",) for c in cmds)
    assert len({c.path[0] for c in cmds}) == 24  # 2026-10-02 加 trm events
    assert len(cmds) == 86  # 同步 trm events（原 85）


def test_render_code_shows_changes_and_verifications(monkeypatch, tmp_path, capsys):
    """需求 7：人读渲染必须真的打出 change（含差异/原因）与 verification（含失败清单）。"""
    from trimum_core import coding_agent
    from trimum_core.verifier import VerificationFailure, VerificationResult

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))

    class Record:
        task = "加个函数"
        session_id = "sid-render"
        cwd = "/tmp"
        dry_run = False
        steps = [{"kind": "edit", "status": "ok"}, {"kind": "run", "status": "denied"}]
        reason = "verification_red"
        ok = False
        record_path = ""
        skills = []
        instructions = ""

        def __init__(self):
            self.changes = [
                coding_agent.SessionChange(
                    path="a.py",
                    status="preview",
                    added_lines=2,
                    removed_lines=1,
                    difference="--- a\n+++ b\n+NEW_LINE\n-OLD_LINE",
                ),
                coding_agent.SessionChange(path="secret.pem", status="rejected", reason="protected path"),
            ]
            self.verifications = [
                VerificationResult(
                    kind="test",
                    command="pytest -q",
                    exit_code=1,
                    verdict="red",
                    failures=[VerificationFailure(file="tests/test_x.py", line=12, message="nope")],
                    evidence_lines=["1 failed"],
                )
            ]

        def to_dict(self):
            return {}

    class Session:
        def __init__(self, task, **kwargs):
            self.record = Record()

        async def run(self):
            return self.record

    monkeypatch.setattr("trimum_core.coding_agent.CodingSession", Session)
    rc = main(["exec", "--code", "加个函数"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "a.py" in out and "preview" in out and "+NEW_LINE" in out
    assert "secret.pem" in out and "rejected" in out and "protected path" in out
    assert "test red" in out and "pytest -q" in out
    assert "tests/test_x.py:12 nope" in out
    assert "结论: failed" in out
