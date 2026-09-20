"""Tests for host (agent harness) detection — `trimum_core.hosts`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import hosts as hosts_mod  # noqa: E402


@pytest.fixture()
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _detect(home: Path, **kwargs):
    return hosts_mod.detect_hosts(home=home, env={}, which=lambda name: None, **kwargs)


class TestSpecs:
    def test_names_and_dirs_are_unique(self):
        names = [spec.name for spec in hosts_mod.KNOWN_HOSTS]
        dirs = [spec.config_dir for spec in hosts_mod.KNOWN_HOSTS]
        assert len(names) == len(set(names))
        assert len(dirs) == len(set(dirs))

    def test_original_omarchy_targets_are_kept(self):
        by_name = {spec.name: spec for spec in hosts_mod.KNOWN_HOSTS}
        assert by_name["agents"].skills_relpath == ".agents/skills"
        assert by_name["claude"].skills_relpath == ".claude/skills"
        assert by_name["codex"].skills_relpath == ".codex/skills"
        assert by_name["pi"].skills_relpath == ".pi/agent/skills"
        assert by_name["gemini"].skills_relpath == ".gemini/config/skills"
        assert by_name["hermes"].skills_relpath == ".hermes/skills"

    def test_skills_dir_is_relative_to_given_home(self, fake_home):
        spec = hosts_mod.host_by_name("claude")
        assert spec.skills_dir(fake_home) == fake_home / ".claude" / "skills"

    def test_host_by_name_is_case_insensitive(self):
        assert hosts_mod.host_by_name("CLAUDE").name == "claude"
        assert hosts_mod.host_by_name("does-not-exist") is None


class TestDetection:
    def test_nothing_installed_yields_no_hosts(self, fake_home):
        statuses = _detect(fake_home)
        assert [item.name for item in statuses] == [spec.name for spec in hosts_mod.KNOWN_HOSTS]
        assert all(not item.present for item in statuses)
        assert all(item.evidence == () for item in statuses)

    def test_config_dir_is_evidence(self, fake_home):
        (fake_home / ".claude").mkdir()
        detected = [item.name for item in _detect(fake_home) if item.present]
        assert detected == ["claude"]
        status = next(item for item in _detect(fake_home) if item.name == "claude")
        assert status.evidence == ("dir:.claude",)

    def test_cli_on_path_is_evidence(self, fake_home):
        def which(name: str):
            return "/usr/bin/codex" if name == "codex" else None

        statuses = hosts_mod.detect_hosts(home=fake_home, env={}, which=which)
        status = next(item for item in statuses if item.name == "codex")
        assert status.present
        assert status.evidence == ("cli:codex",)

    def test_env_force_lists_hosts(self, fake_home):
        statuses = hosts_mod.detect_hosts(
            home=fake_home, env={"TRIMUM_HOSTS": "pi, zed"}, which=lambda name: None
        )
        present = {item.name for item in statuses if item.present}
        assert present == {"pi", "zed"}
        status = next(item for item in statuses if item.name == "pi")
        assert status.evidence == ("env:TRIMUM_HOSTS",)

    def test_env_disable_wins_over_dir(self, fake_home):
        (fake_home / ".codex").mkdir()
        statuses = hosts_mod.detect_hosts(
            home=fake_home,
            env={"TRIMUM_HOSTS_DISABLE": "codex"},
            which=lambda name: None,
        )
        assert not next(item for item in statuses if item.name == "codex").present

    def test_summarize_shape(self, fake_home, monkeypatch):
        monkeypatch.setenv(hosts_mod.SCAN_HOME_ENV, str(fake_home))
        (fake_home / ".agents").mkdir()
        data = hosts_mod.summarize(_detect(fake_home))
        assert data["detected"] == ["agents"]
        assert "claude" in data["absent"]
        assert data["scan_home"] == str(fake_home)
        assert len(data["hosts"]) == len(hosts_mod.KNOWN_HOSTS)
        entry = next(item for item in data["hosts"] if item["name"] == "agents")
        assert entry["present"] is True
        assert entry["skills_dir"].endswith(".agents\\skills") or entry[
            "skills_dir"
        ].endswith(".agents/skills")


class TestTargets:
    def test_detected_targets_end_with_own_root(self, fake_home, monkeypatch, tmp_path):
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "trimum"))
        (fake_home / ".claude").mkdir()
        targets = hosts_mod.detected_skill_targets(
            home=fake_home, env={}, which=lambda name: None
        )
        assert targets[0] == fake_home / ".claude" / "skills"
        assert targets[-1] == tmp_path / "trimum" / "agent-skills"

    def test_bare_machine_still_has_own_root(self, fake_home, monkeypatch, tmp_path):
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "trimum"))
        targets = hosts_mod.detected_skill_targets(
            home=fake_home, env={}, which=lambda name: None
        )
        assert targets == [tmp_path / "trimum" / "agent-skills"]

    def test_all_targets_cover_every_known_host(self, fake_home, monkeypatch, tmp_path):
        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "trimum"))
        targets = hosts_mod.all_skill_targets(home=fake_home)
        assert len(targets) == len(hosts_mod.KNOWN_HOSTS) + 1
        assert targets[-1] == tmp_path / "trimum" / "agent-skills"