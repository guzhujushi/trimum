"""Agent Loop — 交互式 AI Agent 执行循环。

trm exec <自然语言指令> 的核心引擎。

流程：
    1. LLM 理解自然语言 → 生成计划（多步骤）
    2. 展示计划给用户
    3. 对每个步骤：
       a. 安全评估（PolicyEngine + LlmPolicyEngine）
       b. 高风险 → 用户确认
       c. 执行（ToolGateway）
       d. 显示进度 / 发布 Event Bus 事件
    4. LLM 汇总结果 → 终端展示
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .event_bus import EventBus
from .tool_gateway import ToolGateway
from .policy_engine import PolicyEngine
from .models import (
    ExecuteRequest,
    ExecuteResponse,
    RiskLevel,
    Action,
    SecurityMode,
    SourceType,
    ToolType,
)
from .security_config import SecurityConfig
from .llm_policy import LlmPolicyEngine
from .file_trust import FileTrustTracker
from .live_console import LiveConsole, TokenStatusPanel
from .config import Config
from .context_compactor import CompactionPolicy, ContextCompactor
from .audit_store import AuditStore
from .resource_controller import TokenUsageTracker, TokenUsage, PsutilController

log = logging.getLogger("trimum_core.agent_loop")

# 网关认为「执行成功」的状态：allowed / confirmed / success。
# 网关此前用 "ok" 做判定，但 ToolGateway 与 Dispatcher 从不返回 "ok"，
# 导致交互式循环里成功的步骤被当成失败（Phase 3 收尾 P1）。
STEP_OK_STATUSES = frozenset({"allowed", "confirmed", "success"})
STEP_ERROR_STATUSES = frozenset({"denied", "error", "timeout", "jit_required"})
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def _image_to_data_url(path: str) -> str:
    """Read an image file and return a base64 data URL."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    mime = _IMAGE_MIME.get(p.suffix.lower())
    if not mime:
        raise ValueError(f"unsupported image format: {p.suffix} ({path})")
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _build_user_content(text: str, images: list[str] | None = None) -> "str | list[dict]":
    """Build user message content; plain string when no images, multimodal list otherwise."""
    if not images:
        return text
    parts: list[dict] = [{"type": "text", "text": text}]
    for img_path in images:
        data_url = _image_to_data_url(img_path)
        parts.append({"type": "image_url", "image_url": {"url": data_url}})
    return parts


@dataclass
class InteractiveLoopConfig:
    """交互式循环配置。

    max_iterations:      最大迭代次数（防止无限循环）
    interactive_mode:    交互模式：
                         "full"   — 全程可确认/修改/跳过
                         "review" — 每次回顾时确认
                         "auto"   — 低风险自动跑，高风险弹窗
    operator_mode:       Operator 模式，允许循环中修改 prompt
    confirm_plan:        是否在生成计划后要求用户确认
    step_by_step_confirm: 是否每步都要求确认
    use_live_panel:      是否使用 Rich Live 实时面板
    """
    max_iterations: int = 20
    interactive_mode: str = "full"
    operator_mode: bool = True
    confirm_plan: bool = True
    step_by_step_confirm: bool = True
    use_live_panel: bool = True  # 预留，当前版本使用静态 console

    def __post_init__(self):
        valid_modes = {"full", "review", "auto"}
        if self.interactive_mode not in valid_modes:
            raise ValueError(f"interactive_mode 必须是 {valid_modes}，传入 {self.interactive_mode}")


