"""eBPF 特权 helper 的协议层（纯逻辑：动词白名单 + 参数校验 + 清单校验；不碰 socket / 内核 / root）。"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

# ---- 常量 ----
VERBS: tuple[str, ...] = ("bpf.load", "bpf.unload", "bpf.stats", "bpf.tail")
PROGRAMS: tuple[str, ...] = ("bpf_guard", "exec_guard")
PROGRAM_VERBS: tuple[str, ...] = ("bpf.load", "bpf.unload")
NO_PROGRAM_VERBS: tuple[str, ...] = ("bpf.stats", "bpf.tail")
MAX_REQUEST_BYTES: int = 4096
MAX_PARAM_KEYS: int = 8
MAX_PARAM_INT: int = 1_000_000
MIN_PARAM_INT: int = 0
MAX_REQUEST_ID_LEN: int = 64
REQUEST_ID_RE = re.compile(r"\A[A-Za-z0-9._-]*\Z")
DEFAULT_MANIFEST_PATH: str = "/etc/trimum/bpf-manifest.txt"
MANIFEST_ENV: str = "TRIMUM_BPF_MANIFEST"
MANIFEST_CONFIG_KEY: str = "security.bpf_manifest"
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


class ProtocolError(Exception):
    """协议级拒绝（**fail-closed**：任何一条不满足都拒绝，并由调用方写审计）。

    属性：`code`（短稳定串，进审计字段）、`message`（人读）。
    构造：`ProtocolError(code: str, message: str)`；`str(e)` 只回 message。
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ---- 稳定 error code 常量 ----
CODE_BAD_JSON = "bad_json"
CODE_NOT_OBJECT = "not_object"
CODE_TOO_LARGE = "too_large"
CODE_UNKNOWN_FIELD = "unknown_field"
CODE_BAD_VERB = "bad_verb"
CODE_BAD_PROGRAM = "bad_program"
CODE_BAD_PARAMS = "bad_params"
CODE_BAD_REQUEST_ID = "bad_request_id"
CODE_BAD_MANIFEST = "bad_manifest"
CODE_UNKNOWN_PROGRAM = "unknown_program"
CODE_HASH_MISMATCH = "hash_mismatch"


@dataclass(frozen=True)
class PrivRequest:
    """一条已通过校验的请求。"""

    verb: str
    program: str | None      # PROGRAM_VERBS 必非空；NO_PROGRAM_VERBS 恒为 None
    params: dict[str, int]   # 已裁剪；无参时是空 dict（不是 None）
    request_id: str          # 无则空串


def manifest_path(*, explicit: str | os.PathLike[str] | None = None,
                  config: object | None = None) -> Path:
    """按「显式参数 > 环境变量 `TRIMUM_BPF_MANIFEST` > 配置对象 `config.get("security.bpf_manifest")` > 默认」取清单路径。

    规则（逐条都要实现）：
    - `explicit` 非空 ⇒ 直接 `Path(explicit)`；
    - 否则 `os.environ.get(MANIFEST_ENV)` 非空且 `.strip()` 后非空 ⇒ 用它；
    - 否则 `config is not None` 且 `config.get(MANIFEST_CONFIG_KEY)` 返回非空字符串 ⇒ 用它；
    - 否则 `Path(DEFAULT_MANIFEST_PATH)`。
    - **配置缺失 / config 取值抛异常 / 取到空串或非字符串 ⇒ 静默走默认**（不许抛异常）。
    - `config` 只用 duck-typing 调 `.get(...)`，**不许 import `Config`**。
    - 返回 `Path(...)`，**不要**自动 expanduser / resolve / 建目录。
    """
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get(MANIFEST_ENV)
    if env_value is not None and env_value.strip():
        return Path(env_value)
    if config is not None:
        try:
            value = config.get(MANIFEST_CONFIG_KEY)
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return Path(value)
    return Path(DEFAULT_MANIFEST_PATH)


