"""Tests for `trm completion <bash|zsh|fish>`."""

from __future__ import annotations

import inspect
import io
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.cli import __main__ as cli_main  # noqa: E402
from trimum_core.cli.commands import completion as completion_mod  # noqa: E402
from trimum_core.cli.registry import CommandInfo, check_commands, collect_commands  # noqa: E402

SHELLS = ("bash", "zsh", "fish")


def _main(argv: list[str]) -> int:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli_main.main(argv)
    return code, buffer.getvalue()


def _registry_names():
    infos = collect_commands()
    top = sorted({info.path[0] for info in infos if info.path})
    group_subs = {}
    for info in infos:
        if len(info.path) == 2:
            group_subs.setdefault(info.path[0], set()).add(info.path[1])
    return top, {name: sorted(subs) for name, subs in group_subs.items()}


@pytest.mark.parametrize("shell", SHELLS)
def test_main_prints_script(shell):
    code, out = _main(["completion", shell])
    assert code == 0
    assert out.strip()
    assert out.isascii()
    assert out.endswith("\n")


@pytest.mark.parametrize("shell", SHELLS)
def test_script_matches_registry(shell):
    _, script = _main(["completion", shell])
    top, group_subs = _registry_names()
    for name in top:
        assert name in script
    for group, subs in group_subs.items():
        assert group in script
        for sub in subs:
            assert sub in script
    # spec-named routes: `ask`, `workflow submit`, `memory import`
    assert "ask" in script
    assert "submit" in script
    assert "import" in script


def test_script_is_computed_not_cached(monkeypatch):
    fake = [
        CommandInfo(path=("zzz",), kind="command", summary="x", has_handler=True),
        CommandInfo(path=("zzz", "yyy"), kind="command", summary="y", has_handler=True),
    ]
    monkeypatch.setattr(completion_mod, "collect_commands", lambda: fake)
    script = completion_mod.build_script("bash")
    assert "zzz" in script
    assert "yyy" in script
    assert "memory" not in script
    assert "workflow" not in script


