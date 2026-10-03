"""Tests for the legacy `trm install` guide — `trimum_core.install_fn`.

The guide is interactive by nature; the part that needs pinning down is that
it never blocks on a pipe that stays open (``ssh host 'trm install'``, a CI
step, a wrapper script).  ``input()`` only raises ``EOFError`` when stdin is
*closed*, so an open-but-silent pipe would hang forever.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import install_fn  # noqa: E402


class FakeStdin:
    """Minimal stdin stand-in; only ``isatty`` matters here."""

    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    """Point ``expanduser('~')`` at a throwaway directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture()
def no_input(monkeypatch):
    """Make any ``input()`` call a hard failure, so a hang turns into an error."""

    def boom(*_args, **_kwargs):
        raise AssertionError("input() must not be called in an unattended run")

    monkeypatch.setattr("builtins.input", boom)


class TestInteractive:
    def test_tty_is_interactive(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", FakeStdin(True))
        assert install_fn._interactive() is True

    def test_open_pipe_is_not_interactive(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", FakeStdin(False))
        assert install_fn._interactive() is False

    def test_stream_without_isatty_counts_as_pipe(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", SimpleNamespace())
        assert install_fn._interactive() is False

    def test_missing_stdin_counts_as_pipe(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", None)
        assert install_fn._interactive() is False


class TestReadYesNo:
    def test_yes(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _prompt: "y")
        assert install_fn._read_yes_no("q", "N") is True

    def test_yes_long_form_and_case(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _prompt: " YES ")
        assert install_fn._read_yes_no("q", "N") is True

    def test_no(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        assert install_fn._read_yes_no("q", "Y") is False

    def test_empty_answer_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _prompt: "   ")
        assert install_fn._read_yes_no("q", "Y") is True
        assert install_fn._read_yes_no("q", "N") is False

    def test_eof_falls_back_to_default(self, monkeypatch):
        def eof(_prompt):
            raise EOFError

        monkeypatch.setattr("builtins.input", eof)
        assert install_fn._read_yes_no("q", "Y") is True

    def test_interrupt_falls_back_to_default(self, monkeypatch):
        def interrupt(_prompt):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", interrupt)
        assert install_fn._read_yes_no("q", "N") is False

    def test_io_error_falls_back_to_default(self, monkeypatch):
        def broken(_prompt):
            raise OSError("bad file descriptor")

        monkeypatch.setattr("builtins.input", broken)
        assert install_fn._read_yes_no("q", "N") is False


class TestUnattendedInstall:
    def test_pipe_run_returns_without_asking(
        self, monkeypatch, fake_home: Path, no_input, capsys
    ):
        monkeypatch.setattr(sys, "stdin", FakeStdin(False))

        install_fn.install()

        out = capsys.readouterr().out
        assert "非交互模式，跳过" in out
        assert "配置 LLM API Key" in out
        assert (fake_home / ".trimum" / "agents").is_dir()

    def test_answers_no_to_every_prompt(self, monkeypatch, fake_home: Path):
        monkeypatch.setattr(sys, "stdin", FakeStdin(True))
        asked: list[str] = []

        def answer(prompt: str) -> str:
            asked.append(prompt)
            return "n"

        monkeypatch.setattr("builtins.input", answer)
        calls: list[list[str]] = []

        def record(args, **_kwargs):
            calls.append(list(args))
            return SimpleNamespace(stdout="inactive", returncode=0)

        monkeypatch.setattr(install_fn.subprocess, "run", record)

        install_fn.install()

        assert asked, "an interactive run should still ask"
        assert not [c for c in calls if c[:2] in (["systemctl", "enable"], ["systemctl", "start"])]

    def test_yes_to_api_key_reads_hidden_input(self, monkeypatch, fake_home: Path):
        monkeypatch.setattr(sys, "stdin", FakeStdin(True))
        monkeypatch.setattr("builtins.input", lambda _prompt: "y")
        monkeypatch.setattr("getpass.getpass", lambda _prompt: "sk-test")
        monkeypatch.setattr(
            install_fn.subprocess,
            "run",
            lambda *_args, **_kwargs: SimpleNamespace(stdout="inactive", returncode=0),
        )

        install_fn.install()

        env_file = fake_home / ".trimum" / ".env"
        assert "TRIMUM_LLM_API_KEY=sk-test" in env_file.read_text(encoding="utf-8")
