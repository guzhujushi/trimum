"""`trm workflow` command group — list/run/status/log."""

from __future__ import annotations

import argparse
import asyncio
import json

from .._utils import emit, fail


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("workflow", help="manage workflows")
    nested = parser.add_subparsers(dest="workflow_command", title="workflow commands")

    list_parser = nested.add_parser("list", help="list available workflows")
    list_parser.set_defaults(handler=handler)

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
    print("usage: trm workflow {list,run,status,log} ...")
    return 0


def _load_workflows() -> list:
    from trimum_core.workflow_engine import WorkflowDefV2

    return WorkflowDefV2.load_from_dir()


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
        workflows = [_workflow_dict(item) for item in _load_workflows()]
        emit(args, {"workflows": workflows})
        return 0

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


__all__ = ["add_subparsers", "handler"]
