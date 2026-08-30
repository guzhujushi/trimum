"""Tool Gateway — async command execution with policy checking."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional

from .models import ExecuteRequest, ExecuteResponse, RiskLevel, Action, ToolType
from .policy_engine import PolicyEngine
from .logger import get_logger

logger = get_logger("tool_gateway")


class ToolGateway:
    """Execute shell/git/docker commands via async subprocess with policy check.

    This is the core execution engine of trimum Core. It:
    1. Receives execution requests from API or directly
    2. Checks permissions via PolicyEngine
    3. Spawns async subprocess with timeout
    4. Returns structured results
    """

    def __init__(self, policy_engine: Optional[PolicyEngine] = None):
        self.policy = policy_engine or PolicyEngine()

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        """Execute a tool command with policy check."""
        execution_id = uuid.uuid4().hex[:12]

        # Build command string from args
        cmd_str = " ".join(request.args) if isinstance(request.args, list) else request.args
        cmd_str = cmd_str.strip()

        if not cmd_str:
            return ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                error="Empty command",
                exit_code=1,
                risk=RiskLevel.CRITICAL,
                action=Action.DENY,
                reason="No command provided",
            )

        # Policy check
        risk, action, reason = self.policy.evaluate(cmd_str)

        # Deny immediately for critical
        if action == Action.DENY:
            logger.warning("command_denied", command=cmd_str, reason=reason, risk=risk.value)
            return ExecuteResponse(
                execution_id=execution_id,
                status="denied",
                output="",
                error=f"Command denied by policy: {reason}",
                exit_code=1,
                risk=risk,
                action=action,
                reason=reason,
            )

        # For confirm, mark as needing user approval but still execute (caller decides)
        # For auto, execute directly
        logger.info(
            "executing_command",
            command=cmd_str,
            risk=risk.value,
            action=action.value,
            execution_id=execution_id,
            agent_id=request.agent_id,
        )

        # Execute
        result = await self._run_subprocess(
            cmd=cmd_str,
            timeout=request.timeout_seconds,
            env=request.env or None,
            cwd=request.cwd,
        )

        status = "allowed" if action == Action.AUTO else "confirmed"

        return ExecuteResponse(
            execution_id=execution_id,
            status=status,
            output=result["stdout"],
            error=result["stderr"],
            exit_code=result["exit_code"],
            risk=risk,
            action=action,
            reason=reason,
        )

    async def _run_subprocess(
        self,
        cmd: str,
        timeout: float = 30.0,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> dict:
        """Run a command via async subprocess with timeout."""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
                shell=True,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout}s",
                    "exit_code": -1,
                }

            return {
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                "exit_code": proc.returncode or 0,
            }

        except FileNotFoundError:
            return {"stdout": "", "stderr": "Command not found", "exit_code": 127}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1}
