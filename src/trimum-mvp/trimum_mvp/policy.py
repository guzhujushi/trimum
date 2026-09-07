r"""YAML 策略引擎（shellfirm 风格）。

加载 policy.yaml 中的规则，对每条命令做正则匹配，
返回风险级别与动作：low/medium/high/critical + auto/confirm/deny。
匹配规则：按文件顺序第一条命中即生效（critical 规则应放在前面）。

安全设计（C-1）：
- 匹配前先做 shell 规范化（normalize_command）：
  剥离反斜杠转义、剥离引号、按 ; && || | 换行 拆分为子命令段；
  逐段匹配，任一子命令被 deny 则整条命令 deny。
  避免 ``rm\ -rf\ /`` 之类转义绕过（docstring 中反斜杠已转义书写）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# 合法取值
VALID_RISKS = {"low", "medium", "high", "critical"}
VALID_ACTIONS = {"auto", "confirm", "deny"}

# 风险数值（用于取多命令中的最高风险）
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# 链式分隔符（引号外生效）：; && || | 换行
_CHAIN_SEPARATORS = ("&&", "||")


def normalize_command(cmd: str) -> list[str]:
    r"""Shell 规范化：去转义、去引号、拆链，返回子命令列表。

    - 反斜杠转义：``rm\ -rf\ /`` -> ``rm -rf /``（保留被转义字符本身）
    - 单/双引号：剥离引号但保留内容（``ls "/tmp/a b"`` -> ``ls /tmp/a b``）
    - 链式拆分：按 ``;`` ``&&`` ``||`` 换行 拆成独立子命令；
      管道符 ``|`` 仅在括号/花括号最外层拆分，避免拆散
      ``:(){ :|:& }`` 之类的函数体（裸 ``&`` 后台符保留在子命令内）。
    """
    if not cmd:
        return []
    text = cmd.strip()
    pieces: list[str] = []
    current: list[str] = []
    quote: str | None = None
    depth = 0  # 括号/花括号嵌套深度（用于管道拆分判断）
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # 反斜杠转义：剥离转义符，保留被转义字符
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "\n":  # 续行符：直接跳过
                i += 2
                continue
            current.append(nxt)
            i += 2
            continue
        # 引号：剥离引号符本身，内容保留
        if ch in ("'", '"'):
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
            i += 1
            continue
        # 括号深度（引号外）
        if quote is None and ch in "([{":
            depth += 1
            current.append(ch)
            i += 1
            continue
        if quote is None and ch in ")]}":
            depth = max(0, depth - 1)
            current.append(ch)
            i += 1
            continue
        # 链式分隔符（引号外）
        if quote is None and ch in (";", "|", "&", "\n"):
            two = text[i : i + 2]
            if ch == "&" and two != "&&":
                # 裸 &（后台运行）不是分隔符，保留
                current.append(ch)
                i += 1
                continue
            if ch == "|" and depth > 0:
                # 函数体内的管道（如 :|:）不拆分，保留原签名
                current.append(ch)
                i += 1
                continue
            if two in _CHAIN_SEPARATORS:
                i += 2
            else:
                i += 1
            piece = "".join(current).strip()
            if piece:
                pieces.append(piece)
            current = []
            continue
        current.append(ch)
        i += 1
    piece = "".join(current).strip()
    if piece:
        pieces.append(piece)
    return pieces


@dataclass
class PolicyRule:
    """单条策略规则。"""

    pattern: str
    risk: str
    action: str
    description: str = ""
    message: str = ""
    regex: re.Pattern[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.risk not in VALID_RISKS:
            raise ValueError(f"非法的风险级别: {self.risk!r}")
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"非法的动作: {self.action!r}")
        try:
            self.regex = re.compile(self.pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"规则正则无效 {self.pattern!r}: {exc}") from exc

    def matches(self, command: str) -> bool:
        """判断命令是否命中该规则。"""
        return self.regex.search(command) is not None


@dataclass
class PolicyDecision:
    """策略评估结果。"""

    risk: str
    action: str
    matched_rule: PolicyRule | None = None

    @property
    def denied(self) -> bool:
        return self.action == "deny"

    @property
    def confirmed(self) -> bool:
        return self.action == "confirm"


class PolicyEngine:
    """策略引擎：加载规则并对命令做风险分级。"""

    def __init__(
        self,
        policy_file: str | Path = "policy.yaml",
        default_action: str = "confirm",
        default_risk: str = "medium",
    ) -> None:
        self.policy_file = Path(policy_file)
        self.default_action = default_action
        self.default_risk = default_risk
        self.rules: list[PolicyRule] = []
        self._load()

    def _load(self) -> None:
        """从 YAML 文件加载规则（逐条校验，错误时定位到规则序号）。"""
        if not self.policy_file.exists():
            raise FileNotFoundError(f"策略文件不存在: {self.policy_file}")
        data = yaml.safe_load(self.policy_file.read_text(encoding="utf-8")) or {}
        self.default_action = data.get("default_action", self.default_action)
        self.default_risk = data.get("default_risk", self.default_risk)
        if self.default_action not in VALID_ACTIONS:
            raise ValueError(f"非法的默认动作: {self.default_action!r}")
        if self.default_risk not in VALID_RISKS:
            raise ValueError(f"非法的默认风险: {self.default_risk!r}")

        raw_rules = data.get("rules", [])
        if not isinstance(raw_rules, list):
            raise ValueError("rules 字段必须是列表")
        self.rules = []
        for index, raw_rule in enumerate(raw_rules, start=1):
            if not isinstance(raw_rule, dict):
                raise ValueError(f"规则第 {index} 条（Rule #{index}）必须是字典")
            try:
                self.rules.append(PolicyRule(**raw_rule))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"规则第 {index} 条无效（Rule #{index}）: {exc}") from exc

    def _evaluate_normalized(self, command: str) -> PolicyDecision:
        """对单段（已规范化）命令逐条匹配规则。"""
        for rule in self.rules:
            if rule.matches(command):
                return PolicyDecision(risk=rule.risk, action=rule.action, matched_rule=rule)
        return PolicyDecision(risk=self.default_risk, action=self.default_action)

    def evaluate(self, command: str) -> PolicyDecision:
        """评估单条命令，返回风险级别与动作。

        先做 shell 规范化（去转义/引号、拆链），再逐段匹配：
        任一子命令 deny -> 整条 deny；否则取最高风险段。
        """
        command = (command or "").strip()
        if not command:
            return PolicyDecision(risk=self.default_risk, action=self.default_action)
        sub_commands = normalize_command(command)
        if not sub_commands:
            return PolicyDecision(risk=self.default_risk, action=self.default_action)
        decisions = [self._evaluate_normalized(sub) for sub in sub_commands]
        denied = [d for d in decisions if d.denied]
        if denied:
            return PolicyDecision(
                risk=denied[0].risk,
                action="deny",
                matched_rule=denied[0].matched_rule,
            )
        top = max(decisions, key=lambda d: _RISK_ORDER.get(d.risk, 1))
        return PolicyDecision(risk=top.risk, action=top.action, matched_rule=top.matched_rule)

    def evaluate_many(self, commands: list[str]) -> PolicyDecision:
        """评估多条命令，返回整体风险（取最高风险；任一 deny 则整体 deny）。

        每条命令内部同样先规范化再逐段匹配（见 evaluate）。
        """
        if not commands:
            return PolicyDecision(risk=self.default_risk, action=self.default_action)
        decisions = [self.evaluate(command) for command in commands]
        denied = [d for d in decisions if d.denied]
        if denied:
            return PolicyDecision(
                risk=denied[0].risk,
                action="deny",
                matched_rule=denied[0].matched_rule,
            )
        top = max(decisions, key=lambda d: _RISK_ORDER.get(d.risk, 1))
        return PolicyDecision(risk=top.risk, action=top.action, matched_rule=top.matched_rule)

    def describe(self, command: str) -> str:
        """返回命令命中的规则描述（用于展示/审计）。"""
        decision = self.evaluate(command)
        rule = decision.matched_rule
        if rule is None:
            return "未匹配规则（默认策略）"
        return rule.description or rule.pattern