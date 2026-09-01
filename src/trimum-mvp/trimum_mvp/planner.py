"""命令规划器：把自然语言输入转换为结构化命令计划。

流程：
1. 调用 LLM（OpenAI 兼容 API）生成 JSON：{"plan": [...], "commands": [...], "risk": "...", "explanation": "..."}
2. JSON 解析失败则重试一次
3. 仍失败则回退到基于关键词的正则意图匹配（离线可用）

风险级别：low | medium | high | critical
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .llm import LLMClient
from .output import info

VALID_RISKS = {"low", "medium", "high", "critical"}

SYSTEM_PROMPT = """你是一名 Arch Linux 命令助手，负责把用户的自然语言需求转换为可安全执行的 shell 命令计划。

安全约束：
1. 只生成与用户需求直接相关的命令，不要添加多余操作。
2. 涉及删除、修改、安装、系统配置的命令必须给出准确的风险级别。
3. 若需求明显是破坏性操作（如格式化磁盘、删除根目录、零写磁盘），risk 必须为 critical。
4. 若用户要求解释代码/日志（不执行命令），commands 必须为空数组，解释写入 explanation。

输出必须是合法 JSON，不要包含 markdown 代码块或任何多余文字，格式如下：
{
  "plan": ["步骤 1 说明", "步骤 2 说明"],
  "commands": ["命令 1", "命令 2"],
  "risk": "low|medium|high|critical",
  "explanation": "给用户看的简短说明"
}"""

# 兜底意图匹配规则：(正则, 命令列表, 风险, 说明, 步骤列表)
# 注意：顺序敏感——先匹配具体主题（磁盘/内存/进程/用户/git/日志），
#       再匹配通用只读意图（查看/浏览），最后才是破坏性清理规则（H-2）：
#       确保「看看 tmp 目录」这类只读意图不会被误判为 rm -rf /tmp/*。
_FALLBACK_RULES: list[tuple[re.Pattern[str], list[str], str, str, list[str]]] = [
    (
        re.compile(r"解释|说明|explain|what is|为什么|报错|错误|error", re.IGNORECASE),
        [],
        "low",
        "仅解释输入内容，不执行命令。",
        ["分析输入内容并给出解释"],
    ),
    (
        re.compile(r"格式化|format|mkfs", re.IGNORECASE),
        ["mkfs.ext4 /dev/sda"],
        "critical",
        "格式化磁盘属于破坏性操作，将被策略引擎拦截。",
        ["格式化磁盘分区"],
    ),
    (
        re.compile(r"磁盘|空间|df|disk|storage", re.IGNORECASE),
        ["df -h"],
        "low",
        "查看磁盘使用情况。",
        ["查看磁盘空间使用情况"],
    ),
    (
        re.compile(r"内存|free|memory|ram", re.IGNORECASE),
        ["free -h"],
        "low",
        "查看内存使用情况。",
        ["查看内存使用情况"],
    ),
    (
        re.compile(r"进程|ps|process", re.IGNORECASE),
        ["ps aux"],
        "low",
        "查看进程列表。",
        ["列出当前进程"],
    ),
    (
        re.compile(r"当前用户|whoami|current user", re.IGNORECASE),
        ["whoami"],
        "low",
        "查看当前登录用户。",
        ["查询当前登录用户"],
    ),
    (
        re.compile(r"git\s*(status|仓库状态)|仓库状态", re.IGNORECASE),
        ["git status"],
        "low",
        "查看 Git 仓库状态。",
        ["查看 Git 仓库状态"],
    ),
    # 日志：查看（只读）先于清理（破坏性）
    (
        re.compile(
            r"(查看|看看|浏览|显示).*(日志|log|journal)|(日志|log|journal).*(查看|看看|浏览|显示)",
            re.IGNORECASE,
        ),
        ["journalctl -n 50"],
        "low",
        "查看最近系统日志（只读）。",
        ["查看最近系统日志"],
    ),
    (
        re.compile(
            r"(清理|删除|清除|vacuum).*(日志|log|journal)|(日志|log|journal).*(清理|删除|清除|vacuum)",
            re.IGNORECASE,
        ),
        ["journalctl --vacuum-time=7d"],
        "high",
        "清理 7 天前的系统日志（影响审计追溯）。",
        ["清理过期系统日志"],
    ),
    # 通用只读意图（放在破坏性规则之前，H-2）
    (
        re.compile(r"查看|看看|浏览|显示|list|\bls\b", re.IGNORECASE),
        ["ls -la"],
        "low",
        "查看目录/文件列表（只读操作）。",
        ["列出目录内容"],
    ),
    (
        re.compile(r"缓存|\bcache\b|\btmp\b|临时", re.IGNORECASE),
        ["rm -rf /tmp/*"],
        "medium",
        "清理 /tmp 下的临时缓存文件。",
        ["清理 /tmp 缓存文件"],
    ),
    (
        re.compile(r"更新|升级|update|upgrade", re.IGNORECASE),
        ["pacman -Syu"],
        "medium",
        "更新系统软件包。",
        ["同步并更新系统软件包"],
    ),
]


@dataclass
class CommandPlan:
    """一次自然语言请求的结构化命令计划。"""

    plan: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    risk: str = "medium"
    explanation: str = ""

    def __post_init__(self) -> None:
        if self.risk not in VALID_RISKS:
            self.risk = "medium"

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 可序列化字典。"""
        return {
            "plan": self.plan,
            "commands": self.commands,
            "risk": self.risk,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommandPlan | None":
        """从 LLM 返回的字典构造计划；字段非法时返回 None。"""
        try:
            plan_value = data.get("plan") or []
            commands_value = data.get("commands") or []
            # M-3：字符串字段（如 "plan": "查看磁盘"）不应被迭代成字符列表
            if not isinstance(plan_value, list):
                plan_value = []
            if not isinstance(commands_value, list):
                commands_value = []
            plan = [str(item) for item in plan_value]
            commands = [str(item) for item in commands_value]
            risk = str(data.get("risk", "medium")).lower()
            explanation = str(data.get("explanation", ""))
        except (TypeError, ValueError):
            return None
        if risk not in VALID_RISKS:
            return None
        return cls(plan=plan, commands=commands, risk=risk, explanation=explanation)


class Planner:
    """命令规划器：LLM 生成计划，失败时回退到关键词匹配。"""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def plan(self, user_input: str, pipe_input: str | None = None) -> CommandPlan:
        """生成命令计划。

        - user_input: 用户的自然语言需求
        - pipe_input: 管道输入（代码/日志等上下文，如 cat log | trm "解释报错"）
        """
        user_input = (user_input or "").strip()
        if not user_input:
            return CommandPlan(explanation="输入为空，请描述你想做什么（Input is empty）")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_message(user_input, pipe_input)},
        ]
        for _attempt in range(2):  # 最多重试 1 次
            try:
                text = self.llm.chat(messages)
            except Exception:
                break  # LLM 调用失败 -> 回退
            plan = self._parse_json_plan(text)
            if plan is not None:
                return plan

        info("LLM 未返回有效计划，使用离线意图匹配（Fallback to offline matching）")
        return self._fallback_plan(user_input)

    def _build_user_message(self, user_input: str, pipe_input: str | None) -> str:
        """构造用户消息；管道内容作为附加上下文。"""
        text = f"用户需求：{user_input}\n请输出 JSON 命令计划。"
        if pipe_input:
            text += (
                "\n\n附加上下文（管道输入，若仅需解释则 commands 为空数组）：\n"
                f"```\n{pipe_input}\n```"
            )
        return text

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """从 LLM 回复中提取 JSON 对象（容忍 ```json 代码块）。"""
        if not text:
            return None
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", stripped, count=1)
        try:
            data = json.loads(stripped)
            return data if isinstance(data, dict) else None
        except ValueError:
            pass
        # 尝试提取第一个 {...} 片段
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else None
            except ValueError:
                return None
        return None

    @classmethod
    def _parse_json_plan(cls, text: str) -> CommandPlan | None:
        """解析并校验 LLM 返回的 JSON 计划。"""
        data = cls._extract_json(text)
        if data is None:
            return None
        return CommandPlan.from_dict(data)

    @staticmethod
    def _fallback_plan(user_input: str) -> CommandPlan:
        """基于关键词正则的离线意图匹配。"""
        for pattern, commands, risk, explanation, steps in _FALLBACK_RULES:
            if pattern.search(user_input):
                return CommandPlan(
                    plan=steps,
                    commands=commands,
                    risk=risk,
                    explanation=explanation,
                )
        return CommandPlan(
            plan=["未能识别意图，请给出更明确的需求"],
            commands=[],
            risk="medium",
            explanation="无法将输入解析为命令计划，请用更明确的语言描述（Cannot parse intent）",
        )