"""eBPF 特权 helper 本体测试（socket 门 + 分发）：所有用例真调被测函数；socket 一律走 `tmp_path`，不碰真 /run/trimum。"""
from __future__ import annotations

import json
import os
import socket
import stat
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import bpf_helper as H  # noqa: E402


class _FakeLoader:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else {"ok": 1}
        self.error = error
        self.calls: list[tuple] = []

    def _record(self, name, *args):
        self.calls.append((name,) + args)
        if self.error is not None:
            raise self.error

    def load(self, program):
        self._record("load", program)
        return self.result

    def unload(self, program):
        self._record("unload", program)
        return self.result

    def stats(self):
        self._record("stats")
        return self.result

    def tail(self, limit):
        self._record("tail", limit)
        return self.result


class _Cfg:
    def __init__(self, value, raise_exc=False):
        self.value = value
        self.raise_exc = raise_exc

    def get(self, key):
        if self.raise_exc:
            raise RuntimeError("config boom")
        return self.value


class _ExplodingDeny:
    def __init__(self):
        self.calls = []

    def __call__(self, verb, code, peer_uid):
        self.calls.append((verb, code, peer_uid))
        raise RuntimeError("deny boom")


def _req_bytes(verb, **extra):
    obj = {"verb": verb}
    obj.update(extra)
    return json.dumps(obj).encode("utf-8")


# ---- socket_path：四优先级 + 坏值回默认 ----

def test_socket_path_explicit_wins(monkeypatch):
    monkeypatch.setenv(H.SOCKET_ENV, "/tmp/env-sock")
    assert H.socket_path(explicit="/tmp/explicit.sock") == __import__("pathlib").Path("/tmp/explicit.sock")


def test_socket_path_env(monkeypatch):
    monkeypatch.setenv(H.SOCKET_ENV, "/tmp/env-sock")
    assert H.socket_path() == __import__("pathlib").Path("/tmp/env-sock")


def test_socket_path_config_beats_default(monkeypatch):
    monkeypatch.delenv(H.SOCKET_ENV, raising=False)
    assert H.socket_path(config=_Cfg("/tmp/cfg-sock")) == __import__("pathlib").Path("/tmp/cfg-sock")


def test_socket_path_default(monkeypatch):
    monkeypatch.delenv(H.SOCKET_ENV, raising=False)
    assert H.socket_path() == __import__("pathlib").Path(H.DEFAULT_SOCKET_PATH)
    assert H.socket_path(config=_Cfg(None)) == __import__("pathlib").Path(H.DEFAULT_SOCKET_PATH)


def test_socket_path_bad_values_fall_back(monkeypatch):
    monkeypatch.setenv(H.SOCKET_ENV, "   ")
    assert H.socket_path(config=_Cfg(123)) == __import__("pathlib").Path(H.DEFAULT_SOCKET_PATH)
    assert H.socket_path(config=_Cfg("", )) == __import__("pathlib").Path(H.DEFAULT_SOCKET_PATH)
    assert H.socket_path(config=_Cfg(None, raise_exc=True)) == __import__("pathlib").Path(H.DEFAULT_SOCKET_PATH)


# ---- allowed_uids ----

def test_allowed_uids_explicit_sequence():
    assert H.allowed_uids(explicit=[1000, 1001]) == frozenset({1000, 1001})
    assert H.allowed_uids(explicit=(1000,)) == frozenset({1000})


def test_allowed_uids_explicit_string():
    assert H.allowed_uids(explicit="1000,1001") == frozenset({1000, 1001})
    assert H.allowed_uids(explicit="1000 1001") == frozenset({1000, 1001})
    assert H.allowed_uids(explicit=" 1000 , 1001 ") == frozenset({1000, 1001})


def test_allowed_uids_skips_bool_negative_garbage():
    assert H.allowed_uids(explicit=[True, False, -1, "abc", None, 7, 5]) == frozenset({5, 7})
    assert H.allowed_uids(explicit="1000,-1,xyz,") == frozenset({1000})


