"""决策 18（dogfood 第①步）：workflow 节点可以直接拉起 codex 窗口。

只测 CLI 可达的 ``agent_type: codex`` / ``codex-cli`` handler：

- ``resolve_codex_argv``：env > 配置 > 默认，``{prompt}`` 占位替换（决策 24）。
- G-3 闸门：只有 ``triggered_by == "manual"`` 才允许执行，事件触发一律拒。
- 非零退出 / 空 instruction ⇒ run 失败，绝不伪装成功。

全部 ``tmp_path`` / monkeypatch 隔离，**绝不真跑 codex**（tmp 里的假脚本）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from trimum_core.codex_launcher import (
    CODEX_CMD_ENV,
    DEFAULT_CODEX_ARGV,
    resolve_codex_argv,
)
from trimum_core.event_bus import EventBus
from trimum_core.models import TrimumError
from trimum_core.workflow_engine import (
    AgentTask,
    NodeDefinition,
    WorkflowDefV2,
    WorkflowStep,
    WorkflowStepCondition,
)
from trimum_core.workflow_runtime import WorkflowRuntime


class _Cfg:
    """带 ``get`` 的小假配置：``raise_on_get`` 模拟坏配置。"""

    def __init__(self, value=None, *, raise_on_get: bool = False):
        self._value = value
        self._raise = raise_on_get

    def get(self, key, default=None):
        if self._raise:
            raise RuntimeError("broken config")
        return self._value


def _fake_codex(tmp_path: Path, body: str) -> str:
    """在 tmp 里放一个假 codex 脚本，返回可直接进 env 的命令字符串。"""
    script = tmp_path / "fake_codex.py"
    script.write_text(body, encoding="utf-8")
    return f"{sys.executable} {script}"


def _codex_wf(tmp_path: Path, agent_type: str, instruction: str) -> WorkflowRuntime:
    """注册一份单节点 codex workflow，返回挂好 handler 的 runtime。"""
    runtime = WorkflowRuntime(EventBus(), runs_path=tmp_path / "runs.jsonl")
    wf = WorkflowDefV2(
        id="wf-codex",
        name="codex dogfood",
        steps=[
            WorkflowStep(
                trigger=WorkflowStepCondition(event_type=""),
                execute=[
                    AgentTask(
                        agent_type=agent_type,
                        instruction=instruction,
                        timeout_seconds=30.0,
                    )
                ],
            )
        ],
    )
    runtime.register(wf, source="inline")
    return runtime


# ── resolve_codex_argv（决策 24：env > 配置 > 默认）──────────────

def test_resolve_default():
    assert resolve_codex_argv("P", env={}, config=_Cfg({})) == [*DEFAULT_CODEX_ARGV, "P"]


def test_resolve_env_beats_config():
    raw = resolve_codex_argv(
        "P",
        env={CODEX_CMD_ENV: "/bin/echo -n {prompt}"},
        config=_Cfg("should-not-be-used"),
    )
    assert raw == ["/bin/echo", "-n", "P"]


def test_resolve_config_str_and_list():
    from_str = resolve_codex_argv("P", env={}, config=_Cfg("/usr/bin/codex exec --fast"))
    assert from_str == ["/usr/bin/codex", "exec", "--fast", "P"]

    from_list = resolve_codex_argv("P", env={}, config=_Cfg(["/usr/bin/codex", "exec", 42]))
    assert from_list == ["/usr/bin/codex", "exec", "42", "P"]


@pytest.mark.parametrize(
    "cfg",
    [_Cfg(raise_on_get=True), _Cfg(""), _Cfg(None), _Cfg(123)],
    ids=["raises", "empty-str", "none", "int"],
)
def test_resolve_broken_or_empty_config_falls_back(cfg):
    assert resolve_codex_argv("P", env={}, config=cfg) == [*DEFAULT_CODEX_ARGV, "P"]


# ── CLI 可达的 codex handler ────────────────────────────────────

@pytest.mark.asyncio
async def test_codex_alias_runs_and_returns_output(tmp_path, monkeypatch):
    monkeypatch.setenv(
        CODEX_CMD_ENV,
        _fake_codex(tmp_path, "import sys; print('ECHO:' + ' '.join(sys.argv[1:]))\n"),
    )
    runtime = _codex_wf(tmp_path, "codex", "say hi")
    record = await runtime.run_now("wf-codex")
    assert record.status == "completed", record.error
    node = record.nodes[0]
    assert node.result["exit_code"] == 0
    assert "say hi" in node.result["output"]


@pytest.mark.asyncio
async def test_codex_cli_alias_also_registered(tmp_path, monkeypatch):
    monkeypatch.setenv(
        CODEX_CMD_ENV,
        _fake_codex(tmp_path, "import sys; print('ECHO:' + ' '.join(sys.argv[1:]))\n"),
    )
    runtime = _codex_wf(tmp_path, "codex-cli", "say hi")
    record = await runtime.run_now("wf-codex")
    assert record.status == "completed", record.error
    assert record.nodes[0].result["exit_code"] == 0


@pytest.mark.asyncio
async def test_codex_node_refuses_event_trigger(tmp_path, monkeypatch):
    marker = tmp_path / "ran.txt"
    monkeypatch.setenv(
        CODEX_CMD_ENV,
        _fake_codex(
            tmp_path,
            f"import pathlib; pathlib.Path({str(marker)!r}).write_text('ran')\n",
        ),
    )
    runtime = WorkflowRuntime(EventBus(), runs_path=tmp_path / "runs.jsonl")
    node = NodeDefinition(
        id="step_0_task_0",
        label="codex",
        handler="codex",
        config={"agent_type": "codex", "instruction": "say hi"},
    )
    with pytest.raises(TrimumError) as exc:
        await runtime._handle_codex_node("wf", node, {"triggered_by": "event"})
    assert "人工激活" in exc.value.message
    assert not marker.exists()


@pytest.mark.asyncio
async def test_codex_node_failure_paths(tmp_path, monkeypatch):
    # (a) 非零退出 ⇒ run 失败
    monkeypatch.setenv(
        CODEX_CMD_ENV,
        _fake_codex(tmp_path, "import sys; sys.exit(3)\n"),
    )
    runtime = _codex_wf(tmp_path, "codex", "say hi")
    record = await runtime.run_now("wf-codex")
    assert record.status == "failed", record.status
    assert "exit=3" in record.nodes[0].error

    # (b) 空 instruction ⇒ 同样失败
    monkeypatch.setenv(
        CODEX_CMD_ENV,
        _fake_codex(tmp_path, "import sys; print('should not run')\n"),
    )
    runtime2 = _codex_wf(tmp_path, "codex", "   ")
    record2 = await runtime2.run_now("wf-codex")
    assert record2.status == "failed", record2.status
    assert "instruction" in record2.nodes[0].error
