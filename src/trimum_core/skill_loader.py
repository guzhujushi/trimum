"""Skill Loader — scan and parse skill.yaml manifests.

Skill = lightweight capability package (YAML-defined tool composition template).
Agent declares ``skill:<name>`` in capabilities, SkillRouter routes to SkillExecutor.

Directory layout:
    ~/.trimum/skills/<name>/
        skill.yaml   — machine-readable definition
        SKILL.md     — optional human-readable docs (unused by code)

See docs/skills/SKILL-SPEC.md for full specification.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

import logging

log = logging.getLogger("trimum_core.skill_loader")

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class SkillStep(BaseModel):
    """A single step in a skill execution plan."""

    tool: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    timeout_seconds: float = 30.0
    # 校验条件
    expect_exit: Optional[int] = 0
    expect_stdout: Optional[str] = None  # regex pattern
    expect_stderr: Optional[str] = None  # regex pattern (None = expect no stderr)

    model_config = {"extra": "forbid"}


class SkillValidate(BaseModel):
    """Optional validation checks to run before execution."""

    require_tools: list[str] = Field(default_factory=list)
    require_env: list[str] = Field(default_factory=list)
    require_paths: list[str] = Field(default_factory=list)
    require_executables: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class SkillDefinition(BaseModel):
    """A parsed skill.yaml manifest."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    # Author/owner info (informational)
    author: str = ""
    # 依赖的技能（可嵌套）
    depends_on: list[str] = Field(default_factory=list)
    # 所需 capabilities（声明式，AgentRouter 匹配用）
    requires_capabilities: list[str] = Field(default_factory=list)
    # 可选前置校验（命名 precheck 而非 validate，避免与 BaseModel.validate 冲突）
    precheck: Optional[SkillValidate] = None
    # 执行步骤
    steps: list[SkillStep] = Field(min_length=1)
    # 经验注入（踩坑记录 → 写入 Agent 上下文）
    experience: list[str] = Field(default_factory=list)
    # 预设提示词（Agent 用 skill 时可选的 prompt 片段）
    prompts: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Skill Loader
# ---------------------------------------------------------------------------


class SkillLoader:
    """Scan skills directory and load skill.yaml definitions.

    Thread-safe for read operations. Not designed for hot-reload
    (requires a new SkillLoader instance or explicit reload).
    """

    def __init__(self, skills_path: Optional[str] = None) -> None:
        self._skills_path = Path(skills_path or Path.home() / ".trimum" / "skills")
        self._skills: dict[str, SkillDefinition] = {}
        self._load_errors: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> int:
        """Scan skills directory and load all skill.yaml files.

        Returns the number of successfully loaded skills.
        Errors are recorded in ``self._load_errors``.
        """
        self._skills.clear()
        self._load_errors.clear()

        if not self._skills_path.is_dir():
            return 0

        count = 0
        for child in sorted(self._skills_path.iterdir()):
            if not child.is_dir():
                continue
            skill_yaml = child / "skill.yaml"
            if not skill_yaml.is_file():
                continue
            try:
                definition = self._load_single(skill_yaml)
                if definition is not None:
                    self._skills[definition.name] = definition
                    count += 1
            except Exception as e:
                self._load_errors[child.name] = str(e)

        return count

    def get(self, name: str) -> Optional[SkillDefinition]:
        """Get a loaded skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        """Return all loaded skill definitions."""
        return list(self._skills.values())

    def list_skill_names(self) -> list[str]:
        """Return names of all loaded skills."""
        return list(self._skills.keys())

    def get_load_errors(self) -> dict[str, str]:
        """Return {dir_name: error_message} for failed loads."""
        return dict(self._load_errors)

    def get_skills_path(self) -> str:
        """Return the configured skills base directory."""
        return str(self._skills_path)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_single(self, path: Path) -> Optional[SkillDefinition]:
        """Parse a single skill.yaml file into a SkillDefinition.

        Returns None if YAML parsing fails or the required package
        is not available.
        """
        if not HAS_YAML:
            self._load_errors[path.parent.name] = (
                "PyYAML not installed. Install with: pip install pyyaml"
            )
            return None

        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError(f"skill.yaml must be a mapping, got {type(data).__name__}")

        # Validate name matches directory name
        dir_name = path.parent.name
        skill_name = data.get("name", dir_name)
        if skill_name != dir_name:
            log.warning(
                "skill_name_mismatch",
                skill=skill_name,
                dir=dir_name,
            )

        return SkillDefinition(**data)


# Convenience function for simple usage
def parse_skill_yaml(path: str) -> Optional[SkillDefinition]:
    """Parse a single skill.yaml file and return its definition."""
    loader = SkillLoader()
    return loader._load_single(Path(path))