def parse_request(raw: bytes) -> PrivRequest:
    """严格解析并校验一条 helper 请求；任何不合规都抛 `ProtocolError(code, message)`。

    校验顺序与判据（顺序也要按这个来，便于测试定位）：
    1. `not isinstance(raw, (bytes, bytearray))` ⇒ `bad_json`；
    2. `len(raw) > MAX_REQUEST_BYTES` ⇒ `too_large`；
    3. `raw.decode("utf-8")` 失败、或 `json.loads` 失败 ⇒ `bad_json`；
    4. 顶层不是 dict ⇒ `not_object`；
    5. 顶层键集不是 `{"verb","program","params","request_id"}` 的**子集** ⇒ `unknown_field`
       （只要出现白名单外的键就拒，哪怕其它键都合法）；
    6. `verb` 必须是 str 且在 `VERBS` 内 ⇒ 否则 `bad_verb`；
    7. 按 verb 校验 `program`：
       - verb 在 `PROGRAM_VERBS`：`program` 必须是 str 且在 `PROGRAMS` 内 ⇒ 否则 `bad_program`；
       - verb 在 `NO_PROGRAM_VERBS`：`program` 必须缺失或为 None ⇒ 给了值就 `bad_program`；
    8. `params`（可缺省 ⇒ `{}`）：必须是 dict，且
       - 键数 > `MAX_PARAM_KEYS` ⇒ `bad_params`；
       - 键必须是 str ⇒ 否则 `bad_params`；
       - 值必须是 int 且**不是 bool**（`isinstance(v, bool)` 一律 `bad_params`）⇒ 否则 `bad_params`；
       - `MIN_PARAM_INT <= v <= MAX_PARAM_INT` ⇒ 越界 `bad_params`；
    9. `request_id`（可缺省 ⇒ `""`）：必须是 str、长度 ≤ `MAX_REQUEST_ID_LEN`、且匹配 `REQUEST_ID_RE`
       ⇒ 否则 `bad_request_id`。
    注意：`params` 一律**深拷贝出一个新 dict** 再返回（不要直接引用入参里的对象）。
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise ProtocolError(CODE_BAD_JSON, "请求必须是 bytes/bytearray")
    if len(raw) > MAX_REQUEST_BYTES:
        raise ProtocolError(CODE_TOO_LARGE, "请求超过 %d 字节" % MAX_REQUEST_BYTES)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError(CODE_BAD_JSON, "请求不是合法 UTF-8")
    try:
        obj = json.loads(text)
    except ValueError:
        raise ProtocolError(CODE_BAD_JSON, "请求不是合法 JSON")
    if not isinstance(obj, dict):
        raise ProtocolError(CODE_NOT_OBJECT, "顶层必须是 JSON 对象")
    allowed_keys = {"verb", "program", "params", "request_id"}
    unknown = set(obj) - allowed_keys
    if unknown:
        raise ProtocolError(CODE_UNKNOWN_FIELD, "不允许的字段: %s" % ",".join(sorted(unknown)))
    verb = obj.get("verb")
    if not isinstance(verb, str) or verb not in VERBS:
        raise ProtocolError(CODE_BAD_VERB, "非法动词: %r" % (verb,))
    program = obj.get("program")
    if verb in PROGRAM_VERBS:
        if not isinstance(program, str) or program not in PROGRAMS:
            raise ProtocolError(CODE_BAD_PROGRAM, "非法程序名: %r" % (program,))
    else:
        if program is not None:
            raise ProtocolError(CODE_BAD_PROGRAM, "动词 %s 不接受 program" % verb)
    params = obj.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ProtocolError(CODE_BAD_PARAMS, "params 必须是对象")
    if len(params) > MAX_PARAM_KEYS:
        raise ProtocolError(CODE_BAD_PARAMS, "params 键数超过 %d" % MAX_PARAM_KEYS)
    for key, value in params.items():
        if not isinstance(key, str):
            raise ProtocolError(CODE_BAD_PARAMS, "params 的键必须是字符串")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProtocolError(CODE_BAD_PARAMS, "params 的值必须是 int（键 %s）" % key)
        if value < MIN_PARAM_INT or value > MAX_PARAM_INT:
            raise ProtocolError(CODE_BAD_PARAMS, "params 的值越界（键 %s）" % key)
    params = {key: value for key, value in params.items()}
    request_id = obj.get("request_id")
    if request_id is None:
        request_id = ""
    if (not isinstance(request_id, str)
            or len(request_id) > MAX_REQUEST_ID_LEN
            or not REQUEST_ID_RE.match(request_id)):
        raise ProtocolError(CODE_BAD_REQUEST_ID, "非法 request_id: %r" % (request_id,))
    return PrivRequest(verb=verb, program=program, params=params, request_id=request_id)


def encode_response(*, ok: bool, request_id: str = "",
                    data: dict | None = None, error: str = "") -> bytes:
    """把 helper 的应答编码成一行 JSON（UTF-8，末尾带 `\\n`）。

    固定输出键：`{"ok": bool, "request_id": str, "data": dict, "error": str}`。
    - `data=None` ⇒ 输出 `{}`；`error` 非空时也只做字符串透传（不校验内容）。
    - `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`。
    """
    payload = {
        "ok": ok,
        "request_id": request_id,
        "data": {} if data is None else data,
        "error": error,
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (line + "\n").encode("utf-8")


def parse_response(raw: bytes) -> dict:
    """解析 helper 应答；坏数据抛 `ProtocolError`（复用 `bad_json` / `not_object`）。

    - 校验 `ok` 必须是 bool、`request_id` 必须是 str、`data` 必须是 dict、`error` 必须是 str，
      任一不满足 ⇒ `ProtocolError(CODE_BAD_JSON, ...)`（应答坏了不能当成功）。
    - 通过后返回**归一化**的 dict：`{"ok","request_id","data","error"}`。
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise ProtocolError(CODE_BAD_JSON, "应答必须是 bytes/bytearray")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError(CODE_BAD_JSON, "应答不是合法 UTF-8")
    try:
        obj = json.loads(text)
    except ValueError:
        raise ProtocolError(CODE_BAD_JSON, "应答不是合法 JSON")
    if not isinstance(obj, dict):
        raise ProtocolError(CODE_NOT_OBJECT, "应答顶层必须是 JSON 对象")
    if not isinstance(obj.get("ok"), bool):
        raise ProtocolError(CODE_BAD_JSON, "应答字段 ok 必须是 bool")
    if not isinstance(obj.get("request_id"), str):
        raise ProtocolError(CODE_BAD_JSON, "应答字段 request_id 必须是 str")
    if not isinstance(obj.get("data"), dict):
        raise ProtocolError(CODE_BAD_JSON, "应答字段 data 必须是 dict")
    if not isinstance(obj.get("error"), str):
        raise ProtocolError(CODE_BAD_JSON, "应答字段 error 必须是 str")
    return {
        "ok": obj["ok"],
        "request_id": obj["request_id"],
        "data": obj["data"],
        "error": obj["error"],
    }


