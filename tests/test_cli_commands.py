"""Focused tests for Phase B CLI commands."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.cli import main  # noqa: E402
from trimum_core import sandbox_state  # noqa: E402
from trimum_core.cli.commands import doctor as doctor_mod  # noqa: E402
from trimum_core.cli.commands import status as status_mod  # noqa: E402
from trimum_core import env_file  # noqa: E402


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
        monkeypatch.setattr(status_mod, "_find_daemon_pid", lambda *a, **k: 4242)
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
        monkeypatch.setattr(status_mod, "_find_daemon_pid", lambda *a, **k: None)
        monkeypatch.setattr(status_mod, "_system_snapshot", lambda: {"error": "no psutil"})

        data = status_mod.get_status_data(FakeConfig())

        assert data["running"] is False
        assert data["pid"] is None
        assert data["agents"] is None

    def test_pid_http_ipc_come_from_daemon_health(self, monkeypatch):
        """TCP 面关掉后没人监听 8321，pid 只能由 daemon 在 health 里自报。

        `_find_daemon_pid` 后面那条 psutil 扫监听者的路子在那种情况下必然空手。
        """
        monkeypatch.setattr(
            status_mod,
            "get_daemon_status",
            lambda config: {
                "running": True,
                "source": "rpc",
                "health": {
                    "version": "0.5.0",
                    "pid": 777,
                    "http": False,
                    "ipc": True,
                },
            },
        )
        monkeypatch.setattr(status_mod, "read_pid_file", lambda config: None)
        monkeypatch.setattr(status_mod, "_process_info", lambda pid: {"pid": pid})
        monkeypatch.setattr(status_mod, "_system_snapshot", lambda: {})
        monkeypatch.setattr(status_mod, "_agent_count", lambda config: 2)

        data = status_mod.get_status_data(FakeConfig())

        assert data["pid"] == 777
        assert data["http"] is False
        assert data["ipc"] is True


class TestHealthCommand:
    def test_health_json_includes_api_key_presence(self, monkeypatch, capsys):
        # CLI 入口会 env_file.ensure_loaded()：不挡住的话，开发机 .env 里的
        # GROQ_API_KEY 会让「删掉就该缺席」的断言随机器变（有 .env 就挂）。
        monkeypatch.setattr(env_file, "candidate_paths", lambda: [Path("no-such.env")])
        monkeypatch.setattr(env_file, "_loaded", False)
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


class TestSecurityLearningCommand:
    """`trm security learning` / `learn` 走 daemon HTTP（P1 学习反馈环）。

    回归点：`_learn_data` 曾把请求体按位置传给 `http_json`，而该参数是
    keyword-only，真机上直接报 `http_json() takes 3 positional arguments but 4 were given`。
    """

    def test_learning_without_daemon_returns_hint(self, monkeypatch, capsys):
        from trimum_core.cli.commands import security as security_mod

        monkeypatch.setattr(
            security_mod,
            "get_daemon_status",
            lambda config: {"running": False, "source": None, "health": None},
        )
        monkeypatch.setattr(security_mod, "rpc_call", lambda *a, **k: None)

        assert main(["--json", "security", "learning"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["daemon_running"] is False

    def test_learn_posts_body_as_keyword(self, monkeypatch, capsys):
        from trimum_core.cli.commands import security as security_mod

        calls = []

        def fake_http_json(config, method, path, *, json_data=None, timeout=2.0):
            calls.append((method, path, json_data))
            return {"data": {"summary": {"profiles_count": 1}, "injected": 2}}

        monkeypatch.setattr(
            security_mod,
            "get_daemon_status",
            lambda config: {"running": True, "source": "http", "health": None},
        )
        monkeypatch.setattr(security_mod, "http_json", fake_http_json)
        monkeypatch.setattr(security_mod, "rpc_call", lambda *a, **k: None)

        assert main(["--json", "security", "learn", "--inject"]) == 0
        out = json.loads(capsys.readouterr().out)

        assert calls == [("POST", "/api/security/learn", {"inject": True})]
        assert out["injected"] == 2

    def test_learn_without_daemon_fails(self, monkeypatch, capsys):
        from trimum_core.cli.commands import security as security_mod

        monkeypatch.setattr(
            security_mod,
            "get_daemon_status",
            lambda config: {"running": False, "source": None, "health": None},
        )
        monkeypatch.setattr(security_mod, "rpc_call", lambda *a, **k: None)

        assert main(["--json", "security", "learn"]) == 1
        captured = capsys.readouterr()
        assert "daemon is not running" in captured.err

    def test_tokens_and_learning_prefer_rpc(self, monkeypatch, capsys):
        """socket 通了就不该再碰 HTTP —— TCP 面关掉之后这条命令全靠它。"""
        from trimum_core.cli.commands import security as security_mod

        calls = []

        def fake_rpc(config, method, params=None, timeout=2.0):
            calls.append((method, params))
            if method == "security.tokens":
                return {"tokens": [{"agent_id": "a1"}]}
            return {"summary": {"profiles_count": 1}, "profiles": {}}

        def explode(*args, **kwargs):
            raise AssertionError("RPC 通了就不该再走 HTTP")

        monkeypatch.setattr(security_mod, "rpc_call", fake_rpc)
        monkeypatch.setattr(security_mod, "http_json", explode)

        assert main(["--json", "security", "tokens"]) == 0
        assert json.loads(capsys.readouterr().out)["tokens"] == [{"agent_id": "a1"}]

        assert main(["--json", "security", "learning"]) == 0
        assert json.loads(capsys.readouterr().out)["summary"] == {"profiles_count": 1}

        assert [method for method, _ in calls] == ["security.tokens", "security.learning"]

    def test_learn_sends_inject_over_rpc(self, monkeypatch, capsys):
        from trimum_core.cli.commands import security as security_mod

        seen = {}

        def fake_rpc(config, method, params=None, timeout=2.0):
            if method == "security.learn":
                seen["method"] = method
                seen["params"] = params
                return {"mode": "auto", "summary": {}, "injected": 3}
            return None

        monkeypatch.setattr(security_mod, "rpc_call", fake_rpc)

        assert main(["--json", "security", "learn", "--inject"]) == 0

        assert json.loads(capsys.readouterr().out)["injected"] == 3
        assert seen == {"method": "security.learn", "params": {"inject": True}}


class TestSecurityRevokeCommand:
    """`trm security revoke` — JIT token revocation via RPC."""

    def test_revoke_via_rpc_success(self, monkeypatch, capsys):
        from trimum_core.cli.commands import security as security_mod

        seen = {}

        def fake_rpc(config, method, params=None, timeout=2.0):
            seen["method"] = method
            seen["params"] = params
            return {"revoked": True, "token": "abcd1234..."}

        monkeypatch.setattr(security_mod, "rpc_call", fake_rpc)

        assert main(["--json", "security", "revoke", "abcd1234"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["revoked"] is True
        assert seen == {
            "method": "security.revoke",
            "params": {"token_id": "abcd1234"},
        }

    def test_revoke_not_found_fails(self, monkeypatch, capsys):
        from trimum_core.cli.commands import security as security_mod

        monkeypatch.setattr(
            security_mod,
            "rpc_call",
            lambda config, method, params=None, timeout=2.0: {
                "revoked": False,
                "error": "token not found (expired, used, or already revoked)",
            },
        )

        assert main(["--json", "security", "revoke", "zzzz9999"]) == 1
        err = capsys.readouterr().err
        assert "token not found" in err

    def test_revoke_ambiguous_prefix_fails(self, monkeypatch, capsys):
        from trimum_core.cli.commands import security as security_mod

        monkeypatch.setattr(
            security_mod,
            "rpc_call",
            lambda config, method, params=None, timeout=2.0: {
                "revoked": False,
                "error": "ambiguous prefix: 2 tokens match",
            },
        )

        assert main(["--json", "security", "revoke", "abcd"]) == 1
        err = capsys.readouterr().err
        assert "ambiguous" in err

    def test_revoke_daemon_down_fails(self, monkeypatch, capsys):
        from trimum_core.cli.commands import security as security_mod

        monkeypatch.setattr(security_mod, "rpc_call", lambda *a, **k: None)

        assert main(["--json", "security", "revoke", "abcd1234"]) == 1
        err = capsys.readouterr().err
        assert "daemon unreachable" in err


class TestAskCtrlC:
    """`trm ask` — KeyboardInterrupt handling returns exit code 130."""

    def test_ask_keyboard_interrupt_returns_130(self, monkeypatch, capsys):
        from trimum_core.cli.commands import ask as ask_mod

        class _FakeArgs:
            prompt = "do something"
            agent = "trm-exec"
            interactive = False
            json = False
            quiet = False

        def _explode(*args, **kwargs):
            raise KeyboardInterrupt()

        monkeypatch.setattr(ask_mod, "asyncio", _FakeAsyncio(_explode))

        rc = ask_mod.handler(_FakeArgs())
        assert rc == 130
        assert "interrupted" in capsys.readouterr().out


class _FakeAsyncio:
    """Minimal stand-in for the asyncio module (only .run is used)."""

    def __init__(self, run_fn):
        self._run_fn = run_fn

    def run(self, *args, **kwargs):
        return self._run_fn(*args, **kwargs)


class TestGatewayRevokeJitToken:
    """ToolGateway.revoke_jit_token — unit level."""

    def test_revoke_existing_token(self):
        from trimum_core.tool_gateway import ToolGateway
        from trimum_core.models import ToolType

        gw = ToolGateway()
        token = gw.issue_jit_token("agent-1", ToolType.SHELL, "ls")
        full = token.token

        assert gw.revoke_jit_token(full) is True
        assert full not in gw._jit_tokens

    def test_revoke_nonexistent_token_returns_false(self):
        from trimum_core.tool_gateway import ToolGateway
        from trimum_core.models import ToolType

        gw = ToolGateway()
        token = gw.issue_jit_token("agent-1", ToolType.SHELL, "ls")
        full = token.token

        assert gw.revoke_jit_token(full) is True
        assert gw.revoke_jit_token(full) is False  # idempotent

    def test_revoke_empty_gateway_returns_false(self):
        from trimum_core.tool_gateway import ToolGateway

        gw = ToolGateway()
        assert gw.revoke_jit_token("nonexistent") is False


class TestSandboxState:
    """Q8: sandbox_state 现算快照 + status/doctor 展示，只读、拿不到就 unknown。"""

    # -- landlock 三档 + 异常 --

    def test_landlock_readonly(self, monkeypatch):
        monkeypatch.setattr(
            sandbox_state.sandbox_exec, "current_state", lambda: "readonly"
        )
        assert sandbox_state.landlock_state() == "readonly"

    def test_landlock_workspace_write(self, monkeypatch):
        monkeypatch.setattr(
            sandbox_state.sandbox_exec, "current_state", lambda: "workspace-write"
        )
        assert sandbox_state.landlock_state() == "workspace-write"

    def test_landlock_off(self, monkeypatch):
        monkeypatch.setattr(
            sandbox_state.sandbox_exec, "current_state", lambda: "off"
        )
        assert sandbox_state.landlock_state() == "off"

    def test_landlock_exception_is_unknown(self, monkeypatch):
        def boom():
            raise RuntimeError("no landlock")

        monkeypatch.setattr(sandbox_state.sandbox_exec, "current_state", boom)
        assert sandbox_state.landlock_state() == "unknown"

    # -- seccomp 三档 + 异常 --

    def test_seccomp_l1(self, monkeypatch):
        monkeypatch.setattr(
            sandbox_state.seccomp_exec, "current_state", lambda: "l1"
        )
        assert sandbox_state.seccomp_state() == "l1"

    def test_seccomp_strict(self, monkeypatch):
        monkeypatch.setattr(
            sandbox_state.seccomp_exec, "current_state", lambda: "strict"
        )
        assert sandbox_state.seccomp_state() == "strict"

    def test_seccomp_off(self, monkeypatch):
        monkeypatch.setattr(
            sandbox_state.seccomp_exec, "current_state", lambda: "off"
        )
        assert sandbox_state.seccomp_state() == "off"

    def test_seccomp_exception_is_unknown(self, monkeypatch):
        def boom():
            raise RuntimeError("no seccomp")

        monkeypatch.setattr(sandbox_state.seccomp_exec, "current_state", boom)
        assert sandbox_state.seccomp_state() == "unknown"

    # -- S1 daemon 加固 drop-in --

    def test_daemon_hardening_absent_when_dir_without_dropin(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sandbox_state, "SYSTEMD_UNIT_DIR", tmp_path)
        assert sandbox_state.daemon_hardening_state() == "absent"

    def test_daemon_hardening_present_with_dropin(self, monkeypatch, tmp_path):
        dropin_dir = tmp_path / "trmd.service.d"
        dropin_dir.mkdir()
        (dropin_dir / "10-hardening.conf").write_text(
            "[Service]\nNoNewPrivileges=true\n", encoding="utf-8"
        )
        monkeypatch.setattr(sandbox_state, "SYSTEMD_UNIT_DIR", tmp_path)
        assert sandbox_state.daemon_hardening_state() == "present"
        # unit 参数真的生效：别的 unit 没有 drop-in
        assert sandbox_state.daemon_hardening_state("other") == "absent"

    def test_daemon_hardening_unknown_when_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            sandbox_state,
            "SYSTEMD_UNIT_DIR",
            tmp_path / "no-such-systemd-dir",
        )
        assert sandbox_state.daemon_hardening_state() == "unknown"

    # -- snapshot --

    def test_snapshot_shape_and_never_raises(self):
        # 真机跑一次不抛异常；值随宿主变，不断言具体档位
        snap = sandbox_state.snapshot()
        assert set(snap) == {"landlock", "seccomp", "daemon_hardening"}
        for value in snap.values():
            assert isinstance(value, str)
            assert value != ""

    def test_snapshot_unknown_when_all_unavailable(self, monkeypatch, tmp_path):
        def boom():
            raise RuntimeError("nope")

        monkeypatch.setattr(sandbox_state.sandbox_exec, "current_state", boom)
        monkeypatch.setattr(sandbox_state.seccomp_exec, "current_state", boom)
        monkeypatch.setattr(
            sandbox_state, "SYSTEMD_UNIT_DIR", tmp_path / "no-such-systemd-dir"
        )
        snap = sandbox_state.snapshot()
        assert snap == {
            "landlock": "unknown",
            "seccomp": "unknown",
            "daemon_hardening": "unknown",
        }

    # -- status 三条路径 --

    def test_status_data_includes_sandbox(self, monkeypatch):
        monkeypatch.setattr(status_mod, "get_daemon_status", lambda config: {
            "running": False,
            "source": None,
            "health": None,
        })
        monkeypatch.setattr(status_mod, "_find_daemon_pid", lambda *a, **k: None)
        monkeypatch.setattr(status_mod, "_system_snapshot", lambda: {"error": "no psutil"})
        monkeypatch.setattr(
            status_mod.sandbox_state,
            "snapshot",
            lambda unit="trmd": {
                "landlock": "readonly",
                "seccomp": "l1",
                "daemon_hardening": "present",
            },
        )

        data = status_mod.get_status_data(FakeConfig())

        assert data["sandbox"] == {
            "landlock": "readonly",
            "seccomp": "l1",
            "daemon_hardening": "present",
        }

    def test_status_json_has_sandbox_section(self, monkeypatch, capsys):
        monkeypatch.setattr(status_mod, "get_daemon_status", lambda config: {
            "running": False,
            "source": None,
            "health": None,
        })
        monkeypatch.setattr(status_mod, "_find_daemon_pid", lambda *a, **k: None)
        monkeypatch.setattr(status_mod, "_system_snapshot", lambda: {"error": "no psutil"})
        monkeypatch.setattr(
            status_mod.sandbox_state,
            "snapshot",
            lambda unit="trmd": {
                "landlock": "workspace-write",
                "seccomp": "strict",
                "daemon_hardening": "absent",
            },
        )

        assert main(["--json", "status"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["sandbox"]["landlock"] == "workspace-write"
        assert payload["sandbox"]["seccomp"] == "strict"
        assert payload["sandbox"]["daemon_hardening"] == "absent"

    def test_status_human_prints_sandbox_line(self, monkeypatch, capsys):
        monkeypatch.setattr(status_mod, "get_daemon_status", lambda config: {
            "running": False,
            "source": None,
            "health": None,
        })
        monkeypatch.setattr(status_mod, "_find_daemon_pid", lambda *a, **k: None)
        monkeypatch.setattr(status_mod, "_system_snapshot", lambda: {"error": "no psutil"})
        monkeypatch.setattr(
            status_mod.sandbox_state,
            "snapshot",
            lambda unit="trmd": {
                "landlock": "off",
                "seccomp": "off",
                "daemon_hardening": "unknown",
            },
        )

        assert main(["status"]) == 0
        out = capsys.readouterr().out

        sandbox_lines = [line for line in out.splitlines() if "sandbox" in line]
        assert any(
            "landlock=" in line
            and "seccomp=" in line
            and "daemon-hardening=" in line
            for line in sandbox_lines
        )

    # -- doctor 两条路径 --

    def test_doctor_json_has_sandbox_section(self, monkeypatch, capsys):
        monkeypatch.setattr(
            doctor_mod.sandbox_state,
            "snapshot",
            lambda unit="trmd": {
                "landlock": "readonly",
                "seccomp": "l1",
                "daemon_hardening": "present",
            },
        )

        assert main(["--json", "doctor"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["sandbox"] == {
            "landlock": "readonly",
            "seccomp": "l1",
            "daemon_hardening": "present",
        }

    def test_doctor_human_prints_sandbox_line(self, monkeypatch, capsys):
        monkeypatch.setattr(
            doctor_mod.sandbox_state,
            "snapshot",
            lambda unit="trmd": {
                "landlock": "off",
                "seccomp": "off",
                "daemon_hardening": "absent",
            },
        )

        main(["doctor"])
        out = capsys.readouterr().out

        sandbox_lines = [line for line in out.splitlines() if "sandbox" in line]
        assert any(
            "landlock=" in line
            and "seccomp=" in line
            and "daemon-hardening=" in line
            for line in sandbox_lines
        )

    def test_doctor_exit_code_ignores_sandbox(self, monkeypatch, capsys):
        # 沙箱全 unknown 也不该让 doctor 变红：退出码只跟 python/packages 走
        monkeypatch.setattr(
            doctor_mod.sandbox_state,
            "snapshot",
            lambda unit="trmd": {
                "landlock": "unknown",
                "seccomp": "unknown",
                "daemon_hardening": "unknown",
            },
        )
        with_sandbox = main(["doctor"])
        monkeypatch.setattr(
            doctor_mod.sandbox_state,
            "snapshot",
            lambda unit="trmd": {
                "landlock": "readonly",
                "seccomp": "l1",
                "daemon_hardening": "present",
            },
        )
        without_sandbox_unknown = main(["doctor"])
        capsys.readouterr()

        assert with_sandbox == without_sandbox_unknown
        assert with_sandbox in {0, 1}
