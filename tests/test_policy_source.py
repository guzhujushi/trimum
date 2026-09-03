"""Tests for PolicyEngine source_type awareness + SourceType models."""

import tempfile
from pathlib import Path

import pytest

from trimum_core.models import SourceType, RiskLevel, Action
from trimum_core.policy_engine import PolicyEngine


class TestSourceTypeModel:
    def test_source_type_values(self):
        assert SourceType.HUMAN == "human"
        assert SourceType.AI == "ai"
        assert SourceType.WORKFLOW == "workflow"
        assert SourceType.SYSTEM == "system"

    def test_source_type_default(self):
        # 在 ExecuteRequest / SystemEvent 里的默认值
        assert SourceType.UNKNOWN == "unknown"


class TestPolicyEngineSourceAware:
    """PolicyEngine 的 source_type 感知能力。"""

    @pytest.fixture
    def policy_with_source_rules(self):
        """创建一个临时 policy.yaml 包含 source 过滤规则。"""
        content = """
        rules:
          - pattern: "rm"
            risk: critical
            action: deny
            description: "rm is always denied for AI origin"
          - pattern: "rm"
            risk: high
            action: confirm
            source: human
            description: "Human rm with confirm"
          - pattern: ".*"
            risk: low
            action: auto
            source: ai
            description: "Safe auto for AI origin"
        """
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "policy.yaml"
            p.write_text(content, encoding="utf-8")
            yield PolicyEngine(policy_path=p)

    def test_ai_rm_is_denied(self, policy_with_source_rules):
        """AI 来源的 rm → deny（无 source 过滤的规则优先匹配）"""
        risk, action, reason = policy_with_source_rules.evaluate(
            "rm -rf /tmp/test", source_type=SourceType.AI
        )
        assert action == Action.DENY
        assert risk == RiskLevel.CRITICAL

    def test_human_rm_is_confirm(self, policy_with_source_rules):
        """人类来源的 rm → 无 source 过滤的 rm 规则先匹配 → 也是 deny

        因为第一条 rm 规则没有 source 过滤，全局匹配。
        若想让 human rm 不同处理，需要在 YAML 中显式配置。
        """
        risk, action, reason = policy_with_source_rules.evaluate(
            "rm -rf /tmp/test", source_type=SourceType.HUMAN
        )
        # 第一条 rm 规则无 source 过滤，先匹配 → deny
        assert action == Action.DENY

    def test_no_source_type_matches_unfiltered(self, policy_with_source_rules):
        """不传 source_type → 匹配无 source 过滤的 rm 规则（deny）"""
        risk, action, reason = policy_with_source_rules.evaluate("rm -rf /tmp/test")
        assert action == Action.DENY

    def test_ai_ls_is_auto(self, policy_with_source_rules):
        """AI 来源的 ls → 匹配 source:ai 的通配规则 → auto"""
        risk, action, reason = policy_with_source_rules.evaluate(
            "ls -la", source_type=SourceType.AI
        )
        assert action == Action.AUTO

    def test_unknown_source_default(self):
        """未知来源 → 默认 confirm"""
        content = """
        rules:
          - pattern: "echo"
            risk: low
            action: auto
        """
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "policy.yaml"
            p.write_text(content, encoding="utf-8")
            engine = PolicyEngine(policy_path=p)

            risk, action, reason = engine.evaluate(
                "echo hello", source_type=SourceType.UNKNOWN
            )
            assert action == Action.AUTO  # 规则匹配优先

            risk, action, reason = engine.evaluate(
                "something_unknown", source_type=SourceType.UNKNOWN
            )
            assert action == Action.CONFIRM  # 默认
