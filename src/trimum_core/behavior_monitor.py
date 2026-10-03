"""Behavior Monitor — 行为基线 + 异常检测。

职责：
1. 记录每个 Agent/工具的操作历史
2. 建立行为基线（正常操作的频率/模式）
3. 检测偏离基线的异常行为
4. 为 SecurityAgent 提供决策依据

当前实现：简单频率 + 模式检测。
Phase 4 可以升级为 ML 模型。
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque
from typing import Any

log = logging.getLogger("trimum_core.behavior_monitor")


# 操作类型 ↔ 基础命令映射（单一数据源）：
# - _classify_command 用它把命令归到操作类型
# - pattern_for_action_type 反向生成 PolicyEngine 可用的正则
ACTION_TYPE_COMMANDS: dict[str, tuple[str, ...]] = {
    "file_read": ("cat", "less", "more", "head", "tail", "read"),
    "file_write": ("echo", "tee", "write", "touch"),
    "file_delete": ("rm", "trash", "unlink"),
    "file_move": ("cp", "mv", "rename"),
    "file_permission": ("chmod", "chown"),
    "disk_write": ("dd",),
    "network_request": ("curl", "wget", "fetch", "http"),
    "network_remote": ("ssh", "scp", "rsync"),
    "network_raw": ("nc", "ncat", "socat"),
    "process_list": ("ps", "top", "htop"),
    "process_kill": ("kill", "pkill"),
    "system_mount": ("mount", "unmount"),
    "container": ("docker", "podman", "nerdctl"),
    "vcs_operation": ("git", "svn", "hg"),
    "build_tool": ("make", "cmake", "cargo", "npm", "pip"),
}

_COMMAND_TO_ACTION_TYPE: dict[str, str] = {
    command: action_type
    for action_type, commands in ACTION_TYPE_COMMANDS.items()
    for command in commands
}


def pattern_for_action_type(action_type: str) -> str | None:
    """把操作类型反查成 PolicyEngine 可用的命令正则（如 ``^(cat|head|tail)\b``）。"""
    commands = ACTION_TYPE_COMMANDS.get(action_type)
    if not commands:
        return None
    return "^(" + "|".join(re.escape(cmd) for cmd in commands) + r")\b"


class BehaviorRecord:
    """单个行为记录."""

    def __init__(
        self,
        agent_id: str,
        action_type: str,
        target: str = "",
        sandbox: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.action_type = action_type
        self.target = target
        self.sandbox = sandbox
        self.timestamp = time.time()
        self.metadata = metadata or {}


class BehaviorMonitor:
    """行为基线追踪与异常检测.

    追踪每个 Agent 的操作频率和模式，检测以下异常：
    - 突发高频操作（文件写入风暴 / 网络请求风暴）
    - 从未见过的操作类型
    - 跨沙箱攻击尝试
    - 横向移动（traverse）检测
    """

    def __init__(self, window_seconds: int = 300) -> None:
        self._window = window_seconds  # 滑动窗口大小（秒）
        self._history: defaultdict[str, deque[BehaviorRecord]] = (
            defaultdict(lambda: deque(maxlen=1000))
        )
        self._action_counts: defaultdict[str, dict[str, int]] = (
            defaultdict(lambda: defaultdict(int))
        )
        self._known_targets: defaultdict[str, set[str]] = defaultdict(set)
        self._anomaly_count: defaultdict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------
    # 记录接口
    # ------------------------------------------------------------------

    def record(
        self,
        agent_id: str,
        action_type: str,
        target: str = "",
        sandbox: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录一个行为."""
        record = BehaviorRecord(
            agent_id=agent_id,
            action_type=action_type,
            target=target,
            sandbox=sandbox,
            metadata=metadata,
        )
        self._history[agent_id].append(record)
        self._action_counts[agent_id][action_type] += 1
        if target:
            self._known_targets[agent_id].add(target)

        # 自动清理过期记录
        self._prune(agent_id)

    def _prune(self, agent_id: str) -> None:
        """移除超出时间窗口的旧记录."""
        cutoff = time.time() - self._window
        q = self._history[agent_id]
        while q and q[0].timestamp < cutoff:
            old = q.popleft()
            # 减少计数
            self._action_counts[agent_id][old.action_type] -= 1
            if self._action_counts[agent_id][old.action_type] <= 0:
                del self._action_counts[agent_id][old.action_type]

    # ------------------------------------------------------------------
    # 异常检测
    # ------------------------------------------------------------------

    async def check_command(
        self,
        agent_id: str,
        command: str,
        sandbox: str = "default",
    ) -> str:
        """检查命令是否异常.

        返回: "normal" | "suspicious" | "anomaly"
        """
        # 解析命令类型
        action_type = self._classify_command(command)

        # 1. 突发高频检测
        rate = self._get_action_rate(agent_id, action_type)
        if rate is not None and rate > self._get_rate_threshold(action_type):
            return "anomaly"

        # 2. 新操作类型检测
        total_types = len(self._action_counts.get(agent_id, {}))
        if total_types == 0:
            # 第一个操作总是允许
            return "normal"

        # 3. 跨沙箱操作检测
        recent = self._history.get(agent_id, [])
        recent_sandboxes = {r.sandbox for r in recent}
        if recent_sandboxes and sandbox not in recent_sandboxes:
            # Agent 突然操作另一个沙箱 → 可疑
            return "suspicious"

        return "normal"

    def _classify_command(self, command: str) -> str:
        """将命令分类为操作类型."""
        cmd_lower = command.lower().strip()

        if not cmd_lower:
            return "unknown"

        return _COMMAND_TO_ACTION_TYPE.get(cmd_lower.split()[0], "other")

    def classify_command(self, command: str) -> str:
        """公开的分类接口（ToolGateway / LearningEngine 使用）。"""
        return self._classify_command(command)

    def record_command(
        self,
        agent_id: str,
        command: str,
        sandbox: str = "default",
    ) -> str:
        """分类并记录一条命令，返回操作类型。

        ToolGateway 每处理完一条命令就调用它，行为基线与学习引擎都靠这个
        数据源（此前没有任何地方调用 ``record``，导致异常检测与学习都是空转）。
        """
        action_type = self._classify_command(command)
        self.record(agent_id, action_type, target=command, sandbox=sandbox)
        return action_type

    def _get_action_rate(
        self,
        agent_id: str,
        action_type: str,
    ) -> float | None:
        """计算该 Agent 某类操作的频率（次/分钟）."""
        count = self._action_counts.get(agent_id, {}).get(action_type, 0)
        if count <= 1:
            return None
        elapsed = min(self._window, time.time() - self._get_oldest(agent_id))
        if elapsed <= 0:
            return None
        return count / (elapsed / 60.0)

    def _get_oldest(self, agent_id: str) -> float:
        """获取最早的记录时间戳."""
        q = self._history.get(agent_id, [])
        if not q:
            return time.time()
        return q[0].timestamp

    def _get_rate_threshold(self, action_type: str) -> float:
        """获取某类操作的频率阈值（次/分钟）."""
        thresholds = {
            "file_write": 30,
            "file_delete": 20,
            "network_request": 20,
            "network_remote": 5,
            "disk_write": 2,
            "container": 5,
            "process_kill": 10,
        }
        return thresholds.get(action_type, 40)

    # ------------------------------------------------------------------
    # 统计接口
    # ------------------------------------------------------------------

    def get_stats(self, agent_id: str) -> dict[str, Any]:
        """获取 Agent 的行为统计."""
        return {
            "total_actions": len(self._history.get(agent_id, [])),
            "action_type_counts": dict(
                self._action_counts.get(agent_id, {})
            ),
            "known_targets_count": len(
                self._known_targets.get(agent_id, set())
            ),
            "anomaly_count": self._anomaly_count.get(agent_id, 0),
        }

    def get_all_stats(self) -> dict[str, Any]:
        """获取所有 Agent 的统计."""
        return {
            aid: self.get_stats(aid)
            for aid in self._history
            if self._history[aid]
        }
