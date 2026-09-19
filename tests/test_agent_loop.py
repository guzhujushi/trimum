"""AgentLoop Phase C wiring tests — token accounting and SSE parsing."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.agent_loop import AgentLoop
from trimum_core.resource_controller import TokenUsage


def test_token_usage_from_payload():
    usage = AgentLoop._token_usage_from_payload({
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 7,
            "total_tokens": 19,
        },
    })
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 19
    assert usage.calls == 1


def test_token_usage_from_payload_missing_total():
    usage = AgentLoop._token_usage_from_payload({
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 4,
        },
    })
    assert usage.total_tokens == 7


def test_parse_sse_line_data():
    assert AgentLoop._parse_sse_line('data: {"choices":[{"delta":{"content":"hi"}}]}') == {
        "choices": [{"delta": {"content": "hi"}}],
    }


def test_parse_sse_line_done():
    assert AgentLoop._parse_sse_line("data: [DONE]") is None


@pytest.mark.asyncio
async def test_plan_records_token_usage(monkeypatch):
    loop = AgentLoop(agent_name="test-agent")

    async def fake_chat(**kwargs):
        return (
            '{"title":"t","steps":[{"name":"x","command":"echo hi","risk":"low"}]}',
            TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15, calls=1),
        )

    monkeypatch.setattr(loop, "_chat_completion", fake_chat)
    plan = await loop._plan("echo hi")

    assert plan["title"] == "t"
    usage = loop.get_token_usage()
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15
    assert usage.calls == 1
