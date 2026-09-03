"""Transform Agent — 自然语言 → 终端命令 / TARL 的预翻译层。

职责：
1. 接收用户自然语言输入
2. 优先尝试翻译成终端命令（直接走 Tool Gateway Shell 执行）
3. 如果翻不了终端命令，转为 TARL 格式发到 Event Bus
4. 输出 confidence 字段（Workflow Engine 监听器根据匹配度决策）

架构位置：
  用户 → Transform Agent → [终端命令 → Tool Gateway]
                          └ [TARL → Event Bus → Workflow Engine → Planner Agent]
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from trimum_core.tarl_parser import serialize

log = logging.getLogger("trimum_core.transform_agent")

# ── 默认 LLM 配置 ─────────────────────────────────────
# Transform Agent 用便宜模型，通过环境变量独立配置
_ENV_MODEL = "TRANSFORM_LLM_MODEL"
_ENV_BASE_URL = "TRANSFORM_LLM_BASE_URL"
_ENV_API_KEY = "TRANSFORM_LLM_API_KEY"

# ── 默认值（降级到全局配置） ────────────────────────────
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_BASE_URL = "https://models.sjtu.edu.cn/api/v1"


class TransformAgent:
    """将自然语言翻译为终端命令或 TARL。

    Transform Agent 走 LLM（便宜模型），优先输出可直接执行的终端命令。
    如果无法翻译为终端命令，则输出 TARL 格式的事件。

    设计：
    - 温度固定为 0：保证翻译的确定性
    - 独立模型配置：与 Planner Agent 走不同模型
    - system prompt 严格约束输出格式
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self._model = model or os.environ.get(_ENV_MODEL) or _DEFAULT_MODEL
        self._base_url = base_url or os.environ.get(_ENV_BASE_URL) or _DEFAULT_BASE_URL
        self._api_key = api_key or os.environ.get(_ENV_API_KEY) or ""
        self._temperature = temperature

    # ── 核心接口 ──────────────────────────────────────────

    def translate(self, instruction: str) -> TransformResult:
        """翻译自然语言指令。

        Args:
            instruction: 用户原始输入。

        Returns:
            TransformResult，包含翻译结果。
        """
        return self._call_llm(instruction)

    async def translate_async(self, instruction: str) -> TransformResult:
        """异步版 translate（底层调用是同步 HTTP，用 run_in_executor 避免阻塞）。"""
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(
            None, self._call_llm, instruction
        )

    # ── LLM 调用 ──────────────────────────────────────────

    def _call_llm(self, instruction: str) -> TransformResult:
        """调用 LLM 翻译指令。

        输出格式约束（在 system prompt 中已定义，这里做二次校验）：
        1. 终端命令 → 以 SHELL: 开头
        2. TARL → 以 TARL: 开头
        3. 不确定 → confidence < 0.5
        """
        import json
        import urllib.error
        import urllib.request

        url = f"{self._base_url.rstrip('/')}/chat/completions"

        payload = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": instruction},
            ],
            "temperature": self._temperature,
            "max_tokens": 1024,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            log.warning("transform.llm_http_error", code=e.code)
            return TransformResult(
                tarl=self._fallback_tarl(instruction),
                confidence=0.2,
                original=instruction,
                error=f"LLM HTTP {e.code}",
            )
        except Exception as e:
            log.warning("transform.llm_error", error=str(e))
            return TransformResult(
                tarl=self._fallback_tarl(instruction),
                confidence=0.1,
                original=instruction,
                error=str(e),
            )

        choices = body.get("choices", [])
        if not choices:
            return TransformResult(
                tarl=self._fallback_tarl(instruction),
                confidence=0.1,
                original=instruction,
                error="Empty LLM response",
            )

        content = choices[0].get("message", {}).get("content", "").strip()
        return self._parse_llm_output(content, instruction)

    # ── 解析 LLM 输出 ────────────────────────────────────

    def _parse_llm_output(
        self, content: str, instruction: str
    ) -> TransformResult:
        """解析 LLM 输出为 TransformResult。

        LLM 被要求以特定前缀返回：
        - SHELL:<命令>  → 终端命令，直接走 Tool Gateway
        - TARL:<TARL>  → 转为 TARL 事件
        - 其他格式 → 尝试自动判断
        """
        content = content.strip()

        # 解析 confidence（如果 LLM 输出了 CONFIDENCE: 行）
        confidence = 0.8  # 默认
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass

        # 提取有效行（跳过 CONFIDENCE 行）
        body_lines = [
            l for l in content.split("\n")
            if l.strip() and not l.strip().startswith("CONFIDENCE:")
        ]
        body = "\n".join(body_lines).strip()

        # 判断输出类型
        if body.startswith("SHELL:"):
            # 终端命令
            shell_cmd = body[len("SHELL:"):].strip()
            return TransformResult(
                shell_command=shell_cmd,
                tarl=f"cmd:{shell_cmd.replace(' ', '_')} origin:ai",
                confidence=confidence,
                original=instruction,
                output_type="shell",
            )

        elif body.startswith("TARL:"):
            # TARL 格式（如果 LLM 输出不自带 origin 标签，手动追加）
            tarl = body[len("TARL:"):].strip()
            if "origin:" not in tarl:
                tarl = f"{tarl} origin:ai"
            return TransformResult(
                tarl=tarl,
                confidence=confidence,
                original=instruction,
                output_type="tarl",
            )

        else:
            # 无法识别格式 → 转为 fallback TARL
            log.info("transform.unrecognized_output", output=content[:200])
            return TransformResult(
                tarl=self._fallback_tarl(instruction),
                confidence=0.3,
                original=instruction,
                output_type="tarl",
                error=f"Unrecognized LLM output format: {content[:100]}",
            )

    # ── Fallback ──────────────────────────────────────────

    @staticmethod
    def _fallback_tarl(instruction: str) -> str:
        """LLM 调用失败时生成 fallback TARL。"""
        safe = instruction.replace(" ", "_").replace(":", "_")[:80]
        return serialize({"cmd": safe}) + " origin:ai"

    # ── System Prompt ─────────────────────────────────────

    _SYSTEM_PROMPT = """你是一个终端命令翻译器。你的职责是将用户的自然语言指令翻译为可执行的终端命令或标准化的TARL格式。

输出规则（严格遵守）：
1. 如果指令可以翻译为一个或多个终端命令，输出以 SHELL: 开头，后面跟命令本身。
   示例：用户说"查看磁盘" → SHELL:du -h /
   示例：用户说"列出文件" → SHELL:ls -la
   示例：用户说"查看当前目录" → SHELL:pwd
   示例：用户说"查看系统内存" → SHELL:free -h

2. 如果指令无法翻译为终端命令（比如涉及复杂工作流、需要多个步骤、或不是终端操作），输出以 TARL: 开头，后面跟TARL格式的键值对。
   示例：用户说"帮我写一个网站" → TARL:cmd:create_website
   示例：用户说"部署博客" → TARL:cmd:deploy_blog target:production

3. 输出 confidence 行：CONFIDENCE:<0.0-1.0>
   - 0.9-1.0：非常确定，指令清晰
   - 0.7-0.9：比较确定
   - 0.5-0.7：有点不确定
   - 0.3-0.5：不太确定，可能需要用户确认
   - 0.0-0.3：完全不确定

4. 一次只输出一个 SHELL 或一个 TARL。不要同时输出两种。

5. TARL 中的值不能包含空格，用下划线替代。
   错误：cmd:deploy blog
   正确：cmd:deploy_blog

6. 不要输出任何解释文字，只输出 SHELL:/TARL:/CONFIDENCE: 行。"""


