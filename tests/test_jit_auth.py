"""Tests for JIT（Just-In-Time）一次性授权机制.

覆盖：
1. 令牌颁发与消费（一次性）
2. 过期检查
3. agent/tool/command 匹配检查
4. 完整授权流程（issue → verify → consume）
"""

from __future__ import annotations

import time

import pytest

from trimum_core.models import (
    Action,
    ExecuteRequest,
    JITToken,
    RiskLevel,
    ToolType,
)
from trimum_core.tool_gateway import ToolGateway


class TestJITToken:
    """JITToken 模型测试。"""

    def test_create_token(self):
        token = JITToken(
            token="abc123",
            agent_id="agent-01",
            tool="shell",
            command="rm -rf /tmp/foo",
            expires_at=time.time() + 300,
            granted_by="admin",
            used=False,
        )
        assert token.token == "abc123"
        assert token.agent_id == "agent-01"
        assert token.tool == "shell"
        assert not token.used

    def test_token_expired(self):
        token = JITToken(
            token="abc123",
            agent_id="agent-01",
            tool="shell",
            command="rm -rf /tmp/foo",
            expires_at=time.time() - 100,  # 已过期
            granted_by="admin",
            used=False,
        )
        assert time.time() > token.expires_at


class TestToolGatewayJIT:
    """ToolGateway JIT 授权流程测试。"""

    def setup_method(self):
        """为每个测试创建干净的 gateway 实例。"""
        self.gw = ToolGateway()
        # 确保令牌表存在
        self.gw._jit_tokens = {}

    def test_issue_token_creates_valid_entries(self):
        """颁发令牌后应存在于令牌表中。"""
        token = self.gw.issue_jit_token(
            agent_id="agent-01",
            tool=ToolType.SHELL,
            command="sudo systemctl restart nginx",
            granted_by="admin",
            ttl=300,
        )
        assert token.token in self.gw._jit_tokens
        stored = self.gw._jit_tokens[token.token]
        assert stored.agent_id == "agent-01"
        assert stored.tool == "shell"
        assert stored.granted_by == "admin"
        assert not stored.used

    def test_token_is_one_time(self):
        """令牌应是一次性的，使用后不能再次使用。"""
        token = self.gw.issue_jit_token(
            agent_id="agent-01",
            tool=ToolType.SHELL,
            command="sudo rm -rf /tmp/testdir",
            granted_by="admin",
            ttl=300,
        )

        # 第一次验证应该通过
        first = self.gw._verify_jit_token(
            token_str=token.token,
            agent_id="agent-01",
            tool_name="shell",
            command="sudo rm -rf /tmp/testdir",
        )
        assert first is None  # 验证通过

        # 令牌应被标记为已使用
        stored = self.gw._jit_tokens[token.token]
        assert stored.used

        # 第二次验证应该失败（已消费）
        second = self.gw._verify_jit_token(
            token_str=token.token,
            agent_id="agent-01",
            tool_name="shell",
            command="sudo rm -rf /tmp/testdir",
        )
        assert second is not None
        assert "used" in second or "consumed" in second

    def test_expired_token_rejected(self):
        """过期令牌应被拒绝。"""
        token = self.gw.issue_jit_token(
            agent_id="agent-01",
            tool=ToolType.SHELL,
            command="sudo ls /",
            granted_by="admin",
            ttl=0.01,  # 极短有效期
        )

        # 手动把令牌改成已过期
        token.expires_at = time.time() - 1
        self.gw._jit_tokens[token.token] = token

        result = self.gw._verify_jit_token(
            token_str=token.token,
            agent_id="agent-01",
            tool_name="shell",
            command="sudo ls /",
        )
        assert result is not None
        assert "expired" in result

    def test_agent_mismatch_rejected(self):
        """绑定 agent 不匹配应被拒绝。"""
        token = self.gw.issue_jit_token(
            agent_id="agent-01",
            tool=ToolType.SHELL,
            command="sudo ls /",
            granted_by="admin",
            ttl=300,
        )

        result = self.gw._verify_jit_token(
            token_str=token.token,
            agent_id="agent-02",  # 不匹配
            tool_name="shell",
            command="sudo ls /",
        )
        assert result is not None
        assert "agent" in result

    def test_tool_mismatch_rejected(self):
        """绑定 tool 不匹配应被拒绝。"""
        token = self.gw.issue_jit_token(
            agent_id="agent-01",
            tool=ToolType.SHELL,
            command="sudo ls /",
            granted_by="admin",
            ttl=300,
        )

        result = self.gw._verify_jit_token(
            token_str=token.token,
            agent_id="agent-01",
            tool_name="file.write",  # 不匹配
            command="sudo ls /",
        )
        assert result is not None
        assert "tool" in result

    def test_unknown_token_rejected(self):
        """未知令牌应被拒绝。"""
        result = self.gw._verify_jit_token(
            token_str="nonexistent-token",
            agent_id="agent-01",
            tool_name="shell",
            command="sudo ls /",
        )
        assert result is not None
        assert "not found" in result

    def test_full_flow_issue_verify_consume(self):
        """完整流程：颁发→验证→消费→再次验证失败。"""
        token = self.gw.issue_jit_token(
            agent_id="agent-01",
            tool=ToolType.SHELL,
            command="sudo systemctl status sshd",
            granted_by="admin",
            ttl=300,
        )

        # 第一次验证
        r1 = self.gw._verify_jit_token(
            token_str=token.token,
            agent_id="agent-01",
            tool_name="shell",
            command="sudo systemctl status sshd",
        )
        assert r1 is None

        # 再次验证（已消费）
        r2 = self.gw._verify_jit_token(
            token_str=token.token,
            agent_id="agent-01",
            tool_name="shell",
            command="sudo systemctl status sshd",
        )
        assert r2 is not None
