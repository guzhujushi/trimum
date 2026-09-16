"""LlmPolicyEngine — PolicyEngine 的 LLM 增强 wrapper。

核心逻辑：
    命令 → PolicyEngine(正则)
             ├─ low/auto         → 直通（省 LLM token）
             ├─ critical/deny    → 拒绝（省 LLM token）
             └─ 其他             → 查缓存 → 命中？用缓存：调 LLM → 写缓存

安全等级模式由 AgentSecurityConfig 控制：
    regex    模式：永不调 LLM
    balanced 模式：灰色地带才 LLM（默认）
    sandbox  模式：全量 LLM 审查 + 文件信任检查
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from .models import (
    RiskLevel,
    Action,
    SourceType,
    SecurityMode,
    FileTrustLevel,
    AgentSecurityConfig,
    LLMDecision,
)
from .policy_engine import PolicyEngine
from .file_trust import FileTrustTracker
from .security_config import SecurityConfig

log = logging.getLogger("trimum_core.llm_policy")

# ── LLM 调用默认值 ──
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"


class LLMDecisionCache:
    """LLM 决策缓存：同命令 5 分钟内复用。"""

    def __init__(self, ttl: int = 300, max_entries: int = 1000):
        self._cache: dict[str, LLMDecision] = {}
        self._ttl = ttl
        self._max_entries = max_entries

    @staticmethod
    def _make_hash(cmd: str) -> str:
        """SHA256 前缀 8 位作为缓存的 key。"""
        return hashlib.sha256(cmd.encode("utf-8")).hexdigest()[:8]

    def get(self, command: str) -> Optional[LLMDecision]:
        """查询缓存，过期则删除并返回 None。"""
        key = self._make_hash(command)
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() > entry.expires_at:
            del self._cache[key]
            return None
        return entry

    def set(self, command: str, decision: LLMDecision):
        """写入缓存，超出上限时清理最老的一半。"""
        key = self._make_hash(command)
        if len(self._cache) >= self._max_entries:
            self._evict_half()
        self._cache[key] = decision

    def _evict_half(self):
        """淘汰最老的一半条目。"""
        sorted_items = sorted(
            self._cache.items(),
            key=lambda x: x[1].expires_at,
        )
        for k, _ in sorted_items[: len(sorted_items) // 2]:
            del self._cache[k]

    def clear(self):
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


class LlmPolicyEngine:
    """增强版 PolicyEngine：正则 + LLM 双模式。

    用法：
        llm_policy = LlmPolicyEngine(policy_engine, security_config)
        risk, action, reason = await llm_policy.evaluate(
            command="rm -rf /tmp/test",
            source_type=SourceType.AI,
            mode=SecurityMode.BALANCED,
            file_trust=FileTrustLevel.HIGH,
        )
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        security_config: Optional[SecurityConfig] = None,
        file_trust_tracker: Optional[FileTrustTracker] = None,
    ):
        self._pe = policy_engine
        self._sec_cfg = security_config or SecurityConfig()
        self._ft = file_trust_tracker or FileTrustTracker(db_path=":memory:")
        self._cache: dict[str, LLMDecisionCache] = {}  # mode -> cache
        self._llm_config: dict = {}

        # 延迟加载 LLM 配置
        self._load_llm_config()

    def _load_llm_config(self):
        """从 security_config 加载 LLM provider 配置。"""
        self._llm_config = self._sec_cfg.get_llm_config()

    def _get_cache(self, mode: SecurityMode) -> LLMDecisionCache:
        """按模式获取缓存实例。"""
        key = mode.value
        if key not in self._cache:
            level = self._sec_cfg.get_level_config(mode)
            cache_cfg = level.get("cache", {})
            self._cache[key] = LLMDecisionCache(
                ttl=cache_cfg.get("ttl_seconds", 300),
                max_entries=cache_cfg.get("max_entries", 1000),
            )
        return self._cache[key]

    async def evaluate(
        self,
        command: str,
        source_type: Optional[SourceType] = None,
        mode: SecurityMode = SecurityMode.BALANCED,
        file_trust: Optional[FileTrustLevel] = None,
        agent_cfg: Optional[AgentSecurityConfig] = None,
    ) -> tuple[RiskLevel, Action, str]:
        """主入口：按安全等级模式评估命令。

        返回 (risk, action, reason)
        """
        # ── Step 1: 正则匹配（总是先走，省 LLM） ──
        risk, action, reason = self._pe.evaluate(command, source_type)

        # ── Step 2: 根据模式决定后续 ──
        if mode == SecurityMode.REGEX:
            # regex 模式：永不调 LLM，直接返回正则结果
            return risk, action, f"[regex] {reason}"

        # low/auto → 直通，不需要 LLM
        if risk == RiskLevel.LOW and action == Action.AUTO:
            return risk, action, f"[llm-passthrough] {reason}"

        # critical/deny → 直拒，不需要 LLM
        if risk == RiskLevel.CRITICAL and action == Action.DENY:
            return risk, action, f"[llm-blocked] {reason}"

        # ── Step 3: 检查文件信任（信任文件不调 LLM） ──
        if file_trust is not None and mode != SecurityMode.SANDBOX:
            if file_trust >= FileTrustLevel.LOW:
                return risk, action, f"[llm-file-trusted] file_trust={file_trust.name}"

        # ── Step 4: 检查 LLM 缓存 ──
        cache = self._get_cache(mode)
        cached = cache.get(command)
        if cached is not None:
            return cached.risk, cached.action, f"[llm-cached] {cached.reason}"

        # ── Step 5: 决定是否调 LLM ──
        level = self._sec_cfg.get_level_config(mode)
        threshold = level.get("llm_threshold", "suspicious")

        if threshold == "never":
            # regex 模式已经提前返回了，这里不会走到
            return risk, action, f"[llm-skip] threshold=never"

        if threshold == "suspicious":
            # 只有正则命中 medium 且 action=confirm 才调 LLM
            if action != Action.CONFIRM:
                return risk, action, f"[llm-skip] action={action.value}"

        # threshold == "always" 或符合可疑条件
        try:
            llm_decision = await self._call_llm(command)
            cache.set(command, llm_decision)
            return llm_decision.risk, llm_decision.action, f"[llm] {llm_decision.reason}"
        except Exception as e:
            log.warning("LLM call failed, falling back to regex: %s", e)
            return risk, action, f"[llm-fallback] {reason}"

    async def _call_llm(self, command: str) -> LLMDecision:
        """调用 deepseek API 分析命令风险。

        返回 LLMDecision 结构（风险等级 + 动作 + 理由 + 置信度）。

        使用 httpx 直接调 OpenAI-compatible API，不依赖额外库。
        """
        import httpx

        cfg = self._llm_config
        base_url = cfg.get("base_url", _DEFAULT_BASE_URL)
        model = cfg.get("model", _DEFAULT_MODEL)
        api_key_env = cfg.get("api_key_env", _DEFAULT_API_KEY_ENV)
        api_key = cfg.get("api_key") or os.environ.get(api_key_env, "")
        timeout = cfg.get("timeout_seconds", 15)
        max_retries = cfg.get("max_retries", 2)

        if not api_key:
            raise ValueError(f"API key not found (env: {api_key_env})")

        # 构建 prompt
        prompt = f"""分析以下命令的风险等级并返回 JSON。

命令: {command}

请仅返回以下 JSON 格式（不要多余文字）：
{{
    "risk": "low" | "medium" | "high" | "critical",
    "action": "auto" | "confirm" | "deny",
    "reason": "简短说明",
    "confidence": 0.0~1.0
}}

约束：
- 只读/无害命令（ls/cat/find/echo/uname 等）→ risk=low, action=auto
- 写入/删除/安装（rm/mv/cp/dd/wget curl| chmod chown pip install 等）→ risk=medium/high, action=confirm
- 破坏性操作（rm -rf /、dd if=/dev、mkfs、format 等）→ risk=critical, action=deny"""

        last_error = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        f"{base_url.rstrip('/')}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": "You are a security risk analyzer. Return only JSON."},
                                {"role": "user", "content": prompt},
                            ],
                            "temperature": 0.0,
                            "max_tokens": 200,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()

                    # 提取 JSON（处理 markdown 围栏）
                    if content.startswith("```"):
                        content = content.split("\n", 1)[1]
                        content = content.rsplit("```", 1)[0]
                    content = content.strip()

                    result = json.loads(content)
                    cmd_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()[:8]

                    return LLMDecision(
                        command_hash=cmd_hash,
                        risk=RiskLevel(result.get("risk", "medium")),
                        action=Action(result.get("action", "confirm")),
                        reason=result.get("reason", "LLM analysis"),
                        confidence=float(result.get("confidence", 0.5)),
                        expires_at=time.time() + self._get_cache(SecurityMode.BALANCED)._ttl,
                    )

            except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 1.0
                    log.debug("LLM call attempt %d failed, retrying in %.1fs: %s", attempt + 1, wait, e)
                    await asyncio.sleep(wait)
                continue

        raise last_error or RuntimeError("LLM call failed after all retries")

    def clear_cache(self, mode: Optional[SecurityMode] = None):
        """清空缓存。"""
        if mode:
            key = mode.value
            if key in self._cache:
                self._cache[key].clear()
        else:
            for cache in self._cache.values():
                cache.clear()
