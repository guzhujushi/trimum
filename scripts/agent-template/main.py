#!/usr/bin/env python3
"""trimum 子 Agent 模板 —— 复制到 agents 目录即可被 AgentManager 拉起。

安装::

    mkdir -p ~/.local/share/trimum/agents/demo
    cp scripts/agent-template/main.py ~/.local/share/trimum/agents/demo/main.py
    trm agent spawn demo        # 或 POST /api/agents/spawn

契约（由 trimum_core.agent_launcher 约定）：
- argv[1] = agent_id
- 环境变量 TRIMUM_AGENT_ID / TRIMUM_AGENT_TYPE / TRIMUM_SOCKET_PATH
- 收到 SIGTERM 后应尽快退出（AgentManager.stop 会先 terminate，超时则 kill）

这个模板本身只做三件事：打印启动日志、向 Agent Runtime 报一次状态、
阻塞等待退出信号。真正的 Agent 逻辑（装 TrimumAgent / 自己的循环）写在这里。
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys


async def notify_runtime(socket_path: str, agent_id: str) -> None:
    """尽力向 Agent Runtime 报一次 started（连不上不影响运行）。"""
    try:
        from trimum_core.agent_socket import AgentSocketClient

        client = AgentSocketClient(socket_path)
        await client.connect()
        await client.send_status(agent_id, "started")
        await client.disconnect()
    except Exception as exc:  # pragma: no cover - 依赖运行环境
        print(f"[trimum-agent] socket notify skipped: {exc}", flush=True)


async def run() -> int:
    agent_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TRIMUM_AGENT_ID", "unknown")
    agent_type = os.environ.get("TRIMUM_AGENT_TYPE", "demo")
    socket_path = os.environ.get("TRIMUM_SOCKET_PATH", "")

    print(
        f"[trimum-agent] {agent_id} (type={agent_type}) started; socket={socket_path or 'none'}",
        flush=True,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, AttributeError, RuntimeError):
            signal.signal(sig, lambda *_: stop.set())

    if socket_path:
        await notify_runtime(socket_path, agent_id)

    await stop.wait()
    print(f"[trimum-agent] {agent_id} stopping", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        sys.exit(0)