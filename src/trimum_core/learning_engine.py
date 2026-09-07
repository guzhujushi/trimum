"""LearningEngine — BehaviorMonitor 驱动的策略学习模式。

设计：
1. 观察每个 Agent 的操作历史（从 BehaviorMonitor 获取统计）
2. 识别高置信度安全操作模式 → 生成 allow ruleset
3. 支持"新人模式"（严格）和"老司机模式"（自动允许常见操作）
4. 学习结果持久化到 ~/.trimum/learning/
5. 动态 ruleset 注入到 PolicyEngine

验收：
- 学习模式可加载/保存
- 从 BehaviorMonitor 统计生成 ruleset
- 新人/老司机两种模式可切换
- ruleset 可注入到 PolicyEngine
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from .models import RiskLevel, Action
from .behavior_monitor import BehaviorMonitor

log = logging.getLogger("trimum_core.learning_engine")

# 学习数据的存储目录
_DEFAULT_LEARNING_DIR = os.path.expanduser("~/.trimum/learning")


@dataclass
class AgentProfile:
    """单个 Agent 的学习画像."""

    agent_id: str
    total_actions: int = 0
    deny_count: int = 0
    # 操作类型 → 调用次数
    action_counts: dict[str, int] = field(default_factory=dict)
    # 操作类型 → 最后调用时间
    last_seen: dict[str, float] = field(default_factory=dict)
    # 学习到的安全规则：command_pattern → allow
    learned_rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 模式：strict | normal | auto
    learning_mode: str = "normal"


@dataclass
class LearnedRule:
    """一条学习到的策略规则."""

    pattern: str
    action: str  # "auto" | "confirm"
    risk: str  # "low" | "medium"
    confidence: float  # 0~1
    source: str = "learned"
    reason: str = ""


class LearningEngine:
    """基于 BehaviorMonitor 的策略学习引擎.

    工作流程：
    1. 定时/事件触发 analyze()，从 BehaviorMonitor 获取最新统计
    2. 对每个 Agent 的操作模式进行分析
    3. 高置信度安全操作自动生成 allow ruleset
    4. ruleset 可注入到 PolicyEngine（动态添加规则）
    5. 学习结果持久化到 ~/.trimum/learning/

    学习模式：
    - strict: 新人/高安全环境，所有操作走完整 PolicyEngine 检查
    - normal: 默认，观察并学习，但不自动注入规则
    - auto: 老司机模式，高置信度操作自动放行
    """

    def __init__(
        self,
        monitor: BehaviorMonitor | None = None,
        learning_dir: str | None = None,
        mode: str = "normal",
        min_observations: int = 20,
        min_actions_for_auto: int = 50,
        confidence_threshold: float = 0.85,
    ) -> None:
        self._monitor = monitor or BehaviorMonitor()
        self._learning_dir = Path(learning_dir or _DEFAULT_LEARNING_DIR)
        self._min_observations = min_observations  # 学习前最少样本数
        self._min_actions_for_auto = min_actions_for_auto  # 进入 auto 模式的最小操作数
        self._confidence_threshold = confidence_threshold  # 信任阈值

        # Agent 画像
        self._profiles: dict[str, AgentProfile] = {}

        # 学习到的规则（pattern → LearnedRule）
        self._learned_rules: dict[str, LearnedRule] = {}

        # 确保目录存在
        self._learning_dir.mkdir(parents=True, exist_ok=True)

        # 尝试加载历史数据
        self._load()

        # mode 在 _load 后设置，确保 _load 不覆盖传入的 mode
        self._mode = mode

    # ------------------------------------------------------------------
    # 核心分析入口
    # ------------------------------------------------------------------

    def analyze(self) -> dict[str, Any]:
        """从 BehaviorMonitor 获取统计，分析并更新学习结果.

        Returns: 分析摘要 {agent_id: summary}
        """
        all_stats = self._monitor.get_all_stats()
        summary: dict[str, Any] = {}

        for agent_id, stats in all_stats.items():
            profile = self._get_or_create_profile(agent_id)
            old_mode = profile.learning_mode

            # 更新基础统计
            profile.total_actions = stats.get("total_actions", 0)
            action_counts = stats.get("action_type_counts", {})
            profile.action_counts = action_counts

            # 更新学习模式
            profile.learning_mode = self._determine_mode(profile)

            # 分析并生成规则
            new_rules = self._analyze_agent(agent_id, profile, action_counts)

            summary[agent_id] = {
                "total_actions": profile.total_actions,
                "deny_count": profile.deny_count,
                "mode_before": old_mode,
                "mode_after": profile.learning_mode,
                "new_rules": len(new_rules),
                "total_rules": len(profile.learned_rules),
                "action_types": len(action_counts),
            }

        # 持久化
        self._save()

        return summary

    # ------------------------------------------------------------------
    # Agent 级分析
    # ------------------------------------------------------------------

    def _analyze_agent(
        self,
        agent_id: str,
        profile: AgentProfile,
        action_counts: dict[str, int],
    ) -> list[LearnedRule]:
        """分析单个 Agent 的操作模式，生成新规则。"""
        new_rules: list[LearnedRule] = []

        # 只有当操作数>=最少样本且模式不是 strict 时才学习
        if profile.total_actions < self._min_observations:
            return new_rules

        if profile.learning_mode == "strict":
            return new_rules

        for action_type, count in action_counts.items():
            # 如果已经有了该操作类型的学习规则，跳过
            if action_type in profile.learned_rules:
                continue

            # 某个操作类型出现次数越多 → 越可能是常规安全操作
            # 高出现频率 + 未被拒绝过 → 高置信度
            confidence = self._calculate_confidence(action_type, count, profile)

            if confidence >= self._confidence_threshold and action_type not in profile.learned_rules:
                rule = LearnedRule(
                    pattern=action_type,
                    action="auto",
                    risk="low",
                    confidence=confidence,
                    source="learned",
                    reason=(
                        f"Observed {count}x '{action_type}' actions for agent "
                        f"'{agent_id}' — high confidence ({confidence:.2f})"
                    ),
                )
                self._learned_rules[f"{agent_id}:{action_type}"] = rule
                profile.learned_rules[action_type] = {
                    "action": "auto",
                    "risk": "low",
                    "confidence": confidence,
                    "learned_at": time.time(),
                }
                new_rules.append(rule)

        return new_rules

    def _calculate_confidence(
        self,
        action_type: str,
        count: int,
        profile: AgentProfile,
    ) -> float:
        """计算某个操作类型的置信度。

        因素：
        - 出现次数（越多越安全）
        - 拒绝率（越低越安全）
        - 操作类型本身的风险（内置评估）
        """
        # 基础：从出现次数
        if count < 5:
            return 0.0  # 样本太少，不学习
        count_factor = min(count / 50, 1.0)  # 50 次封顶

        # 拒绝率惩罚
        deny_rate = profile.deny_count / max(profile.total_actions, 1)
        deny_penalty = 1.0 - min(deny_rate * 3, 1.0)

        # 操作类型风险惩罚
        risk_penalty = self._action_risk_penalty(action_type)

        confidence = 0.5 * count_factor + 0.3 * deny_penalty - 0.2 * risk_penalty
        return max(0.0, min(confidence, 1.0))

    @staticmethod
    def _action_risk_penalty(action_type: str) -> float:
        """操作类型固有风险惩罚（0=安全, 1=高风险）。"""
        risky = {
            "file_delete": 0.6,
            "disk_write": 0.8,
            "network_raw": 0.7,
            "network_remote": 0.5,
            "container": 0.7,
            "network_request": 0.3,
            "file_write": 0.2,
        }
        return risky.get(action_type, 0.1)

    # ------------------------------------------------------------------
    # 学习模式判定
    # ------------------------------------------------------------------

    def _determine_mode(self, profile: AgentProfile) -> str:
        """根据 Agent 行为判定最优学习模式。"""
        # 如果显式设置过模式，保留
        if profile.learning_mode in ("strict", "auto") and profile.total_actions > 0:
            return profile.learning_mode

        # 操作数不足 → strict
        if profile.total_actions < self._min_observations:
            return "strict"

        # 操作数足够  + 低拒绝率 → auto（老司机模式）
        deny_rate = profile.deny_count / max(profile.total_actions, 1)
        if (
            profile.total_actions >= self._min_actions_for_auto
            and deny_rate < 0.1
        ):
            return "auto"

        return "normal"

    # ------------------------------------------------------------------
    # ruleset 生成
    # ------------------------------------------------------------------

    def generate_ruleset(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        """生成可注入 PolicyEngine 的规则列表.

        Args:
            agent_id: 如果指定，只生成该 Agent 的规则；否则生成全部。

        Returns:
            规则列表（符合 PolicyEngine YAML 规则格式）
        """
        rules: list[dict[str, Any]] = []

        for key, rule in self._learned_rules.items():
            key_agent = key.split(":")[0]
            if agent_id is not None and key_agent != agent_id:
                continue

            rules.append({
                "pattern": rule.pattern,
                "action": rule.action,
                "risk": rule.risk,
                "source": "learned",
                "_confidence": rule.confidence,
                "_reason": rule.reason,
            })

        return rules

    def inject_to_policy(
        self,
        policy_engine: Any,
        agent_id: str | None = None,
    ) -> int:
        """将学习到的 ruleset 注入到 PolicyEngine.

        Args:
            policy_engine: PolicyEngine 实例
            agent_id: 如果指定，只注入该 Agent 的规则

        Returns:
            注入的规则数量
        """
        # PolicyEngine 支持动态添加规则
        # 这里通过直接操作其内部规则列表实现
        rules = self.generate_ruleset(agent_id)
        if not rules:
            return 0

        count = 0
        for rule in rules:
            if hasattr(policy_engine, "_rules"):
                policy_engine._rules.append(rule)
                count += 1

        return count

    def get_mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        """设置全局学习模式.

        Args:
            mode: "strict" | "normal" | "auto"
        """
        if mode not in ("strict", "normal", "auto"):
            raise ValueError(f"Invalid mode: {mode}")
        self._mode = mode

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """保存学习数据到文件。"""
        filepath = self._learning_dir / "learning_data.json"

        data = {
            "mode": self._mode,
            "profiles": {
                aid: asdict(profile)
                for aid, profile in self._profiles.items()
            },
            "learned_rules": {
                key: {
                    "pattern": rule.pattern,
                    "action": rule.action,
                    "risk": rule.risk,
                    "confidence": rule.confidence,
                    "source": rule.source,
                    "reason": rule.reason,
                }
                for key, rule in self._learned_rules.items()
            },
            "updated_at": time.time(),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load(self) -> None:
        """从文件加载学习数据。"""
        filepath = self._learning_dir / "learning_data.json"
        if not filepath.exists():
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("learning_engine.load_failed: %s", str(e))
            return

        self._mode = data.get("mode", "normal")

        for aid, profile_data in data.get("profiles", {}).items():
            profile = AgentProfile(**profile_data)
            self._profiles[aid] = profile

        for key, rule_data in data.get("learned_rules", {}).items():
            rule = LearnedRule(**rule_data)
            self._learned_rules[key] = rule

        log.info(
            "learning_engine.loaded",
            profiles=len(self._profiles),
            rules=len(self._learned_rules),
        )

    def _get_or_create_profile(self, agent_id: str) -> AgentProfile:
        if agent_id not in self._profiles:
            self._profiles[agent_id] = AgentProfile(agent_id=agent_id)
        return self._profiles[agent_id]

    def record_deny(self, agent_id: str) -> None:
        """记录一次拒绝事件（由 ToolGateway 或 SecurityRule 调用）。"""
        profile = self._get_or_create_profile(agent_id)
        profile.deny_count += 1

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_profile(self, agent_id: str) -> AgentProfile | None:
        return self._profiles.get(agent_id)

    def get_learned_rules(self, agent_id: str | None = None) -> list[LearnedRule]:
        if agent_id is None:
            return list(self._learned_rules.values())
        return [
            rule for key, rule in self._learned_rules.items()
            if key.startswith(f"{agent_id}:")
        ]

    def get_summary(self) -> dict[str, Any]:
        return {
            "mode": self._mode,
            "profiles_count": len(self._profiles),
            "learned_rules_count": len(self._learned_rules),
            "min_observations": self._min_observations,
            "min_actions_for_auto": self._min_actions_for_auto,
            "confidence_threshold": self._confidence_threshold,
        }


    # ------------------------------------------------------------------
    # allow ruleset 管理（命令行接口用）
    # ------------------------------------------------------------------
    def auto_allow_rule(self, pattern: str) -> dict[str, Any]:
        return {
            "pattern": pattern,
            "action": "auto",
            "risk": "low",
            "source": "learned",
        }
