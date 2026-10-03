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
import stat
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

    def test_char_devices_fall_back_to_parent_dir(self, supported, monkeypatch, tmp_path):
        """landlock 装不上字符设备 ⇒ 用父目录顶上，否则 `cmd 2>/dev/null` 会 EACCES。

        `_ALWAYS_WRITE` 存在的理由就是这个（见常量上的注释），而
        `_landlockable("/dev/null")` 是 False（字符设备 EINVAL）—— 真机实测
        readonly / workspace-write / strict 三档 `open('/dev/null','w')` 全 EACCES，
        经网关跑 `pytest` 直接 INTERNALERROR（2026-09-29，E7 第 5 片真机验收抓到）。
        """
        dev = tmp_path / "dev"
        dev.mkdir()
        node = dev / "null"
        node.write_text("", encoding="utf-8")
        # 只有当它不是「目录 / 普通文件」时才需要父目录兜底 —— 这里先证明普通文件是 landlockable
        assert sandbox_exec._landlockable(str(node)) is True
        monkeypatch.setattr(sandbox_exec, "_ALWAYS_WRITE", (str(node),))
        assert sandbox_exec._always_write_roots() == (str(node),)

        # 造一个 landlock 装不上的目标（socket / 管道都行；用 os.mkfifo 最省事）
        fifo = dev / "fifo"
        os.mkfifo(str(fifo))
        assert sandbox_exec._landlockable(str(fifo)) is False
        monkeypatch.setattr(sandbox_exec, "_ALWAYS_WRITE", (str(fifo),))
        assert sandbox_exec._always_write_roots() == (str(fifo), str(dev))

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

    def test_dev_null_writable_under_sandbox(self, tmp_path):
        """任何档都必须能写 /dev/null —— 否则经网关跑的 pytest 直接 INTERNALERROR。"""
        self._probe_or_skip()
        ws = tmp_path / "ws"
        ws.mkdir()
        # 对照组：不施沙箱时本来就能写
        with open(os.devnull, "w", encoding="utf-8") as fh:
            fh.write("x")
        for mode in ("workspace-write", "strict", "readonly"):
            plan = sandbox_exec.plan_for(cwd=str(ws), mode=mode)

            async def run(_plan=plan):
                proc = await sandbox_exec.spawn_shell(
                    _plan,
                    "echo ok > /dev/null && echo devnull-ok",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out, err = await proc.communicate()
                return out.decode(), err.decode(), proc.returncode

            out, err, rc = asyncio.run(run())
            assert rc == 0, f"{mode}: rc={rc} out={out} err={err}"
            assert "devnull-ok" in out, f"{mode}: {out} {err}"

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


class TestLandlockTargets:
    """真机教训（2026-09-22）：Landlock 只认目录与普通文件，权限还要按类型给。

    实测：目录 OK；普通文件 / 字符设备 **EINVAL(22)**（那是「给文件申请了目录级权限」）；
    管道 / socket **EBADFD(77)**。S2 的真机用例第一次跑就撞上 —— 每一次派生都 fail-closed。
    """

    def test_collect_drops_non_file_targets(self, monkeypatch, tmp_path):
        keep = tmp_path / "ws"
        keep.mkdir()
        pipe = tmp_path / "fifo"
        pipe.write_text("x", encoding="utf-8")

        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if str(path) == str(pipe):
                # 假装它是管道（真机上 /dev/stderr 就是这个下场）
                return os.stat_result((stat.S_IFIFO | 0o600,) + tuple(info)[1:])
            return info

        monkeypatch.setattr(sandbox_exec.os, "stat", fake_stat)
        kept = sandbox_exec._collect(
            [str(keep), str(pipe), str(tmp_path / "not-there")], kind="write", seen=set()
        )
        assert kept == [str(keep)]

    def test_regular_file_roots_get_file_rights(self, supported, paths, tmp_path):
        ws = paths.ws
        target = tmp_path / "single.txt"
        target.write_text("x", encoding="utf-8")

        plan = sandbox_exec.plan_for(_req(cwd=str(ws)), extra_write=[str(target)])
        rule = dict(plan.rules)[str(target)]
        assert rule & sandbox_exec._A_READ_DIR == 0, "文件根不能要目录级权限（内核判 EINVAL）"
        assert rule & sandbox_exec._A_MAKE_REG == 0
        assert rule & sandbox_exec._A_WRITE_FILE

        read_plan = sandbox_exec.plan_for(_req(cwd=str(ws)), extra_read=[str(target)])
        read_rule = dict(read_plan.rules)[str(target)]
        assert read_rule == sandbox_exec._file_read_rights(read_plan.abi)


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


class TestManifestWriteAuthorization:
    """S6③：manifest 声明的写路径要**运营者显式授权**才生效（取交集）。

    红线的机械证据：① 两边都点名才进写面；② 只授权不声明 → 仍然不进（单向）；
    ③ readonly 档一个字不变（声明写面一律不放开）。
    """

    def test_authorized_manifest_write_enters_write_roots(
        self, supported, paths, monkeypatch
    ):
        monkeypatch.setattr(
            sandbox_exec, "_read_agent_allow_write", lambda name: [str(paths.outside)]
        )
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(
            _req(
                cwd=str(paths.ws),
                agent_manifest=_manifest(write=[str(paths.outside)]),
            )
        )
        assert str(paths.outside) in plan.write_roots
        assert any("allow_write" in note for note in plan.notes)

    def test_unauthorized_manifest_write_is_ignored_with_a_note(
        self, supported, paths, monkeypatch
    ):
        monkeypatch.setattr(sandbox_exec, "_read_agent_allow_write", lambda name: [])
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(
            _req(
                cwd=str(paths.ws),
                agent_manifest=_manifest(write=[str(paths.outside)]),
            )
        )
        assert str(paths.outside) not in plan.write_roots
        assert any("被忽略" in note for note in plan.notes)

    def test_authorization_alone_never_opens_a_path(self, supported, paths, monkeypatch):
        # 交集是单向的：运营者授权 ≠ 自动放开，manifest 也得点名。
        # 用「有名字、但没声明 write」的 manifest —— 若实现把授权当成放行
        # （authorized_write 初值直接取授权列表），这条会挂。
        monkeypatch.setattr(
            sandbox_exec, "_read_agent_allow_write", lambda name: [str(paths.outside)]
        )
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(
            _req(cwd=str(paths.ws), agent_manifest=_manifest())
        )
        assert str(paths.outside) not in plan.write_roots

    def test_authorization_matches_after_path_normalisation(
        self, supported, paths, monkeypatch
    ):
        monkeypatch.setattr(
            sandbox_exec,
            "_read_agent_allow_write",
            lambda name: [f"{paths.outside}/", f"{paths.outside}/../outside"],
        )
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(
            _req(
                cwd=str(paths.ws),
                agent_manifest=_manifest(write=[str(paths.outside)]),
            )
        )
        assert str(paths.outside) in plan.write_roots

    def test_readonly_never_opens_declared_write(self, supported, paths, monkeypatch):
        monkeypatch.setattr(
            sandbox_exec, "_read_agent_allow_write", lambda name: [str(paths.outside)]
        )
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(
            _req(
                cwd=str(paths.ws),
                agent_manifest=_manifest(write=[str(paths.outside)]),
            ),
            mode=sandbox_exec.MODE_READONLY,
        )
        assert str(paths.outside) not in plan.write_roots

    def test_nameless_manifest_still_gets_an_ignore_note(self, supported, paths):
        # manifest 是 dict 且没带 name（dict 形态的 request 常见）：留痕不许消失，
        # 旧行为是用 "?" 兜底 —— 这里钉住「声明被忽略」仍然可见
        # dict 形态的 request 才装得下「没有 name 的 manifest」（AgentManifest 必填 name）
        plan = sandbox_exec.plan_for(
            {
                "cwd": str(paths.ws),
                "agent_manifest": {"sandbox": {"write": [str(paths.outside)]}},
            }
        )
        assert str(paths.outside) not in plan.write_roots
        assert any("被忽略" in note and "?" in note for note in plan.notes)

    def test_readonly_note_does_not_claim_adoption(self, supported, paths, monkeypatch):
        monkeypatch.setattr(
            sandbox_exec, "_read_agent_allow_write", lambda name: [str(paths.outside)]
        )
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(
            _req(
                cwd=str(paths.ws),
                agent_manifest=_manifest(write=[str(paths.outside)]),
            ),
            mode=sandbox_exec.MODE_READONLY,
        )
        assert str(paths.outside) not in plan.write_roots
        assert any("readonly" in note for note in plan.notes)
        assert not any("采纳" in note for note in plan.notes)


class TestPlanSources:
    """S6④：候选面要带来源（谁给的），解释器与校验器都吃这份标注。"""

    def test_sources_cover_every_layer(self, supported, paths, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        req_dir = tmp_path / "req"
        req_dir.mkdir()
        man_dir = tmp_path / "man"
        man_dir.mkdir()
        monkeypatch.setattr(
            sandbox_exec, "_read_config", lambda: {"write_paths": [str(cfg_dir)]}
        )
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(
            _req(cwd=str(paths.ws), agent_manifest=_manifest(read=[str(man_dir)])),
            extra_write=[str(req_dir)],
        )
        assert plan.sources[str(paths.ws)] == sandbox_exec.SOURCE_BUILTIN
        assert plan.sources[str(cfg_dir)] == sandbox_exec.SOURCE_CONFIG
        assert plan.sources[str(req_dir)] == sandbox_exec.SOURCE_REQUEST
        assert plan.sources[str(man_dir)] == sandbox_exec.SOURCE_MANIFEST

    def test_mode_source_tracks_the_layer(self, supported, paths, monkeypatch):
        monkeypatch.setattr(sandbox_exec, "_read_config", lambda: {"mode": "strict"})
        sandbox_exec.reset_cache()
        assert (
            sandbox_exec.plan_for(_req(cwd=str(paths.ws))).mode_source
            == sandbox_exec.SOURCE_CONFIG
        )

        monkeypatch.setenv(sandbox_exec.ENV_MODE, "workspace-write")
        assert (
            sandbox_exec.plan_for(_req(cwd=str(paths.ws))).mode_source
            == sandbox_exec.SOURCE_ENV
        )
        assert (
            sandbox_exec.plan_for(_req(cwd=str(paths.ws)), mode="readonly").mode_source
            == sandbox_exec.SOURCE_EXPLICIT
        )

        tightened = sandbox_exec.plan_for(
            _req(cwd=str(paths.ws), agent_manifest=_manifest(mode="readonly")),
            mode="strict",
        )
        assert tightened.mode_source == sandbox_exec.SOURCE_MANIFEST

    def test_skipped_records_missing_paths_with_source(
        self, supported, paths, tmp_path, monkeypatch
    ):
        missing = tmp_path / "not-there"
        monkeypatch.setattr(
            sandbox_exec, "_read_config", lambda: {"write_paths": [str(missing)]}
        )
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        hits = [item for item in plan.skipped if item["path"] == str(missing)]
        assert hits and hits[0]["reason"] == "missing"
        assert hits[0]["source"] == sandbox_exec.SOURCE_CONFIG

    def test_skipped_marks_not_landlockable_with_source(
        self, supported, paths, tmp_path, monkeypatch
    ):
        target = tmp_path / "fifo"
        target.write_text("x", encoding="utf-8")
        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if str(path) == str(target):
                return os.stat_result((stat.S_IFIFO | 0o600,) + tuple(info)[1:])
            return info

        monkeypatch.setattr(sandbox_exec.os, "stat", fake_stat)
        sandbox_exec.reset_cache()
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)), extra_write=[str(target)])
        hits = [item for item in plan.skipped if item["path"] == str(target)]
        assert hits and hits[0]["reason"] == "not_landlockable"
        assert hits[0]["source"] == sandbox_exec.SOURCE_REQUEST

    def test_collect_report_is_a_side_channel(self, supported, tmp_path, monkeypatch):
        keep = tmp_path / "ws"
        keep.mkdir()
        missing = tmp_path / "not-there"
        report: list[dict] = []
        plain = sandbox_exec._collect(
            [str(keep), str(missing)], kind="write", seen=set()
        )
        with_report = sandbox_exec._collect(
            [(str(keep), sandbox_exec.SOURCE_BUILTIN), str(missing)],
            kind="write",
            seen=set(),
            report=report,
        )
        assert plain == with_report == [str(keep)]
        assert [item["path"] for item in report] == [str(missing)]


