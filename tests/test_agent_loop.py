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

# ── image / multimodal helpers ──


def test_image_to_data_url_valid(tmp_path):
    from trimum_core.agent_loop import _image_to_data_url

    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    url = _image_to_data_url(str(img))
    assert url.startswith("data:image/png;base64,")


def test_image_to_data_url_missing():
    import pytest
    from trimum_core.agent_loop import _image_to_data_url

    with pytest.raises(FileNotFoundError):
        _image_to_data_url("/nonexistent/image.png")


def test_image_to_data_url_unsupported_format(tmp_path):
    import pytest
    from trimum_core.agent_loop import _image_to_data_url

    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    with pytest.raises(ValueError, match="unsupported image format"):
        _image_to_data_url(str(txt))


def test_build_user_content_no_images():
    from trimum_core.agent_loop import _build_user_content

    result = _build_user_content("hello")
    assert result == "hello"


def test_build_user_content_with_images(tmp_path):
    from trimum_core.agent_loop import _build_user_content

    img1 = tmp_path / "a.png"
    img1.write_bytes(b"\x89PNG\r\n\x1a\n")
    img2 = tmp_path / "b.jpg"
    img2.write_bytes(b"\xff\xd8\xff")

    result = _build_user_content("describe", [str(img1), str(img2)])
    assert isinstance(result, list)
    assert result[0] == {"type": "text", "text": "describe"}
    assert result[1]["type"] == "image_url"
    assert result[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result[2]["type"] == "image_url"
    assert result[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_build_user_content_empty_list():
    from trimum_core.agent_loop import _build_user_content

    result = _build_user_content("hello", [])
    assert result == "hello"