"""`.trmpkg` 的安装与登记（E5 第三片）。

一条链只有三个动作，顺序不能换：

1. **校验**（``trmpkg.verify_package``）—— 来源可不可信、有没有被改过；
2. **落地**（``extract_package``）—— 按包声明的 ``type`` 进 ``agents/`` / ``tools/`` /
   ``workflows/`` / ``skills/``，路径越界仍然挡死（``--allow-untrusted`` 只放宽
   「来源」，不放宽「包内路径」）；
3. **登记**（``<TRIMUM_HOME>/config/installed.json5``）—— 记下名字、版本、trust、
   签名者指纹、包哈希与落地路径。

**安装 ≠ 授权**（§7 第 4 条，反复重申）：登记里的 ``trust`` 只回答「这东西从哪来」，
运行期照走 ToolGateway 分层；``trust: untrusted`` 的条目额外强制 confirm
（见 ``capability.py`` 的运行期交集）。本模块不碰任何执行路径。

agent 包额外写一份证书（``agents/<name>/cert.json``）：官方 → ``cert_type: official``
（``check_agent_trust`` 判为 TRUSTED，不弹确认），降级安装 → ``cert_type: none`` +
``scope: untrusted``（判为 CONFIRM，且运行期逐条确认）。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse
from urllib.request import url2pathname

from . import pkg_index, trmpkg
from .models import TRMErrorCode, TrimumError
from .paths import trimum_path

#: 登记表格式版本
INSTALL_FORMAT = "trminstall/1"
#: 两档来源：官方（链追到内置根）/ 用户显式接受的不可信
TRUST_OFFICIAL = "official"
TRUST_UNTRUSTED = "untrusted"
#: 包类型 → 数据根下的目录（与 ``paths.DATA_SUBDIRS`` 对齐）
TYPE_ROOTS: dict[str, str] = {
    "agent": "agents",
    "tool": "tools",
    "workflow": "workflows",
    "skill": "skills",
}
#: 官方目录（占位：站点上线前用 ``--index`` 或 ``TRIMUM_PKG_INDEX`` 指到本地目录）
DEFAULT_INDEX_URL = "https://trimum.dev/packages/index.json5"
INDEX_ENV = "TRIMUM_PKG_INDEX"
#: 下载缓存（包不进缓存目录就不落地到类型根，避免「下了一半」的中间态进业务目录）
CACHE_DIR = ("cache", "pkgs")
#: 不可信安装的证书能力块：工具不限、风险不收紧，但 **scope 触发逐条确认**
UNTRUSTED_CAPABILITIES: dict[str, Any] = {
    "tools": ["*"],
    "max_risk": "inherit",
    "expires_at": None,
    "scope": TRUST_UNTRUSTED,
}


# ---------------------------------------------------------------------------
# 登记表
# ---------------------------------------------------------------------------


def ledger_path() -> Path:
    """``<TRIMUM_HOME>/config/installed.json5`` —— 已安装包的名册。"""
    return trimum_path("config", "installed.json5")


def load_ledger() -> dict[str, Any]:
    """Read the ledger; a missing or corrupt file reads as empty (never fatal)."""
    target = ledger_path()
    if not target.is_file():
        return {"format": INSTALL_FORMAT, "packages": {}}
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"format": INSTALL_FORMAT, "packages": {}}
    if not isinstance(doc, dict):
        return {"format": INSTALL_FORMAT, "packages": {}}
    doc.setdefault("format", INSTALL_FORMAT)
    packages = doc.get("packages")
    if not isinstance(packages, dict):
        doc["packages"] = {}
    return doc


def save_ledger(doc: dict[str, Any]) -> Path:
    """Write the ledger (JSON, UTF-8, LF). No locking: installs are single-user CLI acts."""
    target = ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


def installed_records() -> dict[str, dict]:
    """``{name: record}`` for everything the ledger knows about."""
    packages = load_ledger().get("packages") or {}
    return {str(name): dict(record) for name, record in packages.items()}


def untrusted_names(kind: Optional[str] = None) -> set[str]:
    """Names installed through the downgrade path (``--allow-untrusted``).

    This is the runtime's hook: an untrusted *tool* has to be confirmed even
    though its payload is on disk, because nothing about it was ever vouched for.
    """
    return {
        name
        for name, record in installed_records().items()
        if record.get("trust") == TRUST_UNTRUSTED
        and (kind is None or record.get("type") == kind)
    }


# ---------------------------------------------------------------------------
# 取件（本地目录 / file:// / http(s)）
# ---------------------------------------------------------------------------


def _is_http(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _local_path(source: str) -> Path:
    """Map ``file://`` URLs (including Windows drive letters) to a path."""
    if source.startswith("file://"):
        return Path(url2pathname(urlparse(source).path))
    return Path(source)


