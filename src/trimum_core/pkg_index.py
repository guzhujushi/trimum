"""官方目录索引（签名）—— `trm install <name>` 的入口清单（E5 第三片）。

``.trmpkg`` 回答「这个包可不可信」，本模块回答「**去哪拿这个包**」。两者缺一不可：
索引不签名的话，中间人只要改一个 url 就能把官方包换成自己的包（包本身仍会被
``verify_package()`` 挡住，但用户在 ``--allow-untrusted`` 下就完全没有防线了）。

容器格式（JSON，可存 ``index.json5``）::

    {
      "document":  {"format": "trmindex/1", "generated_at": "...", "packages": [ ... ]},
      "signature": {"alg": "ed25519", "key_id": "...", "signed": "index.json5", "signature": "..."},
      "chain":     [签名者证书, 根证书]
    }

签名覆盖 ``document`` 的**规范字节**（``trmpkg.canonical_bytes``），证书链与包共用
``trmpkg.verify_chain()`` —— 索引与包不可能对「什么算可信」产生第二种解释。

发布方把包丢进一个目录，``entries_from_directory()`` 扫出条目、``sign_index()`` 盖章 ——
``trm pkg index <dir>`` 就是这两个动作的 CLI 面（发布方闭环的最后一步）。

索引里的每个 ``package`` 条目：``name`` / ``type`` / ``version`` / ``url`` / ``sha256``
/ ``size`` / ``description`` / ``requires`` / ``entry``。``sha256`` 是**索引对包的承诺**：
下载下来先比哈希，不一致就不进校验流程（省掉一步「明明不可能通过」的解包）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from . import trmpkg
from .models import TRMErrorCode, TrimumError

#: 索引格式版本（不认识就拒绝，不猜）
INDEX_FORMAT = "trmindex/1"
INDEX_NAME = "index.json5"
#: 索引条目的字段（写进索引的就是这些）
PACKAGE_KEYS = (
    "name",
    "type",
    "version",
    "url",
    "sha256",
    "size",
    "description",
    "requires",
    "entry",
)


def package_entry(
    name: str,
    *,
    type: str = "agent",  # noqa: A002 - 与索引字段同名，读起来更直白
    version: str = "",
    url: str = "",
    sha256: str = "",
    size: int = 0,
    description: str = "",
    requires: Optional[dict] = None,
    entry: str = "",
) -> dict[str, Any]:
    """Build one index entry (all fields spelled out, so the file is readable)."""
    return {
        "name": str(name),
        "type": str(type),
        "version": str(version),
        "url": str(url),
        "sha256": str(sha256),
        "size": int(size or 0),
        "description": str(description),
        "requires": dict(requires or {}),
        "entry": str(entry),
    }


def build_index(
    packages: Sequence[dict],
    *,
    generated_at: str = "",
) -> dict[str, Any]:
    """Assemble the signed-area document (no signature yet)."""
    return {
        "format": INDEX_FORMAT,
        "generated_at": generated_at or trmpkg.now(),
        "packages": [dict(item) for item in packages],
    }


def sign_index(
    index: dict,
    *,
    signer_cert: dict,
    signer_private_pem: str,
    chain: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Wrap *index* with a signature and its certificate chain."""
    if index.get("format") != INDEX_FORMAT:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"format 必须是 {INDEX_FORMAT}"
        )
    signature = {
        "alg": trmpkg.ALG,
        "key_id": signer_cert.get("key_id", ""),
        "signed": INDEX_NAME,
        "signature": trmpkg.sign_bytes(
            trmpkg.canonical_bytes(index), signer_private_pem
        ),
    }
    return {
        "document": dict(index),
        "signature": signature,
        "chain": [dict(doc) for doc in (chain or [])],
    }


