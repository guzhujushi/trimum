"""W1 真机验收（无需 sudo）：workflow 执行语义 —— 监听 Event Bus → 驱动执行。

跑法（真机、以 guzhujushi 身份）：

    cd /home/guzhujushi/trimum && .venv/bin/python scripts/accept_w1.py

全程用临时 ``TRIMUM_HOME``（不碰 ``~/.trimum``），两条哨兵文件盯红线：

- ``TRM-W1-DRY-MUST-NOT-EXIST``：``--dry-run`` 的那条 workflow 写着创建它，全程**不该**出现
- ``TRM-W1-DID-RUN``：真跑的那条会创建它，**必须**出现（证明「真执行」而不是「假成功」）

脚本对 Windows/Linux 都成立（写文件用 ``echo``，路径取自 ``tempfile``）。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(os.environ.get("TRIMUM_APP_DIR", Path(__file__).resolve().parents[1]))


def _interpreter() -> Path:
    """开发树是 `.venv/`，部署树是 `venv/`；都没有就用当前解释器。"""
    for name in (".venv", "venv"):
        candidate = APP / name / "bin" / "python"
        if candidate.exists():
            return candidate
        candidate = APP / name / "Scripts" / "python.exe"
        if candidate.exists():
            return candidate
    return Path(sys.executable)


REPO = APP
PY = str(_interpreter())
HOME = Path(tempfile.mkdtemp(prefix="w1home-"))
WORK = Path(tempfile.mkdtemp(prefix="w1work-"))
MARKERS = Path(tempfile.mkdtemp(prefix="w1mark-"))
DRY_MARKER = MARKERS / "TRM-W1-DRY-MUST-NOT-EXIST"
LIVE_MARKER = MARKERS / "TRM-W1-DID-RUN"
SHARED_MARKER = MARKERS / "TRM-W1-SHARED-RAN"
env = dict(os.environ, TRIMUM_HOME=str(HOME), PYTHONIOENCODING="utf-8")

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {label}" + (f"  -- {detail}" if detail and not condition else ""))
    sys.stdout.flush()


def trm(*args: str, timeout: float = 180.0):
    proc = subprocess.run(
        [PY, "-m", "trimum_core.cli", *args],
        cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    out = proc.stdout[proc.stdout.find("{"):] if "{" in proc.stdout else proc.stdout
    return proc.returncode, out, proc.stderr


def payload(*args: str, timeout: float = 180.0) -> tuple[int, dict, str]:
    rc, out, err = trm(*args)
    try:
        return rc, json.loads(out), err
    except json.JSONDecodeError:
        return rc, {}, (err + out)[-400:]


def write_workflow(root: Path, name: str, body: str) -> Path:
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    path = target / "workflow.yaml"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


ROOT = WORK / "workflows"
ROOT2 = WORK / "shared"
# 三份 workflow 各听各的事件：D6 发 security.monitor_result 时只该命中 w1-live。
DRY_WF = f"""id: w1-dry
name: W1 dry run
steps:
  - trigger:
      event_type: security.dry_result
    execute:
      - agent_type: shell
        instruction: echo w1 > {DRY_MARKER}
        timeout_seconds: 20
"""

LIVE_WF = f"""id: w1-live
name: W1 live
steps:
  - trigger:
      event_type: security.monitor_result
      condition: 'payload.get("threat_name") == "w1"'
    execute:
      - agent_type: shell
        instruction: echo w1 > {LIVE_MARKER}
        timeout_seconds: 20
"""

AGENT_WF = """id: w1-agent
name: W1 agent step
steps:
  - trigger:
      event_type: security.agent_result
    execute:
      - agent_type: trm-agent
        instruction: think about it
"""

# 同事件两份 workflow：一份会成、一份注定失败 —— 用来钉「事件是广播的」这条语义。
SHARED_A = f"""id: w1-shared-a
name: W1 shared a
steps:
  - trigger:
      event_type: security.shared_result
    execute:
      - agent_type: shell
        instruction: echo shared-a > {SHARED_MARKER}
"""

SHARED_B = """id: w1-shared-b
name: W1 shared b
steps:
  - trigger:
      event_type: security.shared_result
    execute:
      - agent_type: trm-agent
        instruction: think about it too
