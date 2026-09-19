"""Tests for the `trm` argparse CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.cli import main  # noqa: E402
from trimum_core.cli import commands  # noqa: E402
from trimum_core.cli.parser import build_parser  # noqa: E402


class TestBuildParser:
    def test_root_help_and_version_flags(self):
        parser = build_parser()
        help_actions = {action.dest for action in parser._actions}
        assert "help" in help_actions
        assert "json" in help_actions

    @pytest.mark.parametrize(
        "argv",
        [
            ["version"],
            ["health"],
            ["status"],
            ["ask", "list files"],
            ["memory", "list"],
            ["memory", "set", "key", "value"],
            ["security", "allow-once", "agent-1", "--ttl", "60"],
            ["daemon", "start"],
            ["log", "tail"],
            ["log", "--audit"],
            ["tool", "list"],
            ["agent", "list"],
            ["workflow", "list"],
            ["config", "show"],
            ["install"],
            ["exec", "echo", "hi"],
        ],
    )
    def test_command_has_handler(self, argv):
        args = build_parser().parse_args(argv)
        assert callable(args.handler)

    def test_json_flag_before_and_after_subcommand(self):
        before = build_parser().parse_args(["--json", "health"])
        after = build_parser().parse_args(["health", "--json"])
        assert before.json is True
        assert after.json is True

    def test_ask_alias_run(self):
        args = build_parser().parse_args(["run", "hello"])
        assert args.command == "run"
        assert args.prompt == "hello"
        assert callable(args.handler)


class TestCommandRegistration:
    def test_register_all_skips_private_modules(self):
        seen: list[str] = []

        class FakeSubparsers:
            def __init__(self):
                self.seen = seen

            def add_parser(self, name, **kwargs):
                self.seen.append(name)
                import argparse

                return argparse.ArgumentParser(prog=name)

        commands.register_all(FakeSubparsers())
        assert "version" in seen
        assert not any(name.startswith("_") for name in seen)


class TestVersionCommand:
    def test_version_command_uses_050(self, capsys):
        assert main(["version"]) == 0
        assert "trimum v0.5.0" in capsys.readouterr().out

    def test_version_json(self, capsys):
        assert main(["--json", "version"]) == 0
        assert '"version": "0.5.0"' in capsys.readouterr().out


class TestConfigHelpers:
    def test_config_set_save_round_trip(self):
        from uuid import uuid4

        from trimum_core.config import Config

        path = Path(__file__).resolve().parents[1] / "tmp" / f"test_cli_config_{uuid4().hex}.yaml"
        try:
            config = Config(path)
            config.set("core.port", 9123)
            config.save(path)

            loaded = Config(path)
            assert loaded.port == 9123
        finally:
            path.unlink(missing_ok=True)
