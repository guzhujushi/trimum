"""LearningEngine 单元测试。"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from trimum_core.behavior_monitor import BehaviorMonitor
from trimum_core.learning_engine import LearningEngine, AgentProfile, LearnedRule


class TestLearningEngineBasics:
    """基础功能测试."""

    def test_init_defaults(self):
        eng = LearningEngine()
        assert eng.get_mode() == "normal"
        assert eng._min_observations == 20
        assert eng._confidence_threshold == 0.85

    def test_init_custom(self, tmp_path):
        eng = LearningEngine(mode="strict", min_observations=5, confidence_threshold=0.9, learning_dir=str(tmp_path))
        assert eng.get_mode() == "strict"
        assert eng._min_observations == 5
        assert eng._confidence_threshold == 0.9

    def test_set_mode(self):
        eng = LearningEngine()
        eng.set_mode("strict")
        assert eng.get_mode() == "strict"
        eng.set_mode("auto")
        assert eng.get_mode() == "auto"

    def test_set_mode_invalid(self):
        eng = LearningEngine()
        with pytest.raises(ValueError):
            eng.set_mode("invalid")


class TestLearningModeDetermination:
    """学习模式判定测试."""

    def test_strict_when_few_actions(self):
        eng = LearningEngine(min_observations=10, min_actions_for_auto=50)
        profile = AgentProfile(agent_id="test", total_actions=5)
        assert eng._determine_mode(profile) == "strict"

    def test_normal_when_sufficient_actions(self):
        eng = LearningEngine(min_observations=10, min_actions_for_auto=50)
        profile = AgentProfile(agent_id="test", total_actions=30)
        assert eng._determine_mode(profile) == "normal"

    def test_auto_when_many_actions_low_deny(self):
        eng = LearningEngine(min_observations=10, min_actions_for_auto=50)
        profile = AgentProfile(agent_id="test", total_actions=100, deny_count=2)
        assert eng._determine_mode(profile) == "auto"

    def test_keeps_explicit_mode(self):
        eng = LearningEngine(min_observations=10)
        profile = AgentProfile(agent_id="test", total_actions=5, learning_mode="auto")
        # 即使操作数不足，显式设置的模式保留
        assert eng._determine_mode(profile) == "auto"

    def test_not_auto_when_high_deny_rate(self):
        eng = LearningEngine(min_observations=10, min_actions_for_auto=50)
        profile = AgentProfile(agent_id="test", total_actions=100, deny_count=30)
        assert eng._determine_mode(profile) == "normal"


class TestConfidence:
    """置信度计算测试."""

    def test_low_confidence_few_samples(self):
        eng = LearningEngine()
        profile = AgentProfile(agent_id="test")
        assert eng._calculate_confidence("file_read", count=2, profile=profile) == 0.0

    def test_high_confidence_many_samples(self):
        eng = LearningEngine()
        profile = AgentProfile(agent_id="test", total_actions=100, deny_count=0)
        conf = eng._calculate_confidence("file_read", count=50, profile=profile)
        # 50次file_read + 0拒绝 => conf ≈ 0.78，实际合理值
        assert conf > 0.7

    def test_confidence_penalized_by_deny(self):
        eng = LearningEngine()
        profile_low_deny = AgentProfile(agent_id="test", total_actions=100, deny_count=0)
        profile_high_deny = AgentProfile(agent_id="test", total_actions=100, deny_count=30)
        conf_low = eng._calculate_confidence("file_read", count=50, profile=profile_low_deny)
        conf_high = eng._calculate_confidence("file_read", count=50, profile=profile_high_deny)
        assert conf_low > conf_high

    def test_risk_penalty_high_risk_action(self):
        eng = LearningEngine()
        profile = AgentProfile(agent_id="test", total_actions=100, deny_count=0)
        conf_safe = eng._calculate_confidence("file_read", count=50, profile=profile)
        conf_risky = eng._calculate_confidence("container", count=50, profile=profile)
        assert conf_safe > conf_risky


class TestAnalysis:
    """核心分析逻辑测试."""

    def test_analyze_no_actions(self):
        eng = LearningEngine(min_observations=5)
        monitor = BehaviorMonitor()
        eng = LearningEngine(monitor=monitor, min_observations=5)
        summary = eng.analyze()
        assert isinstance(summary, dict)

    def test_analyze_generates_rules_after_enough_observations(self, tmp_path):
        monitor = BehaviorMonitor(window_seconds=3000)
        eng = LearningEngine(monitor=monitor, learning_dir=str(tmp_path), min_observations=1, confidence_threshold=0.5)

        # 模拟更多 file_read 操作以提高置信度
        for _ in range(80):
            monitor.record(agent_id="agent-a", action_type="file_read", target="/tmp/a.txt")

        summary = eng.analyze()
        assert "agent-a" in summary
        assert summary["agent-a"]["new_rules"] > 0

    def test_analyze_does_not_generate_rules_below_threshold(self):
        monitor = BehaviorMonitor(window_seconds=3000)
        eng = LearningEngine(monitor=monitor, min_observations=1, confidence_threshold=0.99)

        for _ in range(5):
            monitor.record(agent_id="agent-a", action_type="file_write", target="/tmp/a.txt")

        summary = eng.analyze()
        assert summary["agent-a"]["new_rules"] == 0

    def test_record_deny(self):
        eng = LearningEngine()
        eng.record_deny("agent-a")
        profile = eng.get_profile("agent-a")
        assert profile is not None
        assert profile.deny_count == 1


class TestRulesetGeneration:
    """ruleset 生成测试."""

    def test_generate_empty_ruleset(self, tmp_path):
        eng = LearningEngine(learning_dir=str(tmp_path))
        rules = eng.generate_ruleset()
        assert rules == []

    def test_generate_ruleset_with_agent_filter(self):
        monitor = BehaviorMonitor(window_seconds=3000)
        eng = LearningEngine(monitor=monitor, min_observations=1, confidence_threshold=0.5)

        for _ in range(30):
            monitor.record(agent_id="agent-a", action_type="file_read")
            monitor.record(agent_id="agent-b", action_type="file_write")

        eng.analyze()

        rules_a = eng.generate_ruleset(agent_id="agent-a")
        rules_all = eng.generate_ruleset()
        assert len(rules_a) > 0
        assert len(rules_all) > 0

    def test_auto_allow_rule_shape(self):
        eng = LearningEngine()
        rule = eng.auto_allow_rule("file_read")
        assert rule["pattern"] == "file_read"
        assert rule["action"] == "auto"
        assert rule["risk"] == "low"
        assert rule["source"] == "learned"


class TestPersistence:
    """持久化测试."""

    def test_save_and_load(self, tmp_path):
        monitor = BehaviorMonitor(window_seconds=3000)
        eng = LearningEngine(monitor=monitor, learning_dir=str(tmp_path),
                             min_observations=1, confidence_threshold=0.5)

        for _ in range(30):
            monitor.record(agent_id="agent-a", action_type="file_read")

        eng.analyze()

        # 新引擎加载相同路径
        eng2 = LearningEngine(learning_dir=str(tmp_path))
        assert len(eng2.get_learned_rules()) > 0
        assert eng2.get_mode() == eng.get_mode()

    def test_load_missing_file(self, tmp_path):
        eng = LearningEngine(learning_dir=str(tmp_path / "nonexistent"))
        # 应该静默失败
        assert eng.get_learned_rules() == []

    def test_load_corrupted_file(self, tmp_path):
        # 写一个坏文件
        bad_file = tmp_path / "learning_data.json"
        with open(bad_file, "w") as f:
            f.write("not json")

        eng = LearningEngine(learning_dir=str(tmp_path))
        assert eng.get_learned_rules() == []


class TestProfile:
    """AgentProfile 数据类测试."""

    def test_profile_defaults(self):
        p = AgentProfile(agent_id="test")
        assert p.total_actions == 0
        assert p.deny_count == 0
        assert p.action_counts == {}
        assert p.learned_rules == {}
        assert p.learning_mode == "normal"

    def test_summary(self):
        eng = LearningEngine(min_observations=5)
        summary = eng.get_summary()
        assert "mode" in summary
        assert "profiles_count" in summary
        assert "learned_rules_count" in summary