# ── 结果类型 ──────────────────────────────────────────


class TransformResult:
    """Transform Agent 的翻译结果。

    属性:
        shell_command: 如果翻译为终端命令，这里存命令字符串
        tarl: TARL 格式的指令（始终有值）
        confidence: 翻译置信度 0.0-1.0
        original: 用户的原始输入
        output_type: "shell" | "tarl"
        error: 如果翻译过程出错，这里存错误信息
    """

    def __init__(
        self,
        tarl: str,
        confidence: float,
        original: str,
        shell_command: str | None = None,
        output_type: str = "tarl",
        error: str | None = None,
    ) -> None:
        self.shell_command = shell_command
        self.tarl = tarl
        self.confidence = confidence
        self.original = original
        self.output_type = output_type  # "shell" | "tarl"
        self.error = error

    @property
    def is_shell(self) -> bool:
        """结果是否为可直接执行的终端命令。"""
        return self.output_type == "shell" and bool(self.shell_command)

    @property
    def is_tarl(self) -> bool:
        """结果是否为 TARL 事件。"""
        return self.output_type == "tarl"

    @property
    def is_certain(self) -> bool:
        """翻译结果是否确定（>= 0.7）。"""
        return self.confidence >= 0.7

    @property
    def needs_confirmation(self) -> bool:
        """是否需要用户确认（0.4 ~ 0.7）。"""
        return 0.4 <= self.confidence < 0.7

    @property
    def needs_planner(self) -> bool:
        """是否需要 Planner Agent 干预（< 0.4）。"""
        return self.confidence < 0.4

    def to_dict(self) -> dict[str, Any]:
        return {
            "shell_command": self.shell_command,
            "tarl": self.tarl,
            "confidence": self.confidence,
            "original": self.original,
            "output_type": self.output_type,
            "error": self.error,
        }

    def __repr__(self) -> str:
        if self.is_shell:
            return f"TransformResult(shell={self.shell_command!r}, c={self.confidence})"
        return f"TransformResult(tarl={self.tarl!r}, c={self.confidence})"


__all__ = ["TransformAgent", "TransformResult"]
