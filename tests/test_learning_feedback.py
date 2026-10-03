"""学习反馈环测试：执行结果 → BehaviorMonitor → LearningEngine → PolicyEngine。

Phase 3 收尾 P1：此前没有任何地方调用 BehaviorMonitor.record，异常检测与学习
引擎都是空转；置信度上限（0.78）也低于默认阈值（0.85），学习恒不产出规则。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.behavior_monitor import BehaviorMonitor, pattern_for_action_type
from trimum_core.learning_engine import LearningEngine
from trimum_core.models import ExecuteRequest, SourceType, ToolType
from trimum_core.policy_engine import PolicyEngine
from trimum_core.tool_gateway import ToolGateway


def request(command: str = "cat /var/log/syslog", agent: str = "agent-a") -> ExecuteRequest:
    return ExecuteRequest(
        tool=ToolType.SHELL,
        args=command.split(),
        agent_id=agent,
        source_type=SourceType.AI,
        skip_cwd_check=True,
    )


class TestBehaviorMonitorFeeding:
    def test_record_command_classifies_and_records(self):
        monitor = BehaviorMonitor()
        action_type = monitor.record_command("a", "git status")
        assert action_type == "vcs_operation"
        assert monitor.get_stats("a")["action_type_counts"]["vcs_operation"] == 1

    def test_pattern_for_action_type_maps_to_regex(self):
        assert pattern_for_action_type("file_read").startswith("^(cat|")
        assert pattern_for_action_type("other") is None

    @pytest.mark.asyncio
    async def test_gateway_feeds_monitor(self):
        monitor = BehaviorMonitor()
        gw = ToolGateway(behavior_monitor=monitor)
        await gw.execute(request("cat /var/log/syslog", agent="agent-a"))

        stats = monitor.get_stats("agent-a")
        assert stats["action_type_counts"].get("file_read") == 1
        assert stats["total_actions"] == 1

    @pytest.mark.asyncio
    async def test_denied_command_counts_as_deny(self, tmp_path):
        monitor = BehaviorMonitor()
        engine = LearningEngine(monitor=monitor, learning_dir=str(tmp_path))

        class DenyRule:
            async def can_execute(self, agent_id, command, sandbox="default", resource_ctx=None, source_type=None):
                from trimum_core.security_rule import DecisionResult

                return DecisionResult("deny", "nope", risk_level="high")

        gw = ToolGateway(security_rule=DenyRule(), behavior_monitor=monitor, learning_engine=engine)
        resp = await gw.execute(request("rm -rf /tmp/x", agent="agent-a"))

        assert resp.status == "denied"
        assert engine.get_profile("agent-a").deny_count == 1

    @pytest.mark.asyncio
    async def test_behavior_record_failure_does_not_break_execution(self):
        class BrokenMonitor:
            def record_command(self, *args, **kwargs):
                raise RuntimeError("boom")

        gw = ToolGateway(behavior_monitor=BrokenMonitor())
        resp = await gw.execute(request("echo hi"))
        assert resp.status in ("allowed", "confirmed")


class TestLearningLoop:
    def _observed_engine(self, tmp_path, samples=60):
        monitor = BehaviorMonitor()
        engine = LearningEngine(
            monitor=monitor, learning_dir=str(tmp_path), mode="normal", min_observations=5
        )
        for _ in range(samples):
            monitor.record_command("agent-a", "cat /var/log/syslog")
            monitor.record_command("agent-a", "git status")
        return engine

    def test_confidence_reaches_default_threshold(self):
        """50 次零拒绝的 file_read 应能越过默认阈值（修复前上限 0.78 < 0.85）。"""
        engine = LearningEngine(learning_dir="tmp/learning_conf")
        from trimum_core.learning_engine import AgentProfile

        profile = AgentProfile(agent_id="a", total_actions=100, deny_count=0)
        conf = engine._calculate_confidence("file_read", 50, profile)
        assert conf >= engine._confidence_threshold

    def test_analyze_generates_rules_with_command_patterns(self, tmp_path):
        engine = self._observed_engine(tmp_path)
        summary = engine.analyze()

        assert summary["agent-a"]["new_rules"] == 2
        patterns = {rule.pattern for rule in engine.get_learned_rules()}
        assert "^(cat|less|more|head|tail|read)\\b" in patterns
        assert "^(git|svn|hg)\\b" in patterns

    def test_analyze_without_data_is_empty(self, tmp_path):
        engine = LearningEngine(monitor=BehaviorMonitor(), learning_dir=str(tmp_path))
        assert engine.analyze() == {}

    def test_ruleset_injects_into_policy_once(self, tmp_path):
        engine = self._observed_engine(tmp_path)
        engine.analyze()
        policy = PolicyEngine()

        assert engine.inject_to_policy(policy) == 2
        assert engine.inject_to_policy(policy) == 0  # 去重，不重复堆规则

        learned = [r["pattern"] for r in policy._rules if r.get("source") == "learned"]
        assert "^(cat|less|more|head|tail|read)\\b" in learned

    def test_profiles_view(self, tmp_path):
        engine = self._observed_engine(tmp_path, samples=3)
        engine.analyze()
        profiles = engine.get_profiles()

        assert set(profiles) == {"agent-a"}
        assert profiles["agent-a"].total_actions == 6

    def test_persistence_roundtrip(self, tmp_path):
        engine = self._observed_engine(tmp_path)
        engine.analyze()

        reloaded = LearningEngine(
            monitor=BehaviorMonitor(), learning_dir=str(tmp_path), mode="normal"
        )
        patterns = {rule.pattern for rule in reloaded.get_learned_rules()}
        assert "^(cat|less|more|head|tail|read)\\b" in patterns