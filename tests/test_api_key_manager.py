"""API key 真源（Q4）：``llm_router`` 是唯一 key 清单管理员。

四个调用点（planner / transform / experience）改走 ``resolve_env_api_key``，
两个 CLI（doctor / health）的 key 清单改从 ``known_api_key_envs()`` 取。

用例全部用 ``monkeypatch`` 控 env，不发网络、不读真机 ``~/.trimum``。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import llm_router  # noqa: E402


def test_known_api_key_envs_is_complete_deduped_source():
    names = llm_router.known_api_key_envs()
    assert isinstance(names, tuple)
    for expected in (
        "TRIMUM_LLM_API_KEY",
        "PLANNER_LLM_API_KEY",
        "TRANSFORM_LLM_API_KEY",
        "EXPERIENCE_LLM_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "API_KEY",
    ):
        assert expected in names
    assert len(names) == len(set(names))


def test_describe_api_keys_only_bool_never_echoes_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-super-secret-123456")
    described = llm_router.describe_api_keys()
    assert described["GROQ_API_KEY"]["present"] is True
    assert "sk-super-secret-123456" not in json.dumps(described)

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert llm_router.describe_api_keys()["GROQ_API_KEY"]["present"] is False


def test_role_beats_global(monkeypatch):
    monkeypatch.delenv("PLANNER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("PLANNER_LLM_FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("PLANNER_LLM_FALLBACK", raising=False)
    monkeypatch.setenv("TRIMUM_LLM_API_KEY", "global")
    assert llm_router.resolve_env_api_key(llm_router.ROLE_PLANNER) == "global"

    monkeypatch.setenv("PLANNER_LLM_API_KEY", "role")
    assert llm_router.resolve_env_api_key(llm_router.ROLE_PLANNER) == "role"


def test_transform_uses_resolver(monkeypatch):
    monkeypatch.setattr(
        llm_router, "resolve_env_api_key", lambda *a, **k: "SENTINEL-T"
    )
    from trimum_core.transform_agent import TransformAgent

    agent = TransformAgent()
    assert agent._api_key == "SENTINEL-T"


def test_planner_uses_resolver(monkeypatch, tmp_path):
    monkeypatch.setattr(
        llm_router, "resolve_env_api_key", lambda *a, **k: "SENTINEL-P"
    )
    from trimum_core.event_bus import EventBus
    from trimum_core.planner_agent import PlannerAgent

    planner = PlannerAgent(EventBus(), workflow_dir=tmp_path / "wf")
    assert planner._llm_kwargs["api_key"] == "SENTINEL-P"


def test_cli_key_lists_come_from_single_source():
    from trimum_core.cli.commands import doctor as doctor_mod
    from trimum_core.cli.commands import health as health_mod

    truth = llm_router.known_api_key_envs()
    assert tuple(health_mod._ENV_KEYS) == truth
    assert tuple(doctor_mod._ENV_KEYS) == truth
