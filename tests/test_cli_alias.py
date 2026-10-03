"""Tests for `.trimumrc` command alias expansion."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.cli import _alias, main  # noqa: E402
from trimum_core.cli.parser import build_parser  # noqa: E402


def _write_rc(tmp_path: Path, text: str) -> Path:
    rc = tmp_path / ".trimumrc"
    rc.write_text(text, encoding="utf-8")
    return rc


class TestExpandArgv:
    def test_hit_expands(self, tmp_path, monkeypatch):
        _write_rc(tmp_path, "st = status\n")
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
        parser = build_parser()
        assert _alias.expand_argv(["st"], parser) == ["status"]
        assert _alias.expand_argv(["st", "--json"], parser) == ["status", "--json"]

    def test_only_argv0_touched(self, tmp_path, monkeypatch):
        _write_rc(tmp_path, "st = status\n")
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
        parser = build_parser()
        assert _alias.expand_argv(["exec", "--", "st"], parser) == ["exec", "--", "st"]
        assert _alias.expand_argv(["--help"], parser) == ["--help"]

    def test_no_config_returns_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))  # empty dir, no .trimumrc
        parser = build_parser()
        assert _alias.expand_argv(["st", "--json"], parser) == ["st", "--json"]

    def test_one_level_only(self, tmp_path, monkeypatch):
        _write_rc(tmp_path, "a = b\nb = status\n")
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
        parser = build_parser()
        assert _alias.expand_argv(["a"], parser) == ["b"]

    def test_returns_new_list(self, tmp_path, monkeypatch):
        _write_rc(tmp_path, "st = status\n")
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
        parser = build_parser()
        original = ["st", "--json"]
        result = _alias.expand_argv(original, parser)
        assert original == ["st", "--json"]  # input not mutated


class TestLoadAliases:
    def test_invalid_line_raises(self, tmp_path):
        rc = _write_rc(tmp_path, "没有等号的一行\n")
        with pytest.raises(_alias.AliasError):
            _alias.load_aliases(rc)

    def test_invalid_line_via_main_returns_3(self, tmp_path, monkeypatch, capsys):
        _write_rc(tmp_path, "没有等号的一行\n")
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
        assert main(["st"]) == 3
        assert "第 1 行" in capsys.readouterr().err


class TestCollision:
    def test_alias_collides_with_command_returns_3(self, tmp_path, monkeypatch, capsys):
        _write_rc(tmp_path, "status = version\n")
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
        assert main(["status"]) == 3
        assert "冲突" in capsys.readouterr().err
