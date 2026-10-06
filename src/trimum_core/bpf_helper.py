"""eBPF 特权 helper 本体：unix socket 收动词 + SO_PEERCRED 门 + 分发给可注入的 loader（不含 eBPF 加载本身）。"""
from __future__ import annotations

import json
import logging
import os
import socket
import struct
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from .bpf_helper_protocol import (
    CODE_BAD_JSON, MAX_REQUEST_ID_LEN, ProtocolError, REQUEST_ID_RE, encode_response,
    parse_request, peer_allowed,

)

# ---- 常量（逐字） ----
DEFAULT_SOCKET_PATH: str = "/run/trimum/priv.sock"
SOCKET_ENV: str = "TRIMUM_BPF_SOCKET"
SOCKET_CONFIG_KEY: str = "security.bpf_socket"
ALLOWED_UIDS_CONFIG_KEY: str = "security.bpf_helper_allowed_uids"
SOCKET_MODE: int = 0o660
MAX_REQUEST_BYTES: int = 4096
RECV_TIMEOUT_SECONDS: float = 5.0

log = logging.getLogger("trimum_core.bpf_helper")


class LoaderError(Exception):
    """loader 侧拒绝（加载失败 / 程序不可用…）；helper 捕获后回 `ok:false`，**绝不崩**。"""


def socket_path(*, explicit: str | os.PathLike[str] | None = None,
                config: object | None = None) -> Path:
    """socket 路径，优先级 **显式 > env `TRIMUM_BPF_SOCKET` > `config.get("security.bpf_socket")` > 默认**；
    缺失 / 空串 / 非字符串 / 取值抛异常 ⇒ **静默走默认**（不许抛）。返回 `Path(...)`，不 expanduser / resolve / 建目录。"""
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get(SOCKET_ENV)
    if env_value is not None and env_value.strip():
        return Path(env_value)
    if config is not None:
        try:
            value = config.get(SOCKET_CONFIG_KEY)
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return Path(value)
    return Path(DEFAULT_SOCKET_PATH)


def allowed_uids(*, explicit: "Iterable[int] | str | None" = None,
                 config: object | None = None,
                 default: "Iterable[int] | None" = None) -> frozenset[int]:
    """允许的对端 uid 集合。优先级 **显式 > `config.get("security.bpf_helper_allowed_uids")` > `default`**。

    - 值可以是 `[1000, 1001]` 这种序列，也可以是 `"1000,1001"` / `"1000 1001"` 这种字符串（逗号/空白分隔）；
    - 逐项转 int：**bool 一律跳过**、负数跳过、转不动跳过；
    - 配置缺失 / 类型不对 / 取值抛异常 ⇒ 用 `default`（`default is None` ⇒ 空 `frozenset()`）——**静默，不许抛**。
    """
    if explicit is not None:
        return _coerce_uids(explicit)
    if config is not None:
        try:
            value = config.get(ALLOWED_UIDS_CONFIG_KEY)
        except Exception:
            value = None
        if isinstance(value, (str, list, tuple, set, frozenset)):
            return _coerce_uids(value)
    if default is not None:
        return _coerce_uids(default)
    return frozenset()


def _coerce_uids(value: object) -> frozenset[int]:
    """把「序列 / 逗号或空白分隔字符串」逐项转 int 的 frozenset；bool / 负数 / 转不动 / 整体非序列非字符串 ⇒ 跳过（不抛）。"""
    if isinstance(value, str):
        items = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = value
    else:
        return frozenset()
    result: set[int] = set()
    for item in items:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            if item >= 0:
                result.add(item)
            continue
        if isinstance(item, str):
            try:
                uid = int(item)
            except ValueError:
                continue
            if uid >= 0:
                result.add(uid)
    return frozenset(result)


# ---- loader 契约（用 `typing.Protocol` 声明即可；helper 只按方法名调用，不做 isinstance） ----
class Loader(Protocol):
    def load(self, program: str) -> dict[str, Any]: ...      # 成功返回 dict；拒绝抛 LoaderError
    def unload(self, program: str) -> dict[str, Any]: ...
    def stats(self) -> dict[str, Any]: ...
    def tail(self, limit: int) -> dict[str, Any]: ...


def _call_on_denied(on_denied: "Callable[[str, str, int], None] | None",
                    verb: str, code: str, peer_uid: int) -> None:
    """拒绝点：回调（吞掉它自己的异常）或至少 `log.warning`。"""
    if on_denied is None:
        log.warning("bpf_helper: 拒绝 verb=%r code=%s peer_uid=%d", verb, code, peer_uid)
        return
    try:
        on_denied(verb, code, peer_uid)
    except Exception:
        log.warning("bpf_helper: on_denied 回调自身抛异常（verb=%r code=%s peer_uid=%d）",
                    verb, code, peer_uid, exc_info=True)


def _dispatch(loader: object, request: object) -> dict[str, Any]:
    """按 `request.verb` 去掉 `bpf.` 前缀后调 loader 对应方法；返回 dict（非 dict ⇒ `{}`）。"""
    verb: str = request.verb
    method_name = verb[len("bpf."):] if verb.startswith("bpf.") else verb
    method = getattr(loader, method_name)
    if verb == "bpf.load":
        result = method(request.program)
    elif verb == "bpf.unload":
        result = method(request.program)
    elif verb == "bpf.stats":
        result = method()
    elif verb == "bpf.tail":
        result = method(int(request.params.get("limit", 0)))
    else:
        result = method()
    return result if isinstance(result, dict) else {}


