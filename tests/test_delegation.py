"""子 Agent 委派编排测试（E7 第 4 片前半，只做编排、不接线）。

真调 ``delegation`` 的公开函数，不重写编排。异步用例用 ``@pytest.mark.asyncio``。
真 spawn 用例 Linux 专用（非 Linux 跳过）；不起服务、不连网。
"""

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import delegation
from trimum_core.event_bus import EventBus


def parent_caps(tools, **extra):
    block = {"tools": tools}
    block.update(extra)
    return block


def task(text, **kwargs):
    return delegation.DelegationRequest(task=text, **kwargs)


# ---------- ① plan_delegation 基本口径 ----------

class TestPlanBasics:
    def test_empty_task_raises(self):
        with pytest.raises(ValueError):
            delegation.plan_delegation(parent_caps(["*"]), task("   "))

    def test_none_capabilities_inherits_parent_verbatim(self):
        parent = {"tools": ["file.*"], "max_risk": "low", "expires_at": "2030-01-01T00:00:00Z", "scope": "trusted"}
        plan = delegation.plan_delegation(parent, task("fix the bug"))
        assert plan.status == delegation.PLAN_READY
        assert plan.capabilities["tools"] == ["file.*"]
        assert plan.capabilities["max_risk"] == "low"
        assert plan.capabilities["expires_at"] == "2030-01-01T00:00:00Z"
        assert plan.capabilities["scope"] == "trusted"

    def test_star_inherits_parent_tools(self):
        parent = {"tools": ["file.*", "shell"]}
        plan = delegation.plan_delegation(
            parent, task("x", capabilities={"tools": ["*"]})
        )
        assert plan.status == delegation.PLAN_READY
        assert plan.capabilities["tools"] == ["file.*", "shell"]

    def test_specific_tool_intersection(self):
        parent = {"tools": ["file.*"]}
        plan = delegation.plan_delegation(
            parent, task("x", capabilities={"tools": ["file.read"]})
        )
        assert plan.status == delegation.PLAN_READY
        assert plan.capabilities["tools"] == ["file.read"]


# ---------- ②③ 越权 / 交集空 ----------

class TestRejections:
    def test_overreach_named(self):
        plan = delegation.plan_delegation(
            parent_caps(["file.*"]), task("x", capabilities={"tools": ["shell"]})
        )
        assert plan.status == delegation.STATUS_REJECTED
        assert plan.reason == "tool_not_permitted:shell"

    def test_empty_intersection(self):
        plan = delegation.plan_delegation(
            parent_caps(["file.*"]), task("x", capabilities={"tools": ["net.*"]})
        )
        assert plan.status == delegation.STATUS_REJECTED
        assert plan.reason == "capability_intersection_empty"


# ---------- ④ 能力块读不出来 ----------

class TestUnreadable:
    def test_parent_unreadable(self):
        plan = delegation.plan_delegation({"tools": 123}, task("x"))
        assert plan.status == delegation.STATUS_REJECTED
        assert plan.reason == "capability_unreadable"
        assert len(plan.tightenings) == 1
        t = plan.tightenings[0]
        assert t["action"] == "deny"
        assert t["reason"] == "capability_problems"
        assert t["source"] == "parent"
        assert t["detail"]["problems"]

    def test_request_unreadable(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"]), task("x", capabilities={"tools": 123})
        )
        assert plan.status == delegation.STATUS_REJECTED
        assert plan.reason == "capability_unreadable"
        assert plan.tightenings[0]["source"] == "request"
        assert plan.tightenings[0]["detail"]["problems"]


# ---------- ⑤ max_risk 三档 ----------

class TestMaxRisk:
    def test_request_wider_tightens_to_parent(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"], max_risk="low"),
            task("x", capabilities={"tools": ["*"], "max_risk": "high"}),
        )
        assert plan.capabilities["max_risk"] == "low"

    def test_request_stricter_wins(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"], max_risk="high"),
            task("x", capabilities={"tools": ["*"], "max_risk": "low"}),
        )
        assert plan.capabilities["max_risk"] == "low"

    def test_parent_inherit_uses_request(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"], max_risk="inherit"),
            task("x", capabilities={"tools": ["*"], "max_risk": "medium"}),
        )
        assert plan.capabilities["max_risk"] == "medium"


# ---------- ⑥ expires_at ----------

class TestExpiresAt:
    def test_both_present_earlier_wins(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"], expires_at="2030-06-01T00:00:00Z"),
            task("x", capabilities={"tools": ["*"], "expires_at": "2030-01-01T00:00:00Z"}),
        )
        assert plan.capabilities["expires_at"] == "2030-01-01T00:00:00Z"

    def test_one_empty_takes_other(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"], expires_at="2031-01-01T00:00:00Z"),
            task("x", capabilities={"tools": ["*"]}),
        )
        assert plan.capabilities["expires_at"] == "2031-01-01T00:00:00Z"


