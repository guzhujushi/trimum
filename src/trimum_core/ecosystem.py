"""生态条目统一 schema 与风险分级（E4）。

四层（环境清单 / MCP / Agent Skills / workflow 目录）产出的每一样东西，进 trimum 时
先变成一个 :class:`EcosystemEntry`，它回答四个问题：

* **从哪来** —— ``trust`` / ``source_url`` / ``author`` / ``origin``；
* **要什么** —— ``requires``（外部依赖，如某个二进制）；
* **有多危险** —— ``risk``（由 :func:`assess_risk` 给出，附理由）；
* **现在能不能用** —— ``enabled``。

三条设计要点：

1. **注册 ≠ 授权**：``enabled`` 只决定它进不进 ``ToolRegistry``；进来之后仍走 ToolGateway
   六层 + SecurityRule + 审计，本模块不做任何执行。
2. **分级可解释**：:func:`assess_risk` 返回 ``(level, reasons)``，每条理由都写清是哪个词触发的，
   dry-run 直接展示给用户 —— 用户要能反驳分级，否则分级就是黑箱。
3. **无证据不猜低**：没命中任何动词表时给 ``medium``。猜低会让第三方命令悄悄变成"低风险"，
   一律给 high 又会让所有导入都变成高危而失去区分度。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

TRUST_LEVELS: tuple[str, ...] = ("official", "curated", "third-party", "local")
ENTRY_KINDS: tuple[str, ...] = ("tool", "skill", "workflow", "mcp")

#: 由低到高；顺序即比较依据。
RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
RISK_LEVELS: tuple[str, ...] = tuple(RISK_ORDER)
DEFAULT_RISK = "medium"

#: 破坏性形态：出现即 critical（在整段文本上做子串匹配，不切词）。
CRITICAL_PATTERNS: tuple[str, ...] = (
    "mkfs",
    "dd if=",
    "wipefs",
    "shutdown",
    "reboot",
    "rm -rf /",
    "> /dev/sd",
)

#: 变更系统或不可逆的动词。
HIGH_WORDS: frozenset[str] = frozenset(
    {
        "install", "uninstall", "remove", "purge", "delete", "erase", "rm", "unlink",
        "kill", "pkill", "killall", "prune", "format", "drop", "truncate", "destroy",
        "push", "publish", "deploy", "revoke", "chmod", "chown", "sudo", "su",
        "upgrade", "reset", "terminate", "stop", "restart", "disable", "cancel",
    }
)

#: 有副作用但不破坏的动词。
MEDIUM_WORDS: frozenset[str] = frozenset(
    {
        "run", "exec", "execute", "start", "create", "add", "set", "update", "sync",
        "pull", "clone", "apply", "import", "load", "write", "edit", "move", "rename",
        "link", "mount", "open", "send", "post", "put", "enable", "attach", "touch",
    }
)

#: 纯读动词。
LOW_WORDS: frozenset[str] = frozenset(
    {
        "list", "ls", "show", "get", "status", "info", "log", "logs", "version",
        "read", "cat", "search", "find", "query", "diff", "check", "verify",
        "describe", "inspect", "which", "env", "help", "stat", "history", "view",
        "tree", "count", "print", "display", "wait", "ping",
    }
)

#: "免确认"类旗标：本身不是命令，但把一次操作变成不可回头的操作。
ESCALATING_FLAGS: frozenset[str] = frozenset(
    {"--force", "-f", "--yes", "-y", "--assume-yes", "--no-confirm", "--no-prompt"}
)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_WORD_SPLIT_RE = re.compile(r"[-_.\s]+")

LEVEL_LABELS: dict[str, str] = {
    "low": "只读",
    "medium": "有副作用",
    "high": "变更系统/不可逆",
    "critical": "破坏性",
}


def word_tokens(token: str) -> list[str]:
    """Split one command-ish token into comparable words.

    ``trm-create`` / ``create_thing`` / ``create.thing`` all yield ``create``.
    """
    return [part for part in _WORD_SPLIT_RE.split(token.strip().lower()) if part]


def max_risk(*levels: str) -> str:
    """Return the most severe of *levels* (unknown values are ignored)."""
    best = DEFAULT_RISK
    seen = False
    for level in levels:
        key = (level or "").strip().lower()
        if key not in RISK_ORDER:
            continue
        if not seen or RISK_ORDER[key] > RISK_ORDER[best]:
            best = key
            seen = True
    return best


def assess_risk(
    *tokens: str,
    flags: Iterable[str] = (),
) -> tuple[str, list[str]]:
    """Grade one thing by the words it is made of.

    ``tokens`` is normally ``(binary_name, *subcommand_names)``. Returns the
    level plus one human-readable reason per contributing piece of evidence.
    """
    level = ""
    reasons: list[str] = []

    for raw in tokens:
        token = (raw or "").strip()
        if not token:
            continue
        lowered = token.lower()

        hit = next((p for p in CRITICAL_PATTERNS if p in lowered), None)
        if hit is not None:
            return "critical", [f"`{token}` 命中破坏性形态 `{hit}`"]

        words = word_tokens(token)
        for table, name in (
            (HIGH_WORDS, "high"),
            (MEDIUM_WORDS, "medium"),
            (LOW_WORDS, "low"),
        ):
            matched = [w for w in words if w in table]
            if matched:
                if not level or RISK_ORDER[name] > RISK_ORDER[level]:
                    level = name
                reasons.append(f"`{token}` 含 `{matched[0]}` → {name}")
                break

    for flag in flags:
        flag = (flag or "").strip().lower()
        if flag in ESCALATING_FLAGS:
            if not level or RISK_ORDER["medium"] > RISK_ORDER[level]:
                level = "medium"
            reasons.append(f"旗标 `{flag}` 免确认 → 至少 medium")

    if not level:
        return DEFAULT_RISK, ["无证据：命令名与子命令都不在动词表里 → 兜底 medium"]

    return level, reasons



class ImportRefused(RuntimeError):
    """导入被拒绝（目标已存在且没有 ``--force``，或没有可导入的东西）。

    三个导入器（CLI 适配器 / workflow 目录 / skill）共用这一个类型，调用方不必
    按导入器的种类分别 catch。
    """


@dataclass
class EcosystemEntry:
    """One imported thing, described the same way regardless of its layer."""

    name: str
    kind: str = "tool"
    description: str = ""
    trust: str = "third-party"
    risk: str = DEFAULT_RISK
    requires: list[str] = field(default_factory=list)
    source_url: str = ""
    author: str = ""
    origin: str = ""
    enabled: bool = False
    tags: list[str] = field(default_factory=list)
    risk_reasons: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form (keys are stable — they land in manifests)."""
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "trust": self.trust,
            "risk": self.risk,
            "requires": list(self.requires),
            "source_url": self.source_url,
            "author": self.author,
            "origin": self.origin,
            "enabled": bool(self.enabled),
            "tags": list(self.tags),
            "risk_reasons": list(self.risk_reasons),
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EcosystemEntry":
        """Rebuild from :meth:`to_dict` output (unknown keys are kept in details)."""
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        kwargs = {key: value for key, value in (data or {}).items() if key in known}
        entry = cls(**kwargs)  # type: ignore[arg-type]
        return entry

    def summary(self) -> str:
        """One line for humans: ``gh [tool] trust=third-party risk=medium disabled``."""
        state = "enabled" if self.enabled else "disabled"
        return (
            f"{self.name} [{self.kind}] trust={self.trust} "
            f"risk={self.risk} {state}"
        )


