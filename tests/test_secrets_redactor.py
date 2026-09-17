"""Tests for SecretsRedactor — 凭据脱敏模块。"""

from __future__ import annotations

import pytest

from trimum_core.secrets_redactor import (
    SecretsRedactor,
    redact_text,
    redact_obj,
)


class TestSecretsRedactor:
    """SecretsRedactor 基础功能测试。"""

    def test_redact_api_key_value(self):
        """应脱敏 api_key=sk-xxx 形式。"""
        r = SecretsRedactor()
        result = r.redact("OPENAI_API_KEY=sk-abc123def456ghi789jkl")
        assert "sk-abc123def456ghi789jkl" not in result
        assert "***REDACTED***" in result

    def test_redact_password_value(self):
        """应脱敏 password=xxx 形式。"""
        r = SecretsRedactor()
        result = r.redact("db_password=hunter2secret!")
        assert "hunter2secret!" not in result
        assert "***REDACTED***" in result

    def test_redact_bearer_token(self):
        """应脱敏 Authorization: Bearer xxx。"""
        r = SecretsRedactor()
        result = r.redact(
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )
        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "***REDACTED***" in result

    def test_redact_private_key(self):
        """应脱敏 PEM 私钥块。"""
        r = SecretsRedactor()
        private_key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = r.redact(private_key)
        assert "MIIEowIBAAKCAQEA" not in result
        assert "***REDACTED***" in result

    def test_redact_aws_key(self):
        """应脱敏 AWS Access Key ID。"""
        r = SecretsRedactor()
        result = r.redact("aws_access_key_id=AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "***REDACTED***" in result

    def test_redact_connection_string(self):
        """应脱敏 URL 中的凭据（mysql://user:pass@host）。"""
        r = SecretsRedactor()
        result = r.redact("mysql://admin:secretpass123@db.example.com:3306/mydb")
        assert "secretpass123" not in result
        assert "***REDACTED***" in result

    def test_normal_text_unchanged(self):
        """普通文本不应被修改。"""
        r = SecretsRedactor()
        text = "hello world, this is a normal log message"
        assert r.redact(text) == text

    def test_empty_input(self):
        """空字符串应安全返回。"""
        r = SecretsRedactor()
        assert r.redact("") == ""
        assert r.redact(None) is None

    def test_dict_redaction(self):
        """字典中的敏感值应被脱敏。"""
        r = SecretsRedactor()
        data = {
            "api_key": "sk-abc123",
            "user": "admin",
            "config": {"token": "tok_xyz789"},
            "list": ["password=hunter2", "normal"],
        }
        result = r.redact_dict(data)

        assert result["api_key"] == "***REDACTED***"
        assert result["user"] == "admin"
        assert result["config"]["token"] == "***REDACTED***"
        assert "hunter2" not in str(result["list"][0])

    def test_redact_obj_nested(self):
        """通用入口应处理嵌套结构。"""
        result = redact_obj(
            {
                "secret": "sk-test-secret",
                "name": "test",
                "nested": [{"password": "pw_12345"}, "regular"],
            }
        )

        assert result["secret"] == "***REDACTED***"
        assert result["nested"][0]["password"] == "***REDACTED***"
        assert result["nested"][1] == "regular"


class TestRedactTextFunction:
    """便捷函数 redact_text 测试。"""

    def test_redact_text_basic(self):
        assert "sk-1234567890abcdef" not in redact_text("api_key=sk-1234567890abcdef")

    def test_redact_text_preserves_normal(self):
        assert redact_text("Normal log line") == "Normal log line"
