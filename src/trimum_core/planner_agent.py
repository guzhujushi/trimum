"""Planner Agent — 自然语言 → Workflow YAML 智能分解

Planner Agent 将用户的自然语言请求分解为可执行的 Workflow：
1. 调用 LLM（通过 Agent SDK）分析请求并生成结构化 Workflow JSON
2. 将 JSON 转换为 WorkflowDefinition 并保存为 YAML（~/.trimum/workflows/<name>.yaml）
3. 交给 WorkflowEngine 执行
5. 失败时 emit event.planner.failed

架构要点：
- 使用 Agent SDK（TrimumAgent）替代裸 urllib，支持 per-agent 模型配置
- 输出为 YAML 文件，由 WorkflowEngine 加载执行
- 支持 LLM 回落（降级到默认模型）
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import yaml

from .models import (
    EventSeverity,
    SystemEvent,
)
from .workflow_engine import (
    EdgeCondition,
    EdgeDefinition,
    NodeDefinition,
    WorkflowDefinition,
)
from .event_bus import EventBus, NAMESPACE_EVENT, NAMESPACE_TASK

# ---------------------------------------------------------------------------
# Agent SDK — 可选导入 (Planner 特有)
# ---------------------------------------------------------------------------

try:
    from pydantic_ai import Agent as PydanticAgent
    from agent_sdk import TrimumAgent

    _HAS_AGENT_SDK = True
except ImportError:
    _HAS_AGENT_SDK = False


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_WORKFLOW_DIR = Path.home() / ".trimum" / "workflows"

# Planner Agent 专属环境变量前缀
PLANNER_ENV_MODEL = "PLANNER_LLM_MODEL"
PLANNER_ENV_BASE_URL = "PLANNER_LLM_BASE_URL"
PLANNER_ENV_API_KEY = "PLANNER_LLM_API_KEY"

# 全局回落
GLOBAL_ENV_MODEL = "TRIMUM_LLM_MODEL"
GLOBAL_ENV_BASE_URL = "TRIMUM_LLM_BASE_URL"
GLOBAL_ENV_API_KEY = "TRIMUM_LLM_API_KEY"

# ── urllib 回落函数（当 Agent SDK 不可用时） ──────────────────

import urllib.error
import urllib.request


def _call_llm_api_fallback(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> str:
    """用 urllib 直接调用 OpenAI 兼容 API（Agent SDK 不可用时的回落）。"""
    model = model or os.environ.get(PLANNER_ENV_MODEL) or os.environ.get(GLOBAL_ENV_MODEL, "deepseek-chat")
    base_url = base_url or os.environ.get(PLANNER_ENV_BASE_URL) or os.environ.get(GLOBAL_ENV_BASE_URL,
                                          "https://models.sjtu.edu.cn/api/v1")
    api_key = api_key or os.environ.get(PLANNER_ENV_API_KEY) or os.environ.get(GLOBAL_ENV_API_KEY, "")

    if not api_key:
        raise RuntimeError("PlannerAgent: API Key 未设置 (检查 PLANNER_LLM_API_KEY 或 TRIMUM_LLM_API_KEY)")

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"LLM API HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:500]}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"LLM API 调用失败: {e}") from e

    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError(f"LLM API 返回空 choices: {json.dumps(body, ensure_ascii=False)[:300]}")

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("LLM API 返回空 content")

    return content


# ---------------------------------------------------------------------------
# LLM System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """你是一个 AI Agent 运行时 (trimum) 的 Planner Agent，负责将用户的自然语言请求分解为可执行的 Workflow。
## 可用能力 (Agent 可调用的 capabilities)
{capabilities_str}

## 输出格式
你必须输出 JSON 格式的 WorkflowDefinition，包含 nodes 和 edges：
```json
{{
  "workflow_name": "简短描述, 用英文小写加下划线",
  "description": "详细描述, 说明这个 workflow 做什么",
  "nodes": [
    {{
      "id": "步骤_id",
      "label": "步骤的简短标签",
      "handler": "capability 名称, 如 system.monitor.disk",
      "config": {{
        "command": "如果是 shell 命令 (适用于 handler == shell.exec)",
        "message": "如果是通知消息 (适用于 handler == agent.notify)",
        ...
      }},
      "timeout_seconds": 60,
      "retry_count": 0
    }}
  ],
  "edges": [
    {{
      "source": "上游节点id",
      "target": "下游节点id",
      "condition": {{
        "type": "always"
      }}
    }}
  ]
}}
```

