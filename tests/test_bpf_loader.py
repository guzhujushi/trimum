"""纯逻辑测真 eBPF loader（`bpf_loader`）：不碰内核、不碰 root、不碰真 socket。

三块：
① 纯函数：`decode_event`、`KINDS` ⇄ `bpf/trimum_bpf.h` 数值表、`struct trimum_bpf_event` 布局、
   `program_dir` / 数值阈值配置的「显式 > env > 配置 > 默认」；
② **假 libbpf**（注入）驱动 load / unload / stats / tail / drain_once + 审计回灌落盘；
③ 真 libbpf 的**可选**集成：`.o` 存在且 libbpf 能 dlopen 时，验证 `bpf_object__open_mem` 打得开、
   程序名与 `events` 映射都在（这一步**不需要 CAP_BPF**；`bpf_object__load` 才要，故不在这里跑）。
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402

from trimum_core import bpf_loader as L  # noqa: E402
from trimum_core.bpf_helper import LoaderError  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
HEADER = REPO / "bpf" / "trimum_bpf.h"


# ---------------------------------------------------------------- ① 纯函数 / 表同步

def test_kinds_table_matches_c_header():
    """`bpf_loader.KINDS` 必须与 `bpf/trimum_bpf.h` 的数值表逐项一致（改了 C 不改 Python 就红）。"""
    text = HEADER.read_text(encoding="utf-8")
    pairs = re.findall(r"TRIMUM_KIND_([A-Z_]+)\s*=\s*(\d+)\s*,", text)
    assert pairs, "头文件里没解析到 TRIMUM_KIND_* 枚举"
    from_header = {int(value): name.lower() for name, value in pairs}
    assert from_header == L.KINDS


def test_event_struct_matches_c_header():
    """`struct trimum_bpf_event` 的字段与顺序必须与 Python 那边的 struct 格式一致。"""
    text = HEADER.read_text(encoding="utf-8")
    body = re.search(r"struct trimum_bpf_event \{(.*?)\};", text, re.S)
    assert body, "头文件里没找到 struct trimum_bpf_event"
    fields: list[tuple[str, int]] = []
    for line in body.group(1).splitlines():
        decl = line.split("/*")[0].strip().rstrip(";").strip()
        if not decl:
            continue
        m = re.match(r"(__u32|char)\s+(\w+)(?:\[(\d+)\])?$", decl)
        assert m, "认不出的字段声明：%r" % decl
        kind, name, count = m.group(1), m.group(2), m.group(3)
        fields.append((name, 4 if kind == "__u32" else int(count)))
    assert [name for name, _ in fields] == ["kind", "pid", "arg0", "comm", "text", "pad"]
    assert L.EVENT_STRUCT.size == sum(size for _, size in fields) == 96
    assert L.EVENT_STRUCT.format == "<III16s64sI"


def _record(kind: int, pid: int, arg0: int, comm: bytes, text: bytes) -> bytes:
    return L.EVENT_STRUCT.pack(kind, pid, arg0, comm, text, 0)


def test_decode_event_happy_path():
    raw = _record(1, 4242, 5, b"trm\x00\x00", b"")
    assert L.decode_event(raw) == {
        "kind": "prog_load", "pid": 4242, "comm": "trm", "detail": "cmd=5",
    }


def test_decode_event_uses_text_as_detail_when_present():
    raw = _record(5, 1, 0, b"bash\x00", b"/usr/bin/ls\x00")
    assert L.decode_event(raw) == {
        "kind": "exec", "pid": 1, "comm": "bash", "detail": "/usr/bin/ls",
    }


def test_decode_event_rejects_short_and_unknown_kind():
    assert L.decode_event(b"\x00" * 8) is None
    assert L.decode_event(b"") is None
    assert L.decode_event("not-bytes") is None          # type: ignore[arg-type]
    assert L.decode_event(_record(99, 1, 0, b"x\x00", b"")) is None


def test_decode_event_survives_broken_utf8():
    decoded = L.decode_event(_record(2, 7, 28, b"\xff\xfe\x00", b"\xff\x00"))
    assert decoded is not None
    assert decoded["kind"] == "bpf_attach"
    assert decoded["detail"]                            # 替字符也算有内容，不抛


def test_program_dir_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv(L.PROGRAM_DIR_ENV, raising=False)

    class Cfg:
        def get(self, key):
            return str(tmp_path / "from-config") if key == L.PROGRAM_DIR_CONFIG_KEY else None

    assert L.program_dir(config=Cfg()) == tmp_path / "from-config"
    monkeypatch.setenv(L.PROGRAM_DIR_ENV, str(tmp_path / "from-env"))
    assert L.program_dir(config=Cfg()) == tmp_path / "from-env"
    assert L.program_dir(explicit=tmp_path / "explicit", config=Cfg()) == tmp_path / "explicit"


def test_program_dir_falls_back_to_default(monkeypatch):
    monkeypatch.delenv(L.PROGRAM_DIR_ENV, raising=False)

    class BadCfg:
        def get(self, key):
            raise RuntimeError("boom")

    assert L.program_dir(config=BadCfg()) == L.default_program_dir()
    assert L.program_dir(config=None) == REPO / "bpf"
    assert L.default_program_dir() == REPO / "bpf"


@pytest.mark.parametrize("env_name, config_key, default", [
    (L.DRAIN_INTERVAL_ENV, L.DRAIN_INTERVAL_CONFIG_KEY, L.DEFAULT_DRAIN_INTERVAL_MS),
    (L.ALERTS_MAX_ENV, L.ALERTS_MAX_CONFIG_KEY, L.DEFAULT_ALERTS_MAX_BYTES),
    (L.RECENT_ENV, L.RECENT_CONFIG_KEY, L.DEFAULT_RECENT_EVENTS),
])
def test_int_settings_fall_back_to_default(env_name, config_key, default, monkeypatch):
    monkeypatch.delenv(env_name, raising=False)
    assert L._setting_int(env_name=env_name, config_key=config_key, default=default,
                          config=None) == default
    monkeypatch.setenv(env_name, "not-a-number")
    assert L._setting_int(env_name=env_name, config_key=config_key, default=default,
                          config=None) == default
    monkeypatch.setenv(env_name, "0")                   # 越界（最小值 1）⇒ 默认
    assert L._setting_int(env_name=env_name, config_key=config_key, default=default,
                          config=None) == default

    class Cfg:
        def get(self, key):
            return {"bad": 1} if key == config_key else None   # 类型不对 ⇒ 默认

    monkeypatch.delenv(env_name, raising=False)
    assert L._setting_int(env_name=env_name, config_key=config_key, default=default,
                          config=Cfg()) == default


def test_int_settings_read_env_and_config(monkeypatch):
    monkeypatch.setenv(L.DRAIN_INTERVAL_ENV, "50")
    assert L.BpfLoader(auto_drain=False)._interval_s == pytest.approx(0.05)

    class Cfg:
        def get(self, key):
            return 2048 if key == L.RECENT_CONFIG_KEY else None

    loader = L.BpfLoader(config=Cfg(), auto_drain=False)
    assert loader._recent.maxlen == 2048


# ---------------------------------------------------------------- ② 假 libbpf 驱动

class FakeLibbpf:
    """假 libbpf：只记账，ring buffer 由测试手动灌事件。"""

    RINGBUF_CALLBACK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_size_t)

    def __init__(self, *, ringbuf: bool = True, fail_load: str = "", known=("bpf_guard", "exec_guard")):
        self.path = "fake-libbpf"
        self._ringbuf = ringbuf
        self._fail_load = fail_load
        self._known = set(known)
        self.opened: list[object] = []
        self.loads: list[object] = []
        self.attached: list[object] = []
        self.destroyed = 0
        self.closed = 0
        self.freed = 0
        self.pending: list[bytes] = []
        self._callbacks: dict[object, object] = {}

    def supports_ringbuf(self) -> bool:
        return self._ringbuf

    def open_mem(self, blob: bytes):
        assert isinstance(blob, (bytes, bytearray)) and blob
        obj = ("obj", len(self.opened))
        self.opened.append(obj)
        return obj

    def load(self, obj) -> None:
        if self._fail_load:
            raise LoaderError(self._fail_load)
        self.loads.append(obj)

    def close(self, obj) -> None:
        self.closed += 1

    def find_program(self, obj, name):
        return ("prog", name) if name in self._known else None

    def attach(self, prog):
        self.attached.append(prog)
        return ("link", prog)

    def destroy_link(self, link) -> None:
        self.destroyed += 1

    def find_map_fd(self, obj, name) -> int:
        if name != L.RINGBUF_MAP:
            raise LoaderError("map %r not found" % name)
        return 7

    def ringbuf_new(self, fd, callback):
        if not self._ringbuf:
            raise LoaderError("libbpf has no ring_buffer__new (too old)")
        assert fd == 7
        rb = ("rb", fd)
        self._callbacks[rb] = callback
        return rb

    def ringbuf_poll(self, rb, timeout_ms: int) -> int:
        callback = self._callbacks[rb]
        batch, self.pending = self.pending, []
        for raw in batch:
            buf = ctypes.create_string_buffer(raw, len(raw))
            callback(None, ctypes.addressof(buf), len(raw))
        return len(batch)

    def ringbuf_free(self, rb) -> None:
        self.freed += 1


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """在 tmp 里造一份「产物 + 清单 + 回灌文件路径」，并把 env 指过去。"""
    out = tmp_path / "bpf"
    out.mkdir()
    monkeypatch.setenv(L.PROGRAM_DIR_ENV, str(out))
    monkeypatch.setenv("TRIMUM_BPF_MANIFEST", str(tmp_path / "manifest.txt"))
    alerts = tmp_path / "bpf-alerts.jsonl"
    monkeypatch.setenv("TRIMUM_BPF_ALERTS", str(alerts))
    return out, alerts


def _install_object(out: Path, manifest: Path, name: str, blob: bytes) -> None:
    (out / ("%s.bpf.o" % name)).write_bytes(blob)
    line = "%s  %s\n" % (name, hashlib.sha256(blob).hexdigest())
    with open(manifest, "a", encoding="utf-8") as handle:
        handle.write(line)


def _loader(**kwargs) -> L.BpfLoader:
    kwargs.setdefault("auto_drain", False)
    return L.BpfLoader(**kwargs)


def test_stats_reports_libbpf_unavailable(tmp_path):
    def boom():
        raise LoaderError("libbpf unavailable (nope)")

    stats = _loader(libbpf_factory=boom).stats()
    assert stats["available"] is False
    assert "libbpf" in stats["reason"]
    assert stats["programs"] == {}
    assert isinstance(stats["drain"], dict)


def test_load_unknown_program_raises():
    with pytest.raises(LoaderError) as excinfo:
        _loader().load("not_a_program")
    assert "unknown program" in str(excinfo.value)


def test_load_without_object_raises(installed):
    with pytest.raises(LoaderError) as excinfo:
        _loader(libbpf_factory=FakeLibbpf).load("bpf_guard")
    assert "not installed" in str(excinfo.value)


def test_load_rejects_hash_mismatch(installed):
    out, _alerts = installed
    manifest = Path(os.environ["TRIMUM_BPF_MANIFEST"])
    _install_object(out, manifest, "bpf_guard", b"real-blob")
    (out / "bpf_guard.bpf.o").write_bytes(b"tampered")
    with pytest.raises(LoaderError) as excinfo:
        _loader(libbpf_factory=FakeLibbpf).load("bpf_guard")
    assert "hash_mismatch" in str(excinfo.value)


def test_load_rejects_empty_manifest(installed):
    out, _alerts = installed
    _install_object(out, Path(os.environ["TRIMUM_BPF_MANIFEST"]), "bpf_guard", b"blob")
    Path(os.environ["TRIMUM_BPF_MANIFEST"]).write_text("", encoding="utf-8")
    with pytest.raises(LoaderError) as excinfo:
        _loader(libbpf_factory=FakeLibbpf).load("bpf_guard")
    assert "unknown_program" in str(excinfo.value)


def test_load_attaches_drains_tails_and_unloads(installed):
    out, alerts = installed
    manifest = Path(os.environ["TRIMUM_BPF_MANIFEST"])
    _install_object(out, manifest, "bpf_guard", b"blob-guard")
    fake = FakeLibbpf()
    loader = _loader(libbpf_factory=lambda: fake, alert_path=alerts)

    payload = loader.load("bpf_guard")
    assert payload["attached"] is True and payload["ringbuf"] is True
    assert fake.attached == [("prog", "bpf_guard")]

    # 再 load 一次：幂等，不重复 attach
    assert loader.load("bpf_guard")["attached"] is True
    assert len(fake.attached) == 1

    fake.pending = [_record(1, 11, 5, b"trm\x00", b""), _record(4, 12, 2, b"trm\x00", b"")]
    assert loader.drain_once() == 2
    assert loader.drain_once() == 0

    tailed = loader.tail(0)
    assert [e["kind"] for e in tailed["events"]] == ["prog_load", "map_write"]
    assert tailed["count"] == 2
    assert loader.tail(1)["count"] == 1
    assert loader.stats()["programs"]["bpf_guard"]["events"] == 2

    # 回灌文件：一行一个 JSON，且 daemon 侧的解析器认得（跨模块对齐）
    from trimum_core import bpf_audit

    lines = [ln for ln in alerts.read_text(encoding="utf-8").splitlines() if ln]
    assert len(lines) == 2
    alerts_parsed = [bpf_audit.parse_alert_line(ln) for ln in lines]
    assert [a.kind for a in alerts_parsed] == ["prog_load", "map_write"]
    assert alerts_parsed[0].pid == 11
    assert json.loads(lines[1])["detail"] == "cmd=2"

    assert loader.unload("bpf_guard") == {"program": "bpf_guard", "attached": False,
                                          "unloaded": True}
    assert fake.destroyed == 1 and fake.freed == 1 and fake.closed == 1
    assert loader.stats()["programs"] == {}
    assert loader.unload("bpf_guard")["unloaded"] is False      # 幂等


def test_load_failure_rolls_back_and_reports(installed):
    out, alerts = installed
    manifest = Path(os.environ["TRIMUM_BPF_MANIFEST"])
    _install_object(out, manifest, "exec_guard", b"blob-exec")
    fake = FakeLibbpf(fail_load="bpf_object__load failed: Operation not permitted")
    loader = _loader(libbpf_factory=lambda: fake, alert_path=alerts)

    with pytest.raises(LoaderError) as excinfo:
        loader.load("exec_guard")
    assert "Operation not permitted" in str(excinfo.value)
    assert fake.closed == 1                    # 半途失败必须清干净
    assert loader.stats()["programs"] == {}


def test_unknown_program_in_object_raises(installed):
    out, alerts = installed
    manifest = Path(os.environ["TRIMUM_BPF_MANIFEST"])
    _install_object(out, manifest, "bpf_guard", b"blob")
    fake = FakeLibbpf(known=())
    with pytest.raises(LoaderError) as excinfo:
        _loader(libbpf_factory=lambda: fake, alert_path=alerts).load("bpf_guard")
    assert "no program" in str(excinfo.value)
    assert fake.destroyed == 1 and fake.closed == 1


def test_old_libbpf_without_ringbuf_degrades(installed):
    out, alerts = installed
    manifest = Path(os.environ["TRIMUM_BPF_MANIFEST"])
    _install_object(out, manifest, "bpf_guard", b"blob")
    fake = FakeLibbpf(ringbuf=False)
    loader = _loader(libbpf_factory=lambda: fake, alert_path=alerts)

    assert loader.load("bpf_guard")["ringbuf"] is False
    assert loader.load("bpf_guard")["attached"] is True
    assert loader.stats()["drain"]["reason"] == "ringbuf_unsupported"
    fake.pending = [_record(1, 1, 5, b"x\x00", b"")]
    assert loader.drain_once() == 0                     # 没有 rb 可排
    assert loader.tail(0)["count"] == 0


def test_stats_reports_the_configured_alerts_path(installed):
    """`stats` 要如实报出回灌文件落点（还没写第一条时也要看得到）。"""
    out, alerts = installed
    loader = _loader(libbpf_factory=FakeLibbpf, alert_path=alerts)
    assert loader.stats()["drain"]["alerts"]["path"] == str(alerts)


def test_alerts_file_unwritable_degrades_but_tail_still_works(installed, tmp_path):
    out, _alerts = installed
    manifest = Path(os.environ["TRIMUM_BPF_MANIFEST"])
    _install_object(out, manifest, "bpf_guard", b"blob")
    fake = FakeLibbpf()
    loader = _loader(libbpf_factory=lambda: fake,
                     alert_path=tmp_path / "no-such-dir" / "alerts.jsonl")
    loader.load("bpf_guard")
    fake.pending = [_record(1, 1, 5, b"x\x00", b"")]
    assert loader.drain_once() == 1
    assert loader.tail(0)["count"] == 1                 # 内存环照常
    assert loader.stats()["drain"]["alerts"]["writable"] is False


def test_alerts_file_rotates_when_over_max(installed, monkeypatch):
    out, alerts = installed
    manifest = Path(os.environ["TRIMUM_BPF_MANIFEST"])
    _install_object(out, manifest, "bpf_guard", b"blob")
    monkeypatch.setenv(L.ALERTS_MAX_ENV, "512")
    fake = FakeLibbpf()
    loader = _loader(libbpf_factory=lambda: fake, alert_path=alerts)
    loader.load("bpf_guard")
    fake.pending = [_record(1, i, 5, b"trm\x00", b"") for i in range(50)]
    assert loader.drain_once() == 50
    assert alerts.stat().st_size <= 512
    for line in alerts.read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["kind"] == "prog_load"   # 轮转不写坏半行


def test_drain_thread_starts_and_stops(installed):
    out, alerts = installed
    manifest = Path(os.environ["TRIMUM_BPF_MANIFEST"])
    _install_object(out, manifest, "bpf_guard", b"blob")
    fake = FakeLibbpf()
    loader = L.BpfLoader(libbpf_factory=lambda: fake, alert_path=alerts, auto_drain=True)
    loader.load("bpf_guard")
    assert loader.stats()["drain"]["attachable"] is True
    loader.close()
    assert loader.stats()["drain"]["running"] is False
    assert loader.stats()["programs"] == {}


# ---------------------------------------------------------------- ③ 真 libbpf（可选，不需要 root）

def _real_libbpf_available() -> bool:
    try:
        L._CtypesLibbpf()
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _real_libbpf_available(), reason="本机没有可加载的 libbpf")
def test_real_libbpf_opens_both_program_objects(tmp_path):
    build = REPO / "scripts" / "build_bpf.sh"
    if not build.exists() or not shutil.which("clang"):
        pytest.skip("没有 clang / build_bpf.sh")
    out = tmp_path / "bpf"
    proc = shutil.which("bash") or "/bin/bash"
    result = __import__("subprocess").run([proc, str(build), "--out-dir", str(out)],
                                          capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        pytest.skip("build_bpf.sh 跑不起来（缺 libbpf-dev / linux-headers）：%s"
                    % result.stderr.strip()[-200:])

    lib = L._CtypesLibbpf()
    for name in ("bpf_guard", "exec_guard"):
        blob = (out / ("%s.bpf.o" % name)).read_bytes()
        obj = lib.open_mem(blob)
        try:
            assert lib.find_program(obj, name), "%s 里没有程序 %s" % (name, name)
            # 未 load 时 map 还没有 fd（`bpf_map__fd` 回 -1）：能找到 map 就算过，找不到会抛 LoaderError。
            assert isinstance(lib.find_map_fd(obj, L.RINGBUF_MAP), int)
            with pytest.raises(LoaderError):
                lib.find_map_fd(obj, "no_such_map")
        finally:
            lib.close(obj)