def _http_get(url: str, *, timeout: float = 30.0) -> bytes:
    """Fetch bytes; any transport problem becomes one TRM code (never a raw socket error)."""
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - httpx 是项目依赖
        raise TrimumError(
            TRMErrorCode.HTTP_REQUEST_FAILED,
            message=f"取官方目录需要 httpx：{url}",
        ) from exc
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except Exception as exc:
        raise TrimumError(
            TRMErrorCode.HTTP_REQUEST_FAILED,
            message=f"下载失败：{url}（{exc}）",
        ) from exc
    return response.content


def read_source_bytes(source: str) -> bytes:
    """Read *source* (http(s) / file:// / path) as bytes."""
    if _is_http(source):
        return _http_get(source)
    path = _local_path(source)
    if not path.is_file():
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"找不到文件：{path}"
        )
    return path.read_bytes()


def read_source_text(source: str) -> str:
    """Read *source* as UTF-8 text."""
    try:
        return read_source_bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"文件不是 UTF-8 文本：{source}"
        ) from exc


def resolve_url(base: str, url: str) -> str:
    """Resolve an index entry's ``url`` against where the index itself came from.

    Relative URLs are the norm for a self-hosted directory (``demo.trmpkg`` next to
    ``index.json5``), and ``--index ./dist/`` has to keep working offline.
    """
    if not url:
        return ""
    if _is_http(url) or url.startswith("file://"):
        return url
    if _is_http(base):
        return urljoin(base, url)
    return str(_local_path(base).parent / url)


