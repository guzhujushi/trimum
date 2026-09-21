"""WorkflowListener 接线（2026-09-21，W1 遗留步骤 C）的回归测试。

这条链以前整条是摆设：``event.transform.completed`` **没有生产者**（``WorkflowListener`` 从未被
实例化）、``workflow.trigger`` 也没有消费者之外的东西，而 ``_request_confirm`` 在没有确认回调时
**默认放行**。这里钉住四件事：

1. :meth:`WorkflowListener.submit` 是 ``event.transform.completed`` 的唯一生产者；
2. 三段式决策（高 → ``workflow.trigger``；中 → 问一次；低 → Planner）走的是真事件；
3. **没有确认回调 = 拒绝**（不放行）；
4. 订阅表里只有真类型（``task.task.completed`` 那个拼错的死订阅已删）。
"""

from __future__ import annotations

import asyncio

import pytest
import yaml

from trimum_core.event_bus import EventBus, NAMESPACE_EVENT
from trimum_core.models import SystemEvent
from trimum_core.transform_agent import TransformResult
from trimum_core.workflow_listener import WorkflowListener
from trimum_core.workflow_runtime import WorkflowRuntime


class FakeTransform:
    """TransformAgent 的替身：不碰 LLM，只按给定结果回话。"""

    def __init__(self, result: TransformResult | None = None) -> None:
        self._result = result or tarl_result()
        self.calls: list[str] = []

    async def translate_async(self, instruction: str) -> TransformResult:
        self.calls.append(instruction)
        return self._result


class FakeResponse:
    """网关返回值的替身（只给 listener 会读的那几个字段）。"""

    def __init__(self, status: str = "ok", **extra) -> None:
        self.status = status
        self.exit_code = extra.pop("exit_code", 0)
        self.output = extra.pop("output", "hi")
        self.risk = extra.pop("risk", "low")
        for key, value in extra.items():
            setattr(self, key, value)


class FakeGateway:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.requests: list[object] = []
        self._response = response or FakeResponse()

    async def execute(self, request):
        self.requests.append(request)
        return self._response


