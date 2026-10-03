"""证书能力清单的运行期交集（E6 遗留，E5 第二片 4/4）。

§7.1 把信任拆成三层，各回答一个问题：**来源**（谁发布的、有没有被改过，见 ``trmpkg``）、
**身份**（这是谁的实例，见 ``agent_cert`` / ``identity``）、**能力**（这个身份允许动用
哪些工具、风险上限多少）。本模块只做第三层，规矩只有一条：

    **能力清单只收紧内置策略，永不放宽。**

三个来源，全部都要过（交集，不是并集）：

1. agent 证书的能力块（``agents/<name>/cert.json`` → ``certs/official|trusted/``）；
2. 用户身份证书的能力块（``~/.trimum/identity/``，``trm setup --max-risk`` 写的那个）；
3. 包登记（``installed.json5``）：``trust: untrusted`` 的条目**强制确认**。

判定表（``evaluate``）：

| 情形 | 结论 | 理由 |
|---|---|---|
| 能力块缺字段 / ``max_risk`` 非法 | confirm | 读不懂就别装作读懂了 |
| ``scope: untrusted``（降级安装） | confirm | 来源从没被背书过 |
| 证书过期 | deny | 过期证书不是「待确认」，是无效 |
| 工具不在白名单 | deny | 白名单问的是「允许动用哪些工具」 |
| 风险超过 ``max_risk`` | confirm | 上限之外仍可由人放行（或走 JIT 一次性授权） |
| 其余 | 不表态 | 交回内置策略 |

``max_risk: inherit``（默认）= 不额外加限制。风险序与 ``ecosystem.RISK_ORDER`` 同一份，
不另立一套。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from . import trmpkg
from .ecosystem import DEFAULT_RISK, RISK_ORDER
from .identity import MAX_RISK_VALUES

#: ``max_risk`` 的默认值：不额外加限制（与 ``agent_cert.default_capabilities`` 一致）
INHERIT = "inherit"
#: 降级安装（``--allow-untrusted``）写进证书的 scope
UNTRUSTED = "untrusted"

ALLOW = "allow"
CONFIRM = "confirm"
DENY = "deny"
#: 严格度顺序（合并多个来源时取最严）
STRICTNESS = (DENY, CONFIRM, ALLOW)


@dataclass(frozen=True)
class Tightening:
    """一条收紧结论：谁提的、要什么、为什么。"""

    action: str
    reason: str
    source: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "source": self.source,
            "detail": dict(self.detail),
        }


def normalise(capabilities: Any) -> tuple[dict[str, Any], list[str]]:
    """Normalise a capability block; returns ``(block, problems)``.

    Problems never silently become "no restriction": the caller turns them into a
    confirmation, because a capability block we cannot read is not the same thing
    as a capability block that grants everything.
    """
    caps = dict(capabilities) if isinstance(capabilities, dict) else {}
    problems: list[str] = []

    raw_tools = caps.get("tools")
    if raw_tools is None:
        tools = ["*"]
    elif isinstance(raw_tools, str):
        tools = [raw_tools]
    elif isinstance(raw_tools, (list, tuple, set)):
        tools = [str(item).strip() for item in raw_tools if str(item).strip()]
    else:
        tools = ["*"]
        problems.append(f"tools 应为列表（收到 {type(raw_tools).__name__}）")

    max_risk = str(caps.get("max_risk") or INHERIT).strip().lower()
    if max_risk not in MAX_RISK_VALUES:
        problems.append(f"max_risk 非法：{max_risk!r}（可选 {'/'.join(MAX_RISK_VALUES)}）")
        max_risk = INHERIT

    expires_at = caps.get("expires_at") or None
    scope = str(caps.get("scope") or "").strip().lower()

    return {
        "tools": tools or ["*"],
        "max_risk": max_risk,
        "expires_at": expires_at,
        "scope": scope,
    }, problems


def tool_allowed(tool: str, patterns: Sequence[str]) -> bool:
    """Is *tool* inside the whitelist?

    Entries are globs against the tool's full name (``file.read``); an entry without
    a dot also covers that whole family (``file`` → ``file.*``), so a certificate can
    say "shell + file access" without enumerating every sub-tool.
    """
    name = str(tool or "")
    for pattern in patterns:
        text = str(pattern or "").strip()
        if not text:
            continue
        if text == "*" or fnmatch.fnmatch(name, text):
            return True
        if "." not in text and fnmatch.fnmatch(name, f"{text}.*"):
            return True
    return False


def evaluate(
    capabilities: Any,
    *,
    tool: str = "shell",
    risk: str = "low",
    source: str = "",
    now: str = "",
) -> Optional[Tightening]:
    """One capability block's verdict for one call (``None`` = no statement)."""
    caps, problems = normalise(capabilities)
    if problems:
        return Tightening(
            CONFIRM,
            "能力清单不完整：" + "；".join(problems),
            source,
            {"capabilities": caps},
        )

    if caps["scope"] == UNTRUSTED:
        return Tightening(
            CONFIRM,
            "来源不可信（安装时未验证）—— 需要逐条确认",
            source,
            {"capabilities": caps},
        )

    expires_at = caps["expires_at"]
    if expires_at and str(expires_at) <= str(now or trmpkg.now()):
        return Tightening(
            DENY, f"证书已过期：{expires_at}", source, {"capabilities": caps}
        )

    if not tool_allowed(tool, caps["tools"]):
        return Tightening(
            DENY,
            f"证书不允许动用 {tool}（白名单 {'/'.join(caps['tools'])}）",
            source,
            {"capabilities": caps},
        )

    ceiling = caps["max_risk"]
    if ceiling != INHERIT:
        level = str(risk or DEFAULT_RISK).lower()
        if RISK_ORDER.get(level, RISK_ORDER[DEFAULT_RISK]) > RISK_ORDER[ceiling]:
            return Tightening(
                CONFIRM,
                f"风险 {level} 超出证书上限 max_risk={ceiling}",
                source,
                {"capabilities": caps},
            )
    return None