def peer_allowed(peer_uid: int, allowed_uids: "Iterable[int]") -> bool:
    """SO_PEERCRED 校验：`peer_uid` 必须是 0..2**31-1 的 int（bool 不算）且在 `allowed_uids` 内。

    任何类型不对 / 越界 / 不在集合里 ⇒ 返回 False（不抛）。
    `allowed_uids` 里的元素如果是 bool 也要跳过（`True` 不该被当成 uid 1）。
    """
    if isinstance(peer_uid, bool) or not isinstance(peer_uid, int):
        return False
    if peer_uid < 0 or peer_uid > 2**31 - 1:
        return False
    for uid in allowed_uids:
        if isinstance(uid, bool) or not isinstance(uid, int):
            continue
        if uid == peer_uid:
            return True
    return False


def parse_manifest(text: str) -> dict[str, str]:
    """解析程序清单文本：每行 `<程序名>  <sha256hex>`。

    - 空行、以及 `#` 开头的整行注释 ⇒ 跳过；
    - 拆成的**非空**字段必须恰好 2 个 ⇒ 否则 `bad_manifest`；
    - 名字必须在 `PROGRAMS` 内 ⇒ 否则 `bad_manifest`；
    - sha256 必须匹配 `_SHA256_RE`（64 位小写十六进制）⇒ 否则 `bad_manifest`；
    - 同名重复 ⇒ `bad_manifest`；
    - 返回新 dict；`text` 为空串 ⇒ 返回 `{}`（空清单合法，校验阶段再拒 unknown_program）。
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = [part for part in stripped.split() if part]
        if len(fields) != 2:
            raise ProtocolError(CODE_BAD_MANIFEST, "清单行字段数必须为 2: %r" % (line,))
        name, digest = fields
        if name not in PROGRAMS:
            raise ProtocolError(CODE_BAD_MANIFEST, "未知程序名: %r" % (name,))
        if not _SHA256_RE.match(digest):
            raise ProtocolError(CODE_BAD_MANIFEST, "sha256 非法: %r" % (digest,))
        if name in result:
            raise ProtocolError(CODE_BAD_MANIFEST, "程序名重复: %r" % (name,))
        result[name] = digest
    return result


def verify_program(name: str, blob: bytes, manifest: "Mapping[str, str]") -> None:
    """加载前校验：`sha256(blob)` 必须等于 `manifest[name]`。

    - `name` 不在 manifest ⇒ `ProtocolError(CODE_UNKNOWN_PROGRAM, ...)`；
    - `blob` 不是 bytes/bytearray ⇒ `ProtocolError(CODE_HASH_MISMATCH, ...)`；
    - 哈希不等（大小写无关地比） ⇒ `ProtocolError(CODE_HASH_MISMATCH, ...)`；
    - 通过 ⇒ 返回 None（**不抛**）。
    """
    if name not in manifest:
        raise ProtocolError(CODE_UNKNOWN_PROGRAM, "清单里没有 %r" % (name,))
    if not isinstance(blob, (bytes, bytearray)):
        raise ProtocolError(CODE_HASH_MISMATCH, "程序内容必须是 bytes/bytearray")
    expected = manifest[name]
    if not isinstance(expected, str):
        raise ProtocolError(CODE_HASH_MISMATCH, "清单哈希非法: %r" % (expected,))
    actual = hashlib.sha256(bytes(blob)).hexdigest()
    if actual.lower() != expected.lower():
        raise ProtocolError(CODE_HASH_MISMATCH, "%s 的 sha256 不匹配" % name)
    return None
