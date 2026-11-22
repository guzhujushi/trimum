"""AgentManager resource-controller wiring tests."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.agent_manager import AgentManager
from trimum_core.models import SpawnRequest
from trimum_core.resource_controller import CgroupApplyResult, ResourceLimits


class RecordingController:
    """Minimal ResourceController double for wiring assertions."""

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


class UnenforcedController(RecordingController):
    async def apply_cgroup(self, agent_id, pid, limits):
        self.applied.append((agent_id, pid, limits))
        return CgroupApplyResult(False, False, "cgroup unavailable")


class PreparedController(RecordingController):
    """Controller double that proves hard pre-spawn preparation was used."""

    def __init__(self, marker):
        super().__init__()
        self.marker = marker
        self.prepared = []
        self.killed = []

    async def prepare_cgroup(self, agent_id, limits):
        self.prepared.append((agent_id, limits))
        return CgroupApplyResult(
            applied=True,
            verified=None,
            limits_verified=True,
            detail="fake limits verified before spawn",
        )

    def preexec_hook(self, agent_id):
        target = self.marker

        def _hook():
            import os

            fd = os.open(target, os.O_WRONLY | os.O_CREAT, 0o600)
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)

        return _hook

    async def apply_cgroup(self, agent_id, pid, limits):
        self.applied.append((agent_id, pid, limits))
        return CgroupApplyResult(
            applied=True,
            verified=True,
            limits_verified=True,
            detail="fake pid and limits verified after spawn",
        )

    async def kill_cgroup(self, agent_id):
        self.killed.append(agent_id)
        return True


class PostSpawnFailureController(PreparedController):
    async def apply_cgroup(self, agent_id, pid, limits):
        self.applied.append((agent_id, pid, limits))
        return CgroupApplyResult(
            applied=True,
            verified=True,
            limits_verified=False,
            detail="kernel changed memory.max after spawn",
        )


SLEEPER = "import time\nwhile True: time.sleep(0.05)\n"


def write_agent(root, agent_type):
    script = root / agent_type / "main.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(SLEEPER, encoding="utf-8")
    return script


@pytest.mark.asyncio
async def test_spawn_sets_resource_limits(tmp_path):
    """没有 Agent 脚本时只登记：限额照常记录，但不去绑 cgroup。

    ``agents_root`` 必须指向 tmp：否则会读到真实用户目录里的 Agent 脚本，
    测试结果随宿主环境变化（真机上就因此翻车过一次）。
    """
    controller = RecordingController()
    manager = AgentManager(resource_controller=controller, agents_root=str(tmp_path))

    resp = await manager.spawn(SpawnRequest(
        agent_type="demo",
        config={"resource_limits": {"max_memory_mb": 128, "max_cpu_percent": 25}},
    ))

    limits = controller.limits.get(resp.agent_id)
    assert limits is not None
    assert limits.max_memory_mb == 128.0
    assert limits.max_cpu_percent == 25.0
    assert controller.applied == []


@pytest.mark.asyncio
async def test_spawn_applies_cgroup_with_real_pid(tmp_path):
    """有脚本时真实起进程：cgroup 绑的是真实 PID（P1-e 之后的新语义）。"""
    write_agent(tmp_path, "demo")
    controller = RecordingController()
    manager = AgentManager(resource_controller=controller, agents_root=str(tmp_path))

    resp = await manager.spawn(SpawnRequest(
        agent_type="demo",
        config={"resource_limits": {"max_memory_mb": 128, "max_cpu_percent": 25}},
    ))

    try:
        assert resp.pid is not None
        assert controller.applied, "有脚本时应把真实 PID 绑到 cgroup"
        applied_agent_id, applied_pid, applied_limits = controller.applied[0]
        assert applied_agent_id == resp.agent_id
        assert applied_pid == resp.pid
        assert applied_limits.max_memory_mb == 128.0
    finally:
        await manager.stop(resp.agent_id)


@pytest.mark.asyncio
async def test_hard_enforcement_failure_refuses_to_keep_agent_running(tmp_path):
    """hard 模式：无法在启动前准备 cgroup → 根本不启动进程。"""
    write_agent(tmp_path, "demo")
    controller = UnenforcedController()
    manager = AgentManager(resource_controller=controller, agents_root=str(tmp_path))

    resp = await manager.spawn(SpawnRequest(
        agent_type="demo",
        config={"resource_enforcement": "hard"},
    ))

    assert resp.status.value == "failed"
    assert "resource enforcement required" in resp.message
    assert resp.pid is None
    assert controller.applied == []


@pytest.mark.asyncio
async def test_hard_enforcement_prepares_before_spawn_and_cleans_cgroup(tmp_path):
    """hard：准备 → 子进程 preexec 入组 → 启动后读回验证 → stop 清进程树。"""
    write_agent(tmp_path, "demo")
    marker = tmp_path / "preexec.pid"
    controller = PreparedController(str(marker))
    manager = AgentManager(resource_controller=controller, agents_root=str(tmp_path))

    resp = await manager.spawn(SpawnRequest(
        agent_type="demo",
        config={"resource_enforcement": "hard"},
    ))

    try:
        assert resp.status.value == "running"
        assert resp.pid is not None
        assert controller.prepared, "hard 必须先准备并读回 cgroup 限额"
        assert marker.read_text(encoding="ascii") == str(resp.pid)
        assert controller.applied and controller.applied[0][1] == resp.pid
    finally:
        await manager.stop(resp.agent_id)

    assert controller.killed == [resp.agent_id]
    assert not _pid_alive(resp.pid)


@pytest.mark.asyncio
async def test_hard_post_spawn_verification_failure_terminates_process_tree(tmp_path):
    """hard：启动后限额读回不一致 → 终止主进程并清理整个 cgroup。"""
    write_agent(tmp_path, "demo")
    marker = tmp_path / "preexec.pid"
    controller = PostSpawnFailureController(str(marker))
    manager = AgentManager(resource_controller=controller, agents_root=str(tmp_path))

    resp = await manager.spawn(SpawnRequest(
        agent_type="demo",
        config={"resource_enforcement": "hard"},
    ))

    assert resp.status.value == "failed"
    assert "resource enforcement required" in resp.message
    assert resp.pid is not None
    assert not _pid_alive(resp.pid)
    assert controller.killed == [resp.agent_id]


@pytest.mark.asyncio
async def test_soft_enforcement_failure_is_reported_but_keeps_running(tmp_path):
    """soft 模式：允许降级，但 spawn 结果必须显式标注降级。"""
    write_agent(tmp_path, "demo")
    controller = UnenforcedController()
    manager = AgentManager(resource_controller=controller, agents_root=str(tmp_path))

    resp = await manager.spawn(SpawnRequest(agent_type="demo"))

    try:
        assert resp.status.value == "running"
        assert "resource limits degraded" in resp.message
    finally:
        await manager.stop(resp.agent_id)


def _pid_alive(pid: int) -> bool:
    import psutil

    return psutil.pid_exists(pid)
