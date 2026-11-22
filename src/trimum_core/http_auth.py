"""Authentication for the optional HTTP management plane.

The Unix IPC socket is the primary local control channel.  When the HTTP
plane is enabled it exposes the same management operations, so loopback alone
cannot be treated as authentication: any local process can connect to
``127.0.0.1``.  ``/api/*`` therefore requires a caller-provided admin token.

Resolution order is the project-wide config order: environment variable >
``core.http_admin_token`` > empty default.  When no token is configured the
management API fails closed and only ``/health`` remains public; callers should
use the Unix socket or configure a token explicitly.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

ADMIN_TOKEN_ENV = "TRIMUM_HTTP_ADMIN_TOKEN"
ADMIN_TOKEN_HEADER = "X-Trimum-Admin-Token"
MIN_TOKEN_LENGTH = 16


def configured_admin_token(config: Any = None) -> str:
    """Return the configured HTTP admin token, or ``""`` when disabled."""

    env_value = os.environ.get(ADMIN_TOKEN_ENV, "").strip()
    if env_value:
        return env_value

    if config is None:
        return ""
    try:
        value = config.get("core.http_admin_token", "")
    except Exception:
        return ""
    return value.strip() if isinstance(value, str) else ""


def check_admin_token(config: Any, supplied: str) -> str:
    """Classify an HTTP management request.

    Returns ``ok`` / ``disabled`` / ``weak`` / ``invalid``.  The caller maps
    these to HTTP statuses; never compare tokens with ``==`` (timing leak).
    """

    expected = configured_admin_token(config)
    if not expected:
        return "disabled"
    if len(expected) < MIN_TOKEN_LENGTH:
        return "weak"
    # Compare bytes: ``hmac.compare_digest`` rejects non-ASCII ``str`` inputs
    # with ``TypeError``.  Header values are attacker-controlled, so a
    # non-ASCII token must become 401, never a 500.
    if hmac.compare_digest(
        (supplied or "").encode("utf-8", "surrogateescape"),
        expected.encode("utf-8", "surrogateescape"),
    ):
        return "ok"
    return "invalid"


__all__ = [
    "ADMIN_TOKEN_ENV",
    "ADMIN_TOKEN_HEADER",
    "MIN_TOKEN_LENGTH",
    "check_admin_token",
    "configured_admin_token",
]
