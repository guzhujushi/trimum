"""`trm sandbox explain`（S6④）的 CLI 契约。

只跑真链路（`main([...])`）：JSON 键集、agent 字段、未安装 agent 的说明、
人读输出、命令注册表，以及「manifest 授权后写面真的出现在输出里」。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import sandbox_exec  # noqa: E402
from trimum_core.cli import main  # noqa: E402
from trimum_core.cli.commands import sandbox as sandbox_mod  # noqa: E402
from trimum_core.cli.registry import check_commands  # noqa: E402
from trimum_core.models import AgentManifest  # noqa: E402

REQUIRED_KEYS = {"agent", "mode", "seccomp", "read", "write", "skipped", "notes"}


def _manifest(**sandbox) -> AgentManifest:
    return AgentManifest(name="probe", version="1", capabilities=[], sandbox=sandbox)


class TestExplainCommand:
    def test_json_has_the_fixed_key_set(self, capsys):
        assert main(["sandbox", "explain", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert REQUIRED_KEYS <= set(data)
        assert set(data["seccomp"]) == {"profile", "source"}
        assert isinstance(data["read"], list) and isinstance(data["write"], list)

    def test_unknown_agent_is_reported_not_raised(self, capsys):
        assert main(["sandbox", "explain", "no-such-agent", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["agent"] == "no-such-agent"
        assert "no-such-agent" in data.get("warning", "")

    def test_human_output_names_mode_and_seccomp(self, capsys):
        assert main(["sandbox", "explain"]) == 0
        out = capsys.readouterr().out
        assert "mode:" in out
        assert "seccomp:" in out
        assert "write (" in out

    def test_bare_group_prints_usage(self, capsys):
        assert main(["sandbox"]) == 0
        assert "trm sandbox explain" in capsys.readouterr().out

    def test_authorized_manifest_write_shows_up_as_manifest_source(
        self, monkeypatch, tmp_path, capsys
    ):
        outside = tmp_path / "outside"
        outside.mkdir()
        ws = tmp_path / "ws"
        ws.mkdir()

        monkeypatch.setattr(
            sandbox_mod, "_load_manifest", lambda name: _manifest(write=[str(outside)])
        )
        monkeypatch.setattr(
            sandbox_exec, "_read_agent_allow_write", lambda name: [str(outside)]
        )
        sandbox_exec.reset_cache()

        assert main(["sandbox", "explain", "probe", "--json", "--cwd", str(ws)]) == 0
        data = json.loads(capsys.readouterr().out)
        write = {item["path"]: item["source"] for item in data["write"]}
        assert write.get(str(outside)) == sandbox_exec.SOURCE_MANIFEST
        assert any("allow_write" in note for note in data["notes"])


class TestCommandRegistry:
    def test_command_contract_is_clean(self):
        assert check_commands() == []


class TestCheckCommand:
    """S6⑤：`trm sandbox check` 的 CLI 契约（有 error 才退 1）。"""

    def test_json_has_the_fixed_key_set_and_exit_zero(self, capsys):
        assert main(["sandbox", "check", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert {"problems", "errors", "warnings"} <= set(data)
        assert isinstance(data["problems"], list)
        assert data["errors"] == 0

    def test_bad_mode_exits_one(self, capsys):
        assert main(["sandbox", "check", "--mode", "banana", "--json"]) == 1
        data = json.loads(capsys.readouterr().out)
        assert data["errors"] >= 1
        assert any(item["code"] == "bad_mode" for item in data["problems"])

    def test_unknown_agent_is_not_an_error(self, capsys):
        assert main(["sandbox", "check", "no-such-agent", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert any(
            item["code"] == "agent_manifest_missing" for item in data["problems"]
        )

    def test_human_output_has_brackets_and_summary(self, capsys):
        assert main(["sandbox", "check", "--mode", "banana"]) == 1
        out = capsys.readouterr().out
        assert "[ERROR]" in out
        assert "error(s)" in out and "warning(s)" in out

    def test_missing_agents_dir_does_not_raise(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            "trimum_core.paths.trimum_path", lambda name: tmp_path / "nope"
        )
        assert main(["sandbox", "check", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data["problems"], list)

    def test_dispatch_write_path_is_validated(self, tmp_path, capsys):
        missing = tmp_path / "dispatch-nope"
        assert main(["sandbox", "check", "--write", str(missing), "--json"]) == 1
        data = json.loads(capsys.readouterr().out)
        assert any(
            item["code"] == "path_missing" and str(missing) in item["message"]
            for item in data["problems"]
        )

    def test_sandbox_command_is_registered(self):
        from trimum_core.cli.parser import build_parser

        args = build_parser().parse_args(["sandbox", "explain", "probe", "--json"])
        assert callable(args.handler)
        assert args.sandbox_command == "explain"
        assert args.agent == "probe"
        assert args.json is True