"""

SHARED_C = """id: w1-quiet
name: W1 quiet
steps:
  - trigger:
      event_type: system.heartbeat
    execute:
      - agent_type: shell
        instruction: echo never
"""

print(f"app={REPO}\npy={PY}\ntrimum_home={HOME}\nmarkers={MARKERS}\n")

write_workflow(ROOT, "w1-dry", DRY_WF)
write_workflow(ROOT, "w1-live", LIVE_WF)
write_workflow(ROOT, "w1-agent", AGENT_WF)
write_workflow(ROOT2, "w1-shared-a", SHARED_A)
write_workflow(ROOT2, "w1-shared-b", SHARED_B)
write_workflow(ROOT2, "w1-quiet", SHARED_C)

sys.path.insert(0, str(REPO / "src"))
import yaml  # noqa: E402

from trimum_core.event_bus import EventBus  # noqa: E402
from trimum_core.models import ExecuteResponse, SourceType  # noqa: E402
from trimum_core.workflow_engine import WorkflowDefV2  # noqa: E402
from trimum_core.workflow_runtime import WorkflowRuntime  # noqa: E402


class FakeGateway:
    def __init__(self, deny: bool = False):
        self.requests: list = []
        self.deny = deny

    async def execute(self, request):
        self.requests.append(request)
        if self.deny:
            return ExecuteResponse(
                execution_id="x", status="denied", error="denied by policy",
                exit_code=1, reason="policy",
            )
        return ExecuteResponse(execution_id="x", status="allowed", output="ok", exit_code=0)


def wf(text: str) -> WorkflowDefV2:
    return WorkflowDefV2(**yaml.safe_load(text))


# ── A. 引擎：v2 → 可执行定义 ─────────────────────────────────────────
definition = wf(LIVE_WF).to_workflow_definition()
node = definition.nodes[0]
check("A1 instruction 落进 node.config", node.config.get("instruction", "").startswith("echo w1 >"),
      str(node.config))
check("A2 agent_type / trigger_event 落进 node.config",
      node.config.get("agent_type") == "shell" and node.config.get("trigger_event") == "security.monitor_result",
      str(node.config))
check("A3 handler 是 agent_type", node.handler == "shell", node.handler)

_chained = wf("""
id: chain
steps:
  - trigger: {event_type: x}
    execute:
      - {agent_type: shell, instruction: echo one}
      - {agent_type: shell, instruction: echo two}
