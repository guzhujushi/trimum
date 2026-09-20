"""Tests for Agent Skills distribution (`trimum_core.skill_sync` + `trm skill`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import skill_sync  # noqa: E402
from trimum_core.cli import main  # noqa: E402
from trimum_core.cli.commands import skill as skill_mod  # noqa: E402
from trimum_core.skill_sync import (  # noqa: E402
    discover_skills,
    is_link,
    link_destination,
    link_skill,
    prune_skills,
    sync_skills,
)

SKILL_MD = """---
name: {name}
description: {description}
---

# {name}

Fixture skill body.
"""


def _write_skill(root: Path, name: str, description: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        SKILL_MD.format(name=name, description=description), encoding="utf-8"
    )
    return skill_dir


@pytest.fixture()
def layout(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    _write_skill(source, "alpha", "Alpha fixture skill")
    (source / "beta").mkdir(parents=True)
    (source / "beta" / "skill.yaml").write_text("name: beta\n", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    return source, target


def _entry(source: Path, name: str):
    return {entry.name: entry for entry in discover_skills([source])}[name]


class TestDiscovery:
    def test_separates_agent_skills_from_trimum_skills(self, layout):
        source, _ = layout
        entries = {entry.name: entry for entry in discover_skills([source])}
        assert entries["alpha"].kind == "agent-skill"
        assert entries["alpha"].distributable is True
        assert entries["beta"].kind == "trimum-skill"
        assert entries["beta"].distributable is False

    def test_reads_frontmatter(self, layout):
        source, _ = layout
        assert _entry(source, "alpha").description == "Alpha fixture skill"

    def test_missing_root_is_ignored(self, tmp_path):
        assert discover_skills([tmp_path / "does-not-exist"]) == []

    def test_directory_without_skill_files_is_ignored(self, tmp_path):
        (tmp_path / "source" / "empty").mkdir(parents=True)
        assert discover_skills([tmp_path / "source"]) == []

    def test_first_root_wins_on_name_clash(self, tmp_path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        _write_skill(first, "dup", "from first")
        _write_skill(second, "dup", "from second")
        entry = discover_skills([first, second])[0]
        assert entry.description == "from first"
        assert entry.source_root == first.resolve()


class TestLinking:
    def test_creates_distribution_entry(self, layout):
        source, target = layout
        result = link_skill(_entry(source, "alpha"), target)
        assert result.action in {"linked", "junction", "copied"}
        assert (target / "alpha" / "SKILL.md").is_file()

    def test_repeat_sync_is_idempotent(self, layout):
        source, target = layout
        entry = _entry(source, "alpha")
        first = link_skill(entry, target)
        second = link_skill(entry, target)
        if first.action == "copied":
            assert second.action == "conflict"
        else:
            assert second.action == "unchanged"

    def test_trimum_skills_are_skipped(self, layout):
        source, target = layout
        result = link_skill(_entry(source, "beta"), target)
        assert result.action == "skipped"
        assert not (target / "beta").exists()

    def test_conflict_without_force(self, layout):
        source, target = layout
        (target / "alpha").mkdir()
        result = link_skill(_entry(source, "alpha"), target)
        assert result.action == "conflict"
        assert not (target / "alpha" / "SKILL.md").exists()

    def test_force_replaces_conflicting_directory(self, layout):
        source, target = layout
        (target / "alpha").mkdir()
        result = link_skill(_entry(source, "alpha"), target, force=True)
        assert result.action in {"linked", "junction", "copied"}
        assert (target / "alpha" / "SKILL.md").is_file()

    def test_dry_run_touches_nothing(self, layout):
        source, target = layout
        results = sync_skills([_entry(source, "alpha")], [target], dry_run=True)
        assert [result.action for result in results] == ["planned"]
        assert list(target.iterdir()) == []

    def test_sync_reports_every_target(self, layout, tmp_path):
        source, target = layout
        second = tmp_path / "target2"
        results = sync_skills([_entry(source, "alpha")], [target, second])
        assert len(results) == 2
        assert all(result.skill == "alpha" for result in results)


class TestPrune:
    def test_removes_link_of_deleted_source(self, layout):
        source, target = layout
        result = link_skill(_entry(source, "alpha"), target)
        if result.action == "copied":
            pytest.skip("copy fallback cannot be pruned")
        assert is_link(target / "alpha")

        import shutil

        shutil.rmtree(source / "alpha")
        removed = prune_skills([target], [source])
        assert [item.action for item in removed] == ["removed"]
        assert not (target / "alpha").exists()

    def test_keeps_valid_links(self, layout):
        source, target = layout
        result = link_skill(_entry(source, "alpha"), target)
        if result.action == "copied":
            pytest.skip("copy fallback is not a link")
        assert prune_skills([target], [source]) == []

    def test_prune_dry_run_leaves_link(self, layout):
        source, target = layout
        result = link_skill(_entry(source, "alpha"), target)
        if result.action == "copied":
            pytest.skip("copy fallback is not a link")

        import shutil

        shutil.rmtree(source / "alpha")
        plan = prune_skills([target], [source], dry_run=True)
        assert [item.action for item in plan] == ["planned-remove"]
        assert is_link(target / "alpha")  # still a (dangling) link

    def test_prune_keeps_links_when_source_roots_unknown(self, layout):
        source, target = layout
        result = link_skill(_entry(source, "alpha"), target)
        if result.action == "copied":
            pytest.skip("copy fallback is not a link")
        assert prune_skills([target], [], dry_run=True) == []


class TestSkillCommand:
    @pytest.fixture(autouse=True)
    def _isolate_roots(self, monkeypatch, layout):
        source, target = layout
        monkeypatch.setattr(skill_mod, "default_source_roots", lambda: [source])
        monkeypatch.setattr(skill_mod, "default_target_roots", lambda: [target])
        self.source, self.target = source, target

    def test_list_json(self, capsys):
        assert main(["--json", "skill", "list"]) == 0
        data = json.loads(capsys.readouterr().out)
        names = {item["name"] for item in data["skills"]}
        assert names == {"alpha"}
        assert data["skills"][0]["targets"][str(self.target)] == "missing"

    def test_list_all_includes_trimum_skills(self, capsys):
        assert main(["--json", "skill", "list", "--all"]) == 0
        data = json.loads(capsys.readouterr().out)
        names = {item["name"] for item in data["skills"]}
        assert names == {"alpha", "beta"}

    def test_list_human_output(self, capsys):
        assert main(["skill", "list"]) == 0
        assert "alpha" in capsys.readouterr().out

    def test_sync_dry_run_does_not_write(self, capsys):
        assert main(["--json", "skill", "sync", "--dry-run"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["summary"] == {"planned": 1}
        assert list(self.target.iterdir()) == []

    def test_sync_creates_and_reports(self, capsys):
        assert main(["--json", "skill", "sync"]) == 0
        data = json.loads(capsys.readouterr().out)
        action = data["results"][0]["action"]
        assert action in {"linked", "junction", "copied"}
        assert (self.target / "alpha" / "SKILL.md").is_file()

        assert main(["--json", "skill", "list"]) == 0
        listed = json.loads(capsys.readouterr().out)
        assert listed["skills"][0]["targets"][str(self.target)] in {"linked", "conflict"}

    def test_paths_json(self, capsys):
        assert main(["--json", "skill", "paths"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["sources"][0]["path"] == str(self.source)
        assert data["targets"][0]["exists"] is True
