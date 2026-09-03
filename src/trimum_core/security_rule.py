"""Security Rule — 弹性沙箱的决策规则引擎。

职责：
1. **跨 Agent/工具访问决策** — 任何跨边界的请求，Security Rule 决定放行/弹窗/拒绝
2. **行为基线异常检测** — 调用 BehaviorMonitor 判断当前操作是否偏离常态
3. **资源溢出防护** — Agent 之间互相屏蔽（哪怕在 Docker 内）
4. **Landlock 接口** — 文件系统权限（Phase 4 存根）
5. **弹窗确认接口** — 高风险操作的确认入口

设计原则：
- 不做任何规则匹配（那归 PolicyEngine）
- 只做「这个操作该不该允许？」的决策
- 决策结果 = allow / confirm / deny
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .models import RiskLevel, Action
from .policy_engine import PolicyEngine

log = logging.getLogger("trimum_core.security_agent")


class DecisionResult:
    """Security Agent 的决策结果."""

    def __init__(
        self,
        action: str,
        reason: str,
        risk_level: str = "low",
        requires_confirmation: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.action = action  # "allow" | "deny" | "confirm"
        self.reason = reason
        self.risk_level = risk_level
        self.requires_confirmation = requires_confirmation
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "metadata": self.metadata,
        }


class SecurityRule:
    """弹性沙箱的决策中心.

    与其他组件的关系:
    - PolicyEngine: 规则匹配 → SecurityAgent 决定放行/弹窗/拒绝
    - BehaviorMonitor: 行为基线异常检测 → SecurityAgent 纳入决策
    - ContextManager: 查询上下文权限
    - Landlock: 文件系统权限（Phase 4）
    """

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        behavior_monitor: Optional["BehaviorMonitor"] = None,
        enable_blocking: bool = True,
        sandbox_id: str = "default",
    ) -> None:
        self._policy = policy_engine or PolicyEngine()
        self._monitor = behavior_monitor
        self._blocking = enable_blocking
        self._sandbox_id = sandbox_id

        # 跨 Agent 白名单（同一工作流内的 Agent 默认允许通信）
        self._workflow_peers: dict[str, set[str]] = {}

        # 资源阈值（超出触发限制）
        self._resource_limits: dict[str, float] = {
            "max_file_writes_per_minute": 60,
            "max_network_requests_per_minute": 30,
            "max_cpu_percent": 80.0,
            "max_memory_mb": 512,
        }

    # ------------------------------------------------------------------
    # 核心决策接口
    # ------------------------------------------------------------------

    async def can_access(
        self,
        source_id: str,
        target_id: str,
        access_type: str = "read",
        source_sandbox: str = "default",
        target_sandbox: str = "default",
    ) -> DecisionResult:
        """判断 source 能否访问 target.

        跨沙箱访问规则（开发者工具互访）:
        1. 同一沙箱内 → 默认允许
        2. 不同沙箱 → 需要确认（除非在工作流白名单）
        3. 沙箱外访问沙箱内 → 拒绝
        4. 跨开发者工具 → 需要 Security Agent 同意（即使都在 Docker 内）
        """
        # 同一沙箱 + 同一工具 → 允许
        if source_sandbox == target_sandbox and source_id == target_id:
            return DecisionResult("allow", "same sandbox and agent")

        # 沙箱外访问沙箱内 → 拒绝（防逃逸）
        if source_sandbox != target_sandbox and source_sandbox == "host":
            return DecisionResult(
                "deny",
                "host cannot access sandbox",
                risk_level="high",
            )

        # 不同沙箱 → 跨沙箱访问需要确认
        if source_sandbox != target_sandbox:
            return DecisionResult(
                "confirm",
                f"cross-sandbox access: {source_id} → {target_id}",
                risk_level="high",
                requires_confirmation=True,
                metadata={
                    "source_id": source_id,
                    "target_id": target_id,
                    "source_sandbox": source_sandbox,
                    "target_sandbox": target_sandbox,
                    "access_type": access_type,
                },
            )

        # 同一沙箱但不同工具（开发者工具互访）→ 需要确认
        if source_sandbox == target_sandbox and source_id != target_id:
            # 工作流白名单：同一工作流的 Agent 自动放行
            if self._is_workflow_peer(source_id, target_id):
                return DecisionResult("allow", "workflow peer")

            return DecisionResult(
                "confirm",
                f"cross-tool access: {source_id} → {target_id}",
                risk_level="medium",
                requires_confirmation=True,
                metadata={
                    "source_id": source_id,
                    "target_id": target_id,
                    "sandbox": source_sandbox,
                    "access_type": access_type,
                },
            )

        return DecisionResult("allow", "default allow")

    async def can_execute(
        self,
        agent_id: str,
        command: str,
        sandbox: str = "default",
        resource_ctx: dict[str, Any] | None = None,
    ) -> DecisionResult:
        """判断 Agent 能否执行某个命令.

        Pipeline:
        1. PolicyEngine 规则匹配（现有规则）
        2. BehaviorMonitor 行为异常检测（如果有）
        3. 资源阈值检查
        4. 合并决策
        """
        resource_ctx = resource_ctx or {}

        # Step 1: PolicyEngine 规则匹配
        risk, action, reason = self._policy.evaluate(command)

        # Step 2: BehaviorMonitor 异常检测
        monitor_verdict: str | None = None
        if self._monitor:
            monitor_verdict = await self._monitor.check_command(
                agent_id, command, sandbox=sandbox
            )

        # Step 3: 资源阈值检查
        resource_ok = self._check_resource_limits(agent_id, resource_ctx)

        # Step 4: 合并决策
        if risk == RiskLevel.CRITICAL:
            return DecisionResult(
                "deny",
                f"critical risk: {reason}",
                risk_level="critical",
            )

        if not resource_ok:
            return DecisionResult(
                "deny",
                "resource limit exceeded",
                risk_level="high",
                metadata={"resource_ctx": resource_ctx},
            )

        if monitor_verdict == "anomaly":
            return DecisionResult(
                "confirm",
                f"behavior anomaly detected for command",
                risk_level="high",
                requires_confirmation=True,
                metadata={"monitor_verdict": monitor_verdict},
            )

        if action == Action.DENY:
            return DecisionResult("deny", reason, risk_level=risk.value)

        if action == Action.CONFIRM:
            return DecisionResult(
                "confirm",
                reason,
                risk_level=risk.value,
                requires_confirmation=True,
            )

        return DecisionResult("allow", reason, risk_level=risk.value)

    # ── TARL 接入 ────────────────────────────────────────

    async def can_execute_tarl(
        self,
        agent_id: str,
        tarl_line: str,
        sandbox: str = "default",
    ) -> DecisionResult:
        """TARL-aware execution check: parse ``cmd:`` prefix from TARL line
        and run policy matching on the extracted command.

        If the TARL line contains a ``cmd:`` key, the value is extracted
        and checked via ``can_execute()``.  Additional TARL keys
        (``sandbox:``, ``resource:``) can override defaults.

        Args:
            agent_id: Source agent identifier.
            tarl_line: TARL line, e.g. ``cmd:restart_nginx sandbox:production``.
            sandbox: Default sandbox if TARL doesn't specify one.

        Returns:
            DecisionResult from the standard ``can_execute()`` chain.
        """
        from .tarl_parser import extract_prefix, parse_line

        # Parse TARL to extract command and overrides
        kvs = parse_line(tarl_line)
        cmd_values = extract_prefix(tarl_line, "cmd")
        command = cmd_values[0] if cmd_values else tarl_line

        # TARL can override sandbox via sandbox: key
        effective_sandbox = kvs.get("sandbox", sandbox)

        # Build resource context from TARL resource: key
        resource_ctx: dict[str, Any] = {}
        resource_str = kvs.get("resource", "")
        if resource_str:
            from .tarl_parser import parse_line as _pl
            resource_ctx = _pl(resource_str)
            # Convert numeric strings
            for k in ("cpu_percent", "memory_mb"):
                if k in resource_ctx:
                    try:
                        resource_ctx[k] = float(resource_ctx[k])
                    except ValueError:
                        pass

        return await self.can_execute(
            agent_id=agent_id,
            command=command,
            sandbox=effective_sandbox,
            resource_ctx=resource_ctx,
        )

    # ------------------------------------------------------------------
    # 弹窗确认接口
    # ------------------------------------------------------------------

    async def confirm(
        self,
        decision: DecisionResult,
        user_response: Optional[bool] = None,
    ) -> DecisionResult:
        """处理弹窗确认结果.

        user_response:
            True = 用户允许
            False = 用户拒绝
            None = 等待用户确认（挂起）
        """
        if not decision.requires_confirmation:
            return decision

        if user_response is True:
            return DecisionResult(
                "allow",
                f"user confirmed: {decision.reason}",
                risk_level=decision.risk_level,
            )

        if user_response is False:
            return DecisionResult(
                "deny",
                f"user denied: {decision.reason}",
                risk_level=decision.risk_level,
            )

        # user_response is None → 挂起等待确认
        return DecisionResult(
            "pending",
            f"awaiting user confirmation: {decision.reason}",
            risk_level=decision.risk_level,
            requires_confirmation=True,
            metadata=decision.metadata,
        )

    # ------------------------------------------------------------------
    # Landlock 接口（Phase 4 存根）
    # ------------------------------------------------------------------

    async def check_landlock_path(
        self,
        agent_id: str,
        path: str,
        access_type: str = "read",
    ) -> DecisionResult:
        """检查文件系统路径访问权限.

        Phase 4 实现真正的 Landlock LSM 集成。
        当前返回 allow + 标记为需要 future 实现。
        """
        return DecisionResult(
            "allow",
            f"landlock stub: {agent_id} {access_type} {path}",
            risk_level="low",
            metadata={"landlock_version": 0, "enforced": False},
        )

    # ------------------------------------------------------------------
    # 工作流白名单管理
    # ------------------------------------------------------------------

    def register_workflow_peers(self, agent_ids: list[str]) -> None:
        """注册同一工作流的 Agent 互信关系."""
        agent_set = set(agent_ids)
        for aid in agent_ids:
            if aid not in self._workflow_peers:
                self._workflow_peers[aid] = set()
            self._workflow_peers[aid].update(agent_set - {aid})

    def _is_workflow_peer(self, source: str, target: str) -> bool:
        """检查两个 Agent 是否在同一工作流白名单内."""
        return (
            source in self._workflow_peers
            and target in self._workflow_peers[source]
        )

    # ------------------------------------------------------------------
    # 资源限制
    # ------------------------------------------------------------------

    def _check_resource_limits(
        self,
        agent_id: str,
        ctx: dict[str, Any],
    ) -> bool:
        """检查 Agent 是否超出资源阈值."""
        _ = agent_id  # unused placeholder

        if ctx.get("cpu_percent", 0) > self._resource_limits["max_cpu_percent"]:
            return False
        if ctx.get("memory_mb", 0) > self._resource_limits["max_memory_mb"]:
            return False
        return True

    def set_resource_limit(self, name: str, value: float) -> None:
        """动态调整资源阈值."""
        if name in self._resource_limits:
            self._resource_limits[name] = value

    def get_resource_limits(self) -> dict[str, float]:
        """获取当前资源阈值."""
        return dict(self._resource_limits)

    # ------------------------------------------------------------------
    # 防溢出建议检测
    # ------------------------------------------------------------------

    def get_escape_risks(self, sandbox_config: dict[str, Any]) -> list[str]:
        """检测当前沙箱配置的溢出风险.

        返回风险描述列表。
        """
        risks: list[str] = []

        # Docker socket 逃逸
        if sandbox_config.get("docker_socket_mounted", False):
            risks.append("Docker socket mounted — container escape possible")

        # 特权模式
        if sandbox_config.get("privileged", False):
            risks.append("Privileged mode — full host access")

        # 宿主机 PID namespace
        if sandbox_config.get("host_pid", False):
            risks.append("Host PID namespace — can see all host processes")

        # 宿主机网络
        if sandbox_config.get("host_network", False):
            risks.append("Host network — no network isolation")

        # 卷挂载过大
        mounted_paths = sandbox_config.get("mounted_paths", [])
        for mp in mounted_paths:
            if any(system in mp for system in ["/etc", "/usr", "/boot", "/sys"]):
                risks.append(f"Sensitive system path mounted: {mp}")

        # 跨容器网络连通
        if sandbox_config.get("cross_container_network", False):
            risks.append(
                "Cross-container network enabled — agents can reach each other"
            )

        if not risks:
            risks.append("No escape risks detected (basic sandbox config)")

        return risks
