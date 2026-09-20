"""Tests for the generic CLI adapter — E4 (`cli_adapter.py`).

No test here needs a real binary: probing takes injectable ``runner`` / ``which``,
and the executor's processes are faked through ``asyncio.create_subprocess_exec``
substitutes or a missing-binary path.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import cli_adapter as adapter  # noqa: E402
from trimum_core.ecosystem import validate_entry  # noqa: E402

GH_HELP = """Work seamlessly with GitHub from the command line.

USAGE
  gh <command> <subcommand> [flags]

CORE COMMANDS
  auth:        Authenticate gh and git with GitHub
  browse:      Open repositories, issues, pull requests in the browser

ACCESS COMMANDS
  config:      Manage configuration for gh
  repo:        Manage repositories

FLAGS
  -h, --help      Show help for command
  --version       Show gh version
  --repo string   Select another repository
"""

GITISH_HELP = """usage: tool [<options>] <command> [<args>]

These are common Tool commands used in various situations:

start a working area
   clone      Clone a repository into a new directory
   init       Create an empty repository

examine the history and state
   log        Show commit logs

Options:
  --verbose   Be chatty
"""

NO_SUBCOMMANDS_HELP = """Usage: fd [OPTIONS] [pattern] [path]...

Options:
  -H, --hidden          Search hidden files and directories
  -s, --case-sensitive  Case-sensitive search
  --version             Print version