def handle_request(raw: bytes, *, loader: object, peer_uid: int,
                   allowed_uids: "Iterable[int]",
                   on_denied: "Callable[[str, str, int], None] | None" = None) -> bytes:
    """**纯函数**（无 socket / 无线程）：一条原始请求字节 ⇒ 一条应答字节。所有异常都在这里吞掉。

    顺序与判据（**顺序不能改**，测试按这个定位）：
    1. **先过 uid 门**：`peer_allowed(peer_uid, allowed_uids)` 为假 ⇒ `on_denied(verb="", code="peer_denied", peer_uid=peer_uid)`
       并返回 `encode_response(ok=False, error="peer_denied")` —— **不给未授权对端任何解析反馈**；
    2. `parse_request(raw)`；抛 `ProtocolError` ⇒ `on_denied(verb="", code=e.code, peer_uid=peer_uid)`
       + `encode_response(ok=False, error=e.code, request_id=<能取到就带上，取不到空串>)`；
    3. 分发（`request.verb` 去掉 `"bpf."` 前缀后的方法名）：
       `bpf.load` ⇒ `loader.load(request.program)`；`bpf.unload` ⇒ `loader.unload(request.program)`；
       `bpf.stats` ⇒ `loader.stats()`；`bpf.tail` ⇒ `loader.tail(int(request.params.get("limit", 0)))`；
    4. loader 抛 `LoaderError` ⇒ `on_denied(verb=request.verb, code="loader_error", peer_uid=peer_uid)`
       + `ok=False, error=str(exc), request_id=request.request_id`；
    5. loader 抛**其它任何**异常 ⇒ 同上但 `code="internal"`、`error="internal"`（**绝不向上抛、绝不崩**）；
    6. 成功 ⇒ `encode_response(ok=True, request_id=request.request_id, data=<loader 返回的 dict>)`
       （若 loader 返回的不是 dict ⇒ `data={}`，不要抛）。
    `on_denied` 为 None ⇒ 只 `log.warning`，不调它。`on_denied` 自己抛异常也要吞掉。
    """
    if not peer_allowed(peer_uid, allowed_uids):
        _call_on_denied(on_denied, "", "peer_denied", peer_uid)
        return encode_response(ok=False, error="peer_denied")
    try:
        request = parse_request(raw)
    except ProtocolError as exc:
        _call_on_denied(on_denied, "", exc.code, peer_uid)
        request_id = ""
        try:
            candidate = json.loads(raw.decode("utf-8"))
        except Exception:
            candidate = None
        if isinstance(candidate, dict):
            rid = candidate.get("request_id")
            if (isinstance(rid, str) and len(rid) <= MAX_REQUEST_ID_LEN
                    and REQUEST_ID_RE.match(rid)):
                request_id = rid
        return encode_response(ok=False, error=exc.code, request_id=request_id)
    try:
        data = _dispatch(loader, request)
    except LoaderError as exc:
        _call_on_denied(on_denied, request.verb, "loader_error", peer_uid)
        return encode_response(ok=False, error=str(exc), request_id=request.request_id)
    except Exception:
        _call_on_denied(on_denied, request.verb, "internal", peer_uid)
        return encode_response(ok=False, error="internal", request_id=request.request_id)
    return encode_response(ok=True, request_id=request.request_id, data=data)


def serve(sock: "str | os.PathLike[str]", *, loader: object,
          allowed_uids: "Iterable[int]",
          max_requests: int | None = None,
          on_denied: "Callable[[str, str, int], None] | None" = None) -> int:
    """**单线程串行** accept 循环；返回处理过的连接数。

    - 监听前：若路径已存在**先 `unlink`**（残留 socket）；`bind` 后 `os.chmod(path, SOCKET_MODE)`；
    - 每个连接：`conn.settimeout(RECV_TIMEOUT_SECONDS)` → `recv(MAX_REQUEST_BYTES)` 一次拿一条请求 →
      用 `conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))` 取对端 uid
      （`struct.unpack("3i", ...)[0]`）→ `handle_request(...)` → `conn.sendall(resp)` → 关连接；
    - 连接层异常（对端早退 / 超时 / recv 失败）只 `log.debug`，**继续 accept**；
    - `max_requests` 非 None 且已处理够 ⇒ 退出循环；
    - 退出时：关监听 socket、`unlink` 路径（不存在就忽略）；返回处理计数。`bind`/`chmod` 失败**要抛**（这是启动失败，不许静默）。
    """
    path = Path(sock)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        listener.listen(16)
        os.chmod(str(path), SOCKET_MODE)
    except BaseException:
        listener.close()
        raise
    handled = 0
    try:
        while True:
            if max_requests is not None and handled >= max_requests:
                break
            try:
                conn, _addr = listener.accept()
            except OSError:
                log.debug("bpf_helper: accept 失败，继续", exc_info=True)
                continue
            try:
                conn.settimeout(RECV_TIMEOUT_SECONDS)
                raw = conn.recv(MAX_REQUEST_BYTES)
                if not raw:
                    log.debug("bpf_helper: 对端在发送前关闭连接")
                    continue
                peer_cred = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                            struct.calcsize("3i"))
                peer_uid = struct.unpack("3i", peer_cred)[0]
                response = handle_request(raw, loader=loader, peer_uid=peer_uid,
                                          allowed_uids=allowed_uids, on_denied=on_denied)
                conn.sendall(response)
                handled += 1
            except Exception:
                log.debug("bpf_helper: 连接处理异常（继续 accept）", exc_info=True)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
    finally:
        try:
            listener.close()
        except OSError:
            pass
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return handled
