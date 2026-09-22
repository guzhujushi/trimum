"""S2 内核层沙箱（``sandbox_exec``）用例。

对照 ``docs/SANDBOX-PLAN.md`` §8 的 S2 验收行，四条口径：

1. **允许路径可写 / 未允许路径 EACCES** —— Landlock 是 Linux 专有，只能真机实测
   （``TestLandlockReal``，其他平台 skip）；
2. **施加失败时命令不执行且审计有记录** —— 平台无关（把「施加」那一步换掉即可测）；
3. **不支持的平台如实报 ``unsupported``，不假装已隔离、也不因此拒绝执行** ——
   本机（Windows）走的就是这条；
4. **没有第二条派生通道** —— 静态检查六个 spawn 点全部收口（谁都不许自己
   ``create_subprocess_*``）。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import sandbox_exec  # noqa: E402
from trimum_core.models import (  # noqa: E402
    AgentManifest,
    ExecuteRequest,
    ToolType,
)
from trimum_core.tool_gateway import ToolGateway  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src"
IS_LINUX = sys.platform.startswith("linux")
FAKE_ABI4 = sandbox_exec.SandboxCapability(True, 4, "abi=4")


def _req(**kwargs) -> ExecuteRequest:
    kwargs.setdefault("tool", ToolType.SHELL)
    kwargs.setdefault("args", ["echo", "hi"])
    return ExecuteRequest(**kwargs)


def _manifest(**sandbox) -> AgentManifest:
    return AgentManifest(name="probe", version="1", capabilities=[], sandbox=sandbox)


@pytest.fixture
def supported(monkeypatch):
    """假装本机内核支持 Landlock（abi=4），让档案解析走「会施加」的那条路。"""
    monkeypatch.setattr(sandbox_exec, "_probe_uncached", lambda: FAKE_ABI4)
    sandbox_exec.reset_cache()
    yield FAKE_ABI4
    sandbox_exec.reset_cache()


@pytest.fixture
def paths(monkeypatch, tmp_path):
    """把 Linux 形状的默认路径集换成本次用例的临时目录（平台无关地测档案）。"""
    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()
    monkeypatch.setattr(sandbox_exec, "_ALWAYS_WRITE", ())
    monkeypatch.setattr(sandbox_exec, "_TMP_ROOTS", ())
    monkeypatch.setattr(sandbox_exec, "_SYSTEM_READ", (str(tmp_path),))
    monkeypatch.setattr(sandbox_exec, "_NEVER_WORKSPACE", ())
    monkeypatch.setattr(sandbox_exec, "_socket_dirs", list)
    return SimpleNamespace(ws=ws, outside=outside, root=tmp_path)


# ══════════════════════════════════════════════════════════════════════
# 能力探测
# ══════════════════════════════════════════════════════════════════════


class TestCapability:
    def test_probe_is_cached(self, monkeypatch):
        calls = {"n": 0}

        def fake():
            calls["n"] += 1
            return FAKE_ABI4

        monkeypatch.setattr(sandbox_exec, "_probe_uncached", fake)
        sandbox_exec.reset_cache()
        assert sandbox_exec.probe().supported is True
        assert sandbox_exec.probe().supported is True
        assert calls["n"] == 1
        sandbox_exec.probe(refresh=True)
        assert calls["n"] == 2

    @pytest.mark.skipif(IS_LINUX, reason="这条测的是非 Linux 平台")
    def test_non_linux_is_unsupported_not_silent_pass(self):
        cap = sandbox_exec.probe()
        assert cap.supported is False
        assert "platform" in cap.reason
        assert "unsupported" in cap.summary()

    @pytest.mark.skipif(not IS_LINUX, reason="Landlock 只在 Linux 上探测")
    def test_linux_reports_abi(self):
        cap = sandbox_exec.probe()
        if not cap.supported:
            pytest.skip(f"本机 Landlock 不可用：{cap.reason}")
        assert cap.abi >= 1


# ══════════════════════════════════════════════════════════════════════
# 档案解析（模式 / 路径 / 收紧规则）
# ══════════════════════════════════════════════════════════════════════


class TestPlanResolution:
    def test_default_mode_is_workspace_write(self, supported, paths):
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        assert plan.mode == sandbox_exec.MODE_WORKSPACE
        assert plan.state == sandbox_exec.MODE_WORKSPACE
        assert plan.enforcing is True

    def test_env_overrides_config(self, supported, paths, monkeypatch):
        monkeypatch.setenv(sandbox_exec.ENV_MODE, "readonly")
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        assert plan.mode == "readonly"

    def test_explicit_arg_beats_env(self, supported, paths, monkeypatch):
        monkeypatch.setenv(sandbox_exec.ENV_MODE, "readonly")
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)), mode="strict")
        assert plan.mode == "strict"

    def test_off_mode_has_no_rules(self, supported, paths):
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)), mode="off")
        assert plan.state == sandbox_exec.STATE_OFF
        assert plan.rules == []
        assert plan.enforcing is False

    def test_unknown_mode_is_fail_closed(self, supported, paths):
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)), mode="banana")
        assert plan.blockers and "banana" in plan.blockers[0]
        assert plan.state == "banana:failed"
        assert plan.enforcing is False

    def test_unsupported_platform_skips_profile_but_executes(self, monkeypatch, paths):
        monkeypatch.setattr(
            sandbox_exec,
            "_probe_uncached",
            lambda: sandbox_exec.SandboxCapability(False, 0, "platform:win32"),
        )
        sandbox_exec.reset_cache()
        req = _req(cwd=str(paths.ws))
        plan = sandbox_exec.plan_for(req)
        assert plan.state == sandbox_exec.STATE_UNSUPPORTED
        assert plan.rules == [] and plan.blockers == []
        assert req.sandbox == sandbox_exec.STATE_UNSUPPORTED

    def test_manifest_can_tighten_but_not_loosen(self, supported, paths, monkeypatch):
        monkeypatch.setenv(sandbox_exec.ENV_MODE, "workspace-write")
        tight = _req(cwd=str(paths.ws), agent_manifest=_manifest(mode="readonly"))
        monkeypatch.setenv(sandbox_exec.ENV_MODE, "strict")
        loose = _req(cwd=str(paths.ws), agent_manifest=_manifest(mode="off"))
        assert sandbox_exec.plan_for(tight).mode == "readonly"
        assert sandbox_exec.plan_for(loose).mode == "strict"

    def test_manifest_write_paths_are_ignored(self, supported, paths):
        req = _req(
            cwd=str(paths.ws),
            agent_manifest=_manifest(write=[str(paths.outside)]),
        )
        plan = sandbox_exec.plan_for(req)
        assert str(paths.outside) not in plan.write_roots

    def test_system_cwd_is_not_treated_as_workspace(self, supported):
        # "/" 这类系统面当 cwd 时**不给写权限**（否则等于没边界）；档案回退到进程 cwd
        root = str(Path("/"))
        plan = sandbox_exec.plan_for(_req(cwd="/"))
        assert root not in plan.write_roots
        assert root in plan.read_roots

    def test_config_write_paths_are_honoured(self, supported, paths, monkeypatch):
        monkeypatch.setattr(
            sandbox_exec, "_read_config", lambda: {"write_paths": [str(paths.outside)]}
        )
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        assert str(paths.outside) in plan.write_roots

    def test_same_path_in_read_and_write_keeps_write_rights(self, supported, paths):
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        ws = str(paths.ws)
        assert ws in plan.write_roots
        assert ws not in plan.read_roots  # 写规则是读规则的超集，别重复加
        rights = dict(plan.rules)[ws]
        assert rights & sandbox_exec._A_MAKE_REG
        assert rights & sandbox_exec._A_WRITE_FILE

    def test_rules_are_abi_aware(self, supported, paths):
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        handled = sandbox_exec._handled_mask(plan.abi)
        for _path, rights in plan.rules:
            assert rights & ~handled == 0  # 不许出现内核不认识的位

    def test_state_is_written_back_to_request(self, supported, paths):
        req = _req(cwd=str(paths.ws))
        plan = sandbox_exec.plan_for(req)
        assert req.sandbox == plan.state
        assert plan.as_dict()["state"] == plan.state


# ══════════════════════════════════════════════════════════════════════
# 派生：fail-closed 与 degraded
# ══════════════════════════════════════════════════════════════════════


class TestSpawnFailClosed:
    @pytest.mark.asyncio
    async def test_apply_failure_means_command_never_runs(self, supported, paths, monkeypatch):
        seen: list[dict] = []

        async def fake_spawn(shell, args, kwargs):
            seen.append(kwargs)
            raise subprocess.SubprocessError("Exception occurred in preexec_fn.")

        monkeypatch.setattr(sandbox_exec, "_spawn_process", fake_spawn)
        req = _req(cwd=str(paths.ws))
        plan = sandbox_exec.plan_for(req)

        with pytest.raises(sandbox_exec.SandboxError) as info:
            await sandbox_exec.spawn_shell(plan, "echo hi > " + str(paths.ws / "x"))

        assert plan.state == "workspace-write:failed"
        assert req.sandbox == "workspace-write:failed"
        assert info.value.state == "workspace-write:failed"
        assert len(seen) == 1
        assert callable(seen[0]["preexec_fn"])  # 施不上就抛，绝不放行

    @pytest.mark.asyncio
    async def test_blocked_plan_raises_without_spawning(self, supported, paths, monkeypatch):
        async def explode(*_args, **_kwargs):
            raise AssertionError("档案不可用时不许派生")

        monkeypatch.setattr(sandbox_exec, "_spawn_process", explode)
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)), mode="banana")
        with pytest.raises(sandbox_exec.SandboxError):
            await sandbox_exec.spawn_exec(plan, "echo", "hi")
        assert plan.state == "banana:failed"

    @pytest.mark.asyncio
    async def test_fail_closed_false_degrades_loudly(self, supported, paths, monkeypatch):
        calls: list[dict] = []

        async def fake_spawn(shell, args, kwargs):
            calls.append(kwargs)
            if "preexec_fn" in kwargs:
                raise subprocess.SubprocessError("Exception occurred in preexec_fn.")
            return "PROC"

        monkeypatch.setattr(sandbox_exec, "_spawn_process", fake_spawn)
        monkeypatch.setenv(sandbox_exec.ENV_FAIL_CLOSED, "0")
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        assert plan.fail_closed is False

        proc = await sandbox_exec.spawn_exec(plan, "echo", "hi")
        assert proc == "PROC"
        assert plan.state == "workspace-write:degraded"
        assert "preexec_fn" in calls[0] and "preexec_fn" not in calls[1]

    @pytest.mark.asyncio
    async def test_unsupported_platform_still_runs_command(self, paths, monkeypatch):
        monkeypatch.setattr(
            sandbox_exec,
            "_probe_uncached",
            lambda: sandbox_exec.SandboxCapability(False, 0, "platform:win32"),
        )
        sandbox_exec.reset_cache()
        calls: list[dict] = []

        async def fake_spawn(shell, args, kwargs):
            calls.append(kwargs)
            return "PROC"

        monkeypatch.setattr(sandbox_exec, "_spawn_process", fake_spawn)
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        assert await sandbox_exec.spawn_exec(plan, "echo", "hi") == "PROC"
        assert "preexec_fn" not in calls[0]
        assert plan.state == sandbox_exec.STATE_UNSUPPORTED

    @pytest.mark.asyncio
    async def test_off_mode_never_installs_hook(self, supported, paths, monkeypatch):
        calls: list[dict] = []

        async def fake_spawn(shell, args, kwargs):
            calls.append(kwargs)
            return "PROC"

        monkeypatch.setattr(sandbox_exec, "_spawn_process", fake_spawn)
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)), mode="off")
        await sandbox_exec.spawn_exec(plan, "echo", "hi")
        assert "preexec_fn" not in calls[0]
        assert plan.state == sandbox_exec.STATE_OFF

    @pytest.mark.asyncio
    async def test_command_not_found_is_not_swallowed(self, supported, paths, monkeypatch):
        async def fake_spawn(shell, args, kwargs):
            raise FileNotFoundError("no such binary")

        monkeypatch.setattr(sandbox_exec, "_spawn_process", fake_spawn)
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        with pytest.raises(FileNotFoundError):  # 127 语义不能被沙箱吃掉
            await sandbox_exec.spawn_exec(plan, "definitely-not-a-binary")


# ══════════════════════════════════════════════════════════════════════
# 真机（Linux + Landlock）实测
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not IS_LINUX, reason="Landlock 是 Linux 专有")
class TestLandlockReal:
    def _probe_or_skip(self):
        cap = sandbox_exec.probe()
        if not cap.supported:
            pytest.skip(f"本机 Landlock 不可用：{cap.reason}")
        return cap

    def test_workspace_writable_home_denied(self, tmp_path):
        self._probe_or_skip()
        ws = tmp_path / "ws"
        ws.mkdir()
        home_probe = Path.home() / f"trimum-s2-probe-{os.getpid()}"
        # 先证明「不施沙箱时写 $HOME 是允许的」，否则 EACCES 可能是文件权限而不是沙箱
        home_probe.write_text("permission-ok", encoding="utf-8")
        home_probe.unlink()

        plan = sandbox_exec.plan_for(cwd=str(ws))

        async def run():
            proc = await sandbox_exec.spawn_shell(
                plan,
                f'echo ok > "{ws}/allowed.txt"; echo bad > "{home_probe}"; echo "rc=$?"',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            return out.decode(), err.decode()

        out, err = asyncio.run(run())
        assert plan.state == sandbox_exec.MODE_WORKSPACE
        assert (ws / "allowed.txt").read_text(encoding="utf-8").strip() == "ok"
        assert not home_probe.exists(), f"$HOME 不该可写：{out} {err}"
        assert "rc=0" not in out

    def test_readonly_profile_blocks_workspace_write(self, tmp_path):
        self._probe_or_skip()
        ws = tmp_path / "ws"
        ws.mkdir()
        plan = sandbox_exec.plan_for(cwd=str(ws), mode="readonly")

        async def run():
            proc = await sandbox_exec.spawn_shell(
                plan,
                f'echo nope > "{ws}/nope.txt"',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            return out.decode(), err.decode(), proc.returncode

        _out, _err, rc = asyncio.run(run())
        assert rc != 0
        assert not (ws / "nope.txt").exists()

    def test_apply_failure_happens_before_exec(self, monkeypatch, tmp_path):
        self._probe_or_skip()
        ws = tmp_path / "ws"
        ws.mkdir()
        marker = ws / "must-not-exist.txt"

        def boom(_plan):
            raise sandbox_exec.SandboxError("模拟施加失败")

        monkeypatch.setattr(sandbox_exec, "apply_current", boom)
        plan = sandbox_exec.plan_for(cwd=str(ws))

        with pytest.raises(sandbox_exec.SandboxError):
            asyncio.run(
                sandbox_exec.spawn_shell(plan, f'echo x > "{marker}"')
            )
        assert not marker.exists()
        assert plan.state == "workspace-write:failed"

    def test_module_cli_status(self):
        self._probe_or_skip()
        env = {**os.environ, "PYTHONPATH": str(SRC)}
        proc = subprocess.run(
            [sys.executable, "-m", "trimum_core.sandbox_exec", "--status"],
            capture_output=True,
            env=env,
        )
        assert proc.returncode == 0
        assert b"capability" in proc.stdout

    def test_module_cli_enforces_landlock(self, tmp_path):
        self._probe_or_skip()
        ws = tmp_path / "ws"
        ws.mkdir()
        env = {**os.environ, "PYTHONPATH": str(SRC)}
        proc = subprocess.run(
            [
                sys.executable, "-m", "trimum_core.sandbox_exec",
                "--profile", "workspace-write", "--cwd", str(ws),
                "--", "sh", "-c", f'echo ok > "{ws}/cli.txt"',
            ],
            capture_output=True,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr.decode()
        assert (ws / "cli.txt").exists()


# ══════════════════════════════════════════════════════════════════════
# 收口与审计接线
# ══════════════════════════════════════════════════════════════════════


class TestNoBypass:
    def test_no_direct_subprocess_spawn_in_tool_paths(self):
        for name in ("tool_dispatchers.py", "agent_launcher.py"):
            text = (SRC / "trimum_core" / name).read_text(encoding="utf-8")
            assert "create_subprocess" not in text, f"{name} 还留着自己的派生通道"

    def test_all_spawn_points_go_through_sandbox_exec(self):
        dispatchers = (SRC / "trimum_core" / "tool_dispatchers.py").read_text(encoding="utf-8")
        launcher = (SRC / "trimum_core" / "agent_launcher.py").read_text(encoding="utf-8")
        adapter = (SRC / "trimum_core" / "cli_adapter.py").read_text(encoding="utf-8")
        # 4 个工具分发点（shell / git / process list / process kill）+ 子 Agent + CLI 广接入
        assert dispatchers.count("sandbox_exec.plan_for(") == 4
        assert dispatchers.count("sandbox_exec.spawn_") >= 4
        assert launcher.count("sandbox_exec.plan_for(") == 1
        assert adapter.count("sandbox_exec.plan_for(") == 1


class TestAuditWiring:
    @pytest.mark.asyncio
    async def test_gateway_audit_records_sandbox_state(self, tmp_path):
        gw = ToolGateway(layer4=False)
        resp = await gw.execute(_req(args=["echo", "s2-audit"], cwd=str(tmp_path)))
        assert resp.exit_code == 0
        event = gw._audit_log[-1]
        assert event.sandbox, "审计里必须有沙箱状态（off/unsupported/<档>）"
        assert event.details["sandbox"] == event.sandbox
        assert resp.sandbox == event.sandbox  # 两条路（request 回写 / response 回传）口径一致

    @pytest.mark.asyncio
    async def test_agent_launcher_reports_sandbox_state(self, tmp_path):
        from trimum_core.agent_launcher import launch_agent, terminate_process

        script = tmp_path / "sleeper" / "main.py"
        script.parent.mkdir(parents=True)
        script.write_text(
            "import sys, time\nprint('up', flush=True)\ntime.sleep(5)\n", encoding="utf-8"
        )
        launch = await launch_agent(
            "s2-agent", "sleeper", script=script, base=tmp_path / "agents", startup_grace=0.4
        )
        try:
            assert launch.error is None, launch.error
            assert launch.sandbox in {
                sandbox_exec.STATE_UNSUPPORTED,
                sandbox_exec.MODE_WORKSPACE,
            }
        finally:
            if launch.process is not None:
                await terminate_process(launch.process)

    @pytest.mark.asyncio
    async def test_generic_executor_reports_sandbox_state(self, monkeypatch):
        from trimum_core import cli_adapter

        class Proc:
            returncode = 0

            async def communicate(self):
                return b"hello", b""

        async def fake_exec(*_args, **_kwargs):
            return Proc()

        monkeypatch.setattr(cli_adapter.asyncio, "create_subprocess_exec", fake_exec)
        result = await cli_adapter.generic_executor(
            {"binary": "fd"},
            {"args": ["pattern"]},
            which=lambda _name: "/usr/bin/fd",
        )
        assert result["status"] == "allowed"
        assert result["sandbox"] in {
            sandbox_exec.STATE_UNSUPPORTED,
            sandbox_exec.MODE_WORKSPACE,
        }
