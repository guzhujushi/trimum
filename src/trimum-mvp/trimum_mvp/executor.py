"""命令执行器：风险分级 + 确认流程 + subprocess 安全执行。

风险处理：
- low        -> 自动执行
- medium     -> 用户确认（y/N）
- high       -> 用户确认 + 警告 + 审计日志
- critical   -> 直接拒绝（deny）

3 步确认 UI：
1. 展示计划（I'll run: ...）
2. 展示风险级别（带颜色）
3. 询问 Continue? [y/N]
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .output import (
    ERR_SYMBOL,
    OK_SYMBOL,
    WARN_SYMBOL,
    ask_confirm,
    error,
    info,
    show_commands,
    show_output,
    show_plan,
    show_rejection,
    show_risk,
    success,
    warning,
)
from .planner import CommandPlan
from .policy import PolicyDecision, PolicyEngine, normalize_command

# Linux/POSIX 专属命令（Windows 开发期提示平台差异，L-9）
_POSIX_ONLY_COMMANDS = {
    "df", "du", "free", "ps", "top", "vmstat", "iostat",
    "systemctl", "journalctl", "pacman", "yay", "paru",
    "mkfs", "dd", "wipefs", "fdisk", "parted", "gdisk", "sfdisk",
    "ls", "rm", "mv", "cp", "chmod", "chown", "cat", "head", "tail",
    "tree", "pwd", "sed", "grep", "awk",
}

# 命令前缀（不改变语义，跳过后再取第一个真正命令）
_COMMAND_PREFIXES = {"sudo", "env", "nohup", "time", "bash", "sh", "-c", "zsh", "fish"}


def _first_token(command: str) -> str:
    """取命令的第一个有效 token（跳过 sudo/env/bash -c 等前缀）。"""
    tokens = command.split()
    for token in tokens:
        if token in _COMMAND_PREFIXES:
            continue
        return token
    return tokens[0] if tokens else ""


@dataclass
class ExecutionResult:
    """单条命令的执行结果。"""

    command: str
    risk: str
    action: str
    executed: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    message: str = ""


class Executor:
    """命令执行器：策略评估 -> 确认 -> 执行。"""

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        timeout: float = 60.0,
        confirm_callback: Callable[[str], bool] | None = None,
        audit_log_path: str | Path = "~/.trimum/audit.log",
        dry_run: bool = False,
    ) -> None:
        self.policy = policy if policy is not None else PolicyEngine()
        self.timeout = timeout
        self._default_confirm = confirm_callback is None
        self.confirm_callback = confirm_callback or (
            lambda question: ask_confirm(question)
        )
        self.audit_log_path = Path(audit_log_path).expanduser()
        self.dry_run = dry_run

    # ------------------------------------------------------------------ #
    # 主流程
    # ------------------------------------------------------------------ #
    def execute(self, plan: CommandPlan) -> list[ExecutionResult]:
        """执行命令计划，返回逐条命令的执行结果。

        - commands 为空（解释模式）：仅展示说明，不执行任何命令。
        - 任一命令命中 critical：整体拒绝并提示。
        """
        if not plan.commands:
            # 纯解释模式（如管道输入解释代码）
            if plan.explanation:
                success(plan.explanation)
            else:
                info("没有需要执行的命令（No commands to execute）")
            return []

        # 第 1 步：展示计划与命令（C-1：先规范化展示，避免转义混淆）
        display_commands: list[str] = []
        for command in plan.commands:
            display_commands.extend(normalize_command(command))
        show_plan(plan.plan)
        show_commands(display_commands or plan.commands)

        decision = self.policy.evaluate_many(plan.commands)

        # 第 2 步：展示风险级别（带颜色）
        show_risk(decision.risk)

        # critical -> 直接拒绝
        if decision.denied:
            self._audit(plan, decision, "denied")
            show_rejection(self._rejection_message(decision))
            return [
                ExecutionResult(
                    command=cmd,
                    risk=decision.risk,
                    action="deny",
                    executed=False,
                    message="已被策略拒绝（Denied by policy）",
                )
                for cmd in plan.commands
            ]

        # M-2：dry-run 下 medium/high 不弹确认交互，直接展示占位结果
        if self.dry_run and decision.risk in ("medium", "high"):
            info("dry-run：该操作需要用户确认，已跳过确认（Would ask for confirmation）")
            return [
                ExecutionResult(
                    command=cmd,
                    risk=decision.risk,
                    action=decision.action,
                    executed=False,
                    message="dry-run：未实际执行（Not executed）",
                )
                for cmd in plan.commands
            ]

        # 第 3 步：确认（low 自动执行；high 附警告并审计）
        proceed = self._confirm(plan, decision)
        if not proceed:
            warning("已取消执行（Cancelled by user）")
            return [
                ExecutionResult(
                    command=cmd,
                    risk=decision.risk,
                    action=decision.action,
                    executed=False,
                    message="用户取消（User cancelled）",
                )
                for cmd in plan.commands
            ]

        if decision.risk == "high":
            self._audit(plan, decision, "confirmed")

        results: list[ExecutionResult] = []
        for command in plan.commands:
            result = self._run_command(command, decision)
            results.append(result)
            self._report(result)
        return results

    # ------------------------------------------------------------------ #
    # 确认与执行
    # ------------------------------------------------------------------ #
    def _confirm(self, plan: CommandPlan, decision: PolicyDecision) -> bool:
        """按风险级别决定是否需要用户确认。"""
        if decision.risk == "low":
            return True
        if decision.risk == "high":
            warning(
                f"{WARN_SYMBOL} 高危操作：确认后执行将被记录到审计日志"
                "（High-risk action will be audited）"
            )
        # L-5：非交互终端（管道/CI）下不调用 Confirm.ask（遇 EOF 行为未定义）
        if self._default_confirm and not sys.stdin.isatty():
            warning(
                "当前没有交互终端，无法确认（Non-interactive terminal; "
                "confirmation skipped）"
            )
            return False
        return bool(self.confirm_callback("继续执行？Continue? [y/N]"))

    def _run_command(self, command: str, decision: PolicyDecision) -> ExecutionResult:
        """通过 subprocess 执行单条命令（默认超时 60s）。

        展示用规范化后的命令（去转义/引号、拆链）；
        实际执行使用原始字符串以保持 shell 语义不变——
        策略引擎已对规范化后的子命令逐段评估（C-1）。
        """
        normalized = normalize_command(command)
        display = " ; ".join(normalized) if normalized else command
        if self.dry_run:
            return ExecutionResult(
                command=display,
                risk=decision.risk,
                action=decision.action,
                executed=False,
                message="dry-run：未实际执行（Not executed）",
            )
        if os.name == "nt":  # L-9：Windows 上提示 POSIX 命令可能不可用
            token = _first_token(command)
            if token and token in _POSIX_ONLY_COMMANDS:
                warning(
                    f"{WARN_SYMBOL} 命令 {token!r} 是 Linux/POSIX 命令，"
                    "Windows 上可能不可用（may not exist）"
                )
        try:
            proc = subprocess.run(
                command,
                shell=True,
                timeout=self.timeout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return ExecutionResult(
                command=display,
                risk=decision.risk,
                action=decision.action,
                executed=True,
                returncode=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
            )
        except subprocess.TimeoutExpired as exc:
            return ExecutionResult(
                command=display,
                risk=decision.risk,
                action=decision.action,
                executed=False,
                message=f"命令执行超时（{self.timeout}s，Timed out）",
                stderr=str(exc),
            )
        except (FileNotFoundError, OSError) as exc:
            return ExecutionResult(
                command=display,
                risk=decision.risk,
                action=decision.action,
                executed=False,
                message=f"命令执行失败（Command failed: {exc}）",
                stderr=str(exc),
            )
        except KeyboardInterrupt:
            raise

    def _report(self, result: ExecutionResult) -> None:
        """展示单条命令的结果（H-1：使用平台安全符号）。"""
        if result.executed and result.returncode == 0:
            success(f"{OK_SYMBOL} {result.command}")
        elif result.executed:
            error(f"{ERR_SYMBOL} {result.command}（退出码 {result.returncode}）")
        else:
            warning(f"{WARN_SYMBOL} {result.command}：{result.message}")
        if result.stdout:
            show_output(result.stdout, error=False)
        if result.stderr:
            show_output(result.stderr, error=True)

    # ------------------------------------------------------------------ #
    # 审计与拒绝消息
    # ------------------------------------------------------------------ #
    def _rejection_message(self, decision: PolicyDecision) -> str:
        """构造拒绝提示：优先使用规则自带 message。"""
        if decision.matched_rule is not None and decision.matched_rule.message:
            return decision.matched_rule.message
        return "该操作被策略引擎判定为危险操作，已自动拒绝（Denied by policy engine）"

    def _audit(self, plan: CommandPlan, decision: PolicyDecision, status: str) -> None:
        """审计记录：高危操作（确认执行或被拒绝）写入 ~/.trimum/audit.log。"""
        try:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
            commands = " | ".join(plan.commands)
            # L-6：只记录命令、风险与状态，不记录 explanation（可能含隐私）
            line = (
                f"[{timestamp}] status={status} risk={decision.risk} user={user} "
                f"commands={commands}\n"
            )
            with self.audit_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError as exc:
            warning(f"审计日志写入失败（Audit log write failed: {exc}）")