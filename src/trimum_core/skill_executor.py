"""Skill Executor — execute SkillDefinition steps with validation and experience injection.

Flow:
    1. Pre-validation (required tools, env vars, paths, executables)
    2. Step-by-step execution via ToolGateway
    3. Each step: run → check expect_exit/expect_stdout/expect_stderr
    4. On failure: collect error, stop (configurable)
    5. Return aggregated result with experience payload
"""

from __future__ import annotations

import re
import shutil
import time
import os
from typing import Any, Optional

import logging

from .skill_loader import SkillDefinition, SkillStep, SkillValidate
from .tool_gateway import ToolGateway
from .models import ExecuteRequest, ExecuteResponse, ToolType, SourceType

log = logging.getLogger("trimum_core.skill_executor")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class SkillStepResult:
    """Result of a single skill step."""

    def __init__(
        self,
        step_index: int,
        tool: str,
        args: list[str],
        success: bool,
        exit_code: Optional[int] = None,
        stdout: str = "",
        stderr: str = "",
        error: Optional[str] = None,
        duration_seconds: float = 0.0,
    ) -> None:
        self.step_index = step_index
        self.tool = tool
        self.args = args
        self.success = success
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.error = error
        self.duration_seconds = duration_seconds


class SkillExecutionResult:
    """Aggregated result of a full skill execution."""

    def __init__(
        self,
        skill_name: str,
        success: bool,
        step_results: list[SkillStepResult],
        experience: list[str],
        duration_seconds: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        self.skill_name = skill_name
        self.success = success
        self.step_results = step_results
        self.experience = experience
        self.duration_seconds = duration_seconds
        self.error = error


# ---------------------------------------------------------------------------
# Skill Executor
# ---------------------------------------------------------------------------


class SkillExecutor:
    """Execute a SkillDefinition step by step via ToolGateway.

    Thread-safe only if ToolGateway is thread-safe (it uses asyncio).
    Intended for async use.
    """

    def __init__(
        self,
        gateway: ToolGateway,
        stop_on_failure: bool = True,
    ) -> None:
        self._gateway = gateway
        self._stop_on_failure = stop_on_failure

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        skill: SkillDefinition,
        agent_id: Optional[str] = None,
        extra_args: Optional[dict[str, str]] = None,
    ) -> SkillExecutionResult:
        """Execute a skill end-to-end.

        Args:
            skill: The parsed SkillDefinition to execute.
            agent_id: Optional agent ID for audit/logging.
            extra_args: Optional template variables for ``{placeholder}``
                        substitution in step args.

        Returns:
            SkillExecutionResult with step-by-step details.
        """
        start = time.time()

        # 1. Pre-validation
        if skill.precheck:
            val_error = self._validate(skill.precheck)
            if val_error:
                return SkillExecutionResult(
                    skill_name=skill.name,
                    success=False,
                    step_results=[],
                    experience=skill.experience,
                    duration_seconds=time.time() - start,
                    error=f"Pre-validation failed: {val_error}",
                )

        # 2. Execute steps sequentially
        step_results: list[SkillStepResult] = []
        for i, step in enumerate(skill.steps):
            step_start = time.time()
            result = await self._execute_step(step, i, agent_id, extra_args)
            step_results.append(result)

            if not result.success and self._stop_on_failure:
                return SkillExecutionResult(
                    skill_name=skill.name,
                    success=False,
                    step_results=step_results,
                    experience=skill.experience,
                    duration_seconds=time.time() - start,
                    error=f"Step {i} ({step.tool}) failed: {result.error or 'Unknown error'}",
                )

        # 3. All steps passed
        return SkillExecutionResult(
            skill_name=skill.name,
            success=True,
            step_results=step_results,
            experience=skill.experience,
            duration_seconds=time.time() - start,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        step: SkillStep,
        index: int,
        agent_id: Optional[str],
        extra_args: Optional[dict[str, str]],
    ) -> SkillStepResult:
        """Execute a single skill step via ToolGateway."""
        step_start = time.time()

        # Template substitution in args
        args = list(step.args)
        if extra_args:
            resolved: list[str] = []
            for arg in args:
                for key, value in extra_args.items():
                    arg = arg.replace(f"{{{key}}}", value)
                resolved.append(arg)
            args = resolved

        # Determine ToolType
        tool_type = self._resolve_tool_type(step.tool)
        if tool_type is None:
            return SkillStepResult(
                step_index=index,
                tool=step.tool,
                args=args,
                success=False,
                error=f"Unknown tool type: {step.tool}",
                duration_seconds=time.time() - step_start,
            )

        # Build request
        request = ExecuteRequest(
            tool=tool_type,
            args=args,
            agent_id=agent_id,
            timeout_seconds=step.timeout_seconds,
            env=step.env,
            cwd=step.cwd,
            source_type=SourceType.AI,
        )

        # Execute
        try:
            response: ExecuteResponse = await self._gateway.execute(request)
        except Exception as e:
            return SkillStepResult(
                step_index=index,
                tool=step.tool,
                args=args,
                success=False,
                error=f"Gateway exception: {e}",
                duration_seconds=time.time() - step_start,
            )

        exit_code = response.exit_code or 0
        stdout = response.output or ""
        stderr = response.error or ""

        # Validate exit code
        if step.expect_exit is not None and exit_code != step.expect_exit:
            return SkillStepResult(
                step_index=index,
                tool=step.tool,
                args=args,
                success=False,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                error=f"Expected exit code {step.expect_exit}, got {exit_code}",
                duration_seconds=time.time() - step_start,
            )

        # Validate stdout pattern
        if step.expect_stdout is not None:
            if not re.search(step.expect_stdout, stdout):
                return SkillStepResult(
                    step_index=index,
                    tool=step.tool,
                    args=args,
                    success=False,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    error=f"stdout did not match pattern: {step.expect_stdout}",
                    duration_seconds=time.time() - step_start,
                )

        # Validate stderr pattern
        if step.expect_stderr is not None:
            if not re.search(step.expect_stderr, stderr):
                return SkillStepResult(
                    step_index=index,
                    tool=step.tool,
                    args=args,
                    success=False,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    error=f"stderr did not match pattern: {step.expect_stderr}",
                    duration_seconds=time.time() - step_start,
                )
        elif stderr.strip():
            # Default: stderr should be empty
            return SkillStepResult(
                step_index=index,
                tool=step.tool,
                args=args,
                success=False,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                error=f"Unexpected stderr output (len={len(stderr.strip())})",
                duration_seconds=time.time() - step_start,
            )

        # Success
        return SkillStepResult(
            step_index=index,
            tool=step.tool,
            args=args,
            success=True,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.time() - step_start,
        )

    def _validate(self, validate: SkillValidate) -> Optional[str]:
        """Run pre-validation checks. Returns error string or None."""
        for tool_name in validate.require_tools:
            if not self._gateway.tools.get(tool_name):
                return f"Required tool not registered: {tool_name}"

        for env_var in validate.require_env:
            if not os.environ.get(env_var):
                return f"Required environment variable not set: {env_var}"

        for path in validate.require_paths:
            if not os.path.exists(path):
                return f"Required path does not exist: {path}"

        for exe in validate.require_executables:
            if shutil.which(exe) is None:
                return f"Required executable not found in PATH: {exe}"

        return None

    @staticmethod
    def _resolve_tool_type(name: str) -> Optional[ToolType]:
        """Convert a tool name string to a ToolType enum.

        Supports both short names (``shell``, ``git``) and
        dotted names (``file.read``, ``http.get``).
        """
        # Direct match
        try:
            return ToolType(name)
        except ValueError:
            pass

        # Try literal match (case-insensitive)
        name_lower = name.lower()
        for member in ToolType:
            if member.value == name_lower:
                return member

        return None


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def extract_experience(skill: SkillDefinition) -> list[str]:
    """Extract experience entries from a skill for injection into Agent context."""
    return list(skill.experience)
