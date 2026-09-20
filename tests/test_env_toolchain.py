"""Tests for the opt-in toolchain layer — `trimum_core.env_toolchain` + `trm env`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import env_toolchain as env  # noqa: E402
from trimum_core.cli import main  # noqa: E402
from trimum_core.cli.commands import env as env_cmd  # noqa: E402

CATALOG = {
    "version": 1,
    "loaded": True,
    "path": "/tmp/catalog.yaml",
    "groups": [
        {
            "id": "runtimes",
            "label": "语言运行时",
            "entries": [
                {
                    "name": "python",
                    "label": "Python 3",
                    "note": "base",
                    "packages": {"pacman": "python", "apt": "python3", "winget": "Python.Python.3.12"},
                },
                {
                    "name": "node",
                    "label": "Node.js",
                    "packages": {"pacman": "nodejs", "apt": "nodejs"},
                },
            ],
        },
        {
            "id": "cli-tools",
            "label": "命令行工具",
            "entries": [
                {
                    "name": "fd",
                    "label": "fd",
                    "packages": {"pacman": "fd", "apt": "fd-find"},
                },
                {
                    "name": "zed",
                    "label": "Zed",
                    "packages": {"pacman": "zed", "apt": None, "winget": "Zed.Zed"},
                },
            ],
        },
    ],
}


class Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def which_only(*names: str):
    return lambda name: f"/usr/bin/{name}" if name in names else None


def runner_for(mapping: dict[str, Completed]):
    calls: list[list[str]] = []

    def runner(cmd, timeout=None):
        calls.append(list(cmd))
        return mapping.get(cmd[0], Completed(returncode=127, stderr="not found"))

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def status_for(manager_id: str, *, available: bool = True) -> env.ManagerStatus:
    manager = next(item for item in env.KNOWN_MANAGERS if item.id == manager_id)
    return env.ManagerStatus(manager=manager, available=available, path="/usr/bin/x")


class TestDetection:
    def test_missing_manager_is_reported_unavailable(self):
        statuses = env.detect_managers(
            which=which_only(), runner=runner_for({}), platform="linux"
        )
        assert all(not item.available for item in statuses)

    def test_present_manager_reports_version(self):
        runner = runner_for({"pacman": Completed(stdout="Pacman v6.1.0\n")})
        statuses = env.detect_managers(
            which=which_only("pacman"), runner=runner, platform="linux"
        )
        pacman = next(item for item in statuses if item.id == "pacman")
        assert pacman.available and pacman.version == "Pacman v6.1.0"
        assert pacman.manager.installable

    def test_platform_filter(self):
        statuses = env.detect_managers(
            which=which_only("pacman"), runner=runner_for({}), platform="win32"
        )
        pacman = next(item for item in statuses if item.id == "pacman")
        assert pacman.platform_supported is False
        assert pacman.available is False

    def test_version_probe_failure_is_not_fatal(self):
        def boom(cmd, timeout=None):
            raise OSError("no such binary")

        statuses = env.detect_managers(
            which=which_only("apt-get"), runner=boom, platform="linux"
        )
        apt = next(item for item in statuses if item.id == "apt")
        assert apt.available and apt.version == ""

    def test_mise_is_detected_but_not_driven(self):
        statuses = env.detect_managers(
            which=which_only("mise"), runner=runner_for({}), platform="linux"
        )
        mise = next(item for item in statuses if item.id == "mise")
        assert mise.available and mise.manager.installable is False


class TestParsing:
    def test_pacman_listing(self):
        assert env.parse_installed("pacman", "python\nripgrep\n\n") == {"python", "ripgrep"}

    def test_dpkg_arch_suffix_is_stripped(self):
        assert env.parse_installed("apt", "libc6:amd64\npython3:amd64\n") == {
            "libc6",
            "python3",
        }

    def test_brew_listing(self):
        assert env.parse_installed("brew", "git\nripgrep\n") == {"git", "ripgrep"}

    def test_winget_header_is_skipped(self):
        text = "Name                          Id              Version\n---\nPython 3.12  Python.Python.3.12  3.12.1\n"
        installed = env.parse_installed("winget", text)
        assert "python.python.3.12" in installed
        assert "name" not in installed

    def test_query_returns_none_without_list_command(self):
        assert env.query_installed(status_for("mise"), runner=runner_for({})) is None

    def test_query_returns_none_on_failure(self):
        runner = runner_for({"pacman": Completed(returncode=1, stderr="boom")})
        assert env.query_installed(status_for("pacman"), runner=runner) is None

    def test_query_returns_none_when_unavailable(self):
        assert (
            env.query_installed(status_for("pacman", available=False), runner=runner_for({}))
            is None
        )


class TestInstallPlan:
    def test_packages_are_merged(self):
        plan = env.plan_install(
            CATALOG, ["python", "node"], manager=status_for("apt")
        )
        assert plan["packages"] == ["python3", "nodejs"]
        assert plan["command"][:2] == ["sudo", "apt-get"]

    def test_already_installed_is_reported_not_repeated(self):
        plan = env.plan_install(
            CATALOG,
            ["python", "node"],
            manager=status_for("pacman"),
            installed={"python"},
        )
        assert plan["already_installed"] == ["python"]
        assert plan["packages"] == ["nodejs"]

    def test_entry_without_package_for_manager(self):
        plan = env.plan_install(CATALOG, ["fd"], manager=status_for("winget"))
        assert plan["unavailable"] == ["fd"]
        assert plan["packages"] == []

    def test_unknown_names_are_reported(self):
        plan = env.plan_install(CATALOG, ["python", "nope"], manager=status_for("apt"))
        assert plan["unknown"] == ["nope"]

    def test_selection_from_setup_is_echoed(self):
        plan = env.plan_install(
            CATALOG, ["python"], manager=status_for("apt"), selected=["python", "node"]
        )
        assert plan["selected_before"] == ["python", "node"]

    def test_build_command_sudo_prefix(self):
        assert env.build_command(status_for("apt"), ["python3"], use_sudo=True) == [
            "sudo",
            "apt-get",
            "install",
            "-y",
            "python3",
        ]
        assert env.build_command(status_for("brew"), ["git"], use_sudo=False) == [
            "brew",
            "install",
            "git",
        ]

    def test_no_command_without_packages(self):
        assert env.build_command(status_for("apt"), []) == []
        assert env.commands_for(status_for("apt"), []) == []

    def test_winget_runs_one_package_per_command(self):
        commands = env.commands_for(
            status_for("winget"), ["Python.Python.3.12", "Zed.Zed"], use_sudo=False
        )
        assert len(commands) == 2
        assert commands[0] == ["winget", "install", "-e", "--id", "Python.Python.3.12"]


class TestRunInstall:
    def test_dry_run_never_calls_the_runner(self):
        runner = runner_for({})
        result = env.run_install([["apt-get", "install", "-y", "python3"]], dry_run=True, runner=runner)
        assert runner.calls == []  # type: ignore[attr-defined]
        assert result["dry_run"] is True and result["results"][0]["executed"] is False
        assert result["ok"] is False

    def test_success_and_failure_are_reported(self):
        runner = runner_for({"apt-get": Completed(returncode=0, stdout="ok")})
        assert env.run_install([["apt-get", "install"]], runner=runner)["ok"] is True

        failing = runner_for({"apt-get": Completed(returncode=100, stderr="E: no")})
        result = env.run_install([["apt-get", "install"]], runner=failing)
        assert result["ok"] is False
        assert result["results"][0]["returncode"] == 100

    def test_exception_is_captured(self):
        def boom(cmd, timeout=None):
            raise PermissionError("sudo: no tty")

        result = env.run_install([["sudo", "apt-get", "install"]], runner=boom)
        assert result["ok"] is False
        assert "sudo: no tty" in result["results"][0]["error"]


class TestInventory:
    def test_inventory_reports_coverage_and_selection(self, tmp_path):
        state = tmp_path / "setup.json5"
        state.write_text(
            json.dumps({"steps": {"toolchain": {"selected": ["node"]}}}), encoding="utf-8"
        )
        runner = runner_for(
            {
                "pacman": Completed(stdout="Pacman v6\n"),
                "dpkg-query": Completed(stdout="python3:amd64\n"),
            }
        )
        data = env.inventory(
            catalog=CATALOG,
            which=which_only("pacman", "apt-get"),
            runner=runner,
            platform="linux",
            state_file=state,
        )
        assert data["platform"] == "linux"
        assert data["preferred_manager"] == "pacman"
        assert data["selected"] == ["node"]
        by_name = {row["name"]: row for row in data["toolchain"]}
        assert by_name["python"]["installed"] is True  # dpkg 列表里
        assert by_name["node"]["installed"] is False
        assert by_name["python"]["selected"] is False
        assert by_name["node"]["selected"] is True
        assert "pacman" in by_name["python"]["available_via"]

    def test_inventory_without_managers(self):
        data = env.inventory(
            catalog=CATALOG, which=which_only(), runner=runner_for({}), platform="linux"
        )
        assert data["installable_managers"] == []
        assert data["preferred_manager"] == ""
        assert all(row["available_via"] == [] for row in data["toolchain"])

    def test_package_names_are_opt_in(self, tmp_path):
        runner = runner_for(
            {"pacman": Completed(stdout="Pacman v6\n"), "dpkg-query": Completed(stdout="python3\n")}
        )
        kwargs = dict(
            catalog=CATALOG,
            which=which_only("pacman", "apt-get"),
            runner=runner,
            platform="linux",
            state_file=tmp_path / "missing.json5",
        )
        lean = env.inventory(**kwargs)
        assert "installed" not in next(i for i in lean["managers"] if i["id"] == "pacman")
        full = env.inventory(include_package_names=True, **kwargs)
        assert full["managers"][1]["id"] == "apt"
        assert "python3" in next(i for i in full["managers"] if i["id"] == "apt")["installed"]


class TestEnvCommand:
    @pytest.fixture()
    def fake_env(self, monkeypatch):
        calls: list[list] = []

        def detect(*args, **kwargs):
            calls.append(list(args))
            return [
                env.ManagerStatus(
                    manager=next(m for m in env.KNOWN_MANAGERS if m.id == "pacman"),
                    available=True,
                    path="/usr/bin/pacman",
                    version="Pacman v6",
                )
            ]

        detect.calls = calls  # type: ignore[attr-defined]
        monkeypatch.setattr(env_cmd, "detect_managers", detect)
        monkeypatch.setattr(env_cmd, "load_catalog", lambda path=None: CATALOG)
        monkeypatch.setattr(
            env,
            "query_installed",
            lambda status, **kwargs: {"python"},
        )
        return detect

    def test_inventory_json(self, fake_env, capsys):
        assert main(["--json", "env", "inventory"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["preferred_manager"] == "pacman"
        assert data["installable_managers"] == ["pacman"]

    def test_install_dry_run_prints_plan_without_executing(self, fake_env, capsys):
        assert main(["--json", "env", "install", "node", "--dry-run"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["plan"]["packages"] == ["nodejs"]
        assert data["commands"] == [["sudo", "pacman", "-S", "--noconfirm", "nodejs"]]
        assert data["results"][0]["executed"] is False

    def test_install_probes_managers_once(self, fake_env, capsys):
        assert main(["--json", "env", "install", "node", "--dry-run"]) == 0
        capsys.readouterr()
        assert len(fake_env.calls) == 1

    def test_install_non_interactive_without_yes_aborts(self, fake_env, capsys):
        assert main(["env", "install", "node"]) == 1
        assert "aborted" in capsys.readouterr().err

    def test_install_unknown_entry_fails(self, fake_env, capsys):
        assert main(["env", "install", "nope", "--dry-run"]) == 1
        assert "unknown toolchain entries" in capsys.readouterr().err

    def test_install_without_manager_fails(self, monkeypatch, capsys):
        monkeypatch.setattr(env_cmd, "detect_managers", lambda *a, **k: [])
        monkeypatch.setattr(env_cmd, "load_catalog", lambda path=None: CATALOG)
        assert main(["env", "install", "node", "--yes"]) == 1
        assert "no usable package manager" in capsys.readouterr().err

    def test_install_already_installed_is_a_noop_success(self, fake_env, capsys):
        # 幂等：已装好的条目不算失败 —— 不弹确认、不执行命令、退出码 0
        assert main(["env", "install", "python"]) == 0
        captured = capsys.readouterr()
        assert "already installed: python" in captured.out
        assert "nothing to install" in captured.out
        assert "aborted" not in captured.err

    def test_inventory_rejects_unknown_manager(self, capsys):
        assert main(["env", "inventory", "--manager", "nope"]) == 1
        assert "unknown manager" in capsys.readouterr().err