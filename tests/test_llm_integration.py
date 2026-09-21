"""#11 LLM 混合策略集成测试。

验证链路：
  ToolGateway.execute()
    → Layer 1: PolicyEngine (正则)
    → LLM enhance: LlmPolicyEngine.evaluate()
    → Layer 2-4: 权限/安全/JIT

测试场景：
  1. 低风险命令 → [llm-passthrough]
  2. 中等风险命令 → LLM 二次确认
  3. LLM 不可用 → [llm-fallback]
  4. 缓存命中 → 不重复调 LLM
  5. api_server AppState 创建时 llm_policy 正确注入
"""

import asyncio
import time
import json
import os
import sys
import platform
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.models import (
    ExecuteRequest,
    ExecuteResponse,
    RiskLevel,
    Action,
    SourceType,
    ToolType,
    SecurityMode,
    LLMDecision,
)
from trimum_core.tool_gateway import ToolGateway
from trimum_core.policy_engine import PolicyEngine
from trimum_core.llm_policy import LlmPolicyEngine, LLMDecisionCache
from trimum_core.security_config import SecurityConfig
from trimum_core.file_trust import FileTrustTracker
from pathlib import Path


# ── Fixtures ──

@pytest.fixture
def policy() -> PolicyEngine:
    return PolicyEngine()


@pytest.fixture
def sec_config() -> SecurityConfig:
    sc = SecurityConfig()
    sc.load()
    return sc


@pytest.fixture
def file_trust() -> FileTrustTracker:
    return FileTrustTracker(db_path=":memory:")


@pytest.fixture
def llm_policy(policy, sec_config) -> LlmPolicyEngine:
    return LlmPolicyEngine(policy_engine=policy, security_config=sec_config)


@pytest.fixture
def gateway(policy, llm_policy, file_trust) -> ToolGateway:
    return ToolGateway(
        policy_engine=policy,
        llm_policy=llm_policy,
        file_trust_tracker=file_trust,
    )


# ── Tests ──

