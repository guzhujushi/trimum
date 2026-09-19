"""IPC Handler 监听 socket 测试。

回归点：`loop.sock_accept()` 只在 debug 模式下检查非阻塞标志。之前的实现
用阻塞 socket 调 `loop.sock_accept()`，accept() 会直接阻塞事件循环线程，
在 Linux 上表现为「daemon 起来后整体假死 / 测试挂住」。
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.ipc_handler import IpcHandler


class TestIpcListenerSocket:
    @pytest.mark.asyncio
    async def test_unix_listener_is_non_blocking(self, tmp_path):
        if os.name == "nt":
            pytest.skip("Windows 上跳过 AF_UNIX 监听（_start_unix_socket 直接 return）")

        ipc = IpcHandler(socket_path=str(tmp_path / "trimum.sock"), max_conn=5)
        await ipc.start()
        try:
            assert ipc._server is not None
            assert ipc._server.gettimeout() == 0.0, "监听 socket 必须是非阻塞的"
            assert os.path.exists(ipc.socket_path)
        finally:
            await ipc.stop()

    @pytest.mark.asyncio
    async def test_accept_loop_does_not_block_event_loop(self, tmp_path):
        """起监听后事件循环仍要能跑定时器（阻塞 socket 会让这里超时）。"""
        if os.name == "nt":
            pytest.skip("Windows 上跳过 AF_UNIX 监听")

        ipc = IpcHandler(socket_path=str(tmp_path / "trimum.sock"), max_conn=5)
        await ipc.start()
        try:
            await asyncio.wait_for(asyncio.sleep(0.2), timeout=2.0)
        finally:
            await ipc.stop()

    @pytest.mark.asyncio
    async def test_stop_removes_socket_file(self, tmp_path):
        if os.name == "nt":
            pytest.skip("Windows 上跳过 AF_UNIX 监听")

        ipc = IpcHandler(socket_path=str(tmp_path / "trimum.sock"), max_conn=5)
        await ipc.start()
        await ipc.stop()

        assert not os.path.exists(ipc.socket_path)
