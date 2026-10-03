"""``run_agent``（子 Agent 运行器：看管 + 资源上限 + 用量回传）测试。

口径：所有用例**真调用** ``run_agent``（只断言字符串拼法会失去判别力）。
cgroup 包装口径用注入的 ``systemd_ok`` / ``killer`` 覆盖，不真跑 systemd。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import sandbox_limits
from trimum_core.agent_launcher import (
    agent_log_dir,
    run_agent,
    usage_path_for,
)

USAGE_WRITER = '''
import json, os
path = os.environ.get("TRIMUM_AGENT_USAGE_PATH")
with open(path, "w", encoding="utf-8") as fh:
    json.dump({"steps": 3, "tokens": 120}, fh)
'''

NO_USAGE = "import sys\nsys.exit(0)\n"

BAD_JSON = '''
import os
with open(os.environ["TRIMUM_AGENT_USAGE_PATH"], "w", encoding="utf-8") as fh:
    fh.write("{not json")
'''

STRING_STEPS = '''
import json, os
with open(os.environ["TRIMUM_AGENT_USAGE_PATH"], "w", encoding="utf-8") as fh:
    json.dump({"steps": "3", "tokens": 120}, fh)
'''

SLEEPER = "import time\ntime.sleep(30)\n"


# 本轮红线探针：工作区外写**必须**失败（成功 ⇒ exit(4)），并回传 usage
LANDLOCK_PROBE = """
import json, os, sys
agent_id = os.environ.get('TRIMUM_AGENT_ID')
expected_cwd = os.path.dirname(os.path.abspath(__file__))
if not agent_id or os.getcwd() != expected_cwd:
    sys.exit(3)
try:
    with open(os.environ['TRIMUM_PROBE_OUTSIDE'], 'w', encoding='utf-8') as fh:
        fh.write('x')
except OSError:
    pass
else:
    sys.exit(4)
with open(os.environ['TRIMUM_AGENT_USAGE_PATH'], 'w', encoding='utf-8') as fh:
    json.dump({'steps': 1, 'tokens': 1}, fh)
