"""LlmPolicyEngine 接线测试（决策 15：越权判定走唯一闸门 ToolGateway）。

只验「三处自建网关 + 统一工厂」的接线，不真调 LLM、不碰真 ``~/.trimum``
（conftest 已把 TRIMUM_HOME / XDG_DATA_HOME 指到临时目录）。
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from trimum_core import llm_policy as llm_policy_mod
from trimum_core.event_bus import EventBus
from trimum_core.llm_policy import LlmPolicyEngine, build_default_llm_policy
from trimum_core.policy_engine import PolicyEngine


def test_build_default_llm_policy_ok():
    engine = build_default_llm_policy()
    assert isinstance(engine, LlmPolicyEngine)

    pe = PolicyEngine()
    engine2 = build_default_llm_policy(policy_engine=pe)
    assert isinstance(engine2, LlmPolicyEngine)
    assert engine2._pe is pe


def test_build_default_llm_policy_broken_security_config(monkeypatch):
    # security.yaml **永久**加载失败（load() 次次抛）⇒ 工厂仍不许抛、静默走默认。
    # 注意：不能只抛一次 —— LlmPolicyEngine.__init__ → get_llm_config() 会二次触发 load()，
    # 「只抛一次」会让用例假绿（掩盖真实缺陷）。
    def _boom(self):
        raise RuntimeError("security.yaml broken")

    monkeypatch.setattr(llm_policy_mod.SecurityConfig, "load", _boom)
    engine = build_default_llm_policy()  # 不许抛
    assert isinstance(engine, LlmPolicyEngine)
    # 坏配置下引擎仍可用：内部 config 有 dict 形状的 _raw，LLM 配置取到空 dict 而非抛
    assert isinstance(engine._sec_cfg._raw, dict)
    assert isinstance(engine._llm_config, dict)


def test_agent_loop_gateway_gets_llm_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    from trimum_core.agent_loop import AgentLoop

    loop = AgentLoop(agent_name="t-agent")
    assert loop.gateway.llm_policy is not None
    assert loop.gateway.llm_policy is loop.llm_policy

    fake_gateway = object()
    loop2 = AgentLoop(gateway=fake_gateway, agent_name="t-agent")
    assert loop2.gateway is fake_gateway  # 注入对象原样使用，一个字段都没改


def test_workflow_runtime_gateway_gets_llm_policy():
    from trimum_core.workflow_runtime import WorkflowRuntime

    runtime = WorkflowRuntime(EventBus())
    assert runtime._gateway is None
    gw = runtime._ensure_gateway()
    assert gw is not None
    assert gw.llm_policy is not None
    # 懒建缓存：连调两次拿到同一个实例
    assert runtime._ensure_gateway() is gw


def test_coding_agent_ensure_gateway_gets_llm_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    from trimum_core.coding_agent import CodingSession

    agent = CodingSession(task="t", cwd=str(tmp_path))
    assert agent.gateway is None

    agent._ensure_gateway()
    first = agent.gateway
    assert first is not None
    assert first.llm_policy is not None
    # 懒建语义：再调一次还是同一个 gateway
    agent._ensure_gateway()
    assert agent.gateway is first


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
