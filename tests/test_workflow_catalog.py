"""Tests for the workflow catalog format and importer — E4 (`workflow_catalog.py`)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import cli_adapter as adapter  # noqa: E402
from trimum_core import workflow_catalog as catalog  # noqa: E402
from trimum_core.ecosystem import ImportRefused  # noqa: E402

DOCKER = """
name: Docker 清理
description: 清掉悬空镜像与停止的容器
tags: [docker, cleanup]
command: docker system prune -f
author: someone
source_url: https://github.com/xxx/trimum-workflows
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def parse(text: str, **kwargs):
    return catalog.parse_catalog(
        yaml.safe_load(text), source_path=str(kwargs.pop("source_path", "in.yaml")), **kwargs
    )


class TestParseCatalog:
    def test_single_command_becomes_one_step(self):
        entry = parse(DOCKER)
        assert entry.commands == ["docker system prune -f"]
        assert entry.name == "Docker 清理"
        assert entry.tags == ["docker", "cleanup"]

    def test_steps_run_is_the_alternative_spelling(self):
        entry = parse("name: n\nsteps:\n  - run: docker ps\n  - run: docker system prune\n")
        assert entry.commands == ["docker ps", "docker system prune"]

    def test_plain_string_steps_are_accepted(self):
        entry = parse("name: n\nsteps:\n  - ls -la\n")
        assert entry.commands == ["ls -la"]

    def test_command_list_is_accepted(self):
        entry = parse("name: n\ncommand:\n  - ls\n  - pwd\n")
        assert entry.commands == ["ls", "pwd"]

    def test_command_and_steps_are_merged_in_order(self):
        entry = parse("name: n\ncommand: ls\nsteps:\n  - run: pwd\n")
        assert entry.commands == ["ls", "pwd"]
        assert any("按顺序合并" in warning for warning in entry.warnings)

    def test_id_falls_back_to_the_file_name(self):
        entry = parse("name: Docker 清理\ncommand: ls\n", fallback_id="My-Cleanup")
        assert entry.id == "my-cleanup"
        assert any("未声明 `id`" in warning for warning in entry.warnings)

    def test_name_falls_back_to_the_id(self):
        entry = parse("id: docker-cleanup\ncommand: ls\n")
        assert entry.name == "docker-cleanup"
        assert any("未声明 `name`" in warning for warning in entry.warnings)

    def test_unknown_fields_are_kept_as_a_warning(self):
        entry = parse("name: n\ncommand: ls\nhover: true\n")
        assert any("hover" in warning for warning in entry.warnings)

    def test_neither_name_nor_id_is_an_error(self):
        with pytest.raises(catalog.CatalogError):
            parse("command: ls\n")

    def test_empty_file_is_an_error(self):
        with pytest.raises(catalog.CatalogError):
            parse("")

    def test_top_level_must_be_a_mapping(self):
        with pytest.raises(catalog.CatalogError):
            parse("- just\n- a list\n")

    def test_no_command_is_an_error(self):
        with pytest.raises(catalog.CatalogError):
            parse("name: n\nsteps: []\n")

    def test_illegal_risk_is_an_error(self):
        with pytest.raises(catalog.CatalogError):
            parse("name: n\nrisk: spicy\ncommand: ls\n")

    def test_illegal_trust_is_an_error(self):
        with pytest.raises(catalog.CatalogError):
            parse("name: n\ntrust: shadowy\ncommand: ls\n")

    def test_uppercase_id_is_an_error(self):
        with pytest.raises(catalog.CatalogError):
            parse("name: n\nid: Docker-Cleanup\ncommand: ls\n")

    def test_bad_timeout_is_an_error(self):
        with pytest.raises(catalog.CatalogError):
            parse("name: n\ncommand: ls\ntimeout: soon\n")

    def test_tags_accept_a_comma_string(self):
        entry = parse("name: n\ncommand: ls\ntags: a, b\n")
        assert entry.tags == ["a", "b"]


