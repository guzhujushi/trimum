"""`trm security` command group."""

from __future__ import annotations

import argparse

from .._utils import emit, fail, get_daemon_status, http_json, rpc_call


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("security", help="security policy and JIT tokens")
    nested = parser.add_subparsers(dest="security_command", title="security commands")

    status_parser = nested.add_parser("status", help="show security policy status")
    status_parser.set_defaults(handler=handler)

    allow_parser = nested.add_parser(
        "allow-once",
        help="issue a one-time JIT authorization token",
    )
    allow_parser.add_argument("agent_id")
    allow_parser.add_argument("--tool", default="shell", help="tool name to authorize")
    allow_parser.add_argument("--cmd", default="", help="command to authorize")
    allow_parser.add_argument("--ttl", type=float, default=300.0, help="token lifetime in seconds")
    allow_parser.set_defaults(handler=handler)

    tokens_parser = nested.add_parser("tokens", help="list valid JIT tokens")
    tokens_parser.set_defaults(handler=handler)

    revoke_parser = nested.add_parser(
        "revoke", help="revoke a valid JIT token (full or prefix >= 4 chars)"
    )
    revoke_parser.add_argument(
        "token_id",
        help="full token string or a unique prefix (>= 4 chars)",
    )
    revoke_parser.set_defaults(handler=handler)

    learning_parser = nested.add_parser(
        "learning", help="show policy learning status (profiles + learned rules)"
    )
    learning_parser.set_defaults(handler=handler)

    learn_parser = nested.add_parser(
        "learn", help="run one policy-learning analysis via the daemon"
    )
    learn_parser.add_argument(
        "--inject",
        action="store_true",
        help="inject the learned ruleset into the running PolicyEngine",
    )
    learn_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm security {status,allow-once,tokens,revoke,learning,learn} ...")
    return 0


def _status_data() -> dict:
    from trimum_core.security_config import SecurityConfig

    config = SecurityConfig()
    config.load()
    return {
        "default_mode": config.get_mode().value,
        "levels": config._raw.get("levels", {}),
        "llm": config.get_llm_config(),
    }


def _issue_token(args: argparse.Namespace) -> dict:
    from pathlib import Path

    from trimum_core.config import Config
    from trimum_core.models import ToolType
    from trimum_core.policy_engine import PolicyEngine
    from trimum_core.tool_gateway import ToolGateway

    config = Config()
    try:
        tool = ToolType(args.tool)
    except ValueError:
        tool = ToolType.SHELL

    gateway = ToolGateway(PolicyEngine(Path(config.policy_path)))
    token = gateway.issue_jit_token(
        agent_id=args.agent_id,
        tool=tool,
        command=args.cmd,
        ttl=args.ttl,
    )
    return {
        "token": token.token,
        "agent_id": token.agent_id,
        "tool": token.tool,
        "command": token.command,
        "expires_at": token.expires_at,
        "ttl": args.ttl,
    }


def _tokens_data() -> dict:
    from trimum_core.config import Config

    config = Config()

    # RPC 优先：TCP 面一旦关掉（裁决见 docs/SANDBOX-PLAN.md §9.3.5），
    # 下面那条 HTTP 路会整条消失 —— 这三个子命令以前只有 HTTP 一条腿。
    result = rpc_call(config, "security.tokens")
    if isinstance(result, dict):
        return {"tokens": result.get("tokens", [])}

    status = get_daemon_status(config)
    if status["running"]:
        payload = http_json(config, "GET", "/api/security/tokens")
        if isinstance(payload, dict):
            return {"tokens": payload.get("data", [])}

    return {"tokens": []}


def _revoke_data(token_id: str) -> dict:
    from trimum_core.config import Config

    config = Config()
    result = rpc_call(config, "security.revoke", {"token_id": token_id})
    if isinstance(result, dict):
        return result
    return {"revoked": False, "error": "daemon unreachable (is trmd running?)"}


def _learning_data() -> dict:
    from trimum_core.config import Config

    config = Config()

    result = rpc_call(config, "security.learning")
    if isinstance(result, dict) and result:
        return result

    status = get_daemon_status(config)
    if status["running"]:
        payload = http_json(config, "GET", "/api/security/learning")
        if payload:
            return payload.get("data", {})
    return {"daemon_running": False, "hint": "run `trmd` to collect learning data"}


def _learn_data(inject: bool) -> dict:
    from trimum_core.config import Config

    config = Config()

    result = rpc_call(config, "security.learn", {"inject": bool(inject)}, timeout=10.0)
    if isinstance(result, dict) and result:
        return result

    status = get_daemon_status(config)
    if not status["running"]:
        raise RuntimeError("daemon is not running — learning needs live behavior data")
    payload = http_json(
        config,
        "POST",
        "/api/security/learn",
        json_data={"inject": bool(inject)},
        timeout=10.0,
    )
    if not payload:
        raise RuntimeError("daemon did not return a learning result")
    return payload.get("data", {})


def handler(args: argparse.Namespace) -> int:
    """Execute the requested security subcommand."""
    command = getattr(args, "security_command", None)
    if command == "status":
        data = _status_data()
    elif command == "allow-once":
        if not args.agent_id:
            return fail("agent_id is required")
        try:
            data = _issue_token(args)
        except Exception as exc:
            return fail(f"failed to issue token: {exc}")
    elif command == "tokens":
        data = _tokens_data()
    elif command == "revoke":
        data = _revoke_data(args.token_id)
        if not data.get("revoked"):
            return fail(data.get("error", "revocation failed"))
    elif command == "learning":
        data = _learning_data()
    elif command == "learn":
        try:
            data = _learn_data(bool(getattr(args, "inject", False)))
        except Exception as exc:
            return fail(f"learning analysis failed: {exc}")
    else:
        return _show_help(args)

    emit(args, data)
    return 0


__all__ = ["add_subparsers", "handler"]