def validate_entry(entry: EcosystemEntry) -> list[str]:
    """Return the list of problems with *entry* (empty means valid)."""
    problems: list[str] = []

    if not entry.name:
        problems.append("name is required")
    elif not _NAME_RE.match(entry.name):
        problems.append(
            f"name `{entry.name}` must be lowercase letters/digits/._- and start alphanumeric"
        )
    elif len(entry.name) > 64:
        problems.append("name is longer than 64 characters")

    if entry.kind not in ENTRY_KINDS:
        problems.append(f"unknown kind `{entry.kind}` (expected one of {', '.join(ENTRY_KINDS)})")

    if entry.trust not in TRUST_LEVELS:
        problems.append(
            f"unknown trust `{entry.trust}` (expected one of {', '.join(TRUST_LEVELS)})"
        )

    if entry.risk not in RISK_ORDER:
        problems.append(
            f"unknown risk `{entry.risk}` (expected one of {', '.join(RISK_LEVELS)})"
        )

    if entry.source_url and not entry.source_url.startswith(("http://", "https://")):
        problems.append(f"source_url `{entry.source_url}` must be http(s)")

    for index, item in enumerate(entry.requires):
        if not isinstance(item, str) or not item.strip():
            problems.append(f"requires[{index}] must be a non-empty string")

    return problems


def validate_entries(entries: Sequence[EcosystemEntry]) -> dict[str, list[str]]:
    """Validate many entries at once: ``{name_or_index: problems}``."""
    report: dict[str, list[str]] = {}
    for index, entry in enumerate(entries):
        problems = validate_entry(entry)
        if problems:
            report[entry.name or f"#{index}"] = problems
    return report


__all__ = [
    "CRITICAL_PATTERNS",
    "DEFAULT_RISK",
    "ENTRY_KINDS",
    "ESCALATING_FLAGS",
    "EcosystemEntry",
    "HIGH_WORDS",
    "ImportRefused",
    "LEVEL_LABELS",
    "LOW_WORDS",
    "MEDIUM_WORDS",
    "RISK_LEVELS",
    "RISK_ORDER",
    "TRUST_LEVELS",
    "assess_risk",
    "max_risk",
    "validate_entries",
    "validate_entry",
    "word_tokens",
]
