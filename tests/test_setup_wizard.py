"""Tests for the first-run wizard — `trimum_core.setup_wizard` + `trm setup`."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import agent_cert as agent_cert_mod  # noqa: E402
from trimum_core import hosts as hosts_mod  # noqa: E402
from trimum_core import identity as identity_mod  # noqa: E402
from trimum_core import setup_wizard as wizard  # noqa: E402
from trimum_core.cli import main  # noqa: E402

SKILL_MD = """---
name: {name}
description: Fixture skill
---

# {name}
"""


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch):
    """Isolate TRIMUM_HOME, the host scan root and every host override."""
    home = tmp_path / "home"
    home.mkdir()
    trimum = tmp_path / "trimum"
    monkeypatch.setenv("TRIMUM_HOME", str(trimum))
    monkeypatch.setenv(hosts_mod.SCAN_HOME_ENV, str(home))
    monkeypatch.delenv("TRIMUM_SKILL_TARGETS", raising=False)
    monkeypatch.delenv(hosts_mod.HOSTS_ENV, raising=False)
    monkeypatch.delenv(hosts_mod.HOSTS_DISABLE_ENV, raising=False)
    monkeypatch.delenv("TRIMUM_USER", raising=False)
    return SimpleNamespace(tmp=tmp_path, home=home, trimum=trimum)


@pytest.fixture()
def skill_source(tmp_path: Path, monkeypatch) -> Path:
    """Point the wizard at a throwaway skill source instead of the repo."""
    source = tmp_path / "skills-src"
    skill = source / "fixture-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        SKILL_MD.format(name="fixture-skill"), encoding="utf-8"
    )
    monkeypatch.setattr(wizard, "default_source_roots", lambda: [source])
    return source


class TestCatalog:
    def test_repo_catalog_loads(self):
        catalog = wizard.load_catalog()
        assert catalog["loaded"] is True
        groups = catalog["groups"]
        assert len(groups) >= 5
        names = [entry["name"] for entry in wizard.catalog_entries(catalog)]
        assert len(names) == len(set(names))
        for entry in wizard.catalog_entries(catalog):
            assert entry["name"] and entry["label"]
            assert isinstance(entry["packages"], dict)
            assert entry["group"] and entry["group_label"]

    def test_missing_catalog_is_empty_not_fatal(self, tmp_path):
        catalog = wizard.load_catalog(tmp_path / "nope.yaml")
        assert catalog["loaded"] is False
        assert wizard.catalog_entries(catalog) == []

    def test_find_entry_case_insensitive(self):
        catalog = wizard.load_catalog()
        assert wizard.find_entry(catalog, "PYTHON")["name"] == "python"
        assert wizard.find_entry(catalog, "nope") is None

    def test_resolve_tools_splits_known_and_unknown(self):
        catalog = wizard.load_catalog()
        selected, unknown = wizard.resolve_tools(catalog, ["python", "", "nope"])
        assert [entry["name"] for entry in selected] == ["python"]
        assert unknown == ["nope"]

    def test_parse_tool_names(self):
        assert wizard.parse_tool_names(" python , uv ,,") == ["python", "uv"]
        assert wizard.parse_tool_names("") == []

    def test_render_catalog_numbers_every_entry(self):
        catalog = wizard.load_catalog()
        rendered = wizard.render_catalog(catalog)
        for entry in wizard.catalog_entries(catalog):
            assert entry["name"] in rendered
        assert "[ 1]" in rendered
        assert "[" + str(len(wizard.catalog_entries(catalog))).rjust(2) + "]" in rendered

    def test_prompt_selects_by_number(self):
        catalog = wizard.load_catalog()
        entries = wizard.catalog_entries(catalog)
        selected, answer = wizard.prompt_tools(catalog, input_fn=lambda _prompt: "1, 3")
        assert [entry["name"] for entry in selected] == [
            entries[0]["name"],
            entries[2]["name"],
        ]
        assert answer == "1, 3"

    def test_prompt_ignores_nonsense_and_eof(self):
        catalog = wizard.load_catalog()
        assert wizard.prompt_tools(catalog, input_fn=lambda _p: "abc")[0] == []

        def boom(_prompt):
            raise EOFError

        assert wizard.prompt_tools(catalog, input_fn=boom)[0] == []


class TestWizardSteps:
    def test_dry_run_writes_nothing(self, sandbox):
        report = wizard.run_setup(
            dry_run=True, interactive=False, which=lambda name: None
        )
        assert report["state_written"] is False
        assert report["state_path"] == ""
        assert set(report["steps"]) == set(wizard.STEPS)
        assert list(sandbox.home.iterdir()) == []
        assert not sandbox.trimum.exists()

    def test_missing_crypto_skips_identity(self, sandbox, monkeypatch):
        monkeypatch.setattr(identity_mod, "crypto_available", lambda: False)
        report = wizard.run_setup(steps=("identity",), interactive=False)
        assert report["steps"]["identity"]["status"] == "skipped"
        assert not (sandbox.trimum / "identity").exists()

    def test_full_run_creates_identity_state_and_links(self, sandbox, skill_source):
        (sandbox.home / ".claude").mkdir()
        report = wizard.run_setup(
            interactive=False, tools="python", which=lambda name: None
        )
        steps = report["steps"]

        assert steps["hosts"]["detected"] == ["claude"]
        assert steps["identity"]["status"] == "created"
        doc = steps["identity"]["doc"]
        assert doc["capabilities"] == {
            "tools": ["*"],
            "max_risk": "inherit",
            "expires_at": None,
            "scope": "local",
        }
        assert doc["public_key_fingerprint"].startswith("sha256:")
        assert doc["machine_id"]

        assert steps["toolchain"]["selected"] == ["python"]
        assert steps["toolchain"]["install"] == "deferred"
        assert steps["toolchain"]["unknown"] == []

        assert steps["skills"]["summary"] == {"linked": 2}  # host root + own root
        assert (sandbox.home / ".claude" / "skills" / "fixture-skill" / "SKILL.md").is_file()
        assert (sandbox.trimum / "agent-skills" / "fixture-skill").exists()

        state = json.loads((sandbox.trimum / "config" / "setup.json5").read_text("utf-8"))
        assert state["schema"] == wizard.STATE_SCHEMA
        assert state["steps"]["hosts"]["detected"] == ["claude"]
        assert state["state_path"] == str(sandbox.trimum / "config" / "setup.json5")

    def test_unknown_tool_names_are_reported(self, sandbox, skill_source):
        report = wizard.run_setup(
            steps=("toolchain",), interactive=False, tools="python,nope"
        )
        toolchain = report["steps"]["toolchain"]
        assert toolchain["selected"] == ["python"]
        assert toolchain["unknown"] == ["nope"]

    def test_non_interactive_skips_prompt(self, sandbox):
        def boom(_prompt):
            raise AssertionError("must not prompt in non-interactive mode")

        report = wizard.run_setup(
            steps=("toolchain",), interactive=False, input_fn=boom
        )
        assert report["steps"]["toolchain"]["selected"] == []
        assert "非交互模式" in report["steps"]["toolchain"]["note"]

    def test_interactive_records_prompt_selection(self, sandbox):
        report = wizard.run_setup(
            steps=("toolchain",), interactive=True, input_fn=lambda _p: "2"
        )
        expected = wizard.catalog_entries(wizard.load_catalog())[1]["name"]
        assert report["steps"]["toolchain"]["selected"] == [expected]
        assert report["steps"]["toolchain"]["selection_source"] == "prompt"

    def test_dry_run_never_prompts(self, sandbox):
        def boom(_prompt):
            raise AssertionError("dry-run must not prompt")

        report = wizard.run_setup(
            steps=("toolchain",), interactive=True, dry_run=True, input_fn=boom
        )
        assert report["steps"]["toolchain"]["selected"] == []

    def test_all_hosts_targets_every_known_host(self, sandbox, skill_source):
        report = wizard.run_setup(
            steps=("hosts",), interactive=False, all_hosts=True, which=lambda name: None
        )
        assert len(report["steps"]["hosts"]["targets"]) == len(hosts_mod.KNOWN_HOSTS) + 1

    def test_unknown_step_raises(self, sandbox):
        with pytest.raises(ValueError):
            wizard.run_setup(steps=("nope",), interactive=False)


class TestIdentity:
    def test_generate_creates_keypair_and_doc(self, sandbox):
        result = identity_mod.generate_identity()
        assert result["status"] == "created"
        assert identity_mod.key_path().is_file()
        assert identity_mod.pub_path().is_file()
        doc = identity_mod.load_identity()
        assert doc["schema"] == identity_mod.SCHEMA
        assert doc["issued_by"] == "self"
        assert doc["key_type"] == "ed25519"
        assert identity_mod.is_bound_to_machine(doc) is True

    def test_second_run_keeps_existing_unless_forced(self, sandbox):
        first = identity_mod.generate_identity()
        assert identity_mod.generate_identity()["status"] == "existing"
        replaced = identity_mod.generate_identity(force=True)
        assert replaced["status"] == "replaced"
        assert (
            replaced["doc"]["public_key_fingerprint"]
            != first["doc"]["public_key_fingerprint"]
        )

    def test_capabilities_only_tighten(self, sandbox):
        doc = identity_mod.generate_identity(max_risk="low")["doc"]
        assert doc["capabilities"]["max_risk"] == "low"
        with pytest.raises(ValueError):
            identity_mod.generate_identity(max_risk="higher-than-policy", force=True)

    def test_user_name_comes_from_env(self, sandbox, monkeypatch):
        monkeypatch.setenv("TRIMUM_USER", "guzhu")
        doc = identity_mod.generate_identity()["doc"]
        assert doc["user"] == "guzhu"

    def test_machine_mismatch_is_detected(self, sandbox):
        doc = identity_mod.generate_identity()["doc"]
        tampered = dict(doc, machine_id="some-other-machine")
        assert identity_mod.is_bound_to_machine(tampered) is False
        assert identity_mod.is_bound_to_machine(None) is False

    def test_status_reports_without_writing(self, sandbox):
        before = identity_mod.status()
        assert before["exists"] is False
        assert not sandbox.trimum.exists()


class TestSetupCommand:
    def test_dry_run_json(self, sandbox, capsys):
        assert main(["--json", "setup", "--dry-run", "--yes", "--tools", "python"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["dry_run"] is True
        assert data["interactive"] is False
        assert data["steps"]["toolchain"]["selected"] == ["python"]
        assert data["state_written"] is False

    def test_skip_removes_steps(self, sandbox, capsys):
        assert main(["setup", "--dry-run", "--yes", "--skip", "identity", "--skip", "toolchain"]) == 0
        out = capsys.readouterr().out
        assert "identity" not in out.split("next")[0]
        assert main(["--json", "setup", "--dry-run", "--yes", "--skip", "identity"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["steps_run"] == ["hosts", "official", "toolchain", "skills"]

    def test_all_steps_skipped_fails(self, sandbox, capsys):
        args = ["setup", "--dry-run", "--yes"]
        for step in wizard.STEPS:
            args += ["--skip", step]
        assert main(args) == 1
        assert "nothing to do" in capsys.readouterr().err

    def test_unknown_tool_exits_nonzero(self, sandbox, capsys):
        assert main(["setup", "--dry-run", "--yes", "--tools", "nope"]) == 1
        assert "unknown toolchain entries" in capsys.readouterr().err

    def test_bad_catalog_path_fails(self, sandbox, capsys):
        assert main(["setup", "--dry-run", "--yes", "--catalog", "nope.yaml"]) == 1
        assert "cannot read catalog" in capsys.readouterr().err

    def test_human_output_mentions_detected_hosts(self, sandbox, capsys):
        (sandbox.home / ".claude").mkdir()
        assert main(["setup", "--dry-run", "--yes"]) == 0
        out = capsys.readouterr().out
        assert "hosts      : detected claude" in out
        assert "toolchain  : selected (none)" in out

class TestOfficialStep:
    def test_dry_run_reports_bundled_agents(self, sandbox, tmp_path, monkeypatch):
        base = tmp_path / "agents"
        (base / "maintenance").mkdir(parents=True)
        (base / "maintenance" / "agent.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(agent_cert_mod, "bundled_agent_dirs", lambda: [base])

        report = wizard.run_setup(steps=("official",), dry_run=True, interactive=False)
        step = report["steps"]["official"]
        assert step["bundled"] == ["maintenance"]
        assert step["issued"] == []
        assert not (sandbox.trimum / "certs").exists()

    def test_run_issues_official_cert(self, sandbox, tmp_path, monkeypatch):
        base = tmp_path / "agents"
        (base / "maintenance").mkdir(parents=True)
        (base / "maintenance" / "agent.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(agent_cert_mod, "bundled_agent_dirs", lambda: [base])

        report = wizard.run_setup(steps=("official",), interactive=False)
        step = report["steps"]["official"]
        assert step["issued"] == ["maintenance"]
        cert_path = sandbox.trimum / "certs" / "official" / "maintenance.cert.json"
        assert cert_path.is_file()
        assert json.loads(cert_path.read_text("utf-8"))["capabilities"]["scope"] == "official"

    def test_no_bundled_agents_is_a_no_op(self, sandbox):
        report = wizard.run_setup(steps=("official",), interactive=False)
        assert report["steps"]["official"] == {
            "bundled": [],
            "issued": [],
            "existing": [],
            "dry_run": False,
            "note": report["steps"]["official"]["note"],
        }
        assert not (sandbox.trimum / "certs").exists()

    def test_step_is_listed_in_wizard_steps(self):
        assert "official" in wizard.STEPS
