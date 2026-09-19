"""`trm agent` command group — list/info/spawn/kill agents."""

from __future__ import annotations

import argparse

from .._utils import emit, fail, get_daemon_status, http_json, rpc_call, run_async


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("agent", help="manage runtime agents")
    nested = parser.add_subparsers(dest="agent_command", title="agent commands")

    list_parser = nested.add_parser("list", help="list all agents")
    list_parser.set_defaults(handler=handler)

    info_parser = nested.add_parser("info", help="show agent details")
    info_parser.add_argument("agent_id")
    info_parser.set_defaults(handler=handler)

    spawn_parser = nested.add_parser("spawn", help="spawn a new agent")
    spawn_parser.add_argument("agent_id")
    spawn_parser.set_defaults(handler=handler)

    kill_parser = nested.add_parser("kill", help="stop an agent")
    kill_parser.add_argument("agent_id")
    kill_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm agent {list,info,spawn,kill} ...")
    return 0


def _config():
    from trimum_core.config import Config

    return Config()


def _to_dict(item):
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    return item


async def _local_agent_call(command: str, agent_id: str | None) -> tuple[dict | None, str]:
    from trimum_core.agent_manager import AgentManager
    from trimum_core.models import SpawnRequest

    manager = AgentManager()
    if command == "list":
        agents = await manager.list()
        return {"agents": [_to_dict(agent) for agent in agents]}, "ok"
    if command == "info" and agent_id:
        agent = await manager.get(agent_id)
        return ({"agent": _to_dict(agent)} if agent else None), ("ok" if agent else "not_found")
    if command == "spawn" and agent_id:
        response = await manager.spawn(SpawnRequest(agent_type=agent_id))
        return {"agent": _to_dict(response)}, "ok"
    if command == "kill" and agent_id:
        stopped = await manager.stop(agent_id)
        return {"stopped": stopped, "agent_id": agent_id}, ("ok" if stopped else "failed")
    return None, "unknown"


def _remote_agent_call(config, command: str, agent_id: str | None) -> tuple[dict | None, str]:
    status = get_daemon_status(config)
    if not status["running"]:
        return None, "offline"

    if status["source"] == "rpc":
        if command == "list":
            result = rpc_call(config, "agents.list")
            return ({"agents": result} if result is not None else None), ("ok" if result is not None else "failed")
        if command == "info" and agent_id:
            result = rpc_call(config, "agents.get", {"agent_id": agent_id})
            return ({"agent": result} if result is not None else None), ("ok" if result is not None else "not_found")
        if command == "spawn" and agent_id:
            result = rpc_call(config, "agents.spawn", {"agent_type": agent_id})
            return ({"agent": result} if result is not None else None), ("ok" if result is not None else "failed")
        if command == "kill" and agent_id:
            result = rpc_call(config, "agents.stop", {"agent_id": agent_id})
            return ({"stopped": result.get("success", False), "agent_id": agent_id} if isinstance(result, dict) else None), ("ok" if isinstance(result, dict) and result.get("success") else "failed")
        return None, "unknown"

    if command == "list":
        result = http_json(config, "GET", "/api/agents")
        return ({"agents": result} if result is not None else None), ("ok" if result is not None else "failed")
    if command == "info" and agent_id:
        result = http_json(config, "GET", f"/api/agents/{agent_id}")
        return ({"agent": result} if result is not None else None), ("ok" if result is not None else "not_found")
    if command == "spawn" and agent_id:
        result = http_json(config, "POST", "/api/agents/spawn", json_data={"agent_type": agent_id})
        return ({"agent": result} if result is not None else None), ("ok" if result is not None else "failed")
    if command == "kill" and agent_id:
        result = http_json(config, "POST", f"/api/agents/{agent_id}/stop")
        return ({"stopped": True, "agent_id": agent_id} if result is not None else None), ("ok" if result is not None else "failed")
    return None, "unknown"


def handler(args: argparse.Namespace) -> int:
    """Execute the requested agent subcommand."""
    command = getattr(args, "agent_command", None)
    agent_id = getattr(args, "agent_id", None)
    if command not in {"list", "info", "spawn", "kill"}:
        return _show_help(args)

    config = _config()
    data, status = _remote_agent_call(config, command, agent_id)
    if status == "offline":
        try:
            data, status = run_async(_local_agent_call(command, agent_id))
        except Exception as exc:
            return fail(f"agent operation failed: {exc}")

    if status == "not_found":
        emit(args, {"agent_id": agent_id, "found": False})
        return 1
    if status in {"failed", "unknown"} or data is None:
        return fail(f"agent operation failed ({command})")

    emit(args, data)
    return 0


__all__ = ["add_subparsers", "handler"]
