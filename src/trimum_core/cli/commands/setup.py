"""`trm setup` — first-run wizard: hosts, identity, official certs, tools, skills.

trimum treats the developer toolchain as opt-in (``docs/ECOSYSTEM-STRATEGY.md``
§7.3): nothing is assumed to be installed, the wizard asks once, and the whole
run is safe to repeat.  ``--json`` makes the outcome machine-readable so an
installer or a parent agent can drive it without parsing prose.
"""

from __future__ import annotations

import argparse
import sys

from .._utils import emit, fail
from trimum_core.setup_wizard import (
    STEPS,
    load_catalog,
    run_setup,
)

__command_meta__ = {
    "setup": {
        "summary": "First-run wizard: detect hosts, create identity, certify official agents, pick tools, link skills",
        "args": (
            "[--dry-run] [--yes] [--tools a,b] [--all-hosts] "
            "[--max-risk inherit|low|medium|high] [--skip STEP] [--catalog PATH]"
        ),
        "examples": [
            "trm setup --dry-run",
            "trm setup --tools python,ripgrep",
            "trm setup --yes --json",
        ],
        "tags": ["setup", "identity", "skills", "hosts"],
        "risk": "low",
    },
}


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "setup",
        help="run the first-run wizard (hosts / identity / tools / skills)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would happen without writing anything",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="non-interactive: apply defaults instead of prompting",
    )
    parser.add_argument(
        "--tools",
        default="",
        metavar="a,b",
        help="opt-in toolchain entries to record (names from the catalog)",
    )
    parser.add_argument(
        "--all-hosts",
        action="store_true",
        help="target every known harness, not only the detected ones",
    )
    parser.add_argument(
        "--max-risk",
        choices=("inherit", "low", "medium", "high"),
        default="inherit",
        help="capability ceiling written into the self-signed identity",
    )
    parser.add_argument(
        "--force-identity",
        action="store_true",
        help="replace an existing identity key pair",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        choices=list(STEPS),
        metavar="STEP",
        help="skip a step (repeatable): " + ", ".join(STEPS),
    )
    parser.add_argument(
        "--catalog",
        default="",
        metavar="PATH",
        help="use an alternative toolchain catalog",
    )
    parser.set_defaults(handler=handler)


def _human(report: dict) -> None:
    prefix = "dry-run: " if report["dry_run"] else ""
    mode = "interactive" if report["interactive"] else "non-interactive"
    print(f"{prefix}trm setup ({mode})")

    hosts = report["steps"].get("hosts")
    if hosts:
        detected = ", ".join(hosts["detected"]) or "(none)"
        print(f"  hosts      : detected {detected}")
        print(f"  {'':<12} scan root {hosts['scan_home']}")
        for target in hosts["targets"]:
            print(f"  {'':<12} target    {target}")

    identity = report["steps"].get("identity")
    if identity:
        detail = identity.get("reason") or identity.get("path") or ""
        print(f"  identity   : {identity['status']}  {detail}")
        doc = identity.get("doc") or {}
        if doc.get("public_key_fingerprint"):
            print(f"  {'':<12} fingerprint {doc['public_key_fingerprint']}")
        if doc.get("capabilities"):
            caps = doc["capabilities"]
            print(
                f"  {'':<12} capabilities tools={caps['tools']} "
                f"max_risk={caps['max_risk']} scope={caps['scope']}"
            )

    official = report["steps"].get("official")
    if official:
        issued = ", ".join(official["issued"]) or "(none)"
        print(f"  official   : bundled {len(official['bundled'])} agent(s), issued {issued}")
        if official.get("existing"):
            print(f"  {'':<12} already certified {', '.join(official['existing'])}")

    toolchain = report["steps"].get("toolchain")
    if toolchain:
        selected = ", ".join(toolchain["selected"]) or "(none)"
        print(f"  toolchain  : selected {selected}")
        if toolchain["unknown"]:
            print(f"  {'':<12} unknown   {', '.join(toolchain['unknown'])}")
        print(f"  {'':<12} {toolchain['note']}")

    skills = report["steps"].get("skills")
    if skills:
        counts = ", ".join(
            f"{action}={count}" for action, count in sorted(skills["summary"].items())
        )
        print(f"  skills     : {skills['skills']} skill(s) -> {len(skills['targets'])} root(s)")
        print(f"  {'':<12} {counts or 'nothing to do'}")

    if report.get("state_written"):
        print(f"  state      : {report['state_path']}")
    if report.get("next"):
        print("  next       : " + "; ".join(report["next"]))


def handler(args: argparse.Namespace) -> int:
    """Run the wizard and report the outcome."""
    skip = set(getattr(args, "skip", []) or [])
    steps = tuple(step for step in STEPS if step not in skip)
    if not steps:
        return fail("all steps skipped — nothing to do")

    catalog = None
    custom = (getattr(args, "catalog", "") or "").strip()
    if custom:
        catalog = load_catalog(custom)
        if not catalog.get("loaded"):
            return fail(f"cannot read catalog: {custom}")

    report = run_setup(
        steps=steps,
        dry_run=bool(args.dry_run),
        # None → let the wizard follow the TTY, so a piped run never blocks
        interactive=False if args.yes else None,
        tools=args.tools,
        all_hosts=bool(args.all_hosts),
        max_risk=args.max_risk,
        force_identity=bool(args.force_identity),
        catalog=catalog,
    )
    emit(args, report, _human)

    unknown = (report["steps"].get("toolchain") or {}).get("unknown") or []
    if unknown:
        return fail(f"unknown toolchain entries: {', '.join(unknown)}")

    identity = report["steps"].get("identity") or {}
    if identity.get("status") == "skipped":
        print(f"[i] identity step skipped: {identity.get('reason', '')}", file=sys.stderr)
    return 0


__all__ = ["add_subparsers", "handler"]