class TestExplainScope:
    """S6④：解释器必须与 `plan_for` 的判定**同源**（解释的就是真会施的）。"""

    def test_explanation_matches_the_plan(self, supported, paths, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        monkeypatch.setattr(
            sandbox_exec, "_read_config", lambda: {"write_paths": [str(cfg_dir)]}
        )
        sandbox_exec.reset_cache()
        report = sandbox_exec.explain_scope(cwd=str(paths.ws))
        plan = sandbox_exec.plan_for(_req(cwd=str(paths.ws)))
        assert {item["path"] for item in report["write"]} == set(plan.write_roots)
        assert {item["path"] for item in report["read"]} == set(plan.read_roots)
        assert report["skipped"] == plan.skipped
        assert report["mode"] == plan.mode
        assert report["mode_source"] == plan.mode_source
        assert report["seccomp"]["profile"] == plan.seccomp.profile
        assert report["seccomp"]["source"] == sandbox_exec.SOURCE_DEFAULT
        sources = {item["path"]: item["source"] for item in report["write"]}
        assert sources[str(cfg_dir)] == sandbox_exec.SOURCE_CONFIG
        assert sources[str(paths.ws)] == sandbox_exec.SOURCE_BUILTIN

    def test_seccomp_source_is_labelled(self, supported, paths, monkeypatch):
        monkeypatch.setattr(sandbox_exec, "_read_config", lambda: {"seccomp": "strict"})
        sandbox_exec.reset_cache()
        assert (
            sandbox_exec.explain_scope(cwd=str(paths.ws))["seccomp"]["source"]
            == sandbox_exec.SOURCE_CONFIG
        )
        assert (
            sandbox_exec.explain_scope(cwd=str(paths.ws), seccomp_profile="l1")["seccomp"][
                "source"
            ]
            == sandbox_exec.SOURCE_EXPLICIT
        )

    def test_readonly_explanation_has_no_declared_write(self, supported, paths, monkeypatch):
        monkeypatch.setattr(
            sandbox_exec, "_read_agent_allow_write", lambda name: [str(paths.outside)]
        )
        sandbox_exec.reset_cache()
        report = sandbox_exec.explain_scope(
            "probe",
            manifest=_manifest(write=[str(paths.outside)]),
            mode="readonly",
            cwd=str(paths.ws),
        )
        assert str(paths.outside) not in {item["path"] for item in report["write"]}

    def test_unknown_agent_does_not_raise(self, supported, paths):
        report = sandbox_exec.explain_scope("ghost", cwd=str(paths.ws))
        assert report["agent"] == "ghost"
        assert isinstance(report["mode"], str)
        assert isinstance(report["notes"], list)


class TestValidateScope:
    """S6⑤：校验器只报问题，且判定与 `explain_scope` **同源**（不另解析一遍配置）。"""

    def _clean(self, monkeypatch):
        # 把 security.yaml 换成干净的一份，免得真机配置里的问题串味到断言
        monkeypatch.setattr(sandbox_exec, "_read_config", lambda: {})
        sandbox_exec.reset_cache()

    def test_clean_config_has_no_error(self, supported, paths, monkeypatch):
        self._clean(monkeypatch)
        problems = sandbox_exec.validate_scope(cwd=str(paths.ws))
        assert [item for item in problems if item["severity"] == "error"] == []

    def test_bad_mode_is_an_error(self, supported, paths, monkeypatch):
        self._clean(monkeypatch)
        problems = sandbox_exec.validate_scope(mode="banana", cwd=str(paths.ws))
        assert any(
            item["severity"] == "error" and item["code"] == "bad_mode" for item in problems
        )

    def test_config_path_missing_is_an_error(self, supported, paths, monkeypatch):
        missing = paths.root / "nope"
        monkeypatch.setattr(
            sandbox_exec, "_read_config", lambda: {"write_paths": [str(missing)]}
        )
        sandbox_exec.reset_cache()
        problems = sandbox_exec.validate_scope(cwd=str(paths.ws))
        # 只盯这条路径：干净的 HOME 下内置数据目录缺席也会报 path_missing（但那是 info）
        hits = [item for item in problems if str(missing) in item["message"]]
        assert hits and all(item["severity"] == "error" for item in hits)
        assert any(str(missing) in item["message"] for item in hits)

    def test_request_path_missing_is_an_error(self, supported, paths, monkeypatch):
        """派单请求（`extra_write`，与 agent_launcher 同口径）里的坏路径也要报 error。"""
        self._clean(monkeypatch)
        missing = paths.root / "dispatch-nope"
        problems = sandbox_exec.validate_scope(
            cwd=str(paths.ws), extra_write=[str(missing)]
        )
        hits = [item for item in problems if str(missing) in item["message"]]
        assert hits and all(item["severity"] == "error" for item in hits)
        assert any(
            item["code"] == "path_missing" and "派单请求" in item["message"] for item in hits
        )

    def test_builtin_missing_path_is_info_not_error(self, supported, paths, monkeypatch):
        self._clean(monkeypatch)
        missing = paths.root / "vanished"
        monkeypatch.setattr(sandbox_exec, "_ALWAYS_WRITE", (str(missing),))
        sandbox_exec.reset_cache()
        problems = sandbox_exec.validate_scope(cwd=str(paths.ws))
        hits = [item for item in problems if str(missing) in item["message"]]
        assert hits and all(item["severity"] == "info" for item in hits)
        assert not any(
            item["severity"] == "error" and str(missing) in item["message"] for item in problems
        )

    def test_unauthorized_manifest_write_is_a_warning(self, supported, paths, monkeypatch):
        self._clean(monkeypatch)
        monkeypatch.setattr(sandbox_exec, "_read_agent_allow_write", lambda name: [])
        sandbox_exec.reset_cache()
        problems = sandbox_exec.validate_scope(
            "probe",
            manifest=_manifest(write=[str(paths.outside)]),
            cwd=str(paths.ws),
        )
        hits = [item for item in problems if item["code"] == "manifest_write_not_authorized"]
        assert hits and all(item["severity"] == "warning" for item in hits)
        assert all("allow_write" in item["fix"] for item in hits)

    def test_unknown_keys_are_warnings(self, supported, paths, monkeypatch):
        monkeypatch.setattr(
            sandbox_exec, "_read_config", lambda: {"banana_key": 1}
        )
        sandbox_exec.reset_cache()
        problems = sandbox_exec.validate_scope(
            "probe",
            manifest=_manifest(frobnicate=True),
            cwd=str(paths.ws),
        )
        hits = [item for item in problems if item["code"] == "unknown_key"]
        assert {item["severity"] for item in hits} == {"warning"}
        assert any("banana_key" in item["message"] for item in hits)
        assert any("frobnicate" in item["message"] for item in hits)

    def test_consumed_manifest_keys_are_not_flagged(self, supported, paths, monkeypatch):
        """反向防误报：manifest 里**真会被读**的键（含 seccomp 别名）一个都不许报未知。"""
        self._clean(monkeypatch)
        manifest = _manifest(
            mode="strict",
            seccomp="l1",
            seccomp_allow=["openat"],
            extra_syscalls=["read"],
            seccomp_block=["socket"],
            extra_block=["mount"],
            fs_read=[str(paths.root)],
            allowed_write=[str(paths.ws)],
        )
        problems = sandbox_exec.validate_scope("probe", manifest=manifest, cwd=str(paths.ws))
        assert [item for item in problems if item["code"] == "unknown_key"] == []

    def test_problems_are_sorted_error_warning_info(self, supported, paths, monkeypatch):
        monkeypatch.setattr(sandbox_exec, "_read_config", lambda: {})
        monkeypatch.setattr(sandbox_exec, "_read_agent_allow_write", lambda name: [])
        missing = paths.root / "vanished"
        monkeypatch.setattr(sandbox_exec, "_ALWAYS_WRITE", (str(missing),))
        sandbox_exec.reset_cache()
        problems = sandbox_exec.validate_scope(
            "probe",
            manifest=_manifest(write=[str(paths.outside)]),
            seccomp_profile="banana",
            cwd=str(paths.ws),
        )
        severities = [item["severity"] for item in problems]
        assert severities == sorted(severities, key=["error", "warning", "info"].index)
        assert {"error", "warning", "info"} <= set(severities)