# ---------- ⑦ scope ----------

class TestScope:
    def test_parent_untrusted_propagates(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"], scope="untrusted"),
            task("x", capabilities={"tools": ["*"], "scope": "trusted"}),
        )
        assert plan.capabilities["scope"] == "untrusted"


# ---------- ⑧ 预算 ----------

class TestBudget:
    def test_none_uses_parent(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"]), task("x"), parent_budget=delegation.Budget(5, 600)
        )
        assert plan.budget.steps == 5
        assert plan.budget.tokens == 600

    def test_request_larger_tightens_to_parent(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"]),
            task("x", budget=delegation.Budget(100, 100000)),
            parent_budget=delegation.Budget(5, 600),
        )
        assert plan.budget.steps == 5
        assert plan.budget.tokens == 600

    def test_request_smaller_kept(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"]),
            task("x", budget=delegation.Budget(2, 300)),
            parent_budget=delegation.Budget(5, 600),
        )
        assert plan.budget.steps == 2
        assert plan.budget.tokens == 300

    def test_zero_steps_raises(self):
        with pytest.raises(ValueError):
            delegation.Budget(0, 1)

    def test_zero_tokens_raises(self):
        with pytest.raises(ValueError):
            delegation.Budget(1, 0)


# ---------- ⑨ task_id / agent_id ----------

class TestIds:
    def test_explicit_task_id_unchanged(self):
        plan = delegation.plan_delegation(
            parent_caps(["*"]), task("x", agent_type="worker"), task_id="abcd1234ef"
        )
        assert plan.task_id == "abcd1234ef"
        assert plan.agent_id == "worker-abcd1234"

    def test_generated_task_id_nonempty_and_distinct(self):
        a = delegation.plan_delegation(parent_caps(["*"]), task("x"))
        b = delegation.plan_delegation(parent_caps(["*"]), task("x"))
        assert a.task_id
        assert b.task_id
        assert a.task_id != b.task_id
        assert a.agent_id == f"{a.agent_type}-{a.task_id[:8]}"
        assert b.agent_id == f"{b.agent_type}-{b.task_id[:8]}"


# ---------- ⑩ 不改传入 dict ----------

class TestNoMutation:
    def test_parent_dict_untouched(self):
        parent = {"tools": ["file.*"], "max_risk": "low"}
        snapshot = json.loads(json.dumps(parent))
        delegation.plan_delegation(parent, task("x"))
        delegation.plan_delegation(parent, task("y", capabilities={"tools": ["file.read"]}))
        assert parent == snapshot

    def test_request_dict_untouched(self):
        parent = {"tools": ["*"]}
        req_caps = {"tools": ["file.read"], "max_risk": "high"}
        snapshot = json.loads(json.dumps(req_caps))
        delegation.plan_delegation(parent, task("x", capabilities=req_caps))
        assert req_caps == snapshot


# ---------- delegate：正常 / 失败 / 崩溃 / dict / 预算 / 无自报 ----------

class TestDelegateHappy:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        bus = EventBus()
        calls = []

        async def fake_spawn(plan):
            calls.append(plan)
            return delegation.ChildReport()

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn, bus=bus, task_id="t0001"
        )
        assert len(calls) == 1
        assert result.status == "completed"
        assert result.events == ("task.assigned", "task.completed")
        assert result.task_id == "t0001"
        assert result.usage_reported is False
        history = bus.get_history()
        types = [e.event_type for e in history]
        assert "task.assigned" in types and "task.completed" in types
        assert types.index("task.assigned") < types.index("task.completed")
        audit = result.audit
        for key in (
            "task_id", "agent_id", "agent_type", "parent_session", "status",
            "reason", "error", "steps_used", "tokens_used", "usage_reported",
            "budget", "capabilities", "tightenings", "pid", "log_path",
        ):
            assert key in audit
        assert audit["status"] == "completed"
        assert audit["budget"] == {"steps": 20, "tokens": 20000}
        assert audit["task_id"] == "t0001"

    @pytest.mark.asyncio
    async def test_spawn_failed(self):
        bus = EventBus()

        async def fake_spawn(plan):
            return delegation.ChildReport(status="failed", error="child died")

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn, bus=bus
        )
        assert result.status == delegation.STATUS_FAILED
        assert result.events == ("task.assigned", "task.failed")
        history = bus.get_history()
        assert history[-1].event_type == "task.failed"
        assert history[-1].payload["status"] == "failed"

    @pytest.mark.asyncio
    async def test_spawn_crash_not_raised(self):
        bus = EventBus()

        async def fake_spawn(plan):
            raise RuntimeError("boom")

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn, bus=bus
        )
        assert result.status == delegation.STATUS_CRASHED
        assert "boom" in result.error
        assert result.events == ("task.assigned", "task.failed")

    @pytest.mark.asyncio
    async def test_dict_report_adapted(self):
        async def fake_spawn(plan):
            return {"status": "completed", "steps_used": 3}

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn, bus=None
        )
        assert result.status == delegation.STATUS_COMPLETED
        assert result.steps_used == 3
        assert result.usage_reported is True
        assert result.events == ()


