"""First-run setup wizard — hosts, identity, optional toolchain, skill links.

The wizard exists because trimum assumes **nothing** is installed (see
``docs/ECOSYSTEM-STRATEGY.md`` §7.3): the developer toolchain is opt-in, the
first run asks, and the project may ship its own coding agent later.  Every
step is independent and idempotent, and the wizard never installs anything by
itself — tool selections are recorded here and handed to the package-manager
layer (E3) later.

Steps
-----
``hosts``
    Detect which agent harnesses exist; that result decides where Agent Skills
    are distributed (no more hardcoded target list).
``identity``
    Generate the per-user Ed25519 key pair and self-signed identity document
    (:mod:`trimum_core.identity`).  Skipped when ``cryptography`` is missing.
``toolchain``
    Show the opt-in catalog (``config/setup-catalog.yaml``), ask which entries
    the user wants, and record the answer.  Nothing is installed here.
``skills``
    Link trimum's Agent Skills into the detected hosts (plus trimum's own root).

Non-interactive invocation (no TTY, or ``--yes``) never prompts: it applies the
defaults (nothing selected, identity created, skills linked) and reports what
was skipped.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import hosts as hosts_mod
from . import identity as identity_mod
from .paths import ensure_trimum_home, trimum_path
from .skill_sync import (
    default_source_roots,
    discover_skills,
    sync_skills,
)

STEPS = ("hosts", "identity", "toolchain", "skills")

#: Repository-relative catalog; the curated opt-in toolchain lives in-repo so it
#: is versioned together with the wizard that reads it.
CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "setup-catalog.yaml"

STATE_DIRNAME = "config"
STATE_FILENAME = "setup.json5"
STATE_SCHEMA = "trimum.setup/v1"


def catalog_path() -> Path:
    """Return the path of the opt-in toolchain catalog."""
    return CATALOG_PATH


def state_path() -> Path:
    """Return the path of the wizard state file."""
    return trimum_path(STATE_DIRNAME, STATE_FILENAME)


def load_catalog(path: Path | None = None) -> dict:
    """Load the toolchain catalog (returns an empty catalog when missing)."""
    target = Path(path) if path is not None else catalog_path()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return {"version": 0, "groups": [], "path": str(target), "loaded": False}

    import yaml

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("groups", [])
    data["path"] = str(target)
    data["loaded"] = True
    return data


def catalog_entries(catalog: dict) -> list[dict]:
    """Flatten the catalog into entries carrying their group id/label."""
    entries: list[dict] = []
    for group in catalog.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for entry in group.get("entries") or []:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            item = dict(entry)
            item["group"] = group.get("id", "")
            item["group_label"] = group.get("label", "")
            entries.append(item)
    return entries


def find_entry(catalog: dict, name: str) -> dict | None:
    """Return the catalog entry called *name*, if present."""
    wanted = (name or "").strip().lower()
    for entry in catalog_entries(catalog):
        if str(entry["name"]).lower() == wanted:
            return entry
    return None


def resolve_tools(catalog: dict, names) -> tuple[list[dict], list[str]]:
    """Split *names* into known catalog entries and unknown names."""
    selected: list[dict] = []
    unknown: list[str] = []
    for raw in names:
        name = str(raw).strip()
        if not name:
            continue
        entry = find_entry(catalog, name)
        if entry is None:
            unknown.append(name)
        else:
            selected.append(entry)
    return selected, unknown


def parse_tool_names(value: str) -> list[str]:
    """Parse a ``--tools a,b`` style string into names."""
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def render_catalog(catalog: dict) -> str:
    """Render the catalog as an indented list for the interactive prompt."""
    lines: list[str] = []
    index = 0
    for group in catalog.get("groups") or []:
        if not isinstance(group, dict):
            continue
        lines.append(f"  {group.get('label', group.get('id', '?'))}")
        for entry in group.get("entries") or []:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            index += 1
            note = f" - {entry['note']}" if entry.get("note") else ""
            lines.append(f"    [{index:>2}] {entry['name']:<14}{entry.get('label', '')}{note}")
    return "\n".join(lines)


def prompt_tools(catalog: dict, input_fn=input) -> tuple[list[dict], str]:
    """Interactively pick catalog entries by number.

    Returns ``(selected_entries, raw_answer)``.  EOF / Ctrl-C is treated as
    "select nothing" so the wizard can never hang a scripted run.
    """
    entries = catalog_entries(catalog)
    if not entries:
        return [], ""

    print("可选装的工具链（全部为选装，回车跳过 = 一个都不装）：")
    print(render_catalog(catalog))
    try:
        answer = input_fn("  要装哪些？输入编号，逗号分隔: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return [], ""

    selected: list[dict] = []
    for chunk in answer.replace(" ", ",").split(","):
        if not chunk.strip().isdigit():
            continue
        position = int(chunk.strip())
        if 1 <= position <= len(entries):
            selected.append(entries[position - 1])
    return selected, answer


def _step_hosts(*, home: Path | None, all_hosts: bool, which=None) -> dict:
    statuses = hosts_mod.detect_hosts(home=home, which=which)
    targets = (
        hosts_mod.all_skill_targets(home=home)
        if all_hosts
        else hosts_mod.detected_skill_targets(home=home, which=which)
    )
    data = hosts_mod.summarize(statuses)
    data["all_hosts"] = all_hosts
    data["targets"] = [str(item) for item in targets]
    return data


def _step_identity(*, max_risk: str, dry_run: bool, force: bool) -> dict:
    # Only lay down the data tree when the identity can actually be written; a
    # missing crypto backend must not leave a half-initialised root behind.
    if identity_mod.crypto_available() and not dry_run:
        ensure_trimum_home()
    return identity_mod.generate_identity(max_risk=max_risk, force=force, dry_run=dry_run)


def _step_toolchain(
    *,
    tools: str,
    interactive: bool,
    dry_run: bool,
    catalog: dict,
    input_fn=input,
) -> dict:
    preset = parse_tool_names(tools)
    selected: list[dict] = []
    unknown: list[str] = []
    source = "none"

    if preset:
        selected, unknown = resolve_tools(catalog, preset)
        source = "flag"
    elif interactive and not dry_run:
        selected, _answer = prompt_tools(catalog, input_fn=input_fn)
        source = "prompt"

    available_entries = catalog_entries(catalog)
    payload = {
        "catalog": str(catalog.get("path", "")),
        "catalog_loaded": bool(catalog.get("loaded")),
        "available": [entry["name"] for entry in available_entries],
        "selected": [entry["name"] for entry in selected],
        "unknown": unknown,
        "selection_source": source,
        "install": "deferred",
        "note": (
            "本轮只登记选择；实际安装由系统包管理器完成（E3 的 trm env install）。"
            "trimum 不自建包仓库，也不默认安装任何工具。"
        ),
    }
    if interactive and dry_run:
        payload["note"] = "dry-run：未提示、未登记任何选择。" + payload["note"]
    elif not interactive and not preset:
        payload["note"] = (
            "非交互模式：默认不选择任何工具。"
            "需要选装时用 trm setup --tools python,node 或交互式运行。"
        )
    return payload


def _step_skills(
    *, dry_run: bool, all_hosts: bool, home: Path | None, which=None
) -> dict:
    entries = discover_skills(default_source_roots())
    targets = (
        hosts_mod.all_skill_targets(home=home)
        if all_hosts
        else hosts_mod.detected_skill_targets(home=home, which=which)
    )
    distributable = [entry for entry in entries if entry.distributable]
    results = sync_skills(distributable, targets, dry_run=dry_run)
    summary: dict[str, int] = {}
    for result in results:
        summary[result.action] = summary.get(result.action, 0) + 1
    return {
        "dry_run": dry_run,
        "skills": len(distributable),
        "targets": [str(item) for item in targets],
        "summary": summary,
        "results": [result.to_dict() for result in results],
    }


def write_state(payload: dict) -> Path:
    """Persist the wizard outcome to ``~/.trimum/config/setup.json5``."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def run_setup(
    *,
    steps: tuple[str, ...] = STEPS,
    dry_run: bool = False,
    interactive: bool | None = None,
    tools: str = "",
    all_hosts: bool = False,
    max_risk: str = "inherit",
    force_identity: bool = False,
    catalog: dict | None = None,
    home: Path | None = None,
    which=None,
    input_fn=input,
) -> dict:
    """Run the requested wizard steps and return a machine-readable report.

    *which* overrides executable lookup during host detection (tests inject an
    empty resolver to keep a run independent of what is on ``PATH``).
    """
    unknown_steps = [name for name in steps if name not in STEPS]
    if unknown_steps:
        raise ValueError(f"unknown setup steps: {', '.join(unknown_steps)}")

    if interactive is None:
        interactive = sys.stdin.isatty()

    catalog = catalog if catalog is not None else load_catalog()
    report: dict = {
        "schema": STATE_SCHEMA,
        "dry_run": dry_run,
        "interactive": bool(interactive),
        "steps_run": list(steps),
        "steps": {},
    }

    if "hosts" in steps:
        report["steps"]["hosts"] = _step_hosts(
            home=home, all_hosts=all_hosts, which=which
        )
    if "identity" in steps:
        report["steps"]["identity"] = _step_identity(
            max_risk=max_risk, dry_run=dry_run, force=force_identity
        )
    if "toolchain" in steps:
        report["steps"]["toolchain"] = _step_toolchain(
            tools=tools,
            interactive=bool(interactive),
            dry_run=dry_run,
            catalog=catalog,
            input_fn=input_fn,
        )
    if "skills" in steps:
        report["steps"]["skills"] = _step_skills(
            dry_run=dry_run, all_hosts=all_hosts, home=home, which=which
        )

    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["next"] = [
        "trm skill sync --dry-run",
        "trm commands --json",
        "trm doctor",
    ]

    if dry_run:
        report["state_path"] = ""
        report["state_written"] = False
    else:
        # The state file records the run itself, so it is written last and keeps
        # only the *outcome* (its own path included) - never the write bookkeeping.
        report["state_path"] = str(state_path())
        write_state(report)
        report["state_written"] = True

    return report


__all__ = [
    "STEPS",
    "CATALOG_PATH",
    "STATE_SCHEMA",
    "catalog_path",
    "state_path",
    "load_catalog",
    "catalog_entries",
    "find_entry",
    "resolve_tools",
    "parse_tool_names",
    "render_catalog",
    "prompt_tools",
    "write_state",
    "run_setup",
]