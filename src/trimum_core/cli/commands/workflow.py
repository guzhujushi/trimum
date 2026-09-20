"""`trm workflow` command group — list/run/status/log/import.

``import`` 是 E4 的 workflow 入口（`docs/E4-PLAN.md` §2.4）：把一份 Warp 式目录 YAML
收进 ``<TRIMUM_HOME>/workflows/<id>/workflow.yaml``。导入只读文本、只写文本。

W1 把 ``list`` / ``run`` 接上了执行：两者都走 ``WorkflowRuntime``（与 daemon 同一套
口径），``run --event`` 顺手把「监听 Event Bus → 触发执行」整条链跑一遍；
``enable`` 把内置威胁剧本落盘成用户自己的 workflow（落盘即常驻触发）。
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
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="also list builtin threat playbooks (they are disabled by default)",
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

    run_parser = nested.add_parser(
        "run", help="run a workflow now, or wait for its Event Bus trigger"
    )
    run_parser.add_argument("name")
    run_parser.add_argument(
        "--root", default=None, help="workflow root (default <TRIMUM_HOME>/workflows)"
    )
    run_parser.add_argument("--input", dest="input_json", default=None, help="JSON context object")
    run_parser.add_argument(
        "--event",
        default=None,
        help="wait for this Event Bus event type to trigger the workflow",
    )
    run_parser.add_argument(
        "--payload", default=None, help="JSON payload emitted with --event"
    )
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds to wait for the trigger (default: 30)",
    )
    run_parser.add_argument(
        "--dry-run", action="store_true", help="print the compiled nodes, execute nothing"
    )
    run_parser.set_defaults(handler=handler)

    enable_parser = nested.add_parser(
        "enable", help="materialize a builtin threat playbook into the workflow root"
    )
    enable_parser.add_argument("name")
    enable_parser.add_argument(
        "--root", default=None, help="workflow root (default <TRIMUM_HOME>/workflows)"
    )
    enable_parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    enable_parser.add_argument(
        "--force", action="store_true", help="overwrite an existing workflow file"
    )
    enable_parser.set_defaults(handler=handler)

    status_parser = nested.add_parser("status", help="show workflow run status")
    status_parser.add_argument("run_id")
    status_parser.set_defaults(handler=handler)

    log_parser = nested.add_parser("log", help="show workflow run log")
    log_parser.add_argument("run_id")
    log_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm workflow {list,run,enable,status,log,import} ...")
    return 0


def _build_runtime(root: str | None = None, *, include_builtin: bool = True):
    """建一个与 daemon 同口径的运行时：文件目录 + 内置剧本。

    CLI 是一次性进程，这里不做常驻：``list`` 只读注册表，``run`` 才真的执行。
    """
    from trimum_core.event_bus import EventBus
    from trimum_core.workflow_runtime import WorkflowRuntime

    bus = EventBus()
    runtime = WorkflowRuntime(bus)
    runtime.register_all(root, include_builtin=include_builtin)
    return runtime, bus


def _parse_json_object(raw: str | None, flag: str) -> tuple[dict, str]:
    """解析 ``--input`` / ``--payload``；返回 ``(值, 错误)``。"""
    if not raw:
        return {}, ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"invalid {flag} JSON: {exc}"
    if not isinstance(parsed, dict):
        return {}, f"{flag} must be a JSON object"
    return parsed, ""


def handler(args: argparse.Namespace) -> int:
    """Execute the requested workflow subcommand."""
    command = getattr(args, "workflow_command", None)

    if command == "list":
        runtime, _ = _build_runtime(
            getattr(args, "root", None), include_builtin=bool(getattr(args, "all", False))
        )
        workflows = runtime.list_workflows(include_disabled=True)
        emit(args, {"workflows": workflows, "count": len(workflows)}, _human_list)
        return 0

    if command == "import":
        return _handle_import(args)

    if command == "enable":
        return _handle_enable(args)

    if command == "run":
        return _handle_run(args)

    if command in {"status", "log"}:
        data = {
            "run_id": args.run_id,
            "status": "unknown",
            "message": "workflow run state is not persisted by the local CLI",
        }
        emit(args, data)
        return 0

    return _show_help(args)


def _handle_run(args: argparse.Namespace) -> int:
    """``trm workflow run``：立刻执行，或等 Event Bus 上的触发器命中后再执行。"""
    runtime, bus = _build_runtime(getattr(args, "root", None), include_builtin=True)
    registered = runtime.get(args.name)
    if registered is None:
        return fail(f"unknown workflow: {args.name}")

    context, error = _parse_json_object(getattr(args, "input_json", None), "--input")
    if error:
        return fail(error)
    payload, error = _parse_json_object(getattr(args, "payload", None), "--payload")
    if error:
        return fail(error)

    if getattr(args, "dry_run", False):
        definition = registered.workflow.to_workflow_definition()
        emit(args, {
            "dry_run": True,
            "workflow": registered.to_dict(),
            "nodes": [
                {
                    "node_id": node.id,
                    "handler": node.handler,
                    "instruction": node.config.get("instruction", ""),
                    "timeout_seconds": node.timeout_seconds,
                }
                for node in definition.nodes
            ],
        }, _human_plan)
        return 0

    try:
        records = asyncio.run(_execute(runtime, bus, registered, args, context, payload))
    except Exception as exc:
        return fail(f"workflow run failed: {exc}")

    if records is None:
        triggers = ", ".join(registered.triggers()) or "(none)"
        return fail(
            f"no run triggered by {args.event!r} within {args.timeout}s "
            f"(this workflow listens for: {triggers})"
        )

    # 事件是广播的：同一次触发可能顺带跑掉别的 workflow。只对点名的那份负责，
    # 其余如实汇报，不把它们的成败算到本次命令的退出码上。
    mine = [record for record in records if record.workflow_id == registered.id]
    others = sorted({record.workflow_id for record in records
                     if record.workflow_id != registered.id})
    if not mine:
        triggered = ", ".join(others) or "(none)"
        return fail(
            f"{args.event!r} fired but {registered.id} was not triggered "
            f"(triggered instead: {triggered})"
        )

    data = {
        "workflow": registered.to_dict(),
        "triggered_by": "event" if getattr(args, "event", None) else "manual",
        "runs": [record.to_dict() for record in mine],
    }
    if others:
        data["other_triggered"] = others
    emit(args, data, _human_run)
    return 0 if all(record.ok for record in mine) else 1


async def _execute(runtime, bus, registered, args, context, payload):
    """手动跑整份 workflow，或发一条事件等它自己触发。"""
    if not getattr(args, "event", None):
        return [await runtime.run_now(registered.id, context=context)]

    await runtime.start()
    try:
        baseline = runtime.run_count
        await bus.emit_event(args.event, "trm-cli", payload)
        records = await runtime.wait_for_runs(since=baseline, timeout=args.timeout)
    finally:
        await runtime.stop()
    return records or None


def _handle_enable(args: argparse.Namespace) -> int:
    """把内置剧本落盘成用户自己的 workflow：落盘即显式启用。"""
    from pathlib import Path

    from trimum_core import workflow_catalog
    from trimum_core.paths import trimum_path

    runtime, _ = _build_runtime(getattr(args, "root", None), include_builtin=True)
    registered = runtime.get(args.name)
    if registered is None:
        return fail(f"unknown workflow: {args.name}")
    if registered.source != "builtin":
        return fail(
            f"{registered.id} is already a local workflow (source={registered.source})"
        )

    root = Path(args.root) if args.root else trimum_path("workflows")
    target = Path(root) / registered.id / "workflow.yaml"
    if target.exists() and not args.force:
        return fail(f"{target} already exists (use --force to overwrite)")

    data = registered.workflow.model_dump()
    config = dict(data.get("config") or {})
    config["enabled"] = True
    config["materialized_from"] = "builtin"
    data["config"] = config

    if not args.yes and not ask_confirm(
        f"enable builtin workflow '{registered.id}' -> {target}?"
    ):
        return fail("aborted (use --yes for non-interactive runs)")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(workflow_catalog.dump_workflow(data), encoding="utf-8")
    emit(args, {
        "workflow": registered.to_dict(),
        "path": str(target),
        "enabled": True,
    }, _human_enable)
    return 0


def _human_list(data: dict) -> None:
    for item in data["workflows"]:
        marks = []
        if not item["enabled"]:
            marks.append("disabled")
        if item["triggers"]:
            marks.append("trigger=" + ",".join(item["triggers"]))
        suffix = "  " + " ".join(marks) if marks else ""
        print(
            f"{item['id']:<28} [{item['source']:<7}] "
            f"steps={item['steps']} tasks={item['tasks']}{suffix}"
        )
    print(f"{data['count']} workflow(s)")


def _output_excerpt(result) -> str:
    if not isinstance(result, dict):
        return ""
    output = str(result.get("output", "")).strip().replace("\n", " | ")
    command = str(result.get("command", ""))
    if command and output:
        return f"{command} -> {output}"
    return command or output


def _human_run(data: dict) -> None:
    workflow = data["workflow"]
    print(
        f"workflow {workflow['id']} (source={workflow['source']}, "
        f"triggered_by={data['triggered_by']})"
    )
    for other in data.get("other_triggered") or []:
        print(f"  (the same event also triggered: {other})")
    for record in data["runs"]:
        print(f"  run {record['run_id']} status={record['status']} duration={record['duration']}s")
        for node in record["nodes"]:
            detail = node["error"] or _output_excerpt(node["result"])
            print(
                f"    {node['node_id']:<18} {node['status']:<10} "
                f"{node['handler']:<8} {detail}"
            )


def _human_plan(data: dict) -> None:
    workflow = data["workflow"]
    print(
        f"workflow {workflow['id']} (source={workflow['source']}) — "
        f"{len(data['nodes'])} node(s), nothing executed"
    )
    for node in data["nodes"]:
        print(
            f"  {node['node_id']:<18} {node['handler']:<8} "
            f"timeout={node['timeout_seconds']}s {node['instruction']}"
        )


def _human_enable(data: dict) -> None:
    print(f"enabled {data['workflow']['id']} -> {data['path']}")
    print("  it is an ordinary workflow file now; the next runtime start picks it up")


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
        "summary": "List workflows found in the workflow root (and builtin playbooks)",
        "args": "[--root DIR] [--all]",
        "examples": ["trm workflow list --json", "trm workflow list --all"],
        "risk": "low",
        "tags": ["workflow"],
        "since": "0.6.0",
    },
    "workflow run": {
        "summary": "Run a workflow now, or wait for its Event Bus trigger",
        "args": "<id> [--input JSON] [--event TYPE] [--payload JSON] [--timeout S] [--dry-run]",
        "examples": [
            "trm workflow run docker-cleanup",
            "trm workflow run demo --event security.monitor_result --payload {}",
        ],
        "risk": "medium",
        "tags": ["workflow"],
        "since": "0.6.0",
    },
    "workflow enable": {
        "summary": "Materialize a builtin threat playbook into the workflow root",
        "args": "<id> [--root DIR] [--yes] [--force]",
        "examples": ["trm workflow enable threat-cron-audit --yes"],
        "risk": "medium",
        "tags": ["workflow", "security"],
        "since": "0.6.0",
    },
}


__all__ = ["add_subparsers", "handler"]
