"""Agent Skills distribution — link one skill source into every agent harness.

trimum keeps two skill layers apart on purpose:

* **Agent Skills** (``<skill>/SKILL.md``) — the open standard that Claude Code,
  Codex, Gemini CLI, Cursor and friends read.  Zero runtime cost; distributed by
  linking the skill directory into each harness skill root.
* **trimum skills** (``<skill>/skill.yaml``) — executable step compositions run
  by :mod:`trimum_core.skill_executor`.  These are *not* distributed.

The distribution model follows Omarchy: one source of truth, symlinked into
``~/.agents/skills``, ``~/.claude/skills``, ``~/.codex/skills`` and friends,

Targets are *detected*, never assumed: the toolchain is opt-in, so trimum only
links into harnesses that exist on this machine (see :mod:`trimum_core.hosts`);
``~/.trimum/agent-skills`` is always a target, so a machine with no third-party
agent at all still gets a working skill root.  ``TRIMUM_SKILL_TARGETS`` overrides
the whole list, ``all_hosts=True`` restores the pre-provisioning behaviour.
with a junction/copy fallback on Windows where symlinks need extra privileges.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from . import hosts as hosts_mod
from pathlib import Path

AGENT_SKILL_FILE = "SKILL.md"
TRIMUM_SKILL_FILE = "skill.yaml"

#: Environment overrides, handy for tests and for non-standard layouts.
SOURCE_ENV = "TRIMUM_SKILLS_DIR"
TARGET_ENV = "TRIMUM_SKILL_TARGETS"

LINK_MODES = ("auto", "symlink", "junction", "copy")


@dataclass(frozen=True)
class SkillEntry:
    """A skill directory discovered in one of the source roots."""

    name: str
    path: Path
    source_root: Path
    kind: str = "agent-skill"
    description: str = ""

    @property
    def distributable(self) -> bool:
        return self.kind == "agent-skill"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "source_root": str(self.source_root),
            "kind": self.kind,
            "description": self.description,
            "distributable": self.distributable,
        }


@dataclass(frozen=True)
class SkillSyncResult:
    """Outcome of one (skill, target root) pair."""

    skill: str
    target_root: Path
    path: Path
    action: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "target_root": str(self.target_root),
            "path": str(self.path),
            "action": self.action,
            "detail": self.detail,
        }


def default_source_roots() -> list[Path]:
    """Return the skill source roots, most specific first.

    The first root is the trimum data root (``<TRIMUM_HOME>/skills``), which is
    also where :mod:`trimum_core.skill_import` puts imported skills —— two code
    paths resolving the root differently would mean "imported but invisible".
    """
    from .paths import trimum_path

    roots = [trimum_path("skills")]
    override = os.environ.get(SOURCE_ENV)
    if override:
        roots.append(Path(override).expanduser())
    # Source checkout layout: <repo>/skills
    roots.append(Path(__file__).resolve().parents[2] / "skills")
    return roots


def default_target_roots(*, all_hosts: bool = False) -> list[Path]:
    """Return the agent harness skill roots to distribute into.

    With *all_hosts* false (the default) only harnesses actually present on this
    machine are targeted; trimum's own root is always appended so a bare install
    still has somewhere to put its skills.
    """
    override = os.environ.get(TARGET_ENV)
    if override:
        return [
            Path(part).expanduser()
            for part in override.split(os.pathsep)
            if part.strip()
        ]

    if all_hosts:
        return hosts_mod.all_skill_targets()
    return hosts_mod.detected_skill_targets()


def read_agent_skill(skill_dir: Path) -> dict[str, str]:
    """Return the YAML frontmatter of a skill's ``SKILL.md``."""
    try:
        text = (Path(skill_dir) / AGENT_SKILL_FILE).read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.lstrip().startswith("---"):
        return {}

    _, _, remainder = text.lstrip().partition("---")
    frontmatter, _, _ = remainder.partition("---")
    try:
        import yaml

        data = yaml.safe_load(frontmatter) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in data.items()
        if isinstance(value, (str, int, float))
    }


def discover_skills(source_roots: list[Path] | None = None) -> list[SkillEntry]:
    """Collect skills from every source root (first root wins on name clash)."""
    roots = list(source_roots) if source_roots else default_source_roots()
    found: dict[str, SkillEntry] = {}

    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            has_agent_skill = (child / AGENT_SKILL_FILE).is_file()
            has_trimum_skill = (child / TRIMUM_SKILL_FILE).is_file()
            if not (has_agent_skill or has_trimum_skill):
                continue

            meta = read_agent_skill(child) if has_agent_skill else {}
            entry = SkillEntry(
                name=str(meta.get("name") or child.name),
                path=child.resolve(),
                source_root=root.resolve(),
                kind="agent-skill" if has_agent_skill else "trimum-skill",
                description=str(meta.get("description") or ""),
            )
            found.setdefault(entry.name, entry)

    return [found[name] for name in sorted(found)]


