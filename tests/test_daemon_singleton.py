"""daemon 单实例加固回归测试（2026-09-20 真机故障）。

故障链：`trmd.service`（Restart=always）与手工 daemon 抢 127.0.0.1:8321，
单元每 5s `exit 3`，journal 里 `NRestarts` 一路涨；更隐蔽的是短命进程启动时
先 unlink 再 bind 运行中 daemon 的 `/run/user/1000/trimum.sock`，把 RPC 通道
抢走再自杀，客户端于是静默降级成 HTTP（`trm status` 显示 `source: http`）。

覆盖：启动预检必须在碰端口 / socket 之前 fail-fast，并给出可操作提示
（原先只能等 uvicorn 抛 `[Errno 98] address already in use`）。
"""

import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.main import EXIT_STARTUP_PRECONDITION, check_tcp_port, run


def free_port() -> int:
    """要一个当前空闲的端口。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


def listening_port() -> tuple[socket.socket, int]:
    """占住一个端口，返回 (socket, port)。调用方负责 close。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


class TestPortPrecheck:
    def test_free_port_passes(self):
        assert check_tcp_port("127.0.0.1", free_port()) is None

    def test_occupied_port_is_reported(self):
        sock, port = listening_port()
        try:
            assert check_tcp_port("127.0.0.1", port) is not None
        finally:
            sock.close()

    def test_run_exits_3_when_port_occupied(self, monkeypatch, capsys):
        """端口被占 → 立刻 exit 3，提示是可操作的（不是裸 errno）。"""
        sock, port = listening_port()
        try:
            monkeypatch.setattr(sys, "argv", ["trmd", "--port", str(port)])
            with pytest.raises(SystemExit) as excinfo:
                run()
        finally:
            sock.close()

        assert excinfo.value.code == EXIT_STARTUP_PRECONDITION
        err = capsys.readouterr().err
        assert f"127.0.0.1:{port}" in err
        assert "启动中止" in err
        assert "Errno" not in err


class TestSocketPrecheck:
    def test_run_exits_3_when_socket_held_by_other(
        self, tmp_path, monkeypatch, capsys
    ):
        """别人在监听同一个 unix socket → 本实例拒绝启动（不抢占）。"""
        if os.name == "nt":
            pytest.skip("Windows 上无 AF_UNIX")

        path = str(tmp_path / "trimum.sock")
        holder = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        holder.bind(path)
        holder.listen(1)

        config_file = tmp_path / "trmd-test.yaml"
        config_file.write_text(
            "core:\n"
            '  host: "127.0.0.1"\n'
            f"  port: {free_port()}\n"
            f'  socket_path: "{path}"\n',
            encoding="utf-8",
        )

        try:
            monkeypatch.setattr(sys, "argv", ["trmd", "--config", str(config_file)])
            with pytest.raises(SystemExit) as excinfo:
                run()
        finally:
            holder.close()

        assert excinfo.value.code == EXIT_STARTUP_PRECONDITION
        assert path in capsys.readouterr().err