def fetch_to_cache(source: str, dest: Path) -> Path:
    """Place the package at *dest* (local sources are copied, remote ones downloaded)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _is_http(source):
        dest.write_bytes(_http_get(source))
        return dest
    origin = _local_path(source)
    if not origin.is_file():
        raise TrimumError(
            TRMErrorCode.PACKAGE_NOT_FOUND, message=f"索引指向的包不存在：{origin}"
        )
    if origin.resolve() != dest.resolve():
        shutil.copyfile(origin, dest)
    return dest


# ---------------------------------------------------------------------------
# 安装
# ---------------------------------------------------------------------------


def _write_agent_cert(
    dest: Path,
    name: str,
    *,
    trust: str,
    signer_name: str,
    capabilities: dict,
) -> str:
    """Write ``agents/<name>/cert.json`` — this is what ``check_agent_trust`` reads first."""
    from .agent_cert import AgentCert, CertificateType

    cert = AgentCert(
        agent_name=name,
        cert_type=(
            CertificateType.OFFICIAL
            if trust == TRUST_OFFICIAL
            else CertificateType.NONE
        ),
        issued_by=signer_name or "unknown",
        machine_id="",
        capabilities=capabilities,
    )
    target = dest / "cert.json"
    target.write_text(
        json.dumps(cert.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return str(target)


def install_package(
    package: str | Path,
    *,
    allow_untrusted: bool = False,
    force: bool = False,
    root_path: str | Path | None = None,
    source: str = "",
    index_source: str = "",
    index_verified: bool = True,
) -> dict[str, Any]:
    """Verify, unpack and register one ``.trmpkg``. Returns the ledger record.

    ``allow_untrusted`` is the documented downgrade path: it accepts a package whose
    chain does not reach the built-in root, marks it ``trust: untrusted`` and forces
    confirmation at runtime. It is never the default, and it does not relax the
    in-archive path checks.
    """
    target = Path(package)
    if not target.is_file():
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"包不存在：{target}"
        )

    result = trmpkg.verify_package(target, root_path=root_path)
    if not result.ok and not allow_untrusted:
        raise TrimumError(
            TRMErrorCode.PACKAGE_VERIFY_FAILED,
            message="；".join(result.errors) or "包校验失败",
            context={"package": str(target)},
        )

    name = result.name
    kind = result.type
    if not name:
        raise TrimumError(TRMErrorCode.PACKAGE_INVALID, message="manifest 没有 name")
    if kind not in TYPE_ROOTS:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"未知包类型：{kind!r}"
        )

    dest = trimum_path(TYPE_ROOTS[kind], name)
    if dest.exists() and not force:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message=f"已安装同名 {kind}：{dest}（加 --force 覆盖）",
        )

    # 已经校验过，或用户显式接受不可信 —— 这里不再重复校验，但包内路径检查照旧
    trmpkg.extract_package(target, dest, verify=False)

    trust = TRUST_OFFICIAL if result.ok else TRUST_UNTRUSTED
    capabilities = dict(result.capabilities()) if result.ok else dict(UNTRUSTED_CAPABILITIES)
    signer_name = str(result.signer.get("name", ""))

    record: dict[str, Any] = {
        "name": name,
        "type": kind,
        "version": result.version,
        "trust": trust,
        "signer": signer_name,
        "signer_key_id": str(result.signer.get("key_id", "")),
        "root_key_id": str(result.root.get("key_id", "")),
        "package": str(target),
        "package_sha256": trmpkg.file_digest(target),
        "source": source,
        "index_source": index_source,
        "index_verified": bool(index_verified),
        "installed_at": trmpkg.now(),
        "path": str(dest),
        "entry": str(result.manifest.get("entry", "")),
        "capabilities": capabilities,
        "errors": list(result.errors),
    }
    if kind == "agent":
        record["cert"] = _write_agent_cert(
            dest,
            name,
            trust=trust,
            signer_name=signer_name,
            capabilities=capabilities,
        )
    if trust == TRUST_UNTRUSTED:
        record["warning"] = (
            "来源不可信（--allow-untrusted）：登记为 untrusted，运行期强制逐条确认"
        )

    ledger = load_ledger()
    ledger.setdefault("packages", {})[name] = record
    save_ledger(ledger)
    return record


def install_from_index(
    name: str,
    *,
    index_source: str | None = None,
    allow_untrusted: bool = False,
    force: bool = False,
    root_path: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve *name* in the official directory, download it, then install it.

    The index must itself verify against the built-in root — unless the user asked
    for the untrusted path, in which case the index is accepted as untrusted too
    (and so is whatever package it points at).
    """
    source = index_source or os.environ.get(INDEX_ENV) or DEFAULT_INDEX_URL
    index_result = pkg_index.verify_index(
        pkg_index.parse_container(read_source_text(source)), root_path=root_path
    )
    if not index_result.ok and not allow_untrusted:
        raise TrimumError(
            TRMErrorCode.PACKAGE_VERIFY_FAILED,
            message="；".join(index_result.errors) or "目录索引校验失败",
            context={"index": source},
        )

    entry = index_result.find(name)
    if entry is None:
        raise TrimumError(
            TRMErrorCode.PACKAGE_NOT_FOUND,
            message=f"目录里没有 {name}（索引：{source}）",
            context={"index": source},
        )

    url = resolve_url(source, str(entry.get("url", "")))
    if not url:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message=f"目录里的 {name} 没有 url",
        )
    cached = trimum_path(*CACHE_DIR, f"{name}-{entry.get('version') or 'latest'}.trmpkg")
    fetch_to_cache(url, cached)

    promised = str(entry.get("sha256", ""))
    if promised:
        actual = trmpkg.file_digest(cached)
        if actual != promised:
            raise TrimumError(
                TRMErrorCode.PACKAGE_VERIFY_FAILED,
                message=f"索引承诺的哈希与下载到的包不符：{name}（{actual} != {promised}）",
                context={"package": str(cached)},
            )

    return install_package(
        cached,
        allow_untrusted=allow_untrusted,
        force=force,
        root_path=root_path,
        source=url,
        index_source=source,
        index_verified=index_result.ok,
    )


__all__ = [
    "CACHE_DIR",
    "DEFAULT_INDEX_URL",
    "INDEX_ENV",
    "INSTALL_FORMAT",
    "TYPE_ROOTS",
    "TRUST_OFFICIAL",
    "TRUST_UNTRUSTED",
    "UNTRUSTED_CAPABILITIES",
    "fetch_to_cache",
    "install_from_index",
    "install_package",
    "installed_records",
    "ledger_path",
    "load_ledger",
    "read_source_bytes",
    "read_source_text",
    "resolve_url",
    "save_ledger",
    "untrusted_names",
]