"""LLM 路由与限流：角色 → 主/备模型，令牌桶节流，429/失败自动回退。

为什么有这一层（2026-09-21 定）
--------------------------------
项目里有 5 个 LLM 调用点，各自解析 env、各自重试，谁都不限流：

    llm_policy._call_llm            命令风险灰区裁决（频率最高）
    planner_agent                   任务分解
    transform_agent                 自然语言 → 命令/TARL
    experience_learner              失败经验沉淀
    agent_loop._chat_completion     运行时会话（支持流式）

交我算（models.sjtu.edu.cn）的配额是**硬限**：10 次/分、300k tokens/分、1B tokens/周；
DeepSeek 官方按量计费、没有硬 RPM。于是策略是「免费额度优先、付费兜底」：

    主 = 交我算 qwen3.8-27b（免费，节流到 9 次/分，留 1 次余量）
    备 = DeepSeek 官方 deepseek-flash（仅当主 429/5xx/超时/连不上时用）

本模块只做三件事，HTTP 一概不碰：
1. **选谁**    resolve_targets() 按「角色 env > 全局 env > 调用点默认值 > 内置默认」定出候选链；
2. **等多久**  TokenBucket 把同一 provider 的出站速率压到 N 次/分；
3. **失败换谁** run_with_fallback() 顺序尝试，429/5xx 给该 provider 记冷却并立刻换下一个；
   全部不可用才抛 LlmCallError，由调用点走各自的降级路径（正则 / 空结果 / TARL）。

传输无关的好处：调用点继续用它自己的 urllib / httpx / 流式写法（因此也继续能被
``@patch("urllib.request.urlopen")`` 这类既有测试打桩），本模块只负责策略。

env 约定（全部落在 .env，见 docs/LLM-ROUTING.md）
--------------------------------------------------
    角色级：<ROLE>_LLM_{MODEL,BASE_URL,API_KEY,API_KEY_ENV,RPM,TIMEOUT,MAX_RETRIES}
            ROLE ∈ POLICY / PLANNER / TRANSFORM / EXPERIENCE / AGENT
    全局：  TRIMUM_LLM_{...}                  角色级没写就用它
    回退：  TRIMUM_LLM_FALLBACK_{...}         角色级回退写 <ROLE>_LLM_FALLBACK_{...}
            TRIMUM_LLM_FALLBACK_ENABLED=0     整体关掉回退

    *_API_KEY_ENV 是**间接引用**（值写 ``JIAOWOISAN_API_KEY``），同一把密钥不必写两遍；
    *_API_KEY 也可以直接给值。两者都没给时按 base_url 推断：交我算 →
    JIAOWOISAN_API_KEY/API_KEY，DeepSeek → DEEPSEEK_API_KEY。

已知边界
--------
令牌桶是**进程内**的：daemon 和 CLI 各自持有 9 次/分的预算，两者同时跑时瞬时合计
可能超过交我算的 10 次/分。跨进程限流（文件锁 + 共享状态）见 docs/LLM-ROUTING.md 待办。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, TypeVar

log = logging.getLogger("trimum_core.llm_router")

# ── 角色 ──────────────────────────────────────────────────────────────
ROLE_POLICY = "policy"          # 命令风险灰区裁决（llm_policy）
ROLE_PLANNER = "planner"        # 任务分解（planner_agent）
ROLE_TRANSFORM = "transform"    # 自然语言 → 命令/TARL（transform_agent）
ROLE_EXPERIENCE = "experience"  # 失败经验沉淀（experience_learner）
ROLE_AGENT = "agent"            # 运行时会话（agent_loop）

_ROLE_ENV_PREFIX = {
    ROLE_POLICY: "POLICY_LLM",
    ROLE_PLANNER: "PLANNER_LLM",
    ROLE_TRANSFORM: "TRANSFORM_LLM",
    ROLE_EXPERIENCE: "EXPERIENCE_LLM",
    ROLE_AGENT: "AGENT_LLM",
}

_GLOBAL_PREFIX = "TRIMUM_LLM"
_FALLBACK_KEY = "FALLBACK"

# ── 内置默认值：交我算为主、DeepSeek 为备 ─────────────────────────────
DEFAULT_PRIMARY_BASE_URL = "https://models.sjtu.edu.cn/api/v1"
DEFAULT_PRIMARY_MODEL = "qwen3.8-27b"
SJTU_RPM = 9                     # 交我算硬限 10 次/分，留 1 次给人工和其他工具
DEFAULT_FALLBACK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_FALLBACK_MODEL = "deepseek-flash"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 1          # 1 = 试一次就换 target（跟收口前各调用点行为一致）

# 冷却时长（秒）：命中的 provider 在这段时间内不再被碰
COOLDOWN_RATE_LIMIT = 60.0
COOLDOWN_SERVER_ERROR = 30.0
COOLDOWN_NETWORK = 15.0
COOLDOWN_CLIENT_ERROR = 120.0
# 这些状态码换 provider 比重试同一个更值（配额打满 / key 不对 / 模型名不对）
_SWITCH_STATUSES = frozenset({400, 401, 403, 404, 429})

_NETWORK_HINTS = ("timeout", "timed out", "connect", "network", "unreachable",
                  "reset", "httpcore", "urlerror", "socket", "temporarily")

_T = TypeVar("_T")

# 可替换的睡眠函数：生产里就是 time.sleep / asyncio.sleep；单元测试换成假的，
# 免得为了验证「9 次/分」真的等 6.7 秒。
_sleep: Callable[[float], None] = time.sleep
_async_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


class LlmCallError(RuntimeError):
    """候选链全部失败（或全都不可用）。调用点据此走自己的降级路径。"""

    def __init__(
        self,
        role: str,
        errors: list[tuple["LlmTarget", BaseException]],
        attempts: int,
    ) -> None:
        self.role = role
        self.errors = errors
        self.attempts = attempts
        detail = "; ".join(f"{t.label} -> {e}" for t, e in errors) or "没有可用 target"
        super().__init__(f"LLM 调用失败（role={role}, attempts={attempts}）: {detail}")


@dataclass(frozen=True)
class LlmTarget:
    """一个可调用的模型端点。tier 只有 primary / fallback 两种。"""

    role: str
    tier: str
    model: str
    base_url: str
    api_key: str = ""
    api_key_env: str = ""
    rpm: int = 0
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES

    @property
    def provider(self) -> str:
        """节流与冷却的粒度：一个 base_url = 一份配额。"""
        return self.base_url.rstrip("/")

    @property
    def label(self) -> str:
        return f"{self.tier}:{self.model}@{_short_host(self.base_url)}"

    @property
    def usable(self) -> bool:
        """没有 key 的远端 target 直接判为不可用（本地端点不要求 key）。"""
        return bool(self.api_key) or _is_local(self.base_url)

    @property
    def reason_unusable(self) -> str:
        return f"缺少 API key（env: {self.api_key_env or '未指定'}）"


class TokenBucket:
    """「每分钟 N 次」的令牌桶（N <= 0 表示不限流）。

    consume() 返回「还要等多少秒」，并且**预扣**这一次配额 —— 并发调用者因此各自
    排到不同的时间槽，而不是同时放行后一起去服务端撞 429。
    """

    def __init__(self, rpm: int, burst: float = 1.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.rpm = max(0, int(rpm))
        self._rate = self.rpm / 60.0
        self._capacity = max(1.0, float(burst))
        self._tokens = self._capacity
        self._clock = clock
        self._last = clock()
        self._lock = threading.Lock()

    def consume(self) -> float:
        if self._rate <= 0:
            return 0.0
        with self._lock:
            now = self._clock()
            self._tokens = min(
                self._capacity, self._tokens + max(0.0, now - self._last) * self._rate
            )
            self._last = now
            self._tokens -= 1.0
            if self._tokens >= 0:
                return 0.0
            return -self._tokens / self._rate


# ── 进程内状态：每个 provider 一个桶、一份冷却 ────────────────────────
_buckets: dict[str, TokenBucket] = {}
_cooldowns: dict[str, float] = {}
_registry_lock = threading.Lock()
_stats: dict[str, Any] = {
    "calls": 0,
    "fallbacks": 0,
    "rate_limit_waits": 0,
    "rate_limit_seconds": 0.0,
    "cooldowns": 0,
    "skipped_cooling": 0,
}


def reset_state() -> None:
    """清空桶/冷却/计数。测试用；生产里重启进程即等于清零。"""
    with _registry_lock:
        _buckets.clear()
        _cooldowns.clear()
        for key in _stats:
            _stats[key] = 0.0 if isinstance(_stats[key], float) else 0


def stats() -> dict[str, Any]:
    """给 doctor / 运维看的快照。"""
    with _registry_lock:
        now = time.monotonic()
        cooling = {
            key: round(until - now, 1)
            for key, until in _cooldowns.items()
            if until > now
        }
        return {
            **dict(_stats),
            "buckets": {key: bucket.rpm for key, bucket in _buckets.items()},
            "cooling": cooling,
        }


def set_cooldown(target: LlmTarget, seconds: float) -> None:
    if seconds <= 0:
        return
    with _registry_lock:
        until = time.monotonic() + seconds
        if until > _cooldowns.get(target.provider, 0.0):
            _cooldowns[target.provider] = until
        _stats["cooldowns"] += 1


def cooldown_remaining(target: LlmTarget) -> float:
    with _registry_lock:
        until = _cooldowns.get(target.provider, 0.0)
    return max(0.0, until - time.monotonic())


# ── env 读取 ──────────────────────────────────────────────────────────
def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return ""


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(_env(name)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name))
    except (TypeError, ValueError):
        return default


def _host(url: str) -> str:
    text = (url or "").split("//", 1)[-1]
    return text.split("/", 1)[0].lower()


def _short_host(url: str) -> str:
    return _host(url).split(":", 1)[0] or "?"


def _is_local(url: str) -> bool:
    host = _host(url).split(":", 1)[0]
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or host.endswith(".local")


def _implied_key_envs(base_url: str) -> list[str]:
    """按 base_url 推断该用哪把 key（.env 里已有的名字）。"""
    host = _host(base_url)
    if "sjtu.edu.cn" in host:
        return ["JIAOWOISAN_API_KEY", "API_KEY", "TRIMUM_LLM_API_KEY"]
    if "deepseek.com" in host:
        return ["DEEPSEEK_API_KEY", "TRIMUM_LLM_API_KEY"]
    return ["TRIMUM_LLM_API_KEY"]


def _implied_rpm(base_url: str) -> int:
    """交我算有硬配额，别的 provider 默认不限流。"""
    return SJTU_RPM if "sjtu.edu.cn" in _host(base_url) else 0


def _pick(field: str, prefixes: tuple[str, ...], default: Any, builtin: Any) -> str:
    for prefix in prefixes:
        value = _env(f"{prefix}_{field}")
        if value:
            return value
    if default not in (None, ""):
        return str(default)
    return str(builtin)


def _pick_rpm(
    *,
    prefix: str,
    global_prefix: str,
    url: str,
    given: Any = None,
    url_overridden: bool = False,
) -> int:
    """RPM 的取法（交我算 10 次/分是硬配额，别的 provider 默认不限流）。

    优先级：``<ROLE>_LLM_RPM`` > 调用点默认值 > ``TRIMUM_LLM_*_RPM``（仅当这一级的
    地址没被角色改过）> 按地址推断。

    特意不让 ``TRIMUM_LLM_RPM`` 无条件继承：agent 角色把主模型指到 DeepSeek 时，
    不该被交我算的 9 次/分绑住。
    """
    value = _env(f"{prefix}_RPM")
    if value:
        return _env_int(f"{prefix}_RPM", 0)
    if given not in (None, ""):
        try:
            return int(float(given))
        except (TypeError, ValueError):
            pass
    if not url_overridden:
        inherited = _env(f"{global_prefix}_RPM")
        if inherited:
            return _env_int(f"{global_prefix}_RPM", _implied_rpm(url))
    return _implied_rpm(url)


def _pick_int(field: str, prefixes: tuple[str, ...], default: Any, builtin: int) -> int:
    for prefix in prefixes:
        value = _env(f"{prefix}_{field}")
        if value:
            return _env_int(f"{prefix}_{field}", builtin)
    if default not in (None, ""):
        try:
            return int(float(default))
        except (TypeError, ValueError):
            return builtin
    return builtin


def _pick_float(field: str, prefixes: tuple[str, ...], default: Any, builtin: float) -> float:
    for prefix in prefixes:
        value = _env(f"{prefix}_{field}")
        if value:
            return _env_float(f"{prefix}_{field}", builtin)
    if default not in (None, ""):
        try:
            return float(default)
        except (TypeError, ValueError):
            return builtin
    return builtin


def _resolve_api_key(
    *,
    prefixes: tuple[str, ...],
    direct: Any,
    key_env: Any,
    base_url: str,
) -> tuple[str, str]:
    """按「直接值 > 角色/全局 *_API_KEY > *_API_KEY_ENV 间接引用 > 按 host 推断」取 key。"""
    if direct:
        return str(direct).strip(), "(显式传入)"
    for prefix in prefixes:
        value = _env(f"{prefix}_API_KEY")
        if value:
            return value, f"{prefix}_API_KEY"
    for prefix in prefixes:
        name = _env(f"{prefix}_API_KEY_ENV")
        if name:
            value = _env(name)
            if value:
                return value, name
            return "", name  # 名字写了但环境里是空的：明确报缺，别猜别的
    names: list[str] = []
    if key_env:
        names.append(str(key_env))
    names.extend(_implied_key_envs(base_url))
    for name in names:
        value = _env(name)
        if value:
            return value, name
    return "", (names[0] if names else "")


def resolve_targets(
    role: str,
    *,
    defaults: Optional[dict[str, Any]] = None,
    fallback: Optional[bool] = None,
) -> list[LlmTarget]:
    """定出这个角色的候选链：先 primary，后 fallback（默认开）。

    defaults 是调用点手里的配置（yaml `llm:` 段 / 构造函数参数），优先级**低于** env，
    这样运维只改 .env 就能整体切换模型。
    """
    given = dict(defaults or {})
    role_prefix = _ROLE_ENV_PREFIX.get(role, f"{role.upper()}_LLM")
    primary_prefixes = (role_prefix, _GLOBAL_PREFIX)
    fallback_prefixes = (f"{role_prefix}_{_FALLBACK_KEY}", f"{_GLOBAL_PREFIX}_{_FALLBACK_KEY}")

    primary_url = _pick("BASE_URL", primary_prefixes, given.get("base_url"), DEFAULT_PRIMARY_BASE_URL)
    primary_key, primary_key_env = _resolve_api_key(
        prefixes=primary_prefixes,
        direct=given.get("api_key"),
        key_env=given.get("api_key_env"),
        base_url=primary_url,
    )
    primary = LlmTarget(
        role=role,
        tier="primary",
        model=_pick("MODEL", primary_prefixes, given.get("model"), DEFAULT_PRIMARY_MODEL),
        base_url=primary_url,
        api_key=primary_key,
        api_key_env=primary_key_env,
        rpm=_pick_rpm(
            prefix=role_prefix,
            global_prefix=_GLOBAL_PREFIX,
            url=primary_url,
            given=given.get("rpm"),
            url_overridden=bool(_env(f"{role_prefix}_BASE_URL")),
        ),        timeout=_pick_float("TIMEOUT", primary_prefixes, given.get("timeout"), DEFAULT_TIMEOUT),
        max_retries=_pick_int(
            "MAX_RETRIES", primary_prefixes, given.get("max_retries"), DEFAULT_MAX_RETRIES
        ),
    )

    want_fallback = (
        _env_bool(f"{_GLOBAL_PREFIX}_{_FALLBACK_KEY}_ENABLED", True)
        if fallback is None
        else bool(fallback)
    )
    chain = [primary]
    if not want_fallback:
        return chain

    fallback_url = _pick(
        "BASE_URL", fallback_prefixes, given.get("fallback_base_url"), DEFAULT_FALLBACK_BASE_URL
    )
    fallback_key, fallback_key_env = _resolve_api_key(
        prefixes=fallback_prefixes,
        direct=None,
        key_env=given.get("fallback_api_key_env"),
        base_url=fallback_url,
    )
    secondary = LlmTarget(
        role=role,
        tier="fallback",
        model=_pick("MODEL", fallback_prefixes, given.get("fallback_model"), DEFAULT_FALLBACK_MODEL),
        base_url=fallback_url,
        api_key=fallback_key,
        api_key_env=fallback_key_env,
        rpm=_pick_rpm(
            prefix=f"{role_prefix}_{_FALLBACK_KEY}",
            global_prefix=f"{_GLOBAL_PREFIX}_{_FALLBACK_KEY}",
            url=fallback_url,
            url_overridden=bool(_env(f"{role_prefix}_{_FALLBACK_KEY}_BASE_URL")),
        ),        timeout=_pick_float("TIMEOUT", fallback_prefixes, given.get("timeout"), DEFAULT_TIMEOUT),
        max_retries=_pick_int(
            "MAX_RETRIES", fallback_prefixes, given.get("max_retries"), DEFAULT_MAX_RETRIES
        ),
    )
    if (secondary.provider, secondary.model) != (primary.provider, primary.model):
        chain.append(secondary)
    return chain


# ── 失败分类 ──────────────────────────────────────────────────────────
def resolve_env_api_key(role: str, *, default_env: str = "") -> str:
    """只按 env **名字**取 key，不做 host 推断。

    给「构造函数里就得先把 key 拿到手」的调用点用（例如 ExperienceLearner）：
    这样 .env 里只写 ``TRIMUM_LLM_API_KEY_ENV=JIAOWOISAN_API_KEY`` 也能拿到 key，
    又不会因为机器上恰好存在别的 ``*_API_KEY`` 就误触发真实请求。
    """
    prefixes = (_ROLE_ENV_PREFIX.get(role, f"{role.upper()}_LLM"), _GLOBAL_PREFIX)
    value, _name = _resolve_api_key(
        prefixes=prefixes, direct=None, key_env=default_env, base_url=""
    )
    return value


def http_status(exc: BaseException) -> Optional[int]:
    """urllib.error.HTTPError.code / httpx.HTTPStatusError.response.status_code。"""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def is_network_error(exc: BaseException) -> bool:
    if isinstance(exc, (OSError, TimeoutError)):
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(hint in text for hint in _NETWORK_HINTS)


def should_switch(exc: BaseException) -> bool:
    status = http_status(exc)
    return status in _SWITCH_STATUSES if status is not None else False


def is_retryable(exc: BaseException) -> bool:
    """HTTP 5xx/429/408、网络/超时、以及解析类异常都值得再试一次。"""
    status = http_status(exc)
    if status is None:
        return True
    return status >= 500 or status in (408, 429)


def _backoff_seconds(index: int) -> float:
    return 0.5 * (index + 1)


def _bucket(target: LlmTarget) -> TokenBucket:
    with _registry_lock:
        bucket = _buckets.get(target.provider)
        if bucket is None:
            bucket = TokenBucket(target.rpm)
            _buckets[target.provider] = bucket
        return bucket


def _wait_for_slot(target: LlmTarget) -> float:
    wait = _bucket(target).consume()
    if wait > 0:
        with _registry_lock:
            _stats["rate_limit_waits"] += 1
            _stats["rate_limit_seconds"] += wait
        log.debug("llm throttle: provider=%s 等 %.2fs（%d 次/分）", target.provider, wait, target.rpm)
        _sleep(wait)
    return wait


async def _await_slot(target: LlmTarget) -> float:
    wait = _bucket(target).consume()
    if wait > 0:
        with _registry_lock:
            _stats["rate_limit_waits"] += 1
            _stats["rate_limit_seconds"] += wait
        log.debug("llm throttle: provider=%s 等 %.2fs（%d 次/分）", target.provider, wait, target.rpm)
        await _async_sleep(wait)
    return wait


def _cooldown_for(target: LlmTarget, exc: BaseException) -> Optional[float]:
    """给这个 provider 记一段冷却。返回冷却秒数，None = 不冷却。"""
    status = http_status(exc)
    if status == 429:
        seconds, kind = COOLDOWN_RATE_LIMIT, "配额打满"
    elif status is not None and status >= 500:
        seconds, kind = COOLDOWN_SERVER_ERROR, f"服务端 {status}"
    elif status is not None and 400 <= status < 500:
        seconds, kind = COOLDOWN_CLIENT_ERROR, f"客户端 {status}（key/模型名？）"
    elif is_network_error(exc):
        seconds, kind = COOLDOWN_NETWORK, "网络/超时"
    else:
        return None  # 解析失败之类：provider 没问题，别误伤
    set_cooldown(target, seconds)
    log.warning(
        "llm cooldown: provider=%s %.0fs（%s）", target.provider, seconds, kind
    )
    return seconds


def _charge_call() -> None:
    with _registry_lock:
        _stats["calls"] += 1


def _charge_fallback() -> None:
    with _registry_lock:
        _stats["fallbacks"] += 1


def _charge_skip() -> None:
    with _registry_lock:
        _stats["skipped_cooling"] += 1


def _finish(
    role: str,
    errors: list[tuple[LlmTarget, BaseException]],
    attempts: int,
) -> None:
    raise LlmCallError(role, errors, attempts)


def run_with_fallback(
    role: str,
    attempt: Callable[[LlmTarget], _T],
    *,
    targets: Optional[list[LlmTarget]] = None,
    defaults: Optional[dict[str, Any]] = None,
    fallback: Optional[bool] = None,
) -> tuple[_T, LlmTarget]:
    """顺序尝试候选链，返回 (attempt 的返回值, 实际用上的 target)。同步版。

    attempt(target) 里自己发 HTTP；抛任何异常都算这个 target 失败。
    """
    chain = targets if targets is not None else resolve_targets(
        role, defaults=defaults, fallback=fallback
    )
    errors: list[tuple[LlmTarget, BaseException]] = []
    attempts = 0
    for position, target in enumerate(chain):
        if not target.usable:
            errors.append((target, RuntimeError(target.reason_unusable)))
            continue
        remaining = cooldown_remaining(target)
        if remaining > 0:
            _charge_skip()
            errors.append((target, RuntimeError(f"冷却中（还剩 {remaining:.0f}s）")))
            continue
        tried = 0
        for index in range(max(1, target.max_retries)):
            tried += 1
            attempts += 1
            _wait_for_slot(target)
            try:
                _charge_call()
                value = attempt(target)
            except Exception as exc:  # noqa: BLE001 - 分类后决定重试还是换 target
                errors.append((target, exc))
                _cooldown_for(target, exc)
                if is_retryable(exc) and not should_switch(exc) and index < target.max_retries - 1:
                    wait = _backoff_seconds(index)
                    log.warning(
                        "llm retry: role=%s %s 第 %d 次失败（%s），%.1fs 后重试",
                        role, target.label, tried, exc, wait,
                    )
                    _sleep(wait)
                    continue
                break
            return value, target
        if position < len(chain) - 1:
            _charge_fallback()
            log.warning(
                "llm fallback: role=%s %s 失败（%s），换下一个 target",
                role, target.label, errors[-1][1] if errors else "unknown",
            )
    _finish(role, errors, attempts)
    raise AssertionError("unreachable")  # pragma: no cover - _finish 一定抛


async def arun_with_fallback(
    role: str,
    attempt: Callable[[LlmTarget], Awaitable[_T]],
    *,
    targets: Optional[list[LlmTarget]] = None,
    defaults: Optional[dict[str, Any]] = None,
    fallback: Optional[bool] = None,
) -> tuple[_T, LlmTarget]:
    """run_with_fallback 的异步版：节流与退避都走 asyncio.sleep，不阻塞事件循环。"""
    chain = targets if targets is not None else resolve_targets(
        role, defaults=defaults, fallback=fallback
    )
    errors: list[tuple[LlmTarget, BaseException]] = []
    attempts = 0
    for position, target in enumerate(chain):
        if not target.usable:
            errors.append((target, RuntimeError(target.reason_unusable)))
            continue
        remaining = cooldown_remaining(target)
        if remaining > 0:
            _charge_skip()
            errors.append((target, RuntimeError(f"冷却中（还剩 {remaining:.0f}s）")))
            continue
        tried = 0
        for index in range(max(1, target.max_retries)):
            tried += 1
            attempts += 1
            await _await_slot(target)
            try:
                _charge_call()
                value = await attempt(target)
            except Exception as exc:  # noqa: BLE001
                errors.append((target, exc))
                _cooldown_for(target, exc)
                if is_retryable(exc) and not should_switch(exc) and index < target.max_retries - 1:
                    wait = _backoff_seconds(index)
                    log.warning(
                        "llm retry: role=%s %s 第 %d 次失败（%s），%.1fs 后重试",
                        role, target.label, tried, exc, wait,
                    )
                    await _async_sleep(wait)
                    continue
                break
            return value, target
        if position < len(chain) - 1:
            _charge_fallback()
            log.warning(
                "llm fallback: role=%s %s 失败（%s），换下一个 target",
                role, target.label, errors[-1][1] if errors else "unknown",
            )
    _finish(role, errors, attempts)
    raise AssertionError("unreachable")  # pragma: no cover
