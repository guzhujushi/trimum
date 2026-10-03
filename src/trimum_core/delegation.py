"""子 Agent 委派编排（E7 第 4 片「子 Agent 委派做实」前半，只做编排、不接线）。

本模块把「父会话派活给子 Agent」做成可测对象：

- 派单前先做**权限交集**（子能力 = 父能力 ∩ 请求，只收紧不放宽）+ **预算**
  （步数 / token，父是上限）；交集读不出来或越权 ⇒ 直接拒，不启动、不发事件。
- 子 Agent 的启动走**注入的 ``spawn`` 回调**：默认 ``default_spawn()`` 真启动
  （延迟 import ``agent_launcher.launch_agent``），测试注入 fake 即可全量覆盖。
- 父派子跑通 / 子越权被拒 / 子崩溃不影响父 / 预算耗尽明确停止并上报，四条验收
  全部落在纯函数 ``plan_delegation`` + 编排函数 ``delegate`` 上。

**不接线**：本模块不碰 ``agent_runtime`` / ``agent_loop`` / ``cli`` / ``ToolGateway``，
也不在这里 import 任何会拖起进程依赖的东西（``agent_launcher`` 延迟到
``default_spawn()`` 内部才 import，纯函数测试不拖进程依赖）。

口径约定：``unsupported`` 类的「拿不准」（能力块读不出来、spawn 返回未知形状）
一律**如实记**进 ``reason`` / ``error``，不假装成功。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, fields
from typing import Any, Optional

from . import capability, identity

# ---- 状态常量（名字与取值逐字一致）----
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CRASHED = "crashed"
STATUS_REJECTED = "rejected"
STATUS_BUDGET_EXHAUSTED = "budget_exhausted"

PLAN_READY = "ready"

# 拒绝理由（越权的具体值写成 f"{REASON_TOOL_NOT_PERMITTED}:{tool}"）
REASON_TOOL_NOT_PERMITTED = "tool_not_permitted"
REASON_CAPABILITY_EMPTY = "capability_intersection_empty"
REASON_CAPABILITY_UNREADABLE = "capability_unreadable"
REASON_EMPTY_TASK = "empty_task"

# 事件类型（→ 总线上的 task.<name>）
EVENT_ASSIGNED = "assigned"      # → task.assigned
EVENT_COMPLETED = "completed"    # → task.completed
EVENT_FAILED = "failed"          # → task.failed（细状态放 payload["status"]）

SOURCE = "delegation"

# 注入子 Agent 的环境变量
ENV_BUDGET_STEPS = "TRIMUM_AGENT_BUDGET_STEPS"
ENV_BUDGET_TOKENS = "TRIMUM_AGENT_BUDGET_TOKENS"
ENV_TASK = "TRIMUM_AGENT_TASK"
ENV_CAPABILITIES = "TRIMUM_AGENT_CAPABILITIES"

#: spawn 回调：吃一个 DelegationPlan，返回 ChildReport（或 dict，由 delegate 适配）
SpawnFn = Callable[["DelegationPlan"], Awaitable["ChildReport"]]


@dataclass(frozen=True)
class Budget:
    """子 Agent 的预算：步数与 token 上限（父预算是更外层的上限）。"""

    steps: int = 20
    tokens: int = 20000

    def __post_init__(self) -> None:
        if self.steps <= 0:
            raise ValueError(f"Budget.steps 必须为正整数（收到 {self.steps!r}）")
        if self.tokens <= 0:
            raise ValueError(f"Budget.tokens 必须为正整数（收到 {self.tokens!r}）")

    def tighten(self, parent: "Budget") -> "Budget":
        """父预算是上限：逐项取 min。"""
        return Budget(steps=min(self.steps, parent.steps), tokens=min(self.tokens, parent.tokens))


@dataclass(frozen=True)
class DelegationRequest:
    """一次派单请求。``capabilities`` / ``budget`` 为 None = 继承父。"""

    task: str
    agent_type: str = "coder"
    capabilities: Optional[dict] = None
    budget: Optional[Budget] = None
    session_id: str = ""


@dataclass(frozen=True)
class DelegationPlan:
    """派单计划：``status`` 为 PLAN_READY 或 STATUS_REJECTED（被拒不启动）。"""

    task_id: str
    agent_id: str
    agent_type: str
    task: str
    capabilities: dict
    budget: Budget
    status: str
    reason: str = ""
    tightenings: tuple[dict, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChildReport:
    """子 Agent 自报的结果（spawn 回调的返回值形状）。"""

    status: str = STATUS_COMPLETED
    output: str = ""
    error: str = ""
    steps_used: Optional[int] = None
    tokens_used: Optional[int] = None
    pid: Optional[int] = None
    log_path: str = ""
    usage_reported: Optional[bool] = None


@dataclass(frozen=True)
class DelegationResult:
    """一次派单的最终结果（含真实事件与审计块）。"""

    task_id: str
    agent_id: str
    agent_type: str
    status: str
    output: str = ""
    error: str = ""
    reason: str = ""
    steps_used: Optional[int] = None
    tokens_used: Optional[int] = None
    usage_reported: bool = False
    events: tuple[str, ...] = ()
    audit: dict = field(default_factory=dict)


def _intersect_risk(parent_risk: str, request_risk: str) -> str:
    """更严者胜：任一方 inherit 取另一方；都非 inherit 取下标更小者。"""
    if parent_risk == "inherit":
        return request_risk
    if request_risk == "inherit":
        return parent_risk
    parent_idx = identity.MAX_RISK_VALUES.index(parent_risk)
    request_idx = identity.MAX_RISK_VALUES.index(request_risk)
    return identity.MAX_RISK_VALUES[min(parent_idx, request_idx)]


def plan_delegation(
    parent_capabilities: Any,
    request: DelegationRequest,
    *,
    parent_budget: Optional[Budget] = None,
    task_id: str = "",
) -> DelegationPlan:
    """把一次派单请求 + 父能力块编排成可执行计划（纯函数，不启动、不发事件）。

    被拒（越权 / 交集空 / 能力读不出）⇒ ``status=STATUS_REJECTED`` 且带 ``reason``；
    参数错误（空 task）⇒ 直接抛 ``ValueError``（允许抛）。
    不改动传入的 ``parent_capabilities`` / ``request.capabilities``（先深拷贝）。
    """
    task = request.task.strip()
    if not task:
        raise ValueError(f"{REASON_EMPTY_TASK}: task 不能为空")

    tid = task_id or uuid.uuid4().hex
    agent_id = f"{request.agent_type}-{tid[:8]}"

    # 先做能力判定：任一侧读不出来 ⇒ 拒（读不出来的能力块 ≠ 全权，与 normalise 同源）
    parent_caps, parent_problems = capability.normalise(parent_capabilities)
    request_caps, request_problems = capability.normalise(request.capabilities)

    def _denied(reason: str, tightening: dict) -> DelegationPlan:
        return DelegationPlan(
            task_id=tid,
            agent_id=agent_id,
            agent_type=request.agent_type,
            task=task,
            capabilities=parent_caps,
            budget=(parent_budget or Budget()),
            status=STATUS_REJECTED,
            reason=reason,
            tightenings=(tightening,),
        )

    if parent_problems or request_problems:
        problems = list(parent_problems) + list(request_problems)
        source = "parent" if parent_problems else "request"
        return _denied(
            REASON_CAPABILITY_UNREADABLE,
            {
                "action": "deny",
                "reason": "capability_problems",
                "source": source,
                "detail": {"problems": list(problems)},
            },
        )

    tightenings: list[dict] = []
    if request.capabilities is None:
        # 继承父：原样（normalise 产物，已是新 dict，未改传入值）
        child_caps = dict(parent_caps)
    else:
        parent_tools = list(parent_caps["tools"])
        request_tools = list(request_caps["tools"])
        if "*" in request_tools:
            child_tools = list(parent_tools)  # "全都要" 与父求交 = 父全集
        else:
            child_tools = []
            overreaches = []
            for tool in request_tools:
                if capability.tool_allowed(tool, parent_tools):
                    child_tools.append(tool)
                else:
                    overreaches.append(tool)
            if not child_tools:
                # 点名越权：单个**具体**工具超出父能力 ⇒ 拒（点名）；
                # 请求项本身是通配（要一整族，如 net.*）⇒ 交集为空
                if len(overreaches) == 1 and "*" not in overreaches[0]:
                    tool = overreaches[0]
                    return _denied(
                        f"{REASON_TOOL_NOT_PERMITTED}:{tool}",
                        {
                            "action": "deny",
                            "reason": "tool_not_permitted",
                            "source": "request",
                            "detail": {"tool": tool, "parent_tools": parent_tools},
                        },
                    )
                # 交集为空（整族都不在父里）⇒ 拒
                return _denied(
                    REASON_CAPABILITY_EMPTY,
                    {
                        "action": "deny",
                        "reason": "capability_empty",
                        "source": "request",
                        "detail": {"request_tools": request_tools, "overreaches": overreaches},
                    },
                )
        child_risk = _intersect_risk(parent_caps["max_risk"], request_caps["max_risk"])
        if child_risk != request_caps["max_risk"]:
            tightenings.append(
                {
                    "action": "tighten",
                    "reason": "max_risk_stricter",
                    "source": "parent",
                    "detail": {
                        "parent": parent_caps["max_risk"],
                        "request": request_caps["max_risk"],
                        "result": child_risk,
                    },
                }
            )
        parent_exp = parent_caps.get("expires_at")
        request_exp = request_caps.get("expires_at")
        if parent_exp and request_exp:
            child_exp = min(str(parent_exp), str(request_exp))
        elif request_exp:
            child_exp = request_exp
        else:
            child_exp = parent_exp
        # scope：父 untrusted ⇒ 子 untrusted；否则取父的 scope（只收紧不放宽）
        child_scope = parent_caps["scope"]
        child_caps = {
            "tools": child_tools,
            "max_risk": child_risk,
            "expires_at": child_exp,
            "scope": child_scope,
        }

    # 预算：None ⇒ 父的；给了 ⇒ 与父取 min（父是上限）
    if request.budget is None:
        child_budget = parent_budget or Budget()
    else:
        child_budget = request.budget.tighten(parent_budget or Budget())

    return DelegationPlan(
        task_id=tid,
        agent_id=agent_id,
        agent_type=request.agent_type,
        task=task,
        capabilities=child_caps,
        budget=child_budget,
        status=PLAN_READY,
        reason="",
        tightenings=tuple(tightenings),
    )


def default_spawn(
    agents_root: Any = None,
    socket_path: Optional[str] = None,
    timeout: float = 0.0,
) -> SpawnFn:
    """默认 spawn：真启动子 Agent 进程（延迟 import ``agent_launcher``）。

    纯函数测试不经过这里；只有 ``delegate(spawn=None)`` 或显式注入本工厂时才拖起
    进程依赖。
    """

    async def _spawn(plan: DelegationPlan) -> ChildReport:
        from . import agent_launcher  # 延迟 import：纯函数测试不拖进程依赖

        run = await agent_launcher.run_agent(
            plan.agent_id,
            plan.agent_type,
            base=agents_root,
            socket_path=socket_path,
            extra_env={
                ENV_TASK: plan.task,
                ENV_BUDGET_STEPS: str(plan.budget.steps),
                ENV_BUDGET_TOKENS: str(plan.budget.tokens),
                ENV_CAPABILITIES: json.dumps(plan.capabilities, ensure_ascii=False),
            },
            timeout=timeout,
            budget=plan.budget,
        )
        launch = run.launch
        log_path = str((launch.log_path if launch is not None else None) or "")
        pid = launch.pid if launch is not None else None
        if run.error:
            return ChildReport(status=STATUS_FAILED, error=run.error, log_path=log_path)
        if launch is not None and launch.error:
            return ChildReport(status=STATUS_FAILED, error=str(launch.error), log_path=log_path)
        if pid is None:
            return ChildReport(status=STATUS_FAILED, error="agent script not installed", log_path=log_path)
        if run.timed_out:
            return ChildReport(
                status=STATUS_FAILED,
                error=f"agent timed out after {timeout}s",
                steps_used=run.steps_used, tokens_used=run.tokens_used,
                usage_reported=run.usage_reported, pid=pid, log_path=log_path,
            )
        return ChildReport(
            status=STATUS_COMPLETED,
            output=f"pid={pid}",
            steps_used=run.steps_used,
            tokens_used=run.tokens_used,
            usage_reported=run.usage_reported,
            pid=pid,
            log_path=log_path,
        )

    return _spawn


def _coerce_report(value: Any) -> ChildReport:
    """spawn 返回值鸭子适配：ChildReport 或 dict 两条路都行。"""
    if isinstance(value, ChildReport):
        return value
    if isinstance(value, dict):
        valid = {f.name for f in fields(ChildReport)}
        return ChildReport(**{k: v for k, v in value.items() if k in valid})
    raise TypeError(f"spawn 返回值既不是 ChildReport 也不是 dict：{type(value).__name__}")


def _make_audit(
    plan: DelegationPlan,
    *,
    status: str,
    reason: str,
    error: str,
    steps_used: Optional[int],
    tokens_used: Optional[int],
    usage_reported: bool,
    pid: Optional[int],
    log_path: str,
    parent_session: str,
) -> dict:
    return {
        "task_id": plan.task_id,
        "agent_id": plan.agent_id,
        "agent_type": plan.agent_type,
        "parent_session": parent_session,
        "status": status,
        "reason": reason,
        "error": error,
        "steps_used": steps_used,
        "tokens_used": tokens_used,
        "usage_reported": usage_reported,
        "budget": {"steps": plan.budget.steps, "tokens": plan.budget.tokens},
        "capabilities": dict(plan.capabilities),
        "tightenings": list(plan.tightenings),
        "pid": pid,
        "log_path": log_path,
    }


async def delegate(
    parent_capabilities: Any,
    request: DelegationRequest,
    *,
    spawn: Optional[SpawnFn] = None,
    bus: Any = None,
    parent_budget: Optional[Budget] = None,
    task_id: str = "",
    parent_session: str = "",
) -> DelegationResult:
    """编排一次完整派单：计划 → (被拒直接返回) → 发 task.assigned → spawn → 分类 → 终态事件。

    - 被拒（越权 / 交集空 / 读不出）⇒ 不 spawn、不发任何事件（红线）。
    - 分类顺序固定（先判先赢）：spawn 抛异常 ⇒ crashed；自报非 completed ⇒ failed；
      自报用量超预算 ⇒ budget_exhausted；其余 ⇒ completed。
    - 除 ``ValueError``（参数错，来自 ``plan_delegation``）外从不抛：整体兜底成 crashed。
    """
    if spawn is None:
        spawn = default_spawn()

    session = parent_session or request.session_id

    plan = plan_delegation(
        parent_capabilities,
        request,
        parent_budget=parent_budget,
        task_id=task_id,
    )

    # 被拒：不 spawn、不发任何事件（红线）
    if plan.status != PLAN_READY:
        return DelegationResult(
            task_id=plan.task_id,
            agent_id=plan.agent_id,
            agent_type=plan.agent_type,
            status=STATUS_REJECTED,
            reason=plan.reason,
            events=(),
            audit=_make_audit(
                plan,
                status=STATUS_REJECTED,
                reason=plan.reason,
                error="",
                steps_used=None,
                tokens_used=None,
                usage_reported=False,
                pid=None,
                log_path="",
                parent_session=session,
            ),
        )

    events: list[str] = []
    try:
        # 派单事件（bus 为 None 就跳过）
        if bus is not None:
            await bus.emit_task(
                EVENT_ASSIGNED,
                {
                    "task_id": plan.task_id,
                    "agent_id": plan.agent_id,
                    "agent_type": plan.agent_type,
                    "parent_session": session,
                    "task": plan.task,
                    "capabilities": dict(plan.capabilities),
                    "budget": {"steps": plan.budget.steps, "tokens": plan.budget.tokens},
                },
                source=SOURCE,
            )
            events.append(f"task.{EVENT_ASSIGNED}")

        # spawn（鸭子适配返回值）
        raw = await spawn(plan)
        report = _coerce_report(raw)

        # 分类（先判先赢）
        status = STATUS_COMPLETED
        reason = ""
        error = ""
        if report.status != STATUS_COMPLETED:
            status = STATUS_FAILED
            error = report.error
        else:
            over_steps = report.steps_used is not None and report.steps_used > plan.budget.steps
            over_tokens = report.tokens_used is not None and report.tokens_used > plan.budget.tokens
            if over_steps or over_tokens:
                status = STATUS_BUDGET_EXHAUSTED
                detail = []
                if over_steps:
                    detail.append(f"steps {report.steps_used}/{plan.budget.steps}")
                if over_tokens:
                    detail.append(f"tokens {report.tokens_used}/{plan.budget.tokens}")
                error = "budget exhausted: " + ", ".join(detail)

        reported = report.usage_reported
        usage_reported = (
            reported
            if reported is not None
            else (report.steps_used is not None or report.tokens_used is not None)
        )

        # 终态事件：completed → task.completed；其余 → task.failed（细状态放 payload）
        if bus is not None:
            if status == STATUS_COMPLETED:
                await bus.emit_task(
                    EVENT_COMPLETED,
                    {
                        "task_id": plan.task_id,
                        "agent_id": plan.agent_id,
                        "status": status,
                        "steps_used": report.steps_used,
                        "tokens_used": report.tokens_used,
                    },
                    source=SOURCE,
                )
                events.append(f"task.{EVENT_COMPLETED}")
            else:
                await bus.emit_task(
                    EVENT_FAILED,
                    {
                        "task_id": plan.task_id,
                        "agent_id": plan.agent_id,
                        "status": status,
                        "error": error,
                        "steps_used": report.steps_used,
                        "tokens_used": report.tokens_used,
                    },
                    source=SOURCE,
                    severity="warning",
                )
                events.append(f"task.{EVENT_FAILED}")

        return DelegationResult(
            task_id=plan.task_id,
            agent_id=plan.agent_id,
            agent_type=plan.agent_type,
            status=status,
            output=report.output,
            error=error,
            reason=reason,
            steps_used=report.steps_used,
            tokens_used=report.tokens_used,
            usage_reported=usage_reported,
            events=tuple(events),
            audit=_make_audit(
                plan,
                status=status,
                reason=reason,
                error=error,
                steps_used=report.steps_used,
                tokens_used=report.tokens_used,
                usage_reported=usage_reported,
                pid=report.pid,
                log_path=report.log_path,
                parent_session=session,
            ),
        )
    except Exception as exc:  # noqa: BLE001 —— 除 ValueError 外兜底成 crashed
        # 这里兜底 spawn 抛异常 / 事件发送失败等一切运行时异常：子崩溃不影响父
        status = STATUS_CRASHED
        error = str(exc)
        if bus is not None and f"task.{EVENT_FAILED}" not in events:
            try:
                await bus.emit_task(
                    EVENT_FAILED,
                    {
                        "task_id": plan.task_id,
                        "agent_id": plan.agent_id,
                        "status": status,
                        "error": error,
                    },
                    source=SOURCE,
                    severity="warning",
                )
                events.append(f"task.{EVENT_FAILED}")
            except Exception:  # noqa: BLE001 —— 事件发送失败也不许影响父
                pass
        return DelegationResult(
            task_id=plan.task_id,
            agent_id=plan.agent_id,
            agent_type=plan.agent_type,
            status=status,
            error=error,
            usage_reported=False,
            events=tuple(events),
            audit=_make_audit(
                plan,
                status=status,
                reason="",
                error=error,
                steps_used=None,
                tokens_used=None,
                usage_reported=False,
                pid=None,
                log_path="",
                parent_session=session,
            ),
        )


__all__ = [
    "Budget",
    "ChildReport",
    "DelegationPlan",
    "DelegationRequest",
    "DelegationResult",
    "EVENT_ASSIGNED",
    "EVENT_COMPLETED",
    "EVENT_FAILED",
    "ENV_BUDGET_STEPS",
    "ENV_BUDGET_TOKENS",
    "ENV_CAPABILITIES",
    "ENV_TASK",
    "PLAN_READY",
    "REASON_CAPABILITY_EMPTY",
    "REASON_CAPABILITY_UNREADABLE",
    "REASON_EMPTY_TASK",
    "REASON_TOOL_NOT_PERMITTED",
    "SOURCE",
    "SpawnFn",
    "STATUS_BUDGET_EXHAUSTED",
    "STATUS_COMPLETED",
    "STATUS_CRASHED",
    "STATUS_FAILED",
    "STATUS_REJECTED",
    "default_spawn",
    "delegate",
    "plan_delegation",
]
