"""`trm sandbox` —— 查看沙箱**生效范围**与每条规则的来源（S6④）。

三层（内置默认 < ``security.yaml`` < manifest / 派单请求）叠完之后，光看配置文件
根本不知道「到底生效了什么、这条是谁给的、我写的路径为什么没出现」。这个命令就是
把 ``sandbox_exec.plan_for`` 的判定结果连同**来源标注**摊开讲清楚 —— 它是**解释器**，
不施加任何沙箱、不改任何状态。
"""

from __future__ import annotations

import argparse
import os

from .._utils import emit

_USAGE = (
    "trm sandbox explain [agent] [--mode MODE] [--cwd DIR]\n"
    "trm sandbox check [agent] [--mode MODE] [--cwd DIR] [--read PATH] [--write PATH]\n"
    "       （省略 agent 只看全局地板 + security.yaml）"
)


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "sandbox",
        help="inspect the effective sandbox scope and where each rule comes from",
    )
    parser.set_defaults(handler=handler)

    nested = parser.add_subparsers(dest="sandbox_command", metavar="SUBCOMMAND")

    explain = nested.add_parser(
        "explain",
        help="explain the effective sandbox scope (mode / read / write / skipped)",
    )
    explain.add_argument(
        "agent",
        nargs="?",
        default=None,
        help="agent name (omit to see the global floor only)",
    )
    explain.add_argument(
        "--mode",
        default=None,
        help="override the mode (readonly / workspace-write / strict / off)",
    )
    explain.add_argument("--cwd", default=None, help="workspace candidate to explain")
    explain.set_defaults(handler=handler)

    check = nested.add_parser(
        "check",
        help=(
            "validate the sandbox scope config "
            "(unknown names / missing paths / ignored declarations)"
        ),
    )
    check.add_argument(
        "agent",
        nargs="?",
        default=None,
        help="agent name (omit to validate the global floor + every installed agent)",
    )
    check.add_argument("--mode", default=None, help="override the mode to validate")
    check.add_argument("--cwd", default=None, help="workspace candidate to validate")
    check.add_argument(
        "--read",
        action="append",
        default=[],
        metavar="PATH",
        help="simulate a dispatch-time read path (repeatable)",
    )
    check.add_argument(
        "--write",
        action="append",
        default=[],
        metavar="PATH",
        help="simulate a dispatch-time write path (repeatable)",
    )
    check.set_defaults(handler=handler)


def _load_manifest(agent_name: str | None):
    """**只读**读 manifest：绝不用 ``load_from_dir``（那会做证书确认并写盘）。"""
    if not agent_name:
        return None
    from trimum_core.agent_registry import AgentRegistry
    from trimum_core.paths import trimum_path

    try:
        return AgentRegistry().read_manifest(
            agent_name, base_path=str(trimum_path("agents"))
        )
    except Exception:  # noqa: BLE001 - 只读命令：读不到就当没装，别把 CLI 打挂
        return None


def handler(args: argparse.Namespace) -> int:
    if getattr(args, "sandbox_command", None) == "explain":
        return _explain(args)
    if getattr(args, "sandbox_command", None) == "check":
        return _check(args)
    print(_USAGE)
    return 0


_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _installed_agents() -> list[str]:
    """``trimum_path("agents")`` 下的目录名（只读；目录不存在就当没装任何 agent）。"""
    from trimum_core.paths import trimum_path

    try:
        base = trimum_path("agents")
        return sorted(entry.name for entry in os.scandir(base) if entry.is_dir())
    except OSError:
        return []


def _check(args: argparse.Namespace) -> int:
    """校验沙箱范围配置：未知档位 / 不存在的路径 / 会被静默忽略的声明（S6⑤）。

    只报问题，不改配置、不施加沙箱。有 ``error`` 退出码 1，否则 0。
    """
    from trimum_core import sandbox_exec

    mode = getattr(args, "mode", None)
    cwd = getattr(args, "cwd", None)
    agent = getattr(args, "agent", None)
    extra_read = list(getattr(args, "read", None) or [])
    extra_write = list(getattr(args, "write", None) or [])

    def _validate(name: str | None) -> list[dict]:
        return sandbox_exec.validate_scope(
            name,
            manifest=_load_manifest(name),
            mode=mode,
            cwd=cwd,
            extra_read=extra_read,
            extra_write=extra_write,
        )

    def _key(item: dict) -> tuple:
        # 同一份内置面会对每个 agent 重复报一模一样的 info —— 去重，别淹没有用信息
        return (item["severity"], item["code"], item["message"])

    problems: list[dict] = []
    if agent:
        problems.extend(_validate(agent))
    else:
        global_problems = _validate(None)
        problems.extend(global_problems)
        seen = {_key(item) for item in global_problems}
        for name in _installed_agents():
            for item in _validate(name):
                if _key(item) in seen:
                    continue  # 与全局地板逐字相同的（内置面 / 派单路径），全局那条已报
                seen.add(_key(item))
                problems.append(item)

    problems.sort(
        key=lambda item: (
            _SEVERITY_RANK.get(item["severity"], 9),
            item.get("agent") or "",
            item["code"],
        )
    )
    data = {
        "problems": problems,
        "errors": sum(1 for item in problems if item["severity"] == "error"),
        "warnings": sum(1 for item in problems if item["severity"] == "warning"),
    }
    emit(args, data, _human_check)
    return 1 if data["errors"] else 0


def _explain(args: argparse.Namespace) -> int:
    from trimum_core import sandbox_exec

    agent = getattr(args, "agent", None)
    manifest = _load_manifest(agent)
    report = sandbox_exec.explain_scope(
        agent,
        manifest=manifest,
        mode=getattr(args, "mode", None),
        cwd=getattr(args, "cwd", None),
    )
    if agent and manifest is None:
        report["warning"] = (
            f"agent '{agent}' 未安装（或 manifest 读不出来）⇒ 只看全局地板 + security.yaml"
        )
    emit(args, report, _human_explain)
    return 0


def _human_explain(report: dict) -> None:
    def _fmt(items: list[dict]) -> list[str]:
        return [f"  {item['path']:<44} <- {item['source']}" for item in items]

    seccomp = report.get("seccomp") or {}
    print(f"mode:    {report.get('mode')}  (来源: {report.get('mode_source')})")
    print(
        f"state:   {report.get('state')}  "
        f"(supported={report.get('supported')}, abi={report.get('abi')})"
    )
    print(f"seccomp: {seccomp.get('profile')}  (来源: {seccomp.get('source')})")
    if report.get("warning"):
        print(f"[WARN] {report['warning']}")

    for label, key in (("read", "read"), ("write", "write")):
        items = report.get(key) or []
        print(f"{label} ({len(items)}):")
        for line in _fmt(items):
            print(line)

    skipped = report.get("skipped") or []
    print(f"skipped ({len(skipped)}):")
    for item in skipped:
        print(
            f"  {item['path']:<44} ({item['kind']}: {item['reason']}, <- {item['source']})"
        )

    notes = report.get("notes") or []
    if notes:
        print(f"notes ({len(notes)}):")
        for note in notes:
            print(f"  - {note}")


def _human_check(data: dict) -> None:
    for item in data["problems"]:
        print(f"[{item['severity'].upper()}] {item.get('agent') or '(global)'}: {item['message']}")
        if item.get("fix"):
            print(f"  fix: {item['fix']}")
    print(f"{data['errors']} error(s), {data['warnings']} warning(s)")


__all__ = ["add_subparsers", "handler"]
