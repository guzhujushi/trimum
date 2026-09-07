"""Tests for TRM error code system: TRMErrorCode enum and TrimumError exception."""

import pytest
from trimum_core.models import TRMErrorCode, TrimumError


class TestTRMErrorCode:
    """Verify TRMErrorCode enum values, properties, and invariants."""

    def test_format_all_codes(self):
        """Every code must match TRM-NNNN format."""
        for code in TRMErrorCode:
            value = code.value
            assert value.startswith("TRM-"), f"{value} does not start with TRM-"
            suffix = value[4:]
            assert suffix.isdigit() and len(suffix) == 4, f"{value} suffix not 4 digits"

    def test_category_map(self):
        """Category is correct for each range."""
        expected = {
            "TRM-1": "runtime",
            "TRM-2": "security",
            "TRM-3": "agent",
            "TRM-4": "tool",
            "TRM-5": "workflow",
            "TRM-6": "memory",
            "TRM-7": "network",
            "TRM-8": "config",
            "TRM-9": "internal",
        }
        for code in TRMErrorCode:
            prefix = code.value[:5]  # "TRM-1"
            assert code.category == expected.get(prefix, "unknown"), (
                f"{code.value}: expected category {expected.get(prefix)}, got {code.category}"
            )

    def test_no_duplicate_values(self):
        """No two enum members share the same value string."""
        values = [c.value for c in TRMErrorCode]
        assert len(values) == len(set(values)), "Duplicate TRMErrorCode values found"

    def test_http_status_range(self):
        """http_status returns a valid HTTP status code."""
        for code in TRMErrorCode:
            status = code.http_status
            assert 200 <= status <= 599, f"{code.value}: http_status={status} out of range"

    def test_log_level_valid(self):
        """log_level returns one of the standard logging levels."""
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        for code in TRMErrorCode:
            assert code.log_level.upper() in valid, (
                f"{code.value}: log_level={code.log_level} not in {valid}"
            )

    def test_specific_codes(self):
        """Spot-check specific error codes."""
        assert TRMErrorCode.AGENT_NOT_FOUND.value == "TRM-3001"
        assert TRMErrorCode.TOOL_EXECUTION_FAILED.value == "TRM-4002"
        assert TRMErrorCode.POLICY_DENIED.value == "TRM-2001"
        assert TRMErrorCode.NOT_IMPLEMENTED.value == "TRM-9003"

    def test_specific_http_status(self):
        """Spot-check HTTP status mappings."""
        assert TRMErrorCode.JIT_TOKEN_EXPIRED.http_status == 401
        assert TRMErrorCode.POLICY_DENIED.http_status == 403
        assert TRMErrorCode.AGENT_NOT_FOUND.http_status == 404
        assert TRMErrorCode.AGENT_ALREADY_EXISTS.http_status == 409
        assert TRMErrorCode.WORKFLOW_PARSE_ERROR.http_status == 422
        assert TRMErrorCode.HTTP_TIMEOUT.http_status == 504
        assert TRMErrorCode.RUNTIME_INIT_FAILED.http_status == 500

    def test_specific_log_level(self):
        """Spot-check log level mappings."""
        assert TRMErrorCode.AGENT_KILLED.log_level == "CRITICAL"
        assert TRMErrorCode.UNREACHABLE_CODE.log_level == "CRITICAL"
        assert TRMErrorCode.POLICY_DENIED.log_level == "WARNING"
        assert TRMErrorCode.AGENT_NOT_FOUND.log_level == "ERROR"

    def test_total_count(self):
        """Total number of defined error codes."""
        assert len(TRMErrorCode) == 65, (
            f"Expected 65 error codes, got {len(TRMErrorCode)}. "
            "Update this test if you added/removed codes."
        )


class TestTrimumError:
    """Verify TrimumError exception class."""

    def test_create_with_code_only(self):
        """TrimumError can be created with just an error code."""
        err = TrimumError(TRMErrorCode.AGENT_NOT_FOUND)
        assert err.code == TRMErrorCode.AGENT_NOT_FOUND
        assert err.message == "Agent with given ID not found"
        assert err.context == {}
        assert str(err) == "[TRM-3001] Agent with given ID not found"

    def test_create_with_custom_message(self):
        """TrimumError accepts a custom message."""
        err = TrimumError(TRMErrorCode.AGENT_NOT_FOUND, message="Custom: agent 'x' not found")
        assert err.message == "Custom: agent 'x' not found"
        assert str(err) == "[TRM-3001] Custom: agent 'x' not found"

    def test_create_with_context(self):
        """TrimumError accepts a context dict."""
        err = TrimumError(
            TRMErrorCode.TOOL_EXECUTION_FAILED,
            message="git push failed",
            context={"exit_code": 128, "tool": "git"},
        )
        assert err.context["exit_code"] == 128
        assert err.context["tool"] == "git"

    def test_category_property(self):
        """category property delegates to code.category."""
        err = TrimumError(TRMErrorCode.POLICY_DENIED)
        assert err.category == "security"

    def test_http_status_property(self):
        """http_status property delegates to code.http_status."""
        err = TrimumError(TRMErrorCode.AGENT_NOT_FOUND)
        assert err.http_status == 404

    def test_log_level_property(self):
        """log_level property delegates to code.log_level."""
        err = TrimumError(TRMErrorCode.AGENT_KILLED)
        assert err.log_level == "CRITICAL"

    def test_is_exception(self):
        """TrimumError is an Exception subclass that can be caught."""
        try:
            raise TrimumError(TRMErrorCode.TOOL_NOT_FOUND)
        except TrimumError as e:
            assert e.code == TRMErrorCode.TOOL_NOT_FOUND
        except Exception:
            pytest.fail("TrimumError not caught as TrimumError")

    def test_exception_from_string_code(self):
        """TrimumError accepts a TRMErrorCode string value."""
        err = TrimumError("TRM-3001")
        assert err.code == TRMErrorCode.AGENT_NOT_FOUND
        assert err.category == "agent"

    def test_default_message_all_codes(self):
        """Every error code has a non-empty default message."""
        for code in TRMErrorCode:
            err = TrimumError(code)
            assert err.message, f"{code.value} has empty default message"
            assert len(err.message) > 10, f"{code.value} default message too short: {err.message}"
