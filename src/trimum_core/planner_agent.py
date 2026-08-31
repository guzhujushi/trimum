"""Planner Agent 鈥?Runtime 鍐呭敮涓€鍚?LLM 鏅鸿兘鐨勭粍浠?

鑱岃矗锛堟寜闇€鍚姩锛岄潪甯搁┗锛?
1. 鎺ユ敹鏃犲尮閰?workflow 鐨勬柊璇锋眰/鑷劧璇█鎰忓浘
2. LLM 鎷嗚В鎰忓浘 鈫?缁撴瀯鍖?WorkflowDefinition
3. 鍐欏叆 YAML 鍥哄寲锛垀/.trimum/workflows/<name>.yaml锛?4. 瑙﹀彂 WorkflowEngine 鎵ц
5. 澶辫触鏃?emit event.planner.failed

璁捐鍘熷垯:
- 杞婚噺: 鍙?imports models + event_bus, 涓嶄緷璧栧叾浠栨ā鍧?- 鏈夌姸鎬? 姣忔 run() 鐙珛瀹炰緥, 涓嶅瓨璺ㄨ姹傜姸鎬?- workflow 鎸佷箙鍖栦娇鐢?YAML:
  - 鍙, 鍙墜鍔ㄧ紪杈? 鍙増鏈帶鍒?  - WorkflowEngine.run() 鎺ュ彈 WorkflowDefinition 瀵硅薄
  - ~/.trimum/workflows/ 鏄敞鍐岀洰褰?"""

from __future__ import annotations

import json
import os
import time
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

# 鈹€鈹€ 榛樿鐩綍 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

DEFAULT_WORKFLOW_DIR = Path.home() / ".trimum" / "workflows"

# 鈹€鈹€ LLM 璋冪敤鍑芥暟 (鏃犲閮?SDK 渚濊禆) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


import urllib.error
import urllib.request