@pytest.mark.parametrize("shell", SHELLS)
def test_real_syntax_check(shell):
    _, script = _main(["completion", shell])
    binary = shutil.which(shell)
    if shell == "fish":
        if binary is not None:
            # fish present: run a real syntax check
            result = subprocess.run([binary, "-n"], input=script, text=True, capture_output=True)
            assert result.returncode == 0, result.stderr
            assert script.strip()
        else:
            # no fish binary on this machine: fall back to static assertions
            assert script.startswith("complete -c trm")
            assert "__fish_use_subcommand" in script
    else:
        assert binary is not None
        result = subprocess.run([shell, "-n"], input=script, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr


def test_unknown_shell_argument_fails():
    with pytest.raises(SystemExit) as exc:
        _main(["completion"])
    assert exc.value.code not in (0, None)
    with pytest.raises(SystemExit) as exc:
        _main(["completion", "powershell"])
    assert exc.value.code not in (0, None)


def test_build_script_unknown_shell_raises():
    with pytest.raises(ValueError):
        completion_mod.build_script("nope")


def test_module_is_string_only():
    source = inspect.getsource(completion_mod)
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "popen" not in source


def test_command_contract_still_holds():
    assert check_commands() == []


def test_zsh_no_double_quote_and_array_literal():
    _, zsh_script = _main(["completion", "zsh"])
    assert "\"\"" not in zsh_script
    assert "cmds=(" in zsh_script
    assert "$words[1]" in zsh_script
    assert "$words[2]" not in zsh_script


def test_zsh_harness_control():
    """Prove the harness can see a real zsh array as pipe-joined items (not a string)."""
    zsh_bin = shutil.which("zsh")
    assert zsh_bin is not None, "zsh not found on this machine"
    code = (
        "_describe(){ print -r -- \"DESCRIBE:$1:${(j:|:)@[2,-1]}\"; }\n"
        "arr=(a b)\n"
        "_describe command $arr"
    )
    result = subprocess.run([zsh_bin, "-c", code], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "DESCRIBE:command:a|b" in result.stdout


def test_zsh_harness_cmds_state(tmp_path):
    """Real zsh: state=cmds must _describe a real array containing ask & workflow."""
    zsh_bin = shutil.which("zsh")
    assert zsh_bin is not None, "zsh not found on this machine"
    _, zsh_script = _main(["completion", "zsh"])
    script_path = tmp_path / "trm_zsh.zsh"
    script_path.write_text(zsh_script, encoding="utf-8")
    harness = (
        "_describe() { local an=$2 out=\"\" i; for i in ${${(P)an}}; do out+=\"${i}|\"; done; print -r -- \"DESCRIBE:$1:${out%|}\"; }\n"
        "_values()   { print -r -- \"VALUES:$1:${(j:|:)@[2,-1]}\"; }\n"
        "_arguments(){ :; }\n"
        "compdef()   { :; }\n"
        f"source {script_path}\n"
        "state=cmds\n"
        "words=(trm)\n"
        "current=2\n"
        "_trm"
    )
    result = subprocess.run([zsh_bin, "-c", harness], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    line = [l for l in result.stdout.splitlines() if l.startswith("DESCRIBE:command:")]
    assert line, f"no DESCRIBE line in output: {result.stdout!r}"
    items = line[0].split("DESCRIBE:command:", 1)[1]
    assert "ask" in items.split("|")
    assert "workflow" in items.split("|")


def test_zsh_harness_args_state(tmp_path):
    """Real zsh: state=args must _values the right group subcommands."""
    zsh_bin = shutil.which("zsh")
    assert zsh_bin is not None, "zsh not found on this machine"
    _, zsh_script = _main(["completion", "zsh"])
    script_path = tmp_path / "trm_zsh.zsh"
    script_path.write_text(zsh_script, encoding="utf-8")
    for words, expect in (
        (("(workflow su)", "submit"),
         ("(memory imp)", "import")),
    ):
        harness = (
            "_describe() { local an=$2 out=\"\" i; for i in ${${(P)an}}; do out+=\"${i}|\"; done; print -r -- \"DESCRIBE:$1:${out%|}\"; }\n"
            "_values()   { print -r -- \"VALUES:$1:${(j:|:)@[2,-1]}\"; }\n"
            "_arguments(){ :; }\n"
            "compdef()   { :; }\n"
            f"source {script_path}\n"
            "state=args\n"
            f"words={words[0]}\n"
            "current=2\n"
            "_trm"
        )
        result = subprocess.run([zsh_bin, "-c", harness], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        line = [l for l in result.stdout.splitlines() if l.startswith("VALUES:subcommand:")]
        assert line, f"no VALUES line for words={words[0]}: {result.stdout!r}"
        items = line[0].split("VALUES:subcommand:", 1)[1].split("|")
        assert words[1] in items, f"expected {words[1]!r} in {items!r}"


def test_bash_harness_positional(tmp_path):
    """Real bash: pos1 -> top names, pos2 -> group subs, pos3 -> empty."""
    bash_bin = shutil.which("bash")
    assert bash_bin is not None, "bash not found on this machine"
    _, bash_script = _main(["completion", "bash"])
    script_path = tmp_path / "trm_bash.sh"
    script_path.write_text(bash_script, encoding="utf-8")
    cases = [
        ("(trm wo)", 1, "workflow"),
        ("(trm workflow su)", 2, "submit"),
        ("(trm workflow submit x)", 3, None),
    ]
    for words, cword, expect in cases:
        harness = (
            f"source {script_path}\n"
            f"COMP_WORDS={words}; COMP_CWORD={cword}; COMPREPLY=(); "
            "_trm_complete; printf \"%s\n\" \"${COMPREPLY[@]}\""
        )
        result = subprocess.run([bash_bin, "-c", harness], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        if expect is None:
            assert lines == [], f"pos{cword} expected empty, got {lines!r}"
        else:
            assert expect in lines, f"pos{cword} expected {expect!r} in {lines!r}"
