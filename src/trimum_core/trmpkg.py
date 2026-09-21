"""``.trmpkg`` —— 官方分发包的格式、打包与校验（E5）。

信任模型（``docs/ECOSYSTEM-STRATEGY.md`` §7）：随包内置官方**根证书**（只有公钥，是信任锚），
官网产物由该根签发的**签名者证书**私钥签名；签名者签 manifest，manifest 里逐文件 sha256
覆盖整个载荷 —— 改一个字节都验不过，且校验只依赖包内签名与内置根，不依赖 TLS。

包结构（``tar.gz``，成员名排序，不存目录项之外的元数据）::

    manifest.json5      # format / name / type / version / requires / entry / capabilities / files{路径: sha256}
    SIGNATURE           # {alg, key_id, signature}：Ed25519 签 manifest 的**规范字节**
    chain.json          # [签名者证书, 根证书]（JSON 证书，不是 X.509 —— 见下）
    <载荷文件…>

与设计文档的两处口径差（有意）：证书沿用本仓库既有形态（``agent_cert`` / ``identity`` 都是
JSON 证书 + Ed25519 公钥），所以链文件叫 ``chain.json`` 而不是 ``chain.pem``；manifest 用
``json5`` 解析（依赖已有），写出时是严格 JSON（JSON 是 JSON5 的子集）。

红线：**安装 ≠ 授权**。``verify_package()`` 只回答「来源可不可信、有没有被改过」，
不回答「这条命令允不允许执行」—— 那仍由本机策略（ToolGateway 分层 + 用户证书能力）决定。
"""

from __future__ import annotations

import base64
import hashlib
import json
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .models import TRMErrorCode, TrimumError
from .paths import trimum_home, trimum_path

#: 包格式版本（不兼容时直接拒绝，不做「猜」）
FORMAT = "trmpkg/1"
MANIFEST_NAME = "manifest.json5"
SIGNATURE_NAME = "SIGNATURE"
CHAIN_NAME = "chain.json"
META_NAMES = (MANIFEST_NAME, SIGNATURE_NAME, CHAIN_NAME)
#: 允许的包类型（与生态四层对齐）
KNOWN_TYPES = ("agent", "tool", "workflow", "skill")
ALG = "ed25519"
#: 仓库内自带的信任锚（源码树 / 开发态）；运行态优先看 ``~/.trimum/trust/``
REPO_ROOT_CERT = Path(__file__).resolve().parents[2] / "config" / "trust" / "trimum-root.crt"
ROOT_CERT_NAME = "trimum-root.crt"


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _require_crypto():
    """延迟 import cryptography：没有它就没法验签，直接给出可执行的错误。"""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - 环境缺依赖
        raise TrimumError(
            TRMErrorCode.PACKAGE_VERIFY_FAILED,
            message="校验 .trmpkg 需要 cryptography（Ed25519）",
        ) from exc
    return ed25519, serialization


