"""纯逻辑测 `bpf_helper_main`（不碰真 socket / 不碰 systemd / 不碰 /run）：
只测 `UnavailableLoader`、`build_loader`、`main`（`serve` 用假实现注入，不真起服务）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 允许直接 `pytest tests/test_bpf_helper_main.py`（无需 pip 安装本包）：把 src 挂上 sys.path。
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402

from trimum_core.bpf_helper import LoaderError  # noqa: E402
from trimum_core.bpf_helper_main import (  # noqa: E402
    UnavailableLoader, build_loader, main,
)


class FakeServe:
    """记录调用、返回 int 的假 serve（不真起 socket）。"""

    def __init__(self, return_value: int = 0, exc: BaseException | None = None):
        self.calls: list[dict] = []
        self._return = return_value
        self._exc = exc

    def __call__(self, sock, *, loader, allowed_uids, max_requests=None, **_kw):
        self.calls.append({
            "sock": sock,
            "loader": loader,
            "allowed_uids": allowed_uids,
            "max_requests": max_requests,
        })
        if self._exc is not None:
            raise self._exc
        return self._return


# ---- UnavailableLoader：如实报不可用，绝不假装在监控 ----

def test_stats_reports_unavailable():
    stats = UnavailableLoader().stats()
    assert stats.get("available") is False
    assert isinstance(stats.get("reason"), str) and stats["reason"]


def test_load_raises_loadererror_with_message():
    with pytest.raises(LoaderError) as ei:
        UnavailableLoader().load("bpf_guard")
    assert str(ei.value).strip()


def test_unload_raises_loadererror_with_message():
    with pytest.raises(LoaderError) as ei:
        UnavailableLoader().unload("exec_guard")
    assert str(ei.value).strip()


def test_tail_raises_loadererror_with_message():
    with pytest.raises(LoaderError) as ei:
        UnavailableLoader().tail(10)
    assert str(ei.value).strip()


# ---- build_loader：现在恒返回一个带四方法的 loader ----

def test_build_loader_returns_unavailable_loader():
    loader = build_loader()
    assert isinstance(loader, UnavailableLoader)
    for name in ("load", "unload", "stats", "tail"):
        assert hasattr(loader, name)
        assert callable(getattr(loader, name))


def test_build_loader_stats_unavailable():
    assert build_loader().stats()["available"] is False


# ---- main：纯逻辑（serve 注入假实现，不真起服务）----

def test_main_help_exits_zero():
    with pytest.raises(SystemExit) as ei:
        main(["--help"])
    assert ei.value.code == 0


def test_main_once_socket_uses_injected_serve(tmp_path):
    fake = FakeServe(return_value=0)
    sock_file = tmp_path / "priv.sock"
    ret = main(["--once", "--socket", str(sock_file)], serve_fn=fake)
    assert ret == 0
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert str(call["sock"]) == str(sock_file)
    assert call["max_requests"] == 1


def test_main_without_once_max_requests_none(tmp_path):
    fake = FakeServe(return_value=0)
    sock_file = tmp_path / "priv.sock"
    ret = main(["--socket", str(sock_file)], serve_fn=fake)
    assert ret == 0
    assert len(fake.calls) == 1
    assert fake.calls[0]["max_requests"] is None


def test_main_loader_injected_and_available_flag_false(tmp_path):
    fake = FakeServe(return_value=0)
    sock_file = tmp_path / "priv.sock"
    main(["--socket", str(sock_file)], serve_fn=fake)
    assert fake.calls[0]["loader"].stats()["available"] is False


def test_main_serve_raises_returns_one(tmp_path):
    fake = FakeServe(exc=OSError("bind 失败"))
    sock_file = tmp_path / "priv.sock"
    ret = main(["--socket", str(sock_file)], serve_fn=fake)
    assert ret == 1
    assert len(fake.calls) == 1


def test_main_allows_env_socket_override(tmp_path, monkeypatch):
    # socket 路径优先级：--socket 显式 > env。这里只给 env，不给 --socket，
    # 验证 env TRIMUM_BPF_SOCKET 生效（helper 的「显式 > env > 默认」口径）。
    env_sock = tmp_path / "env.sock"
    monkeypatch.setenv("TRIMUM_BPF_SOCKET", str(env_sock))
    fake = FakeServe(return_value=0)
    ret = main([], serve_fn=fake)
    assert ret == 0
    assert str(fake.calls[0]["sock"]) == str(env_sock)


# ---- F2：入口真的用上配置层（config / env / --allow-uid 优先级链）----

def _strip_uid_env(monkeypatch):
    monkeypatch.delenv("TRIMUM_BPF_ALLOWED_UIDS", raising=False)


def _fake_config(*, socket_key, uid_key, socket_val, uid_val):
    """假配置对象：只提供本单要读的两个键（`security.bpf_socket` / `security.bpf_helper_allowed_uids`）。"""

    class FakeConfig:
        def get(self, key, default=None):
            if key == socket_key:
                return socket_val
            if key == uid_key:
                return uid_val
            return default

    return FakeConfig()


def test_main_config_socket_and_uids(tmp_path, monkeypatch):
    # 传假 config（socket=/tmp/x.sock、uid=[1000,1001]）+ 假 serve_fn，
    # 断言 serve 收到的 sock == 配置里的路径、allowed_uids == 配置里的集合。
    monkeypatch.delenv("TRIMUM_BPF_SOCKET", raising=False)
    _strip_uid_env(monkeypatch)
    sock_val = str(tmp_path / "x.sock")
    fake_cfg = _fake_config(socket_key="security.bpf_socket",
                            uid_key="security.bpf_helper_allowed_uids",
                            socket_val=sock_val, uid_val=[1000, 1001])
    fake = FakeServe(return_value=0)
    ret = main([], serve_fn=fake, config=fake_cfg)
    assert ret == 0
    assert len(fake.calls) == 1
    assert str(fake.calls[0]["sock"]) == sock_val
    assert fake.calls[0]["allowed_uids"] == frozenset({1000, 1001})


def test_main_env_uids_override_config(tmp_path, monkeypatch):
    # env TRIMUM_BPF_ALLOWED_UIDS 覆盖配置：配置给 [1000,1001]，env 给 "7,8" ⇒ {7,8}。
    monkeypatch.delenv("TRIMUM_BPF_SOCKET", raising=False)
    monkeypatch.setenv("TRIMUM_BPF_ALLOWED_UIDS", "7,8")
    fake_cfg = _fake_config(socket_key="security.bpf_socket",
                            uid_key="security.bpf_helper_allowed_uids",
                            socket_val=str(tmp_path / "x.sock"), uid_val=[1000, 1001])
    fake = FakeServe(return_value=0)
    ret = main([], serve_fn=fake, config=fake_cfg)
    assert ret == 0
    assert fake.calls[0]["allowed_uids"] == frozenset({7, 8})


def test_main_allow_uid_flag_override_env(tmp_path, monkeypatch):
    # --allow-uid 9 覆盖 env TRIMUM_BPF_ALLOWED_UIDS=7,8 ⇒ {9}（flag 优先级最高）。
    monkeypatch.delenv("TRIMUM_BPF_SOCKET", raising=False)
    monkeypatch.setenv("TRIMUM_BPF_ALLOWED_UIDS", "7,8")
    fake = FakeServe(return_value=0)
    ret = main(["--allow-uid", "9"], serve_fn=fake)
    assert ret == 0
    assert fake.calls[0]["allowed_uids"] == frozenset({9})
