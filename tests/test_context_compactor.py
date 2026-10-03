"""ContextCompactor — Agent 上下文窗口管理测试（Phase 3 收尾 P0）。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.agent_loop import AgentLoop
from trimum_core.context_compactor import CompactionPolicy, ContextCompactor
from trimum_core.resource_controller import TokenUsage


def entry(name, command, status="ok", output="", error=""):
    return {
        "step": {"name": name, "command": command},
        "result": {"status": status, "output": output, "error": error},
    }


class TestTruncateOutput:
    def test_short_output_untouched(self):
        compactor = ContextCompactor()
        assert compactor.truncate_output("hello") == "hello"

    def test_long_output_keeps_head_and_tail(self):
        policy = CompactionPolicy(max_output_chars=100, output_head_chars=40, output_tail_chars=20)
        compactor = ContextCompactor(policy)
        raw = "A" * 40 + "B" * 500 + "C" * 20
        text = compactor.truncate_output(raw)

        assert text.startswith("A" * 40)
        assert text.endswith("C" * 20)
        assert "已省略" in text
        assert len(text) < len(raw)

    def test_non_string_output_is_stringified(self):
        compactor = ContextCompactor()
        assert compactor.truncate_output({"a": 1}) == "{'a': 1}"

    def test_none_output(self):
        assert ContextCompactor().truncate_output(None) == ""


class TestBuildContext:
    def test_empty_history(self):
        assert ContextCompactor().build([]) == ""

    def test_recent_steps_rendered_verbatim(self):
        compactor = ContextCompactor()
        context = compactor.build([entry("列目录", "ls -la", output="a\nb")])

        assert "最近步骤" in context
        assert "ls -la" in context
        assert "a\nb" in context

    def test_older_steps_become_summaries(self):
        policy = CompactionPolicy(recent_steps=2)
        compactor = ContextCompactor(policy)
        history = [
            entry("第一步", "echo one", output="one"),
            entry("第二步", "echo two", output="two"),
            entry("第三步", "echo three", output="three"),
            entry("第四步", "echo four", output="four"),
        ]
        context = compactor.build(history)

        assert "早期步骤摘要" in context
        assert "- 第一步: echo one → ok" in context
        # 被摘要的步骤不再输出正文块
        assert "步骤: 第一步" not in context
        assert "步骤: 第三步" in context

    def test_summary_is_single_line_and_bounded(self):
        policy = CompactionPolicy(recent_steps=0, max_summary_chars=50)
        compactor = ContextCompactor(policy)
        long_line = "x" * 5000
        context = compactor.build([entry("大步骤", "cat big.log", output=long_line)])

        assert len(context) <= policy.max_context_chars
        assert "x" * 5000 not in context

    def test_context_stays_within_budget(self):
        policy = CompactionPolicy()
        compactor = ContextCompactor(policy)
        history = [
            entry(f"步骤{i}", f"echo {i}", output="y" * 10000)
            for i in range(40)
        ]
        context = compactor.build(history)

        assert len(context) <= policy.max_context_chars
        assert "早期步骤摘要" in context
        # 最新一步必须保留
        assert "echo 39" in context
        # 最老的步骤已被预算挤掉
        assert "echo 0 " not in context

    def test_output_limits_applied_within_recent_steps(self):
        policy = CompactionPolicy()
        compactor = ContextCompactor(policy)
        context = compactor.build([entry("日志", "cat app.log", output="z" * 50000)])

        assert "已省略" in context
        assert len(context) <= policy.max_context_chars

    def test_error_text_used_when_no_output(self):
        compactor = ContextCompactor()
        context = compactor.build([entry("失败步骤", "false", status="error", error="boom")])
        assert "boom" in context


class TestAgentLoopIntegration:
    @pytest.mark.asyncio
    async def test_plan_single_step_sends_bounded_context(self, monkeypatch):
        loop = AgentLoop(agent_name="test-agent")
        captured = {}

        async def fake_chat(**kwargs):
            captured["messages"] = kwargs["messages"]
            return '{"name":"x","command":"echo hi","risk":"low"}', TokenUsage()

        monkeypatch.setattr(loop, "_chat_completion", fake_chat)

        history = [entry(f"步骤{i}", f"echo {i}", output="z" * 10000) for i in range(30)]
        await loop._plan_single_step("做个任务", context=history)

        payload = captured["messages"][-1]["content"]
        assert "执行历史" in payload
        assert len(payload) < 4000
        assert "早期步骤摘要" in payload

    @pytest.mark.asyncio
    async def test_plan_single_step_without_context(self, monkeypatch):
        loop = AgentLoop(agent_name="test-agent")
        captured = {}

        async def fake_chat(**kwargs):
            captured["messages"] = kwargs["messages"]
            return '{"name":"x","command":"echo hi","risk":"low"}', TokenUsage()

        monkeypatch.setattr(loop, "_chat_completion", fake_chat)
        await loop._plan_single_step("做个任务", context=None)

        assert len(captured["messages"]) == 2