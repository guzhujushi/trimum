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
import json
import logging
import time
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
from .live_console import LiveConsole
from .config import Config

log = logging.getLogger("trimum_core.agent_loop")


class AgentLoop:
    """交互式 Agent 执行循环。

    Usage:
        loop = AgentLoop()
        await loop.run("删除 /tmp 下所有 .log 文件")
    """

    def __init__(
        self,
        gateway: Optional[ToolGateway] = None,
        event_bus: Optional[EventBus] = None,
        console: Optional[LiveConsole] = None,
        llm_policy: Optional[LlmPolicyEngine] = None,
        config: Optional[Config] = None,
        agent_name: str = "trm-exec",
    ):
        self.gateway = gateway or ToolGateway(interactive=False)
        self.event_bus = event_bus or EventBus()
        self.console = console or LiveConsole(self.event_bus)
        self.agent_name = agent_name

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

    # ── 主入口 ──

    async def run(self, prompt: str) -> list[dict]:
        """执行一个自然语言指令。

        返回 [(step_name, result_dict), ...]
        """
        self.console.info(f"正在分析: {prompt}", emoji="🔍")

        # 1. LLM 制定计划
        plan = await self._plan(prompt)
        if not plan or "steps" not in plan:
            self.console.error("无法生成执行计划，请描述得更具体一些")
            return []

        # 2. 展示计划
        self.console.divider()
        self.console.show_plan(plan.get("title", "执行计划"), plan["steps"])
        self.console.divider()

        # 3. 订阅 Event Bus
        await self.console.subscribe_events("agent")

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

        return results

    # ── LLM 计划 ──

    async def _plan(self, prompt: str) -> Optional[dict]:
        """调用 LLM 将自然语言转换为执行计划。"""
        import httpx
        import os

        llm_cfg = self.sec_config.get_llm_config()
        base_url = llm_cfg.get("base_url", "https://api.deepseek.com/v1")
        model = llm_cfg.get("model", "deepseek-chat")
        api_key = llm_cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
        timeout_s = llm_cfg.get("timeout_seconds", 15)

        if not api_key:
            self.console.warning("未配置 API key，使用正则模式（不支持自然语言）")
            return self._fallback_plan(prompt)

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
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 1024,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]

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

        if ev_action == Action.CONFIRM or interactive:
            ok = await self.console.confirm(f"执行: {command}", default=False)
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

            if resp.status == "ok":
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
                "status": resp.status,
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
        import httpx
        import os

        llm_cfg = self.sec_config.get_llm_config()
        base_url = llm_cfg.get("base_url", "https://api.deepseek.com/v1")
        model = llm_cfg.get("model", "deepseek-chat")
        api_key = llm_cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")

        if not api_key:
            return ""

        summary_prompt = f"""用户要求: {prompt}
执行结果:
{json.dumps(results, ensure_ascii=False, indent=2)}

用一句话总结发生了什么，不要超过 3 行。
"""

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "简洁总结执行结果，不超过3行。"},
                            {"role": "user", "content": summary_prompt},
                        ],
                        "temperature": 0.0,
                        "max_tokens": 200,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            return ""

    # ── Event Bus 发布 ──

    async def _publish(self, event_type: str, **kwargs):
        try:
            await self.event_bus.publish_sync("agent." + event_type, kwargs)
        except Exception:
            pass


__all__ = ["AgentLoop"]