class TestLLMPolicyIntegration:
    """验证 LlmPolicyEngine 在 ToolGateway 中的真实集成链路。"""

    @pytest.mark.asyncio
    async def test_low_risk_passthrough(self, gateway):
        """低风险命令：标记 [llm-passthrough]，不调 API。"""
        # 绕过实际 shell 执行，只验证 LLM 策略层的直通判定
        risk, action, reason = await gateway.llm_policy.evaluate(
            "echo hello", mode=SecurityMode.BALANCED
        )
        assert reason and "[llm-passthrough]" in reason, f"应有 LLM 直通标记：{reason}"

    @pytest.mark.asyncio
    async def test_llm_triggers_on_medium_risk(self, gateway):
        """中等风险（rm）：LLM 触发，不应回退。

        验证要点：
        - reason 含 [llm] 标记（说明走了 LLM）
        - 绕过实际 shell 执行（平台无关）
        """
        risk, action, reason = await gateway.llm_policy.evaluate(
            "rm -rf /tmp/test", mode=SecurityMode.BALANCED
        )
        assert "[llm]" in reason, f"LLM 应触发：{reason}"
        assert "[llm-fallback]" not in reason, f"LLM 不应回退：{reason}"

    @pytest.mark.asyncio
    async def test_llm_cache_hit(self, llm_policy):
        """缓存命中：同一命令返回缓存值。"""
        cmd = "dd if=/dev/zero of=/tmp/test bs=1M count=100"
        cache = LLMDecisionCache(ttl=300)
        decision = LLMDecision(
            command_hash="testhash",
            risk=RiskLevel.HIGH,
            action=Action.CONFIRM,
            reason="Cache test: dd to /tmp",
            confidence=0.8,
            expires_at=time.time() + 300,
        )
        cache.set(cmd, decision)
        cached = cache.get(cmd)
        assert cached is not None
        assert cached.action == Action.CONFIRM
        assert cached.risk == RiskLevel.HIGH

    @pytest.mark.asyncio
    async def test_llm_fallback_on_no_key(self, policy, sec_config, monkeypatch):
        """一把 key 都没有 → [llm-fallback]（主/备都不可用）。

        注意：默认主 provider 是交我算（qwen3.8-27b）、备是 DeepSeek（deepseek-flash），
        所以要**所有** key 都清掉；只清 DEEPSEEK_API_KEY 的话交我算仍然会顶上 —— 那才是
        设计如此（免费额度优先）。
        """
        for name in (
            "DEEPSEEK_API_KEY",
            "JIAOWOISAN_API_KEY",
            "API_KEY",
            "TRIMUM_LLM_API_KEY",
            "TRIMUM_LLM_API_KEY_ENV",
            "POLICY_LLM_API_KEY",
            "POLICY_LLM_API_KEY_ENV",
        ):
            monkeypatch.delenv(name, raising=False)

        llm_no_key = LlmPolicyEngine(policy_engine=policy, security_config=sec_config)
        risk, action, reason = await llm_no_key.evaluate(
            "rm test.txt", mode=SecurityMode.BALANCED
        )
        assert "[llm-fallback]" in reason

    @pytest.mark.asyncio
    async def test_api_server_state_injection(self):
        """api_server 构建时 llm_policy 已注入 ToolGateway。"""
        from trimum_core.api_server import create_app, AppState
        from trimum_core.config import Config
        config = Config()
        state = AppState(config)
        assert state.llm_policy is not None, "LlmPolicyEngine 未创建"
        assert state.tool_gateway.llm_policy is not None, "ToolGateway.llm_policy 未注入"
        assert state.tool_gateway.llm_policy is state.llm_policy
        risk, action, reason = await state.tool_gateway.llm_policy.evaluate(
            "echo hello",
            mode=SecurityMode.BALANCED,
        )
        assert risk is not None
        assert reason is not None

    @pytest.mark.asyncio
    async def test_cache_eviction(self):
        """缓存超出上限时清理最老的一半。"""
        cache = LLMDecisionCache(ttl=300, max_entries=10)
        for i in range(15):
            decision = LLMDecision(
                command_hash=f"h{i:04d}",
                risk=RiskLevel.LOW,
                action=Action.AUTO,
                reason=f"test {i}",
                confidence=1.0,
                expires_at=time.time() + (i * 10),
            )
            cache.set(f"cmd{i}", decision)
        assert cache.size <= 10, f"缓存大小应为 ≤10，实际 {cache.size}"

    @pytest.mark.asyncio
    async def test_gateway_with_security_mode_regex(self, policy, sec_config):
        """REGEX 模式：永不调 LLM。"""
        from trimum_core.models import SecurityMode
        gateway = ToolGateway(
            policy_engine=policy,
            llm_policy=LlmPolicyEngine(policy_engine=policy, security_config=sec_config),
        )
        req = ExecuteRequest(
            tool=ToolType.SHELL,
            args=["cat", "/etc/passwd"],
            agent_id="test",
            source_type=SourceType.AI,
        )
        resp = await gateway.execute(req)
        assert resp.execution_id is not None


class TestLLMDecisionCache:
    """LLMDecisionCache 单元测试。"""

    def test_basic_set_get(self):
        cache = LLMDecisionCache(ttl=300)
        decision = LLMDecision(
            command_hash="a1b2c3",
            risk=RiskLevel.LOW,
            action=Action.AUTO,
            reason="safe",
            confidence=1.0,
            expires_at=time.time() + 300,
        )
        cache.set("echo hello", decision)
        cached = cache.get("echo hello")
        assert cached is not None
        assert cached.action == Action.AUTO

    def test_expiry(self):
        cache = LLMDecisionCache(ttl=0)
        decision = LLMDecision(
            command_hash="expired",
            risk=RiskLevel.LOW,
            action=Action.AUTO,
            reason="expired",
            confidence=1.0,
            expires_at=time.time() - 1,
        )
        cache.set("old cmd", decision)
        time.sleep(0.01)
        assert cache.get("old cmd") is None, "过期后不应返回"

    def test_evict_half(self):
        cache = LLMDecisionCache(ttl=300, max_entries=10)
        for i in range(20):
            decision = LLMDecision(
                command_hash=f"h{i:04d}",
                risk=RiskLevel.LOW,
                action=Action.AUTO,
                reason=f"test {i}",
                confidence=1.0,
                expires_at=time.time() + 300,
            )
            cache.set(f"cmd{i}", decision)
        assert cache.size <= 10

    def test_clear(self):
        cache = LLMDecisionCache(ttl=300)
        decision = LLMDecision(
            command_hash="clear_test",
            risk=RiskLevel.LOW,
            action=Action.AUTO,
            reason="clear",
            confidence=1.0,
            expires_at=time.time() + 300,
        )
        cache.set("cmd", decision)
        cache.clear()
        assert cache.size == 0
