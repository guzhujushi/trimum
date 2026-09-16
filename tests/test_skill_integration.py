"""Integration tests for Skill Layer — load → route → execute.

Covers:
  1. SkillLoader scans skills directory, parses skill.yaml
  2. SkillDefinition model has `precheck` field (no `validate` conflict)
  3. SkillRouter routes `skill:<name>` capability
  4. SkillExecutor validates steps and reports results
  5. Template variable substitution {{input.xxx}}
  6. Pre-validation failure
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from trimum_core.skill_loader import (
    SkillLoader,
    SkillDefinition,
    SkillStep,
    SkillValidate,
    parse_skill_yaml,
)
from trimum_core.skill_router import SkillRouter
from trimum_core.skill_executor import SkillExecutor, SkillStepResult
from trimum_core.models import ExecuteResponse, ToolType
from trimum_core.tool_gateway import ToolGateway


# ===================================================================
#  SECTION 1: Skill Schema — no `validate` name conflict
# ===================================================================

def test_skill_definition_no_validate_conflict():
    """SkillDefinition uses `precheck` not `validate` — no Pydantic BaseModel conflict."""
    sd = SkillDefinition(
        name="test-skill",
        steps=[SkillStep(tool="shell", args=["echo", "hi"])],
    )
    # Pydantic BaseModel has a `validate()` method — ensure we don't shadow it
    assert hasattr(sd, "validate"), "Pydantic BaseModel.validate() must be accessible"
    assert sd.precheck is None, "precheck should default to None (not conflict with validate)"

    # With precheck
    sd2 = SkillDefinition(
        name="test-precheck",
        steps=[SkillStep(tool="shell", args=["echo", "hi"])],
        precheck=SkillValidate(require_executables=["git"]),
    )
    assert sd2.precheck is not None
    assert sd2.precheck.require_executables == ["git"]
    # verify no warning by calling validate (if it were shadowed, this would be the SkillValidate type)
    # BaseModel.validate() is a classmethod that takes cls and value
    assert callable(SkillDefinition.validate), "BaseModel.validate() must remain callable"


def test_skill_step_defaults():
    """SkillStep has sensible defaults."""
    step = SkillStep(tool="shell", args=["echo", "hello"])
    assert step.timeout_seconds == 30.0
    assert step.expect_exit == 0
    assert step.expect_stdout is None
    assert step.expect_stderr is None
    assert step.env == {}
    assert step.cwd is None


def test_skill_definition_validation():
    """SkillDefinition enforces at least one step."""
    with pytest.raises(Exception):  # Pydantic min_length validation
        SkillDefinition(name="empty", steps=[])

    # Two steps should be fine
    sd = SkillDefinition(
        name="multi-step",
        steps=[
            SkillStep(tool="shell", args=["echo", "one"]),
            SkillStep(tool="shell", args=["echo", "two"]),
        ],
    )
    assert len(sd.steps) == 2


# ===================================================================
#  SECTION 2: SkillLoader — scan real skills directory
# ===================================================================

def test_skill_loader_load_hello_world():
    """SkillLoader loads ~/.trimum/skills/hello-world/skill.yaml."""
    loader = SkillLoader()
    count = loader.load_all()
    assert count >= 1, "Should load at least hello-world skill"
    hello = loader.get("hello-world")
    assert hello is not None, "hello-world skill should be loaded"
    assert hello.name == "hello-world"
    assert len(hello.steps) == 2
    assert hello.steps[0].tool == "shell"


def test_skill_loader_load_git_deploy():
    """SkillLoader loads git-deploy with precheck."""
    loader = SkillLoader()
    loader.load_all()
    deploy = loader.get("git-deploy")
    assert deploy is not None, "git-deploy skill should be loaded"
    assert deploy.precheck is not None
    assert "git" in deploy.precheck.require_executables
    assert len(deploy.steps) == 3


def test_skill_loader_parse_single():
    """parse_skill_yaml convenience function works."""
    skill_path = Path.home() / ".trimum" / "skills" / "hello-world" / "skill.yaml"
    assert skill_path.exists()
    sd = parse_skill_yaml(str(skill_path))
    assert sd is not None
    assert sd.name == "hello-world"


def test_skill_loader_list_skills():
    """SkillLoader lists loaded skills."""
    loader = SkillLoader()
    loader.load_all()
    names = loader.list_skill_names()
    assert "hello-world" in names
    assert "git-deploy" in names


# ===================================================================
#  SECTION 3: SkillRouter — capability routing
# ===================================================================

def test_skill_router_prefix():
    """SkillRouter.skill_prefix parsing."""
    assert SkillRouter.is_skill_capability("skill:hello-world") is True
    assert SkillRouter.is_skill_capability("shell") is False
    assert SkillRouter.is_skill_capability("") is False

    assert SkillRouter.extract_skill_name("skill:hello-world") == "hello-world"
    assert SkillRouter.extract_skill_name("shell") is None
    assert SkillRouter.extract_skill_name("skill:") == ""


def test_skill_router_get_skill():
    """SkillRouter resolves skill by name."""
    loader = SkillLoader()
    loader.load_all()
    gw = ToolGateway()
    router = SkillRouter(loader, gw)
    skill = router.get_skill("hello-world")
    assert skill is not None
    assert skill.name == "hello-world"
    assert router.get_skill("nonexistent") is None


def test_skill_router_list_capabilities():
    """SkillRouter.list_skill_capabilities returns skill:<name> strings."""
    loader = SkillLoader()
    loader.load_all()
    gw = ToolGateway()
    router = SkillRouter(loader, gw)
    caps = router.list_skill_capabilities()
    assert "skill:hello-world" in caps
    assert "skill:git-deploy" in caps


# ===================================================================
#  SECTION 4: SkillExecutor — step execution (mocked)
# ===================================================================

@pytest.mark.asyncio
async def test_skill_executor_simple():
    """SkillExecutor runs steps successfully (mocked gateway)."""
    mock_gw = AsyncMock(spec=ToolGateway)
    mock_gw.execute.return_value = ExecuteResponse(
        status="allowed",
        exit_code=0,
        output="Hello from trimum Skill layer!",
        error="",
    )

    skill = SkillDefinition(
        name="test-simple",
        steps=[
            SkillStep(tool="shell", args=["echo", "Hello from trimum Skill layer!"]),
        ],
    )
    executor = SkillExecutor(mock_gw)
    result = await executor.execute(skill)

    assert result.success is True
    assert result.skill_name == "test-simple"
    assert len(result.step_results) == 1
    assert result.step_results[0].success is True


@pytest.mark.asyncio
async def test_skill_executor_step_failure():
    """SkillExecutor stops on step failure when stop_on_failure=True."""
    mock_gw = AsyncMock(spec=ToolGateway)
    mock_gw.execute.side_effect = [
        ExecuteResponse(status="allowed", exit_code=0, output="ok", error=""),
        ExecuteResponse(status="allowed", exit_code=1, output="", error="failure"),
    ]

    skill = SkillDefinition(
        name="test-fail",
        steps=[
            SkillStep(tool="shell", args=["echo", "ok"]),
            SkillStep(tool="shell", args=["false"]),
        ],
    )
    executor = SkillExecutor(mock_gw, stop_on_failure=True)
    result = await executor.execute(skill)

    assert result.success is False
    assert len(result.step_results) == 2  # both ran but step 2 failed
    assert result.step_results[0].success is True
    assert result.step_results[1].success is False


@pytest.mark.asyncio
async def test_skill_executor_precheck_failure():
    """SkillExecutor fails fast when precheck validation fails."""
    mock_gw = AsyncMock(spec=ToolGateway)
    mock_gw.tools = {}  # no tools registered

    skill = SkillDefinition(
        name="test-precheck-fail",
        steps=[SkillStep(tool="shell", args=["echo", "hi"])],
        precheck=SkillValidate(require_executables=["this_exe_does_not_exist_xyz123"]),
    )
    executor = SkillExecutor(mock_gw)
    result = await executor.execute(skill)

    assert result.success is False
    assert "Pre-validation failed" in (result.error or "")
    assert len(result.step_results) == 0  # no steps ran


@pytest.mark.asyncio
async def test_skill_executor_expect_exit_check():
    """SkillExecutor validates expect_exit code."""
    mock_gw = AsyncMock(spec=ToolGateway)
    mock_gw.execute.return_value = ExecuteResponse(
        status="allowed", exit_code=1, output="", error="error output",
    )

    skill = SkillDefinition(
        name="test-exit-check",
        steps=[SkillStep(tool="shell", args=["false"])],
    )
    executor = SkillExecutor(mock_gw)
    result = await executor.execute(skill)

    assert result.success is False
    assert "Expected exit code 0" in (result.error or "")


@pytest.mark.asyncio
async def test_skill_executor_expect_stdout_regex():
    """SkillExecutor validates stdout against a regex pattern."""
    mock_gw = AsyncMock(spec=ToolGateway)
    mock_gw.execute.return_value = ExecuteResponse(
        status="allowed", exit_code=0, output="Deploy completed successfully", error="",
    )

    skill = SkillDefinition(
        name="test-stdout-check",
        steps=[SkillStep(tool="shell", args=["echo", "Deploy completed successfully"],
                         expect_stdout=r"successfully")],
    )
    executor = SkillExecutor(mock_gw)
    result = await executor.execute(skill)
    assert result.success is True


@pytest.mark.asyncio
async def test_skill_executor_experience_injection():
    """SkillExecutor returns experience entries in result."""
    mock_gw = AsyncMock(spec=ToolGateway)
    mock_gw.execute.return_value = ExecuteResponse(
        status="allowed", exit_code=0, output="ok", error="",
    )

    skill = SkillDefinition(
        name="test-exp",
        steps=[SkillStep(tool="shell", args=["echo", "ok"])],
        experience=["Exp 1: Always backup first", "Exp 2: Use --ff-only"],
    )
    executor = SkillExecutor(mock_gw)
    result = await executor.execute(skill)

    assert result.success is True
    assert len(result.experience) == 2
    assert "Exp 1: Always backup first" in result.experience


# ===================================================================
#  SECTION 5: SkillRouter — full end-to-end mocked execution
# ===================================================================

@pytest.mark.asyncio
async def test_skill_router_execute_skill():
    """SkillRouter.execute_skill dispatches to executor correctly."""
    loader = SkillLoader()
    loader.load_all()
    mock_gw = AsyncMock(spec=ToolGateway)
    mock_gw.execute.return_value = ExecuteResponse(
        status="allowed", exit_code=0, output="Hello from trimum Skill layer!", error="",
    )

    router = SkillRouter(loader, mock_gw)
    result = await router.execute_skill("hello-world")

    assert result.success is True
    assert result.skill_name == "hello-world"


@pytest.mark.asyncio
async def test_skill_router_execute_skill_not_found():
    """SkillRouter raises ValueError for unknown skill."""
    loader = SkillLoader()
    mock_gw = AsyncMock(spec=ToolGateway)
    router = SkillRouter(loader, mock_gw)

    with pytest.raises(ValueError, match="Skill 'nonexistent' not found"):
        await router.execute_skill("nonexistent")


# ===================================================================
#  SECTION 6: Template variable substitution
# ===================================================================

@pytest.mark.asyncio
async def test_skill_executor_template_vars():
    """SkillExecutor substitutes {placeholder} in step args."""
    mock_gw = AsyncMock(spec=ToolGateway)
    mock_gw.execute.return_value = ExecuteResponse(
        status="allowed", exit_code=0, output="deployed to production", error="",
    )

    skill = SkillDefinition(
        name="test-template",
        steps=[
            SkillStep(tool="shell", args=["echo", "Deploying to {env}"]),
        ],
    )
    executor = SkillExecutor(mock_gw)
    result = await executor.execute(skill, extra_args={"env": "production"})

    assert result.success is True
    # Verify that gateway was called with resolved args
    call_args = mock_gw.execute.call_args[0][0]
    assert "production" in str(call_args.args)


# ===================================================================
#  SECTION 7: Edge cases
# ===================================================================

def test_skill_loader_missing_yaml_causes_no_error():
    """SkillLoader handles missing YAML package gracefully."""
    loader = SkillLoader(skills_path="/nonexistent/path")
    count = loader.load_all()
    assert count == 0


def test_skill_loader_custom_path():
    """SkillLoader can use custom skills directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "demo"
        skill_dir.mkdir()
        yaml_path = skill_dir / "skill.yaml"
        yaml_path.write_text("""name: demo
version: "1.0.0"
steps:
  - tool: shell
    args: ["echo", "demo"]
""", encoding="utf-8")

        loader = SkillLoader(skills_path=str(Path(tmpdir)))
        count = loader.load_all()
        assert count == 1
        skill = loader.get("demo")
        assert skill is not None
        assert skill.name == "demo"


def test_skill_step_result_dataclass():
    """SkillStepResult holds expected fields."""
    sr = SkillStepResult(
        step_index=0,
        tool="shell",
        args=["echo", "hi"],
        success=True,
        exit_code=0,
        stdout="hi\n",
        stderr="",
        duration_seconds=0.1,
    )
    assert sr.success is True
    assert sr.tool == "shell"