def agent_capabilities(agent_id: str) -> dict[str, Any]:
    """The agent's certificate capability block (empty when it has no certificate)."""
    from .agent_cert import check_agent_trust

    _level, cert = check_agent_trust(agent_id)
    return dict(cert.capabilities or {}) if cert is not None else {}


def identity_capabilities() -> dict[str, Any]:
    """The user's identity capability block (``trm setup --max-risk`` wrote it)."""
    from .identity import load_identity

    doc = load_identity() or {}
    return dict(doc.get("capabilities") or {})


def untrusted_installs(names: Sequence[str]) -> list[str]:
    """Installed package names among *names* that came in through the downgrade path."""
    from .pkg_install import untrusted_names

    wanted = {str(name) for name in names if name}
    return sorted(wanted & untrusted_names())


def tighten(
    agent_id: str,
    *,
    tool: str = "shell",
    risk: str = "low",
    tool_name: str = "",
    now: str = "",
) -> Optional[Tightening]:
    """The runtime intersection across every source; ``None`` means "no restriction".

    The strictest verdict wins (deny ▸ confirm); "allow" is never returned because a
    certificate can only ever *remove* freedom, never add it.
    """
    candidates: list[tuple[str, dict[str, Any]]] = []

    agent_caps = agent_capabilities(agent_id)
    if agent_caps:
        candidates.append((f"agent-cert:{agent_id}", agent_caps))

    identity_caps = identity_capabilities()
    if identity_caps:
        candidates.append(("identity", identity_caps))

    for name in untrusted_installs([tool_name, tool, agent_id]):
        candidates.append(
            (
                f"installed-package:{name}",
                {"tools": ["*"], "max_risk": INHERIT, "scope": UNTRUSTED},
            )
        )

    verdicts = [
        verdict
        for verdict in (
            evaluate(caps, tool=tool, risk=risk, source=source, now=now)
            for source, caps in candidates
        )
        if verdict is not None
    ]
    if not verdicts:
        return None
    for action in STRICTNESS:
        for verdict in verdicts:
            if verdict.action == action:
                return verdict
    return None


__all__ = [
    "ALLOW",
    "CONFIRM",
    "DENY",
    "INHERIT",
    "STRICTNESS",
    "Tightening",
    "UNTRUSTED",
    "agent_capabilities",
    "evaluate",
    "identity_capabilities",
    "normalise",
    "tighten",
    "tool_allowed",
    "untrusted_installs",
]