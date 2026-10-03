"""E7 自研编码智能体 · 第 2 片 —— 验证闭环（``trimum_core.verifier``）。

覆盖五条判定路径（绿 / 红 / 命令不存在 / 超时 / 被拒）、四种探测（含
``.venv/bin/python`` 优先与 ``tests/`` 不存在不误判）、空目录返回 ``[]``、
pytest 失败解析的三条抽取规则与「不重复记」、generic 诚实降级、证据行上限
与 400 字符截断、执行者抛异常 → unknown、``outcome_from_response`` 的四种
映射，以及一条红线用例（源码不得出现 subprocess / os.system / popen）。

全程只用 ``tmp_path`` 造目录，不碰真实文件系统。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import verifier
from trimum_core.verifier import (
    VERDICT_GREEN,
    VERDICT_RED,
    VERDICT_UNKNOWN,
    CommandOutcome,
    VerificationSpec,
    detect_project_specs,
    outcome_from_response,
    parse_failures,
    parse_pytest_failures,
    run_verification,
    verdict_from_outcome,
)

PYTEST_FAIL_OUTPUT = """============================= FAILURES =============================
_______ TestCalc.test_add _______

    def test_add(self):
>       assert 1 + 1 == 3
E       AssertionError: boom

tests/test_x.py:123: AssertionError
========================== short test summary info ==================
FAILED tests/test_x.py::TestCalc::test_add - AssertionError: boom
======================== 1 failed in 0.02s =========================
"""


def _spec(parser="generic"):
    return VerificationSpec(kind="test", command=["echo", "hi"], parser=parser)


def _executor(outcome):
    def _exec(spec, cwd):
        return outcome
    return _exec


# ---------- 五条判定路径 ----------

def test_green_path():
    res = run_verification(_spec(), cwd="/tmp/x", executor=_executor(CommandOutcome(exit_code=0, stdout="ok\n")))
    assert res.verdict == "green"
    assert res.reason == ""
    assert res.exit_code == 0


def test_red_path_with_failures():
    res = run_verification(
        _spec(parser="pytest"),
        cwd="/tmp/x",
        executor=_executor(CommandOutcome(exit_code=1, stdout=PYTEST_FAIL_OUTPUT)),
    )
    assert res.verdict == "red"
    assert res.reason == ""
    assert len(res.failures) == 1


def test_command_missing_is_unknown_not_green():
    res = run_verification(
        _spec(),
        cwd="/tmp/x",
        executor=_executor(CommandOutcome(exit_code=None)),
    )
    assert res.verdict == "unknown"
    assert res.verdict != "green"
    assert res.reason != ""
    assert res.exit_code is None


def test_timeout_is_unknown():
    res = run_verification(
        _spec(),
        cwd="/tmp/x",
        executor=_executor(CommandOutcome(exit_code=1, timed_out=True)),
    )
    assert res.verdict == "unknown"
    assert res.reason != ""


def test_denied_is_unknown_not_green():
    res = run_verification(
        _spec(),
        cwd="/tmp/x",
        executor=_executor(CommandOutcome(exit_code=0, denied=True)),
    )
    assert res.verdict == "unknown"
    assert res.verdict != "green"
    assert res.reason != ""


# ---------- 探测 ----------

def test_detect_pytest_prefers_venv(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    specs = detect_project_specs(tmp_path)
    assert len(specs) == 1
    assert specs[0].parser == "pytest"
    assert specs[0].source == "pyproject.toml"
    assert specs[0].command == [str(tmp_path / ".venv" / "bin" / "python"), "-m", "pytest", "-q"]


def test_detect_pytest_falls_back_to_python(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_a.py").write_text("x = 1\n", encoding="utf-8")
    specs = detect_project_specs(tmp_path)
    assert len(specs) == 1
    assert specs[0].source == "pytest.ini"
    assert specs[0].command == ["python", "-m", "pytest", "-q"]


def test_detect_pytest_marker_without_test_layout_is_ignored(tmp_path):
    # 有 pyproject.toml 但既无 tests/ 也无 test_*.py ⇒ 不误判
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert detect_project_specs(tmp_path) == []


def test_detect_marker_source_first_hit_order(tmp_path):
    (tmp_path / "setup.cfg").write_text("[tool:pytest]\n", encoding="utf-8")
    (tmp_path / "tox.ini").write_text("[tox]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    specs = detect_project_specs(tmp_path)
    assert specs[0].source == "setup.cfg"


def test_detect_multiple_languages(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    specs = detect_project_specs(tmp_path)
    assert [s.source for s in specs] == ["pyproject.toml", "Cargo.toml", "go.mod", "package.json"]
    assert [s.command for s in specs] == [
        ["python", "-m", "pytest", "-q"],
        ["cargo", "test"],
        ["go", "test", "./..."],
        ["npm", "test"],
    ]
    assert all(s.kind == "test" for s in specs)


def test_detect_empty_dir_returns_empty(tmp_path):
    assert detect_project_specs(tmp_path) == []


# ---------- pytest 失败解析 ----------

def test_parse_pytest_file_line_message():
    failures = parse_pytest_failures(PYTEST_FAIL_OUTPUT)
    assert len(failures) == 1
    f = failures[0]
    assert f.file == "tests/test_x.py"
    assert f.line == 123
    assert f.message == "AssertionError: boom"


def test_parse_pytest_message_empty_when_no_dash():
    out = "FAILED tests/test_y.py::Test::go\n"
    failures = parse_pytest_failures(out)
    assert failures[0].file == "tests/test_y.py"
    assert failures[0].message == ""
    assert failures[0].line is None


def test_parse_pytest_strips_leading_slash():
    out = "FAILED /abs/path/tests/test_z.py::f - ValueError: bad\n"
    failures = parse_pytest_failures(out)
    assert failures[0].file == "abs/path/tests/test_z.py"
    assert failures[0].message == "ValueError: bad"


def test_parse_pytest_error_and_no_duplicate():
    out = (
        "ERROR tests/test_e.py::setup - RuntimeError: no\n"
        "FAILED tests/test_x.py::TestCalc::test_add - AssertionError: boom\n"
        "FAILED tests/test_x.py::TestCalc::test_add - AssertionError: boom\n"
    )
    failures = parse_pytest_failures(out)
    assert len(failures) == 2
    assert failures[0].file == "tests/test_e.py"
    assert failures[0].message == "RuntimeError: no"
    assert failures[1].message == "AssertionError: boom"


def test_parse_pytest_two_failures_same_file_get_their_own_lines():
    """同一文件两处失败：行号按序各自对应，不能都给第一个。"""
    out = (
        "tests/test_two.py:2: in test_a\n    assert 0\nE   assert 0\n"
        "tests/test_two.py:7: in test_b\n    assert 0\nE   assert 0\n"
        "=================== short test summary info ====================\n"
        "FAILED tests/test_two.py::test_a - assert 0\n"
        "FAILED tests/test_two.py::test_b - assert 0\n"
    )
    failures = parse_pytest_failures(out)
    assert [f.line for f in failures] == [2, 7]
    assert [f.message for f in failures] == ["assert 0", "assert 0"]


def test_parse_pytest_two_files_get_their_own_lines():
    """两个文件失败：各自拿到自己文件的行号，不串号。"""
    out = (
        "tests/test_a.py:6: in test_a\nE   assert 0\n"
        "tests/test_b.py:8: in test_b\nE   assert 0\n"
        "FAILED tests/test_a.py::test_a - boom\n"
        "FAILED tests/test_b.py::test_b - boom\n"
    )
    failures = parse_pytest_failures(out)
    assert [(f.file, f.line) for f in failures] == [
        ("tests/test_a.py", 6),
        ("tests/test_b.py", 8),
    ]


def test_parse_pytest_line_is_none_when_no_loc_line():
    """输出里没有该文件的 `<file>:<数字>:` 时给 None，而不是借用别人的行号。"""
    out = (
        "tests/test_other.py:9: in test_other\nE   assert 0\n"
        "FAILED tests/test_missing.py::test_x - no loc\n"
    )
    failures = parse_pytest_failures(out)
    assert failures[0].file == "tests/test_missing.py"
    assert failures[0].line is None


def test_evidence_line_truncation_boundary_400():
    """恰好 400 字符不截断；401 字符才截断成 400 + '…'。"""
    res = run_verification(
        _spec(),
        cwd="/tmp/x",
        executor=_executor(
            CommandOutcome(exit_code=0, stdout="a" * 400 + "\n" + "b" * 401 + "\n")
        ),
    )
    assert len(res.evidence_lines[0]) == 400
    assert not res.evidence_lines[0].endswith("…")
    assert len(res.evidence_lines[1]) == 401
    assert res.evidence_lines[1].endswith("…")


def test_parse_failures_generic_returns_empty():
    assert parse_failures("generic", PYTEST_FAIL_OUTPUT) == []
    assert parse_failures("whatever", "FAILED x") == []


# ---------- 证据行 ----------

def test_evidence_line_cap():
    out = "\n".join(f"line{i}" for i in range(100)) + "\n"
    res = run_verification(
        _spec(),
        cwd="/tmp/x",
        executor=_executor(CommandOutcome(exit_code=0, stdout=out)),
    )
    assert len(res.evidence_lines) == 40
    assert res.evidence_lines[-1] == "line99"
    assert res.evidence_lines[0] == "line60"


def test_evidence_line_truncation_400():
    long = "a" * 500
    res = run_verification(
        _spec(),
        cwd="/tmp/x",
        executor=_executor(CommandOutcome(exit_code=0, stdout=long + "\nshort\n")),
    )
    assert res.evidence_lines[0] == "a" * 400 + "…"
    assert len(res.evidence_lines[0]) == 401


def test_evidence_empty_when_no_output():
    res = run_verification(_spec(), cwd="/tmp/x", executor=_executor(CommandOutcome(exit_code=0)))
    assert res.evidence_lines == []


# ---------- 执行者异常 ----------

def test_executor_exception_is_unknown():
    def boom(spec, cwd):
        raise RuntimeError("kaboom")

    res = run_verification(_spec(), cwd="/tmp/x", executor=boom)
    assert res.verdict == "unknown"
    assert "kaboom" in res.reason
    assert res.exit_code is None
    assert res.failures == []
    assert res.evidence_lines == []


# ---------- outcome_from_response ----------

class _Resp:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_outcome_from_response_denied():
    oc = outcome_from_response(_Resp(status="denied"))
    assert oc.denied is True
    assert oc.exit_code is None
    assert oc.stdout == ""
    assert oc.stderr == ""
    assert oc.timed_out is False


def test_outcome_from_response_full():
    oc = outcome_from_response(_Resp(status="done", output="out\n", error="err\n", exit_code=2, timed_out=True))
    assert oc.denied is False
    assert oc.stdout == "out\n"
    assert oc.stderr == "err\n"
    assert oc.exit_code == 2
    assert oc.timed_out is True


def test_outcome_from_response_plain_object_missing_fields():
    class Plain:
        output = "hello"

    oc = outcome_from_response(Plain())
    assert oc.denied is False
    assert oc.stdout == "hello"
    assert oc.stderr == ""
    assert oc.exit_code is None
    assert oc.timed_out is False


def test_outcome_from_response_none_falsy_fields():
    oc = outcome_from_response(_Resp(output=None, error=None, exit_code=None))
    assert oc.stdout == ""
    assert oc.stderr == ""
    assert oc.exit_code is None


# ---------- verdict_from_outcome 直接规则 ----------

def test_verdict_from_outcome_rules():
    assert verdict_from_outcome(CommandOutcome(exit_code=0)) == (VERDICT_GREEN, "")
    assert verdict_from_outcome(CommandOutcome(exit_code=1)) == (VERDICT_RED, "")
    assert verdict_from_outcome(CommandOutcome(exit_code=2)) == (VERDICT_RED, "")
    assert verdict_from_outcome(CommandOutcome(exit_code=None))[0] == VERDICT_UNKNOWN
    assert verdict_from_outcome(CommandOutcome(denied=True))[0] == VERDICT_UNKNOWN
    assert verdict_from_outcome(CommandOutcome(timed_out=True))[0] == VERDICT_UNKNOWN


# ---------- 红线 ----------

def test_verifier_source_has_no_process_spawning():
    src = inspect.getsource(verifier)
    for banned in ("subprocess", "os.system", "popen"):
        assert banned not in src, f"红线：verifier 源码出现 {banned!r}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "--basetemp", "tmp/pytest-tmp", "-p", "no:cacheprovider"]))
