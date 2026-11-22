"""HTTP management plane requires caller authentication."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi.testclient import TestClient

from trimum_core.api_server import create_app
from trimum_core.config import Config
from trimum_core.http_auth import (
    ADMIN_TOKEN_ENV,
    ADMIN_TOKEN_HEADER,
    check_admin_token,
    configured_admin_token,
)

STRONG_TOKEN = "0123456789abcdef0123456789abcdef"


def build_config(tmp_path: Path) -> Config:
    config = Config()
    config.set("logging.file", str(tmp_path / "logs" / "trimum.log"))
    config.set("context.db_path", str(tmp_path / "context.db"))
    config.set("core.socket_path", str(tmp_path / "trimum.sock"))
    config.set("policy.path", str(tmp_path / "policy.yaml"))
    return config


def test_token_resolution_prefers_env(tmp_path, monkeypatch):
    config = build_config(tmp_path)
    config.set("core.http_admin_token", "config-token-0123456789")
    monkeypatch.setenv(ADMIN_TOKEN_ENV, "env-token-0123456789")

    assert configured_admin_token(config) == "env-token-0123456789"
    assert check_admin_token(config, "env-token-0123456789") == "ok"


def test_missing_or_weak_tokens_fail_closed(tmp_path, monkeypatch):
    monkeypatch.delenv(ADMIN_TOKEN_ENV, raising=False)
    config = build_config(tmp_path)

    assert check_admin_token(config, "") == "disabled"

    config.set("core.http_admin_token", "short")
    assert check_admin_token(config, "short") == "weak"


def test_health_stays_public_and_api_is_closed_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(ADMIN_TOKEN_ENV, raising=False)
    app = create_app(build_config(tmp_path))
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    response = client.post(
        "/api/security/allow_once",
        json={"agent_id": "a", "tool": "shell", "command": "ls"},
    )
    assert response.status_code == 403


def test_api_rejects_wrong_token_and_accepts_configured_token(tmp_path, monkeypatch):
    monkeypatch.delenv(ADMIN_TOKEN_ENV, raising=False)
    config = build_config(tmp_path)
    config.set("core.http_admin_token", STRONG_TOKEN)
    client = TestClient(create_app(config))
    body = {"agent_id": "a", "tool": "shell", "command": "ls"}

    wrong = client.post(
        "/api/security/allow_once",
        json=body,
        headers={ADMIN_TOKEN_HEADER: "wrong-token-0123456789"},
    )
    assert wrong.status_code == 401

    allowed = client.post(
        "/api/security/allow_once",
        json=body,
        headers={ADMIN_TOKEN_HEADER: STRONG_TOKEN},
    )
    assert allowed.status_code == 200
    assert allowed.json()["success"] is True


def test_non_ascii_token_is_rejected_not_crashing(tmp_path, monkeypatch):
    """Header 值不可信：非 ASCII token 必须 401，而不是 compare_digest 抛 TypeError。"""
    monkeypatch.delenv(ADMIN_TOKEN_ENV, raising=False)
    config = build_config(tmp_path)
    config.set("core.http_admin_token", STRONG_TOKEN)
    client = TestClient(create_app(config))

    response = client.post(
        "/api/security/allow_once",
        json={"agent_id": "a", "tool": "shell", "command": "ls"},
        headers={ADMIN_TOKEN_HEADER: "tökén-0123456789".encode("utf-8")},
    )

    assert response.status_code == 401
