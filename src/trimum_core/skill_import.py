"""Agent Skills 导入 —— E4（E3 顺延的 ``trm skill import``）。

``trm skill sync`` 解决"把已有的技能分发到各个 harness"，本模块解决"技能从哪来"：
本地一个目录、或一个 git 仓库，``trm skill import`` 就能收进 ``<TRIMUM_HOME>/skills/``。

三条红线（与另两个导入器一致）：

* **导入不执行**：只读文本、只复制文件 —— 导入一份 SKILL.md 不会运行里面任何一个字；
* **``--dry-run`` 不落盘**，逐条给出校验结果；
* **不覆盖已有**：目标已存在时拒绝，除非显式 ``--force``（先全量检查再写，不做半截导入）。

git 源走系统 ``git clone --depth 1``（不引入新依赖）：克隆到临时目录，用来**看**技能长什么样，
导入完就删掉。clone 失败即报错，不静默降级成"本地没有"。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .cli_adapter import default_runner
from .ecosystem import (
    TRUST_LEVELS,
    EcosystemEntry,
    ImportRefused,
    validate_entry,
)

#: 认的技能描述文件（Agent Skills 标准）与 trimum 自己的可执行技能。
AGENT_SKILL_FILE = "SKILL.md"
TRIMUM_SKILL_FILE = "skill.yaml"

#: git clone 的超时（秒）与 ``git clone`` 的参数。
CLONE_TIMEOUT = 120.0

#: 技能目录里不复制的东西（都不是技能内容，复制它们只会让导入变重）。
IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)

#: 一份技能最多多少个文件：防止"导入一个仓库"变成"复制一个仓库"。
MAX_FILES = 200

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_REMOTE_RE = re.compile(r"^(?:https?://|git\+|ssh://|git://|git@)")


class SkillImportError(ValueError):
    """源不能用（路径不存在、clone 失败、frontmatter 不合法）时抛出。"""


def skills_root(root: Path | str | None = None) -> Path:
    """Return the skill install root (``<TRIMUM_HOME>/skills`` by default)."""
    if root is not None:
        return Path(root).expanduser()
    from .paths import trimum_path

    return trimum_path("skills")


def is_remote_source(source: str | Path) -> bool:
    """Whether *source* has to be fetched with ``git clone``.

    ``.../repo.git`` 这种**本地**裸仓库路径也算：它确实是 git 源，只是不用联网。
    """
    text = str(source).strip()
    return bool(_REMOTE_RE.match(text)) or text.endswith(".git")


def is_url(value: str | Path) -> bool:
    """Whether *value* is a real URL (as opposed to a path that ends in ``.git``)."""
    return bool(_REMOTE_RE.match(str(value).strip()))


def default_git_runner(argv: Sequence[str], timeout: float):
    """Run ``git`` with the same safe capture the CLI prober uses.

    ``stdin=DEVNULL`` 是关键：私有仓库要凭据时，git 会去等输入 —— 无人值守的导入
    宁可立刻失败，也不要挂在那里。
    """
    return default_runner(argv, timeout)


def clone_repo(
    url: str,
    destination: Path,
    *,
    runner: Callable[[Sequence[str], float], Any] | None = None,
    timeout: float = CLONE_TIMEOUT,
) -> Path:
    """``git clone --depth 1`` *url* into *destination*; returns the destination."""
    run = runner or default_git_runner
    destination = Path(destination)
    argv = ["git", "clone", "--depth", "1", url, str(destination)]
    try:
        completed = run(argv, timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SkillImportError(f"git clone failed: {exc}") from exc

    if getattr(completed, "returncode", 1) != 0:
        detail = (getattr(completed, "stderr", "") or "").strip().splitlines()
        tail = detail[-1] if detail else "no output"
        raise SkillImportError(f"git clone failed (rc={completed.returncode}): {tail}")
    if not destination.is_dir():
        raise SkillImportError(f"git clone left nothing at {destination}")
    return destination


def read_frontmatter(skill_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Return ``(frontmatter, problems)`` for a skill's ``SKILL.md``.

    Agent Skills 要求 ``SKILL.md`` 以 ``---`` 开头的 YAML frontmatter 打头，且
    ``name`` / ``description`` 必填 —— 缺了就不该进技能目录（harness 读不懂它）。
    """
    skill_md = Path(skill_dir) / AGENT_SKILL_FILE
    if not skill_md.is_file():
        return {}, [f"没有 {AGENT_SKILL_FILE}"]

    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, [f"读不了 {AGENT_SKILL_FILE}: {exc}"]

    if not text.lstrip().startswith("---"):
        return {}, [f"{AGENT_SKILL_FILE} 没有 YAML frontmatter（应以 --- 开头）"]

    remainder = text.lstrip()[3:]
    frontmatter, separator, _ = remainder.partition("\n---")
    if not separator:
        return {}, [f"{AGENT_SKILL_FILE} 的 frontmatter 没有结束的 ---"]

    import yaml

    try:
        data = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError as exc:
        return {}, [f"{AGENT_SKILL_FILE} 的 frontmatter 不是合法 YAML: {exc}"]
    if not isinstance(data, dict):
        return {}, [f"{AGENT_SKILL_FILE} 的 frontmatter 必须是 mapping"]

    problems: list[str] = []
    front = {str(key): item for key, item in data.items()}
    name = str(front.get("name") or "").strip()
    description = str(front.get("description") or "").strip()
    if not name:
        problems.append("frontmatter 缺 `name`")
    elif len(name) > 64:
        problems.append("frontmatter 的 `name` 超过 64 个字符")
    elif not _NAME_RE.match(name):
        problems.append(f"`name` `{name}` 只能用小写字母/数字/连字符")
    if not description:
        problems.append("frontmatter 缺 `description`")
    return front, problems


