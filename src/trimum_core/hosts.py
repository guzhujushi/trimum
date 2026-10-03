"""Host (agent harness) detection — what this machine actually has installed.

trimum deliberately assumes *nothing* about third-party coding agents: the
developer toolchain is opt-in, the first-run wizard asks, and a trimum coding
agent may replace them altogether (see ``docs/ECOSYSTEM-STRATEGY.md`` §7.3).
Everything trimum distributes *into* another harness — Agent Skills today,
rules and hooks later — therefore resolves its targets from detection instead
of a hardcoded list.

Signals, in order of precedence:

* ``TRIMUM_HOSTS`` / ``TRIMUM_HOSTS_DISABLE`` — explicit comma separated lists
  (tests, CI, provisioning); they add or remove hosts without touching disk;
* the host config directory exists (``~/.claude`` …);
* the host CLI resolves on ``PATH`` (``claude`` …).

``TRIMUM_HOSTS_HOME`` redirects the directory scan, which keeps test runs and
image builds away from the real home directory.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .paths import trimum_path

HOSTS_ENV = "TRIMUM_HOSTS"
HOSTS_DISABLE_ENV = "TRIMUM_HOSTS_DISABLE"
SCAN_HOME_ENV = "TRIMUM_HOSTS_HOME"

#: Directory trimum always owns, even when no third-party host is installed.
OWN_SKILLS_DIRNAME = "agent-skills"


@dataclass(frozen=True)
class HostSpec:
    """A known agent harness that can consume trimum-distributed content."""

    name: str
    label: str
    config_dir: str
    skills_subdir: str = "skills"
    cli_names: tuple[str, ...] = ()

    @property
    def skills_relpath(self) -> str:
        return f"{self.config_dir}/{self.skills_subdir}"

    def skills_dir(self, home: Path) -> Path:
        return Path(home) / self.config_dir / self.skills_subdir

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "config_dir": self.config_dir,
            "skills_relpath": self.skills_relpath,
            "cli_names": list(self.cli_names),
        }


#: Order is intentional: the six original Omarchy-style targets first, then the
#: wider set of ECC-style harnesses.  Output order stays deterministic.
KNOWN_HOSTS: tuple[HostSpec, ...] = (
    HostSpec("agents", "Agent Skills (shared)", ".agents"),
    HostSpec("claude", "Claude Code", ".claude", cli_names=("claude",)),
    HostSpec("codex", "Codex", ".codex", cli_names=("codex",)),
    HostSpec("pi", "Pi", ".pi", skills_subdir="agent/skills"),
    HostSpec(
        "gemini",
        "Gemini CLI",
        ".gemini",
        skills_subdir="config/skills",
        cli_names=("gemini",),
    ),
    HostSpec("hermes", "Hermes", ".hermes"),
    HostSpec("cursor", "Cursor", ".cursor", cli_names=("cursor",)),
    HostSpec("opencode", "OpenCode", ".opencode", cli_names=("opencode",)),
    HostSpec("kimi", "Kimi", ".kimi", cli_names=("kimi",)),
    HostSpec("qwen", "Qwen Code", ".qwen", cli_names=("qwen",)),
    HostSpec("zed", "Zed", ".zed", cli_names=("zed",)),
    HostSpec("kiro", "Kiro", ".kiro"),
    HostSpec("trae", "Trae", ".trae"),
    HostSpec("openclaw", "OpenClaw", ".openclaw"),
)


@dataclass(frozen=True)
class HostStatus:
    """Detection outcome for one known host."""

    spec: HostSpec
    present: bool
    evidence: tuple[str, ...]
    skills_dir: Path

    @property
    def name(self) -> str:
        return self.spec.name

    def to_dict(self) -> dict:
        data = self.spec.to_dict()
        data.update(
            {
                "present": self.present,
                "evidence": list(self.evidence),
                "skills_dir": str(self.skills_dir),
            }
        )
        return data


def scan_home() -> Path:
    """Return the directory scanned for host config dirs."""
    override = os.environ.get(SCAN_HOME_ENV)
    if override and override.strip():
        return Path(override).expanduser()
    return Path.home()


def known_hosts() -> tuple[HostSpec, ...]:
    """Return every host trimum knows how to distribute into."""
    return KNOWN_HOSTS


def host_by_name(name: str) -> HostSpec | None:
    """Return the spec for *name* (case insensitive), if known."""
    wanted = (name or "").strip().lower()
    for spec in KNOWN_HOSTS:
        if spec.name == wanted:
            return spec
    return None



def detect_hosts(
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    which=None,
) -> list[HostStatus]:
    """Detect which known hosts are installed on this machine.

    *home* is the directory holding host config dirs (defaults to
    :func:`scan_home`), *which* resolves an executable name (defaults to
    :func:`shutil.which`).
    """
    if env is None:
        env = dict(os.environ)
    home = Path(home) if home is not None else scan_home()
    which = shutil.which if which is None else which

    forced = _env_names_from(env, HOSTS_ENV)
    disabled = _env_names_from(env, HOSTS_DISABLE_ENV)

    statuses: list[HostStatus] = []
    for spec in KNOWN_HOSTS:
        skills_dir = spec.skills_dir(home)
        evidence: list[str] = []

        if spec.name in forced:
            evidence.append(f"env:{HOSTS_ENV}")
        if (home / spec.config_dir).is_dir():
            evidence.append(f"dir:{spec.config_dir}")
        for cli in spec.cli_names:
            found = which(cli)
            if found:
                evidence.append(f"cli:{cli}")
                break

        present = bool(evidence) and spec.name not in disabled
        statuses.append(
            HostStatus(
                spec=spec,
                present=present,
                evidence=tuple(evidence),
                skills_dir=skills_dir,
            )
        )
    return statuses


def _env_names_from(env: dict, variable: str) -> set[str]:
    raw = env.get(variable, "") or ""
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def own_skills_dir() -> Path:
    """Return trimum's own skill root (always a valid target)."""
    return trimum_path(OWN_SKILLS_DIRNAME)


def detected_skill_targets(
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    which=None,
    include_own: bool = True,
) -> list[Path]:
    """Return skill roots of *present* hosts, plus trimum's own root."""
    targets = [
        status.skills_dir
        for status in detect_hosts(home=home, env=env, which=which)
        if status.present
    ]
    if include_own:
        targets.append(own_skills_dir())
    return targets


def all_skill_targets(*, home: Path | None = None, include_own: bool = True) -> list[Path]:
    """Return skill roots of every known host (pre-provisioning mode)."""
    home = Path(home) if home is not None else scan_home()
    targets = [spec.skills_dir(home) for spec in KNOWN_HOSTS]
    if include_own:
        targets.append(own_skills_dir())
    return targets


def summarize(statuses: list[HostStatus]) -> dict:
    """Compact machine-readable detection summary."""
    return {
        "scan_home": str(scan_home()),
        "detected": [item.name for item in statuses if item.present],
        "absent": [item.name for item in statuses if not item.present],
        "hosts": [item.to_dict() for item in statuses],
    }


__all__ = [
    "HOSTS_ENV",
    "HOSTS_DISABLE_ENV",
    "SCAN_HOME_ENV",
    "OWN_SKILLS_DIRNAME",
    "HostSpec",
    "HostStatus",
    "KNOWN_HOSTS",
    "scan_home",
    "known_hosts",
    "host_by_name",
    "detect_hosts",
    "detected_skill_targets",
    "all_skill_targets",
    "own_skills_dir",
    "summarize",
]