"""


def fake_runner(mapping):
    """Return a runner that answers like a process, keyed by the argv tail."""

    def run(argv, timeout):
        key = tuple(argv[1:])
        payload = mapping.get(key, mapping.get("default", ""))
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, tuple):
            stdout, stderr = payload
            return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=0)
        return SimpleNamespace(stdout=payload, stderr="", returncode=0)

    return run


class TestParseHelp:
    def test_reads_a_commands_block_with_colons(self):
        subcommands, flags = adapter.parse_help(GH_HELP)
        assert subcommands == ["auth", "browse", "config", "repo"]
        assert "--version" in flags and "--repo" in flags and "-h" in flags

    def test_walks_group_titles_and_stops_at_options(self):
        subcommands, _ = adapter.parse_help(GITISH_HELP)
        assert subcommands == ["clone", "init", "log"]

    def test_no_commands_block_means_no_subcommands(self):
        subcommands, flags = adapter.parse_help(NO_SUBCOMMANDS_HELP)
        assert subcommands == []
        assert "--hidden" in flags and "-H" in flags

    def test_does_not_invent_subcommands_from_prose(self):
        text = "Usage: x [options]\n\n  some prose line\n  another prose line\n"
        assert adapter.parse_help(text)[0] == []

    def test_single_space_separated_rows_are_not_subcommands(self):
        text = "Commands:\n  foo bar baz\n"
        assert adapter.parse_help(text)[0] == []

    def test_empty_text(self):
        assert adapter.parse_help("") == ([], [])

    def test_subcommand_count_is_bounded(self):
        rows = "\n".join(f"  cmd{i:<4}  description" for i in range(200))
        subcommands, _ = adapter.parse_help("Commands:\n" + rows + "\n")
        assert len(subcommands) == adapter.MAX_SUBCOMMANDS


class TestProbeBinary:
    def test_missing_binary_is_reported_not_raised(self):
        probe = adapter.probe_binary("nope", which=lambda _name: None)
        assert probe.found is False
        assert "not found" in probe.error

    def test_empty_binary_name(self):
        probe = adapter.probe_binary("   ", which=lambda name: f"/usr/bin/{name}")
        assert probe.found is False and probe.error == "empty binary name"

    def test_prefers_long_help_flag(self):
        probe = adapter.probe_binary(
            "tool",
            which=lambda _name: "/usr/bin/tool",
            runner=fake_runner({("--help",): GH_HELP}),
            subcommand_limit=0,
        )
        assert probe.found and probe.help_flag == "--help"
        assert probe.subcommands[:2] == ["auth", "browse"]

    def test_falls_back_to_short_flag(self):
        probe = adapter.probe_binary(
            "tool",
            which=lambda _name: "/usr/bin/tool",
            runner=fake_runner({("--help",): "", ("-h",): GH_HELP}),
            subcommand_limit=0,
        )
        assert probe.help_flag == "-h"

    def test_no_help_output_is_an_error(self):
        probe = adapter.probe_binary(
            "tool",
            which=lambda _name: "/usr/bin/tool",
            runner=fake_runner({}),
        )
        assert probe.error == "no help output" and probe.help_text == ""

    def test_runner_exception_is_captured(self):
        probe = adapter.probe_binary(
            "tool",
            which=lambda _name: "/usr/bin/tool",
            runner=fake_runner({("--help",): OSError("boom")}),
        )
        assert probe.found and "boom" in probe.error

    def test_subcommand_probe_collects_more_flags(self):
        probe = adapter.probe_binary(
            "tool",
            which=lambda _name: "/usr/bin/tool",
            runner=fake_runner(
                {
                    ("--help",): GH_HELP,
                    ("auth", "--help"): "Usage: auth\n\nOptions:\n  --token string  Token\n",
                    ("browse", "--help"): "Usage: browse\n",
                    ("config", "--help"): "unknown command config\n",
                    ("repo", "--help"): "",
                }
            ),
            subcommand_limit=4,
        )
        assert probe.verified_subcommands == ["auth", "browse"]
        assert "--token" in probe.flags

    def test_subcommand_limit_is_respected(self):
        seen = []

        def run(argv, timeout):
            seen.append(tuple(argv[1:]))
            return SimpleNamespace(stdout=GH_HELP, stderr="", returncode=0)

        adapter.probe_binary(
            "tool",
            which=lambda _name: "/usr/bin/tool",
            runner=run,
            subcommand_limit=1,
        )
        assert seen.count(("--help",)) == 1
        assert len([item for item in seen if item != ("--help",)]) == 1


class TestBuildEntry:
    def probe(self, **kwargs):
        return adapter.probe_binary(
            "apt",
            which=lambda _name: "/usr/bin/apt",
            runner=fake_runner({("--help",): "Commands:\n  install   Install packages\n  list    List\n"}),
            **kwargs,
        )

    def test_risk_comes_from_subcommands(self):
        entry = adapter.build_entry(self.probe(subcommand_limit=0))
        assert entry.risk == "high"
        assert any("install" in reason for reason in entry.risk_reasons)

    def test_entry_is_valid_and_disabled_by_default(self):
        entry = adapter.build_entry(self.probe(subcommand_limit=0))
        assert validate_entry(entry) == []
        assert entry.enabled is False
        assert entry.trust == "third-party"
        assert entry.requires == ["apt"]

    def test_name_can_be_overridden(self):
        entry = adapter.build_entry(self.probe(subcommand_limit=0), name="apt-cli")
        assert entry.name == "apt-cli"


class TestManifestAndShell:
    def _entry(self):
        probe = adapter.probe_binary(
            "gh",
            which=lambda _name: "/usr/bin/gh",
            runner=fake_runner({("--help",): GH_HELP}),
            subcommand_limit=0,
        )
        return adapter.build_entry(probe)

    def test_manifest_carries_ecosystem_metadata(self):
        manifest = adapter.tool_manifest(self._entry())
        for key in ("trust", "requires", "source_url", "author", "origin", "enabled"):
            assert key in manifest
        assert manifest["kind"] == "custom"
        assert manifest["enabled"] is False

    def test_unconfirming_flags_are_dropped_from_the_allow_list(self):
        allowed, dropped = adapter.safe_flags(["--force", "-y", "--repo", "--yes"])
        assert allowed == ["--repo"]
        assert dropped == ["--force", "-y", "--yes"]

    def test_main_module_binds_binary_and_whitelists(self):
        source = adapter.render_main_module(self._entry())
        assert "from trimum_core.cli_adapter import generic_executor" in source
        assert '"binary": "gh"' in source
        assert "async def execute(" in source


class TestValidateArgv:
    BINDING = {"binary": "gh", "allowed_flags": ["--repo"], "subcommands": ["pr", "repo"]}

    def test_allowed_call(self):
        assert adapter.validate_argv(self.BINDING, ["pr", "--repo", "o/r"]) == ""

    def test_flag_not_in_whitelist(self):
        problem = adapter.validate_argv(self.BINDING, ["pr", "--force"])
        assert "flag not allowed" in problem

    def test_flag_with_equals_is_normalised(self):
        assert adapter.validate_argv(self.BINDING, ["pr", "--repo=o/r"]) == ""

    def test_unknown_subcommand(self):
        problem = adapter.validate_argv(self.BINDING, ["nope"])
        assert "unknown subcommand" in problem

    def test_no_subcommand_whitelist_accepts_positional(self):
        assert adapter.validate_argv({"binary": "fd"}, ["pattern"]) == ""


class TestGenericExecutor:
    BINDING = {"binary": "gh", "allowed_flags": ["--repo"], "subcommands": ["pr"]}

    def run(self, request, binding=None, **kwargs):
        return asyncio.run(
            adapter.generic_executor(
                self.BINDING if binding is None else binding, request, **kwargs
            )
        )

    def test_missing_binary_returns_error(self):
        result = self.run({"args": ["pr"]}, which=lambda _name: None)
        assert result["status"] == "denied"
        assert "not found on PATH" in result["error"]

    def test_binding_without_binary(self):
        result = self.run({"args": []}, binding={})
        assert "no binary" in result["error"]

    def test_refuses_unknown_flag_before_spawning(self):
        def explode(*_args, **_kwargs):
            raise AssertionError("must not spawn for a refused call")

        result = asyncio.run(
            adapter.generic_executor(
                self.BINDING,
                {"args": ["pr", "--force"]},
                which=explode,
            )
        )
        assert result["status"] == "denied" and result["exit_code"] == 2

    def test_reports_nonzero_exit(self, monkeypatch):
        class Proc:
            returncode = 3

            async def communicate(self):
                return b"partial", b"bad thing"

        async def fake_exec(*_args, **_kwargs):
            return Proc()

        monkeypatch.setattr(adapter.asyncio, "create_subprocess_exec", fake_exec)
        result = self.run({"args": ["pr"]}, which=lambda _name: "/usr/bin/gh")
        assert result["exit_code"] == 3
        assert "bad thing" in result["error"]
        assert result["output"] == "partial"

    def test_success_returns_output(self, monkeypatch):
        class Proc:
            returncode = 0

            async def communicate(self):
                return b"hello", b""

        async def fake_exec(*_args, **_kwargs):
            return Proc()

        monkeypatch.setattr(adapter.asyncio, "create_subprocess_exec", fake_exec)
        result = self.run({"args": ["pr"]}, which=lambda _name: "/usr/bin/gh")
        assert result["status"] == "allowed" and result["output"] == "hello"

    def test_timeout_kills_and_reports(self, monkeypatch):
        class Proc:
            returncode = -9
            killed = False

            async def communicate(self):
                await asyncio.sleep(5)
                return b"", b""

            def kill(self):
                self.killed = True

            async def wait(self):
                return -9

        proc = Proc()

        async def fake_exec(*_args, **_kwargs):
            return proc

        monkeypatch.setattr(adapter.asyncio, "create_subprocess_exec", fake_exec)
        result = self.run(
            {"args": ["pr"], "timeout_seconds": 0.01}, which=lambda _name: "/usr/bin/gh"
        )
        assert result["exit_code"] == 124
        assert proc.killed is True

    def test_spawn_oserror_is_reported(self, monkeypatch):
        async def fake_exec(*_args, **_kwargs):
            raise OSError("nope")

        monkeypatch.setattr(adapter.asyncio, "create_subprocess_exec", fake_exec)
        result = self.run({"args": ["pr"]}, which=lambda _name: "/usr/bin/gh")
        assert "cannot start" in result["error"]


class TestWriteTool:
    def _plan(self, tmp_path):
        probe = adapter.probe_binary(
            "gh",
            which=lambda _name: "/usr/bin/gh",
            runner=fake_runner({("--help",): GH_HELP}),
            subcommand_limit=0,
        )
        return adapter.plan_import(probe, root=tmp_path, source_url="https://cli.github.com")

    def test_dry_run_writes_nothing(self, tmp_path):
        plan = self._plan(tmp_path)
        assert adapter.write_tool(plan, dry_run=True) == []
        assert not (tmp_path / "gh").exists()

    def test_writes_manifest_and_shell(self, tmp_path):
        plan = self._plan(tmp_path)
        written = adapter.write_tool(plan)
        assert len(written) == 2
        manifest = json.loads((tmp_path / "gh" / "tool.json5").read_text(encoding="utf-8"))
        assert manifest["name"] == "gh"
        assert manifest["enabled"] is False
        assert manifest["source_url"] == "https://cli.github.com"
        shell = (tmp_path / "gh" / "main.py").read_text(encoding="utf-8")
        assert "generic_executor" in shell

    def test_existing_target_is_refused_without_force(self, tmp_path):
        plan = self._plan(tmp_path)
        adapter.write_tool(plan)
        with pytest.raises(adapter.ImportRefused):
            adapter.write_tool(plan)
        adapter.write_tool(plan, force=True)

    def test_enable_flag_flips_the_manifest(self, tmp_path):
        plan = self._plan(tmp_path)
        adapter.write_tool(plan, enable=True)
        manifest = json.loads((tmp_path / "gh" / "tool.json5").read_text(encoding="utf-8"))
        assert manifest["enabled"] is True

    def test_plan_reports_target_and_warnings(self, tmp_path):
        probe = adapter.probe_binary(
            "apt",
            which=lambda _name: "/usr/bin/apt",
            runner=fake_runner({("--help",): "Commands:\n  install   Install\n"}),
            subcommand_limit=0,
        )
        plan = adapter.plan_import(probe, root=tmp_path)
        assert plan["target_dir"].endswith("apt")
        assert plan["warnings"]


class TestDefaultRunner:
    """`default_runner` 在 Windows 上有两个必须堵死的挂死点：输入与输出句柄。"""

    def test_uses_devnull_stdin_and_never_pipes(self, monkeypatch):
        seen = {}

        def fake_run(argv, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        monkeypatch.setattr(adapter.subprocess, "run", fake_run)
        completed = adapter.default_runner(["gh", "--help"], 3.0)

        assert completed.returncode == 0
        assert seen["stdin"] is subprocess.DEVNULL
        assert seen["timeout"] == 3.0
        for stream in ("stdout", "stderr"):
            handle = seen[stream]
            assert handle is not subprocess.PIPE, f"{stream} must not be a pipe"
            assert callable(getattr(handle, "fileno", None)), f"{stream} must be a real file"

    def test_leaked_grandchild_cannot_block_the_probe(self, tmp_path):
        """被探测 CLI 留下的后台进程若继承了标准输出句柄，探测仍必须立刻返回。

        用守护线程兜底：真挂了也不会拖住整个测试套件，只是超时断言失败。
        """
        script = tmp_path / "leaky_cli.py"
        script.write_text(
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(15)'])\n"
            "sys.stdout.write('leaky help text\\n')\n"
            "sys.stdout.flush()\n",
            encoding="utf-8",
            newline="\n",
        )

        result: list = []
        started = time.monotonic()

        def call():
            result.append(adapter.default_runner([sys.executable, str(script)], 5.0))

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(8.0)
        elapsed = time.monotonic() - started

        assert result, "default_runner blocked on a handle leaked by a grandchild"
        assert result[0].returncode == 0
        assert "leaky help text" in result[0].stdout
        assert elapsed < 5.0

    def test_timeout_is_reported_as_timeout(self, tmp_path):
        script = tmp_path / "slow_cli.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8", newline="\n")
        with pytest.raises(subprocess.TimeoutExpired):
            adapter.default_runner([sys.executable, str(script)], 1.0)

    def test_output_is_decoded_with_a_fallback(self):
        assert adapter._decode(b"") == ""
        assert adapter._decode("命令列表".encode("utf-8")) == "命令列表"
        assert isinstance(adapter._decode(b"\xff\xfe\xff"), str)
