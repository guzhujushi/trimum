"""`trm skill` command group — list / sync / paths / import.

Two layers are visible here and deliberately kept apart: Agent Skills
(``SKILL.md``) are distributed into other harnesses' skill roots, while
trimum's own executable skills (``skill.yaml``) are only reported.

``import`` is the E4 on-ramp (``docs/E4-PLAN.md``): fetch a skill from a local
directory or a git repo into ``<TRIMUM_HOME>/skills``.  Importing only reads and
copies text — nothing inside a skill is ever executed here.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .._ask import ask_confirm
from .._utils import emit, fail
from trimum_core.skill_sync import (
    LINK_MODES,
    default_source_roots,
    default_target_roots,
    discover_skills,
    is_link,
    link_destination,
    sync_skills,
)

__command_meta__ = {
    "skill": {
        "summary": "List and distribute trimum Agent Skills",
        "args": "{list,sync,paths}",
        "tags": ["skills", "agent"],
        "risk": "low",
    },
    "skill list": {
        "summary": "Show skills and where they are distributed",
        "args": "[--all] [--all-hosts]",
        "examples": ["trm skill list --json"],
        "tags": ["skills"],
        "risk": "low",
    },
    "skill sync": {
        "summary": "Link Agent Skills into the detected agent harness skill roots",
        "args": "[--dry-run] [--force] [--prune] [--mode M] [--all-hosts]",
        "examples": [
            "trm skill sync --dry-run",
            "trm skill sync",
        ],
        "tags": ["skills", "setup"],
        "risk": "low",
    },
    "skill paths": {
        "summary": "Show skill source and target roots",
        "args": "[--create] [--all-hosts]",
        "tags": ["skills"],
        "risk": "low",
    },
    "skill import": {
        "summary": "Import Agent Skills from a local directory or a git repo",
        "args": "<path|git-url> [--root DIR] [--trust T] [--dry-run] [--yes] [--force]",
        "examples": [
            "trm skill import ./skills --dry-run",
            "trm skill import git@github.com:me/skills.git --yes",
        ],
        "tags": ["skills", "ecosystem"],
        "risk": "medium",
        "since": "0.6.0",
    },
}


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("skill", help="list and distribute Agent Skills")
    nested = parser.add_subparsers(dest="skill_command", title="skill commands")

    list_parser = nested.add_parser("list", help="show skills and their distribution")
    list_parser.add_argument(
        "--all", action="store_true", help="include non-distributable skills"
    )
    list_parser.add_argument(
        "--source", action="append", default=[], metavar="DIR", help="extra source root"
    )
    list_parser.add_argument(
        "--target", action="append", default=[], metavar="DIR", help="target root override"
    )
    list_parser.add_argument(
        "--all-hosts",
        action="store_true",
        help="target every known harness, not only the detected ones",
    )
    list_parser.set_defaults(handler=handler)

    sync_parser = nested.add_parser(
        "sync", help="link Agent Skills into every agent harness skill root"
    )
    sync_parser.add_argument(
        "--dry-run", action="store_true", help="report actions without touching the disk"
    )
    sync_parser.add_argument(
        "--force", action="store_true", help="replace conflicting entries"
    )
    sync_parser.add_argument(
        "--prune", action="store_true", help="remove links whose source disappeared"
    )
    sync_parser.add_argument(
        "--mode", choices=LINK_MODES, default="auto", help="link strategy (default: auto)"
    )
    sync_parser.add_argument(
        "--source", action="append", default=[], metavar="DIR", help="extra source root"
    )
    sync_parser.add_argument(
        "--target", action="append", default=[], metavar="DIR", help="target root override"
    )
    sync_parser.add_argument(
        "--all-hosts",
        action="store_true",
        help="target every known harness, not only the detected ones",
    )
    sync_parser.set_defaults(handler=handler)

    import_parser = nested.add_parser(
        "import",
        help="copy Agent Skills from a local directory or git repo into the skill root",
    )
    import_parser.add_argument("source", help="skill directory, a directory of them, or a git URL")
    import_parser.add_argument(
        "--root", default=None, help="skill root (default <TRIMUM_HOME>/skills)"
    )
    import_parser.add_argument(
        "--trust",
        default="third-party",
        choices=["official", "curated", "third-party", "local"],
    )
    import_parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    import_parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    import_parser.add_argument("--force", action="store_true", help="overwrite an existing skill")
    import_parser.set_defaults(handler=handler)

    paths_parser = nested.add_parser("paths", help="show skill source and target roots")
    paths_parser.add_argument(
        "--create", action="store_true", help="create missing target roots"
    )
    paths_parser.add_argument(
        "--target", action="append", default=[], metavar="DIR", help="target root override"
    )
    paths_parser.add_argument(
        "--all-hosts",
        action="store_true",
        help="target every known harness, not only the detected ones",
    )
    paths_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm skill {list,sync,paths,import} ...")
    return 0


def _source_roots(args: argparse.Namespace) -> list[Path]:
    roots = default_source_roots()
    roots.extend(Path(item).expanduser() for item in getattr(args, "source", []))
    return roots


def _target_roots(args: argparse.Namespace) -> list[Path]:
    override = getattr(args, "target", [])
    if override:
        return [Path(item).expanduser() for item in override]
    return default_target_roots(all_hosts=bool(getattr(args, "all_hosts", False)))


def _target_state(entry, root: Path) -> str:
    destination = root / entry.name
    if is_link(destination):
        return "linked" if link_destination(destination) == entry.path else "conflict"
    if destination.exists():
        return "conflict"
    return "missing"


def _collect_list_data(args: argparse.Namespace) -> dict:
    sources = _source_roots(args)
    targets = _target_roots(args)
    entries = discover_skills(sources)
    show_all = getattr(args, "all", False)

    skills = []
    for entry in entries:
        if not show_all and not entry.distributable:
            continue
        data = entry.to_dict()
        data["targets"] = {str(root): _target_state(entry, root) for root in targets}
        data["distributed"] = sum(
            1 for state in data["targets"].values() if state == "linked"
        )
        skills.append(data)

    return {
        "sources": [
            {"path": str(root), "exists": root.is_dir()} for root in sources
        ],
        "targets": [
            {"path": str(root), "exists": root.is_dir()} for root in targets
        ],
        "skills": skills,
        "distributable": sum(1 for item in skills if item["distributable"]),
    }


def _human_roots(data: dict) -> None:
    print("skill sources:")
    for item in data["sources"]:
        mark = "ok" if item["exists"] else "missing"
        print(f"  [{mark}] {item['path']}")
    print("target roots:")
    for item in data["targets"]:
        mark = "ok" if item["exists"] else "missing"
        print(f"  [{mark}] {item['path']}")


def _human_list(data: dict) -> None:
    roots = ", ".join(item["path"] for item in data["sources"] if item["exists"])
    print(f"skill sources: {roots or '(none found)'}")
    print(f"target roots : {len(data['targets'])}")
    for item in data["skills"]:
        if item["distributable"]:
            state = f"linked in {item['distributed']}/{len(item['targets'])} roots"
        else:
            state = "not distributed (skill.yaml only)"
        description = f" - {item['description']}" if item["description"] else ""
        print(f"  {item['name']:<24} [{item['kind']}] {state}{description}")
        print(f"  {'':<24} {item['path']}")


def _human_sync(data: dict) -> None:
    for item in data["results"]:
        detail = f"  ({item['detail']})" if item["detail"] else ""
        print(
            f"  {item['action']:<16}{item['skill']:<24}"
            f"{item['path']}{detail}"
        )
    counts = ", ".join(
        f"{action}={count}" for action, count in sorted(data["summary"].items())
    )
    prefix = "dry-run: " if data["dry_run"] else ""
    print(f"{prefix}{counts or 'nothing to do'}")


def _handle_import(args: argparse.Namespace) -> int:
    """Import skills: plan (cloning if needed) → validate → confirm → copy."""
    from trimum_core import skill_import

    try:
        plan = skill_import.plan_import(
            args.source, root=args.root, trust=args.trust
        )
    except skill_import.SkillImportError as exc:
        return fail(str(exc))

    try:
        importable = [item for item in plan["skills"] if not item["problems"]]
        copied: list[str] = []
        if not args.dry_run:
            if not importable:
                detail = "; ".join(
                    f"{item.get('name') or item['path']}: {'; '.join(item['problems'])}"
                    for item in plan["skills"]
                )
                return fail(f"nothing importable: {detail}")
            if not args.yes:
                question = (
                    f"import {len(importable)} skill(s) into {plan['root']}"
                    + (" (overwriting existing)" if args.force else "")
                    + "?"
                )
                if not ask_confirm(question):
                    return fail("aborted (use --yes for non-interactive runs)")
            try:
                copied = skill_import.write_skills(plan, force=args.force)
            except skill_import.ImportRefused as exc:
                return fail(str(exc))

        payload = {
            "dry_run": bool(args.dry_run),
            "source": plan["source"],
            "origin": plan["origin"],
            "root": plan["root"],
            "skills": plan["skills"],
            "problems": plan["problems"],
            "importable": len(importable),
            "installed": copied,
        }
        emit(args, payload, _human_import)
        return 0
    finally:
        skill_import.cleanup(plan)


def _human_import(data: dict) -> None:
    verb = "would import" if data["dry_run"] else "imported"
    print(f"{verb} {data['source']} ({data['origin']}) -> {data['root']}")
    for item in data["skills"]:
        label = item.get("name") or item["path"]
        if item["problems"]:
            print(f"  [skip] {label}")
            for problem in item["problems"]:
                print(f"         ! {problem}")
            continue
        print(f"  [ok]   {label:<24} files={len(item['files'])} kind={item['kind']}")
        for warning in item["warnings"]:
            print(f"         - {warning}")
    for path in data["installed"]:
        print(f"  wrote {path}")


def handler(args: argparse.Namespace) -> int:
    """Execute the requested skill subcommand."""
    command = getattr(args, "skill_command", None)

    if command == "import":
        return _handle_import(args)

    if command == "list":
        emit(args, _collect_list_data(args), _human_list)
        return 0

    if command == "paths":
        targets = _target_roots(args)
        if getattr(args, "create", False):
            for root in targets:
                try:
                    root.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    return fail(f"cannot create {root}: {exc}")
        payload = {
            "sources": [
                {"path": str(root), "exists": root.is_dir()}
                for root in _source_roots(args)
            ],
            "targets": [
                {"path": str(root), "exists": root.is_dir()} for root in targets
            ],
        }
        emit(args, payload, _human_roots)
        return 0

    if command == "sync":
        entries = discover_skills(_source_roots(args))
        targets = _target_roots(args)
        results = sync_skills(
            entries,
            targets,
            mode=args.mode,
            dry_run=args.dry_run,
            force=args.force,
            prune=args.prune,
        )
        summary: dict[str, int] = {}
        for result in results:
            summary[result.action] = summary.get(result.action, 0) + 1
        payload = {
            "dry_run": bool(args.dry_run),
            "mode": args.mode,
            "results": [result.to_dict() for result in results],
            "summary": summary,
        }
        emit(args, payload, _human_sync)
        return 1 if any(result.action == "error" for result in results) else 0

    return _show_help(args)


__all__ = ["add_subparsers", "handler"]