""").to_workflow_definition()
check("A4 多个任务串成一条链", len(_chained.nodes) == 2 and len(_chained.edges) == 1,
      f"{len(_chained.nodes)} nodes / {len(_chained.edges)} edges")

_engine_src = (REPO / "src" / "trimum_core" / "workflow_engine.py").read_text(encoding="utf-8")
check("A5 坏掉的模块级 start_v2 已删除", "async def start_v2" not in _engine_src)
check("A6 load_from_dir 尾部死代码已清（to_workflow_definition 只有一份）",
      _engine_src.count("def to_workflow_definition") == 1,
      str(_engine_src.count("def to_workflow_definition")))

# ── B. 触发器匹配与条件 ─────────────────────────────────────────────
check("B1 精确匹配", WorkflowRuntime.type_matches("security.monitor_result", "security.monitor_result"))
check("B2 去掉命名空间前缀后匹配",
      WorkflowRuntime.type_matches("security.monitor_result", "event.security.monitor_result")
      and WorkflowRuntime.type_matches("node.completed", "task.node.completed"))
check("B3 通配匹配", WorkflowRuntime.type_matches("security.*", "event.security.monitor_result"))
check("B4 空触发器永不命中（只能手动跑）",
      not WorkflowRuntime.type_matches("", "event.security.monitor_result"))
check("B5 条件读 payload",
      WorkflowRuntime.eval_condition('payload.get("a") == 1', {"a": 1})
      and not WorkflowRuntime.eval_condition('payload.get("a") == 1', {"a": 2}))
check("B6 条件里没有 builtins",
      not WorkflowRuntime.eval_condition('__import__("os").getcwd()', {})
      and not WorkflowRuntime.eval_condition('open("/etc/passwd").read()', {}))
check("B7 写坏的条件按「不通过」而不是炸掉", not WorkflowRuntime.eval_condition("payload[", {}))

# ── C. 运行时（假网关：命中 / 网关红线 / 失败 / 熔断 / 记账）─────────
async def runtime_checks() -> None:
    bus = EventBus()
    gateway = FakeGateway()
    runtime = WorkflowRuntime(bus, gateway=gateway)
    runtime.register(wf(LIVE_WF))
    await runtime.start()
    try:
        baseline = runtime.run_count
        await bus.emit_event("security.monitor_result", "accept", {"threat_name": "w1"})
        runs = await runtime.wait_for_runs(since=baseline, timeout=15)
    finally:
        await runtime.stop()
    check("C1 命中事件 → 跑起来了", len(runs) == 1 and runs[0].status == "completed",
          str([record.status for record in runs]))
    check("C2 shell 经过 ToolGateway（红线：没有旁路）", len(gateway.requests) == 1,
          str(len(gateway.requests)))
    check("C3 整条命令原样传（不 shlex 拆分，保住引号）",
          bool(gateway.requests) and gateway.requests[0].args == [
              f"echo w1 > {LIVE_MARKER}"
          ],
          str(gateway.requests[0].args if gateway.requests else None))
    check("C4 工作流流量标记为 SourceType.WORKFLOW",
          bool(gateway.requests) and gateway.requests[0].source_type is SourceType.WORKFLOW,
          str(gateway.requests[0].source_type if gateway.requests else None))

    bus = EventBus()
    gateway = FakeGateway()
    runtime = WorkflowRuntime(bus, gateway=gateway)
    runtime.register(wf(LIVE_WF))
    await runtime.start()
    try:
        baseline = runtime.run_count
        await bus.emit_event("security.monitor_result", "accept", {"threat_name": "other"})
        blocked = await runtime.wait_for_runs(since=baseline, timeout=1.0, grace=0.3)
    finally:
        await runtime.stop()
    check("C5 条件不匹配 → 不跑（也没碰网关）",
          blocked == [] and gateway.requests == [], f"{len(blocked)} runs")

    bus = EventBus()
    runtime = WorkflowRuntime(bus, gateway=FakeGateway(deny=True))
    runtime.register(wf(LIVE_WF))
    await runtime.start()
    try:
        baseline = runtime.run_count
        await bus.emit_event("security.monitor_result", "accept", {"threat_name": "w1"})
        denied = await runtime.wait_for_runs(since=baseline, timeout=15)
    finally:
        await runtime.stop()
    check("C6 网关拒绝 → workflow failed 且点名原因（失败不伪装）",
          len(denied) == 1 and denied[0].status == "failed"
          and "denied by policy" in denied[0].nodes[0].error,
          str(denied[0].nodes[0].error if denied else None))

    bus = EventBus()
    gateway = FakeGateway()
    runtime = WorkflowRuntime(bus, gateway=gateway)
    runtime.register(wf(LIVE_WF))
    record = await runtime.run_now("w1-live")
    check("C7 手动 run_now 跑整份定义", record.status == "completed" and record.step_index == -1,
          record.status)
    check("C8 运行记录可查", len(runtime.runs("w1-live")) == 1
          and runtime.list_workflows()[0]["triggers"] == ["security.monitor_result"],
          str(runtime.list_workflows()))

    bus = EventBus()
    runtime = WorkflowRuntime(
        bus, gateway=FakeGateway(), run_window_seconds=10.0, max_runs_per_window=3
    )
    runtime.register(wf("""
id: loopy
steps:
  - trigger: {event_type: security.monitor_result}
    execute: [{agent_type: shell, instruction: echo kick}]
  - trigger: {event_type: workflow.finished}
    execute: [{agent_type: shell, instruction: echo a}]
  - trigger: {event_type: workflow.finished}
    execute: [{agent_type: shell, instruction: echo b}]