# ---------- ⑮ 预算耗尽 ----------

class TestBudgetExhausted:
    @pytest.mark.asyncio
    async def test_steps_over(self):
        async def fake_spawn(plan):
            return delegation.ChildReport(
                status="completed", steps_used=plan.budget.steps + 1
            )

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn, bus=None
        )
        assert result.status == delegation.STATUS_BUDGET_EXHAUSTED
        assert result.usage_reported is True

    @pytest.mark.asyncio
    async def test_tokens_over(self):
        async def fake_spawn(plan):
            return delegation.ChildReport(
                status="completed", tokens_used=plan.budget.tokens + 1
            )

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn, bus=None
        )
        assert result.status == delegation.STATUS_BUDGET_EXHAUSTED


# ---------- ⑯ 用量没自报 ----------

class TestNoUsageReported:
    @pytest.mark.asyncio
    async def test_not_reported(self):
        async def fake_spawn(plan):
            return delegation.ChildReport(status="completed")

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn, bus=None
        )
        assert result.usage_reported is False
        assert result.status == "completed"


# ---------- ⑰ 被拒路径：不 spawn、不发事件 ----------

class TestRejectedPath:
    @pytest.mark.asyncio
    async def test_rejected_no_spawn_no_events(self):
        bus = EventBus()
        calls = []

        async def fake_spawn(plan):
            calls.append(plan)
            return delegation.ChildReport()

        result = await delegation.delegate(
            parent_caps(["file.*"]),
            task("x", capabilities={"tools": ["shell"]}),
            spawn=fake_spawn,
            bus=bus,
        )
        assert result.status == delegation.STATUS_REJECTED
        assert result.reason == "tool_not_permitted:shell"
        assert calls == []                      # spawn 一次都没被调用
        assert result.events == ()
        history = bus.get_history()
        assert [e for e in history if e.event_type.startswith("task.")] == []


# ---------- ⑱ bus=None ----------

class TestNoBus:
    @pytest.mark.asyncio
    async def test_bus_none(self):
        async def fake_spawn(plan):
            return delegation.ChildReport()

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn, bus=None
        )
        assert result.status == "completed"
        assert result.events == ()


# ---------- ⑲ 真 spawn（Linux 专用）----------

REAL_SCRIPT = '''
import os, time
print("BUDGET=" + os.environ["TRIMUM_AGENT_BUDGET_STEPS"], flush=True)
time.sleep(0.6)
print("DONE", flush=True)
'''


@pytest.mark.skipif(os.name != "posix", reason="real spawn is Linux-only")
class TestRealSpawn:
    @pytest.mark.asyncio
    async def test_real_spawn_lifecycle(self, tmp_path):
        root = tmp_path / "agents"
        (root / "coder").mkdir(parents=True)
        (root / "coder" / "main.py").write_text(REAL_SCRIPT, encoding="utf-8")

        plan = delegation.plan_delegation(
            parent_caps(["*"]), task("real task"), parent_budget=delegation.Budget(7, 700)
        )
        spawn = delegation.default_spawn(agents_root=root)
        result = await delegation.delegate(
            parent_caps(["*"]),
            task("real task"),
            spawn=spawn,
            bus=None,
            parent_budget=delegation.Budget(7, 700),
            task_id=plan.task_id,
        )
        try:
            assert result.status == "completed"
            pid = result.audit["pid"]
            assert isinstance(pid, int) and pid > 0
            log_path = Path(result.audit["log_path"])

            def log_has(text):
                try:
                    return text in log_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return False

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if log_has(f"BUDGET={plan.budget.steps}") and log_has("DONE"):
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail(f"child did not finish in time: {log_path}")
            assert log_has("BUDGET=7")
            assert log_has("DONE")
        finally:
            if result.audit.get("pid"):
                try:
                    os.kill(result.audit["pid"], signal.SIGTERM)
                except Exception:
                    pass


