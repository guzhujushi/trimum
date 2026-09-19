"""AgentManager resource-controller wiring tests."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.agent_manager import AgentManager
from trimum_core.models import SpawnRequest
from trimum_core.resource_controller import ResourceLimits


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
