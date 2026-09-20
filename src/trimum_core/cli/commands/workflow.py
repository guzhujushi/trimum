"""`trm workflow` command group — list/run/status/log/import.

``import`` 是 E4 的 workflow 入口（`docs/E4-PLAN.md` §2.4）：把一份 Warp 式目录 YAML
收进 ``<TRIMUM_HOME>/workflows/<id>/workflow.yaml``。导入只读文本、只写文本。
"""

from __future__ import annotations

import argparse
import asyncio
import json

from .._ask import ask_confirm
from .._utils import emit, fail


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("workflow", help="manage workflows")
    nested = parser.add_subparsers(dest="workflow_command", title="workflow commands")

    list_parser = nested.add_parser("list", help="list available workflows")
    list_parser.add_argument(
        "--root", default=None, help="workflow root (default <TRIMUM_HOME>/workflows)"
    )
    list_parser.set_defaults(handler=handler)

    import_parser = nested.add_parser(
        "import",
        help="import catalog YAML (a file, or a directory of them) into the workflow root",
    )
    import_parser.add_argument("source", help="catalog file, or a directory containing them")
    import_parser.add_argument(
        "--root", default=None, help="workflow root (default <TRIMUM_HOME>/workflows)"
    )
    import_parser.add_argument(
        "--trust",
        default="third-party",
        choices=["official", "curated", "third-party", "local"],
    )
    import_parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    import_parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    import_parser.add_argument("--force", action="store_true", help="overwrite an existing workflow")
    import_parser.set_defaults(handler=handler)

    run_parser = nested.add_parser("run", help="run a workflow")
    run_parser.add_argument("name")
    run_parser.add_argument("--input", dest="input_json", default=None, help="JSON context object")
    run_parser.set_defaults(handler=handler)

    status_parser = nested.add_parser("status", help="show workflow run status")
    status_parser.add_argument("run_id")
    status_parser.set_defaults(handler=handler)

    log_parser = nested.add_parser("log", help="show workflow run log")
    log_parser.add_argument("run_id")
    log_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm workflow {list,run,status,log,import} ...")
    return 0


def _load_workflows(root: str | None = None) -> list:
    from trimum_core.workflow_engine import WorkflowDefV2

    return WorkflowDefV2.load_from_dir(root)


def _find_workflow(name: str):
    for workflow in _load_workflows():
        if workflow.id == name or workflow.name == name:
            return workflow
    return None


def _workflow_dict(workflow) -> dict:
    model_dump = getattr(workflow, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
    }


def handler(args: argparse.Namespace) -> int:
    """Execute the requested workflow subcommand."""
    command = getattr(args, "workflow_command", None)

    if command == "list":
        workflows = [
            _workflow_dict(item) for item in _load_workflows(getattr(args, "root", None))
        ]
        emit(args, {"workflows": workflows, "count": len(workflows)})
        return 0

    if command == "import":
        return _handle_import(args)

    if command == "run":
        workflow = _find_workflow(args.name)
        if workflow is None:
            return fail(f"unknown workflow: {args.name}")

        context = {}
        if getattr(args, "input_json", None):
            try:
                parsed = json.loads(args.input_json)
                if isinstance(parsed, dict):
                    context = parsed
                else:
                    return fail("--input must be a JSON object")
            except json.JSONDecodeError as exc:
                return fail(f"invalid --input JSON: {exc}")

        try:
            from trimum_core.event_bus import EventBus
            from trimum_core.workflow_engine import WorkflowEngine

            definition = workflow.to_workflow_definition()
            engine = WorkflowEngine(EventBus())
            result = asyncio.run(engine.run(definition, context))
            data = {"workflow": _workflow_dict(workflow), "result": result.model_dump()}
            emit(args, data)
            return 0
        except Exception as exc:
            return fail(f"workflow run failed: {exc}")

    if command in {"status", "log"}:
        data = {
            "run_id": args.run_id,
            "status": "unknown",
            "message": "workflow run state is not persisted by the local CLI",
        }
        emit(args, data)
        return 0

    return _show_help(args)


def _handle_import(args: argparse.Namespace) -> int:
    """Import catalog YAML: plan → validate every file → confirm → write."""
    from trimum_core import workflow_catalog

    try:
        plan = workflow_catalog.plan_import(
            args.source, root=args.root, trust=args.trust
        )
    except workflow_catalog.CatalogError as exc:
        return fail(str(exc))

    importable = [item for item in plan["workflows"] if not item["problems"]]
    written: list[str] = []
    if not args.dry_run:
        if not importable:
            detail = "; ".join(
                f"{item.get('id') or item['path']}: {'; '.join(item['problems'])}"
                for item in plan["workflows"]
            )
            return fail(f"nothing importable: {detail}")
        if not args.yes:
            question = (
                f"import {len(importable)} workflow(s) into {plan['root']}"
                + (" (overwriting existing)" if args.force else "")
                + "?"
            )
            if not ask_confirm(question):
                return fail("aborted (use --yes for non-interactive runs)")
        try:
            written = workflow_catalog.write_workflows(plan, force=args.force)
        except workflow_catalog.ImportRefused as exc:
            return fail(str(exc))

    payload = {
        "dry_run": bool(args.dry_run),
        "source": plan["source"],
        "root": plan["root"],
        "files": plan["files"],
        "workflows": plan["workflows"],
        "importable": len(importable),
        "problems": plan["problems"],
        "written": written,
    }
    emit(args, payload, _human_import)
    return 0 if (importable or args.dry_run) else 1


def _human_import(data: dict) -> None:
    verb = "would import" if data["dry_run"] else "imported"
    print(f"{verb} {data['source']} -> {data['root']}")
    for item in data["workflows"]:
        label = item.get("id") or item["path"]
        if item["problems"]:
            print(f"  [skip] {label}")
            for problem in item["problems"]:
                print(f"         ! {problem}")
            continue
        entry = item["entry"]
        print(
            f"  [ok]   {label:<24} risk={entry['risk']:<8} "
            f"steps={entry['details']['steps']} requires={','.join(entry['requires']) or '-'}"
        )
        for warning in item["warnings"]:
            print(f"         - {warning}")
    for path in data["written"]:
        print(f"  wrote {path}")


__command_meta__ = {
    "workflow import": {
        "summary": "Import Warp-style catalog YAML into the workflow root",
        "args": "<file|dir> [--root DIR] [--trust T] [--dry-run] [--yes] [--force]",
        "examples": [
            "trm workflow import ./my-workflows --dry-run",
            "trm workflow import docker-cleanup.yaml --yes",
        ],
        "risk": "medium",
        "tags": ["workflow", "ecosystem"],
        "since": "0.6.0",
    },
    "workflow list": {
        "summary": "List workflows found in the workflow root",
        "args": "[--root DIR]",
        "examples": ["trm workflow list --json"],
        "risk": "low",
        "tags": ["workflow"],
        "since": "0.6.0",
    },
}


__all__ = ["add_subparsers", "handler"]
