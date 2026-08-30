"""Structured logging for trimum Core using structlog."""

from __future__ import annotations

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer

from .config import Config


def setup_logging(config: Config) -> None:
    """Configure structlog based on config."""
    log_level = config.log_level.upper()
    log_format = config.log_format
    log_path = config.log_path

    if log_format == "json":
        renderer = JSONRenderer()
    else:
        renderer = ConsoleRenderer(colors=False)

    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        renderer,
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(
            open(log_path, "a", encoding="utf-8") if log_path else None
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger instance."""
    return structlog.get_logger(name or "trimum_core")