def is_link(path: Path) -> bool:
    """Return whether *path* is a symlink or (on Windows) a junction."""
    path = Path(path)
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def link_destination(path: Path) -> Path | None:
    """Return what a link points at, or ``None`` when it is not a link."""
    if not is_link(path):
        return None
    try:
        return Path(path).resolve()
    except OSError:
        return None


def _remove_link(path: Path) -> None:
    """Remove a link without touching the directory it points at."""
    try:
        Path(path).unlink()
    except (OSError, IsADirectoryError):
        os.rmdir(path)  # junctions and other directory reparse points


def _create_link(source: Path, destination: Path, mode: str) -> tuple[str, str]:
    """Create the distribution entry; return ``(action, detail)``."""
    notes: list[str] = []

    if mode in {"auto", "symlink"}:
        try:
            os.symlink(source, destination, target_is_directory=True)
            return "linked", ""
        except (OSError, NotImplementedError) as exc:
            notes.append(f"symlink unavailable ({exc.__class__.__name__})")
            if mode == "symlink" or os.name != "nt":
                return "error", "; ".join(notes)

    if mode in {"auto", "junction"} and os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(destination), str(source)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            notes.append("junction")
            return "junction", "; ".join(notes)
        notes.append("junction failed")

    if mode in {"auto", "copy"}:
        shutil.copytree(source, destination)
        notes.append("copied")
        return "copied", "; ".join(notes)

    return "error", "; ".join(notes) or f"mode {mode!r} is not applicable"


def link_skill(
    entry: SkillEntry,
    target_root: Path,
    *,
    mode: str = "auto",
    dry_run: bool = False,
    force: bool = False,
) -> SkillSyncResult:
    """Distribute one skill into one target root."""
    target_root = Path(target_root).expanduser()
    destination = target_root / entry.name

    if not entry.distributable:
        return SkillSyncResult(
            entry.name, target_root, destination, "skipped", "not an Agent Skill"
        )

    if is_link(destination):
        current = link_destination(destination)
        if current is not None and current == entry.path:
            return SkillSyncResult(entry.name, target_root, destination, "unchanged")
        if not force:
            return SkillSyncResult(
                entry.name,
                target_root,
                destination,
                "conflict",
                f"link points at {current}",
            )
        if dry_run:
            return SkillSyncResult(entry.name, target_root, destination, "planned")
        _remove_link(destination)
    elif destination.exists():
        if not force:
            return SkillSyncResult(
                entry.name, target_root, destination, "conflict", "path already exists"
            )
        if dry_run:
            return SkillSyncResult(entry.name, target_root, destination, "planned")
        if destination.is_dir() and not is_link(destination):
            shutil.rmtree(destination)
        else:
            destination.unlink()

    if dry_run:
        return SkillSyncResult(entry.name, target_root, destination, "planned")

    try:
        target_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return SkillSyncResult(
            entry.name, target_root, destination, "error", f"mkdir failed: {exc}"
        )

    action, detail = _create_link(entry.path, destination, mode)
    return SkillSyncResult(entry.name, target_root, destination, action, detail)


def sync_skills(
    entries: list[SkillEntry],
    target_roots: list[Path],
    *,
    mode: str = "auto",
    dry_run: bool = False,
    force: bool = False,
    prune: bool = False,
) -> list[SkillSyncResult]:
    """Distribute every skill into every target root, optionally pruning first."""
    results: list[SkillSyncResult] = []

    if prune:
        source_roots = sorted({entry.source_root for entry in entries})
        results.extend(prune_skills(target_roots, source_roots, dry_run=dry_run))

    for entry in entries:
        if not entry.distributable:
            continue
        for root in target_roots:
            results.append(
                link_skill(entry, root, mode=mode, dry_run=dry_run, force=force)
            )
    return results


def prune_skills(
    target_roots: list[Path],
    source_roots: list[Path],
    *,
    dry_run: bool = False,
) -> list[SkillSyncResult]:
    """Remove links in target roots whose source disappeared or moved away."""
    results: list[SkillSyncResult] = []
    sources = [Path(root).expanduser().resolve() for root in source_roots]

    for root in target_roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not is_link(child):
                continue
            current = link_destination(child)
            stale = current is None or not current.exists()
            if not stale and sources:
                stale = not any(
                    current == source / child.name for source in sources
                )
            if not stale:
                continue
            if dry_run:
                results.append(
                    SkillSyncResult(child.name, root, child, "planned-remove")
                )
                continue
            _remove_link(child)
            results.append(SkillSyncResult(child.name, root, child, "removed"))
    return results


__all__ = [
    "AGENT_SKILL_FILE",
    "TRIMUM_SKILL_FILE",
    "LINK_MODES",
    "SkillEntry",
    "SkillSyncResult",
    "default_source_roots",
    "default_target_roots",
    "discover_skills",
    "is_link",
    "link_destination",
    "link_skill",
    "prune_skills",
    "read_agent_skill",
    "sync_skills",
]
