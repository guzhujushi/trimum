"""`trm pkg` — `.trmpkg` 官方分发包的打包、校验与信任锚（E5 第二片）。

六个动作对应分发渠道的两端：**发布方造钥匙**（``root-init`` / ``signer-init``）、
**发布方打包**（``create``）、**发布方建目录**（``index``）、
**使用者校验**（``verify`` / ``info``）、**解包落地**（``extract`` —— 先校验后落地，不留「先解开再判断」的中间态）。

两条硬规则（``docs/ECOSYSTEM-STRATEGY.md`` §7）：

1. **私钥绝不进仓库**：``root-init`` / ``signer-init`` 拒绝把私钥写进 git 工作树，
   除非显式 ``--insecure-key-output``；默认落在 ``<TRIMUM_HOME>/trust/`` 下。
2. **安装 ≠ 授权**：本命令只回答「来源可不可信、有没有被改过」，
   「这条命令允不允许执行」由运行期策略决定（ToolGateway 分层 + 证书能力交集）。
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from .._utils import emit, fail
from trimum_core.pkg_index import INDEX_NAME
from trimum_core import pkg_index, trmpkg
from trimum_core.models import TRMErrorCode, TrimumError

__command_meta__ = {
    "pkg": {
        "summary": "Build, inspect and verify official .trmpkg packages",
        "args": "{verify,info,create,extract,index,root-init,signer-init}",
        "tags": ["pkg", "ecosystem", "trust"],
        "risk": "low",
    },
    "pkg verify": {
        "summary": "Verify a package against the built-in trust root",
        "args": "<package> [--root-cert PATH]",
        "examples": ["trm pkg verify dist/demo.trmpkg --json"],
        "tags": ["pkg", "trust"],
        "risk": "low",
    },
    "pkg info": {
        "summary": "Print a package manifest without verifying it",
        "args": "<package>",
        "examples": ["trm pkg info dist/demo.trmpkg"],
        "tags": ["pkg"],
        "risk": "low",
    },
    "pkg create": {
        "summary": "Pack a directory into a signed .trmpkg",
        "args": (
            "<source> [-o OUT] [--name N] [--type T] [--version V] [--entry E] "
            "[--signer-cert P] [--key P] [--root-cert P] [--force]"
        ),
        "examples": [
            "trm pkg create ./agents/demo -o dist/demo.trmpkg --type agent "
            "--signer-cert trust/signers/release.crt --key trust/signers/release.key",
        ],
        "tags": ["pkg", "publish"],
        "risk": "medium",
    },
    "pkg index": {
        "summary": "Build and sign the directory index for a folder of .trmpkg files",
        "args": "<directory> [-o PATH] [--signer-cert P] [--key P] [--root-cert P] [--force]",
        "examples": [
            "trm pkg index dist/ --signer-cert trust/signers/release.crt --key trust/signers/release.key",
        ],
        "tags": ["pkg", "publish", "trust"],
        "risk": "medium",
    },
    "pkg extract": {
        "summary": "Verify a package, then unpack it into a directory",
        "args": "<package> --dest DIR [--root-cert PATH] [--force]",
        "tags": ["pkg"],
        "risk": "medium",
    },
    "pkg root-init": {
        "summary": "Generate the official trust root certificate and its key",
        "args": "[--out DIR] [--name NAME] [--force] [--insecure-key-output]",
        "examples": ["trm pkg root-init"],
        "tags": ["pkg", "trust"],
        "risk": "high",
    },
    "pkg signer-init": {
        "summary": "Mint a signer certificate from the trust root",
        "args": (
            "--name N [--tools a,b] [--max-risk X] [--expires-at TS] "
            "[--root-cert P] [--root-key P] [--out DIR]"
        ),
        "examples": [
            "trm pkg signer-init --name trimum-release --tools shell,fs --max-risk high",
        ],
        "tags": ["pkg", "trust"],
        "risk": "high",
    },
}


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("pkg", help="build and verify .trmpkg packages")
    nested = parser.add_subparsers(dest="pkg_command", title="pkg commands")

    verify_parser = nested.add_parser(
        "verify", help="verify a package against the built-in trust root"
    )
    verify_parser.add_argument("package")
    verify_parser.add_argument(
        "--root-cert", default=None, help="trust root to verify against"
    )
    verify_parser.set_defaults(handler=handler)

    info_parser = nested.add_parser("info", help="print a package manifest")
    info_parser.add_argument("package")
    info_parser.set_defaults(handler=handler)

    create_parser = nested.add_parser(
        "create", help="pack a directory into a signed package"
    )
    create_parser.add_argument("source")
    create_parser.add_argument("-o", "--out", default=None, help="output .trmpkg path")
    create_parser.add_argument(
        "--name", default="", help="package name (default: directory name)"
    )
    create_parser.add_argument(
        "--type", default="agent", help="agent | tool | workflow | skill"
    )
    create_parser.add_argument("--version", default="0.0.0")
    create_parser.add_argument("--entry", default="", help="entry point inside the payload")
    create_parser.add_argument(
        "--requires",
        action="append",
        default=[],
        metavar="NAME[=VERSION]",
        help="external dependency (repeatable)",
    )
    create_parser.add_argument(
        "--signer-cert", default=None, help="signer certificate (JSON)"
    )
    create_parser.add_argument(
        "--key", default=None, help="signer private key (PEM); never commit this file"
    )
    create_parser.add_argument(
        "--root-cert", default=None, help="trust root that issued the signer certificate"
    )
    create_parser.add_argument(
        "--force", action="store_true", help="overwrite an existing package"
    )
    create_parser.set_defaults(handler=handler)

    extract_parser = nested.add_parser("extract", help="verify then unpack a package")
    extract_parser.add_argument("package")
    extract_parser.add_argument("--dest", required=True, help="destination directory")
    extract_parser.add_argument("--root-cert", default=None)
    extract_parser.add_argument(
        "--force", action="store_true", help="unpack into a non-empty directory"
    )
    extract_parser.set_defaults(handler=handler)

    index_parser = nested.add_parser(
        "index", help="build and sign the directory index for a folder of packages"
    )
    index_parser.add_argument("directory", help="directory holding the .trmpkg files")
    index_parser.add_argument(
        "-o", "--out", default=None, help=f"output path (default: <directory>/{INDEX_NAME})"
    )
    index_parser.add_argument(
        "--signer-cert", default=None, help="signer certificate; the index must be signed"
    )
    index_parser.add_argument(
        "--key", default=None, help="signer private key (PEM); never commit this file"
    )
    index_parser.add_argument(
        "--root-cert", default=None, help="trust root that issued the signer certificate"
    )
    index_parser.add_argument(
        "--force", action="store_true", help="overwrite an existing index"
    )
    index_parser.set_defaults(handler=handler)

    root_parser = nested.add_parser(
        "root-init", help="generate the official trust root (cert + private key)"
    )
    root_parser.add_argument(
        "--out", default=None, help="output directory (default: <TRIMUM_HOME>/trust)"
    )
    root_parser.add_argument("--name", default="trimum-root")
    root_parser.add_argument("--force", action="store_true")
    root_parser.add_argument(
        "--insecure-key-output",
        action="store_true",
        help="allow writing the private key inside a git working tree (never do this)",
    )
    root_parser.set_defaults(handler=handler)

    signer_parser = nested.add_parser(
        "signer-init", help="mint a signer certificate from the trust root"
    )
    signer_parser.add_argument(
        "--name", required=True, help="signer name, e.g. trimum-release"
    )
    signer_parser.add_argument(
        "--tools", default="*", help="tool whitelist (comma separated)"
    )
    signer_parser.add_argument(
        "--max-risk", default="inherit", help="risk ceiling: inherit | low | medium | high"
    )
    signer_parser.add_argument("--expires-at", default="", help="expiry timestamp (RFC3339)")
    signer_parser.add_argument("--root-cert", default=None)
    signer_parser.add_argument("--root-key", default=None)
    signer_parser.add_argument("--out", default=None)
    signer_parser.add_argument("--force", action="store_true")
    signer_parser.add_argument("--insecure-key-output", action="store_true")
    signer_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm pkg {verify,info,create,extract,index,root-init,signer-init} ...")
    return 0


# ---------------------------------------------------------------------------
# 路径与写盘守卫
# ---------------------------------------------------------------------------


def trust_dir() -> Path:
    """Where the built-in root and the signer keys live by default."""
    from trimum_core.paths import trimum_path

    return trimum_path("trust")


def signer_dir() -> Path:
    """Where signer certificates and keys live by default."""
    return trust_dir() / "signers"


def _root_cert_path(explicit: str | None) -> Path:
    return Path(explicit) if explicit else trmpkg.default_root_path()


def _root_key_path(explicit: str | None) -> Path:
    return Path(explicit) if explicit else trust_dir() / "trimum-root.key"


def _repo_root(path: Path) -> Path | None:
    """Return the enclosing git working tree of *path*, if there is one."""
    current = path.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _refuse_overwrite(path: Path, force: bool, what: str) -> None:
    if path.exists() and not force:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message=f"{what}已存在：{path}（加 --force 覆盖）",
        )


def _write_private_key(path: Path, pem: str, *, insecure_output: bool) -> None:
    """Write a private key with owner-only permissions.

    Refuses to drop a key into a git working tree: the design point of §7 is that
    the root key never enters the repository, and a mistyped ``--out ./config/trust``
    is exactly how that accident happens.
    """
    repo = _repo_root(path)
    if repo is not None and not insecure_output:
        raise TrimumError(
            TRMErrorCode.CONFIG_VALIDATION_FAILED,
            message=(
                f"拒绝把私钥写进 git 仓库（{repo}）：换一个 --out 目录，"
                "或加 --insecure-key-output 明确接受风险"
            ),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pem, encoding="utf-8", newline="\n")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:  # pragma: no cover - Windows and exotic filesystems
        pass


def _parse_requires(items: list[str]) -> dict[str, str]:
    requires: dict[str, str] = {}
    for item in items:
        name, _, version = str(item).partition("=")
        name = name.strip()
        if name:
            requires[name] = version.strip()
    return requires


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


def _verify(package: str, root_cert: str | None) -> dict[str, Any]:
    result = trmpkg.verify_package(
        package, root_path=_root_cert_path(root_cert) if root_cert else None
    )
    return {
        "ok": result.ok,
        "package": result.package,
        "name": result.name,
        "version": result.version,
        "type": result.type,
        "files_checked": result.files_checked,
        "signer": {
            "name": result.signer.get("name", ""),
            "key_id": result.signer.get("key_id", ""),
        },
        "root": {
            "name": result.root.get("name", ""),
            "key_id": result.root.get("key_id", ""),
        },
        "capabilities": result.capabilities(),
        "errors": list(result.errors),
        "warnings": list(result.warnings),
    }


def _info(package: str) -> dict[str, Any]:
    if not Path(package).is_file():
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"包不存在：{package}"
        )
    manifest = trmpkg.read_manifest(package)
    files = manifest.get("files") or {}
    return {
        "package": str(package),
        "format": manifest.get("format", ""),
        "name": manifest.get("name", ""),
        "type": manifest.get("type", ""),
        "version": manifest.get("version", ""),
        "entry": manifest.get("entry", ""),
        "requires": manifest.get("requires", {}),
        "capabilities": manifest.get("capabilities", {}),
        "created_at": manifest.get("created_at", ""),
        "files": sorted(files),
        "files_count": len(files),
    }


def _create(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source)
    if not source.is_dir():
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID, message=f"载荷目录不存在：{source}"
        )
    if not args.signer_cert or not args.key:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message="需要 --signer-cert 与 --key：包必须由根签发的签名者签，不能无签打包",
        )

    signer_cert = trmpkg.load_cert(args.signer_cert)
    root_cert = trmpkg.load_cert(_root_cert_path(args.root_cert))
    if signer_cert.get("issuer_key_id") != root_cert.get("key_id"):
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message=(
                f"签名者证书 {signer_cert.get('name', '?')} 不是这个根签发的"
                f"（issuer_key_id={signer_cert.get('issuer_key_id', '')[:20]}…，"
                f"root key_id={root_cert.get('key_id', '')[:20]}…）"
            ),
        )
    signer_key = Path(args.key).read_text(encoding="utf-8")

    out = Path(args.out) if args.out else Path.cwd() / f"{args.name or source.name}.trmpkg"
    _refuse_overwrite(out, bool(args.force), "包")

    manifest = trmpkg.build_manifest(
        source,
        name=args.name,
        type=args.type,
        version=args.version,
        entry=args.entry,
        requires=_parse_requires(args.requires),
    )
    trmpkg.create_package(
        source,
        out,
        signer_private_pem=signer_key,
        signer_cert=signer_cert,
        chain=[signer_cert, root_cert],
        manifest=manifest,
    )
    return {
        "package": str(out),
        "name": manifest["name"],
        "type": manifest["type"],
        "version": manifest["version"],
        "files_count": len(manifest.get("files") or {}),
        "signer": signer_cert.get("name", ""),
        "root": root_cert.get("name", ""),
    }


def _index(args: argparse.Namespace) -> dict[str, Any]:
    """Build the signed directory index for a folder of packages."""
    directory = Path(args.directory)
    if not args.signer_cert or not args.key:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message=(
                "需要 --signer-cert 与 --key：索引必须签名 ——"
                "不签名的索引等于把「去哪拿这个包」交给中间人"
            ),
        )

    signer_cert = trmpkg.load_cert(args.signer_cert)
    root_path = _root_cert_path(args.root_cert)
    root_cert = trmpkg.load_cert(root_path)
    if signer_cert.get("issuer_key_id") != root_cert.get("key_id"):
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message=(
                f"签名者证书 {signer_cert.get('name', '?')} 不是这个根签发的"
                f"（issuer_key_id={signer_cert.get('issuer_key_id', '')[:20]}…，"
                f"root key_id={root_cert.get('key_id', '')[:20]}…）"
            ),
        )
    signer_key = Path(args.key).read_text(encoding="utf-8")

    out = Path(args.out) if args.out else directory / INDEX_NAME
    _refuse_overwrite(out, bool(args.force), "索引")

    entries = pkg_index.entries_from_directory(directory, root_path=root_path)
    document = pkg_index.build_index(entries)
    container = pkg_index.sign_index(
        document,
        signer_cert=signer_cert,
        signer_private_pem=signer_key,
        chain=[signer_cert, root_cert],
    )
    path = pkg_index.write_index(out, container)
    # 写完自检：刚签出来的索引自己必须先验得过，否则「签名」只是自我安慰。
    pkg_index.verify_index(path, root_path=root_path).require_ok()

    return {
        "index": str(path),
        "directory": str(directory),
        "generated_at": document["generated_at"],
        "count": len(entries),
        "signer": {
            "name": signer_cert.get("name", ""),
            "key_id": signer_cert.get("key_id", ""),
        },
        "root": {"name": root_cert.get("name", ""), "key_id": root_cert.get("key_id", "")},
        "packages": entries,
    }


def _extract(args: argparse.Namespace) -> dict[str, Any]:
    dest = Path(args.dest)
    if dest.exists() and any(dest.iterdir()) and not args.force:
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message=f"目标目录非空：{dest}（加 --force 继续，或换 --dest）",
        )
    root = _root_cert_path(args.root_cert) if args.root_cert else None
    written = trmpkg.extract_package(args.package, dest, root_path=root)
    return {
        "package": str(args.package),
        "dest": str(dest),
        "files_written": written,
        "files_count": len(written),
    }


def _root_init(args: argparse.Namespace) -> dict[str, Any]:
    out = Path(args.out) if args.out else trust_dir()
    cert_path = out / trmpkg.ROOT_CERT_NAME
    key_path = out / "trimum-root.key"
    _refuse_overwrite(cert_path, bool(args.force), "根证书")
    _refuse_overwrite(key_path, bool(args.force), "根私钥")

    cert, private_pem = trmpkg.make_root(args.name)
    _write_private_key(key_path, private_pem, insecure_output=args.insecure_key_output)
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_text(
        json.dumps(cert, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "root": cert["name"],
        "key_id": cert["key_id"],
        "cert": str(cert_path),
        "key": str(key_path),
        "warning": (
            "根私钥是这条渠道的信任源头：备份它、别提交、别复制到别的机器；"
            "丢了就只能换根重签所有包"
        ),
    }


def _signer_init(args: argparse.Namespace) -> dict[str, Any]:
    from trimum_core.identity import MAX_RISK_VALUES

    if args.max_risk not in MAX_RISK_VALUES:
        raise TrimumError(
            TRMErrorCode.CONFIG_VALIDATION_FAILED,
            message=f"--max-risk 只能是 {' | '.join(MAX_RISK_VALUES)}（收到 {args.max_risk!r}）",
        )

    root_cert_path = _root_cert_path(args.root_cert)
    root_key_path = _root_key_path(args.root_key)
    root_cert = trmpkg.load_cert(root_cert_path)
    if not root_key_path.is_file():
        raise TrimumError(
            TRMErrorCode.PACKAGE_INVALID,
            message=f"根私钥不存在：{root_key_path}（签发签名者证书必须有它）",
        )

    out = Path(args.out) if args.out else signer_dir()
    cert_path = out / f"{args.name}.crt"
    key_path = out / f"{args.name}.key"
    _refuse_overwrite(cert_path, bool(args.force), "签名者证书")
    _refuse_overwrite(key_path, bool(args.force), "签名者私钥")

    tools = [item.strip() for item in str(args.tools).split(",") if item.strip()] or ["*"]
    capabilities = {
        "tools": tools,
        "max_risk": args.max_risk,
        "expires_at": args.expires_at or None,
        "scope": "official",
    }
    cert, private_pem = trmpkg.make_signer_cert(
        args.name,
        root_cert,
        root_key_path.read_text(encoding="utf-8"),
        capabilities=capabilities,
        expires_at=args.expires_at,
    )
    _write_private_key(key_path, private_pem, insecure_output=args.insecure_key_output)
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_text(
        json.dumps(cert, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "signer": cert["name"],
        "key_id": cert["key_id"],
        "issued_by": cert["issued_by"],
        "capabilities": capabilities,
        "cert": str(cert_path),
        "key": str(key_path),
    }


# ---------------------------------------------------------------------------
# 人读输出
# ---------------------------------------------------------------------------


def _human_verify(data: dict[str, Any]) -> None:
    state = "OK  " if data["ok"] else "FAIL"
    print(
        f"{state} {data['name']} {data['version']} [{data['type']}] "
        f"files={data['files_checked']} signer={data['signer']['name']} "
        f"root={data['root']['name']}"
    )
    for problem in data["errors"]:
        print(f"[!] {problem}", file=sys.stderr)
    for warning in data["warnings"]:
        print(f"[~] {warning}")


def _human_info(data: dict[str, Any]) -> None:
    print(f"{data['name']} {data['version']} [{data['type']}]")
    print(f"  format:  {data['format']}")
    if data["entry"]:
        print(f"  entry:   {data['entry']}")
    if data["requires"]:
        print(f"  requires: {data['requires']}")
    if data["capabilities"]:
        print(f"  capabilities: {data['capabilities']}")
    print(f"  files:   {data['files_count']}")
    for name in data["files"]:
        print(f"    - {name}")


def _human_create(data: dict[str, Any]) -> None:
    print(
        f"packed {data['name']} {data['version']} [{data['type']}] "
        f"files={data['files_count']} -> {data['package']}"
    )
    print(f"  signed by {data['signer']} (root {data['root']})")


def _human_index(data: dict[str, Any]) -> None:
    print(f"indexed {data['count']} package(s) -> {data['index']}")
    print(f"  signed by {data['signer']['name']} (root {data['root']['name']})")
    for item in data["packages"]:
        short = str(item["sha256"]).split(":", 1)[-1][:12]
        print(f"  - {item['name']} {item['version']} [{item['type']}] {item['url']} {short}")


def _human_extract(data: dict[str, Any]) -> None:
    print(f"verified and unpacked {data['files_count']} file(s) -> {data['dest']}")
    for name in data["files_written"]:
        print(f"  - {name}")


def _human_root_init(data: dict[str, Any]) -> None:
    print(f"trust root {data['root']} generated")
    print(f"  cert: {data['cert']}   (commit this one)")
    print(f"  key:  {data['key']}   (never commit this one)")
    print(f"  key_id: {data['key_id']}")
    print(f"[!] {data['warning']}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def handler(args: argparse.Namespace) -> int:
    """Execute the requested pkg subcommand."""
    command = getattr(args, "pkg_command", None)
    try:
        if command == "verify":
            data = _verify(args.package, args.root_cert)
            emit(args, data, _human_verify)
            return 0 if data["ok"] else 1
        if command == "info":
            data = _info(args.package)
            human = _human_info
        elif command == "create":
            data = _create(args)
            human = _human_create
        elif command == "index":
            data = _index(args)
            human = _human_index
        elif command == "extract":
            data = _extract(args)
            human = _human_extract
        elif command == "root-init":
            data = _root_init(args)
            human = _human_root_init
        elif command == "signer-init":
            data = _signer_init(args)
            human = None
        else:
            return _show_help(args)
    except TrimumError as exc:
        return fail(f"{exc.code.value} {exc.message}")
    except OSError as exc:
        return fail(str(exc))

    emit(args, data, human)
    return 0


__all__ = ["add_subparsers", "handler"]