"""


def write_landlock_probe(root, tag):
    """写探针脚本，返回 (脚本目录, 工作区外探针文件)。

    探针路径取 ``$HOME/.trimum-landlock-probe-<tag>``：它**不在**任何默认写根里
    （写根只有 ``~/.trimum`` / ``~/.local/share/trimum`` / ``/tmp`` 等），
    但用户本来就能写 ⇒ 写不进去只可能是 Landlock 在起作用（判据有效）。
    """
    script_dir = root / "worker"
    script = script_dir / "main.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(LANDLOCK_PROBE, encoding="utf-8")
    outside = Path.home() / f".trimum-landlock-probe-{tag}"
    if outside.exists():
        outside.unlink()
    return script_dir, outside


def write_agent(root, agent_type, body):
    script = root / agent_type / "main.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")
    return script


class _ArgvProbe:
    """包一层 sandbox_exec.spawn_exec，记录真派生的 argv（用于验证 cgroup 包装）。"""

    def __init__(self, sandbox_exec_module):
        self._mod = sandbox_exec_module
        self._real = sandbox_exec_module.spawn_exec
        self.argvs = []

    async def __call__(self, plan, *argv, **kwargs):
        self.argvs.append(list(argv))
        return await self._real(plan, *argv, **kwargs)


class TestUsagePath:
    def test_usage_path_for(self, tmp_path):
        expected = agent_log_dir(tmp_path) / "a1.usage.json"
        assert usage_path_for("a1", tmp_path) == expected
        assert expected.parent == agent_log_dir(tmp_path)
        assert expected.name == "a1.usage.json"


class TestUsageReporting:
    @pytest.mark.asyncio
    async def test_normal_usage_round_trip(self, tmp_path):
        write_agent(tmp_path, "demo", USAGE_WRITER)
        run = await run_agent("u1", "demo", base=tmp_path, cgroup=False)

        assert run.usage_path == usage_path_for("u1", tmp_path)
        assert run.usage_reported is True
        assert run.steps_used == 3
        assert run.tokens_used == 120
        assert run.returncode == 0
        assert run.timed_out is False
        assert run.terminated is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(NO_USAGE, id="missing-file"),
            pytest.param(BAD_JSON, id="bad-json"),
            pytest.param(STRING_STEPS, id="steps-is-string"),
        ],
    )
    async def test_invalid_usage_not_reported(self, tmp_path, body):
        write_agent(tmp_path, "demo", body)
        # 不许抛异常；坏/缺的 usage 一律不回填
        run = await run_agent("u2", "demo", base=tmp_path, cgroup=False)

        assert run.usage_reported is False
        assert run.steps_used is None
        assert run.tokens_used is None


class TestTimeoutTermination:
    @pytest.mark.asyncio
    async def test_timeout_actually_kills_process(self, tmp_path):
        write_agent(tmp_path, "sleeper", SLEEPER)
        run = await run_agent(
            "s1", "sleeper", base=tmp_path, cgroup=False, timeout=0.5
        )
        pid = run.launch.process.pid

        assert run.timed_out is True
        assert run.terminated is True
        assert run.returncode is not None
        # 进程真的没了（不只信标志位）
        await asyncio.sleep(0.1)
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        assert alive is False


class TestCgroupWrapping:
    """cgroup 包装口径：①② 用 ``build_command`` 纯产物校验（不依赖本机有没有 systemd-run），
    ③（killer 序列）用真派生的长命进程校验。都不真跑 systemd。"""

    def test_cgroup_command_shape(self):
        from trimum_core import sandbox_limits as sl

        base_argv = [sys.executable, "/tmp/worker/main.py", "w1"]
        cmd = sl.build_command(base_argv, agent_name="worker", systemd_ok=True)
        unit = sl.unit_name("worker")

        # ① 状态 + 单元名
        assert cmd.state == "systemd"
        assert cmd.unit == unit == "trimum-agent-worker.service"

        # ② argv 前缀 + -p 里含 MemoryMax=
        assert list(cmd.argv)[:7] == [
            "systemd-run", "--user", "--quiet", "--wait", "--pipe",
            "--collect", f"--unit={unit}",
        ]
        assert "MemoryMax=" in " ".join(cmd.argv)
        # 传入的原始 argv 被原样保留在 `--` 之后
        assert list(cmd.argv)[-len(base_argv):] == base_argv

    @pytest.mark.asyncio
    async def test_cgroup_killer_sequence_on_timeout(self, tmp_path, monkeypatch):
        """超时时走注入的 killer：TERM 先、宽限后 KILL。

        ``systemd_ok=True`` 让 ``build_command`` 真产出包装 argv + 单元名（校验 ①②），
        但**不真跑 systemd**（本机能跑 systemd-run 也会因无 user 会话秒退）：
        spawn_exec 的 spy 改用一个独立的长命真实进程，让 ``run_agent`` 真等到超时、
        真触发终止流程，从而校验注入 killer 的 (unit, signal) 序列。
        """
        import trimum_core.agent_launcher as al
        from trimum_core import sandbox_exec

        write_agent(tmp_path, "worker", SLEEPER)  # 让 base_argv 里的脚本路径存在
        # 记录真派生的 argv（来自 build_command 的包装），校验 cgroup 口径
        recorded_argv = []
        kill_argv = []
        real_spawn = sandbox_exec.spawn_exec

        unit = sandbox_limits.unit_name("worker")
        script_dir = tmp_path / "worker"
        base_argv = [sys.executable, str(script_dir / "main.py"), "w1"]

        class _LongLived:
            """挂起的协程 ⇒ wait() 永远不返回 ⇒ run_agent 必然超时走终止流程。"""

            def __init__(self):
                self.pid = os.getpid()
                self.returncode = None
                self._done = asyncio.Event()

            def terminate(self):
                pass

            def kill(self):
                self._done.set()

            async def wait(self):
                await self._done.wait()
                return self.returncode

        long_lived = _LongLived()
        calls = []

        async def spy_spawn(plan, *argv, **kwargs):
            # 记包装 argv；agent 本体用挂起进程模拟长命（不跑 systemd-run 二进制）。
            # 注入 killer 优先 ⇒ 终止信号不该走到 spawn_exec 的 systemctl 派生
            assert not (argv and argv[0] == "systemctl"), "注入 killer 时默认派生不该被触发"
            recorded_argv.append(list(argv))
            return long_lived

        monkeypatch.setattr(sandbox_exec, "spawn_exec", spy_spawn)

        # 注入的 killer 仍然优先（签名 (unit, signal_name) 不变），并顺手结束挂起进程
        async def fake_killer(unit_, signal_name):
            calls.append((unit_, signal_name))
            if signal_name == "KILL":
                long_lived.kill()
                long_lived.returncode = -9

        run = await run_agent(
            "w1",
            "worker",
            base=tmp_path,
            timeout=2.0,
            terminate_grace=0.3,
            cgroup=True,
            systemd_ok=True,
            killer=fake_killer,
        )

        # ② 真派生的 argv 确实是 systemd-run 包装，且 `--` 之后是「单元内 Layer K 施加 + agent 本体」
        assert recorded_argv
        assert recorded_argv[0][:7] == [
            "systemd-run", "--user", "--quiet", "--wait", "--pipe",
            "--collect", f"--unit={unit}",
        ]
        assert "MemoryMax=" in " ".join(recorded_argv[0])
        assert "SystemCallFilter" not in " ".join(recorded_argv[0])
        inner = recorded_argv[0][recorded_argv[0].index("--") + 1:]
        assert inner[:4] == [sys.executable, "-m", "trimum_core.sandbox_exec", "--profile"]
        assert inner[inner.index("--") + 1:] == base_argv, "单元内最终 exec 的必须是 agent 本体"
        # 缺陷 1/2 回归钉：TRIMUM_ 变量透传 + 工作目录钉在脚本目录
        assert "--setenv=TRIMUM_AGENT_ID=w1" in recorded_argv[0]
        assert f"--setenv=TRIMUM_AGENT_USAGE_PATH={usage_path_for('w1', tmp_path)}" in recorded_argv[0]
        assert f"--working-directory={script_dir}" in recorded_argv[0]
        # argv 顺序固定：--working-directory 与 --setenv 都排在 -p 之前、-- 之前
        wd_idx = recorded_argv[0].index(f"--working-directory={script_dir}")
        setenv_idx = recorded_argv[0].index("--setenv=TRIMUM_AGENT_ID=w1")
        first_p = next(i for i, a in enumerate(recorded_argv[0]) if a == "-p")
        sep_idx = recorded_argv[0].index("--")
        assert wd_idx < setenv_idx < first_p < sep_idx

        # ③ 超时走注入 killer，TERM 先、宽限后 KILL
        assert run.limits_state == "systemd"
        assert run.unit == unit
        assert run.timed_out is True
        assert run.terminated is True
        assert run.returncode is not None
        signals = [sig for (_u, sig) in calls]
        units = {u for (u, _s) in calls}
        assert units == {unit}
        assert signals[0] == "TERM"
        assert signals.index("TERM") < signals.index("KILL")
        # 注入 killer 优先：终止全程没走默认派生（kill_argv 恒空，spy 里另断言）
        assert kill_argv == []

    @pytest.mark.asyncio
    async def test_cgroup_argv_wraps_layer_k(self, tmp_path, monkeypatch):
        """cgroup 档 argv 口径：systemd-run 包装里必须再包一层「单元内 Layer K 施加」。

        不然 Landlock/seccomp 只施在 ``systemd-run`` 身上，真正的 agent 由 systemd
        重新 fork ⇒ 边界静默失效却仍上报已隔离（本轮修的就是它）。
        """
        from trimum_core import sandbox_exec

        script_dir = tmp_path / "worker"
        script = write_agent(tmp_path, "worker", NO_USAGE)
        recorded = []
        real_spawn = sandbox_exec.spawn_exec

        async def spy(plan, *argv, **kwargs):
            recorded.append(list(argv))
            return await real_spawn(plan, "/bin/true", **kwargs)

        monkeypatch.setattr(sandbox_exec, "spawn_exec", spy)
        run = await run_agent(
            "w3", "worker", base=tmp_path, timeout=5.0, cgroup=True, systemd_ok=True,
        )

        assert recorded, "cgroup 档必须真派生一次"
        argv = recorded[0]
        assert argv[0] == "systemd-run"
        assert "SystemCallFilter" not in " ".join(argv), "单元上不许再有第二套 syscall 口径"
        assert "--setenv=TRIMUM_AGENT_ID=w3" in argv
        assert f"--working-directory={script_dir}" in argv

        inner = argv[argv.index("--") + 1:]
        sep = inner.index("--")
        head, tail = inner[:sep], inner[sep + 1:]
        assert head[:4] == [sys.executable, "-m", "trimum_core.sandbox_exec", "--profile"]
        assert "--cwd" in head and str(script_dir) in head
        assert "--seccomp" in head
        assert "--write" in head, "单元内写面必须显式转录（含 usage 目录）"
        assert str(usage_path_for("w3", tmp_path).parent) in head
        assert tail == [sys.executable, str(script), "w3"]

        assert run.limits_state == "systemd"
        assert run.unit == sandbox_limits.unit_name("worker")

    @pytest.mark.asyncio
    async def test_default_killer_uses_kill_whom_all(self, tmp_path, monkeypatch):
        """默认 killer（不注入）在 cgroup 档超时时，argv 必须含 ``--kill-whom=all``。

        用 monkeypatch 抓 ``sandbox_exec.spawn_exec`` 实参，**别真杀东西**：
        ``_kill_unit`` 改走 spawn_exec 派生 systemctl，spy 把它转回真进程并记录 argv；
        agent 本体用挂起进程模拟长命，TERM/KILL 轮次真实走一遍。
        """
        import trimum_core.agent_launcher as al
        from trimum_core import sandbox_exec

        write_agent(tmp_path, "worker", SLEEPER)
        unit = sandbox_limits.unit_name("worker")
        real_spawn = sandbox_exec.spawn_exec

        class _LongLived:
            def __init__(self):
                self.pid = os.getpid()
                self.returncode = None
                self._done = asyncio.Event()

            def terminate(self):
                pass

            def kill(self):
                self._done.set()

            async def wait(self):
                await self._done.wait()
                return self.returncode

        long_lived = _LongLived()
        kill_argv = []

        async def spy_spawn(plan, *argv, **kwargs):
            if argv and argv[0] == "systemctl":
                kill_argv.append(list(argv))
                # TERM 轮：systemctl 不会杀挂起协程，放行让轮次走完；
                # KILL 轮：顺手结束挂起进程，避免测试悬挂
                if "--signal=KILL" in argv:
                    long_lived.kill()
                return await real_spawn(plan, *argv, **kwargs)
            return long_lived

        monkeypatch.setattr(sandbox_exec, "spawn_exec", spy_spawn)

        run = await run_agent(
            "w2", "worker", base=tmp_path, timeout=0.5,
            terminate_grace=0.2, cgroup=True, systemd_ok=True,
        )

        assert run.timed_out is True
        assert run.terminated is True
        assert run.unit == unit
        # 默认 killer 的 argv 必须含 --kill-whom=all（TERM、KILL 各一次）
        assert len(kill_argv) >= 2
        for argv in kill_argv:
            assert argv[0] == "systemctl"
            assert "--kill-whom=all" in argv
            assert unit in argv
        assert kill_argv[0][3] == "--signal=TERM"
        assert kill_argv[1][3] == "--signal=KILL"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not sandbox_limits.systemd_available(),
        reason="systemd-run 不可用（本测试需在 systemd 真机上跑）",
    )
    async def test_cgroup_real_run_env_and_cwd(self, tmp_path):
        """真跑 systemd-run：TRIMUM_AGENT_ID / cwd 正确，且**工作区外写被拒**。

        子脚本写不到 TRIMUM_AGENT_ID、cwd 不对 ⇒ exit(3)；工作区外写得进去 ⇒ exit(4)。
        这两条合起来才证明「Layer K 在单元内真施上了」（本轮红线）。
        """
        script_dir, outside = write_landlock_probe(tmp_path, "cgroup")
        try:
            run = await run_agent(
                "real1", "worker", base=tmp_path, cgroup=True,
                extra_env={"TRIMUM_PROBE_OUTSIDE": str(outside)},
            )
        finally:
            leaked = outside.exists()
            if leaked:
                outside.unlink()
        assert not leaked, "cgroup 档：工作区外的写必须被 Landlock 拒绝"
        assert run.usage_reported is True
        assert run.returncode == 0

    @pytest.mark.asyncio
    async def test_no_cgroup_real_run_same_boundary(self, tmp_path):
        """cgroup=False 档必须是同一套边界（两条路不许一个严一个松）。"""
        script_dir, outside = write_landlock_probe(tmp_path, "nocgroup")
        try:
            run = await run_agent(
                "real2", "worker", base=tmp_path, cgroup=False,
                extra_env={"TRIMUM_PROBE_OUTSIDE": str(outside)},
            )
        finally:
            leaked = outside.exists()
            if leaked:
                outside.unlink()
        assert not leaked, "非 cgroup 档：工作区外的写必须被 Landlock 拒绝"
        assert run.usage_reported is True
        assert run.returncode == 0


class TestStartupFailure:
    @pytest.mark.asyncio
    async def test_missing_script_returns_error(self, tmp_path):
        run = await run_agent("g1", "ghost", base=tmp_path, cgroup=False)
        assert run.error
        assert "not found" in run.error
        assert run.returncode is None
        assert run.usage_reported is False


class TestUsageDirInWriteRoots:
    def test_plan_includes_usage_dir(self, tmp_path):
        from trimum_core import sandbox_exec

        usage_dir = str(usage_path_for("w1", tmp_path).parent)
        plan = sandbox_exec.plan_for(
            cwd=str(tmp_path),
            extra_write=[usage_dir],
        )
        assert usage_dir in plan.write_roots


class TestSpawnPointInvariants:
    """S2 架构红线自检（本文件内）：agent_launcher 不许留自己的派生通道，
    plan_for 只许出现一次。口径与 ``tests/test_sandbox_exec.py::TestNoBypass`` 一致，
    但不去动那个文件。"""

    @staticmethod
    def _launcher_text():
        here = Path(__file__).resolve().parent
        return (here / ".." / "src" / "trimum_core" / "agent_launcher.py").read_text(
            encoding="utf-8"
        )

    def test_no_direct_subprocess_spawn_in_launcher(self):
        text = self._launcher_text()
        assert "create_subprocess" not in text

    def test_single_plan_for_in_launcher(self):
        text = self._launcher_text()
        assert text.count("sandbox_exec.plan_for(") == 1


# ---------- 接线片：预算真叫停（E7 第 4 片后半）----------

OVER_BUDGET_SCRIPT = '''
import json, os, time
path = os.environ["TRIMUM_AGENT_USAGE_PATH"]
with open(path, "w", encoding="utf-8") as fh:
    json.dump({"steps": 5, "tokens": 50}, fh)
time.sleep(30)
'''

SMALL_USAGE_SCRIPT = '''
import json, os
path = os.environ["TRIMUM_AGENT_USAGE_PATH"]
with open(path, "w", encoding="utf-8") as fh:
    json.dump({"steps": 1, "tokens": 1}, fh)
'''

CORRUPT_AFTER_USAGE_SCRIPT = '''
import json, os, time
path = os.environ["TRIMUM_AGENT_USAGE_PATH"]
with open(path, "w", encoding="utf-8") as fh:
    json.dump({"steps": 5, "tokens": 50}, fh)
time.sleep(0.5)  # 先让看管方轮询读到这份合法 usage，再改成坏 JSON
with open(path, "w", encoding="utf-8") as fh:
    fh.write("{oops")
time.sleep(30)
'''


class _TinyBudget:
    """鸭子类型预算（别 import delegation）。"""

    def __init__(self, steps, tokens):
        self.steps = steps
        self.tokens = tokens


class TestBudgetStop:
    @pytest.mark.asyncio
    async def test_budget_stops_child(self, tmp_path):
        write_agent(tmp_path, "worker", OVER_BUDGET_SCRIPT)
        run = await run_agent(
            "b1", "worker", base=tmp_path, cgroup=False,
            budget=_TinyBudget(2, 20), timeout=0,
            usage_poll=0.05, terminate_grace=0.3,
        )
        pid = run.launch.process.pid
        assert run.budget_exhausted is True
        assert run.terminated is True
        assert run.timed_out is False
        assert run.steps_used == 5
        assert run.usage_reported is True
        await asyncio.sleep(0.1)
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        assert alive is False

    @pytest.mark.asyncio
    async def test_budget_not_exceeded_keeps_running(self, tmp_path):
        write_agent(tmp_path, "worker", SMALL_USAGE_SCRIPT)
        run = await run_agent(
            "b2", "worker", base=tmp_path, cgroup=False,
            budget=_TinyBudget(20, 200), timeout=0, usage_poll=0.05,
        )
        assert run.budget_exhausted is False
        assert run.returncode == 0

    @pytest.mark.asyncio
    async def test_seen_usage_fallback_after_kill(self, tmp_path):
        write_agent(tmp_path, "worker", CORRUPT_AFTER_USAGE_SCRIPT)
        run = await run_agent(
            "b3", "worker", base=tmp_path, cgroup=False,
            budget=_TinyBudget(2, 20), timeout=0,
            usage_poll=0.05, terminate_grace=0.3,
        )
        assert run.budget_exhausted is True
        assert run.usage_reported is True
        assert run.steps_used == 5


class TestBudgetPureFuncs:
    def test_budget_ceilings(self):
        from trimum_core.agent_launcher import _budget_ceilings

        assert _budget_ceilings(None) == (None, None)
        assert _budget_ceilings(_TinyBudget(2, 3)) == (2, 3)
        assert _budget_ceilings({"steps": 2}) == (2, None)
        assert _budget_ceilings({"steps": 2, "tokens": 5}) == (2, 5)
        assert _budget_ceilings({"steps": "3", "tokens": True}) == (None, None)
        assert _budget_ceilings(_TinyBudget(0, 0)) == (None, None)
        assert _budget_ceilings({"steps": True}) == (None, None)

    def test_over_budget(self):
        from trimum_core.agent_launcher import _over_budget

        # 等于不算超
        assert _over_budget(5, 50, 5, 50) is False
        # 严格大于才算超
        assert _over_budget(6, 50, 5, 50) is True
        assert _over_budget(5, 51, 5, 50) is True
        # None 维度本身不判超（逐维判定，与 delegate.delegate 同一口径）；另一维超了照样算超
        assert _over_budget(None, 50, 5, 50) is False   # steps 未知、tokens 恰好不超
        assert _over_budget(None, 51, 5, 50) is True    # steps 未知、tokens 超
        assert _over_budget(99, None, 5, 50) is True    # tokens 未知、steps 超
        assert _over_budget(None, None, 5, 50) is False
        assert _over_budget(99, 99, None, None) is False


@pytest.mark.skipif(not sandbox_limits.systemd_available(), reason="needs systemd user session")
class TestBudgetStopCgroup:
    @pytest.mark.asyncio
    async def test_budget_stops_child_cgroup(self, tmp_path):
        write_agent(tmp_path, "worker", OVER_BUDGET_SCRIPT)
        run = await run_agent(
            "b4", "worker", base=tmp_path, cgroup=True,
            budget=_TinyBudget(2, 20), timeout=0,
            usage_poll=0.05, terminate_grace=0.3,
        )
        assert run.budget_exhausted is True
        assert run.terminated is True
        assert run.timed_out is False
        assert run.steps_used == 5
        assert run.usage_reported is True
        if run.unit:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "status", run.unit,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            assert await proc.wait() != 0


class TestStaleUsageReset:
    #: 慢速 writer：先睡 0.5s 再写 usage —— 保证首片（0.1s）轮询一定先读到**陈旧的** 9999
    #: （全局 USAGE_WRITER 跑得太快，对这条 bug 没有判别力，别改它）
    SLOW_USAGE_WRITER = '''
import json, os, time
time.sleep(0.5)
path = os.environ.get("TRIMUM_AGENT_USAGE_PATH")
with open(path, "w", encoding="utf-8") as fh:
    json.dump({"steps": 3, "tokens": 120}, fh)
'''

    @pytest.mark.asyncio
    async def test_stale_usage_is_reset_before_launch(self, tmp_path):
        """上一轮遗留的 usage.json 不许叫停本轮（复用 agent_id 时）"""
        write_agent(tmp_path, "demo", self.SLOW_USAGE_WRITER)
        stale = usage_path_for("u9", tmp_path)
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text(json.dumps({"steps": 9999, "tokens": 999999}), encoding="utf-8")

        run = await run_agent(
            "u9", "demo", base=tmp_path, cgroup=False, budget={"steps": 5, "tokens": 500},
        )

        # 旧实现（不清陈旧文件）会：首片读到 9999 > 5 ⇒ 提前 TERM，budget_exhausted=True / steps_used=9999
        assert run.budget_exhausted is False, run
        assert run.timed_out is False, run
        assert run.steps_used == 3, run
        assert run.tokens_used == 120, run

    @pytest.mark.asyncio
    async def test_usage_path_is_directory_does_not_raise(self, tmp_path):
        """usage.json 位置是个目录时：只告警降级，不许把 launch 打挂（删不掉时的优雅降级）"""
        write_agent(tmp_path, "demo", USAGE_WRITER)
        usage_path_for("u10", tmp_path).mkdir(parents=True, exist_ok=True)

        run = await run_agent("u10", "demo", base=tmp_path, cgroup=False)

        assert run.error == ""
        assert run.usage_reported is False