def canonical_bytes(doc: dict) -> bytes:
    """签名 / 校验用的规范字节：键排序 + 紧凑分隔符 + UTF-8（非 ASCII 不转义）。"""
    return json.dumps(
        doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def file_digest(path: str | Path) -> str:
    """``sha256:<hex>``（与 ``agent_cert.AgentCert.compute_fingerprint`` 同格式）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def key_id(public_pem: str) -> str:
    """公钥指纹（证书之间用它互相引用，避免抄一大段 PEM）。"""
    return f"sha256:{hashlib.sha256(public_pem.encode('utf-8')).hexdigest()}"


def _load_private_key(pem: str):
    ed25519, serialization = _require_crypto()
    return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)


def _load_public_key(pem: str):
    ed25519, serialization = _require_crypto()
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def sign_bytes(payload: bytes, private_key_pem: str) -> str:
    """Ed25519 签名 → base64（不带换行）。"""
    key = _load_private_key(private_key_pem)
    return base64.b64encode(key.sign(payload)).decode("ascii")


def verify_bytes(payload: bytes, signature_b64: str, public_key_pem: str) -> bool:
    """验签；任何异常都当「验不过」，绝不把异常当通过。"""
    ed25519, _ = _require_crypto()
    try:
        _load_public_key(public_key_pem).verify(
            base64.b64decode(signature_b64), payload
        )
        return True
    except Exception:
        return False


def new_keypair() -> tuple[str, str]:
    """生成 Ed25519 密钥对 → ``(private_pem, public_pem)``。"""
    _, serialization = _require_crypto()
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


# ---------------------------------------------------------------------------
# 证书（JSON 证书：根 + 签名者）
# ---------------------------------------------------------------------------


def make_root(name: str = "trimum-root") -> tuple[dict, str]:
    """生成官方根证书与其私钥。

    **私钥只属于发布方**（官网签名机 / 用户自己的发布账号），绝不进仓库；
    仓库里只提交 ``config/trust/trimum-root.crt``（公钥 + key_id）。
    """
    private_pem, public_pem = new_keypair()
    cert = {
        "name": name,
        "role": "root",
        "alg": ALG,
        "public_key": public_pem,
        "key_id": key_id(public_pem),
        "created_at": now(),
    }
    return cert, private_pem


def make_signer_cert(
    name: str,
    root_cert: dict,
    root_private_pem: str,
    *,
    capabilities: Optional[dict] = None,
    expires_at: str = "",
) -> tuple[dict, str]:
    """由根签发一张签名者证书（官网发布用的那把钥匙）。"""
    private_pem, public_pem = new_keypair()
    cert = {
        "name": name,
        "role": "signer",
        "alg": ALG,
        "public_key": public_pem,
        "key_id": key_id(public_pem),
        "issued_by": root_cert.get("name", ""),
        "issuer_key_id": root_cert.get("key_id", ""),
        "issued_at": now(),
        "expires_at": expires_at,
        "capabilities": dict(capabilities or {}),
    }
    cert["issuer_signature"] = sign_bytes(canonical_bytes(cert), root_private_pem)
    return cert, private_pem


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_cert(path: str | Path) -> dict:
    """读一份 JSON 证书（文件不存在 / 解析失败都按「没有这个证书」报错）。"""
    target = Path(path)
    if not target.is_file():
        raise TrimumError(
            TRMErrorCode.PACKAGE_VERIFY_FAILED,
            message=f"证书不存在：{target}",
        )
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise TrimumError(
            TRMErrorCode.PACKAGE_VERIFY_FAILED,
            message=f"证书无法解析：{target}",
        ) from exc


def default_root_path() -> Path:
    """内置根证书的位置：``TRIMUM_TRUST_ROOT`` → ``~/.trimum/trust/`` → 仓库 ``config/trust/``。"""
    import os

    override = os.environ.get("TRIMUM_TRUST_ROOT")
    if override:
        return Path(override)
    candidate = trimum_path("trust", ROOT_CERT_NAME)
    if candidate.is_file():
        return candidate
    return REPO_ROOT_CERT


# ---------------------------------------------------------------------------
# manifest / 打包
# ---------------------------------------------------------------------------


def build_manifest(
    source: str | Path,
    *,
    name: str = "",
    type: str = "agent",  # noqa: A002 - 与包字段同名，读起来更直白
    version: str = "0.0.0",
    requires: Optional[dict] = None,
    entry: str = "",
    capabilities: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> dict:
    """扫一棵目录树生成 manifest（载荷文件 + 逐文件 sha256，路径用 ``/``）。"""
    root = Path(source)
    if not root.is_dir():
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"载荷目录不存在：{root}"
        )
    if type not in KNOWN_TYPES:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message=f"未知包类型：{type}（可选 {'/'.join(KNOWN_TYPES)}）",
        )

    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in META_NAMES:
            continue
        files[relative] = file_digest(path)

    manifest = {
        "format": FORMAT,
        "name": name or root.name,
        "type": type,
        "version": version,
        "requires": dict(requires or {}),
        "entry": entry,
        "capabilities": dict(capabilities or {}),
        "files": files,
        "created_at": now(),
    }
    if extra:
        manifest.update(extra)
    return manifest


def create_package(
    source: str | Path,
    out_path: str | Path,
    *,
    signer_private_pem: str,
    signer_cert: dict,
    chain: Optional[list[dict]] = None,
    manifest: Optional[dict] = None,
    **manifest_fields: Any,
) -> Path:
    """把一棵目录树打成已签名的 ``.trmpkg``。

    签名覆盖 manifest 的规范字节（manifest 覆盖每个载荷文件），所以「先签名再改包」
    是做不到的。返回产出的包路径。
    """
    root = Path(source)
    manifest = manifest or build_manifest(root, **manifest_fields)
    if manifest.get("format") != FORMAT:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"format 必须是 {FORMAT}"
        )

    signature = {
        "alg": ALG,
        "key_id": signer_cert.get("key_id", ""),
        "signed": MANIFEST_NAME,
        "signature": sign_bytes(canonical_bytes(manifest), signer_private_pem),
    }
    chain_docs = list(chain or [])

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")

    with tarfile.open(target, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        _add_bytes(tar, MANIFEST_NAME, manifest_bytes)
        _add_bytes(
            tar,
            SIGNATURE_NAME,
            (json.dumps(signature, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        _add_bytes(
            tar,
            CHAIN_NAME,
            (json.dumps(chain_docs, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        for relative in sorted(manifest.get("files", {})):
            path = root / relative
            tar.add(path, arcname=relative, recursive=False)
    return target


def _add_bytes(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    """以固定 mtime / 权限写入元数据成员：不让打包机器的时间 / umask 混进产物。"""
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    info.mtime = 0
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, _BytesReader(payload))


class _BytesReader:
    """``tarfile`` 要的文件对象（``io.BytesIO`` 就够，包一层是为了类型明确）。"""

    def __init__(self, payload: bytes) -> None:
        import io as _io

        self._buffer = _io.BytesIO(payload)

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


@dataclass
class VerifyResult:
    """校验结果：**不抛异常**，把每一条失败都摆在 ``errors`` 里（CLI 直接打印）。"""

    ok: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    signer: dict = field(default_factory=dict)
    root: dict = field(default_factory=dict)
    files_checked: int = 0
    package: str = ""

    @property
    def name(self) -> str:
        return str(self.manifest.get("name", ""))

    @property
    def version(self) -> str:
        return str(self.manifest.get("version", ""))

    @property
    def type(self) -> str:
        return str(self.manifest.get("type", ""))

    def capabilities(self) -> dict:
        """签名者证书里的能力清单（安装 ≠ 授权：运行期只许**收紧**内置策略）。"""
        return dict(self.signer.get("capabilities") or {})

    def require_ok(self) -> "VerifyResult":
        if not self.ok:
            raise TrimumError(
                TRMErrorCode.PACKAGE_VERIFY_FAILED,
                message="；".join(self.errors) or "包校验失败",
                context={"package": self.package},
            )
        return self


def _safe_members(tar: tarfile.TarFile) -> tuple[list[tarfile.TarInfo], list[str]]:
    """路径安全检查：拒绝绝对路径 / ``..`` / 符号链接 / 硬链接 / 设备文件。

    包是「别人给的文件」，解包前先把能把文件写到 ``dest`` 之外的形态全部挡掉
    （tar 的经典逃逸手法：``../``、绝对路径、指向外部的符号链接）。
    """
    keep: list[tarfile.TarInfo] = []
    problems: list[str] = []
    for member in tar.getmembers():
        name = member.name
        if member.isdir():
            continue
        if member.issym() or member.islnk():
            problems.append(f"包内含有链接：{name}")
            continue
        if not member.isfile():
            problems.append(f"包内含有非普通文件：{name}")
            continue
        pure = Path(name)
        if pure.is_absolute() or any(part == ".." for part in pure.parts):
            problems.append(f"包内路径越界：{name}")
            continue
        keep.append(member)
    return keep, problems


def read_manifest(package: str | Path) -> dict:
    """只读 manifest（不做完整校验，给 ``trm pkg info`` 之类用）。"""
    with tarfile.open(package, "r:gz") as tar:
        handle = tar.extractfile(MANIFEST_NAME)
        if handle is None:
            raise TrimumError(
                TRMErrorCode.PACKAGE_INVALID, message=f"包里没有 {MANIFEST_NAME}"
            )
        raw = handle.read().decode("utf-8")
    return _parse_manifest(raw)


def _parse_manifest(raw: str) -> dict:
    try:
        import json5

        return dict(json5.loads(raw))
    except ImportError:  # pragma: no cover - json5 是项目依赖
        return dict(json.loads(raw))
    except Exception as exc:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"{MANIFEST_NAME} 无法解析：{exc}"
        ) from exc


def verify_package(
    package: str | Path,
    *,
    root_path: str | Path | None = None,
) -> VerifyResult:
    """校验顺序：解包安全 → manifest 格式 → 逐文件 sha256 → 证书链（到内置根）→ 签名。

    任何一步失败都记进 ``result.errors`` 并置 ``ok=False``；缺文件 / 坏 tar 这类
    「根本不是包」的情况抛 :class:`TrimumError`。
    """
    result = VerifyResult(package=str(package))
    target = Path(package)
    if not target.is_file():
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"包不存在：{target}"
        )

    try:
        with tarfile.open(target, "r:gz") as tar:
            members, problems = _safe_members(tar)
            result.errors.extend(problems)
            blobs: dict[str, bytes] = {}
            for member in members:
                handle = tar.extractfile(member)
                if handle is not None:
                    blobs[member.name] = handle.read()
    except tarfile.TarError as exc:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"不是合法的 tar.gz 包：{exc}"
        ) from exc

    if MANIFEST_NAME not in blobs:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"包里没有 {MANIFEST_NAME}"
        )
    manifest = _parse_manifest(blobs[MANIFEST_NAME].decode("utf-8"))
    result.manifest = manifest

    if manifest.get("format") != FORMAT:
        result.errors.append(
            f"format 不是 {FORMAT}（实际 {manifest.get('format')!r}）"
        )
    if manifest.get("type") not in KNOWN_TYPES:
        result.errors.append(f"未知包类型：{manifest.get('type')!r}")

    # ① 逐文件 sha256：包里的每个载荷文件都要在 manifest 里且哈希一致，反之亦然
    declared = manifest.get("files") or {}
    for name, digest in sorted(declared.items()):
        if name not in blobs:
            result.errors.append(f"manifest 里的文件缺失：{name}")
            continue
        actual = f"sha256:{hashlib.sha256(blobs[name]).hexdigest()}"
        if actual != digest:
            result.errors.append(f"文件哈希不符：{name}")
        result.files_checked += 1
    for name in sorted(blobs):
        if name in META_NAMES or name in declared:
            continue
        result.errors.append(f"manifest 未登记的额外文件：{name}")

    # ② 证书链：根（内置信任锚）→ 签名者
    chain = _parse_chain(blobs.get(CHAIN_NAME, b""), result.errors)
    signer, root_doc, chain_errors = verify_chain(chain, root_path=root_path)
    result.errors.extend(chain_errors)
    result.signer = signer
    result.root = root_doc

    # ③ 签名：签名者签 manifest 的规范字节
    signature = _parse_signature(blobs.get(SIGNATURE_NAME, b""), result.errors)
    verify_document_signature(manifest, signature, signer, result.errors)

    result.ok = not result.errors
    return result


def _parse_chain(raw: bytes, errors: list[str]) -> list[dict]:
    if not raw:
        errors.append(f"包里没有 {CHAIN_NAME}")
        return []
    try:
        docs = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        errors.append(f"{CHAIN_NAME} 无法解析")
        return []
    if not isinstance(docs, list) or not docs:
        errors.append(f"{CHAIN_NAME} 应为非空证书列表")
        return []
    return [dict(doc) for doc in docs if isinstance(doc, dict)]


def _parse_signature(raw: bytes, errors: list[str]) -> dict:
    if not raw:
        errors.append(f"包里没有 {SIGNATURE_NAME}")
        return {}
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        errors.append(f"{SIGNATURE_NAME} 无法解析")
        return {}
    if not isinstance(doc, dict):
        errors.append(f"{SIGNATURE_NAME} 应为对象")
        return {}
    if doc.get("alg") != ALG:
        errors.append(f"不支持的签名算法：{doc.get('alg')!r}")
    return doc


def _load_builtin_root(root_path: str | Path | None, errors: list[str]) -> dict:
    path = Path(root_path) if root_path is not None else default_root_path()
    if not path.is_file():
        errors.append(f"找不到内置根证书：{path}")
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        errors.append(f"内置根证书无法解析：{path}")
        return {}
    if doc.get("role") != "root" or not doc.get("public_key"):
        errors.append(f"内置根证书缺字段（role/public_key）：{path}")
        return {}
    return dict(doc)


def verify_chain(
    chain: list[dict],
    *,
    root_path: str | Path | None = None,
) -> tuple[dict, dict, list[str]]:
    """Verify ``signer ← built-in root`` and return ``(signer, root, errors)``.

    The ``.trmpkg`` manifest and the official directory index share this conclusion:
    the chain must reach *this machine's* built-in root, the signer certificate must
    be issued by it, and it must not be expired.  Failures only ever land in
    *errors* — "why is this untrustworthy" is more useful than an exception.
    """
    errors: list[str] = []
    builtin = _load_builtin_root(root_path, errors)
    signer = dict(chain[0]) if chain else {}
    root_doc = dict(chain[-1]) if chain else {}

    if builtin and root_doc and root_doc.get("key_id") != builtin.get("key_id"):
        errors.append("证书链的根不是本机内置根")
    if signer:
        issuer = canonical_bytes(
            {key: value for key, value in signer.items() if key != "issuer_signature"}
        )
        if not builtin:
            errors.append("本机没有内置根证书，无法验证签发者")
        elif not verify_bytes(
            issuer, signer.get("issuer_signature", ""), builtin.get("public_key", "")
        ):
            errors.append("签名者证书不是内置根签发的")
        expires = signer.get("expires_at") or ""
        if expires and expires < now():
            errors.append(f"签名者证书已过期：{expires}")
    return signer, (root_doc or builtin), errors


def verify_document_signature(
    document: dict,
    signature: dict,
    signer: dict,
    errors: list[str],
    *,
    label: str = "manifest",
    container: str = "包",
) -> None:
    """Verify that *signer* signed ``canonical_bytes(document)``.

    Signing a document's canonical bytes (sorted keys, compact separators, UTF-8)
    is how both the package manifest and the directory index are covered — one
    routine, so the two cannot drift apart.
    """
    if not signature:
        return
    if signature.get("key_id") and signer.get("key_id") != signature.get("key_id"):
        errors.append("签名所用密钥与证书不一致")
    if not signer:
        errors.append(f"{container}里没有签名者证书")
        return
    if not verify_bytes(
        canonical_bytes(document),
        signature.get("signature", ""),
        signer.get("public_key", ""),
    ):
        errors.append(f"{label} 签名验证失败（内容被改过）")


def extract_package(
    package: str | Path,
    dest: str | Path,
    *,
    verify: bool = True,
    root_path: str | Path | None = None,
) -> list[str]:
    """安全解包（可选先校验）。返回落地的相对路径列表。

    校验不通过就**不解包** —— 不给自己留「先解开再判断」的中间态。
    """
    if verify:
        verify_package(package, root_path=root_path).require_ok()

    target = Path(dest)
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    with tarfile.open(package, "r:gz") as tar:
        members, problems = _safe_members(tar)
        if problems:
            raise TrimumError(
                TRMErrorCode.PACKAGE_VERIFY_FAILED,
                message="；".join(problems),
            )
        for member in members:
            if member.name in META_NAMES:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            out = target / member.name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(handle.read())
            written.append(member.name)
    return written


def trust_dirs() -> dict[str, Path]:
    """信任相关的目录（内置根 / 密钥），给 CLI 与安装流程共用。"""
    return {
        "trust": trimum_path("trust"),
        "home": trimum_home(),
    }


__all__ = [
    "ALG",
    "CHAIN_NAME",
    "FORMAT",
    "KNOWN_TYPES",
    "MANIFEST_NAME",
    "META_NAMES",
    "ROOT_CERT_NAME",
    "SIGNATURE_NAME",
    "VerifyResult",
    "build_manifest",
    "canonical_bytes",
    "create_package",
    "default_root_path",
    "extract_package",
    "file_digest",
    "key_id",
    "load_cert",
    "make_root",
    "make_signer_cert",
    "new_keypair",
    "now",
    "read_manifest",
    "sign_bytes",
    "trust_dirs",
    "verify_bytes",
    "verify_chain",
    "verify_document_signature",
    "verify_package",
]