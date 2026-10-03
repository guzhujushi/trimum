import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import coding_agent, llm_router, patch_ops, verifier
from trimum_core.llm_router import LlmCallError
from trimum_core.models import SourceType, ToolType, TRMErrorCode, TrimumError
from trimum_core.paths import trimum_path


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("TRIMUM_HOME", str(home))
    return home


class FakeResponse:
    def __init__(self, status="allowed", output="", error="", exit_code=0):
        self.status = status
        self.output = output
        self.error = error
        self.exit_code = exit_code
        self.timed_out = False


class FakeGateway:
    def __init__(self, response=None, responder=None):
        self.requests = []
        self.response = response
        self.responder = responder

    async def execute(self, request):
        self.requests.append(request)
        if self.responder is not None:
            return self.responder(request)
        return self.response or FakeResponse()


# ---------------------------------------------------------------- ① 只读任务


def test_readonly_run_step(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("hello\n", encoding="utf-8")
    gateway = FakeGateway()
    session = coding_agent.CodingSession(
        "看一下 note",
        cwd=str(tmp_path),
        gateway=gateway,
        planner=coding_agent.ScriptedPlanner(
            [{"kind": "run", "command": "cat note.txt"}, {"kind": "done"}]
        ),
        yes=False,
    )
    record = session.run.__wrapped__() if hasattr(session.run, "__wrapped__") else None
    import asyncio

    record = asyncio.run(session.run())
    assert record.ok is True
    assert record.changes == []
    assert note.read_text(encoding="utf-8") == "hello\n"
    req = gateway.requests[0]
    assert req.tool == ToolType.SHELL
    assert req.source_type == SourceType.AI
    assert list(req.args) == ["cat", "note.txt"]


# ---------------------------------------------------------------- ② 不带 yes 只预览


def test_edit_without_yes_only_preview(tmp_path):
    target = tmp_path / "f.txt"
    original = target.read_bytes() if target.exists() else None
    target.write_text("alpha ALPHA line\n", encoding="utf-8")
    original = target.read_bytes()
    gateway = FakeGateway()

    def make(yes, dry_run):
        return coding_agent.CodingSession(
            "改一下",
            cwd=str(tmp_path),
            gateway=gateway,
            planner=coding_agent.ScriptedPlanner(
                [{"kind": "edit", "path": str(target), "anchor": "ALPHA",
                  "replacement": "BETA", "reason": "改名"}, {"kind": "done"}]
            ),
            yes=yes,
            dry_run=dry_run,
        )

    import asyncio

    record = asyncio.run(make(yes=False, dry_run=False).run())
    assert record.changes[0].status == coding_agent.CHANGE_PREVIEW
    assert target.read_bytes() == original
    assert record.changes[0].snapshot_id is None

    record2 = asyncio.run(make(yes=True, dry_run=True).run())
    assert record2.changes[0].status == coding_agent.CHANGE_PREVIEW
    assert target.read_bytes() == original


# ---------------------------------------------------------------- ③ 落盘 + 回滚


def test_edit_applied_and_rollback(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("alpha ALPHA line\n", encoding="utf-8")
    original = target.read_bytes()
    gateway = FakeGateway()
    session = coding_agent.CodingSession(
        "改一下",
        cwd=str(tmp_path),
        gateway=gateway,
        session_id="sid-abc",
        planner=coding_agent.ScriptedPlanner(
            [{"kind": "edit", "path": str(target), "anchor": "ALPHA",
              "replacement": "BETA", "reason": "改名"}, {"kind": "done"}]
        ),
        yes=True,
    )
    import asyncio

    record = asyncio.run(session.run())
    assert record.changes[0].status == coding_agent.CHANGE_APPLIED
    assert "BETA" in target.read_text(encoding="utf-8")
    assert record.changes[0].snapshot_id is not None
    assert record.ok is True

    restored = patch_ops.rollback(record.session_id)
    assert str(target) in [str(p) for p in restored]
    assert target.read_bytes() == original

    session_dir = trimum_path("sessions", record.session_id)
    assert (session_dir / "session.json").is_file()
    assert (session_dir / "coding.json").is_file()


# ---------------------------------------------------------------- ④ 保护路径


def test_protected_path_rejected(tmp_path):
    secret = tmp_path / "secret.pem"
    secret.write_text("PEM DATA\n", encoding="utf-8")
    gateway = FakeGateway()
    session = coding_agent.CodingSession(
        "改 secret",
        cwd=str(tmp_path),
        gateway=gateway,
        planner=coding_agent.ScriptedPlanner(
            [{"kind": "edit", "path": str(secret), "anchor": "PEM DATA",
              "replacement": "XXX", "reason": "不该动"}, {"kind": "done"}]
        ),
        yes=True,
    )
    import asyncio

    record = asyncio.run(session.run())
    assert record.changes[0].status == coding_agent.CHANGE_REJECTED
    assert record.ok is False
    assert record.reason == coding_agent.REASON_CHANGE_REJECTED


# ---------------------------------------------------------------- ⑤ 锚点不唯一


def test_anchor_not_unique_rejected(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("ALPHA ALPHA\n", encoding="utf-8")
    original = target.read_bytes()
    gateway = FakeGateway()
    session = coding_agent.CodingSession(
        "改",
        cwd=str(tmp_path),
        gateway=gateway,
        planner=coding_agent.ScriptedPlanner(
            [{"kind": "edit", "path": str(target), "anchor": "ALPHA",
              "replacement": "BETA"}, {"kind": "done"}]
        ),
        yes=True,
    )
    import asyncio

    record = asyncio.run(session.run())
    assert record.changes[0].status == coding_agent.CHANGE_REJECTED
    assert target.read_bytes() == original


# ---------------------------------------------------------------- ⑥ 验证红/绿/unknown


def _make_verify_session(tmp_path, response):
    target = tmp_path / "f.txt"
    target.write_text("ALPHA\n", encoding="utf-8")
    gateway = FakeGateway(response=response)
    spec = verifier.VerificationSpec(
        kind=verifier.KIND_TEST, command=["pytest", "-q"], parser="pytest"
    )
    return coding_agent.CodingSession(
        "改",
        cwd=str(tmp_path),
        gateway=gateway,
        planner=coding_agent.ScriptedPlanner(
            [{"kind": "edit", "path": str(target), "anchor": "ALPHA",
              "replacement": "BETA"}, {"kind": "done"}]
        ),
        yes=True,
        specs=[spec],
    ), target


def test_verification_red(tmp_path):
    resp = FakeResponse(
        exit_code=1,
        output="FAILED tests/x.py::test_a - AssertionError: nope\ntests/x.py:12: AssertionError\n",
    )
    session, _ = _make_verify_session(tmp_path, resp)
    import asyncio

    record = asyncio.run(session.run())
    assert record.verifications[0].verdict == verifier.VERDICT_RED
    assert record.ok is False
    assert record.reason == coding_agent.REASON_VERIFICATION_RED


def test_verification_green(tmp_path):
    session, _ = _make_verify_session(tmp_path, FakeResponse(exit_code=0, output=""))
    import asyncio

    record = asyncio.run(session.run())
    assert record.verifications[0].verdict == verifier.VERDICT_GREEN
    assert record.ok is True


def test_verification_unknown_denied(tmp_path):
    session, _ = _make_verify_session(tmp_path, FakeResponse(status="denied"))
    import asyncio

    record = asyncio.run(session.run())
    assert record.verifications[0].verdict == verifier.VERDICT_UNKNOWN
    assert record.ok is False


# ---------------------------------------------------------------- ⑦ 迭代上限


def test_iteration_cap(tmp_path):
    gateway = FakeGateway()
    session = coding_agent.CodingSession(
        "永远在跑",
        cwd=str(tmp_path),
        gateway=gateway,
        planner=coding_agent.ScriptedPlanner(
            [{"kind": "run", "command": "echo 1"}, {"kind": "run", "command": "echo 2"}]
        ),
        max_iterations=2,
    )
    import asyncio

    record = asyncio.run(session.run())
    assert record.ok is False
    assert record.reason == coding_agent.REASON_ITERATION_CAP


# ---------------------------------------------------------------- ⑧ --skill


def _write_skill(skill_dir: Path, name: str):
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\nkeywords: [{name}]\n---\n\nbody of {name}\n",
        encoding="utf-8",
    )


def test_skill_filter(tmp_path):
    _write_skill(tmp_path / "skills" / "alpha", "alpha")
    _write_skill(tmp_path / "skills" / "beta", "beta")
    gateway = FakeGateway()
    session = coding_agent.CodingSession(
        "任务涉及 alpha 关键词的处理",
        cwd=str(tmp_path),
        gateway=gateway,
        planner=coding_agent.ScriptedPlanner([{"kind": "done"}]),
        skill="alpha",
        roots=[tmp_path / "skills"],
    )
    import asyncio

    record = asyncio.run(session.run())
    assert record.skills == ["alpha"]
    assert "body of alpha" in record.instructions
    assert "beta" not in record.instructions


def test_skill_not_found(tmp_path):
    gateway = FakeGateway()
    session = coding_agent.CodingSession(
        "随便",
        cwd=str(tmp_path),
        gateway=gateway,
        planner=coding_agent.ScriptedPlanner([{"kind": "done"}]),
        skill="no-such",
        roots=[tmp_path / "skills"],
    )
    import asyncio

    with pytest.raises(TrimumError) as excinfo:
        asyncio.run(session.run())
    assert "skill not found" in str(excinfo.value)


# ---------------------------------------------------------------- ⑨ plan_step_with_llm


def test_plan_step_with_llm_no_model(monkeypatch):
    async def fake(role, attempt, *, targets=None, defaults=None, fallback=None):
        raise LlmCallError("agent", [], 0)

    monkeypatch.setattr(llm_router, "arun_with_fallback", fake)
    import asyncio

    with pytest.raises(coding_agent.NoModelError):
        asyncio.run(coding_agent.plan_step_with_llm("任务", []))


def test_plan_step_with_llm_parses_json(monkeypatch):
    async def fake(role, attempt, *, targets=None, defaults=None, fallback=None):
        return ('```json\n{"kind":"run","command":"ls"}\n```', None)

    monkeypatch.setattr(llm_router, "arun_with_fallback", fake)
    import asyncio

    step = asyncio.run(coding_agent.plan_step_with_llm("任务", []))
    assert step.kind == "run"
    assert step.command == "ls"


# ---------------------------------------------------------------- ⑩ 收尾


def test_planner_exhausted_returns_none_and_record_serializable(tmp_path):
    gateway = FakeGateway()
    session = coding_agent.CodingSession(
        "收尾",
        cwd=str(tmp_path),
        gateway=gateway,
        planner=coding_agent.ScriptedPlanner([{"kind": "done"}]),
    )
    import asyncio

    planner = session._planner
    got = asyncio.run(planner("t", []))
    assert got.kind == "done"
    assert asyncio.run(planner("t", [])) is None

    record = asyncio.run(session.run())
    dumped = json.dumps(record.to_dict())
    assert dumped
    out = Path(record.record_path)
    assert out.is_file()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["session_id"] == record.session_id
    assert loaded["ok"] is True


# ------------------------------------------------ ⑪ 会话 cwd 必须对 run/edit 生效


def test_run_step_carries_session_cwd(tmp_path):
    """run 步必须把会话 cwd 传给网关（否则 `cat note.txt` 会落到调用方进程目录）。"""
    import asyncio

    gateway = FakeGateway()
    session = coding_agent.CodingSession(
        "看一眼 note",
        cwd=str(tmp_path),
        gateway=gateway,
        planner=coding_agent.ScriptedPlanner(
            [{"kind": "run", "command": "cat note.txt"}, {"kind": "done"}]
        ),
    )
    record = asyncio.run(session.run())
    assert record.ok is True
    assert gateway.requests[0].cwd == str(tmp_path)


def test_edit_step_relative_path_anchors_at_session_cwd(tmp_path, monkeypatch):
    """edit 步的相对路径锚在会话 cwd（与 run / 验证同一口径），不是进程 cwd。"""
    import asyncio

    monkeypatch.chdir(tmp_path.parent)
    target = tmp_path / "note.txt"
    target.write_text("ALPHA\n", encoding="utf-8")
    session = coding_agent.CodingSession(
        "改名",
        cwd=str(tmp_path),
        planner=coding_agent.ScriptedPlanner(
            [
                {"kind": "edit", "path": "note.txt", "anchor": "ALPHA", "replacement": "BETA"},
                {"kind": "done"},
            ]
        ),
        yes=True,
    )
    record = asyncio.run(session.run())
    assert record.changes[0].status == "applied"
    assert record.steps[0]["path"] == str(target)
    assert target.read_text(encoding="utf-8") == "BETA\n"
    assert not (tmp_path.parent / "note.txt").exists()
