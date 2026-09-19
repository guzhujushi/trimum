"""Focused tests for Phase B CLI commands."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.cli import main  # noqa: E402
from trimum_core.cli.commands import doctor as doctor_mod  # noqa: E402
from trimum_core.cli.commands import status as status_mod  # noqa: E402


class FakeConfig:
    host = "127.0.0.1"
    port = 8321
    socket_path = "/tmp/trimum-test.sock"


class TestStatusCommand:
    def test_get_status_data_assembles_process_and_system(self, monkeypatch):
        monkeypatch.setattr(
            status_mod,
            "get_daemon_status",
            lambda config: {
                "running": True,
                "source": "rpc",
                "health": {"version": "0.5.0"},
            },
        )
        monkeypatch.setattr(status_mod, "_find_daemon_pid", lambda config: 4242)
        monkeypatch.setattr(
            status_mod,
            "_process_info",
            lambda pid: {
                "pid": pid,
                "status": "running",
                "uptime_seconds": 90.0,
                "memory_mb": 12.5,
                "cpu_percent": 1.5,
            },
        )
        monkeypatch.setattr(
            status_mod,
            "_system_snapshot",
            lambda: {
                "cpu_percent": 8.0,
                "memory_percent": 20.0,
                "memory_used_mb": 3000.0,
                "memory_total_mb": 16000.0,
            },
        )
        monkeypatch.setattr(status_mod, "_agent_count", lambda config: 3)

        data = status_mod.get_status_data(FakeConfig())

        assert data["running"] is True
        assert data["version"] == "0.5.0"
        assert data["pid"] == 4242
        assert data["process"]["memory_mb"] == 12.5
        assert data["system"]["cpu_percent"] == 8.0
        assert data["agents"] == 3

    def test_status_offline(self, monkeypatch):
        monkeypatch.setattr(
            status_mod,
            "get_daemon_status",
            lambda config: {"running": False, "source": None, "health": None},
        )
        monkeypatch.setattr(status_mod, "_find_daemon_pid", lambda config: None)
        monkeypatch.setattr(status_mod, "_system_snapshot", lambda: {"error": "no psutil"})

        data = status_mod.get_status_data(FakeConfig())

        assert data["running"] is False
        assert data["pid"] is None
        assert data["agents"] is None


class TestHealthCommand:
    def test_health_json_includes_api_key_presence(self, monkeypatch, capsys):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "present-for-test")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        assert main(["--json", "health"]) == 0
        payload = json.loads(capsys.readouterr().out)

        by_name = {item["name"]: item for item in payload["api_keys"]}
        assert by_name["DEEPSEEK_API_KEY"]["present"] is True
        assert by_name["GROQ_API_KEY"]["present"] is False
        assert "DEEPSEEK_API_KEY" not in payload["missing_api_keys"]
        assert "GROQ_API_KEY" in payload["missing_api_keys"]


class TestDoctorCommand:
    def test_package_check_reports_all_required_packages(self):
        data = doctor_mod._check_packages()
        names = {item["name"] for item in data["packages"]}
        assert {"fastapi", "pydantic", "psutil", "httpx"} <= names
        assert data["status"] in {"ok", "fail"}


class TestMemoryCommand:
    def test_set_get_missing(self, monkeypatch, capsys):
        root = Path(__file__).resolve().parents[1] / "tmp" / "phaseb_memory_test"
        shutil.rmtree(root, ignore_errors=True)
        monkeypatch.setenv("TRIMUM_MEMORY_DIR", str(root))
        try:
            assert main(["--quiet", "memory", "set", "greeting", "hello"]) == 0

            assert main(["--json", "memory", "get", "greeting"]) == 0
            payload = json.loads(capsys.readouterr().out)
            assert payload["found"] is True
            assert payload["value"] == "hello"

            assert main(["--json", "memory", "get", "missing-key"]) == 1
            payload = json.loads(capsys.readouterr().out)
            assert payload["found"] is False
        finally:
            shutil.rmtree(root, ignore_errors=True)