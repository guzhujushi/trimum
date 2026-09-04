"""Transform Agent 稳定性测试。

测试策略：
- 单元测试不调真实 LLM：mock urllib.request.urlopen
- 覆盖 LLM 输出的各种解析路径（SHELL:/TARL:/未知格式）
- 覆盖 confidence 解析
- 覆盖错误处理（HTTP error / 网络异常 / 空响应）
- 边界 case：空输入、超长、特殊符号、多意图
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from trimum_core.transform_agent import TransformAgent, TransformResult


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_response(content: str, status: int = 200) -> MagicMock:
    """创建一个模拟的 urllib.response."""
    resp = MagicMock()
    body = json.dumps({
        "choices": [{"message": {"content": content}}]
    }).encode("utf-8")
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    # urllib.request.urlopen 返回的 context manager 要 yield resp
    return resp


def _make_mock_http_error(code: int = 500) -> Exception:
    """模拟 HTTPError."""
    from urllib.error import HTTPError
    # HTTPError 构造函数需要 response 对象
    mock_resp = MagicMock()
    mock_resp.status = code
    # 用最简构造，我们只关心 catch
    return HTTPError(
        url="http://test", code=code, msg="Error",
        hdrs={}, fp=None,
    )


def _make_mock_timeout() -> Exception:
    """模拟超时。"""
    from urllib.error import URLError
    return URLError("timed out")


@pytest.fixture
def agent() -> TransformAgent:
    """创建一个不依赖真实环境变量的 TransformAgent. """
    return TransformAgent(
        model="test-model",
        base_url="http://test.local",
        api_key="test-key",
    )


@pytest.fixture
def agent_no_key() -> TransformAgent:
    """空 api_key 测试。"""
    return TransformAgent(
        model="test-model",
        base_url="http://test.local",
        api_key="",
    )


# ── 测试: TransformResult 属性 ──────────────────────────────────────────────


class TestTransformResult:
    """TransformResult 的状态判断逻辑。"""

    def test_shell_result(self):
        r = TransformResult(
            shell_command="ls -la",
            tarl="cmd:ls origin:ai",
            confidence=0.9,
            original="列出文件",
            output_type="shell",
        )
        assert r.is_shell is True
        assert r.is_tarl is False
        assert r.is_certain is True
        assert r.needs_confirmation is False
        assert r.needs_planner is False

    def test_tarl_result(self):
        r = TransformResult(
            tarl="cmd:deploy_blog origin:ai",
            confidence=0.75,
            original="部署博客",
            output_type="tarl",
        )
        assert r.is_shell is False
        assert r.is_tarl is True
        assert r.is_certain is True

    def test_low_confidence_needs_planner(self):
        r = TransformResult(
            tarl="cmd:unknown origin:ai",
            confidence=0.2,
            original="???",
            output_type="tarl",
        )
        assert r.needs_planner is True
        assert r.is_certain is False
        assert r.needs_confirmation is False

    def test_medium_confidence_needs_confirmation(self):
        r = TransformResult(
            tarl="cmd:maybe origin:ai",
            confidence=0.5,
            original="不太确定",
            output_type="tarl",
        )
        assert r.needs_confirmation is True
        assert r.is_certain is False
        assert r.needs_planner is False

    def test_boundary_confirmation(self):
        """边界值测试：0.4 和 0.7 的归属。"""
        # 0.4 应为 needs_confirmation（左闭）
        r1 = TransformResult(tarl="cmd:x", confidence=0.4, original="x")
        assert r1.needs_confirmation is True
        assert r1.needs_planner is False

        # 0.7 应为 is_certain（右闭）
        r2 = TransformResult(tarl="cmd:x", confidence=0.7, original="x")
        assert r2.is_certain is True
        assert r2.needs_confirmation is False

    def test_to_dict(self):
        r = TransformResult(
            shell_command="df -h",
            tarl="cmd:df origin:ai",
            confidence=0.9,
            original="磁盘",
            output_type="shell",
        )
        d = r.to_dict()
        assert d["shell_command"] == "df -h"
        assert d["confidence"] == 0.9
        assert d["error"] is None

    def test_repr_shell(self):
        r = TransformResult(
            shell_command="ls", tarl="cmd:ls", confidence=0.9, original="ls",
            output_type="shell",
        )
        assert "shell=" in repr(r)

    def test_repr_tarl(self):
        r = TransformResult(
            tarl="cmd:deploy", confidence=0.6, original="deploy",
            output_type="tarl",
        )
        assert "tarl=" in repr(r)


# ── 测试: LLM 输出解析 (核心) ──────────────────────────────────────────────


class TestParseLlmOutput:
    """不调用 LLM，直接测 _parse_llm_output 的解析逻辑。"""

    def test_shell_output(self, agent):
        """标准 SHELL: 输出。"""
        result = agent._parse_llm_output(
            "SHELL:ls -la\nCONFIDENCE:0.95",
            "列出文件",
        )
        assert result.is_shell is True
        assert result.shell_command == "ls -la"
        assert result.confidence == 0.95
        assert result.original == "列出文件"
        assert "origin:ai" in result.tarl

    def test_shell_with_complex_command(self, agent):
        """含管道/特殊字符的命令。"""
        result = agent._parse_llm_output(
            "SHELL:ps aux | grep python | awk '{print $2}'\nCONFIDENCE:0.9",
            "查看 python 进程",
        )
        assert result.is_shell is True
        assert result.shell_command == "ps aux | grep python | awk '{print $2}'"
        assert result.confidence == 0.9

    def test_tarl_output(self, agent):
        """标准 TARL: 输出。"""
        result = agent._parse_llm_output(
            "TARL:cmd:deploy_blog target:production\nCONFIDENCE:0.85",
            "部署博客",
        )
        assert result.is_tarl is True
        assert "cmd:deploy_blog" in result.tarl
        assert "origin:ai" in result.tarl
        assert result.confidence == 0.85

    def test_tarl_without_origin(self, agent):
        """TARL 中无 origin 标签 → 自动追加。"""
        result = agent._parse_llm_output(
            "TARL:cmd:test_task\nCONFIDENCE:0.9",
            "测试任务",
        )
        assert "origin:ai" in result.tarl

    def test_tarl_with_existing_origin(self, agent):
        """TARL 中已有 origin 标签 → 不重复追加。"""
        result = agent._parse_llm_output(
            "TARL:cmd:test_task origin:human\nCONFIDENCE:0.9",
            "测试任务",
        )
        # origin:human 保留，不应再追加 origin:ai
        assert "origin:human" in result.tarl
        assert result.tarl.count("origin:") == 1

    def test_unrecognized_output(self, agent):
        """未知格式 → fallback TARL + 低 confidence。"""
        result = agent._parse_llm_output(
            "I don't know what you mean.",
            "随便说点什么",
        )
        assert result.is_tarl is True
        assert result.confidence < 0.5
        assert result.error is not None
        assert "Unrecognized" in result.error

    def test_no_confidence_line(self, agent):
        """没有 CONFIDENCE 行 → 使用默认值 0.8。"""
        result = agent._parse_llm_output(
            "SHELL:pwd",
            "当前目录",
        )
        assert result.confidence == 0.8

    def test_invalid_confidence(self, agent):
        """CONFIDENCE: 值不是数字 → 忽略。"""
        result = agent._parse_llm_output(
            "SHELL:pwd\nCONFIDENCE:abc",
            "当前目录",
        )
        # 解析失败用默认 0.8
        assert result.confidence == 0.8

    def test_empty_content(self, agent):
        """空 LLM 输出 → fallback TARL。"""
        result = agent._parse_llm_output("", "空指令")
        assert result.is_tarl is True
        assert result.confidence < 0.5

    def test_whitespace_only(self, agent):
        """只有空白字符的 LLM 输出。"""
        result = agent._parse_llm_output("   \n  \n  ", "空白输出")
        assert result.is_tarl is True
        assert result.confidence < 0.5

    def test_tarl_with_spaces_in_value(self, agent):
        """TARL 值包含空格 → 原样保留（parse 不做校验，由 LLM 保证）。"""
        result = agent._parse_llm_output(
            "TARL:cmd:test_task\nCONFIDENCE:0.8",
            "测试",
        )
        assert result.tarl == "cmd:test_task origin:ai"


# ── 测试: _call_llm (mock HTTP) ────────────────────────────────────────────


class TestCallLlm:
    """mock urllib.request.urlopen 测试 LLM 调用。"""

    @patch("urllib.request.urlopen")
    def test_successful_shell(self, mock_urlopen, agent):
        """LLM 返回 SHELL 命令。"""
        mock_urlopen.return_value = _make_mock_response(
            "SHELL:free -h\nCONFIDENCE:0.95"
        )
        result = agent._call_llm("查看内存")
        assert result.is_shell is True
        assert result.shell_command == "free -h"
        assert result.confidence == 0.95

    @patch("urllib.request.urlopen")
    def test_successful_tarl(self, mock_urlopen, agent):
        """LLM 返回 TARL。"""
        mock_urlopen.return_value = _make_mock_response(
            "TARL:cmd:create_website lang:python\nCONFIDENCE:0.8"
        )
        result = agent._call_llm("创建网站")
        assert result.is_tarl is True
        assert "cmd:create_website" in result.tarl

    @patch("urllib.request.urlopen")
    def test_empty_choices(self, mock_urlopen, agent):
        """LLM 返回空 choices → fallback。"""
        resp = MagicMock()
        body = json.dumps({"choices": []}).encode("utf-8")
        resp.read.return_value = body
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        result = agent._call_llm("随便")
        assert result.confidence < 0.5
        assert result.error is not None

    @patch("urllib.request.urlopen")
    def test_http_500(self, mock_urlopen, agent):
        """HTTP 500 → fallback + 低 confidence。"""
        mock_urlopen.side_effect = _make_mock_http_error(500)
        result = agent._call_llm("啥")
        assert result.confidence <= 0.2
        assert result.error is not None
        assert "HTTP" in result.error

    @patch("urllib.request.urlopen")
    def test_http_429_rate_limit(self, mock_urlopen, agent):
        """Rate limit (429) → fallback。"""
        mock_urlopen.side_effect = _make_mock_http_error(429)
        result = agent._call_llm("快点")
        assert result.confidence <= 0.2
        assert "429" in result.error

    @patch("urllib.request.urlopen")
    def test_network_timeout(self, mock_urlopen, agent):
        """网络超时 → fallback。"""
        mock_urlopen.side_effect = _make_mock_timeout()
        result = agent._call_llm("慢死了")
        assert result.confidence <= 0.1
        assert result.error is not None

    @patch("urllib.request.urlopen")
    def test_request_contains_correct_payload(self, mock_urlopen, agent):
        """验证请求体内容。"""
        mock_urlopen.return_value = _make_mock_response(
            "SHELL:pwd\nCONFIDENCE:0.9"
        )
        agent._call_llm("测试 payload")

        call_args = mock_urlopen.call_args
        assert call_args is not None
        req = call_args[0][0]
        # 检查请求属性
        assert req.method == "POST"
        assert req.full_url == "http://test.local/chat/completions"
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "test-model"
        assert body["temperature"] == 0.0
        assert body["max_tokens"] == 1024
        assert body["messages"][1]["content"] == "测试 payload"
        # 确认 api_key 在 header
        assert req.headers["Authorization"] == "Bearer test-key"


# ── 测试: 边界 Case ────────────────────────────────────────────────────────


class TestEdgeCases:
    """边界和异常输入测试。"""

    def test_empty_shell_command_fallback(self, agent):
        """SHELL: 后为空命令 → 按 unrecognized 处理为 fallback TARL。"""
        result = agent._parse_llm_output(
            "SHELL:\nCONFIDENCE:0.9", "空命令"
        )
        # SHELL: 后为空 → unrecognized → fallback TARL
        assert result.is_tarl is True
        assert result.confidence < 0.5

    def test_long_instruction(self, agent):
        """超长指令（模拟解析逻辑，不调 LLM）。"""
        long_text = "a" * 10000
        result = agent._parse_llm_output(
            "TARL:cmd:long_input\nCONFIDENCE:0.5",
            long_text,
        )
        assert result.original == long_text
        assert result.is_tarl is True

    def test_special_characters(self, agent):
        """特殊符号：中日韩文混排、emoji、标点。"""
        mixed = "查看磁盘 /mnt/data 还剩多少空间？⚠️ 快满了！df -h"
        result = agent._parse_llm_output(
            "SHELL:df -h\nCONFIDENCE:0.95",
            mixed,
        )
        assert result.is_shell is True
        assert result.original == mixed

    @patch("urllib.request.urlopen")
    def test_multi_intent_input(self, mock_urlopen, agent):
        """多意图输入：含 SHELL 和 TARL 两种意图。"""
        mock_urlopen.return_value = _make_mock_response(
            "TARL:cmd:complex_workflow\nCONFIDENCE:0.6"
        )
        # 复杂输入：既有命令又有工作流意图
        result = agent._call_llm(
            "先看看磁盘，然后部署博客，再检查一下 nginx 状态"
        )
        # 当前只输出一个，所以应该是 TARL（因为复杂）
        assert result.is_tarl is True
        assert result.confidence == 0.6

    def test_newlines_in_output(self, agent):
        """LLM 输出包含多余空行。"""
        result = agent._parse_llm_output(
            "\n\nSHELL:docker ps\n\nCONFIDENCE:0.88\n\n",
            "看看容器",
        )
        assert result.is_shell is True
        assert result.shell_command == "docker ps"

    def test_mixed_case_prefix(self, agent):
        """前缀大小写：SHELL: vs shell:。"""
        result = agent._parse_llm_output(
            "shell:ls\nCONFIDENCE:0.9",
            "小写 shell",
        )
        # 当前代码只认大写 SHELL:，小写不识别 → fallback
{}