def _call_llm_api(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> str:
    """璋冪敤 OpenAI 鍏煎 API (鏃犲閮?SDK 渚濊禆).

    鍙傛暟:
        system_prompt: 绯荤粺鎻愮ず璇?        user_prompt: 鐢ㄦ埛璇锋眰
        model: 妯″瀷鍚? 榛樿浠?TRIMUM_LLM_MODEL 鐜鍙橀噺璇诲彇
        base_url: API 鍦板潃, 榛樿 TRIMUM_LLM_BASE_URL
        api_key: API Key, 榛樿 TRIMUM_LLM_API_KEY
        timeout: 璇锋眰瓒呮椂绉掓暟

    杩斿洖:
        LLM 鍝嶅簲鐨?content 瀛楃涓?
    鎶涘嚭:
        RuntimeError: 璇锋眰澶辫触鎴栦笉鍚堟硶鍝嶅簲
    """
    model = model or os.environ.get("TRIMUM_LLM_MODEL", "deepseek-chat")
    base_url = base_url or os.environ.get("TRIMUM_LLM_BASE_URL",
                                          "https://models.sjtu.edu.cn/api/v1")
    api_key = api_key or os.environ.get("TRIMUM_LLM_API_KEY", "")

    if not api_key:
        raise RuntimeError("PlannerAgent: TRIMUM_LLM_API_KEY 未设置")

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
        raise RuntimeError(f"LLM API 璋冪敤澶辫触: {e}") from e

    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError(f"LLM API 杩斿洖绌?choices: {json.dumps(body, ensure_ascii=False)[:300]}")

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("LLM API 杩斿洖绌?content")

    return content


# 鈹€鈹€ 绯荤粺鎻愮ず璇嶆ā鏉?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

SYSTEM_PROMPT_TEMPLATE = """浣犳槸涓€涓?AI Agent 杩愯鏃?(trimum) 鐨?Planner Agent銆?浣犵殑鑱岃矗鏄皢鐢ㄦ埛鐨勮嚜鐒惰瑷€璇锋眰鎷嗚В涓哄彲鎵ц鐨?Workflow銆?
## 鍙敤鑳藉姏 (Agent 娉ㄥ唽琛ㄦ彁渚涚殑 capabilities)
{capabilities_str}

## 杈撳嚭鏍煎紡
杩斿洖涓€涓?JSON 瀵硅薄锛屼笉瑕佸寘鍚换浣曞叾浠栨枃瀛楋細

```json
{{
  "workflow_name": "绠€鐭嫳鏂囧悕, 鐢ㄤ笅鍒掔嚎鍒嗛殧",
  "description": "涓枃鎻忚堪, 璇存槑杩欎釜 workflow 鍋氫粈涔?,
  "nodes": [
    {{
      "id": "姝ラ1_id",
      "label": "姝ラ涓枃鏍囩",
      "handler": "capability 鍚嶇О, 濡?system.monitor.disk",
      "config": {{
        "command": "闇€瑕佹墽琛岀殑 shell 鍛戒护 (濡傛灉 handler 鏄?shell.exec)",
        "message": "闇€瑕佸彂閫佺殑娑堟伅 (濡傛灉 handler 鏄?agent.notify)",
        ...
      }},
      "timeout_seconds": 60,
      "retry_count": 0
    }}
  ],
  "edges": [
    {{
      "source": "鍓嶇疆姝ラ_id",
      "target": "鍚庣画姝ラ_id",
      "condition": {{
        "type": "always"
      }}
    }}
  ]
}}
```

## 鏉′欢绫诲瀷璇存槑
- "always": 鍓嶇疆瀹屾垚灏辩珛鍗虫墽琛?(榛樿)
- "on_complete": 鍓嶇疆鎴愬姛瀹屾垚鎵嶆墽琛?- "on_fail": 鍓嶇疆澶辫触鎵嶆墽琛?(闄嶇骇/澶囬€?
- "expression": 鑷畾涔夎〃杈惧紡, 濡?{{"type": "expression", "expression": "result.get('usage', 0) > 80"}}

## 瑙勫垯
1. 姝ラ鎸夋墽琛岄『搴忔帓鍒?(浠?nodes[0] 鍒?nodes[n-1])
2. 姣忎釜姝ラ鐨?handler 蹇呴』浠庡彲鐢ㄨ兘鍔涗腑閫夋嫨
3. 浣跨敤 "always" 鏉′欢杩炴帴椤哄簭姝ラ
4. 瀵逛簬妫€鏌ョ被姝ラ, 璁剧疆 timeout_seconds 涓?30
5. 瀵逛簬绯荤粺鎿嶄綔绫绘楠? 璁剧疆 timeout_seconds 涓?120
6. 鍗遍櫓鎿嶄綔娣诲姞 retry_count=0 (涓嶉噸璇?
7. 濡傛灉璇锋眰鏃犳硶鎷嗚В, 杩斿洖: {{"error": "鏃犳硶鐞嗚В姝よ姹?}}
"""


class PlannerAgent:
    """Planner Agent.

    闈炴寔涔呭寲缁勪欢 鈥?姣忔璇锋眰鍒涘缓鏂板疄渚?
    閫氳繃 Event Bus 涓?Runtime 鍏朵粬閮ㄥ垎閫氫俊.
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        workflow_dir: str | Path | None = None,
        available_capabilities: list[str] | None = None,
        llm_model: str | None = None,
        llm_base_url: str | None = None,
        llm_api_key: str | None = None,
    ) -> None:
        self._bus = event_bus
        self._workflow_dir = Path(workflow_dir or DEFAULT_WORKFLOW_DIR)
        self._available_capabilities = available_capabilities or ["shell.exec", "system.monitor"]
        self._llm_model = llm_model
        self._llm_base_url = llm_base_url
        self._llm_api_key = llm_api_key

        # 纭繚鐩綍瀛樺湪
        self._workflow_dir.mkdir(parents=True, exist_ok=True)

    # 鈹€鈹€ 鍏紑鎺ュ彛 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    async def run(
        self,
        request: str,
        context: dict[str, Any] | None = None,
    ) -> WorkflowDefinition | None:
        """瀹屾暣瑙勫垝娴佺▼: LLM 鎷嗚В 鈫?鍐欏叆 鈫?杩斿洖 WorkflowDefinition.

        鍙傛暟:
            request: 鐢ㄦ埛鑷劧璇█璇锋眰
            context: 棰濆涓婁笅鏂?(鍙€?

        杩斿洖:
            WorkflowDefinition 鎴?None (澶辫触鏃?
        """
        context = context or {}
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"

        await self._bus.emit_event("planner.started", "planner_agent", {
            "plan_id": plan_id,
            "request_preview": request[:200],
        })

        try:
            # 1. LLM 鎷嗚В
            workflow_json = self._decompose_with_llm(request, context)
            if workflow_json is None:
                raise RuntimeError("LLM 鏃犳硶鎷嗚В璇锋眰")

            # 2. JSON 鈫?WorkflowDefinition
            wf_def = self._json_to_workflow(workflow_json, plan_id)

            # 3. 鏍￠獙 (鍩烘湰缁撴瀯)
            self._validate_workflow(wf_def)

            # 4. 鍐欏叆鎸佷箙鍖?            filepath = self._save_workflow(wf_def)

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

            # 鍙︽寜鏋舵瀯鏂囨。鍙?event.planner.failed
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

    # 鈹€鈹€ LLM 鎷嗚В 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def _decompose_with_llm(
        self,
        request: str,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """璋冪敤 LLM 灏嗚嚜鐒惰瑷€璇锋眰鎷嗚В涓虹粨鏋勫寲 workflow JSON."""
        caps_str = "\n".join(f"- {c}" for c in self._available_capabilities)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(capabilities_str=caps_str)

        context_str = ""
        if context:
            context_str = "\n## 棰濆涓婁笅鏂嘰n" + json.dumps(context, ensure_ascii=False, indent=2)

        user_prompt = f"璇锋媶瑙ｄ互涓嬭姹備负 Workflow:\n\n{request}{context_str}"

        try:
            raw = _call_llm_api(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self._llm_model,
                base_url=self._llm_base_url,
                api_key=self._llm_api_key,
            )
        except RuntimeError as e:
            print(f"[PlannerAgent] LLM 璋冪敤澶辫触: {e}")
            return None

        # 瑙ｆ瀽 JSON
        return self._extract_json(raw)

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any] | None:
        """浠?LLM 鍝嶅簲涓彁鍙?JSON (鍙兘琚?```json 鍖呰９)."""
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
            print(f"[PlannerAgent] JSON 瑙ｆ瀽澶辫触: {e}")
            print(f"[PlannerAgent] 鍘熷 LLM 鍝嶅簲:\n{raw[:500]}")
            return None

        if isinstance(data, dict) and "error" in data:
            print(f"[PlannerAgent] LLM 杩斿洖閿欒: {data['error']}")
            return None

        return data

    # 鈹€鈹€ 鏁版嵁缁撴瀯杞崲 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @staticmethod
    def _json_to_workflow(
        data: dict[str, Any],
        plan_id: str,
    ) -> WorkflowDefinition:
        """瑙ｆ瀽 LLM 杩斿洖鐨?JSON dict 鈫?WorkflowDefinition."""
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
        """鍩烘湰鏍￠獙: 闈炵┖鑺傜偣, 鏈?handler."""
        if not wf.nodes:
            raise ValueError("Workflow 娌℃湁鑺傜偣")

        for i, node in enumerate(wf.nodes):
            if not node.id:
                raise ValueError(f"鑺傜偣 {i} 缂哄皯 id")
            if not node.handler:
                raise ValueError(f"鑺傜偣 '{node.id}' 缂哄皯 handler")

    # 鈹€鈹€ 鎸佷箙鍖?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def _save_workflow(self, wf: WorkflowDefinition) -> Path:
        """灏?Workflow 鍐欏叆 YAML 鏂囦欢."""
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

    # 鈹€鈹€ 鏌ヨ宸叉湁 workflow 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def list_workflows(self) -> list[dict[str, Any]]:
        """鍒楀嚭鎵€鏈夊凡鍥哄寲鐨?workflow 鍏冩暟鎹?(涓嶅姞杞藉畬鏁村畾涔?."""
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
        """浠庢寔涔呭寲鐩綍鍔犺浇鎸囧畾 workflow.

        鍙傛暟:
            name: workflow 鍚嶇О (涓嶅惈 .yaml)

        杩斿洖:
            WorkflowDefinition 鎴?None (鏈壘鍒?鍔犺浇澶辫触)
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
