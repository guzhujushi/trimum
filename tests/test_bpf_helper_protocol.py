"""eBPF 特权 helper 协议层测试（纯逻辑：动词白名单 + 参数校验 + 清单校验）。

口径：所有用例**真调**被测函数；协议层不碰 socket / 内核 / root。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import bpf_helper_protocol as P  # noqa: E402


def _req(obj: dict) -> bytes:
    return json.dumps(obj).encode("utf-8")


# ---- happy path：四个动词各一条 ----

def test_load_happy_path():
    r = P.parse_request(_req({"verb": "bpf.load", "program": "bpf_guard"}))
    assert r.verb == "bpf.load"
    assert r.program == "bpf_guard"
    assert r.params == {}
    assert r.request_id == ""


def test_unload_happy_path():
    r = P.parse_request(_req({"verb": "bpf.unload", "program": "exec_guard"}))
    assert r.verb == "bpf.unload"
    assert r.program == "exec_guard"


def test_stats_happy_path():
    r = P.parse_request(_req({"verb": "bpf.stats", "request_id": "req.1_x-2"}))
    assert r.verb == "bpf.stats"
    assert r.program is None
    assert r.request_id == "req.1_x-2"


def test_tail_happy_path():
    r = P.parse_request(_req({"verb": "bpf.tail"}))
    assert r.verb == "bpf.tail"
    assert r.program is None


# ---- params：缺省 / 保留 / 新 dict ----

def test_params_default_empty_dict():
    r = P.parse_request(_req({"verb": "bpf.stats"}))
    assert r.params == {}
    assert isinstance(r.params, dict)


def test_params_preserved_and_fresh_copy():
    obj = {"verb": "bpf.load", "program": "bpf_guard", "params": {"pid": 42}}
    first = P.parse_request(_req(obj))
    first.params["pid"] = -999
    second = P.parse_request(_req(obj))
    assert second.params == {"pid": 42}
    assert first.params is not second.params


# ---- bad_json / not_object / too_large ----

def test_bad_json_non_bytes():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request("not bytes".encode().decode())
    assert exc.value.code == P.CODE_BAD_JSON


def test_bad_json_broken_json():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(b'{"verb": "bpf.stats",')
    assert exc.value.code == P.CODE_BAD_JSON


def test_not_object():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(b"[1,2]")
    assert exc.value.code == P.CODE_NOT_OBJECT


def test_too_large():
    payload = {"verb": "bpf.stats", "request_id": "x" * (P.MAX_REQUEST_BYTES)}
    raw = json.dumps(payload).encode("utf-8")
    assert len(raw) > P.MAX_REQUEST_BYTES
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(raw)
    assert exc.value.code == P.CODE_TOO_LARGE


# ---- unknown_field：协议上不接受命令字符串 ----

def test_unknown_field_cmd_rejected():
    raw = _req({"verb": "bpf.stats", "cmd": "rm -rf /"})
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(raw)
    assert exc.value.code == P.CODE_UNKNOWN_FIELD


# ---- bad_verb / bad_program ----

def test_bad_verb():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(_req({"verb": "bpf.exec", "program": "bpf_guard"}))
    assert exc.value.code == P.CODE_BAD_VERB


def test_bad_program_unknown_name():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(_req({"verb": "bpf.load", "program": "evil_prog"}))
    assert exc.value.code == P.CODE_BAD_PROGRAM


def test_bad_program_given_for_stats():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(_req({"verb": "bpf.stats", "program": "bpf_guard"}))
    assert exc.value.code == P.CODE_BAD_PROGRAM


# ---- bad_params 三种 ----

def test_bad_params_string_value():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(_req({"verb": "bpf.load", "program": "bpf_guard", "params": {"pid": "42"}}))
    assert exc.value.code == P.CODE_BAD_PARAMS


def test_bad_params_bool_value():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(_req({"verb": "bpf.load", "program": "bpf_guard", "params": {"pid": True}}))
    assert exc.value.code == P.CODE_BAD_PARAMS


def test_bad_params_out_of_range():
    for value in (-1, P.MAX_PARAM_INT + 1):
        with pytest.raises(P.ProtocolError) as exc:
            P.parse_request(_req(
                {"verb": "bpf.load", "program": "bpf_guard", "params": {"pid": value}}))
        assert exc.value.code == P.CODE_BAD_PARAMS


# ---- bad_request_id ----

def test_bad_request_id_illegal_char():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(_req({"verb": "bpf.stats", "request_id": "a b"}))
    assert exc.value.code == P.CODE_BAD_REQUEST_ID


def test_bad_request_id_too_long():
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_request(_req({"verb": "bpf.stats", "request_id": "a" * (P.MAX_REQUEST_ID_LEN + 1)}))
    assert exc.value.code == P.CODE_BAD_REQUEST_ID


# ---- peer_allowed ----

def test_peer_allowed_hits_and_misses():
    assert P.peer_allowed(1000, [1000, 0]) is True
    assert P.peer_allowed(1001, [1000, 0]) is False
    assert P.peer_allowed(True, [1]) is False
    assert P.peer_allowed(1, [True]) is False


# ---- parse_manifest ----

def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_parse_manifest_normal():
    text = (
        "# 清单\n"
        "bpf_guard  " + _sha(b"guard") + "\n"
        "\n"
        "exec_guard  " + _sha(b"exec") + "\n"
    )
    manifest = P.parse_manifest(text)
    assert manifest == {"bpf_guard": _sha(b"guard"), "exec_guard": _sha(b"exec")}


@pytest.mark.parametrize("text", [
    "bpf_guard\n",                      # 字段数 != 2
    "bpf_guard " + "0" * 63 + "\n",     # 坏 hex（63 位）
    "evil_prog " + "0" * 64 + "\n",     # 未知名
    "bpf_guard " + "0" * 64 + "\nbpf_guard " + "1" * 64 + "\n",  # 重名
])
def test_parse_manifest_bad_lines(text):
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_manifest(text)
    assert exc.value.code == P.CODE_BAD_MANIFEST


def test_parse_manifest_empty_string():
    assert P.parse_manifest("") == {}


# ---- verify_program ----

def test_verify_program_pass_and_unknown():
    blob = b"guard"
    manifest = {"bpf_guard": _sha(blob)}
    assert P.verify_program("bpf_guard", blob, manifest) is None
    with pytest.raises(P.ProtocolError) as exc:
        P.verify_program("exec_guard", blob, manifest)
    assert exc.value.code == P.CODE_UNKNOWN_PROGRAM


def test_verify_program_hash_mismatch():
    blob = b"guard"
    manifest = {"bpf_guard": _sha(blob)}
    tampered = blob + b"x"
    with pytest.raises(P.ProtocolError) as exc:
        P.verify_program("bpf_guard", tampered, manifest)
    assert exc.value.code == P.CODE_HASH_MISMATCH


# ---- manifest_path 四条优先级 ----

class _Cfg:
    def __init__(self, value):
        self._value = value

    def get(self, key):
        assert key == P.MANIFEST_CONFIG_KEY
        return self._value


class _RaisingCfg:
    def get(self, key):
        raise RuntimeError("boom")


def test_manifest_path_priority(monkeypatch):
    monkeypatch.setenv(P.MANIFEST_ENV, "/env/path.txt")
    config = _Cfg("/cfg/path.txt")
    assert P.manifest_path(explicit="/x.txt", config=config) == Path("/x.txt")
    assert P.manifest_path(config=config) == Path("/env/path.txt")
    monkeypatch.delenv(P.MANIFEST_ENV)
    assert P.manifest_path(config=config) == Path("/cfg/path.txt")
    assert P.manifest_path() == Path(P.DEFAULT_MANIFEST_PATH)
    assert P.manifest_path(config=_Cfg("")) == Path(P.DEFAULT_MANIFEST_PATH)


def test_manifest_path_config_raises_falls_back(monkeypatch):
    monkeypatch.delenv(P.MANIFEST_ENV, raising=False)
    assert P.manifest_path(config=_RaisingCfg()) == Path(P.DEFAULT_MANIFEST_PATH)


# ---- encode_response / parse_response ----

def test_response_roundtrip():
    raw = P.encode_response(ok=True, request_id="r1", data={"n": 2}, error="")
    assert raw.endswith(b"\n")
    parsed = P.parse_response(raw)
    assert parsed == {"ok": True, "request_id": "r1", "data": {"n": 2}, "error": ""}
    assert parsed["data"] is not {"n": 2}


def test_parse_response_bad_ok():
    raw = P.encode_response(ok=True, request_id="r1", data=None, error="")
    obj = json.loads(raw)
    obj["ok"] = "yes"
    with pytest.raises(P.ProtocolError) as exc:
        P.parse_response(json.dumps(obj).encode("utf-8"))
    assert exc.value.code == P.CODE_BAD_JSON
