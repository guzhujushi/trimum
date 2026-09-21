"""daemon 与客户端必须对同一个 socket 路径达成一致。

回归：`config.py` 曾把默认 socket 写死 `/run/user/1000/trimum.sock`（假设
uid=1000），而客户端 `trimum_client.discover_socket()` 走 `XDG_RUNTIME_DIR`，
换个 uid 两端就对不上（daemon 绑 A、客户端连 B）。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import config as config_module
from trimum_core.config import DEFAULT_CONFIG, Config, default_socket_path
from trimum_core.trimum_client import (
    SYSTEM_RUNTIME_SOCKET,
    discover_socket,
    socket_candidates,
)


class TestDefaultSocketPath:
    def test_follows_xdg_runtime_dir(self):
        assert default_socket_path(runtime_dir="/run/user/4242", uid=4242) == Path(
            "/run/user/4242/trimum.sock"
        )

    def test_falls_back_to_uid_when_xdg_missing(self):
        assert default_socket_path(runtime_dir="", uid=1001) == Path(
            "/run/user/1001/trimum.sock"
        )

    def test_falls_back_to_data_dir_without_uid(self, monkeypatch):
        monkeypatch.delattr(config_module.os, "getuid", raising=False)
        assert default_socket_path(runtime_dir="", uid=None) == (
            config_module.DEFAULT_DATA_DIR / "trimum.sock"
        )

    def test_default_config_uses_the_helper(self):
        assert DEFAULT_CONFIG["core"]["socket_path"] == str(default_socket_path())

    def test_config_instance_does_not_pollute_global_defaults(self):
        """浅拷贝回归：`Config.__init__` 只做 `dict(DEFAULT_CONFIG)` 时，`_raw["core"]`
        与 `DEFAULT_CONFIG["core"]` 是同一个 dict，一次 set() 就会把全局默认值改掉，
        进程内后续 `Config()` 跟着串味（socket_path 尤其致命）。"""
        config = Config()
        config.set("core.socket_path", "/tmp/hijacked.sock")

        assert DEFAULT_CONFIG["core"]["socket_path"] != "/tmp/hijacked.sock"
        assert Config().socket_path != "/tmp/hijacked.sock"


class TestClientServerAgreement:
    def test_client_matches_daemon_when_xdg_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monkeypatch.delenv("TRIMUM_SOCKET", raising=False)

        socket_file = tmp_path / "trimum.sock"
        socket_file.write_text("", encoding="utf-8")

        assert Path(discover_socket()) == socket_file
        assert Path(discover_socket()) == default_socket_path()

    def test_client_returns_runtime_dir_candidate_when_nothing_exists(
        self, tmp_path, monkeypatch
    ):
        """socket 还没建出来时不能退到数据目录 —— daemon 只在 runtime dir 建。

        这里把 uid 换成不存在的号：否则会撞上本机真 daemon 的
        `/run/user/<uid>/trimum.sock`（存在即被选中），测试就随环境飘。
        """
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monkeypatch.delenv("TRIMUM_SOCKET", raising=False)
        monkeypatch.setattr(config_module.os, "getuid", lambda: 4242, raising=False)

        assert Path(discover_socket()) == tmp_path / "trimum.sock"

    def test_trimum_socket_env_wins(self, monkeypatch):
        monkeypatch.setenv("TRIMUM_SOCKET", "/tmp/custom.sock")
        assert discover_socket() == "/tmp/custom.sock"


class TestSystemRuntimeDirSocket:
    """系统级 daemon 的 socket 在 `/run/trimum`（S1 加固：单元里 RuntimeDirectory=trimum
    + XDG_RUNTIME_DIR=/run/trimum），与登录会话的 `/run/user/<uid>` 不同名 ——
    客户端不认识这条就会永远走 HTTP 回退（真机实测：`trm status` 显示 source=http）。"""

    def test_system_runtime_socket_is_a_candidate(self, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/9999")

        candidates = socket_candidates()

        assert SYSTEM_RUNTIME_SOCKET == Path("/run/trimum/trimum.sock")
        # XDG 那条最优先（会话内的实例），系统 daemon 那条紧跟其后：
        # 会话内有 socket 就先用手上的，没有才去认系统 daemon。
        assert candidates[0] == Path("/run/user/9999/trimum.sock")
        assert candidates[1] == SYSTEM_RUNTIME_SOCKET
        # /run/user/* 的任何一条都不许排在它前面（Windows 上没有 getuid 那条）
        assert all(
            idx > 1
            for idx, path in enumerate(candidates)
            if str(path).startswith("/run/user/")
        )

    def test_discover_prefers_existing_system_socket(self, monkeypatch, tmp_path):
        """`/run/trimum/trimum.sock` 存在时应当被选中（用 monkeypatch 伪造存在性，
        不去碰真机的 /run）。"""
        monkeypatch.delenv("TRIMUM_SOCKET", raising=False)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        real_exists = Path.exists

        def fake_exists(self):
            if self == SYSTEM_RUNTIME_SOCKET:
                return True
            return real_exists(self)

        monkeypatch.setattr(Path, "exists", fake_exists)

        assert Path(discover_socket()) == SYSTEM_RUNTIME_SOCKET

    def test_session_socket_still_wins_when_present(self, monkeypatch, tmp_path):
        """会话 socket 存在时优先级更高（系统 daemon 只是兜底，不抢会话内实例）。"""
        monkeypatch.delenv("TRIMUM_SOCKET", raising=False)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        session_socket = tmp_path / "trimum.sock"
        session_socket.write_text("", encoding="utf-8")

        real_exists = Path.exists

        def fake_exists(self):
            if self == SYSTEM_RUNTIME_SOCKET:
                return True
            return real_exists(self)

        monkeypatch.setattr(Path, "exists", fake_exists)

        assert Path(discover_socket()) == session_socket