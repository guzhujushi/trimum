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


@pytest.mark.asyncio
async def test_spawn_sets_resource_limits():
    controller = RecordingController()
    manager = AgentManager(resource_controller=controller)

    resp = await manager.spawn(SpawnRequest(
        agent_type="demo",
        config={"resource_limits": {"max_memory_mb": 128, "max_cpu_percent": 25}},
    ))

    limits = controller.limits.get(resp.agent_id)
    assert limits is not None
    assert limits.max_memory_mb == 128.0
    assert limits.max_cpu_percent == 25.0
    assert controller.applied == []
