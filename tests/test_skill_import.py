"""Tests for the Agent Skills importer — E4 (`skill_import.py`)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import skill_import as importer  # noqa: E402
from trimum_core.ecosystem import ImportRefused  # noqa: E402
from trimum_core.skill_sync import default_source_roots  # noqa: E402

GOOD = """---
name: pdf-tools
description: Work with PDF files when you need to read or fill them.
---

# PDF tools
"""


def make_skill(
    root: Path,
    name: str = "pdf-tools",
    text: str | None = None,
    files: dict[str, str] | None = None,
) -> Path:
    """Create one skill directory; its frontmatter follows *name* unless *text* is given."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    if text is None:
        text = f"---\nname: {name}\ndescription: Skill {name}.\n---\n\n# {name}\n"
    (directory / "SKILL.md").write_text(text, encoding="utf-8", newline="\n")
    for filename, content in (files or {}).items():
        (directory / filename).write_text(content, encoding="utf-8", newline="\n")
    return directory


class TestFrontmatter:
    def test_reads_name_and_description(self, tmp_path):
        directory = make_skill(tmp_path)
        front, problems = importer.read_frontmatter(directory)
        assert problems == []
        assert front["name"] == "pdf-tools"

    def test_missing_skill_md(self, tmp_path):
        front, problems = importer.read_frontmatter(tmp_path)
        assert front == {}
        assert "SKILL.md" in problems[0]

    def test_no_frontmatter_block(self, tmp_path):
        directory = make_skill(tmp_path, text="# only prose\n")
        _, problems = importer.read_frontmatter(directory)
        assert any("frontmatter" in problem for problem in problems)

    def test_unterminated_frontmatter(self, tmp_path):
        directory = make_skill(tmp_path, text="---\nname: x\ndescription: y\n")
        _, problems = importer.read_frontmatter(directory)
        assert problems

    def test_name_is_required(self, tmp_path):
        directory = make_skill(tmp_path, text="---\ndescription: y\n---\n\nbody\n")
        _, problems = importer.read_frontmatter(directory)
        assert any("name" in problem for problem in problems)

    def test_description_is_required(self, tmp_path):
        directory = make_skill(tmp_path, text="---\nname: x\n---\n\nbody\n")
        _, problems = importer.read_frontmatter(directory)
        assert any("description" in problem for problem in problems)

    def test_uppercase_name_is_rejected(self, tmp_path):
        directory = make_skill(tmp_path, text="---\nname: PDF-Tools\ndescription: y\n---\n\nx\n")
        _, problems = importer.read_frontmatter(directory)
        assert any("小写" in problem for problem in problems)


class TestDiscover:
    def test_the_source_can_be_one_skill(self, tmp_path):
        directory = make_skill(tmp_path)
        assert importer.discover_skill_dirs(directory) == [directory]

    def test_direct_children_are_skills(self, tmp_path):
        first = make_skill(tmp_path, "alpha")
        second = make_skill(tmp_path, "beta")
        assert importer.discover_skill_dirs(tmp_path) == [first, second]

    def test_a_repo_layout_is_looked_into_once(self, tmp_path):
        deep = make_skill(tmp_path / "skills", "gamma")
        assert importer.discover_skill_dirs(tmp_path) == [deep]

    def test_nothing_found_is_an_error(self, tmp_path):
        (tmp_path / "notes").mkdir()
        with pytest.raises(importer.SkillImportError):
            importer.discover_skill_dirs(tmp_path)

    def test_missing_path_is_an_error(self, tmp_path):
        with pytest.raises(importer.SkillImportError):
            importer.discover_skill_dirs(tmp_path / "nope")

    def test_a_file_is_an_error(self, tmp_path):
        path = tmp_path / "SKILL.md"
        path.write_text(GOOD, encoding="utf-8", newline="\n")
        with pytest.raises(importer.SkillImportError):
            importer.discover_skill_dirs(path)

    def test_dot_directories_are_ignored(self, tmp_path):
        make_skill(tmp_path, "alpha")
        make_skill(tmp_path, ".hidden")
        assert [path.name for path in importer.discover_skill_dirs(tmp_path)] == ["alpha"]


class TestFileList:
    def test_git_and_node_modules_are_pruned(self, tmp_path):
        directory = make_skill(tmp_path, files={"helper.py": "print(1)\n"})
        (directory / ".git").mkdir()
        (directory / ".git" / "HEAD").write_text("ref\n", encoding="utf-8")
        (directory / "node_modules").mkdir()
        (directory / "node_modules" / "x.js").write_text("1\n", encoding="utf-8")
        (directory / "references").mkdir()
        (directory / "references" / "api.md").write_text("# api\n", encoding="utf-8")

        files = [str(item).replace("\\", "/") for item in importer.list_skill_files(directory)]
        assert files == ["SKILL.md", "helper.py", "references/api.md"]


