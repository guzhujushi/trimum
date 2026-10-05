"""E7 第 5 片：编码会话编排。

不新造执行通道（一切命令经 ``ToolGateway``）、判定复用 ``verifier``、
编辑复用 ``patch_ops``、写盘可回滚、没有模型就说没有。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from . import patch_ops, verifier
from .agent_loop import STEP_ERROR_STATUSES, STEP_OK_STATUSES  # noqa: F401
from .audit_store import AuditStore
from .edit_hooks import EditPreviewHook
from .instruction_loader import (
    DEFAULT_MAX_BODY_CHARS,
    DEFAULT_MAX_CHARS,
    load_instructions,
    match_instructions,
    render_injection,
)
from .llm_router import LlmCallError, ROLE_AGENT
from .llm_policy import build_default_llm_policy
from .models import TRMErrorCode, ExecuteRequest, SourceType, ToolType, TrimumError
from .paths import trimum_path
from .tool_gateway import ToolGateway

log = logging.getLogger("trimum_core.coding_agent")

STEP_RUN = "run"
STEP_EDIT = "edit"
STEP_DONE = "done"

CHANGE_PREVIEW = "preview"
CHANGE_APPLIED = "applied"
CHANGE_REJECTED = "rejected"

REASON_ITERATION_CAP = "iteration_cap"
REASON_STEP_FAILED = "step_failed"
REASON_CHANGE_REJECTED = "change_rejected"
REASON_VERIFICATION_RED = "verification_red"


@dataclass
class CodingStep:
    """planner 吐出的一步指令。"""

    kind: str
    command: str = ""
    path: str = ""
    anchor: str = ""
    replacement: str = ""
    reason: str = ""
    done: bool = False

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "CodingStep":
        kind = str(mapping.get("kind") or "").strip()
        if not kind:
            if mapping.get("done"):
                kind = STEP_DONE
            elif mapping.get("command"):
                kind = STEP_RUN
            elif mapping.get("anchor") or mapping.get("replacement"):
                kind = STEP_EDIT
        # 未知 kind 原样保留，不抛
        return cls(
            kind=kind,
            command=str(mapping.get("command") or ""),
            path=str(mapping.get("path") or ""),
            anchor=str(mapping.get("anchor") or ""),
            replacement=str(mapping.get("replacement") or ""),
            reason=str(mapping.get("reason") or ""),
            done=bool(mapping.get("done")),
        )


@dataclass
class SessionChange:
    """一次编辑的归一结果（含 dry-run 预览与拒绝）。"""

    path: str
    status: str
    added_lines: int = 0
    removed_lines: int = 0
    difference: str = ""
    snapshot_id: Optional[str] = None
    reason: str = ""


@dataclass
class SessionRecord:
    """一次编码会话的完整落盘记录。"""

    task: str
    session_id: str
    cwd: str
    dry_run: bool
    steps: list[dict] = field(default_factory=list)
    changes: list[SessionChange] = field(default_factory=list)
    verifications: list[verifier.VerificationResult] = field(default_factory=list)
    started_at: str = ""
    ended_at: str = ""
    ok: bool = False
    reason: str = ""
    record_path: str = ""
    skills: list[str] = field(default_factory=list)
    instructions: str = ""

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "session_id": self.session_id,
            "cwd": self.cwd,
            "dry_run": self.dry_run,
            "steps": self.steps,
            "changes": [asdict(c) for c in self.changes],
            "verifications": [asdict(v) for v in self.verifications],
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "ok": self.ok,
            "reason": self.reason,
            "record_path": self.record_path,
            "skills": self.skills,
            "instructions": self.instructions,
        }


class ScriptedPlanner:
    """按序吐固定步骤；吐完返回 None（不重复吐同一步）。"""

    def __init__(self, steps: Sequence[CodingStep | Mapping[str, Any]]) -> None:
        self._steps: list[CodingStep] = [
            s if isinstance(s, CodingStep) else CodingStep.from_mapping(s) for s in steps
        ]
        self._index = 0

    async def __call__(self, task: str, history: list[dict]) -> Optional[CodingStep]:
        if self._index >= len(self._steps):
            return None
        step = self._steps[self._index]
        self._index += 1
        return step


class NoModelError(RuntimeError):
    """没有可用模型 / 调不通 —— 必须显式失败，绝不假装完成任务。"""


async def plan_step_with_llm(
    task: str,
    history: list[dict],
    *,
    router: Any = None,
    timeout: float = 15.0,
) -> CodingStep:
    """默认 planner：单步 JSON。router 默认 ``from . import llm_router`` 后取模块本身。"""
    from . import llm_router

    router = router or llm_router

    system = (
        "你是编码助手，返回 JSON：{\"kind\":\"run|edit|done\",\"command\":\"\",\"path\":\"\",\"anchor\":\""
        "\",\"replacement\":\"\",\"reason\":\"\",\"done\":false}"
    )
    user = f"任务：{task}\n历史：{json.dumps(history, ensure_ascii=False)[:4000]}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def attempt(target: Any) -> str:
        import httpx

        url = f"{target.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {target.api_key}"}
        body = {
            "model": target.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 512,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(target.timeout)) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    try:
        content, target = await router.arun_with_fallback(
            ROLE_AGENT, attempt, defaults={"model": "deepseek-chat"}
        )
    except LlmCallError as e:
        raise NoModelError(f"没有可用的模型：{e}") from e

    raw = (content or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise NoModelError(f"模型输出无法解析：{raw[:200]!r}") from e
    return CodingStep.from_mapping(payload)


class CodingSession:
    """编码会话：planner 逐步给指令，run 经网关、edit 复用 patch_ops、落盘后跑验证。"""

    def __init__(
        self,
        task: str,
        *,
        cwd: str,
        agent_id: str = "trm-code",
        gateway: Any = None,
        planner: Any = None,
        session_id: Optional[str] = None,
        dry_run: bool = False,
        yes: bool = False,
        skill: Optional[str] = None,
        max_iterations: int = 20,
        command_timeout: float = 60.0,
        roots: Optional[Sequence[Path]] = None,
        hook: Any = None,
        specs: Optional[Sequence[verifier.VerificationSpec]] = None,
    ) -> None:
        self.task = task
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.cwd = str(Path(cwd).resolve())
        self.agent_id = agent_id
        self.gateway = gateway  # 惰性：run() 里才建
        self._planner = planner or plan_step_with_llm
        self.dry_run = dry_run
        self.yes = yes
        self.skill = skill
        self.max_iterations = max_iterations
        self.command_timeout = command_timeout
        self.roots = list(roots) if roots is not None else None
        self.hook = hook or EditPreviewHook(roots=self.roots)
        self.specs = list(specs) if specs is not None else None

    def _ensure_gateway(self) -> None:
        """懒建网关（AI 发起 ⇒ 接 LlmPolicyEngine，走唯一闸门）。"""
        if self.gateway is None:
            self.gateway = ToolGateway(
                interactive=False,
                audit_store=AuditStore(),
                llm_policy=build_default_llm_policy(),
            )

    async def run(self) -> SessionRecord:
        self._ensure_gateway()

        record = SessionRecord(
            task=self.task,
            session_id=self.session_id,
            cwd=self.cwd,
            dry_run=self.dry_run,
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

        # 技能注入（只做一次）
        blocks, problems = load_instructions(self.roots)
        if problems:
            log.warning("技能扫描问题：%s", problems)
        if self.skill:
            blocks = [b for b in blocks if b.name == self.skill]
            if not blocks:
                raise TrimumError(
                    TRMErrorCode.FILE_NOT_FOUND,
                    message=f"skill not found: {self.skill}",
                    context={"skill": self.skill},
                )
        matches = match_instructions(self.task, blocks, max_body_chars=DEFAULT_MAX_BODY_CHARS)
        plan = render_injection(matches, max_chars=DEFAULT_MAX_CHARS)
        record.skills = [m.block.name for m in plan.used]
        record.instructions = plan.text
        if plan.dropped or plan.problems:
            log.warning("技能注入 dropped=%s problems=%s", plan.dropped, plan.problems)

        history: list[dict] = [
            {"skills": record.skills, "instructions": plan.text, "problems": problems}
        ]

        finished = False
        for _ in range(self.max_iterations):
            step = await self._planner(self.task, history)
            if step is None or step.kind == STEP_DONE:
                record.steps.append(
                    {"kind": STEP_DONE, "status": "ok", "reason": "" if step is None else step.reason}
                )
                finished = True
                break

            if step.kind == STEP_RUN:
                record.steps.append(await self._run_step(step))
            elif step.kind == STEP_EDIT:
                applied = await self._edit_step(step, record)
                if applied:
                    await self._verify(record)
            else:
                record.steps.append(
                    {"kind": step.kind or "unknown", "status": "error", "reason": "unknown step kind"}
                )

        record.ended_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        failed_step = any(s.get("status") in {"error", "denied"} for s in record.steps)
        rejected = any(c.status == CHANGE_REJECTED for c in record.changes)
        verdicts = {v.verdict for v in record.verifications}
        red = verifier.VERDICT_RED in verdicts
        unverified = verifier.VERDICT_UNKNOWN in verdicts
        record.ok = (not failed_step) and (not rejected) and (not red) and (not unverified) and finished
        if failed_step:
            record.reason = REASON_STEP_FAILED
        elif rejected:
            record.reason = REASON_CHANGE_REJECTED
        elif red:
            record.reason = REASON_VERIFICATION_RED
        elif unverified:
            record.reason = "verification_unknown"
        elif not finished:
            record.reason = REASON_ITERATION_CAP
        else:
            record.reason = ""

        record.record_path = str(trimum_path("sessions", self.session_id) / "coding.json")
        try:
            out = Path(record.record_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8") as fh:
                json.dump(record.to_dict(), fh, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001 - 记录落盘失败不该毁掉会话
            log.warning("会话记录落盘失败：%s", e)

        return record

    async def _run_step(self, step: CodingStep) -> dict:
        started = time.monotonic()
        try:
            args = shlex.split(step.command)
        except ValueError as e:
            return {
                "kind": STEP_RUN,
                "status": "error",
                "command": step.command,
                "output": f"命令解析失败：{e}",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        if not args:
            return {
                "kind": STEP_RUN,
                "status": "error",
                "command": step.command,
                "output": "空命令",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        try:
            resp = await self.gateway.execute(
                ExecuteRequest(
                    tool=ToolType.SHELL,
                    args=args,
                    timeout_seconds=self.command_timeout,
                    agent_id=self.agent_id,
                    source_type=SourceType.AI,
                    # 会话的 cwd 就是项目根：命令必须在这里跑，否则 `cat note.txt`
                    # 之类的相对路径会落到调用方的进程目录（实测踩到）。
                    cwd=self.cwd,
                    skip_cwd_check=True,
                )
            )
            if resp.status in STEP_OK_STATUSES:
                status = "ok"
            elif resp.status == "denied":
                status = "denied"
            else:
                status = "error"
            return {
                "kind": STEP_RUN,
                "status": status,
                "command": step.command,
                "output": (resp.output or resp.error or ""),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        except Exception as e:  # noqa: BLE001 - 异常吞成 error 步，不抛
            log.warning("run 步异常：%s", e)
            return {
                "kind": STEP_RUN,
                "status": "error",
                "command": step.command,
                "output": str(e),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }

    async def _edit_step(self, step: CodingStep, record: SessionRecord) -> bool:
        """执行一步编辑；返回是否落盘（落盘后调用方才跑验证）。"""
        summary = step.reason or step.path
        # 相对路径锚在会话 cwd（与 run/验证同一口径）；绝对路径原样。
        target = Path(step.path)
        if not target.is_absolute():
            target = Path(self.cwd) / target
        note = self.hook.advise_preview(str(target), summary)
        change: SessionChange
        note2 = None
        try:
            res = patch_ops.replace_anchor(
                str(target),
                step.anchor,
                step.replacement,
                dry_run=(self.dry_run or not self.yes),
                session_id=self.session_id,
            )
            change = SessionChange(
                path=res.path,
                status=res.status,
                added_lines=res.added_lines,
                removed_lines=res.removed_lines,
                difference=res.difference,
                snapshot_id=res.snapshot_id,
                reason=res.reason,
            )
            if res.status == CHANGE_APPLIED:
                note2 = self.hook.advise_applied(str(target), summary)
        except TrimumError as e:
            change = SessionChange(path=str(target), status=CHANGE_REJECTED, reason=str(e))
            note2 = None

        entry = {
            "kind": STEP_EDIT,
            "status": change.status,
            "path": str(target),
            "reason": change.reason,
            "advice": list(note.advice),
            "problems": list(note.problems),
            "+": change.added_lines,
            "-": change.removed_lines,
        }
        if note2 is not None:
            entry["applied_advice"] = list(note2.advice)
        record.steps.append(entry)
        record.changes.append(change)
        return change.status == CHANGE_APPLIED

    async def _verify(self, record: SessionRecord) -> None:
        specs = self.specs if self.specs is not None else verifier.detect_project_specs(self.cwd)
        for spec in specs:
            loop = asyncio.get_running_loop()

            def _executor(spec, cwd, _loop=loop):
                fut = asyncio.run_coroutine_threadsafe(
                    self._run_argv(list(spec.command), spec.timeout_seconds, cwd), _loop
                )
                return verifier.outcome_from_response(fut.result())

            result = await asyncio.to_thread(
                verifier.run_verification, spec, cwd=self.cwd, executor=_executor
            )
            record.verifications.append(result)

    async def _run_argv(self, argv: list[str], timeout: float, cwd: str):
        return await self.gateway.execute(
            ExecuteRequest(
                tool=ToolType.SHELL,
                args=list(argv),
                cwd=cwd,
                timeout_seconds=timeout,
                agent_id=self.agent_id,
                source_type=SourceType.AI,
                skip_cwd_check=True,
            )
        )


__all__ = [
    "STEP_RUN",
    "STEP_EDIT",
    "STEP_DONE",
    "CHANGE_PREVIEW",
    "CHANGE_APPLIED",
    "CHANGE_REJECTED",
    "REASON_ITERATION_CAP",
    "REASON_STEP_FAILED",
    "REASON_CHANGE_REJECTED",
    "REASON_VERIFICATION_RED",
    "CodingStep",
    "SessionChange",
    "SessionRecord",
    "ScriptedPlanner",
    "NoModelError",
    "plan_step_with_llm",
    "CodingSession",
]