class FakePlanner:
    """Planner 的替身：返回一个带 name / nodes 的假 workflow。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, request: str, context: dict | None = None):
        self.calls.append(request)

        class Planned:
            name = "planned-from-intent"
            nodes = [1, 2]

        return Planned()


class Recorder:
    """把总线上出现的事件记下来（按顺序）。"""

    def __init__(self) -> None:
        self.events: list[SystemEvent] = []

    def __call__(self, event: SystemEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [event.event_type for event in self.events]

    def payloads(self, suffix: str) -> list[dict]:
        return [event.payload for event in self.events if event.event_type.endswith(suffix)]


def tarl_result(
    tarl: str = "cmd:restart_nginx user:guzhu",
    confidence: float = 0.9,
    original: str = "重启 nginx",
) -> TransformResult:
    return TransformResult(tarl=tarl, confidence=confidence, original=original, output_type="tarl")


def shell_result(
    command: str = "echo hi",
    confidence: float = 0.9,
    original: str = "打个招呼",
) -> TransformResult:
    return TransformResult(
        tarl=f"cmd:{command}",
        confidence=confidence,
        original=original,
        shell_command=command,
        output_type="shell",
    )


def build_listener(bus: EventBus, *, transform=None, gateway=None, planner=None, **kwargs):
    return WorkflowListener(
        bus,
        transform or FakeTransform(),
        gateway or FakeGateway(),
        planner,
        **kwargs,
    )


class TestSubscriptions:
    @pytest.mark.asyncio
    async def test_only_real_event_types_are_subscribed(self):
        bus = EventBus()
        listener = build_listener(bus)
        await listener.start()

        assert set(bus._subscribers) == {
            f"{NAMESPACE_EVENT}transform.completed",
            f"{NAMESPACE_EVENT}planner.task_created",
            f"{NAMESPACE_EVENT}system.status",
        }
        # 拼错的 task.task.* 死订阅（以及给它喂数据的 _pending_sub_tasks）已删
        assert not [pattern for pattern in bus._subscribers if "task.task" in pattern]

    @pytest.mark.asyncio
    async def test_stop_makes_the_listener_deaf(self):
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe(f"{NAMESPACE_EVENT}workflow.trigger", recorder)
        listener = build_listener(bus, transform=FakeTransform(tarl_result(confidence=0.95)))
        await listener.start()
        await listener.stop()

        await listener.submit("重启 nginx")
        await bus.wait_for_handlers()

        assert recorder.events == []


class TestSubmit:
    @pytest.mark.asyncio
    async def test_submit_is_the_producer_of_transform_completed(self):
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe(f"{NAMESPACE_EVENT}transform.completed", recorder)
        listener = build_listener(bus)
        await listener.start()

        result = await listener.submit("重启 nginx")
        await bus.wait_for_handlers()

        assert result.tarl == "cmd:restart_nginx user:guzhu"
        assert recorder.types() == [f"{NAMESPACE_EVENT}transform.completed"]
        payload = recorder.payloads("transform.completed")[0]
        assert payload["result"]["original"] == "重启 nginx"
        assert payload["result"]["output_type"] == "tarl"
        assert recorder.events[0].source == "transform-agent"


class TestThreeStageDecision:
    @pytest.mark.asyncio
    async def test_high_confidence_goes_straight_to_workflow_trigger(self):
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe(f"{NAMESPACE_EVENT}workflow.trigger", recorder)
        listener = build_listener(bus, transform=FakeTransform(tarl_result(confidence=0.9)))
        await listener.start()

        await listener.submit("重启 nginx")
        await bus.wait_for_handlers()

        payload = recorder.payloads("workflow.trigger")[0]
        assert payload["decision"] == "high"
        assert payload["cmd"] == "restart_nginx"
        assert payload["tarl"] == "cmd:restart_nginx user:guzhu"
        assert payload["original"] == "重启 nginx"
        assert isinstance(payload["timestamp"], float)

    @pytest.mark.asyncio
    async def test_mid_confidence_without_a_confirm_callback_is_denied(self):
        """红线：确认缺位 ≠ 放行。没有回调就没人能同意，必须拒绝。"""
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe(f"{NAMESPACE_EVENT}workflow.trigger", recorder)
        listener = build_listener(bus, transform=FakeTransform(tarl_result(confidence=0.5)))
        await listener.start()

        # 一个回调都不注册 —— 这正是「确认通道还没接上」时的状态
        assert listener._confirm_callbacks == []

        await listener.submit("重启 nginx")
        await bus.wait_for_handlers()

        assert recorder.events == []

    @pytest.mark.asyncio
    async def test_mid_confidence_asks_the_confirm_callback(self):
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe(f"{NAMESPACE_EVENT}workflow.trigger", recorder)
        listener = build_listener(bus, transform=FakeTransform(tarl_result(confidence=0.5)))
        asked: list[tuple] = []

        async def confirm(original, tarl, confidence):
            asked.append((original, tarl, confidence))
            return True

        listener.on_confirm(confirm)
        await listener.start()

        await listener.submit("重启 nginx")
        await bus.wait_for_handlers()

        assert len(asked) == 1
        assert asked[0][0] == "重启 nginx"
        assert recorder.payloads("workflow.trigger")[0]["decision"] == "confirmed"

    @pytest.mark.asyncio
    async def test_mid_confidence_rejected_by_the_user_stays_unexecuted(self):
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe(f"{NAMESPACE_EVENT}workflow.trigger", recorder)
        listener = build_listener(bus, transform=FakeTransform(tarl_result(confidence=0.5)))
        listener.on_confirm(lambda original, tarl, confidence: False)
        await listener.start()

        await listener.submit("重启 nginx")
        await bus.wait_for_handlers()

        assert recorder.events == []

    @pytest.mark.asyncio
    async def test_low_confidence_goes_to_the_planner(self):
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe(f"{NAMESPACE_EVENT}planner.workflow_created", recorder)
        planner = FakePlanner()
        listener = build_listener(
            bus, transform=FakeTransform(tarl_result(confidence=0.2)), planner=planner
        )
        await listener.start()

        await listener.submit("重启 nginx")
        await bus.wait_for_handlers()

        assert planner.calls == ["重启 nginx"]
        payload = recorder.payloads("planner.workflow_created")[0]
        assert payload["workflow_name"] == "planned-from-intent"

    @pytest.mark.asyncio
    async def test_low_confidence_without_a_planner_publishes_nothing(self):
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe("*", recorder)
        listener = build_listener(bus, transform=FakeTransform(tarl_result(confidence=0.2)))
        await listener.start()

        await listener.submit("重启 nginx")
        await bus.wait_for_handlers()

        assert recorder.types() == [f"{NAMESPACE_EVENT}transform.completed"]


class TestShellPath:
    @pytest.mark.asyncio
    async def test_shell_result_goes_through_the_gateway(self):
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe(f"{NAMESPACE_EVENT}shell.executed", recorder)
        gateway = FakeGateway()
        listener = build_listener(
            bus, transform=FakeTransform(shell_result("echo hi")), gateway=gateway
        )
        await listener.start()

        await listener.submit("打个招呼")
        await bus.wait_for_handlers()

        assert len(gateway.requests) == 1
        # ExecuteRequest 的字段是 args（命令整条塞进去），没有 command
        assert list(gateway.requests[0].args) == ["echo hi"]
        assert gateway.requests[0].raw_command == "echo hi"
        payload = recorder.payloads("shell.executed")[0]
        assert payload["command"] == "echo hi"
        assert payload["status"] == "ok"

    @pytest.mark.asyncio
    async def test_denied_shell_result_is_reported(self):
        bus = EventBus()
        recorder = Recorder()
        bus.subscribe(f"{NAMESPACE_EVENT}shell.denied", recorder)
        gateway = FakeGateway(FakeResponse(status="denied", reason="policy"))
        listener = build_listener(
            bus, transform=FakeTransform(shell_result("rm -rf /")), gateway=gateway
        )
        await listener.start()

        await listener.submit("清空根目录")
        await bus.wait_for_handlers()

        assert recorder.payloads("shell.denied")[0]["reason"] == "policy"


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_intent_actually_runs_a_workflow_that_listens_for_workflow_trigger(self, tmp_path):
        """整条链的收益：一句自然语言 → TARL → workflow.trigger → 文件 workflow 真的跑起来。"""
        root = tmp_path / "workflows"
        (root / "intent-demo").mkdir(parents=True)
        (root / "intent-demo" / "workflow.yaml").write_text(
            yaml.safe_dump({
                "id": "intent-demo",
                "name": "Intent demo",
                "steps": [
                    {
                        "trigger": {"event_type": "workflow.trigger"},
                        "execute": [{"agent_type": "shell", "instruction": "echo from-intent"}],
                    }
                ],
            }),
            encoding="utf-8",
        )

        bus = EventBus()
        gateway = FakeGateway()
        runtime = WorkflowRuntime(bus, gateway=gateway)
        runtime.register_dir(str(root), enabled=True)
        await runtime.start()

        listener = build_listener(
            bus,
            transform=FakeTransform(tarl_result(confidence=0.9)),
            gateway=gateway,
        )
        await listener.start()
        try:
            await listener.submit("重启 nginx")
            for _ in range(3):  # 决策链自己也是事件，等两轮
                await bus.wait_for_handlers()
            records = await runtime.wait_for_runs(since=0, timeout=1.0)
        finally:
            await listener.stop()
            await runtime.stop()

        assert [record.workflow_id for record in records] == ["intent-demo"]
        assert records[0].trigger_event == f"{NAMESPACE_EVENT}workflow.trigger"
        assert records[0].ok
        assert list(gateway.requests[0].args) == ["echo from-intent"]
