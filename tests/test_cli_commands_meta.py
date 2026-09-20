"""Tests for the `trm commands` surface and its metadata contract.

The metadata contract is only useful if it cannot rot: every test here mirrors a
``trm commands --check`` rule, so a drifting command module fails the suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.cli import main  # noqa: E402
from trimum_core.cli.commands import commands as commands_mod  # noqa: E402
from trimum_core.cli.parser import build_parser  # noqa: E402
from trimum_core.cli.registry import (  # noqa: E402
    METADATA_KEYS,
    CommandMetadata,
    check_commands,
    collect_commands,
    load_command_metadata,
)


class TestCommandSurface:
    def test_real_surface_passes_the_contract(self):
        assert check_commands() == []

    def test_collects_groups_and_commands(self):
        infos = collect_commands(build_parser())
        keys = {info.key for info in infos}
        assert {"commands", "skill", "skill sync", "tool list", "workflow run"} <= keys
        assert all(info.kind in {"group", "command"} for info in infos)

    def test_argparse_aliases_collapse_into_one_command(self):
        infos = {info.key: info for info in collect_commands()}
        assert "run" not in infos
        assert "run" in infos["ask"].aliases

    def test_leaf_commands_have_summary_and_handler(self):
        for info in collect_commands():
            assert info.summary, info.key
            assert info.has_handler, info.key

    def test_declared_metadata_is_supported_and_targets_real_commands(self):
        metadata = load_command_metadata()
        known = {info.key for info in collect_commands()}
        assert metadata.by_path
        for key, payload in metadata.by_path.items():
            assert key in known, key
            assert set(payload) <= METADATA_KEYS, key
        assert metadata.duplicates == {}


class TestCheckRules:
    def test_unknown_metadata_key_is_reported(self):
        metadata = CommandMetadata(
            by_path={"version": {"summary": "x", "nonsense": True}},
            module_by_path={"version": "version"},
        )
        problems = check_commands(metadata=metadata)
        assert any("unsupported metadata key" in item for item in problems)

    def test_metadata_for_unknown_command_is_reported(self):
        metadata = CommandMetadata(by_path={"nope": {"summary": "x"}})
        problems = check_commands(metadata=metadata)
        assert any("unknown command" in item for item in problems)

    def test_invalid_risk_is_reported(self):
        metadata = CommandMetadata(by_path={"version": {"risk": "extreme"}})
        problems = check_commands(metadata=metadata)
        assert any("invalid risk" in item for item in problems)

    def test_duplicate_metadata_is_reported(self):
        metadata = CommandMetadata(duplicates={"version": ("a", "b")})
        problems = check_commands(metadata=metadata)
        assert any("declared twice" in item for item in problems)

    def test_hidden_flag_is_honoured_by_collection(self):
        metadata = CommandMetadata(by_path={"version": {"hidden": True}})
        infos = {info.key: info for info in collect_commands(metadata=metadata)}
        assert infos["version"].hidden is True


class TestCommandsCommand:
    def test_commands_json_lists_the_surface(self, capsys):
        assert main(["--json", "commands"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is True
        assert data["count"] == data["total"] > 0
        routes = {item["route"] for item in data["commands"]}
        assert {"trm skill sync", "trm commands"} <= routes

    def test_commands_human_output(self, capsys):
        assert main(["commands"]) == 0
        out = capsys.readouterr().out
        assert "trm commands" in out
        assert "groups" in out

    def test_check_passes_and_reports(self, capsys):
        assert main(["commands", "--check"]) == 0
        assert "no problems" in capsys.readouterr().out

    def test_check_failure_exits_non_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(commands_mod, "check_commands", lambda *a, **k: ["boom"])
        assert main(["commands", "--check"]) == 1
        assert "boom" in capsys.readouterr().out

    def test_all_flag_matches_total(self, capsys):
        assert main(["--json", "commands", "--all"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["count"] == data["total"]