"""))
    throttled: list = []

    async def _on_throttle(event) -> None:
        throttled.append(event)

    bus.subscribe("event.workflow.throttled", _on_throttle)
    await runtime.start()
    try:
        baseline = runtime.run_count
        await bus.emit_event("security.monitor_result", "accept", {})
        await runtime.wait_for_runs(since=baseline, timeout=15)
        await asyncio.sleep(0.3)
        settled = runtime.run_count
        await asyncio.sleep(0.3)
        stopped = runtime.run_count == settled
    finally:
        await runtime.stop()
    check("C9 事件环路被熔断（跑轰一下之后停下来）", bool(throttled) and stopped,
          f"throttled={len(throttled)} settled={stopped}")

    bus = EventBus()
    runtime = WorkflowRuntime(bus, gateway=FakeGateway())
    runtime.register(wf(AGENT_WF))
    agent_run = await runtime.run_now("w1-agent")
    check("C10 散文/Agent 步骤在没有 driver 时明确失败，不假装成功",
          agent_run.status == "failed" and "WorkflowEventDriver" in agent_run.nodes[0].error,
          str(agent_run.nodes[0].error if agent_run.nodes else None))


asyncio.run(runtime_checks())

# ── D. 真网关执行（生产路径：真的起进程、真的写文件）─────────────────
for marker in (DRY_MARKER, LIVE_MARKER):
    marker.unlink(missing_ok=True)

rc, data, err = payload("--json", "workflow", "run", "w1-dry", "--dry-run", "--root", str(ROOT))
check("D1 --dry-run 只打印节点，不执行", rc == 0 and data.get("dry_run") is True
      and len(data.get("nodes") or []) == 1, f"rc={rc} {err[-200:]}")
check("D2 红线：--dry-run 没有创建哨兵文件", not DRY_MARKER.exists(), str(DRY_MARKER))

rc, data, err = payload("--json", "workflow", "run", "w1-live", "--root", str(ROOT))
run = (data.get("runs") or [{}])[0]
check("D3 手动跑：真执行经 ToolGateway，退出码 0",
      rc == 0 and run.get("status") == "completed", f"rc={rc} status={run.get('status')} {err[-300:]}")
check("D4 红线：真跑的那一步真的动了手（哨兵出现）", LIVE_MARKER.exists(), str(LIVE_MARKER))
check("D5 审计里有 agent_id=trm-workflow / tool=shell",
      "trm-workflow" in (err + json.dumps(data)) and "shell" in (err + json.dumps(data)),
      (err[-300:] or json.dumps(data)[-300:]))

LIVE_MARKER.unlink(missing_ok=True)
rc, data, err = payload(
    "--json", "workflow", "run", "w1-live", "--root", str(ROOT),
    "--event", "security.monitor_result", "--payload", json.dumps({"threat_name": "w1"}),
    "--timeout", "15",
)
run = (data.get("runs") or [{}])[0]
check("D6 事件触发路径：发事件 → 运行时命中 → 执行",
      rc == 0 and data.get("triggered_by") == "event" and run.get("status") == "completed"
      and [r.get("workflow_id") for r in data.get("runs") or []] == ["w1-live"],
      f"rc={rc} {json.dumps(data)[-300:]}")
check("D7 事件触发也真的动了手", LIVE_MARKER.exists())
check("D9 红线：同一 root 下的其它 workflow 没被顺手触发（dry 哨兵仍不存在）",
      not DRY_MARKER.exists(), str(DRY_MARKER))

rc, data, err = payload(
    "--json", "workflow", "run", "w1-live", "--root", str(ROOT),
    "--event", "nope.event", "--timeout", "1",
)
check("D8 事件不来就报错退出（不会假装跑过）", rc == 1 and not data, f"rc={rc} {err[-200:]}")

# 一次事件命中两份 workflow：只对点名的负责，顺带跑掉的如实汇报
rc, data, err = payload(
    "--json", "workflow", "run", "w1-shared-a", "--root", str(ROOT2),
    "--event", "security.shared_result", "--timeout", "15",
)
check("D10 事件是广播的：别的 workflow 只汇报、不算进本命令的退出码",
      rc == 0 and [r.get("workflow_id") for r in data.get("runs") or []] == ["w1-shared-a"]
      and data.get("other_triggered") == ["w1-shared-b"] and SHARED_MARKER.exists(),
      f"rc={rc} {json.dumps(data)[-300:]}")

rc, data, err = payload(
    "workflow", "run", "w1-quiet", "--root", str(ROOT2),
    "--event", "security.shared_result", "--timeout", "15",
)
check("D11 点名的那份没被触发就明说（不拿别人的运行充数）",
      rc == 1 and "was not triggered" in err and "w1-shared-a, w1-shared-b" in err,
      f"rc={rc} {err[-200:]}")

# ── E. 内置威胁剧本 ─────────────────────────────────────────────────
rc, data, err = payload("--json", "workflow", "list", "--all", "--root", str(ROOT))
items = {item["id"]: item for item in data.get("workflows") or []}
builtin = [item for item in items.values() if item["source"] == "builtin"]
check("E1 内置剧本已登记（16 条威胁响应手册）", len(builtin) == 16, str(len(builtin)))
check("E2 内置剧本默认不自动触发（enabled=false）",
      bool(builtin) and all(item["enabled"] is False for item in builtin))
check("E3 内置剧本带触发器信息",
      items.get("threat-cron-audit", {}).get("triggers") == ["security.monitor_result"],
      str(items.get("threat-cron-audit")))
check("E4 文件 workflow 仍然默认 enabled",
      items.get("w1-live", {}).get("enabled") is True, str(items.get("w1-live")))

rc, data, err = payload("--json", "workflow", "run", "threat-cron-audit", "--dry-run",
                        "--root", str(ROOT))
instructions = [node["instruction"] for node in data.get("nodes") or []]
handlers = [node["handler"] for node in data.get("nodes") or []]
check("E5 内置剧本：命令式步骤编译成 shell，散文式步骤交给 Agent",
      rc == 0 and handlers.count("shell") >= 2 and "trm-agent" in handlers,
      f"{handlers} {err[-200:]}")
check("E6 内置剧本的步骤文本进到了 instruction", "crontab -l" in instructions, str(instructions))

# ── F. CLI 契约 ─────────────────────────────────────────────────────
rc, data, err = payload("--json", "workflow", "list", "--root", str(ROOT))
check("F1 list 只列文件 workflow", rc == 0 and data.get("count") == 3, str(data.get("count")))
rc, _data, err = payload("workflow", "run", "no-such-workflow", "--root", str(ROOT))
check("F2 未知 workflow 退出码 1", rc == 1 and "unknown workflow" in err, err[-200:])

ENABLE_ROOT = WORK / "enable-root"
rc, data, err = payload("workflow", "enable", "threat-cron-audit",
                        "--root", str(ENABLE_ROOT), "--yes")
written = ENABLE_ROOT / "threat-cron-audit" / "workflow.yaml"
check("F3 enable：内置剧本落盘成自己的 workflow", rc == 0 and written.exists(), err[-200:])
rc, data, err = payload("--json", "workflow", "list", "--all", "--root", str(ENABLE_ROOT))
items = {item["id"]: item for item in data.get("workflows") or []}
entry = items.get("threat-cron-audit", {})
check("F4 enable 之后同名文件压过内置那份（且 enabled）",
      entry.get("source") == "file" and entry.get("enabled") is True, str(entry))
rc, _data, err = payload("workflow", "enable", "threat-cron-audit",
                         "--root", str(ENABLE_ROOT), "--yes")
check("F5 重复 enable 被拒（不覆盖已有）", rc == 1, err[-200:])

rc, out, err = trm("commands", "--check")
check("F6 trm commands --check 无问题", rc == 0 and "no problems" in (out + err), (out + err)[-200:])

# ── G. daemon 接线 ──────────────────────────────────────────────────
_api_src = (REPO / "src" / "trimum_core" / "api_server.py").read_text(encoding="utf-8")
check("G1 daemon 启动时建并启动 workflow 运行时",
      "WorkflowRuntime(" in _api_src and "await runtime.start()" in _api_src)
check("G2 只读观测端点已注册（不开放执行端点）",
      '"/api/workflows"' in _api_src and '"/api/workflows/runs"' in _api_src
      and "workflows/{workflow_id}/trigger" not in _api_src)

print()
print(f"== W1 验收：{len(PASS)} passed / {len(FAIL)} failed ==")
for item in FAIL:
    print(f"  FAILED: {item}")
print(f"artifacts: TRIMUM_HOME={HOME} work={WORK} markers={MARKERS}")
sys.exit(1 if FAIL else 0)