def _holds_skill(path: Path) -> bool:
    """Whether *path* is itself a skill directory."""
    return (path / AGENT_SKILL_FILE).is_file() or (path / TRIMUM_SKILL_FILE).is_file()


def discover_skill_dirs(source: Path | str) -> list[Path]:
    """Skill directories under *source*.

    ``source`` 自己带 ``SKILL.md`` 就是一个技能；否则把它当"技能根"，看它的**直接**子目录；
    直接子目录里也没有时，再看一层（``<repo>/skills/<name>/SKILL.md`` 是仓库里最常见的
    布局）。再深就不看了 —— 技能是平的，无限递归只会把别人的例子目录也当成技能。
    """
    path = Path(source).expanduser()
    if not path.exists():
        raise SkillImportError(f"no such file or directory: {path}")
    if path.is_file():
        raise SkillImportError(f"{path} 是文件；请给技能目录（含 {AGENT_SKILL_FILE}）")

    if _holds_skill(path):
        return [path]

    found: list[Path] = []
    for child in sorted(path.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and _holds_skill(child):
            found.append(child)
    if found:
        return found

    for child in sorted(path.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        for grandchild in sorted(child.iterdir()):
            if grandchild.is_dir() and _holds_skill(grandchild):
                found.append(grandchild)
    if not found:
        raise SkillImportError(f"{path} 里没有找到任何技能（需要 {AGENT_SKILL_FILE}）")
    return found


def list_skill_files(skill_dir: Path) -> list[Path]:
    """Every file to copy, relative to *skill_dir* (ignored dirs pruned)."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(skill_dir):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        for filename in sorted(filenames):
            files.append(Path(dirpath, filename).relative_to(skill_dir))
    return files


@dataclass
class SkillCandidate:
    """One skill directory, validated and ready to copy."""

    name: str
    path: str
    description: str = ""
    kind: str = "agent-skill"
    trust: str = "third-party"
    source: str = ""
    frontmatter: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def to_entry(self) -> EcosystemEntry:
        """The same shape every other imported thing has (``kind=skill``)."""
        return EcosystemEntry(
            name=self.name,
            kind="skill",
            description=self.description,
            trust=self.trust,
            risk="low",
            requires=[],
            source_url=self.source if is_url(self.source) else "",
            author=str(self.frontmatter.get("author") or ""),
            origin=self.source,
            enabled=True,
            tags=[],
            risk_reasons=[
                "技能是纯文本：导入不执行任何东西，risk 固定 low（执行它的是读到它的 agent）"
            ],
            details={"files": len(self.files), "kind": self.kind, "path": self.path},
        )

    def summary(self) -> str:
        """One line for humans."""
        return f"{self.name} files={len(self.files)} trust={self.trust}"


def parse_skill(
    skill_dir: Path | str,
    *,
    trust: str = "third-party",
    source: str = "",
) -> SkillCandidate:
    """Validate one skill directory (never executes anything inside it)."""
    path = Path(skill_dir)
    if trust not in TRUST_LEVELS:
        raise SkillImportError(f"unknown trust `{trust}` (expected one of {', '.join(TRUST_LEVELS)})")

    has_agent_skill = (path / AGENT_SKILL_FILE).is_file()
    has_trimum_skill = (path / TRIMUM_SKILL_FILE).is_file()
    if not has_agent_skill and not has_trimum_skill:
        raise SkillImportError(f"{path} 里既没有 {AGENT_SKILL_FILE} 也没有 {TRIMUM_SKILL_FILE}")

    candidate = SkillCandidate(
        name=path.name,
        path=str(path),
        trust=trust,
        source=str(source or path),
        kind="agent-skill" if has_agent_skill else "trimum-skill",
    )

    if has_agent_skill:
        frontmatter, problems = read_frontmatter(path)
        candidate.frontmatter = frontmatter
        candidate.problems.extend(problems)
        candidate.description = str(frontmatter.get("description") or "").strip()
        declared = str(frontmatter.get("name") or "").strip()
        if declared:
            candidate.name = declared
            if declared != path.name:
                candidate.warnings.append(
                    f"frontmatter 的 `name`（{declared}）与目录名（{path.name}）不同，按 `{declared}` 安装"
                )
    else:
        candidate.warnings.append(
            f"只有 {TRIMUM_SKILL_FILE}（trimum 自带技能），不会分发到别的 harness"
        )

    files = list_skill_files(path)
    candidate.files = [str(item).replace(os.sep, "/") for item in files]
    if AGENT_SKILL_FILE not in candidate.files and has_agent_skill:
        candidate.problems.append(f"{AGENT_SKILL_FILE} 不在可复制的文件列表里")
    if len(files) > MAX_FILES:
        candidate.problems.append(f"技能目录里有 {len(files)} 个文件，超过上限 {MAX_FILES}")

    problems = validate_entry(candidate.to_entry())
    candidate.problems.extend(problems)
    return candidate


def plan_import(
    source: str | Path,
    *,
    root: Path | str | None = None,
    trust: str = "third-party",
    workspace: Path | str | None = None,
    git_runner: Callable[[Sequence[str], float], Any] | None = None,
) -> dict[str, Any]:
    """Describe what importing *source* would do (used by ``--dry-run``).

    git 源会先浅克隆到 *workspace*（没给就自己开一个临时目录，删不删看
    :func:`cleanup`）：要判断"这个仓库里有哪些技能"，就必须真的看一眼。
    """
    text = str(source).strip()
    if not text:
        raise SkillImportError("empty source")
    if trust not in TRUST_LEVELS:
        raise SkillImportError(f"unknown trust `{trust}`")

    workspace_path: Path | None = None
    temporary = False
    origin_kind = "local"

    if is_remote_source(text):
        origin_kind = "git"
        if workspace is not None:
            workspace_path = Path(workspace).expanduser()
            workspace_path.mkdir(parents=True, exist_ok=True)
        else:
            workspace_path = Path(tempfile.mkdtemp(prefix="trm-skill-import-"))
            temporary = True
        clone_repo(text, workspace_path / "repo", runner=git_runner)
        local_root = workspace_path / "repo"
    else:
        local_root = Path(text).expanduser()

    target_root = skills_root(root)
    skills: list[dict[str, Any]] = []
    problems: dict[str, list[str]] = {}
    seen: dict[str, str] = {}

    for skill_dir in discover_skill_dirs(local_root):
        try:
            candidate = parse_skill(skill_dir, trust=trust, source=text)
        except SkillImportError as exc:
            problems[str(skill_dir)] = [str(exc)]
            skills.append({"path": str(skill_dir), "problems": [str(exc)], "warnings": []})
            continue

        item: dict[str, Any] = {
            "name": candidate.name,
            "path": candidate.path,
            "kind": candidate.kind,
            "description": candidate.description,
            "entry": candidate.to_entry().to_dict(),
            "files": candidate.files,
            "target_dir": str(target_root / candidate.name),
            "problems": list(candidate.problems),
            "warnings": list(candidate.warnings),
        }
        if candidate.name in seen:
            item["problems"].append(f"`{candidate.name}` 与 {seen[candidate.name]} 重复")
        else:
            seen[candidate.name] = candidate.path
        if item["problems"]:
            problems[candidate.name] = list(item["problems"])
        skills.append(item)

    return {
        "source": text,
        "origin": origin_kind,
        "root": str(target_root),
        "workspace": str(workspace_path) if workspace_path else "",
        "workspace_temporary": temporary,
        "skills": skills,
        "importable": sum(1 for item in skills if not item["problems"]),
        "problems": problems,
    }


def cleanup(plan: dict[str, Any]) -> None:
    """Remove the throwaway clone a git-source plan made (no-op for local sources)."""
    if not plan.get("workspace_temporary"):
        return
    workspace = plan.get("workspace")
    if workspace:
        shutil.rmtree(workspace, ignore_errors=True)


def write_skills(
    plan: dict[str, Any],
    *,
    dry_run: bool = False,
    force: bool = False,
) -> list[str]:
    """Copy the usable skills from *plan*; returns the directories created.

    先全量检查再写：目标已存在（且没有 ``--force``）时抛 :class:`ImportRefused`，
    不做"拷了一半才发现冲突"的导入。
    """
    usable = [item for item in plan.get("skills", []) if not item.get("problems")]
    if not usable:
        raise ImportRefused("没有可导入的技能（逐条校验都没过）")

    targets = [Path(item["target_dir"]) for item in usable]
    if not force:
        clashes = [str(path) for path in targets if path.exists()]
        if clashes:
            raise ImportRefused(
                "目标已存在：" + ", ".join(clashes) + "（确认要覆盖就加 --force）"
            )
    if dry_run:
        return []

    # 文件清单在这里重算一遍：plan 到写盘之间人会等（--force 确认）、源目录也可能变，
    # 复制"此刻的源目录"比复制"刚才看到的清单"更不容易骗人。
    batches: list[tuple[Path, Path, list[str]]] = []
    for item in usable:
        source_dir = Path(item["path"])
        skill_file = AGENT_SKILL_FILE if item["kind"] == "agent-skill" else TRIMUM_SKILL_FILE
        if not (source_dir / skill_file).is_file():
            raise SkillImportError(f"{source_dir} 已经不是技能了（缺 {skill_file}）")
        files = [str(rel).replace(os.sep, "/") for rel in list_skill_files(source_dir)]
        if len(files) > MAX_FILES:
            raise SkillImportError(
                f"{source_dir} 里的文件变成 {len(files)} 个，超过上限 {MAX_FILES}"
            )
        batches.append((source_dir, Path(item["target_dir"]), files))

    written: list[str] = []
    for source_dir, target_dir, files in batches:
        if target_dir.exists() and force:
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        for relative in files:
            source_file = source_dir / relative
            target_file = target_dir / relative
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
        written.append(str(target_dir))
    return written


__all__ = [
    "AGENT_SKILL_FILE",
    "CLONE_TIMEOUT",
    "IGNORED_DIRS",
    "MAX_FILES",
    "TRIMUM_SKILL_FILE",
    "SkillCandidate",
    "SkillImportError",
    "cleanup",
    "clone_repo",
    "default_git_runner",
    "discover_skill_dirs",
    "is_remote_source",
    "is_url",
    "list_skill_files",
    "parse_skill",
    "plan_import",
    "read_frontmatter",
    "skills_root",
    "write_skills",
]
