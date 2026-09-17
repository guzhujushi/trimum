"""trimum Core — main entry point.

Usage:
    trmd                  # Run with default config (host 127.0.0.1:8321)
    trmd --config /etc/trimum/config.yaml
    trmd --host 0.0.0.0 --port 8321
    trmd --version        # Show version and exit
"""

from __future__ import annotations

import argparse
import sys
from .install_fn import install


def run() -> None:
    """CLI entry point for trimum Core daemon."""
    parser = argparse.ArgumentParser(
        description="trimum Core Daemon - system-level AI agent runtime",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to config YAML file",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Override host (default from config: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override port (default from config: 8321)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )

    args = parser.parse_args()

    if args.version:
        from . import __version__
        print(f"trimum-core v{__version__}")
        sys.exit(0)

    from .config import Config
    from .api_server import create_app
    from .event_bus import EventBus
    from .sec_monitor import SecMonitor, ThreatMatcher, OpContextClassifier
    from .sec_executor import SecExecutor, SecAudit, SecNotif
    from .tool_gateway import ToolGateway
    from .logger import setup_logging, get_logger
    from pathlib import Path
    import asyncio
    import uvicorn

    config = Config()
    if args.config:
        config = Config(Path(args.config))
    if args.host:
        config._raw["core"]["host"] = args.host
    if args.port:
        config._raw["core"]["port"] = args.port

    # ── 初始化安全组件 ─────────────────────────────────────────
    async def init_security(tool_gateway: ToolGateway, event_bus: EventBus) -> SecMonitor:
        sec_audit = SecAudit()
        sec_notif = SecNotif(event_bus)
        sec_executor = SecExecutor(event_bus, sec_audit, sec_notif)
        threat_matcher = ThreatMatcher()
        op_context = OpContextClassifier()
        sec_monitor = SecMonitor(event_bus, threat_matcher, op_context, sec_executor)
        await sec_monitor.start()
        # 挂载到 ToolGateway
        tool_gateway.sec_monitor = sec_monitor
        tool_gateway.sec_executor = sec_executor
        tool_gateway.op_context = op_context
        return sec_monitor

    # ── 启动 ───────────────────────────────────────────────────
    # 先初始化安全组件（同步包装）
    import asyncio

    async def _init():
        setup_logging(config)
        logger = get_logger("main")
        app = create_app(config)
        state = app.state.trimum
        logger.info("initializing_security_components")
        sec_monitor = await init_security(state.tool_gateway, state.event_bus)
        state.sec_monitor = sec_monitor
        logger.info("security_components_ready", monitor=type(sec_monitor).__name__)
        logger.info("starting_http_server", host=config.host, port=config.port)
        return app, config

    app, config = asyncio.run(_init())

    # 使用 uvicorn.run() 替代手动 Server.serve()
    # uvicorn 0.52.4 中 Server.startup() 在手动调用 config.load()
    # 之前不创建 lifespan 属性；server.serve() 也可能因 create_server
    # 卡住。uvicorn.run() 是官方推荐入口，自带完整生命周期管理。
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        reload=False,
    )


# ── 快速健康检查 CLI（无 daemon 模式） ─────────────────────────