class AgentLoop:
    """交互式 Agent 执行循环。

    支持两种运行模式：
    1. run()              — 一次性计划执行（原有模式）
    2. run_interactive()  — 多步循环模式（LLM 分析结果→生成下一步→直到完成）

    Usage:
        loop = AgentLoop()
        # 一次性执行
        await loop.run("删除 /tmp 下所有 .log 文件")
        # 多步循环
        await loop.run_interactive("写个 python 脚本统计 /var/log 各文件大小")
    """

    def __init__(
        self,
        gateway: Optional[ToolGateway] = None,
        event_bus: Optional[EventBus] = None,
        console: Optional[LiveConsole] = None,
        llm_policy: Optional[LlmPolicyEngine] = None,
        config: Optional[Config] = None,
        agent_name: str = "trm-exec",
        stream_output: bool = False,
        context_manager: Optional[Any] = None,
        compactor: Optional[ContextCompactor] = None,
        compaction_policy: Optional[CompactionPolicy] = None,
    ):
        self.event_bus = event_bus or EventBus()
        # 审计落盘 + 广播：与 daemon 一致，方便 `trm log audit` 统一查询
        self.gateway = gateway or ToolGateway(
            interactive=False,
            event_bus=self.event_bus,
            audit_store=AuditStore(),
        )
        self.console = console or LiveConsole(self.event_bus)
        self.agent_name = agent_name
        self.stream_output = bool(stream_output)
        self.context_manager = context_manager
        # 上下文窗口管理（P0）：工具输出限长 + 滑窗 + 早期步骤摘要
        self.compactor = compactor or ContextCompactor(compaction_policy)

        # 安全组件
        sec_config = SecurityConfig()
        sec_config.load()
        self.sec_config = sec_config

        self.policy = PolicyEngine()
        self.ft_tracker = FileTrustTracker(db_path=":memory:")
        self.llm_policy = llm_policy or LlmPolicyEngine(
            policy_engine=self.policy,
            security_config=sec_config,
            file_trust_tracker=self.ft_tracker,
        )

        # 默认安全等级
        self.mode: SecurityMode = sec_config.get_mode(agent_name)

        # 循环配置（默认 full interactive）
        self.loop_config: InteractiveLoopConfig = InteractiveLoopConfig()

        # Token 资源追踪（可视化用）
        self.token_tracker = TokenUsageTracker(window_minutes=5)
        self.resource_controller = PsutilController()
        self._token_panel = TokenStatusPanel()

    def get_token_usage(self) -> TokenUsage:
        """Return the tracked token usage for this agent loop."""
        return self.token_tracker.get_usage(self.agent_name)

    def _print_token_usage(self) -> None:
        """Print a compact token-usage line when tracking produced data."""
        usage = self.get_token_usage()
        if usage.calls <= 0 and usage.total_tokens <= 0:
            return
        self.console.print(
            f"📊  Token — {usage.total_tokens} total "
            f"({usage.prompt_tokens} prompt + {usage.completion_tokens} completion) "
            f"| 调用: {usage.calls} 次"
        )

    def _record_token_usage(self, usage: TokenUsage) -> None:
        if (
            usage.calls <= 0
            and usage.total_tokens <= 0
            and usage.prompt_tokens <= 0
            and usage.completion_tokens <= 0
        ):
            return
        if usage.calls <= 0:
            usage.calls = 1
        self.token_tracker.record(self.agent_name, usage)

    def _write_stream(self, text: str) -> None:
        """Incrementally print a streamed LLM delta."""
        if self.stream_output and text:
            self.console.print(text, end="")

    @staticmethod
    def _parse_sse_line(line: str) -> Optional[dict]:
        """Parse one OpenAI-compatible SSE ``data:`` line."""
        if not line or not line.startswith("data:"):
            return None
        data = line[5:].strip()
        if not data or data == "[DONE]":
            return None
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _token_usage_from_payload(payload: dict) -> TokenUsage:
        """Extract ``TokenUsage`` from a chat-completion response payload."""
        usage = payload.get("usage") or {}

        def _int(key: str) -> int:
            try:
                return int(usage.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        prompt = _int("prompt_tokens")
        completion = _int("completion_tokens")
        total = _int("total_tokens") or (prompt + completion)
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            calls=1,
        )

    async def _chat_completion(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        timeout: float,
        stream: bool = False,
    ) -> tuple[str, TokenUsage]:
        """Call the configured chat-completion endpoint and return (text, usage).

        经 llm_router：agent 角色由 .env 决定用谁（本项目分工是主 deepseek-flash、
        备交我算），429/5xx/超时自动换 provider，并按 RPM 限流；全都不可用时
        返回空内容（调用方各自走正则/TARL 降级）。
        """
        import httpx

        from . import llm_router

        llm_cfg = self.sec_config.get_llm_config()

        async def _attempt(target: "llm_router.LlmTarget") -> tuple[str, TokenUsage]:
            url = f"{target.base_url.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {target.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": target.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            timeout_cfg = httpx.Timeout(target.timeout)

            async with httpx.AsyncClient(timeout=timeout_cfg) as client:
                if not (stream and self.stream_output):
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return content, self._token_usage_from_payload(data)

                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    resp.raise_for_status()
                    parts: list[str] = []
                    usage = TokenUsage(calls=1)
                    async for line in resp.aiter_lines():
                        chunk = self._parse_sse_line(line)
                        if chunk is None:
                            continue
                        delta = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            parts.append(delta)
                            self._write_stream(delta)
                        if chunk.get("usage"):
                            usage = self._token_usage_from_payload({"usage": chunk["usage"]})

                    content = "".join(parts)
                    if content and not usage.total_tokens:
                        usage = TokenUsage(
                            prompt_tokens=0,
                            completion_tokens=max(1, len(content) // 4),
                            total_tokens=max(1, len(content) // 4),
                            calls=1,
                        )
                    return content, usage

        try:
            result, target = await llm_router.arun_with_fallback(
                llm_router.ROLE_AGENT,
                _attempt,
                defaults={
                    "model": model,
                    "base_url": llm_cfg.get("base_url", "https://api.deepseek.com/v1"),
                    "api_key": llm_cfg.get("api_key"),
                    "api_key_env": llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY"),
                    "timeout": timeout,
                    "max_retries": llm_cfg.get("max_retries", 1),
                    "rpm": llm_cfg.get("rpm"),
                },
            )
        except llm_router.LlmCallError as e:
            log.warning("chat completion failed: %s", e)
            return "", TokenUsage()

        log.debug("agent loop: 本次会话来自 %s", target.label)
        return result

    # ── 主入口 ──

    async def run(self, prompt: str, *, images: list[str] | None = None) -> list[dict]:
        """执行一个自然语言指令。

        返回 [(step_name, result_dict), ...]
        """
        self.console.info(f"正在分析: {prompt}", emoji="🔍")

        # 1. LLM 制定计划
        plan = await self._plan(prompt, images=images)
        if not plan or "steps" not in plan:
            self.console.error("无法生成执行计划，请描述得更具体一些")
            return []

        # 2. 展示计划
        self.console.divider()
        self.console.show_plan(plan.get("title", "执行计划"), plan["steps"])
        self.console.divider()

        # 3. 订阅 Event Bus（task.* 任务事件）
        await self.console.subscribe_events("task")

        # 4. 逐步执行
        results = []
        for step in plan["steps"]:
            result = await self._execute_step(step)
            results.append(result)

        # 5. 取消订阅
        self.console.unsubscribe()

        # 6. LLM 汇总
        self.console.divider()
        summary = await self._summarize(prompt, results)
        self.console.show_summary(results)
        if summary:
            self.console.info(summary, emoji="📋")

        self._print_token_usage()

        return results

    # ── LLM 计划 ──

    async def _plan(self, prompt: str, *, images: list[str] | None = None) -> Optional[dict]:
        """调用 LLM 将自然语言转换为执行计划。"""
        llm_cfg = self.sec_config.get_llm_config()
        model = llm_cfg.get("model", "deepseek-chat")
        timeout_s = llm_cfg.get("timeout_seconds", 15)

        system_prompt = """你是一个安全的 Shell 助手。你需要将用户自然语言指令拆解为可执行的步骤。

返回 JSON 格式（不要多余文字）：
{
    "title": "简短计划标题",
    "steps": [
        {
            "name": "步骤名称",
            "description": "简短说明",
            "command": "要执行的 shell 命令",
            "risk": "low|medium|high|critical",
            "interactive": false
        }
    ]
}

规则：
- 优先用安全的命令（ls/cat/find 等）
- 写文件/删除文件/安装软件要有用户确认（interactive: true）
- 永远不要生成破坏性命令
- 如果任务复杂，拆成多个小步骤"""

        try:
            content, usage = await self._chat_completion(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": _build_user_content(prompt, images)},
                ],
                temperature=0.1,
                max_tokens=1024,
                timeout=timeout_s,
            )
            self._record_token_usage(usage)

            if not content:
                return self._fallback_plan(prompt)

            # 提取 JSON
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            content = content.strip()

            plan = json.loads(content)
            if "steps" not in plan or not isinstance(plan["steps"], list):
                raise ValueError("invalid plan format")

            return plan

        except Exception as e:
            log.warning("LLM plan failed: %s", e)
            self.console.warning(f"LLM 分析失败，使用正则回退: {e}")
            return self._fallback_plan(prompt)

    def _fallback_plan(self, prompt: str) -> dict:
        """LLM 不可用时的正则回退：把整条指令当单步执行。"""
        return {
            "title": "直接执行",
            "steps": [{
                "name": "执行命令",
                "description": prompt,
                "command": prompt,
                "risk": "medium",
                "interactive": True,
            }],
        }

    # ── 多步循环模式 ──

    async def run_interactive(self, task: str, loop_config: Optional[InteractiveLoopConfig] = None) -> list[dict]:
        """多步交互式 Agent 循环。

        流程：
        LLM 分析任务 → 执行第一步 → 结果反馈 LLM → LLM 分析下一步 → 直到完成

        Operator 模式：循环中可输入 /continue /stop /retry /edit <cmd> 等指令
        """
        if loop_config:
            self.loop_config = loop_config

        config = self.loop_config
        results: list[dict] = []
        context_history: list[dict] = []  # 每步结果 -> 供 LLM 分析下一步

        self.console.divider()
        self.console.info(f"🎯 任务: {task}")
        self.console.info(f"交互模式: {config.interactive_mode} | Operator模式: {'开' if config.operator_mode else '关'}")
        self.console.divider()

        if self.context_manager is not None:
            try:
                await self.context_manager.register_session(
                    self.agent_name,
                    "interactive",
                    metadata={"task": task},
                )
            except Exception:
                pass

        # 第一步：LLM 分析任务生成首个计划
        first_step = await self._plan_single_step(task, context=None)
        if not first_step or "command" not in first_step:
            self.console.error("无法生成执行计划")
            return []

        plan = {"title": "循环执行", "steps": [first_step]}
        self.console.show_plan(plan.get("title", "执行计划"), plan["steps"])

        # 计划确认
        if config.confirm_plan:
            ok = await self.console.confirm("确认开始执行计划?")
            if not ok:
                self.console.info("已取消")
                return []

        current_step = first_step
        iteration = 0

        while iteration < config.max_iterations:
            iteration += 1
            self.console.info(f"— 第 {iteration}/{config.max_iterations} 轮 —")

            # 执行当前步骤
            step_result = await self._execute_step(current_step)
            results.append(step_result)
            context_history.append({
                "step": current_step,
                "result": step_result,
            })

            # 更新资源/Token 追踪面板
            try:
                usage = await self.resource_controller.get_usage(self.agent_name)
                tok = self.token_tracker.get_usage(self.agent_name)
                self._token_panel.update(
                    cpu_percent=usage.cpu_percent,
                    memory_mb=usage.memory_mb,
                    token_used=tok.total_tokens,
                    token_limit=10000,
                    calls_5min=tok.calls,
                    calls_limit=30,
                )
            except Exception:
                pass

            # 检查是否完成
            if step_result.get("status") == "ok" and current_step.get("done", False):
                self.console.success("✅ 任务完成!")
                break

            # 检查执行失败
            if step_result.get("status") == "error":
                if config.operator_mode:
                    choice = await self.console.prompt("执行出错。输入 /retry 重试, /edit <cmd> 修改命令, /stop 中止")
                    if choice == "/stop":
                        break
                    current_step = self._handle_operator_edit(choice, current_step)
                    continue
                else:
                    self.console.error(f"步骤执行失败: {step_result.get('error', '未知错误')}")
                    break

            # LLM 分析上一步结果，决定下一步
            next_step = await self._plan_single_step(task, context=context_history)

            # LLM 判定任务完成
            if not next_step or next_step.get("done", False):
                self.console.success("✅ LLM 判定任务已完成!")
                break

            # 展示下一步前，提供 Operator 介入机会
            if config.operator_mode:
                self.console.info(f"下一步建议: {next_step.get('name', '')} — {next_step.get('command', '')}")
                choice = await self.console.prompt("回车继续, 或输入 /skip 跳过 /stop 中止 /edit <cmd> 修改")
                if choice == "/stop":
                    break
                elif choice == "/skip":
                    continue
                elif choice == "/edit":
                    choice2 = await self.console.prompt("新命令: ")
                    next_step["command"] = choice2

            current_step = next_step

        # 最终总结：展示资源消耗面板
        self.console.divider()
        tok = self.token_tracker.get_usage(self.agent_name)
        self.console.print(f"📊  资源消耗 — Token: {tok.total_tokens} ({tok.prompt_tokens} prompt + {tok.completion_tokens} completion) | 调用: {tok.calls} 次")
        if self.context_manager is not None:
            try:
                await self.context_manager.update_session(
                    self.agent_name,
                    {
                        "last_task": task,
                        "result_count": len(results),
                        "total_tokens": tok.total_tokens,
                        "calls": tok.calls,
                    },
                )
            except Exception:
                pass
        self.console.show_summary(results)
        summary = await self._summarize(task, results)
        if summary:
            self.console.info(summary, emoji="📋")

        return results

    def _handle_operator_edit(self, choice: str, step: dict) -> dict:
        """处理 Operator 指令：/edit <cmd> 修改命令。"""
        prefix = "/edit "
        if choice.startswith(prefix):
            new_cmd = choice[len(prefix):].strip()
            if new_cmd:
                step["command"] = new_cmd
                self.console.info(f"已修改命令: {new_cmd}", emoji="✏️")
        return step

    async def _plan_single_step(self, task: str, context: Optional[list[dict]]) -> Optional[dict]:
        """调用 LLM 生成单步计划。返回 step dict 或 None。"""
        llm_cfg = self.sec_config.get_llm_config()
        model = llm_cfg.get("model", "deepseek-chat")
        timeout_s = llm_cfg.get("timeout_seconds", 15)

        sys_prompt = """你是安全的 Shell 助手。结合上下文决定下一步执行什么。

返回 JSON，字段：
{
    "name": "步骤名",
    "command": "要执行的命令",
    "risk": "low|medium|high|critical",
    "done": true/false,   // true=任务已完成，无需更多步骤
    "reason": "为什么这么做"
}

规则：
- 优先用安全的命令
- 删除/写入/安装需要 high 风险
- 如果任务已完成，done=true 且 command 可为空"""

        # 构建消息
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"任务: {task}\n"},
        ]

        if context:
            # 附加上下文历史（限长 + 滑窗 + 摘要，见 ContextCompactor）
            context_text = self.compactor.build(context)
            messages.append({"role": "user", "content": f"执行历史:\n{context_text}\n\n下一步?"})

        try:
            content, usage = await self._chat_completion(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=512,
                timeout=timeout_s,
            )
            self._record_token_usage(usage)

            if not content:
                return self._fallback_single_step(task)

            # 提取 JSON
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            content = content.strip()

            step = json.loads(content)
            if "command" in step and step.get("command"):
                return step
            if step.get("done"):
                return {"name": "done", "command": "", "risk": "low", "done": True, "reason": step.get("reason", "")}
            return None

        except Exception as e:
            log.warning("LLM 单步计划失败: %s", e)
            return self._fallback_single_step(task)

    def _fallback_single_step(self, task: str) -> dict:
        """无 LLM 时的单步回退。"""
        return {
            "name": "执行命令",
            "command": task,
            "risk": "medium",
            "done": False,
            "reason": "LLM 不可用，直接执行",
        }

    # ── 单步执行 ──

    async def _execute_step(self, step: dict) -> dict:
        """执行一个步骤，包含安全确认。"""
        name = step.get("name", "未知步骤")
        command = step.get("command", "")
        risk_str = step.get("risk", "medium")
        interactive = step.get("interactive", False)
        description = step.get("description", "")

        # 1. 安全评估
        try:
            risk = RiskLevel(risk_str)
        except ValueError:
            risk = RiskLevel.MEDIUM

        # 用 LlmPolicyEngine 做安全分析（带缓存）
        try:
            ev_risk, ev_action, ev_reason = await self.llm_policy.evaluate(
                command=command,
                source_type=SourceType.AI,
                mode=self.mode,
            )
        except Exception:
            ev_risk, ev_action, ev_reason = risk, Action.CONFIRM, "评估失败，默认确认"

        self.console.step_start(name)

        start_ts = time.time()

        # 2. 安全确认
        if ev_action == Action.DENY:
            self.console.error(f"已拒绝: {ev_reason}")
            self.console.step_skip(name, "安全策略拒绝")
            await self._publish("task.skipped", name=name, reason=ev_reason)
            return {
                "name": name, "status": "denied", "output": ev_reason,
                "elapsed_ms": 0, "command": command,
            }

        # 增强确认交互：展示操作摘要
        if ev_action == Action.CONFIRM or interactive:
            # 逐行展示摘要
            summary_lines = [
                f"  {'操作':>8}: {name}",
                f"  {'命令':>8}: {command[:120]}{'...' if len(command) > 120 else ''}",
                f"  {'风险':>8}: {ev_risk.name}",
                f"  {'说明':>8}: {ev_reason or description}",
            ]
            for line in summary_lines:
                self.console.print(line)

            ok = await self.console.confirm(f"执行以上操作?", default=False)
            if not ok:
                # Operator 模式：可选择修改后执行
                if self.loop_config.operator_mode:
                    modify = await self.console.confirm("是否修改命令?", default=False)
                    if modify:
                        new_cmd = await self.console.prompt("新命令", default=command)
                        command = new_cmd
                        ok = True  # 修改后放行
                if not ok:
                    self.console.step_skip(name, "用户取消")
                    await self._publish("task.skipped", name=name, reason="用户取消")
                    return {
                        "name": name, "status": "cancelled", "output": "用户取消",
                        "elapsed_ms": 0, "command": command,
                    }

        # 3. 执行
        await self._publish("task.started", name=name, command=command)

        try:
            self.console.info(command, emoji="⚡")

            req = ExecuteRequest(
                tool=ToolType.SHELL,
                args=command.strip().split(),
                env={},
                cwd=None,
                timeout_seconds=60,
                agent_id=self.agent_name,
                source_type=SourceType.AI,
                skip_cwd_check=True,
            )

            resp: ExecuteResponse = await self.gateway.execute(req)

            elapsed = int((time.time() - start_ts) * 1000)

            step_ok = resp.status in STEP_OK_STATUSES
            if step_ok:
                output_text = resp.output or ""
                self.console.step_output(output_text)
                self.console.step_done(name)
                await self._publish("task.completed", name=name, status=resp.status)
            else:
                err_text = resp.error or "未知错误"
                self.console.step_output(err_text)
                self.console.warning(f"步骤出错: {err_text}")
                await self._publish("task.completed", name=name, status=resp.status, error=err_text)

            return {
                "name": name,
                "status": "ok" if step_ok else "error",
                "gateway_status": resp.status,
                "output": resp.output or resp.error or "",
                "elapsed_ms": elapsed,
                "command": command,
            }

        except Exception as e:
            elapsed = int((time.time() - start_ts) * 1000)
            self.console.error(f"执行异常: {e}")
            await self._publish("task.failed", name=name, error=str(e))
            return {
                "name": name, "status": "error", "output": str(e),
                "elapsed_ms": elapsed, "command": command,
            }

    # ── LLM 总结 ──

    async def _summarize(self, prompt: str, results: list[dict]) -> str:
        """用 LLM 总结执行结果。"""
        llm_cfg = self.sec_config.get_llm_config()
        model = llm_cfg.get("model", "deepseek-chat")

        summary_prompt = f"""用户要求: {prompt}
执行结果:
{json.dumps(results, ensure_ascii=False, indent=2)}

用一句话总结发生了什么，不要超过 3 行。
"""

        try:
            content, usage = await self._chat_completion(
                model=model,
                messages=[
                    {"role": "system", "content": "简洁总结执行结果，不超过3行。"},
                    {"role": "user", "content": summary_prompt},
                ],
                temperature=0.0,
                max_tokens=200,
                timeout=10,
                stream=True,
            )
            self._record_token_usage(usage)
            if self.stream_output:
                self.console.print("")
            return content
        except Exception:
            return ""

    # ── Event Bus 发布 ──

    async def _publish(self, event_type: str, **kwargs):
        try:
            # ``emit_task`` prepends the ``task.`` namespace, so strip a
            # caller-supplied prefix to avoid ``task.task.started``.
            task_type = event_type
            if task_type.startswith("task."):
                task_type = task_type[len("task."):]
            await self.event_bus.emit_task(task_type, kwargs, source=self.agent_name)
        except Exception:
            pass


__all__ = ["AgentLoop"]
