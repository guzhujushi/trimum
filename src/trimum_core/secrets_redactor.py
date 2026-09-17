"""Secrets Redactor — 凭据脱敏模块。

职责：
1. 扫描日志输出 / 审计事件 / 工具执行结果中的敏感信息
2. 使用模式匹配替换 API key、secret、token、password、私钥等凭证
3. 提供统一的脱敏入口，供 logger、tool_gateway、audit 等模块使用

用法：
    redactor = SecretsRedactor()
    safe_text = redactor.redact("token=sk-abc123")
    safe_json = redactor.redact_dict({"api_key": "sk-xxx", "user": "alice"})
"""

from __future__ import annotations

import re
from typing import Any, Callable


# ── 敏感环境变量名匹配（KEY=value 形式） ─────────────────────────────
_SENSITIVE_KEY_NAMES = re.compile(
    r"(?i)"
    r"(secret|password|passwd|token|api[_-]?key|apikey|access[_-]?key"
    r"|client[_-]?secret|session[_-]?id|authorization|bearer|cookie|jwt"
    r"|private[_-]?key|credential|auth)"
)

# ── 模式替换规则 ─────────────────────────────────────────────────────
# 每个条目: (编译后的正则, 替换函数)
# 注意：顺序很重要。最具体的模式要放前面。

_MASK = "***REDACTED***"


def _mask_key_value(match: re.Pattern[str]) -> str:
    """key=value / key: value 形式 → 保留 key 名字和分隔符，打码 value"""
    return f"{match.group(1)}={_MASK}"


def _mask_standalone(_match: re.Pattern[str]) -> str:
    """独立 token → 全部打码"""
    return _MASK


_SECRET_PATTERNS: list[tuple[re.Pattern[str], Callable[[re.Pattern[str]], str]]] = [
    # 1. URI connection strings: scheme://user:password@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^:\s/]+):([^@\s/]+)@"),
     lambda m: f"{m.group(1)}:{_MASK}@{m.group(2) if m.lastindex >= 3 else ''}"),
    # 2. key=value / key: value / key:value (with sensitive key names)
    (re.compile(r"(?i)((?:api[_-]?key|secret|password|passwd|token|auth|credential|client[_-]?secret|access[_-]?key|session[_-]?id|cookie|jwt)[A-Za-z0-9_-]*)\s*[=:]\s*['\"]?([^\s'\",}]+)"),
     _mask_key_value),
    # 3. Bearer tokens
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), _mask_standalone),
    # 4. Basic auth
    (re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]{8,}"), _mask_standalone),
    # 5. AWS Access Key ID
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), _mask_standalone),
    # 6. GitHub tokens
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,})\b"), _mask_standalone),
    # 7. OpenAI-style keys
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{20,})\b"), _mask_standalone),
    # 8. Stripe keys
    (re.compile(r"(?i)\b(sk_(?:live|test)_[A-Za-z0-9]{20,})\b"), _mask_standalone),
    # 9. Private key blocks
    (re.compile(r"(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)", re.DOTALL), _mask_standalone),
    # 10. PEM certificates
    (re.compile(r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)", re.DOTALL), _mask_standalone),
    # 11. JWT tokens (header.payload.signature)
    (re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"), _mask_standalone),
    # 12. Generic long hex/base64 secrets in context
    (re.compile(r"(?i)\b([a-f0-9]{32,64})\b(?=\s*(?:secret|token|key|salt|iv))"), _mask_standalone),
]


class SecretsRedactor:
    """凭据脱敏器。

    对所有日志 / 审计 / 工具执行结果中的敏感信息进行检测和替换。
    支持字符串、字典、任意嵌套结构。
    """

    def __init__(self, custom_patterns: list[tuple[re.Pattern[str], Callable[[re.Pattern[str]], str]]] | None = None) -> None:
        self._patterns = list(_SECRET_PATTERNS)
        if custom_patterns:
            self._patterns.extend(custom_patterns)

    # -- 公开 API --

    def redact(self, text: str) -> str:
        """脱敏单个字符串。"""
        if not text or not isinstance(text, str):
            return text

        result = text
        for pattern, replacer in self._patterns:
            result = pattern.sub(replacer, result)
        return result

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """脱敏字典，深度遍历。返回新字典副本。"""
        return self.redact_value(data)

    def redact_value(self, value: Any) -> Any:
        """脱敏任意值（字符串 / 数字 / 列表 / 字典）。"""
        if isinstance(value, dict):
            result = {}
            for k, v in value.items():
                if isinstance(k, str) and _SENSITIVE_KEY_NAMES.search(k):
                    if isinstance(v, (str, int, float, bool)):
                        result[k] = _MASK
                        continue
                result[k] = self.redact_value(v)
            return result
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, str):
            return self.redact(value)
        return value

    def add_pattern(self, pattern: re.Pattern[str], replacer: Callable[[re.Pattern[str]], str]) -> None:
        """添加自定义脱敏模式。"""
        self._patterns.append((pattern, replacer))


# -- 便捷函数 --
_global_redactor = SecretsRedactor()


def redact_text(text: str) -> str:
    """便捷入口：脱敏字符串。"""
    return _global_redactor.redact(text)


def redact_obj(obj: Any) -> Any:
    """便捷入口：脱敏任意对象。"""
    return _global_redactor.redact_value(obj)


__all__ = ["SecretsRedactor", "redact_text", "redact_obj"]
