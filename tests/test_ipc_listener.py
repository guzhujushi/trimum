"""IPC Handler 监听 socket 测试。

回归点：`loop.sock_accept()` 只在 debug 模式下检查非阻塞标志。之前的实现
用阻塞 socket 调 `loop.sock_accept()`，accept() 会直接阻塞事件循环线程，
在 Linux 上表现为「daemon 起来后整体假死 / 测试挂住」。
"""

import asyncio
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.ipc_handler import IpcHandler, socket_is_live


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


class TestSocketTakeoverGuard:
    """回归：短命进程不得抢走运行中 daemon 的 unix socket。

    真机故障链（2026-09-20）：`trmd.service`（Restart=always）与手工 daemon
    抢同一个 socket，每次启动都先 unlink 别人的 socket 再 bind，自己死掉后
    留下无人监听的 socket 文件 —— 客户端于是静默降级成 HTTP
    （`trm status` 显示 `source: http`）。
    """

    @pytest.mark.asyncio
    async def test_second_handler_does_not_steal_live_socket(self, tmp_path):
        if os.name == "nt":
            pytest.skip("Windows 上跳过 AF_UNIX 监听")

        path = str(tmp_path / "trimum.sock")
        first = IpcHandler(socket_path=path, max_conn=5)
        await first.start()
        second = IpcHandler(socket_path=path, max_conn=5)
        try:
            await second.start()

            assert second._server is None, "不得抢占已有人在监听的 socket"
            assert second.socket_held_by_other is True
            assert first._server is not None, "原实例的监听不能被破坏"
            assert os.path.exists(path)

            # stop() 也不能顺手 unlink 别人的 socket
            await second.stop()
            assert os.path.exists(path)
        finally:
            await second.stop()
            await first.stop()

        assert not os.path.exists(path), "持有者 stop() 时才清理自己的 socket"

    @pytest.mark.asyncio
    async def test_stale_socket_file_is_replaced(self, tmp_path):
        """无人监听的残留文件必须照旧清理重建（不能因此起不来）。"""
        if os.name == "nt":
            pytest.skip("Windows 上跳过 AF_UNIX 监听")

        path = str(tmp_path / "trimum.sock")
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(path)
        stale.close()  # 只留文件，没有 listener
        assert os.path.exists(path)

        ipc = IpcHandler(socket_path=path, max_conn=5)
        await ipc.start()
        try:
            assert ipc._server is not None
            assert ipc.socket_held_by_other is False
        finally:
            await ipc.stop()

        assert not os.path.exists(path)

    def test_socket_is_live_is_false_for_missing_path(self, tmp_path):
        assert socket_is_live(str(tmp_path / "nope.sock")) is False