class TestRisk:
    def test_declared_risk_can_only_go_up(self):
        entry = parse("name: n\nrisk: low\ncommand: rm -rf build\n")
        assert entry.risk == "high"
        assert any("低于命令探测结果" in warning for warning in entry.warnings)

    def test_declared_risk_is_kept_when_it_is_higher(self):
        entry = parse("name: n\nrisk: critical\ncommand: ls -la\n")
        assert entry.risk == "critical"

    def test_detected_risk_is_used_when_nothing_is_declared(self):
        entry = parse("name: n\ncommand: docker system prune\n")
        assert entry.risk == "high"
        assert any("prune" in reason for reason in entry.risk_reasons)

    def test_unconfirming_flag_raises_the_floor(self):
        entry = parse("name: n\ncommand: ls --force\n")
        assert entry.risk == "medium"
        assert any("免确认" in reason for reason in entry.risk_reasons)

    def test_unknown_verbs_fall_back_to_medium(self):
        entry = parse("name: n\ncommand: frobnicate\n")
        assert entry.risk == "medium"
        assert any("兜底 medium" in reason for reason in entry.risk_reasons)

    def test_destructive_shape_is_critical(self):
        entry = parse("name: n\ncommand: mkfs.ext4 /dev/sdb\n")
        assert entry.risk == "critical"


class TestCommandBinary:
    def test_plain_command(self):
        assert catalog.command_binary("docker ps") == "docker"

    def test_wrappers_are_skipped(self):
        assert catalog.command_binary("sudo docker ps") == "docker"
        assert catalog.command_binary("env FOO=1 gh pr list") == "gh"

    def test_shell_builtins_are_not_dependencies(self):
        assert catalog.command_binary("cd /tmp && make") == ""

    def test_a_leading_flag_gives_up(self):
        assert catalog.command_binary("sudo -u root docker ps") == ""

    def test_empty_command(self):
        assert catalog.command_binary("   ") == ""

    def test_inference_lands_in_requires(self):
        entry = parse("name: n\ncommand: docker ps\n")
        assert entry.requires == ["docker"]
        assert any("自动补上" in warning for warning in entry.warnings)

    def test_declared_requires_come_first_and_are_not_duplicated(self):
        entry = parse("name: n\nrequires: [docker]\ncommand: docker ps\n")
        assert entry.requires == ["docker"]


class TestCompile:
    def test_steps_carry_the_command_verbatim(self):
        entry = parse(DOCKER, fallback_id="docker-cleanup")
        compiled = entry.to_workflow_dict()
        execute = compiled["steps"][0]["execute"]
        assert [task["instruction"] for task in execute] == ["docker system prune -f"]
        assert execute[0]["agent_type"] == "shell"
        assert compiled["steps"][0]["trigger"]["event_type"] == "workflow.request"

    def test_ecosystem_metadata_rides_in_config(self):
        entry = parse(DOCKER, fallback_id="docker-cleanup")
        meta = entry.to_workflow_dict()["config"]["ecosystem"]
        assert meta["kind"] == "workflow"
        assert meta["trust"] == "third-party"
        assert meta["requires"] == ["docker"]
        assert meta["risk"] == "high"
        assert meta["enabled"] is True
        assert meta["source_url"] == "https://github.com/xxx/trimum-workflows"

    def test_compiled_definition_validates_and_round_trips(self, tmp_path):
        from trimum_core.workflow_engine import WorkflowDefV2

        entry = parse(DOCKER, fallback_id="docker-cleanup")
        definition = entry.build_workflow()
        assert isinstance(definition, WorkflowDefV2)
        assert definition.id == "docker-cleanup"

        path = write(tmp_path / "workflow.yaml", entry.to_yaml())
        reloaded = WorkflowDefV2.load_yaml(path)
        assert reloaded.id == "docker-cleanup"
        assert reloaded.steps[0].execute[0].instruction == "docker system prune -f"

    def test_timeout_reaches_the_task(self):
        entry = parse("name: n\ncommand: ls\ntimeout: 5\n")
        task = entry.to_workflow_dict()["steps"][0]["execute"][0]
        assert task["timeout_seconds"] == 5.0


class TestDiscover:
    def test_a_single_file(self, tmp_path):
        path = write(tmp_path / "one.yaml", DOCKER)
        assert catalog.discover_catalogs(path) == [path]

    def test_workflow_yaml_layout(self, tmp_path):
        write(tmp_path / "docker-cleanup" / "workflow.yaml", DOCKER)
        found = catalog.discover_catalogs(tmp_path)
        assert [path.name for path in found] == ["workflow.yaml"]

    def test_loose_yaml_files(self, tmp_path):
        write(tmp_path / "a.yaml", DOCKER)
        write(tmp_path / "b.yml", "name: b\ncommand: ls\n")
        found = catalog.discover_catalogs(tmp_path)
        assert sorted(path.name for path in found) == ["a.yaml", "b.yml"]

    def test_missing_path_is_an_error(self, tmp_path):
        with pytest.raises(catalog.CatalogError):
            catalog.discover_catalogs(tmp_path / "nope")

    def test_empty_directory_finds_nothing(self, tmp_path):
        assert catalog.discover_catalogs(tmp_path) == []


