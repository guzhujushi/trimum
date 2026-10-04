"""llm_router 单元测试：选谁 / 等多久 / 失败换谁。

不碰网络，也不真等：attempt 都是假的、睡眠被打桩，验证的是「策略」而不是「墙钟」。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import llm_router as R

_ENV_PATTERN = re.compile(r"^(TRIMUM|POLICY|PLANNER|TRANSFORM|EXPERIENCE|AGENT)_LLM")
_SHARED_KEYS = ("JIAOWOISAN_API_KEY", "API_KEY", "DEEPSEEK_API_KEY")


@pytest.fixture(autouse=True)
def router_env(monkeypatch, tmp_path):
    """干净环境 + 干净的桶/冷却 + 打桩睡眠（返回记录等待时长的列表）。"""
    for name in list(os.environ):
        if _ENV_PATTERN.match(name) or name in _SHARED_KEYS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
    R.reset_state()
    # 注意：不要在这里给 `R._clock` 装假钟 —— 既有用例（`test_throttle_is_applied_between_calls`
    # / `test_arun_awaits_instead_of_blocking`）的期望值是按真实时钟算的（≈60/rpm 秒），
    # 装了「每次调用 +1s」的钟会把它们带偏。需要冻结钟的用例自己局部构造（见 T2）。
    waits: list[float] = []
    monkeypatch.setattr(R, "_sleep", lambda seconds: waits.append(seconds))

    async def _fake_async_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(R, "_async_sleep", _fake_async_sleep)
    yield waits
    R.reset_state()


def _http_error(status: int, headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://x/chat/completions", status, "boom", headers if headers is not None else {}, None
    )


def _target(
    tier: str = "primary",
    model: str = "qwen3.8-27b",
    base_url: str = "https://models.sjtu.edu.cn/api/v1",
    api_key: str = "sk-a",
    rpm: int = 9,
    retries: int = 1,
) -> R.LlmTarget:
    return R.LlmTarget(
        role=R.ROLE_POLICY,
        tier=tier,
        model=model,
        base_url=base_url,
        api_key=api_key,
        api_key_env="TEST_KEY",
        rpm=rpm,
        timeout=5.0,
        max_retries=retries,
    )


# ── 选谁 ──────────────────────────────────────────────────────────────


def test_default_chain_is_jiaowoisan_then_deepseek():
    chain = R.resolve_targets(R.ROLE_POLICY)
    assert [t.tier for t in chain] == ["primary", "fallback"]
    assert chain[0].base_url == R.DEFAULT_PRIMARY_BASE_URL
    assert chain[0].model == "qwen3.8-27b"
    assert chain[0].rpm == R.SJTU_RPM
    assert chain[0].timeout == R.DEFAULT_TIMEOUT
    assert chain[1].model == "deepseek-flash"
    assert chain[1].base_url == R.DEFAULT_FALLBACK_BASE_URL
    assert chain[1].rpm == 0, "DeepSeek 官方没有硬 RPM，默认不限流"


def test_role_env_beats_global_env_beats_defaults(monkeypatch):
    monkeypatch.setenv("TRIMUM_LLM_MODEL", "global-model")
    monkeypatch.setenv("TRIMUM_LLM_BASE_URL", "https://global.example/v1")
    monkeypatch.setenv("POLICY_LLM_MODEL", "role-model")
    chain = R.resolve_targets(
        R.ROLE_POLICY,
        defaults={"model": "cfg-model", "base_url": "https://cfg.example/v1"},
    )
    assert chain[0].model == "role-model", "角色级 env 最优先"
    assert chain[0].base_url == "https://global.example/v1", "该字段没给角色级就用全局"


def test_defaults_beat_builtin(monkeypatch):
    """yaml 里写死的值算默认值：既压过内置默认，又被 env 压过。"""
    chain = R.resolve_targets(
        R.ROLE_POLICY,
        defaults={"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1",
                  "api_key_env": "DEEPSEEK_API_KEY", "timeout": 15, "max_retries": 2},
    )
    assert chain[0].model == "deepseek-chat"
    assert chain[0].timeout == 15.0
    assert chain[0].max_retries == 2
    monkeypatch.setenv("TRIMUM_LLM_MODEL", "qwen3.8-27b")
    assert R.resolve_targets(R.ROLE_POLICY, defaults={"model": "deepseek-chat"})[0].model == "qwen3.8-27b"


def test_api_key_env_indirection(monkeypatch):
    monkeypatch.setenv("TRIMUM_LLM_API_KEY_ENV", "JIAOWOISAN_API_KEY")
    monkeypatch.setenv("JIAOWOISAN_API_KEY", "sk-indirect")
    target = R.resolve_targets(R.ROLE_TRANSFORM)[0]
    assert target.api_key == "sk-indirect"
    assert target.api_key_env == "JIAOWOISAN_API_KEY"


def test_api_key_env_named_but_empty_is_reported(monkeypatch):
    monkeypatch.setenv("TRIMUM_LLM_API_KEY_ENV", "NOT_SET_ANYWHERE")
    target = R.resolve_targets(R.ROLE_TRANSFORM)[0]
    assert target.api_key == ""
    assert target.api_key_env == "NOT_SET_ANYWHERE"
    assert target.usable is False


def test_direct_env_key_beats_indirection(monkeypatch):
    monkeypatch.setenv("TRIMUM_LLM_API_KEY_ENV", "JIAOWOISAN_API_KEY")
    monkeypatch.setenv("JIAOWOISAN_API_KEY", "sk-indirect")
    monkeypatch.setenv("TRIMUM_LLM_API_KEY", "sk-direct")
    assert R.resolve_targets(R.ROLE_TRANSFORM)[0].api_key == "sk-direct"


def test_key_implied_by_host(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-jiaowoisan")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    chain = R.resolve_targets(R.ROLE_AGENT)
    assert chain[0].api_key == "sk-jiaowoisan", "交我算 host → JIAOWOISAN_API_KEY/API_KEY"
    assert chain[1].api_key == "sk-deepseek", "deepseek host → DEEPSEEK_API_KEY"


def test_local_endpoint_needs_no_key():
    chain = R.resolve_targets(
        R.ROLE_POLICY, defaults={"base_url": "http://127.0.0.1:8080/v1", "model": "local"}
    )
    assert chain[0].usable is True


def test_rpm_implied_by_host_and_overridable(monkeypatch):
    assert R.resolve_targets(R.ROLE_POLICY)[0].rpm == 9
    assert R.resolve_targets(
        R.ROLE_POLICY, defaults={"base_url": "https://api.deepseek.com/v1"}
    )[0].rpm == 0
    monkeypatch.setenv("POLICY_LLM_RPM", "3")
    assert R.resolve_targets(R.ROLE_POLICY)[0].rpm == 3


def test_role_pointing_elsewhere_does_not_inherit_global_rpm(monkeypatch):
    """TRIMUM_LLM_RPM 是「交我算的配额」，不该跟着角色级地址搬到别的 provider 上。"""
    monkeypatch.setenv("TRIMUM_LLM_RPM", "9")
    assert R.resolve_targets(R.ROLE_POLICY)[0].rpm == 9, "用全局地址 → 继承全局 RPM"

    monkeypatch.setenv("AGENT_LLM_BASE_URL", "https://api.deepseek.com/v1")
    assert R.resolve_targets(R.ROLE_AGENT)[0].rpm == 0, "指到 DeepSeek → 不继承"

    monkeypatch.setenv("AGENT_LLM_RPM", "3")
    assert R.resolve_targets(R.ROLE_AGENT)[0].rpm == 3, "角色级显式写了就听角色的"


def test_fallback_off(monkeypatch):
    assert len(R.resolve_targets(R.ROLE_POLICY, fallback=False)) == 1
    monkeypatch.setenv("TRIMUM_LLM_FALLBACK_ENABLED", "0")
    assert len(R.resolve_targets(R.ROLE_POLICY)) == 1


def test_identical_fallback_is_dropped(monkeypatch):
    monkeypatch.setenv("TRIMUM_LLM_FALLBACK_BASE_URL", R.DEFAULT_PRIMARY_BASE_URL)
    monkeypatch.setenv("TRIMUM_LLM_FALLBACK_MODEL", "qwen3.8-27b")
    assert len(R.resolve_targets(R.ROLE_POLICY)) == 1


def test_role_level_fallback_override(monkeypatch):
    """AGENT 角色的目标形态：主 deepseek-flash（贵但强），备交我算（免费但弱）。"""
    monkeypatch.setenv("AGENT_LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("AGENT_LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("AGENT_LLM_FALLBACK_MODEL", "qwen3.8-27b")
    monkeypatch.setenv("AGENT_LLM_FALLBACK_BASE_URL", R.DEFAULT_PRIMARY_BASE_URL)
    monkeypatch.setenv("AGENT_LLM_FALLBACK_API_KEY_ENV", "API_KEY")
    monkeypatch.setenv("API_KEY", "sk-api")
    chain = R.resolve_targets(R.ROLE_AGENT)
    assert chain[0].model == "deepseek-flash"
    assert chain[1].model == "qwen3.8-27b"
    assert chain[1].api_key == "sk-api"


# ── 等多久 ────────────────────────────────────────────────────────────


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_reserves_slots():
    clock = _FakeClock()
    bucket = R.TokenBucket(9, clock=clock)
    assert bucket.consume() == 0.0, "首次调用不用等"
    wait = bucket.consume()
    assert 6.5 < wait < 6.8, f"9 次/分 → 第 2 次大约等 6.67s，实际 {wait}"
    clock.now += wait
    assert bucket.consume() == pytest.approx(wait, abs=0.2), (
        "桶是预扣式的：第 2 次调用已经预定了 6.67s 后的槽位，第 3 次要再排一个窗口"
    )
    clock.now += 2 * wait
    assert bucket.consume() == pytest.approx(0.0, abs=1e-9), "整整空出两个窗口后额度回满"


def test_token_bucket_unlimited_when_rpm_zero():
    bucket = R.TokenBucket(0)
    assert [bucket.consume() for _ in range(5)] == [0.0] * 5


def test_throttle_is_applied_between_calls(router_env):
    waits = router_env
    target = _target(rpm=6, api_key="sk-a")  # 6 次/分 = 每 10 秒一次
    calls: list[int] = []

    def attempt(_target: R.LlmTarget) -> str:
        calls.append(1)
        return "ok"

    for _ in range(3):
        R.run_with_fallback(R.ROLE_POLICY, attempt, targets=[target])
    assert len(calls) == 3
    assert len(waits) == 2, f"第 2、3 次各等一次，实际等了 {waits}"
    assert waits[0] == pytest.approx(10.0, abs=0.5)


def test_bucket_is_per_provider_not_per_role():
    policy = R.resolve_targets(R.ROLE_POLICY)[0]
    agent = R.resolve_targets(R.ROLE_AGENT)[0]
    assert policy.provider == agent.provider
    assert R._bucket(policy) is R._bucket(agent), "同一 provider 共用一个桶（配额是账号级的）"


# ── 失败换谁 ──────────────────────────────────────────────────────────


def test_switch_to_fallback_on_429(router_env):
    primary = _target(tier="primary")
    fallback = _target(tier="fallback", model="deepseek-flash",
                       base_url="https://api.deepseek.com/v1", api_key="sk-d", rpm=0)
    seen: list[str] = []

    def attempt(target: R.LlmTarget) -> str:
        seen.append(target.tier)
        if target.tier == "primary":
            raise _http_error(429)
        return "from-fallback"

    value, used = R.run_with_fallback(
        R.ROLE_POLICY, attempt, targets=[primary, fallback]
    )
    assert value == "from-fallback"
    assert used.tier == "fallback"
    assert seen == ["primary", "fallback"], "429 不原地重试，直接换 provider"
    assert R.stats()["fallbacks"] == 1
    assert R.cooldown_remaining(primary) > 0, "429 要给这个 provider 记冷却"


def _cooldown_on_429(headers: dict | None) -> float:
    primary = _target(tier="primary")
    return R._cooldown_for(primary, _http_error(429, headers))


def test_429_retry_after_seconds_used_as_cooldown(router_env):
    assert _cooldown_on_429({"Retry-After": "30"}) == pytest.approx(30)


def test_429_retry_after_http_date_in_sane_range(router_env):
    from datetime import datetime, timedelta, timezone

    future = datetime.now(timezone.utc) + timedelta(seconds=90)
    value = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    cooldown = _cooldown_on_429({"retry-after": value})
    assert 60 < cooldown <= 91, f"HTTP 日期应折算成剩余秒数，got {cooldown}"


def test_429_without_retry_after_falls_back_to_60(router_env):
    assert _cooldown_on_429(None) == pytest.approx(R.COOLDOWN_RATE_LIMIT)
    assert _cooldown_on_429({"Content-Type": "application/json"}) == pytest.approx(60)


def test_429_retry_above_cap_clamped_to_300(router_env):
    assert _cooldown_on_429({"Retry-After": "9999"}) == pytest.approx(300)
    assert _cooldown_on_429({"Retry-After": "9999"}) == pytest.approx(R.COOLDOWN_RATE_LIMIT_MAX)


def test_429_httpx_style_response_headers(router_env):
    class _HttpxResponse:
        status_code = 429

        def __init__(self, headers):
            self.headers = headers

    class _HttpxError(Exception):
        def __init__(self, headers):
            self.response = _HttpxResponse(headers)

    primary = _target(tier="primary")
    exc = _HttpxError({"retry-after": "42"})
    assert R._retry_after_seconds(exc) == pytest.approx(42)
    assert R._cooldown_for(primary, exc) == pytest.approx(42)

    from datetime import datetime, timedelta, timezone

    future = datetime.now(timezone.utc) + timedelta(seconds=90)
    date_str = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    exc2 = _HttpxError({"Retry-After": date_str})
    assert 60 < R._cooldown_for(_target(tier="primary"), exc2) <= 91


def test_429_bare_exception_without_headers(router_env):
    class _Bare429(Exception):
        code = 429

    exc = _Bare429()
    assert R._retry_after_seconds(exc) is None
    assert R._cooldown_for(_target(tier="primary"), exc) == pytest.approx(60)


def test_429_non_string_header_values_never_raise(router_env):
    assert R._retry_after_seconds(_http_error(429, {"Retry-After": 30})) == 30.0
    assert R._cooldown_for(_target(tier="primary"), _http_error(429, {"Retry-After": 30})) == pytest.approx(30)
    assert R._retry_after_seconds(_http_error(429, {"Retry-After": None})) is None
    assert R._cooldown_for(_target(tier="primary"), _http_error(429, {"Retry-After": None})) == pytest.approx(60)
    assert R._retry_after_seconds(_http_error(429, {"Retry-After": ["30"]})) is None


def test_cooled_down_provider_is_skipped_next_time(router_env):
    primary = _target(tier="primary")
    fallback = _target(tier="fallback", model="deepseek-flash",
                       base_url="https://api.deepseek.com/v1", api_key="sk-d", rpm=0)
    seen: list[str] = []

    def attempt(target: R.LlmTarget) -> str:
        seen.append(target.tier)
        if target.tier == "primary":
            raise _http_error(429)
        return "ok"

    R.run_with_fallback(R.ROLE_POLICY, attempt, targets=[primary, fallback])
    seen.clear()
    R.run_with_fallback(R.ROLE_POLICY, attempt, targets=[primary, fallback])
    assert seen == ["fallback"], "冷却期内不该再碰主 provider"
    assert R.stats()["skipped_cooling"] == 1


def test_all_targets_unusable_raises_before_any_call(router_env):
    primary = _target(tier="primary", api_key="")
    fallback = _target(tier="fallback", api_key="",
                       base_url="https://api.deepseek.com/v1", model="deepseek-flash")

    def attempt(_target: R.LlmTarget) -> str:  # pragma: no cover - 不该被调用
        raise AssertionError("没有 key 就不该发请求")

    with pytest.raises(R.LlmCallError) as excinfo:
        R.run_with_fallback(R.ROLE_POLICY, attempt, targets=[primary, fallback])
    assert "缺少 API key" in str(excinfo.value)
    assert R.stats()["calls"] == 0


def test_server_error_retries_then_switches(router_env):
    primary = _target(tier="primary", retries=2)
    fallback = _target(tier="fallback", model="deepseek-flash",
                       base_url="https://api.deepseek.com/v1", api_key="sk-d", rpm=0)
    seen: list[str] = []

    def attempt(target: R.LlmTarget) -> str:
        seen.append(target.tier)
        if target.tier == "primary":
            raise _http_error(503)
        return "ok"

    value, used = R.run_with_fallback(R.ROLE_POLICY, attempt, targets=[primary, fallback])
    assert value == "ok" and used.tier == "fallback"
    assert seen == ["primary", "primary", "fallback"], "5xx 先重试（max_retries=2）再换"
    assert router_env and router_env[0] == pytest.approx(0.5, abs=0.1), "重试前退避 0.5s"


def test_parse_error_retries_without_cooldown(router_env):
    """解析失败（JSON 烂了）算这个 target 失败，但 provider 没毛病 → 不冷却。"""
    primary = _target(tier="primary", retries=2)
    seen: list[str] = []

    def attempt(target: R.LlmTarget) -> str:
        seen.append(target.tier)
        raise ValueError("Expecting value: line 1 column 1")

    with pytest.raises(R.LlmCallError):
        R.run_with_fallback(R.ROLE_POLICY, attempt, targets=[primary])
    assert seen == ["primary", "primary"]
    assert R.cooldown_remaining(primary) == 0.0


def test_network_error_cools_down_and_switches(router_env):
    primary = _target(tier="primary")
    fallback = _target(tier="fallback", model="deepseek-flash",
                       base_url="https://api.deepseek.com/v1", api_key="sk-d", rpm=0)

    def attempt(target: R.LlmTarget) -> str:
        if target.tier == "primary":
            raise OSError("Connection refused")
        return "ok"

    assert R.run_with_fallback(R.ROLE_POLICY, attempt, targets=[primary, fallback])[0] == "ok"
    assert 0 < R.cooldown_remaining(primary) <= R.COOLDOWN_NETWORK


def test_httpx_style_status_error_is_classified():
    class _Response:
        status_code = 429

    class _HTTPStatusError(Exception):
        response = _Response()

    assert R.http_status(_HTTPStatusError()) == 429
    assert R.should_switch(_HTTPStatusError()) is True


def test_unresolvable_role_uses_its_own_prefix(monkeypatch):
    """没登记的 role（插件/未来角色）也要能配：<ROLE>_LLM_*。"""
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "custom-model")
    assert R.resolve_targets("custom")[0].model == "custom-model"


# ── 异步版 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_arun_switches_on_timeout(router_env):
    primary = _target(tier="primary", rpm=0)
    fallback = _target(tier="fallback", model="deepseek-flash",
                       base_url="https://api.deepseek.com/v1", api_key="sk-d", rpm=0)
    seen: list[str] = []

    async def attempt(target: R.LlmTarget) -> str:
        seen.append(target.tier)
        if target.tier == "primary":
            raise TimeoutError("read timeout")
        return "async-ok"

    value, used = await R.arun_with_fallback(
        R.ROLE_AGENT, attempt, targets=[primary, fallback]
    )
    assert value == "async-ok" and used.tier == "fallback"
    assert seen == ["primary", "fallback"]
    assert R.cooldown_remaining(primary) > 0


@pytest.mark.asyncio
async def test_arun_awaits_instead_of_blocking(router_env):
    target = _target(rpm=6, api_key="sk-a")
    calls: list[int] = []

    async def attempt(_target: R.LlmTarget) -> str:
        calls.append(1)
        return "ok"

    for _ in range(2):
        await R.arun_with_fallback(R.ROLE_AGENT, attempt, targets=[target])
    assert len(calls) == 2
    assert router_env and router_env[0] == pytest.approx(10.0, abs=0.5)


# ── P1 缺件：跨进程限流 + token 维度 ──────────────────────


def test_file_bucket_cross_process_third_consume_waits(tmp_path, monkeypatch):
    """T1: 同一 TRIMUM_HOME，rpm=2，父进程 + 真起子进程共 3 次 consume() ⇒ 第 3 次 > 0。"""
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
    src_root = os.path.join(os.path.dirname(__file__), "..")
    child_src = "import os, sys\nsys.path.insert(0, \"src\")\nfrom trimum_core import llm_router as R\nprint(repr(R.FileTokenBucket(2).consume()))"
    results = []
    results.append(R.FileTokenBucket(2).consume())
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-c", child_src],
            cwd=src_root, env={**os.environ, "TRIMUM_HOME": str(tmp_path)},
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        results.append(float(proc.stdout.strip()))
    # 容量口径与 TokenBucket 一致（capacity = 1 个 burst）：第 1 次放行，之后每一次都要等，
    # 而且等的是「共享文件里的同一个槽位」——这条只有在状态真的跨进程共享时才成立。
    assert results[0] == 0.0
    assert results[1] > 0, "第 2 次（子进程）必须读到父进程预扣后的槽位：" + repr(results)
    assert results[2] > results[1], "第 3 次要排在更后面（预扣是累计的）：" + repr(results)


def test_file_bucket_pre_deduct_same_process(tmp_path, monkeypatch):
    """T2: rpm=2 同进程预扣 ⇒ 第 1 次 0.0，之后每次都 > 0 且**逐次变大**（冻结钟）。"""
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
    _ticks = {"t": 0.0}
    _clock = lambda: _ticks.__setitem__("t", _ticks["t"] + 1.0) or _ticks["t"]
    bucket = R.FileTokenBucket(2, clock=_clock)
    first = bucket.consume()
    second = bucket.consume()
    third = bucket.consume()
    assert first == 0.0, "第 1 次占的是那个空槽，不用等"
    assert second > 0.0, "第 2 次必须等（容量只有 1 个 burst，与 TokenBucket 同口径）"
    assert third > second, f"预扣是累计的：第 3 次应排在更后面（{third} <= {second}）"


def test_file_bucket_corrupted_file_self_heals(tmp_path, monkeypatch):
    """T3: 落盘文件写垃圾 ⇒ consume() 不抛且返回 0.0（自愈）。"""
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path))
    (tmp_path / "llm-throttle.json").write_text("this is not json 垃圾", encoding="utf-8")
    assert R.FileTokenBucket(2).consume() == 0.0


def test_record_usage_accumulates_into_stats():
    """T4: record_usage(3,5) ⇒ prompt/completion/total = 3/5/8（含累加）。"""
    R.reset_state()
    R.record_usage(3, 5)
    s = R.stats()
    assert s["prompt_tokens"] == 3
    assert s["completion_tokens"] == 5
    assert s["total_tokens"] == 8
    R.record_usage(3, 5)
    s = R.stats()
    assert s["prompt_tokens"] == 6
    assert s["completion_tokens"] == 10
    assert s["total_tokens"] == 16


# ── 决策 19 修订版 A：token 记账收口在统一调用（usage_of 抽取器） ──
def test_sync_usage_of_records_into_stats(router_env):
    """T1 同步记账：usage_of 抽 (10,4) ⇒ 返回不变，stats 记 10/4/14。"""
    R.reset_state()
    target = _target(rpm=0)
    value = object()

    def attempt(_t: R.LlmTarget):
        return value

    result, used = R.run_with_fallback(
        R.ROLE_POLICY, attempt, targets=[target], usage_of=lambda v: (10, 4)
    )
    assert result is value and used is target
    s = R.stats()
    assert s["prompt_tokens"] == 10
    assert s["completion_tokens"] == 4
    assert s["total_tokens"] == 14


@pytest.mark.asyncio
async def test_async_usage_of_records_into_stats(router_env):
    """T2 异步记账：arun_with_fallback 同口径，stats 记 10/4/14。"""
    R.reset_state()
    target = _target(rpm=0)
    value = object()

    async def attempt(_t: R.LlmTarget):
        return value

    result, used = await R.arun_with_fallback(
        R.ROLE_AGENT, attempt, targets=[target], usage_of=lambda v: (10, 4)
    )
    assert result is value and used is target
    s = R.stats()
    assert s["prompt_tokens"] == 10
    assert s["completion_tokens"] == 4
    assert s["total_tokens"] == 14


def test_sync_usage_of_raising_never_fails_business(router_env):
    """T3 观测失败不许让业务失败：usage_of 抛 RuntimeError ⇒ 照常返回，token 仍 0。"""
    R.reset_state()
    target = _target(rpm=0)
    value = object()

    def attempt(_t: R.LlmTarget):
        return value

    def boom(_v):
        raise RuntimeError("usage_of 崩了")

    result, used = R.run_with_fallback(
        R.ROLE_POLICY, attempt, targets=[target], usage_of=boom
    )
    assert result is value and used is target
    s = R.stats()
    assert s["prompt_tokens"] == 0
    assert s["completion_tokens"] == 0
    assert s["total_tokens"] == 0


def test_sync_usage_of_default_keeps_old_behavior(router_env):
    """T4 不传 usage_of 行为不变：返回值与 stats token 三字段仍 0。"""
    R.reset_state()
    target = _target(rpm=0)
    value = object()

    def attempt(_t: R.LlmTarget):
        return value

    result, used = R.run_with_fallback(R.ROLE_POLICY, attempt, targets=[target])
    assert result is value and used is target
    s = R.stats()
    assert s["prompt_tokens"] == 0
    assert s["completion_tokens"] == 0
    assert s["total_tokens"] == 0
