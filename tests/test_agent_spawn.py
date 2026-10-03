"""子 Agent 真实 spawn + cgroup 绑定测试（Phase 3 收尾 P1）。"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.agent_launcher import (
    agents_root,
    launch_agent,
    resolve_agent_script,
)
from trimum_core.agent_manager import AgentManager
from trimum_core.agent_runtime import AgentRuntime
from trimum_core.event_bus import EventBus
from trimum_core.models import AgentStatus, SpawnRequest
from trimum_core.resource_controller import ResourceLimits

SLEEPER = '''
import os, signal, sys, time

marker = os.environ.get("TRIMUM_TEST_MARKER")
if marker:
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(os.environ.get("TRIMUM_AGENT_ID", ""))

try:
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
except Exception:
    pass

while True:
    time.sleep(0.05)
'''

CRASHER = '''
import sys
print("boom", file=sys.stderr)
sys.exit(3)
'''


class RecordingController:
    def __init__(self):
        self.limits = {}
        self.applied = []

    async def get_usage(self, agent_id):
        raise NotImplementedError

    async def check_limits(self, agent_id, usage=None):
        raise NotImplementedError

    async def set_limits(self, agent_id, limits):
        self.limits[agent_id] = limits

    async def get_limits(self, agent_id):
        return ResourceLimits()

    async def apply_cgroup(self, agent_id, pid, limits):
        self.applied.append((agent_id, pid, limits))


def write_agent(root, agent_type, body=SLEEPER):
    script = root / agent_type / "main.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")
    return script


def alive(pid):
    import psutil

    return psutil.pid_exists(pid)


class TestLauncher:
    def test_agents_root_override(self, tmp_path):
        assert agents_root(tmp_path) == tmp_path

    def test_resolve_missing_script(self, tmp_path):
        assert resolve_agent_script("nope", tmp_path) is None

    def test_resolve_existing_script(self, tmp_path):
        script = write_agent(tmp_path, "demo")
        assert resolve_agent_script("demo", tmp_path) == script

    @pytest.mark.asyncio
    async def test_launch_without_script_returns_empty(self, tmp_path):
        result = await launch_agent("a1", "ghost", base=tmp_path)
        assert result.process is None
        assert result.script is None

    @pytest.mark.asyncio
    async def test_launch_passes_env_contract(self, tmp_path):
        marker = tmp_path / "marker.txt"
        write_agent(tmp_path, "demo")

        result = await launch_agent(
            "agent-42", "demo", base=tmp_path, extra_env={"TRIMUM_TEST_MARKER": str(marker)}
        )
        try:
            assert result.pid and alive(result.pid)
            await asyncio.sleep(0.3)
            assert marker.read_text(encoding="utf-8") == "agent-42"
        finally:
            result.process.terminate()
            await result.process.wait()

    @pytest.mark.asyncio
    async def test_launch_detects_immediate_exit(self, tmp_path):
        write_agent(tmp_path, "bad", CRASHER)
        result = await launch_agent("a1", "bad", base=tmp_path)

        assert result.error is not None
        assert "exited immediately" in result.error
        assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_launch_writes_output_to_log_file(self, tmp_path):
        """子进程输出落日志文件（不走 PIPE，避免写满管道把 Agent 卡死）。"""
        write_agent(
            tmp_path,
            "chatty",
            'import sys, time\nprint("hello-log", flush=True)\ntime.sleep(5)\n',
        )
        result = await launch_agent("chatty-1", "chatty", base=tmp_path)

        try:
            assert result.process is not None
            assert result.process.stdout is None  # 不再持有管道
            assert result.log_path is not None and result.log_path.is_file()
            await asyncio.sleep(0.3)
            assert "hello-log" in result.log_path.read_text(encoding="utf-8")
        finally:
            result.process.terminate()
            await result.process.wait()

    @pytest.mark.asyncio
    async def test_launch_error_summary_only_covers_this_run(self, tmp_path):
        """同一 agent_id 反复启动时，摘要只取本次写入的区间。"""
        write_agent(tmp_path, "bad", CRASHER)
        first = await launch_agent("repeat", "bad", base=tmp_path)
        second = await launch_agent("repeat", "bad", base=tmp_path)

        assert first.log_path == second.log_path
        assert "boom" in second.error
        assert second.error.count("boom") == 1


class TestAgentManagerSpawn:
    @pytest.mark.asyncio
    async def test_spawn_starts_real_process_and_binds_cgroup(self, tmp_path):
        write_agent(tmp_path, "demo")
        controller = RecordingController()
        manager = AgentManager(resource_controller=controller, agents_root=str(tmp_path))

        resp = await manager.spawn(SpawnRequest(agent_type="demo", agent_id="demo-1"))

        try:
            assert resp.status == AgentStatus.RUNNING
            assert resp.pid and alive(resp.pid)
            assert controller.applied and controller.applied[0][0] == "demo-1"
            assert controller.applied[0][1] == resp.pid
        finally:
            await manager.stop("demo-1")

        await asyncio.sleep(0.3)
        assert not alive(resp.pid)

    @pytest.mark.asyncio
    async def test_spawn_without_script_only_registers(self, tmp_path):
        controller = RecordingController()
        manager = AgentManager(resource_controller=controller, agents_root=str(tmp_path))

        resp = await manager.spawn(SpawnRequest(agent_type="ghost"))

        assert resp.status == AgentStatus.INITIALIZED
        assert resp.pid is None
        assert controller.applied == []
        assert "no agent script installed" in resp.message

    @pytest.mark.asyncio
    async def test_spawn_reports_failed_when_script_crashes(self, tmp_path):
        write_agent(tmp_path, "bad", CRASHER)
        manager = AgentManager(agents_root=str(tmp_path))

        resp = await manager.spawn(SpawnRequest(agent_type="bad"))

        assert resp.status == AgentStatus.FAILED
        assert "exited immediately" in resp.message

    @pytest.mark.asyncio
    async def test_stop_marks_agent_stopped(self, tmp_path):
        write_agent(tmp_path, "demo")
        manager = AgentManager(agents_root=str(tmp_path))
        resp = await manager.spawn(SpawnRequest(agent_type="demo"))

        try:
            assert resp.status == AgentStatus.RUNNING
        finally:
            assert await manager.stop(resp.agent_id) is True
        info = await manager.get(resp.agent_id)
        assert info.status == AgentStatus.STOPPED


class TestAgentRuntimeSpawn:
    @pytest.mark.asyncio
    async def test_start_agent_spawns_process(self, tmp_path):
        write_agent(tmp_path, "demo")
        runtime = AgentRuntime(
            socket_path=str(tmp_path / "agent.sock"),
            event_bus=EventBus(),
            agents_root=str(tmp_path),
        )

        assert await runtime.start_agent("a1", "demo") is True
        process = runtime._agents["a1"]
        try:
            assert await runtime.get_status("a1") == "running"
            assert process is not None and alive(process.pid)
        finally:
            assert await runtime.stop_agent("a1") is True

        await asyncio.sleep(0.3)
        assert not alive(process.pid)
        assert await runtime.get_status("a1") is None

    @pytest.mark.asyncio
    async def test_start_agent_without_script_registers_only(self, tmp_path):
        runtime = AgentRuntime(
            socket_path=str(tmp_path / "agent.sock"),
            event_bus=EventBus(),
            agents_root=str(tmp_path),
        )
        assert await runtime.start_agent("ghost", "ghost-type") is True
        assert runtime._agents["ghost"] is None
        assert await runtime.get_status("ghost") == "running"