def health() -> None:
    """Quick health check — runs synchronously, no daemon start."""
    from .config import Config
    from .policy_engine import PolicyEngine
    from .agent_registry import AgentRegistry
    from pathlib import Path

    config = Config()
    results = {
        "config": {"status": "ok", "path": str(config.config_path)},
        "imports": {"status": "ok", "modules": []},
    }

    # 尝试导入每个核心模块
    core_modules = [
        "trimum_core.models",
        "trimum_core.event_bus",
        "trimum_core.tool_gateway",
        "trimum_core.policy_engine",
        "trimum_core.security_rule",
        "trimum_core.sec_monitor",
        "trimum_core.sec_executor",
        "trimum_core.behavior_monitor",
        "trimum_core.system_monitor",
        "trimum_core.context_manager",
        "trimum_core.agent_manager",
        "trimum_core.agent_registry",
        "trimum_core.agent_runtime",
        "trimum_core.agent_socket",
        "trimum_core.workflow_engine",
        "trimum_core.skill_loader",
        "trimum_core.skill_router",
        "trimum_core.skill_executor",
        "trimum_core.experience_learner",
        "trimum_core.tarl_parser",
        "trimum_core.transform_agent",
        "trimum_core.planner_agent",
        "trimum_core.tool_file_loader",
        "trimum_core.tool_dispatchers",
        "trimum_core.ipc_handler",
        "trimum_core.memory_bridge",
    ]
    # Deduplicate
    seen = set()
    unique_modules = []
    for m in core_modules:
        if m not in seen:
            seen.add(m)
            unique_modules.append(m)

    failures = []
    for mod_name in unique_modules:
        try:
            __import__(mod_name)
            results["imports"]["modules"].append(f"{mod_name}: ok")
        except Exception as e:
            failures.append(f"{mod_name}: {e}")
            results["imports"]["modules"].append(f"{mod_name}: FAIL ({e})")

    # 检查 policy 加载（通过 evaluate 一个无害命令来验证规则工作）
    try:
        policy = PolicyEngine(Path(config.policy_path))
        risk, action, reason = policy.evaluate("ls -la")
        results["policy"] = {"status": "ok", "evaluate_test": f"ls -> {risk.value}/{action.value}"}
    except Exception as e:
        results["policy"] = {"status": "fail", "error": str(e)}
        failures.append(f"policy: {e}")

    # 检查 Agent Registry 目录
    import os
    agent_dir = os.path.expanduser("~/.trimum/agents")
    if os.path.isdir(agent_dir):
        results["agents"] = {"status": "ok", "path": agent_dir, "count": len(os.listdir(agent_dir))}
    else:
        results["agents"] = {"status": "warn", "path": agent_dir, "msg": "directory does not exist yet"}

    # 检查 ~/.trimum/tools
    tools_dir = os.path.expanduser("~/.trimum/tools")
    results["tools"] = {}
    if os.path.isdir(tools_dir):
        results["tools"] = {"status": "ok", "path": tools_dir}
    else:
        results["tools"] = {"status": "warn", "path": tools_dir, "msg": "directory does not exist yet"}

    import json
    print(json.dumps(results, indent=2, ensure_ascii=False))
    if failures:
        print(f"\n[!] {len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("\n[OK] trimum health: all checks passed")
        sys.exit(0)




def cli_dispatch() -> None:
    """CLI dispatch entry point (``trm`` command).

    Usage::

        trm              -> runs daemon (same as ``trmd``)
        trm health       -> quick health check
        trm install      -> interactive first-time setup guide
        trm exec <cmd>   -> AI Agent 执行自然语言指令（流式）
        trm version      -> show version

    This is registered as the ``trm`` console_scripts entry in ``pyproject.toml``.
    """
    if len(sys.argv) > 1:
        sub = sys.argv[1]
        if sub == "health":
            health()
            return
        elif sub == "install":
            install()
            return
        elif sub == "exec":
            # 解析 --interactive / -i 标志
            args = sys.argv[2:]
            interactive = "--interactive" in args or "-i" in args
            args = [a for a in args if a not in ("--interactive", "-i")]
            prompt = " ".join(args)
            _exec_command(prompt, interactive=interactive)
            return
        elif sub == "security":
            security()
            return
        elif sub == "version":
            from . import __version__
            print(f"trimum v{__version__}")
            return
    # Default: run daemon
    run()


def _exec_command(prompt: str, interactive: bool = False) -> None:
    """trm exec 入口 — 交互式 AI Agent 执行。

    interactive=True 时进入多步循环模式。
    """
    if not prompt:
        print("用法: trm exec [--interactive|-i] \"<自然语言指令>\"")
        print("例:   trm exec \"查看 /tmp 下有哪些大文件\"")
        print("      trm exec -i \"写个脚本统计日志文件大小\"")
        sys.exit(1)

    import asyncio
    from .agent_loop import AgentLoop

    loop = AgentLoop(agent_name="trm-exec")
    if interactive:
        asyncio.run(loop.run_interactive(prompt))
    else:
        asyncio.run(loop.run(prompt))


if __name__ == "__main__":
    cli_dispatch()



def _security_allow_once(agent_id: str, tool: str, command: str, ttl: float) -> None:
    """签发改一次性代理授权令牌并输出到 stdout。"""
    from .tool_gateway import ToolGateway
    from .policy_engine import PolicyEngine
    from .config import Config
    from pathlib import Path
    from .models import ToolType

    config = Config(Path(config.config_path) if hasattr(config, "config_path") else Path("~/.trimum/config.yaml").expanduser())
    # 简化流程：直接初始化 ToolGateway 并签发
    gateway = ToolGateway(
        PolicyEngine(Path(config.policy_path)),
    )
    try:
        tool_enum = ToolType(tool)
    except ValueError:
        tool_enum = ToolType.SHELL

    tok = gateway.issue_jit_token(
        agent_id=agent_id,
        tool=tool_enum,
        command=command,
        ttl=ttl,
    )
    print(f"JIT_TOKEN={tok.token}")
    print(f"AGENT={tok.agent_id}")
    print(f"TOOL={tok.tool}")
    print(f"EXPIRES_AT={tok.expires_at}")
    print(f"TTL={ttl}s")
    print(f"Command: {command if command else '<any>'}")


def security() -> None:
    """trm security 子命令组。"""
    if len(sys.argv) < 3:
        print("用法: trm security allow-once <agent_id> [--tool shell] [--cmd <command>] [--ttl 300]")
        sys.exit(0)

    sub = sys.argv[2]
    if sub == "allow-once":
        args = sys.argv[3:]
        agent_id = ""
        tool = "shell"
        command = ""
        ttl = 300.0

        if args and not args[0].startswith("-"):
            agent_id = args[0]
            args = args[1:]

        i = 0
        while i < len(args):
            if args[i] == "--tool" and i + 1 < len(args):
                tool = args[i + 1]; i += 2
            elif args[i] == "--cmd" and i + 1 < len(args):
                command = args[i + 1]; i += 2
            elif args[i] == "--ttl" and i + 1 < len(args):
                ttl = float(args[i + 1]); i += 2
            else:
                i += 1

        if not agent_id:
            print("[!] 需要 agent_id 参数")
            print("用法: trm security allow-once <agent_id> [--tool shell] [--cmd <command>] [--ttl 300]")
            sys.exit(1)

        _security_allow_once(agent_id, tool, command, ttl)
    else:
        print(f"未知 security 子命令: {sub}")
        print("可用: allow-once")
        sys.exit(1)