class TestPlanAndWrite:
    def test_plan_reports_every_file_separately(self, tmp_path):
        write(tmp_path / "docker-cleanup.yaml", DOCKER)
        write(tmp_path / "broken.yaml", "name: broken\nrisk: nonsense\ncommand: ls\n")
        plan = catalog.plan_import(tmp_path, root=tmp_path / "home")
        rows = {item.get("id"): item for item in plan["workflows"]}
        assert plan["importable"] == 1
        broken = rows[None]
        assert broken["problems"]
        assert rows["docker-cleanup"]["problems"] == []
        assert plan["problems"][broken["path"]] == broken["problems"]

    def test_plan_targets_the_workflow_layout(self, tmp_path):
        write(tmp_path / "docker-cleanup.yaml", DOCKER)
        plan = catalog.plan_import(tmp_path, root=tmp_path / "home")
        item = plan["workflows"][0]
        assert item["file"] == str(tmp_path / "home" / "docker-cleanup" / "workflow.yaml")

    def test_duplicate_ids_are_a_problem(self, tmp_path):
        write(tmp_path / "a.yaml", "id: same\nname: a\ncommand: ls\n")
        write(tmp_path / "b.yaml", "id: same\nname: b\ncommand: pwd\n")
        plan = catalog.plan_import(tmp_path, root=tmp_path / "home")
        assert plan["importable"] == 1
        flagged = [item for item in plan["workflows"] if item["problems"]]
        assert any("重复" in problem for problem in flagged[0]["problems"])

    def test_dry_run_writes_nothing(self, tmp_path):
        write(tmp_path / "docker-cleanup.yaml", DOCKER)
        plan = catalog.plan_import(tmp_path, root=tmp_path / "home")
        assert catalog.write_workflows(plan, dry_run=True) == []
        assert not (tmp_path / "home").exists()

    def test_write_lands_where_load_from_dir_looks(self, tmp_path):
        write(tmp_path / "docker-cleanup.yaml", DOCKER)
        plan = catalog.plan_import(tmp_path, root=tmp_path / "home")
        written = catalog.write_workflows(plan)
        assert written == [str(tmp_path / "home" / "docker-cleanup" / "workflow.yaml")]

        from trimum_core.workflow_engine import WorkflowDefV2

        loaded = WorkflowDefV2.load_from_dir(str(tmp_path / "home"))
        assert [item.id for item in loaded] == ["docker-cleanup"]

    def test_existing_target_is_refused_without_force(self, tmp_path):
        write(tmp_path / "docker-cleanup.yaml", DOCKER)
        plan = catalog.plan_import(tmp_path, root=tmp_path / "home")
        catalog.write_workflows(plan)
        with pytest.raises(ImportRefused):
            catalog.write_workflows(plan)
        assert catalog.write_workflows(plan, force=True)

    def test_a_clash_blocks_the_whole_batch(self, tmp_path):
        write(tmp_path / "a.yaml", "name: a\ncommand: ls\n")
        write(tmp_path / "b.yaml", "name: b\ncommand: pwd\n")
        plan = catalog.plan_import(tmp_path, root=tmp_path / "home")
        write(tmp_path / "home" / "b" / "workflow.yaml", "id: b\n")
        with pytest.raises(ImportRefused):
            catalog.write_workflows(plan)
        assert not (tmp_path / "home" / "a" / "workflow.yaml").exists()

    def test_nothing_importable_is_refused(self, tmp_path):
        write(tmp_path / "broken.yaml", "name: broken\nrisk: nonsense\ncommand: ls\n")
        plan = catalog.plan_import(tmp_path, root=tmp_path / "home")
        with pytest.raises(ImportRefused):
            catalog.write_workflows(plan)

    def test_the_refusal_type_is_shared_with_the_cli_adapter(self):
        assert ImportRefused is adapter.ImportRefused