## 条件类型
- "always": 无条件串联（默认）
- "on_complete": 上游完成后自动触发下游
- "on_fail": 上游失败时触发下游（错误处理）
- "expression": 条件表达式, 如 {{"type": "expression", "expression": "result.get('usage', 0) > 80"}}

## 规则
1. 节点按执行顺序排列 (nodes[0] 到 nodes[n-1])
2. 边连接节点的顺序，使用 handler 中定义的能力
3. 默认边类型为 "always" 表示无条件顺序执行
4. 每个独立任务使用单独节点，不使用折线/合并节点
5. timeout_seconds 默认为 30
6. 复杂任务 timeout_seconds 默认为 120
7. 除非明确说明，retry_count=0 (不重试)
8. 执行失败时，返回 {{"error": "失败原因描述"}}
"""


# ---------------------------------------------------------------------------
# PlannerAgent
# ---------------------------------------------------------------------------


class PlannerAgent:
    """Planner Agent — 自然语言 → Workflow YAML。

    接收用户自然语言请求，通过 LLM 分解并生成 WorkflowDefinition，
    保存为 YAML 文件。通过 Event Bus 与 Runtime 通信。
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        workflow_dir: str | Path | None = None,
        available_capabilities: list[str] | None = None,
        # LLM 配置（Planner 专属，覆盖全局）
        llm_model: str | None = None,
        llm_base_url: str | None = None,
        llm_api_key: str | None = None,
        # Agent SDK 集成
        use_agent_sdk: bool = True,
    ) -> None:
        self._bus = event_bus
        self._workflow_dir = Path(workflow_dir or DEFAULT_WORKFLOW_DIR)
        self._available_capabilities = available_capabilities or ["shell.exec", "system.monitor"]
        self._use_agent_sdk = use_agent_sdk and _HAS_AGENT_SDK

        # Planner 专属模型配置（优先级：构造参数 > 环境变量 > 全局环境变量）
        self._llm_kwargs: dict[str, str | None] = {
            "model": llm_model or os.environ.get(PLANNER_ENV_MODEL) or os.environ.get(GLOBAL_ENV_MODEL),
            "base_url": llm_base_url or os.environ.get(PLANNER_ENV_BASE_URL) or os.environ.get(GLOBAL_ENV_BASE_URL),
            "api_key": llm_api_key or os.environ.get(PLANNER_ENV_API_KEY) or os.environ.get(GLOBAL_ENV_API_KEY),
        }

        # 初始化 Agent SDK 包装器（如果可用）
        self._sdk_agent: TrimumAgent | None = None
        if self._use_agent_sdk:
            self._init_sdk_agent()

        # 创建工作流目录
        self._workflow_dir.mkdir(parents=True, exist_ok=True)

    # ── Agent SDK 初始化 ──────────────────────────────────

    def _init_sdk_agent(self) -> None:
        """初始化 Agent SDK 的 TrimumAgent 包装器。"""
        if not _HAS_AGENT_SDK:
            self._use_agent_sdk = False
            return

        model = self._llm_kwargs.get("model") or "deepseek-chat"

        # 构建 Pydantic AI model 字符串
        # 注意：pydantic_ai 需要格式如 "openai:model-name"
        # 对于自定义 provider，我们使用 logfire 或其他方式
        # 这里使用 pydantic_ai 的 OpenAI provider
        if "sjtu" in str(self._llm_kwargs.get("base_url", "")):
            model_str = f"openai:{model}"
        else:
            model_str = f"openai:{model}"

        try:
            base = PydanticAgent(
                model_str,
                system_prompt="你是一个 Planner Agent，将用户请求分解为 WorkflowDefinition。",
            )
            self._sdk_agent = TrimumAgent(
                base_agent=base,
                agent_id="planner-agent",
                event_bus=self._bus,
            )
        except Exception as e:
            print(f"[PlannerAgent] Agent SDK 初始化失败，恢复到 urllib: {e}")
            self._use_agent_sdk = False
            self._sdk_agent = None

    # ── 核心接口 ──────────────────────────────────────────

    async def run(
        self,
        request: str,
        context: dict[str, Any] | None = None,
    ) -> WorkflowDefinition | None:
        """分解自然语言请求 → LLM 分析 → 验证 → 保存 → 返回 WorkflowDefinition。

        参数:
            request: 用户自然语言请求
            context: 额外的上下文信息（可选）

        返回:
            WorkflowDefinition 或 None（失败时）
        """
        context = context or {}
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"

        await self._bus.emit_event("planner.started", "planner_agent", {
            "plan_id": plan_id,
            "request_preview": request[:200],
        })

        try:
            # 1. LLM 调用（优先 Agent SDK，回落 urllib）
            workflow_json = await self._decompose_with_llm(request, context)
            if workflow_json is None:
                raise RuntimeError("LLM 返回空 Workflow 数据")

            # 2. JSON → WorkflowDefinition
            wf_def = self._json_to_workflow(workflow_json, plan_id)

            # 3. 验证
            self._validate_workflow(wf_def)

            # 4. 保存 YAML
            filepath = self._save_workflow(wf_def)

            await self._bus.emit_event("planner.completed", "planner_agent", {
                "plan_id": plan_id,
                "workflow_name": wf_def.name,
                "node_count": len(wf_def.nodes),
                "filepath": str(filepath),
            })

            return wf_def

        except Exception as e:
            await self._bus.emit_event("planner.failed", "planner_agent", {
                "plan_id": plan_id,
                "request_preview": request[:200],
                "error": str(e),
            })

            # 发送 SystemEvent
            await self._bus.emit(SystemEvent(
                event_type=f"{NAMESPACE_EVENT}planner.failed",
                source="planner_agent",
                severity=EventSeverity.ERROR,
                payload={
                    "plan_id": plan_id,
                    "error": str(e),
                    "request_preview": request[:200],
                },
            ))

            return None

    # ── LLM 调用 ──────────────────────────────────────────

    async def _decompose_with_llm(
        self,
        request: str,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """调用 LLM 将自然语言分解为 workflow JSON。

        优先使用 Agent SDK（如果可用），回落使用 urllib。
        """
        caps_str = "\n".join(f"- {c}" for c in self._available_capabilities)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(capabilities_str=caps_str)

        context_str = ""
        if context:
            context_str = "\n## 额外上下文\n" + json.dumps(context, ensure_ascii=False, indent=2)

        user_prompt = f"请为以下请求创建 Workflow:\n\n{request}{context_str}"

        if self._use_agent_sdk and self._sdk_agent is not None:
            return await self._decompose_via_sdk(system_prompt, user_prompt)
        else:
            return self._decompose_via_urllib(system_prompt, user_prompt)

    async def _decompose_via_sdk(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any] | None:
        """通过 Agent SDK 调用 LLM。"""
        try:
            # 构建完整 prompt（system + user 合并到 TrimumAgent 的 run）
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            result = self._sdk_agent.run_sync(full_prompt)
            raw = result.data if hasattr(result, "data") else str(result)
        except Exception as e:
            print(f"[PlannerAgent] Agent SDK 调用失败，回落到 urllib: {e}")
            return self._decompose_via_urllib(system_prompt, user_prompt)

        return self._extract_json(raw)

    def _decompose_via_urllib(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any] | None:
        """通过 urllib 直接调用 LLM API（回落方案）。"""
        try:
            raw = _call_llm_api_fallback(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self._llm_kwargs.get("model"),
                base_url=self._llm_kwargs.get("base_url"),
                api_key=self._llm_kwargs.get("api_key"),
            )
        except RuntimeError as e:
            print(f"[PlannerAgent] LLM 调用失败: {e}")
            return None

        return self._extract_json(raw)

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any] | None:
        """从 LLM 返回文本中提取 JSON（去掉 ```json 包围）。"""
        if "```json" in raw:
            start = raw.index("```json") + 7
            end = raw.index("```", start) if "```" in raw[start:] else len(raw)
            raw = raw[start:end].strip()
        elif "```" in raw:
            start = raw.index("```") + 3
            end = raw.index("```", start) if "```" in raw[start:] else len(raw)
            raw = raw[start:end].strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[PlannerAgent] JSON 解析失败: {e}")
            print(f"[PlannerAgent] 原始 LLM 输出:\n{raw[:500]}")
            return None

        if isinstance(data, dict) and "error" in data:
            print(f"[PlannerAgent] LLM 返回错误: {data['error']}")
            return None

        return data

    # ── 转换与验证 ────────────────────────────────────────

    @staticmethod
    def _json_to_workflow(
        data: dict[str, Any],
        plan_id: str,
    ) -> WorkflowDefinition:
        """将 LLM 返回的 JSON dict 转换为 WorkflowDefinition。"""
        nodes_raw: list[dict] = data.get("nodes", [])
        edges_raw: list[dict] = data.get("edges", [])

        nodes = [
            NodeDefinition(
                id=n.get("id", f"step_{i}"),
                label=n.get("label", ""),
                handler=n.get("handler", ""),
                config=n.get("config", {}),
                timeout_seconds=n.get("timeout_seconds", 60.0),
                retry_count=n.get("retry_count", 0),
                retry_delay=n.get("retry_delay", 2.0),
            )
            for i, n in enumerate(nodes_raw)

        ]

        edges = [
            EdgeDefinition(
                source=e["source"],
                target=e["target"],
                condition=EdgeCondition(
                    type=e.get("condition", {}).get("type", "always"),
                    expression=e.get("condition", {}).get("expression", ""),
                ),
            )
            for e in edges_raw
        ]

        return WorkflowDefinition(
            id=plan_id,
            name=data.get("workflow_name", f"unnamed_{plan_id}"),
            description=data.get("description", ""),
            nodes=nodes,
            edges=edges,
            config={"source": "planner"},
        )

    @staticmethod
    def _validate_workflow(wf: WorkflowDefinition) -> None:
        """验证 workflow: 必须有节点, 每个节点有 id 和 handler."""
        if not wf.nodes:
            raise ValueError("Workflow 没有节点")

        for i, node in enumerate(wf.nodes):
            if not node.id:
                raise ValueError(f"节点 {i} 缺少 id")
            if not node.handler:
                raise ValueError(f"节点 '{node.id}' 缺少 handler")

    # ---- YAML 保存 ----

    def _save_workflow(self, wf: WorkflowDefinition) -> Path:
        """将 Workflow 保存为 YAML 文件."""
        filename = wf.name.replace(" ", "_").lower()
        if not filename:
            filename = f"workflow_{uuid.uuid4().hex[:8]}"
        filepath = self._workflow_dir / f"{filename}.yaml"

        data = {
            "workflow": {
                "name": wf.name,
                "description": wf.description,
                "nodes": [
                    {
                        "id": n.id,
                        "label": n.label,
                        "handler": n.handler,
                        "config": dict(n.config),
                        "timeout_seconds": n.timeout_seconds,
                        "retry_count": n.retry_count,
                        "retry_delay": n.retry_delay,
                    }
                    for n in wf.nodes
                ],
                "edges": [
                    {
                        "source": e.source,
                        "target": e.target,
                        "condition": {
                            "type": e.condition.type,
                            "expression": e.condition.expression,
                        },
                    }
                    for e in wf.edges
                ],
            }
        }

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return filepath

    # ---- Workflow 管理 ----

    def list_workflows(self) -> list[dict[str, Any]]:
        """列出所有已保存的 workflow 元信息（仅文件名和名称，不加载完整内容）。"""
        if not self._workflow_dir.exists():
            return []

        workflows: list[dict[str, Any]] = []
        for fpath in sorted(self._workflow_dir.glob("*.yaml")):
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                wf_data = data.get("workflow", data)
                workflows.append({
                    "name": wf_data.get("name", fpath.stem),
                    "description": wf_data.get("description", ""),
                    "node_count": len(wf_data.get("nodes", [])),
                    "filepath": str(fpath),
                })
            except Exception as e:
                workflows.append({
                    "name": fpath.stem,
                    "error": str(e),
                    "filepath": str(fpath),
                })

        return workflows

    def load_workflow(self, name: str) -> WorkflowDefinition | None:
        """加载已保存的 workflow.

        参数:
            name: workflow 名称 (不含 .yaml)

        返回:
            WorkflowDefinition 或 None (文件不存在或解析失败)
        """
        filepath = self._workflow_dir / f"{name}.yaml"
        if not filepath.exists():
            return None

        try:
            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            wf_data = data.get("workflow", data)

            nodes = [
                NodeDefinition(
                    id=n.get("id", ""),
                    label=n.get("label", ""),
                    handler=n.get("handler", ""),
                    config=n.get("config", {}),
                    timeout_seconds=n.get("timeout_seconds", 60.0),
                    retry_count=n.get("retry_count", 0),
                    retry_delay=n.get("retry_delay", 2.0),
                )
                for n in wf_data.get("nodes", [])
            ]

            edges = [
                EdgeDefinition(
                    source=e["source"],
                    target=e["target"],
                    condition=EdgeCondition(
                        type=e.get("condition", {}).get("type", "always"),
                        expression=e.get("condition", {}).get("expression", ""),
                    ),
                )
                for e in wf_data.get("edges", [])
            ]

            return WorkflowDefinition(
                id=wf_data.get("name", name),
                name=wf_data.get("name", name),
                description=wf_data.get("description", ""),
                nodes=nodes,
                edges=edges,
            )

        except Exception as e:
            print(f"[PlannerAgent] 加载 workflow '{name}' 失败: {e}")
            return None


__all__ = ["PlannerAgent"]
