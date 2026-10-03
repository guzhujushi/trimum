"""Tests for the ecosystem entry schema and risk grader — E4 (`ecosystem.py`)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import ecosystem as eco  # noqa: E402


class TestWordTokens:
    def test_splits_on_dash_underscore_dot_and_space(self):
        assert eco.word_tokens("git-status") == ["git", "status"]
        assert eco.word_tokens("create_thing") == ["create", "thing"]
        assert eco.word_tokens("docker.system.prune") == ["docker", "system", "prune"]
        assert eco.word_tokens("  List Files ") == ["list", "files"]

    def test_empty_pieces_are_dropped(self):
        assert eco.word_tokens("a--b") == ["a", "b"]
        assert eco.word_tokens("") == []


class TestAssessRisk:
    def test_destructive_pattern_is_critical_and_short_circuits(self):
        level, reasons = eco.assess_risk("wipefs", "list")
        assert level == "critical"
        assert "wipefs" in reasons[0]

    def test_critical_wins_over_read_only_siblings(self):
        level, _ = eco.assess_risk("list", "mkfs")
        assert level == "critical"

    def test_system_changing_verb_is_high(self):
        level, reasons = eco.assess_risk("apt", "install")
        assert level == "high"
        assert "install" in reasons[0]

    def test_side_effecting_verb_is_medium(self):
        level, _ = eco.assess_risk("gh", "pr", "create")
        assert level == "medium"

    def test_read_only_verb_is_low(self):
        assert eco.assess_risk("git", "status")[0] == "low"
        assert eco.assess_risk("fd", "search")[0] == "low"

    def test_most_severe_token_wins(self):
        level, reasons = eco.assess_risk("git", "status", "push")
        assert level == "high"
        assert any("push" in reason for reason in reasons)

    def test_unknown_command_falls_back_to_medium_with_reason(self):
        level, reasons = eco.assess_risk("ripgrep")
        assert level == "medium"
        assert reasons == ["无证据：命令名与子命令都不在动词表里 → 兜底 medium"]

    def test_no_tokens_at_all_is_medium(self):
        assert eco.assess_risk()[0] == "medium"
        assert eco.assess_risk("", "  ")[0] == "medium"

    def test_unconfirming_flag_escalates_a_read_only_command(self):
        level, reasons = eco.assess_risk("git", "status", flags=["--force"])
        assert level == "medium"
        assert any("--force" in reason for reason in reasons)

    def test_flag_never_downgrades(self):
        assert eco.assess_risk("apt", "remove", flags=["--force"])[0] == "high"

    def test_short_yes_flag_escalates(self):
        assert eco.assess_risk("tool", flags=["-y"])[0] == "medium"

    def test_unrelated_flag_is_ignored(self):
        level, reasons = eco.assess_risk("git", "status", flags=["--porcelain"])
        assert level == "low"
        assert not any("--porcelain" in reason for reason in reasons)

    def test_reasons_are_human_readable(self):
        _, reasons = eco.assess_risk("apt", "install")
        assert reasons
        assert all(isinstance(reason, str) and reason for reason in reasons)


class TestMaxRisk:
    def test_picks_the_most_severe(self):
        assert eco.max_risk("low", "critical", "medium") == "critical"
        assert eco.max_risk("low", "medium") == "medium"

    def test_unknown_values_are_ignored(self):
        assert eco.max_risk("nonsense", "high") == "high"

    def test_nothing_usable_falls_back_to_default(self):
        assert eco.max_risk() == eco.DEFAULT_RISK
        assert eco.max_risk("", "bogus") == eco.DEFAULT_RISK


class TestEntry:
    def test_round_trip(self):
        entry = eco.EcosystemEntry(
            name="gh",
            kind="tool",
            description="GitHub CLI",
            trust="third-party",
            risk="medium",
            requires=["gh"],
            source_url="https://cli.github.com",
            author="cli",
            origin="help-probe",
            enabled=False,
            tags=["git"],
            risk_reasons=["`create` 含 `create` → medium"],
            details={"binary": "gh"},
        )
        restored = eco.EcosystemEntry.from_dict(entry.to_dict())
        assert restored == entry

    def test_from_dict_ignores_unknown_keys(self):
        entry = eco.EcosystemEntry.from_dict({"name": "x", "future_field": 1})
        assert entry.name == "x"
        assert entry.kind == "tool"

    def test_summary_mentions_state(self):
        entry = eco.EcosystemEntry(name="rg", risk="low")
        assert "disabled" in entry.summary()
        entry.enabled = True
        assert "enabled" in entry.summary()


class TestValidateEntry:
    def test_minimal_entry_is_valid(self):
        assert eco.validate_entry(eco.EcosystemEntry(name="gh")) == []

    def test_name_is_required(self):
        assert "name is required" in eco.validate_entry(eco.EcosystemEntry(name=""))

    def test_name_must_be_lowercase_and_simple(self):
        problems = eco.validate_entry(eco.EcosystemEntry(name="Git Hub"))
        assert any("lowercase" in problem for problem in problems)
        assert eco.validate_entry(eco.EcosystemEntry(name="../etc")) != []

    def test_name_length_is_bounded(self):
        problems = eco.validate_entry(eco.EcosystemEntry(name="a" * 65))
        assert any("64" in problem for problem in problems)

    def test_kind_trust_and_risk_are_enumerated(self):
        problems = eco.validate_entry(
            eco.EcosystemEntry(name="x", kind="plugin", trust="vibes", risk="spicy")
        )
        assert len(problems) == 3

    def test_source_url_must_be_http(self):
        entry = eco.EcosystemEntry(name="x", source_url="git@github.com:a/b")
        assert any("http" in problem for problem in eco.validate_entry(entry))

    def test_requires_must_be_non_empty_strings(self):
        entry = eco.EcosystemEntry(name="x", requires=["", "  "])
        problems = eco.validate_entry(entry)
        assert len(problems) == 2

    def test_validate_entries_reports_by_name(self):
        report = eco.validate_entries(
            [eco.EcosystemEntry(name="good"), eco.EcosystemEntry(name="bad", risk="?")]
        )
        assert list(report) == ["bad"]
