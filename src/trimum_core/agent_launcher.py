"""子 Agent 进程启动器 —— AgentManager 与 AgentRuntime 共用。

Phase 3 收尾 P1：``AgentManager.spawn`` / ``AgentRuntime.start_agent`` 之前都是
stub（只登记 AgentInfo，不真正起进程），cgroup 也就没有真实 PID 可绑。

脚本布局（Linux）::

    ~/.local/share/trimum/agents/<agent_type>/main.py

Windows 开发机回退到 ``~/.trimum/agents/<agent_type>/main.py``。

脚本契约：
- ``argv[1]`` = agent_id
- 环境变量：``TRIMUM_AGENT_ID`` / ``TRIMUM_AGENT_TYPE`` / ``TRIMUM_SOCKET_PATH``
- 收到 SIGTERM（Windows: terminate）后应尽快退出

子进程输出不走 PIPE，而是追加写入 ``<agents_root>/../agent-logs/<agent_id>.log``：
PIPE 在没人读的情况下写满 64KB 就会把 Agent 卡死，短命的 CLI 进程退出时
还会抛 asyncio "Event loop is closed"。落文件既不阻塞又留下可回看的输出，
启动失败时从本次写入区间取尾部作为 stderr 摘要。
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .logger import get_logger

log = get_logger("trimum_core.agent_launcher")

# 启动后等一小会儿，用来发现"脚本立刻崩了"的情况
STARTUP_GRACE_SECONDS = 0.15


def _data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(xdg) / "trimum"


def agent_log_dir(base: Optional[str | Path] = None) -> Path:
    """Agent 输出目录（与脚本根同级，随 ``agents_root`` 一起搬迁）。"""
    return agents_root(base).parent / "agent-logs"


def agents_root(base: Optional[str | Path] = None) -> Path:
    """Agent 脚本根目录。"""
    if base is not None:
        return Path(base)
    if os.name == "nt":
        # 开发机回退：~/.trimum/agents
        windows_root = Path.home() / ".trimum" / "agents"
        if windows_root.exists():
            return windows_root
    return _data_dir() / "agents"


def resolve_agent_script(
    agent_type: str,
    base: Optional[str | Path] = None,
) -> Optional[Path]:
    """返回 ``<root>/<agent_type>/main.py``，不存在则返回 None。"""
    script = agents_root(base) / agent_type / "main.py"
    return script.resolve() if script.is_file() else None


def build_agent_env(
    agent_id: str,
    agent_type: str,
    socket_path: Optional[str] = None,
    extra: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """构造子 Agent 的环境变量（继承父进程 + trimum 约定变量）。"""
    env = dict(os.environ)
    env["TRIMUM_AGENT_ID"] = agent_id
    env["TRIMUM_AGENT_TYPE"] = agent_type
    if socket_path:
        env["TRIMUM_SOCKET_PATH"] = socket_path
    for key, value in (extra or {}).items():
        env[str(key)] = str(value)
    return env


@dataclass
class LaunchResult:
    """启动结果。``process is None`` 表示没有找到脚本（仅登记）。"""

    process: Optional[asyncio.subprocess.Process] = None
    pid: Optional[int] = None
    error: Optional[str] = None
    script: Optional[Path] = None
    log_path: Optional[Path] = None


async def launch_agent(
    agent_id: str,
    agent_type: str,
    *,
    script: Optional[Path] = None,
    base: Optional[str | Path] = None,
    socket_path: Optional[str] = None,
    extra_env: Optional[dict[str, str]] = None,
    startup_grace: float = STARTUP_GRACE_SECONDS,
) -> LaunchResult:
    """真正把子 Agent 拉起来（``asyncio.create_subprocess_exec``）。

    没找到脚本 → 返回空结果，由调用方决定"只登记"还是报错。
    进程秒退 → 返回 ``error``（含 stderr 摘要），调用方标记 FAILED。
    """
    script = script or resolve_agent_script(agent_type, base)
    if script is None:
        return LaunchResult(script=None)

    # 必须绝对化：下面会把子进程 cwd 设为脚本目录，相对路径会解析错位
    script = Path(script).resolve()

    try:
        log_path = _prepare_log_file(agent_id, base)
    except OSError as e:
        log.warning("agent_launcher.log_open_failed", agent_id=agent_id, error=str(e))
        return LaunchResult(error=f"failed to open agent log: {e}", script=script)

    # 本次启动前的写入量：秒退时只读这一次的输出
    log_offset = log_path.stat().st_size if log_path.exists() else 0

    try:
        with open(log_path, "ab") as sink:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script),
                agent_id,
                cwd=str(script.parent),
                env=build_agent_env(agent_id, agent_type, socket_path, extra_env),
                stdout=sink,
                stderr=sink,
            )
    except Exception as e:
        log.warning("agent_launcher.spawn_failed", agent_type=agent_type, error=str(e))
        return LaunchResult(
            error=f"failed to spawn agent: {e}", script=script, log_path=log_path
        )

    if startup_grace > 0:
        await asyncio.sleep(startup_grace)

    if process.returncode is not None:
        detail = _read_log_tail(log_path, log_offset)
        log.warning(
            "agent_launcher.exited_early",
            agent_type=agent_type,
            returncode=process.returncode,
        )
        return LaunchResult(
            process=process,
            pid=process.pid,
            error=f"agent exited immediately (code={process.returncode}){detail}",
            script=script,
            log_path=log_path,
        )

    log.info(
        "agent_launcher.started",
        agent_id=agent_id,
        agent_type=agent_type,
        pid=process.pid,
        script=str(script),
        log_path=str(log_path),
    )
    return LaunchResult(
        process=process, pid=process.pid, script=script, log_path=log_path
    )


def _prepare_log_file(agent_id: str, base: Optional[str | Path]) -> Path:
    """确保日志目录存在，返回该 Agent 的日志文件（追加写）。"""
    log_dir = agent_log_dir(base)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{agent_id}.log"


def _read_log_tail(path: Path, offset: int = 0, limit: int = 400) -> str:
    """读取本次启动写入的日志尾部（子进程秒退时的诊断摘要）。"""
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    return f": {text[-limit:]}"


async def terminate_process(
    process: Optional[asyncio.subprocess.Process],
    timeout: float = 5.0,
) -> None:
    """优雅终止子 Agent 进程（超时则强杀）。"""
    if process is None or process.returncode is not None:
        return
    try:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
    except ProcessLookupError:
        pass


__all__ = [
    "LaunchResult",
    "agent_log_dir",
    "agents_root",
    "build_agent_env",
    "launch_agent",
    "resolve_agent_script",
    "terminate_process",
]