def write_index(path: str | Path, container: dict) -> Path:
    """Write the container as ``index.json5`` (strict JSON, UTF-8, LF)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(container, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


def read_index(source: str | Path | dict) -> dict:
    """Read a container from a path or accept an already-parsed document."""
    if isinstance(source, dict):
        return dict(source)
    target = Path(source)
    if not target.is_file():
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"索引不存在：{target}"
        )
    return parse_container(target.read_text(encoding="utf-8"))


def parse_container(text: str) -> dict:
    """Parse index JSON (``json5`` when available, strict JSON otherwise)."""
    try:
        import json5

        doc = json5.loads(text)
    except ImportError:  # pragma: no cover - json5 是项目依赖
        doc = json.loads(text)
    except Exception as exc:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"{INDEX_NAME} 无法解析：{exc}"
        ) from exc
    if not isinstance(doc, dict):
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"{INDEX_NAME} 应为对象"
        )
    return dict(doc)


@dataclass
class IndexResult:
    """校验结果：**不抛异常**，每条失败都摆在 ``errors`` 里（与 VerifyResult 同风格）。"""

    ok: bool = False
    errors: list[str] = field(default_factory=list)
    index: dict = field(default_factory=dict)
    signer: dict = field(default_factory=dict)
    root: dict = field(default_factory=dict)
    source: str = ""

    @property
    def packages(self) -> list[dict]:
        packages = self.index.get("packages")
        return [dict(item) for item in packages] if isinstance(packages, list) else []

    def find(self, name: str) -> Optional[dict]:
        """Return the newest entry for *name* (``""`` version sorts last)."""
        matches = [item for item in self.packages if item.get("name") == name]
        if not matches:
            return None
        return sorted(matches, key=lambda item: str(item.get("version", "")))[-1]

    def require_ok(self) -> "IndexResult":
        if not self.ok:
            raise TrimumError(
                TRMErrorCode.PACKAGE_VERIFY_FAILED,
                message="；".join(self.errors) or "目录索引校验失败",
                context={"source": self.source},
            )
        return self


def verify_index(
    source: str | Path | dict,
    *,
    root_path: str | Path | None = None,
) -> IndexResult:
    """Verify the container's signature and chain against the built-in root."""
    container = read_index(source)
    result = IndexResult(source=str(source) if not isinstance(source, dict) else "")

    document = container.get("document")
    if not isinstance(document, dict):
        result.errors.append("索引缺少 document")
        return result
    result.index = dict(document)

    if document.get("format") != INDEX_FORMAT:
        result.errors.append(
            f"format 不是 {INDEX_FORMAT}（实际 {document.get('format')!r}）"
        )
    if not isinstance(document.get("packages"), list):
        result.errors.append("document.packages 应为列表")

    chain = container.get("chain")
    if not isinstance(chain, list) or not chain:
        result.errors.append("索引缺少证书链")
        chain = []
    chain = [dict(item) for item in chain if isinstance(item, dict)]

    signature = container.get("signature")
    if not isinstance(signature, dict):
        result.errors.append("索引缺少签名")
        signature = {}
    elif signature.get("alg") != trmpkg.ALG:
        result.errors.append(f"不支持的签名算法：{signature.get('alg')!r}")

    signer, root_doc, chain_errors = trmpkg.verify_chain(chain, root_path=root_path)
    result.errors.extend(chain_errors)
    result.signer = signer
    result.root = root_doc

    trmpkg.verify_document_signature(
        document,
        signature,
        signer,
        result.errors,
        label=INDEX_NAME,
        container="索引",
    )

    result.ok = not result.errors
    return result



def entries_from_directory(
    directory: str | Path,
    *,
    root_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Scan *directory* for ``.trmpkg`` files and turn each one into an index entry.

    这是发布方闭环的**最后一步**，同时是一条质检线：

    * 只收录**验得过**的包（证书链追到 *root_path*），一个验不过就整体失败并列出原因 ——
      索引是「官方目录」这份承诺本身，「悄悄少一个包」比「报错」危险得多;
    * 字段取自**校验过的 manifest**，不是文件名 —— 文件叫什么不等于包里写的是什么;
    * ``url`` 是相对**索引位置**的路径（``/`` 分隔），所以索引与包放进同一个目录树
      就能离线安装（``pkg_install.resolve_url`` 负责解析）。
    """
    base = Path(directory)
    if not base.is_dir():
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"目录不存在：{base}"
        )
    found = sorted(
        (item for item in base.rglob("*.trmpkg") if item.is_file()),
        key=lambda item: item.relative_to(base).as_posix(),
    )

    entries: list[dict[str, Any]] = []
    problems: list[str] = []
    for package in found:
        result = trmpkg.verify_package(package, root_path=root_path)
        if not result.ok:
            reasons = "；".join(result.errors) or "校验失败"
            problems.append(f"{package.relative_to(base).as_posix()}：{reasons}")
            continue
        manifest = result.manifest or {}
        entries.append(
            package_entry(
                str(manifest.get("name", "")),
                type=str(manifest.get("type", "")),
                version=str(manifest.get("version", "")),
                url=package.relative_to(base).as_posix(),
                sha256=trmpkg.file_digest(package),
                size=package.stat().st_size,
                requires=dict(manifest.get("requires") or {}),
                entry=str(manifest.get("entry", "")),
            )
        )

    if problems:
        raise TrimumError(
            TRMErrorCode.PACKAGE_VERIFY_FAILED,
            message="索引拒绝收录验不过的包（先修包或先移出目录）：" + "；".join(problems),
            context={"directory": str(base)},
        )
    if not entries:
        raise TrimumError(
            TRMErrorCode.PACKAGE_NOT_FOUND,
            message=f"{base} 里没有 .trmpkg：空索引不是官方目录该有的样子",
        )
    return sorted(entries, key=lambda item: (item["name"], item["version"], item["url"]))

__all__ = [
    "INDEX_FORMAT",
    "INDEX_NAME",
    "PACKAGE_KEYS",
    "IndexResult",
    "build_index",
    "entries_from_directory",
    "package_entry",
    "parse_container",
    "read_index",
    "sign_index",
    "verify_index",
    "write_index",
]