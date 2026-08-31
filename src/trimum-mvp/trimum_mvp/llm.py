"""LLM 适配器：OpenAI 兼容 Chat Completions API 客户端。

参照 shell_gpt 的适配器模式，提供：
- 自定义 base_url（DeepSeek 等国产模型兼容）
- stream / 非 stream 两种模式
- 错误重试（默认 3 次）+ 友好的中英文错误提示
- API Key 从环境变量 TRIMUM_API_KEY / OPENAI_API_KEY 读取

用法：
    client = LLMClient()
    reply = client.chat([{"role": "user", "content": "你好"}])
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# 可重试的 HTTP 状态码：限流与服务端临时错误
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# 常见状态码 -> 中英文提示
_STATUS_HINTS = {
    400: "请求参数有误（Bad Request）",
    401: "API Key 无效或已过期（Invalid API key）",
    403: "无访问权限，请检查账号余额或模型权限（Forbidden）",
    404: "接口地址不存在，请检查 base_url 配置（Not Found）",
    429: "请求过于频繁，已触发限流（Rate limited）",
    500: "服务端内部错误（Server error）",
    502: "服务端网关错误（Bad gateway）",
    503: "服务暂时不可用（Service unavailable）",
    504: "服务端响应超时（Gateway timeout）",
}


class LLMError(Exception):
    """LLM 调用失败，携带可选 HTTP 状态码与原始异常。"""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.cause = cause


def get_api_key() -> str | None:
    """按优先级读取 API Key：TRIMUM_API_KEY > OPENAI_API_KEY。"""
    return os.environ.get("TRIMUM_API_KEY") or os.environ.get("OPENAI_API_KEY")


def _describe_error(exc: Exception | None) -> str:
    """把异常转换为可读的中文描述。"""
    if isinstance(exc, LLMError):
        return exc.message
    if exc is None:
        return "未知错误（Unknown error）"
    return f"{type(exc).__name__}: {exc}"


def _friendly_http_message(status_code: int) -> str:
    """根据状态码生成友好的中英文错误提示。"""
    hint = _STATUS_HINTS.get(status_code, "HTTP 请求失败（HTTP request failed）")
    return f"{hint}（HTTP {status_code}）"


class LLMClient:
    """OpenAI 兼容 Chat Completions 客户端（httpx 实现）。"""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        if httpx is None:
            raise LLMError("缺少依赖 httpx，请先安装：pip install httpx")
        self.api_key = api_key or get_api_key()
        if not self.api_key:
            raise LLMError(
                "未找到 API Key：请设置环境变量 TRIMUM_API_KEY 或 OPENAI_API_KEY"
                "（No API key found. Set TRIMUM_API_KEY or OPENAI_API_KEY.）"
            )
        self.base_url = (
            base_url or os.environ.get("TRIMUM_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._client = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        """调用 chat/completions 并返回完整回复文本。

        - stream=True 时逐块回调 on_chunk，同时返回拼接后的完整文本。
        - 网络错误 / 5xx / 429 自动重试（最多 max_retries 次）。
        - 4xx 参数或鉴权错误不重试，直接抛出 LLMError。
        """
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if stream:
                    # L-8：流式输出无法安全重试（已打印的块可能重复），失败直接抛出
                    return self._chat_stream(messages, on_chunk)
                return self._chat_once(messages)
            except LLMError as exc:
                if stream:
                    raise
                if exc.status_code is not None and exc.status_code not in RETRYABLE_STATUS_CODES:
                    raise
                last_error = exc
            except httpx.HTTPError as exc:  # type: ignore[attr-defined]
                if stream:
                    raise LLMError(
                        f"LLM 流式请求失败：{_describe_error(exc)}（Stream request failed）",
                        cause=exc,
                    ) from exc
                last_error = exc
            if attempt < self.max_retries:
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 5.0))
        raise LLMError(
            f"LLM 请求在 {self.max_retries} 次尝试后仍失败：{_describe_error(last_error)}"
            f"（LLM request failed after {self.max_retries} attempts）",
            cause=last_error,
        )

    def close(self) -> None:
        """关闭底层 HTTP 连接。"""
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> "LLMClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages: list[dict[str, str]], stream: bool) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }

    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _chat_once(self, messages: list[dict[str, str]]) -> str:
        """非流式单次请求并返回回复文本。"""
        response = self._client.post(
            self._endpoint(),
            headers=self._headers(),
            json=self._payload(messages, stream=False),
        )
        self._raise_for_status(response)
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(
                "LLM 返回格式异常：缺少 choices[0].message.content"
                "（Unexpected response format）",
                cause=exc,
            ) from exc
        if not isinstance(content, str):
            raise LLMError("LLM 返回内容不是字符串（Unexpected content type）")
        return content

    def _chat_stream(
        self,
        messages: list[dict[str, str]],
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        """流式请求：解析 SSE 数据块并拼接完整文本。"""
        chunks: list[str] = []
        with self._client.stream(
            "POST",
            self._endpoint(),
            headers=self._headers(),
            json=self._payload(messages, stream=True),
        ) as response:
            self._raise_for_status(response)
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0]["delta"].get("content") or ""
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                if delta:
                    chunks.append(delta)
                    if on_chunk is not None:
                        on_chunk(delta)
        return "".join(chunks)

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        """状态码 >= 400 时抛出带友好提示的 LLMError。"""
        status_code = getattr(response, "status_code", 200)
        if status_code >= 400:
            raise LLMError(
                _friendly_http_message(int(status_code)),
                status_code=int(status_code),
            )