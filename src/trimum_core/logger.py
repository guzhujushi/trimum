"""Structured logging for trimum Core using structlog.

包括全局凭据脱敏：所有日志输出前自动过滤 API key / secret / token / password
等敏感信息。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer

from .config import Config
from .secrets_redactor import SecretsRedactor

# 全局脱敏器实例
_secrets_redactor = SecretsRedactor()


def _redact_event(_logger: object, _method_name: str, event_dict: dict) -> dict:
    """structlog processor：递归脱敏 event_dict 中的所有字符串值。"""
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            event_dict[key] = _secrets_redactor.redact(value)
        elif isinstance(value, dict):
            event_dict[key] = _secrets_redactor.redact_dict(value)
        elif isinstance(value, list):
            event_dict[key] = [_secrets_redactor.redact_value(item) for item in value]
    return event_dict


def setup_logging(config: Config) -> None:
    """Configure structlog based on config."""
    log_level = config.log_level.upper()
    log_format = config.log_format
    log_path = config.log_path

    structlog.configure(
        processors=_build_processors(log_format),
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(
            open(log_path, "a", encoding="utf-8") if log_path else None
        ),
        cache_logger_on_first_use=True,
    )


def _build_processors(log_format: str) -> list:
    """Build the processor chain (shared by the daemon and the CLI)."""
    if log_format == "json":
        renderer = JSONRenderer()
    else:
        renderer = ConsoleRenderer(colors=False)

    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_event,  # ← 全局凭据脱敏
        renderer,
    ]

    # 时间戳放在最前面方便阅读
    if log_format != "json":
        processors = [
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            *processors,
        ]
    return processors


class _StderrWriter:
    """Write-through proxy so logs always reach the *current* ``sys.stderr``."""

    def write(self, data: str) -> int:
        return sys.stderr.write(data)

    def flush(self) -> None:
        sys.stderr.flush()


def setup_cli_logging() -> None:
    """Send CLI diagnostics to stderr, keeping stdout payload-only.

    ``trm --json <cmd>`` must stay machine-readable, but library code logs at INFO
    (e.g. ``mcp.started``) — without this, those lines land in front of the JSON.
    The daemon keeps using :func:`setup_logging` (log file / stdout).
    """
    structlog.configure(
        processors=_build_processors("console"),
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(_StderrWriter()),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger instance."""
    return structlog.get_logger(name or "trimum_core")


__all__ = ["setup_logging", "setup_cli_logging", "get_logger"]