def test_allowed_uids_config_and_default():
    assert H.allowed_uids(config=_Cfg([2000, 2001])) == frozenset({2000, 2001})
    assert H.allowed_uids(config=_Cfg("1,2")) == frozenset({1, 2})
    assert H.allowed_uids(default=[3000]) == frozenset({3000})
    assert H.allowed_uids(default=None) == frozenset()
    assert H.allowed_uids() == frozenset()
    # 配置优先级高于 default；显式优先于配置
    assert H.allowed_uids(config=_Cfg("1"), default=[2]) == frozenset({1})
    assert H.allowed_uids(explicit=[9], config=_Cfg("1")) == frozenset({9})


def test_allowed_uids_bad_config_uses_default():
    assert H.allowed_uids(config=_Cfg(123), default=[42]) == frozenset({42})
    assert H.allowed_uids(config=_Cfg(None, raise_exc=True), default="7,8") == frozenset({7, 8})
    assert H.allowed_uids(config=_Cfg(123), default=None) == frozenset()


# ---- handle_request：uid 门 ----

def test_handle_request_peer_denied_loader_never_called():
    loader = _FakeLoader()
    resp = json.loads(H.handle_request(
        _req_bytes("bpf.stats"), loader=loader, peer_uid=9999, allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is False and resp["error"] == "peer_denied"
    assert loader.calls == []


def test_handle_request_allowed_uid_continues():
    loader = _FakeLoader({"ok": 1})
    resp = json.loads(H.handle_request(
        _req_bytes("bpf.stats"), loader=loader, peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is True and loader.calls == [("stats",)]


# ---- handle_request：四动词 happy ----

def test_handle_request_load_happy():
    loader = _FakeLoader({"loaded": True})
    resp = json.loads(H.handle_request(
        _req_bytes("bpf.load", program="bpf_guard", request_id="r-1"),
        loader=loader, peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp == {"ok": True, "request_id": "r-1", "data": {"loaded": True}, "error": ""}
    assert loader.calls == [("load", "bpf_guard")]


def test_handle_request_unload_happy():
    loader = _FakeLoader({"unloaded": True})
    resp = json.loads(H.handle_request(
        _req_bytes("bpf.unload", program="exec_guard", request_id="r-2"),
        loader=loader, peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is True and resp["data"] == {"unloaded": True} and resp["request_id"] == "r-2"
    assert loader.calls == [("unload", "exec_guard")]


def test_handle_request_stats_happy():
    loader = _FakeLoader({"stats": [1, 2, 3]})
    resp = json.loads(H.handle_request(
        _req_bytes("bpf.stats", request_id="r-3"),
        loader=loader, peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is True and resp["data"] == {"stats": [1, 2, 3]} and resp["request_id"] == "r-3"
    assert loader.calls == [("stats",)]


def test_handle_request_tail_passes_limit():
    loader = _FakeLoader({"lines": []})
    resp = json.loads(H.handle_request(
        _req_bytes("bpf.tail", params={"limit": 42}, request_id="r-4"),
        loader=loader, peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is True and resp["data"] == {"lines": []} and resp["request_id"] == "r-4"
    assert loader.calls == [("tail", 42)]


# ---- handle_request：错误分支 ----

def test_handle_request_bad_json():
    loader = _FakeLoader()
    resp = json.loads(H.handle_request(b"{not json", loader=loader,
                                       peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is False and resp["error"] == "bad_json" and loader.calls == []


def test_handle_request_unknown_verb():
    loader = _FakeLoader()
    resp = json.loads(H.handle_request(_req_bytes("bpf.warp"), loader=loader,
                                       peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is False and resp["error"] == "bad_verb" and loader.calls == []


def test_handle_request_stats_with_program_bad_program():
    loader = _FakeLoader()
    resp = json.loads(H.handle_request(
        _req_bytes("bpf.stats", program="bpf_guard"), loader=loader,
        peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is False and resp["error"] == "bad_program" and loader.calls == []


def test_handle_request_too_large():
    payload = b'{"verb": "bpf.stats", "request_id": "' + b"x" * 5000 + b'"}'
    resp = json.loads(H.handle_request(payload, loader=_FakeLoader(),
                                       peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is False and resp["error"] == "too_large"


def test_handle_request_loader_error():
    loader = _FakeLoader(error=H.LoaderError("nope"))
    resp = json.loads(H.handle_request(_req_bytes("bpf.stats", request_id="r-e1"),
                                       loader=loader, peer_uid=1000,
                                       allowed_uids={1000}).decode("utf-8"))
    assert resp == {"ok": False, "request_id": "r-e1", "data": {}, "error": "nope"}
    assert loader.calls == [("stats",)]


def test_handle_request_loader_internal_error():
    loader = _FakeLoader(error=RuntimeError("boom"))
    resp = json.loads(H.handle_request(_req_bytes("bpf.load", program="bpf_guard", request_id="r-e2"),
                                       loader=loader, peer_uid=1000,
                                       allowed_uids={1000}).decode("utf-8"))
    assert resp == {"ok": False, "request_id": "r-e2", "data": {}, "error": "internal"}


def test_handle_request_loader_non_dict_return():
    loader = _FakeLoader(result="not-a-dict")
    resp = json.loads(H.handle_request(_req_bytes("bpf.stats", request_id="r-e3"),
                                       loader=loader, peer_uid=1000,
                                       allowed_uids={1000}).decode("utf-8"))
    assert resp["ok"] is True and resp["data"] == {} and resp["request_id"] == "r-e3"


# ---- on_denied 回调 ----

def test_on_denied_called_once_per_branch_with_args():
    cases = [
        (b"{not json", "bad_json"),
        (json.dumps({"verb": "nope"}).encode(), "bad_verb"),
    ]
    for raw, expected_code in cases:
        seen: list[tuple] = []
        resp = json.loads(H.handle_request(raw, loader=_FakeLoader(), peer_uid=1000,
                                           allowed_uids={1000},
                                           on_denied=lambda v, c, u: seen.append((v, c, u))).decode("utf-8"))
        assert resp["error"] == expected_code
        assert seen == [("", expected_code, 1000)]

    seen = []
    H.handle_request(_req_bytes("bpf.stats"), loader=_FakeLoader(), peer_uid=4242,
                     allowed_uids={1000},
                     on_denied=lambda v, c, u: seen.append((v, c, u)))
    assert seen == [("", "peer_denied", 4242)]

    seen = []
    H.handle_request(_req_bytes("bpf.stats", request_id="r-d"), loader=_FakeLoader(error=H.LoaderError("nope")),
                     peer_uid=1000, allowed_uids={1000},
                     on_denied=lambda v, c, u: seen.append((v, c, u)))
    assert seen == [("bpf.stats", "loader_error", 1000)]

    seen = []
    H.handle_request(_req_bytes("bpf.stats"), loader=_FakeLoader(error=RuntimeError("x")),
                     peer_uid=1000, allowed_uids={1000},
                     on_denied=lambda v, c, u: seen.append((v, c, u)))
    assert seen == [("bpf.stats", "internal", 1000)]


def test_on_denied_raising_is_swallowed():
    resp = json.loads(H.handle_request(
        b"{not json", loader=_FakeLoader(), peer_uid=1000, allowed_uids={1000},
        on_denied=_ExplodingDeny()).decode("utf-8"))
    assert resp["ok"] is False and resp["error"] == "bad_json"


def test_on_denied_none_does_not_raise():
    resp = json.loads(H.handle_request(b"{not json", loader=_FakeLoader(),
                                       peer_uid=1000, allowed_uids={1000}).decode("utf-8"))
    assert resp["error"] == "bad_json"
    resp2 = json.loads(H.handle_request(_req_bytes("bpf.stats"), loader=_FakeLoader(),
                                        peer_uid=9999, allowed_uids={1000}).decode("utf-8"))
    assert resp2["error"] == "peer_denied"


# ---- serve 冒烟（唯一允许起线程的用例） ----

def _client_send(sock_path_str: str, payload: bytes) -> dict:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        deadline = time.time() + 10
        while True:
            try:
                client.connect(sock_path_str)
                break
            except (ConnectionRefusedError, FileNotFoundError):
                if time.time() >= deadline:
                    raise
                time.sleep(0.02)
        client.sendall(payload)
        deadline = time.time() + 10
        chunks = []
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise AssertionError("client recv timeout")
            client.settimeout(remaining)
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        return json.loads(b"".join(chunks).decode("utf-8"))
    finally:
        client.close()


def test_serve_smoke(tmp_path, monkeypatch):
    monkeypatch.delenv(H.SOCKET_ENV, raising=False)
    sock_file = tmp_path / "priv.sock"
    loader = _FakeLoader({"n": 0})

    def _wait_socket():
        deadline = time.time() + 10
        while not sock_file.exists() and time.time() < deadline:
            time.sleep(0.02)
        assert sock_file.exists()

    # ---- 第一段：空 allowed_uids ⇒ 必然 peer_denied，从回调里学到真实 peer uid ----
    denied: list[tuple] = []
    result: dict = {}

    def _cap(verb, code, peer_uid):
        denied.append((verb, code, peer_uid))

    def _serve1():
        try:
            result["count"] = H.serve(str(sock_file), loader=loader,
                                      allowed_uids=frozenset(), max_requests=1, on_denied=_cap)
        except BaseException as exc:  # pragma: no cover - 测试断言用
            result["error"] = exc

    thread = threading.Thread(target=_serve1, daemon=True)
    thread.start()
    try:
        _wait_socket()
        first = _client_send(str(sock_file), _req_bytes("bpf.stats", request_id="d-1"))
        assert first["ok"] is False and first["error"] == "peer_denied"
        assert len(denied) == 1
        assert denied[0][1] == "peer_denied"
        learned_uid = denied[0][2]
        assert isinstance(learned_uid, int) and learned_uid >= 0
    finally:
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert "error" not in result
    assert result.get("count") == 1
    assert not sock_file.exists()

    # ---- 第二段：用学到的 peer uid 放行 ⇒ 两次都成功，服务按 max_requests 收尾 ----
    result.clear()

    def _serve2():
        try:
            result["count"] = H.serve(str(sock_file), loader=loader,
                                      allowed_uids={learned_uid}, max_requests=2)
        except BaseException as exc:  # pragma: no cover - 测试断言用
            result["error"] = exc

    thread = threading.Thread(target=_serve2, daemon=True)
    thread.start()
    try:
        _wait_socket()
        first = _client_send(str(sock_file), _req_bytes("bpf.stats", request_id="s-1"))
        assert first["ok"] is True and first["data"] == {"n": 0} and first["request_id"] == "s-1"
        mode = stat.S_IMODE(os.stat(str(sock_file)).st_mode)
        assert mode == 0o660
        second = _client_send(str(sock_file), _req_bytes("bpf.stats", request_id="s-2"))
        assert second["ok"] is True and second["request_id"] == "s-2"
    finally:
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert "error" not in result
    assert result.get("count") == 2
    assert not sock_file.exists()


def test_serve_gate_uses_the_uid_field_not_the_pid_field(tmp_path):
    """`serve()` 取 SO_PEERCRED 的 **uid**（`struct ucred` 下标 1 = {pid, uid, gid}），不是 pid（下标 0）。

    回归（2026-10-08 真机冒烟抓到的真 bug）：原来取 `[0]` ⇒ 白名单里放的是 uid、实际拿到的是**对端 pid**
    ⇒ 永远匹配不上 ⇒ 连放行 uid 都被判 peer_denied（表现成「helper 装了但全拒」，日志里 `peer_uid=` 是百万级 pid）。
    判据：用 `{os.getuid()}` 放行**自己**（同进程发的连接）必须成功 —— 取成 pid 时除非 pid 恰好等于 uid，必被拒。
    """
    sock_file = tmp_path / "priv.sock"
    loader = _FakeLoader({"available": True})
    result: dict = {}

    def _serve():
        try:
            result["count"] = H.serve(str(sock_file), loader=loader,
                                      allowed_uids={os.getuid()}, max_requests=1)
        except BaseException as exc:  # pragma: no cover - 断言/跳过用
            result["error"] = exc

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not sock_file.exists() and time.time() < deadline and "error" not in result:
        time.sleep(0.02)
    if not sock_file.exists():
        thread.join(timeout=10)
        exc = result.get("error")
        if exc is not None:
            pytest.skip(f"环境不许 bind AF_UNIX socket（{exc!r}）；本条只在能真起 socket 的环境里跑")
        pytest.fail("socket 一直没出现，且 serve() 没报错")
    try:
        response = _client_send(str(sock_file), _req_bytes("bpf.stats"))
    finally:
        thread.join(timeout=10)
    assert response.get("error") != "peer_denied", (
        "本进程 uid == 放行 uid 却被拒 ⇒ 取的不是 uid 字段（取成 pid 了）")
    assert response["ok"] is True and response["data"] == {"available": True}
    assert result.get("count") == 1
    assert not sock_file.exists()