# ---------- ⑳ 红线静态检查 ----------

class TestRedlineStatic:
    @pytest.mark.asyncio
    async def test_no_subprocess_literals_and_lazy_launcher(self):
        here = os.path.dirname(os.path.abspath(__file__))
        source = Path(here, "..", "src", "trimum_core", "delegation.py").read_text(
            encoding="utf-8"
        )
        assert "subprocess" not in source
        assert "popen" not in source
        assert "os.system" not in source
        # 顶层不许 import agent_launcher（只许延迟 import 到 default_spawn 里）
        assert not any(
            line.startswith("import") and "agent_launcher" in line
            for line in source.splitlines()
        )
        # 延迟 import 确实存在（在 default_spawn 闭包里，缩进的 from ... import）
        assert "from . import agent_launcher" in source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ---------- 接线片：usage_reported 自报优先 + default_spawn 真用 run_agent ----------

class TestUsageReportedPassThrough:
    @pytest.mark.asyncio
    async def test_usage_reported_pass_through(self):
        async def fake_spawn_true(plan):
            return delegation.ChildReport(
                status="completed", steps_used=1, tokens_used=1, usage_reported=True
            )

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn_true, bus=None
        )
        assert result.usage_reported is True

        async def fake_spawn_false(plan):
            # 矛盾输入：自报 False 优先于「有 steps 就推断 True」的旧口径
            return delegation.ChildReport(
                status="completed", steps_used=1, usage_reported=False
            )

        result = await delegation.delegate(
            parent_caps(["*"]), task("x"), spawn=fake_spawn_false, bus=None
        )
        assert result.usage_reported is False

    def test_child_report_usage_reported_default_none(self):
        assert delegation.ChildReport().usage_reported is None

        async def fake_spawn_infer(plan):
            return delegation.ChildReport(status="completed", steps_used=1)

        import asyncio as _asyncio

        async def _runner():
            return await delegation.delegate(
                parent_caps(["*"]), task("x"), spawn=fake_spawn_infer, bus=None
            )

        result = _asyncio.run(_runner())
        assert result.usage_reported is True


class TestDefaultSpawnWiring:
    @pytest.mark.asyncio
    async def test_default_spawn_uses_run_agent(self, monkeypatch):
        import trimum_core.agent_launcher as agent_launcher

        calls = []

        async def fake_run_agent(*args, **kwargs):
            calls.append((args, kwargs))
            return agent_launcher.AgentRun(
                launch=agent_launcher.LaunchResult(pid=4242, log_path=Path("/tmp/x.log")),
                steps_used=3,
                tokens_used=30,
                usage_reported=True,
            )

        monkeypatch.setattr(agent_launcher, "run_agent", fake_run_agent)
        spawn = delegation.default_spawn(agents_root=None, socket_path=None)
        plan = delegation.plan_delegation(
            parent_caps(["*"]), task("x"), parent_budget=delegation.Budget(9, 900)
        )

        report = await spawn(plan)

        assert len(calls) == 1
        args, kwargs = calls[0]
        assert kwargs.get("budget") is plan.budget
        assert kwargs["extra_env"][delegation.ENV_BUDGET_STEPS] == str(plan.budget.steps)
        assert report.pid == 4242
        assert report.steps_used == 3
        assert report.tokens_used == 30
        assert report.usage_reported is True
        assert report.status == delegation.STATUS_COMPLETED

        async def fake_run_agent_failed(*args, **kwargs):
            return agent_launcher.AgentRun(
                launch=agent_launcher.LaunchResult(
                    pid=4242, error="agent exited immediately (code=1)"
                ),
                returncode=1,
            )

        monkeypatch.setattr(agent_launcher, "run_agent", fake_run_agent_failed)
        report = await spawn(plan)
        assert report.status == delegation.STATUS_FAILED
        assert report.error

    @pytest.mark.asyncio
    async def test_default_spawn_timeout_maps_to_failed(self, monkeypatch):
        import trimum_core.agent_launcher as agent_launcher

        async def fake_run_agent(*args, **kwargs):
            return agent_launcher.AgentRun(
                launch=agent_launcher.LaunchResult(pid=1),
                timed_out=True,
                terminated=True,
            )

        monkeypatch.setattr(agent_launcher, "run_agent", fake_run_agent)
        spawn = delegation.default_spawn(agents_root=None, timeout=7.0)
        plan = delegation.plan_delegation(
            parent_caps(["*"]), task("x"), parent_budget=delegation.Budget(9, 900)
        )
        report = await spawn(plan)
        assert report.status == delegation.STATUS_FAILED
        assert "timed out" in report.error