class TestParseSkill:
    def test_name_comes_from_the_frontmatter(self, tmp_path):
        candidate = importer.parse_skill(make_skill(tmp_path))
        assert candidate.name == "pdf-tools"
        assert candidate.kind == "agent-skill"
        assert candidate.problems == []
        assert candidate.description

    def test_a_different_directory_name_is_a_warning(self, tmp_path):
        candidate = importer.parse_skill(make_skill(tmp_path, "some-dir", text=GOOD))
        assert candidate.name == "pdf-tools"
        assert any("目录名" in warning for warning in candidate.warnings)

    def test_entry_is_a_low_risk_skill(self, tmp_path):
        entry = importer.parse_skill(make_skill(tmp_path)).to_entry()
        assert entry.kind == "skill"
        assert entry.risk == "low"
        assert entry.enabled is True
        assert entry.requires == []

    def test_trimum_only_skill_gets_a_warning(self, tmp_path):
        directory = tmp_path / "trm-cli"
        directory.mkdir()
        (directory / "skill.yaml").write_text("name: trm-cli\n", encoding="utf-8", newline="\n")
        candidate = importer.parse_skill(directory)
        assert candidate.kind == "trimum-skill"
        assert any("不会分发" in warning for warning in candidate.warnings)

    def test_too_many_files_is_a_problem(self, tmp_path):
        extra = {f"file{index}.txt": "x\n" for index in range(importer.MAX_FILES + 1)}
        candidate = importer.parse_skill(make_skill(tmp_path, files=extra))
        assert any("超过上限" in problem for problem in candidate.problems)

    def test_unknown_trust_is_an_error(self, tmp_path):
        with pytest.raises(importer.SkillImportError):
            importer.parse_skill(make_skill(tmp_path), trust="shadowy")

    def test_a_directory_without_any_skill_file_is_an_error(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(importer.SkillImportError):
            importer.parse_skill(tmp_path / "empty")


class TestSourceDetection:
    def test_local_paths_are_not_remote(self, tmp_path):
        assert not importer.is_remote_source(tmp_path)
        assert not importer.is_url(tmp_path)

    def test_urls_are_remote(self):
        for url in ("https://github.com/a/b.git", "git@github.com:a/b", "ssh://git@h/b"):
            assert importer.is_remote_source(url)
            assert importer.is_url(url)

    def test_a_local_bare_repo_is_cloned_but_is_not_a_source_url(self, tmp_path):
        assert importer.is_remote_source(tmp_path / "repo.git")
        assert not importer.is_url(tmp_path / "repo.git")


class TestClone:
    def test_fake_runner_creates_the_destination(self, tmp_path):
        seen = {}

        def runner(argv, timeout):
            seen["argv"] = list(argv)
            Path(argv[-1]).mkdir(parents=True)
            return subprocess.CompletedProcess(argv, 0, "", "")

        destination = tmp_path / "repo"
        importer.clone_repo("https://example.invalid/x.git", destination, runner=runner)
        assert destination.is_dir()
        assert seen["argv"][:5] == ["git", "clone", "--depth", "1", "https://example.invalid/x.git"]

    def test_nonzero_exit_is_an_error(self, tmp_path):
        def runner(argv, timeout):
            return subprocess.CompletedProcess(argv, 128, "", "fatal: repository not found\n")

        with pytest.raises(importer.SkillImportError) as excinfo:
            importer.clone_repo("https://example.invalid/x.git", tmp_path / "repo", runner=runner)
        assert "128" in str(excinfo.value)
        assert "repository not found" in str(excinfo.value)

    def test_a_missing_git_binary_is_an_error(self, tmp_path):
        def runner(argv, timeout):
            raise FileNotFoundError("git")

        with pytest.raises(importer.SkillImportError):
            importer.clone_repo("https://example.invalid/x.git", tmp_path / "repo", runner=runner)

    def test_clone_leaving_nothing_is_an_error(self, tmp_path):
        def runner(argv, timeout):
            return subprocess.CompletedProcess(argv, 0, "", "")

        with pytest.raises(importer.SkillImportError):
            importer.clone_repo("https://example.invalid/x.git", tmp_path / "repo", runner=runner)


class TestPlanAndWrite:
    def test_local_plan_lists_the_skills(self, tmp_path):
        make_skill(tmp_path / "src", "alpha")
        make_skill(tmp_path / "src", "beta")
        plan = importer.plan_import(tmp_path / "src", root=tmp_path / "home")
        assert plan["origin"] == "local"
        assert plan["importable"] == 2
        assert {item["name"] for item in plan["skills"]} == {"alpha", "beta"}

    def test_plan_reports_every_skill_separately(self, tmp_path):
        make_skill(tmp_path / "src", "alpha")
        make_skill(tmp_path / "src", "broken", text="# nope\n")
        plan = importer.plan_import(tmp_path / "src", root=tmp_path / "home")
        rows = {item.get("name"): item for item in plan["skills"]}
        assert plan["importable"] == 1
        assert rows["alpha"]["problems"] == []
        assert rows["broken"]["problems"]
        assert plan["problems"]["broken"] == rows["broken"]["problems"]

    def test_duplicate_names_are_a_problem(self, tmp_path):
        make_skill(tmp_path / "src" / "one", "alpha")
        make_skill(tmp_path / "src" / "two", "alpha")
        plan = importer.plan_import(tmp_path / "src", root=tmp_path / "home")
        assert plan["importable"] == 1
        assert any("重复" in problem for item in plan["skills"] for problem in item["problems"])

    def test_dry_run_writes_nothing(self, tmp_path):
        make_skill(tmp_path / "src")
        plan = importer.plan_import(tmp_path / "src", root=tmp_path / "home")
        assert importer.write_skills(plan, dry_run=True) == []
        assert not (tmp_path / "home").exists()

    def test_write_copies_the_files(self, tmp_path):
        make_skill(tmp_path / "src", files={"helper.py": "print(1)\n"})
        plan = importer.plan_import(tmp_path / "src", root=tmp_path / "home")
        written = importer.write_skills(plan)
        assert written == [str(tmp_path / "home" / "pdf-tools")]
        assert (tmp_path / "home" / "pdf-tools" / "SKILL.md").is_file()
        assert (tmp_path / "home" / "pdf-tools" / "helper.py").is_file()

    def test_existing_target_is_refused_without_force(self, tmp_path):
        make_skill(tmp_path / "src")
        plan = importer.plan_import(tmp_path / "src", root=tmp_path / "home")
        importer.write_skills(plan)
        with pytest.raises(ImportRefused):
            importer.write_skills(plan)
        assert importer.write_skills(plan, force=True)

    def test_a_clash_blocks_the_whole_batch(self, tmp_path):
        make_skill(tmp_path / "src", "alpha")
        make_skill(tmp_path / "src", "beta")
        plan = importer.plan_import(tmp_path / "src", root=tmp_path / "home")
        (tmp_path / "home" / "beta").mkdir(parents=True)
        with pytest.raises(ImportRefused):
            importer.write_skills(plan)
        assert not (tmp_path / "home" / "alpha").exists()

    def test_nothing_importable_is_refused(self, tmp_path):
        make_skill(tmp_path / "src", "broken", text="# nope\n")
        plan = importer.plan_import(tmp_path / "src", root=tmp_path / "home")
        with pytest.raises(ImportRefused):
            importer.write_skills(plan)

    def test_force_replaces_the_old_copy(self, tmp_path):
        make_skill(tmp_path / "src", files={"old.txt": "stale\n"})
        plan = importer.plan_import(tmp_path / "src", root=tmp_path / "home")
        importer.write_skills(plan)
        (tmp_path / "src" / "pdf-tools" / "old.txt").unlink()
        (tmp_path / "src" / "pdf-tools" / "new.txt").write_text("fresh\n", encoding="utf-8")
        importer.write_skills(plan, force=True)
        target = tmp_path / "home" / "pdf-tools"
        assert (target / "new.txt").is_file()
        assert not (target / "old.txt").exists()


class TestTheImportRootIsVisibleToSkillList:
    def test_both_paths_resolve_to_the_same_root(self):
        assert importer.skills_root() == default_source_roots()[0]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
class TestRealGitClone:
    """真跑一次 ``git clone --depth 1``（本地裸仓库，不需要网络）。"""

    @staticmethod
    def _repo(tmp_path: Path) -> Path:
        repo = tmp_path / "upstream"
        make_skill(repo / "skills", "git-skill")
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            [
                "git", "-C", str(repo),
                "-c", "user.email=t@example.invalid",
                "-c", "user.name=t",
                "commit", "-q", "-m", "init",
            ],
            check=True,
        )
        return repo

    def test_a_local_bare_repo_is_cloned_and_imported(self, tmp_path):
        repo = self._repo(tmp_path)
        bare = tmp_path / "upstream.git"
        repo.rename(bare)

        plan = importer.plan_import(bare, root=tmp_path / "home")
        try:
            assert plan["origin"] == "git"
            assert plan["workspace_temporary"] is True
            assert [item["name"] for item in plan["skills"]] == ["git-skill"]
            written = importer.write_skills(plan)
            assert (Path(written[0]) / "SKILL.md").is_file()
            assert plan["skills"][0]["entry"]["origin"] == str(bare)
        finally:
            importer.cleanup(plan)
        assert not Path(plan["workspace"]).exists()
