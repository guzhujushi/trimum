"""真 eBPF loader（ebpf1e）：用 libbpf（ctypes 绑定）加载 `/opt/trimum/bpf/<程序名>.bpf.o`。

契约就是 `bpf_helper.Loader` 那四个方法（`load` / `unload` / `stats` / `tail`）：

- **失败一律抛 `LoaderError`**（helper 回 `ok:false`），绝不静默降级、绝不崩；
- 只加载**清单里登记过、且 sha256 对得上**的 `.o`（`bpf_helper_protocol` 的清单/校验就是真源）；
- 路径 / 阈值一律「显式参数 > env > 配置 > 默认」，配置缺失或坏值**静默走默认**（不许抛）。

为什么用 ctypes 而不是 `libbpf` 的 Python 绑定：真机只有发行版的 `libbpf.so.1`（`libbpf-dev`），
不想为 helper 再装一份 pip 依赖（它会进 build / wheel 链）。ctypes 直接调 C ABI 最省事。

排水（ring buffer -> 审计回灌文件）：libbpf 1.x 的 `ring_buffer__poll` 回调在**同一线程**里被调，
所以 loader 起一个后台线程按 `security.bpf_drain_interval_ms` 轮询；事件同时进
① `tail()` 能看到的内存环（最近 N 条，非破坏性读）② `/run/trimum/bpf-alerts.jsonl`（daemon 侧
`bpf_audit.BpfAlertTailer` 读的那个文件）。文件写失败只降级 + `log.warning`，**不影响 attach**。
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import json
import logging
import os
import struct
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable

from .bpf_helper import LoaderError
from .bpf_helper_protocol import (
    PROGRAMS, ProtocolError, manifest_path, parse_manifest, verify_program,
)

log = logging.getLogger("trimum_core.bpf_loader")

# ---- 常量（键名逐字；顺序恒为「显式 > env > 配置 > 默认」） ----
PROGRAM_DIR_CONFIG_KEY: str = "security.bpf_program_dir"
PROGRAM_DIR_ENV: str = "TRIMUM_BPF_PROGRAM_DIR"
DRAIN_INTERVAL_CONFIG_KEY: str = "security.bpf_drain_interval_ms"
DRAIN_INTERVAL_ENV: str = "TRIMUM_BPF_DRAIN_INTERVAL_MS"
DEFAULT_DRAIN_INTERVAL_MS: int = 200
ALERTS_MAX_CONFIG_KEY: str = "security.bpf_alerts_max_bytes"
ALERTS_MAX_ENV: str = "TRIMUM_BPF_ALERTS_MAX_BYTES"
DEFAULT_ALERTS_MAX_BYTES: int = 4 * 1024 * 1024
RECENT_CONFIG_KEY: str = "security.bpf_recent_events"
RECENT_ENV: str = "TRIMUM_BPF_RECENT_EVENTS"
DEFAULT_RECENT_EVENTS: int = 1024

#: 事件环缓冲映射名（bpf/*.bpf.c 里两张同名 map，各程序一份）。
RINGBUF_MAP: str = "events"

#: `struct trimum_bpf_event` 的 Python 镜像（`bpf/trimum_bpf.h`）；末尾 pad 见头文件注释。
EVENT_STRUCT = struct.Struct("<III16s64sI")

#: 内核侧 `enum trimum_bpf_kind` 的镜像；tests/test_bpf_loader.py 解析 `bpf/trimum_bpf.h` 逐项对齐。
KINDS: dict[int, str] = {
    1: "prog_load",
    2: "bpf_attach",
    3: "bpf_detach",
    4: "map_write",
    5: "exec",
}


# ---- 配置解析（缺失 / 坏值 ⇒ 静默走默认） ----

def default_program_dir() -> Path:
    """默认产物目录 = 本包的**上一级**下的 `bpf/`（仓库里是 `<repo>/bpf`，真机是 `/opt/trimum/bpf`）。

    不写死绝对路径：部署根换了（`TRIMUM_BPF_DEPLOY_ROOT` / 自定义部署）默认也跟着走。
    """
    return Path(__file__).resolve().parents[2] / "bpf"


def program_dir(*, explicit: "str | os.PathLike[str] | None" = None,
                config: object | None = None) -> Path:
    """eBPF 产物目录；优先级 **显式 > env `TRIMUM_BPF_PROGRAM_DIR` > 配置 `security.bpf_program_dir` > 默认**。

    配置缺失 / 空串 / 非字符串 / 取值抛异常 ⇒ 静默走默认（不许抛）。返回 `Path(...)`，不建目录。
    """
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get(PROGRAM_DIR_ENV)
    if env_value is not None and env_value.strip():
        return Path(env_value)
    value = _config_str(config, PROGRAM_DIR_CONFIG_KEY)
    if value:
        return Path(value)
    return default_program_dir()


def _config_str(config: object | None, key: str) -> str:
    """`config.get(key)` 取非空字符串；缺失 / 类型不对 / 抛异常 ⇒ `""`（静默）。"""
    if config is None:
        return ""
    try:
        value = config.get(key)
    except Exception:
        return ""
    return value if isinstance(value, str) and value.strip() else ""


def _setting_int(*, env_name: str, config_key: str, default: int, config: object | None,
                 minimum: int = 1) -> int:
    """读一个「正整数」配置：env 优先，其次配置文件，都拿不到 / 坏值 / 越界 ⇒ `default`（静默）。"""
    raw_env = os.environ.get(env_name)
    if raw_env is not None and raw_env.strip():
        parsed = _to_int(raw_env)
        if parsed is not None and parsed >= minimum:
            return parsed
    value: object = None
    if config is not None:
        try:
            value = config.get(config_key)
        except Exception:
            value = None
    if isinstance(value, str):
        value = _to_int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= minimum:
        return value
    return default


def _to_int(value: str) -> "int | None":
    try:
        return int(value.strip())
    except (AttributeError, ValueError):
        return None


# ---- libbpf 薄封装（可注入：测试用假实现；真实现只在需要时 dlopen） ----

class _CtypesLibbpf:
    """libbpf 的 ctypes 绑定：只包 `BpfLoader` 用到的那些符号。

    指针型返回值按 libbpf 1.x 口径判错：`NULL` ⇒ 用 `errno`；落在 `ERR_PTR` 区间
    （高位全 1）⇒ `-ptr`。int 返回值 `rc < 0` ⇒ `-rc` 就是 errno。
    """

    def __init__(self, path: "str | None" = None) -> None:
        if path is None:
            path = ctypes.util.find_library("bpf") or "libbpf.so.1"
        try:
            self._lib = ctypes.CDLL(path, use_errno=True)
        except OSError as exc:
            raise LoaderError("libbpf unavailable (%s: %s)" % (path, exc)) from exc
        self.path = path
        self._keepalive: list = []   # 保住 open_mem 的 blob 缓冲区
        self._bind()

    # ---- 符号表 ----
    def _bind(self) -> None:
        lib = self._lib
        void_p, c_int, c_size, c_char_p = (
            ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_char_p)

        def sig(name: str, restype, argtypes) -> Any:
            try:
                fn = getattr(lib, name)
            except AttributeError as exc:
                raise LoaderError("libbpf is missing symbol %s (too old?)" % name) from exc
            fn.restype = restype
            fn.argtypes = argtypes
            return fn

        self._open_mem = sig("bpf_object__open_mem", void_p, [c_char_p, c_size, void_p])
        self._obj_load = sig("bpf_object__load", c_int, [void_p])
        self._obj_close = sig("bpf_object__close", None, [void_p])
        self._next_prog = sig("bpf_object__next_program", void_p, [void_p, void_p])
        self._prog_name = sig("bpf_program__name", c_char_p, [void_p])
        self._prog_attach = sig("bpf_program__attach", void_p, [void_p])
        self._link_destroy = sig("bpf_link__destroy", c_int, [void_p])
        self._find_map = sig("bpf_object__find_map_by_name", void_p, [void_p, c_char_p])
        self._map_fd = sig("bpf_map__fd", c_int, [void_p])
        try:
            self._rb_new = sig("ring_buffer__new", void_p,
                               [c_int, self.RINGBUF_CALLBACK, void_p, void_p])
            self._rb_poll = sig("ring_buffer__poll", c_int, [void_p, c_int])
            self._rb_free = sig("ring_buffer__free", None, [void_p])
        except LoaderError:
            # 旧 libbpf 没有 ring_buffer__*（<0.6）：还能 attach，但排不出事件（如实报不可用）。
            self._rb_new = self._rb_poll = self._rb_free = None
        self._errno = ctypes.get_errno

    # ---- 判错小工具 ----
    def _last_errno(self) -> int:
        try:
            return int(self._errno()) or errno.EIO
        except Exception:
            return errno.EIO

    def _ptr_error(self, ptr) -> int:
        """`0` ⇒ 没指针；`>0` ⇒ 正常指针；`<0` ⇒ errno（`NULL` 用 `errno`，`ERR_PTR` 用 `-ptr`）。"""
        if not ptr:
            return self._last_errno()
        value = ctypes.cast(ptr, ctypes.c_void_p).value or 0
        if value >= (1 << 64) - 4096:
            return (1 << 64) - value
        return 0

    # ---- 对外接口 ----
    def supports_ringbuf(self) -> bool:
        return self._rb_new is not None

    def open_mem(self, blob: bytes):
        buf = ctypes.create_string_buffer(bytes(blob), len(blob))
        ptr = self._open_mem(ctypes.cast(buf, ctypes.c_char_p), len(blob), None)
        err = self._ptr_error(ptr)
        if err:
            raise LoaderError("bpf_object__open_mem failed: %s" % os.strerror(err))
        self._keepalive.append(buf)   # keep the blob alive until the object is closed
        return ptr

    def load(self, obj) -> None:
        rc = self._obj_load(obj)
        if rc < 0:
            raise LoaderError("bpf_object__load failed: %s" % os.strerror(-rc))

    def close(self, obj) -> None:
        if obj:
            self._obj_close(obj)

    def find_program(self, obj, name: str):
        prev = None
        while True:
            prog = self._next_prog(obj, prev)
            if not prog:
                return None
            if (self._prog_name(prog) or b"").decode("utf-8", "replace") == name:
                return prog
            prev = prog

    def attach(self, prog):
        link = self._prog_attach(prog)
        err = self._ptr_error(link)
        if err:
            raise LoaderError("bpf_program__attach failed: %s" % os.strerror(err))
        return link

    def destroy_link(self, link) -> None:
        if link:
            self._link_destroy(link)

    def find_map_fd(self, obj, name: str) -> int:
        m = self._find_map(obj, name.encode("utf-8"))
        err = self._ptr_error(m)
        if err:
            raise LoaderError("map %r not found: %s" % (name, os.strerror(err)))
        return int(self._map_fd(m))

    RINGBUF_CALLBACK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_size_t)

    def ringbuf_new(self, fd: int, callback) -> object:
        if self._rb_new is None:
            raise LoaderError("libbpf has no ring_buffer__new (too old)")
        rb = self._rb_new(fd, callback, None, None)
        err = self._ptr_error(rb)
        if err:
            raise LoaderError("ring_buffer__new failed: %s" % os.strerror(err))
        return rb

    def ringbuf_poll(self, rb, timeout_ms: int) -> int:
        return int(self._rb_poll(rb, timeout_ms))

    def ringbuf_free(self, rb) -> None:
        if rb:
            self._rb_free(rb)


# ---- 事件解码 ----

def decode_event(raw: bytes) -> "dict[str, Any] | None":
    """一条 ring buffer 原始记录 ⇒ `{"kind","pid","comm","detail"}`；认不出来 ⇒ `None`（静默丢弃）。

    `detail`：`text` 非空就用它（exec_guard 的文件名），否则 `prog_load` 之类的回 `cmd=<arg0>`。
    """
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < EVENT_STRUCT.size:
        return None
    kind, pid, arg0, comm, text, _pad = EVENT_STRUCT.unpack_from(bytes(raw))
    name = KINDS.get(kind)
    if name is None:
        return None
    text_str = _cstr(text)
    detail = text_str if text_str else ("cmd=%d" % arg0 if arg0 else "")
    return {"kind": name, "pid": int(pid), "comm": _cstr(comm), "detail": detail}


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


class _Program:
    """一个已加载程序的状态（object / link / ring buffer / 计数）。"""

    __slots__ = ("obj", "link", "rb", "callback", "events", "dropped")

    def __init__(self, obj, link, rb, callback) -> None:
        self.obj = obj
        self.link = link
        self.rb = rb
        self.callback = callback
        self.events = 0
        self.dropped = 0


class BpfLoader:
    """libbpf 真 loader。`load` / `unload` / `stats` / `tail` 见 `bpf_helper.Loader`。"""

    def __init__(self, *, config: object | None = None,
                 libbpf_factory: "Callable[[], Any] | None" = None,
                 alert_path: "str | os.PathLike[str] | None" = None,
                 auto_drain: bool = True) -> None:
        self._config = config
        self._libbpf_factory = libbpf_factory or _CtypesLibbpf
        self._libbpf: Any = None
        self._libbpf_error: "str | None" = None
        self._alert_path_override = alert_path
        self._alerts_path: "Path | None" = None
        self._alerts_fh = None
        self._alerts_bytes = 0
        self._alerts_writable: "bool | None" = None
        self._alerts_reason = ""
        self._alerts_max = _setting_int(env_name=ALERTS_MAX_ENV, config_key=ALERTS_MAX_CONFIG_KEY,
                                       default=DEFAULT_ALERTS_MAX_BYTES, config=config)
        self._interval_s = _setting_int(env_name=DRAIN_INTERVAL_ENV,
                                       config_key=DRAIN_INTERVAL_CONFIG_KEY,
                                       default=DEFAULT_DRAIN_INTERVAL_MS, config=config) / 1000.0
        recent = _setting_int(env_name=RECENT_ENV, config_key=RECENT_CONFIG_KEY,
                              default=DEFAULT_RECENT_EVENTS, config=config)
        self._recent: deque = deque(maxlen=recent)
        self._lock = threading.RLock()
        self._alerts_lock = threading.Lock()
        self._programs: "dict[str, _Program]" = {}
        self._auto_drain = auto_drain
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._drain_note = ""

    # ---- libbpf 惰性取得：拿不到就如实报不可用（`stats` 不许抛） ----
    def _libbpf_or_none(self):
        if self._libbpf is None and self._libbpf_error is None:
            try:
                self._libbpf = self._libbpf_factory()
            except Exception as exc:                     # LoaderError 或 dlopen 的 OSError
                self._libbpf_error = str(exc) or exc.__class__.__name__
                log.warning("bpf_loader: libbpf unavailable (%s)", self._libbpf_error)
        return self._libbpf

    def _need_libbpf(self):
        lib = self._libbpf_or_none()
        if lib is None:
            raise LoaderError("libbpf unavailable: %s" % (self._libbpf_error or "unknown"))
        return lib

    # ---- 清单 ----
    def _manifest(self) -> "dict[str, str]":
        path = manifest_path(config=self._config)
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise LoaderError("manifest unreadable (%s: %s)" % (path, exc))
        try:
            return parse_manifest(text)
        except ProtocolError as exc:
            raise LoaderError("bad manifest (%s: %s)" % (path, exc.code))

    def _program_dir(self) -> Path:
        return program_dir(config=self._config)

    # ---- 四个动词 ----
    def load(self, program: str) -> "dict[str, Any]":
        """校验 + 加载 + attach 一个程序；已在跑则幂等返回（不重复 attach）。"""
        if program not in PROGRAMS:
            raise LoaderError("unknown program: %r" % (program,))
        with self._lock:
            if program in self._programs:
                return self._program_payload(program)
        blob_path = self._program_dir() / ("%s.bpf.o" % program)
        try:
            blob = Path(blob_path).read_bytes()
        except OSError as exc:
            raise LoaderError("program object not installed (%s: %s)" % (blob_path, exc))
        manifest = self._manifest()
        try:
            verify_program(program, blob, manifest)
        except ProtocolError as exc:
            raise LoaderError("%s: %s" % (exc.code, exc))
        lib = self._need_libbpf()
        obj = lib.open_mem(blob)
        link = None
        rb = None
        callback = None
        try:
            lib.load(obj)
            prog = lib.find_program(obj, program)
            if prog is None:
                raise LoaderError("object has no program %r (%s)" % (program, blob_path))
            link = lib.attach(prog)
            if lib.supports_ringbuf():
                fd = lib.find_map_fd(obj, RINGBUF_MAP)
                callback = self._make_callback(program)
                rb = lib.ringbuf_new(fd, callback)
            else:
                self._drain_note = "ringbuf_unsupported"
        except LoaderError:
            self._teardown_quietly(lib, obj, link, rb)
            raise
        except Exception as exc:                          # ctypes 层的意外一律包成 LoaderError
            self._teardown_quietly(lib, obj, link, rb)
            raise LoaderError("loading %s failed: %s" % (program, exc))
        with self._lock:
            self._programs[program] = _Program(obj, link, rb, callback)
            payload = self._program_payload(program)
        self._start_drain()
        log.info("bpf_loader: loaded %s (%s)", program, blob_path)
        return payload

    def unload(self, program: str) -> "dict[str, Any]":
        """卸载一个程序（没在跑 ⇒ 幂等返回 `attached:false`，不算错）。"""
        if program not in PROGRAMS:
            raise LoaderError("unknown program: %r" % (program,))
        with self._lock:
            state = self._programs.pop(program, None)
            if state is None:
                return {"program": program, "attached": False, "unloaded": False}
        lib = self._libbpf_or_none()
        if lib is not None:
            self._teardown_quietly(lib, state.obj, state.link, state.rb)
        log.info("bpf_loader: unloaded %s", program)
        return {"program": program, "attached": False, "unloaded": True}

    def stats(self) -> "dict[str, Any]":
        """当前状态；**任何情况都不许抛**（拿不到 libbpf ⇒ `available:false` + `reason`）。"""
        try:
            lib = self._libbpf_or_none()
            with self._lock:
                programs = {name: {"attached": True, "events": st.events, "dropped": st.dropped}
                            for name, st in sorted(self._programs.items())}
                recent = len(self._recent)
                drain_ok = bool(self._programs) and lib is not None
            payload: dict[str, Any] = {
                "available": lib is not None,
                "reason": "" if lib is not None else (self._libbpf_error or "unknown"),
                "libbpf": getattr(lib, "path", "") if lib is not None else "",
                "programs": programs,
                "recent": recent,
                "drain": {
                    "running": self._thread is not None and self._thread.is_alive(),
                    "interval_ms": int(self._interval_s * 1000),
                    "reason": self._drain_note,
                    "alerts": self._alerts_state(),
                    "attachable": drain_ok,
                },
            }
        except Exception as exc:                          # 兜底：stats 永远回一条可读的应答
            payload = {"available": False, "reason": "internal: %s" % exc, "programs": {}}
        return payload

    def tail(self, limit: int = 0) -> "dict[str, Any]":
        """**非破坏性**读最近的事件（`limit <= 0` ⇒ 全部）；认不出来的记录早已被丢掉，这里不会抛。"""
        try:
            count = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else 0
            with self._lock:
                events = list(self._recent)
        except Exception:
            events = []
        if count:
            events = events[-count:]
        return {"events": events, "count": len(events)}

    def close(self) -> None:
        """停排水线程 + 卸掉所有程序（测试与退出用）。"""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        for program in list(self._programs):
            try:
                self.unload(program)
            except LoaderError:
                log.debug("bpf_loader: unload %s on close failed (ignored)", program, exc_info=True)
        with self._alerts_lock:
            if self._alerts_fh is not None:
                try:
                    self._alerts_fh.close()
                except OSError:
                    pass
                self._alerts_fh = None

    # ---- 内部：排水 ----
    def _program_payload(self, program: str) -> "dict[str, Any]":
        state = self._programs.get(program)
        return {
            "program": program,
            "attached": True,
            "unloaded": False,
            "events": state.events if state else 0,
            "ringbuf": bool(state and state.rb),
        }

    def _teardown_quietly(self, lib, obj, link, rb) -> None:
        for step in (lambda: lib.ringbuf_free(rb), lambda: lib.destroy_link(link),
                     lambda: lib.close(obj)):
            try:
                step()
            except Exception:
                log.debug("bpf_loader: teardown step failed (ignored)", exc_info=True)

    def _make_callback(self, program: str):
        def _on_event(_ctx, data, size):
            try:
                self._absorb(program, ctypes.string_at(data, size))
            except Exception:
                log.debug("bpf_loader: event callback failed (ignored)", exc_info=True)
            return 0

        return self._libbpf.RINGBUF_CALLBACK(_on_event)

    def _absorb(self, program: str, raw: bytes) -> None:
        event = decode_event(raw)
        with self._lock:
            state = self._programs.get(program)
            if event is None:
                if state is not None:
                    state.dropped += 1
                return
            if state is not None:
                state.events += 1
            self._recent.append(event)
        self._append_alert(event)

    def drain_once(self) -> int:
        """把所有 ring buffer 里现成的事件吸干一次，返回吸收条数（排水线程每轮调它）。"""
        lib = self._libbpf_or_none()
        if lib is None:
            return 0
        with self._lock:
            buffers = [st.rb for st in self._programs.values() if st.rb is not None]
        absorbed = 0
        for rb in buffers:
            try:
                while True:
                    n = lib.ringbuf_poll(rb, 0)
                    if n <= 0:
                        break
                    absorbed += n
            except Exception:
                log.debug("bpf_loader: ring_buffer__poll failed (ignored)", exc_info=True)
        return absorbed

    def _start_drain(self) -> None:
        if not self._auto_drain or self._drain_note == "ringbuf_unsupported":
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._drain_loop, name="trimum-bpf-drain",
                                        daemon=True)
        self._thread.start()

    def _drain_loop(self) -> None:
        while not self._stop.is_set():
            try:
                absorbed = self.drain_once()
            except Exception:
                log.debug("bpf_loader: drain loop error (continuing)", exc_info=True)
                absorbed = 0
            if not absorbed:
                self._stop.wait(self._interval_s)

    # ---- 内部：审计回灌文件（best-effort，永不抛） ----
    def _alerts_path_or_none(self) -> "Path | None":
        if self._alerts_path is None and self._alert_path_override is not None:
            self._alerts_path = Path(self._alert_path_override)
        if self._alerts_path is None:
            try:
                from .bpf_audit import alert_path as _alert_path

                self._alerts_path = Path(_alert_path(config=self._config))
            except Exception as exc:
                self._alerts_reason = "alert_path_unavailable: %s" % exc
                self._alerts_writable = False
                return None
        return self._alerts_path

    def _append_alert(self, event: "dict[str, Any]") -> None:
        path = self._alerts_path_or_none()
        if path is None:
            return
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        blob = line.encode("utf-8")
        with self._alerts_lock:
            try:
                if self._alerts_fh is None:
                    self._alerts_fh = open(os.open(str(path), os.O_WRONLY | os.O_CREAT
                                                   | os.O_APPEND, 0o640), "ab", buffering=0)
                    self._alerts_bytes = int(os.path.getsize(str(path)))
                if (self._alerts_bytes + len(blob) > self._alerts_max
                        and self._alerts_bytes > self._alerts_max // 2):
                    self._rotate_alerts(path)
                self._alerts_fh.write(blob)
                self._alerts_bytes += len(blob)
                if self._alerts_writable is not True:
                    log.info("bpf_loader: alert drain writing %s", path)
                self._alerts_writable = True
                self._alerts_reason = ""
            except OSError as exc:
                if self._alerts_writable is not False:
                    log.warning("bpf_loader: cannot write alerts %s (degraded only, attach unaffected): %s",
                                path, exc)
                self._alerts_writable = False
                self._alerts_reason = str(exc)
                self._close_alerts_locked()

    def _rotate_alerts(self, path: Path) -> None:
        """超上限就把文件留最后一半（保留最近的记录）；daemon 侧 tailer 见到 size < offset 会重读。"""
        self._close_alerts_locked()
        try:
            size = os.path.getsize(str(path))
            with open(str(path), "rb") as handle:
                handle.seek(max(0, size - self._alerts_max // 2))
                data = handle.read()
            cut = data.find(b"\n")
            data = data[cut + 1:] if cut >= 0 else b""
            with open(str(path), "wb") as handle:
                handle.write(data)
            self._alerts_bytes = len(data)
        except OSError as exc:
            self._alerts_bytes = 0
            log.warning("bpf_loader: alerts rotation failed (%s): %s", path, exc)

    def _close_alerts_locked(self) -> None:
        if self._alerts_fh is not None:
            try:
                self._alerts_fh.close()
            except OSError:
                pass
            self._alerts_fh = None

    def _alerts_state(self) -> "dict[str, Any]":
        try:
            path = self._alerts_path_or_none()      # stats 也要能看到「会往哪写」（解析失败 ⇒ path 空）
        except Exception:
            path = None
        return {
            "path": str(path) if path is not None else "",
            "writable": self._alerts_writable,
            "reason": self._alerts_reason,
            "max_bytes": self._alerts_max,
        }
