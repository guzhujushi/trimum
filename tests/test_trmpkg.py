"""``.trmpkg`` 打包与校验（E5 第一片）。

覆盖：往返打包/校验、能力清单透传、四类拒绝路径（载荷被改 / manifest 被改 / 换了根 /
路径越界）以及「校验不通过就不解包」。
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import trmpkg  # noqa: E402
from trimum_core.models import TRMErrorCode, TrimumError  # noqa: E402


@pytest.fixture
def trust(tmp_path):
    """一对钥匙：官方根（信任锚）+ 由它签发的发布签名者。"""
    root_doc, root_key = trmpkg.make_root("trimum-root")
    root_path = tmp_path / "trimum-root.crt"
    root_path.write_text(json.dumps(root_doc, indent=2), encoding="utf-8")
    signer_doc, signer_key = trmpkg.make_signer_cert(
        "trimum-release",
        root_doc,
        root_key,
        capabilities={"tools": ["shell"], "max_risk": "medium"},
    )
    return {
        "root_doc": root_doc,
        "root_key": root_key,
        "root_path": root_path,
        "signer_doc": signer_doc,
        "signer_key": signer_key,
    }


@pytest.fixture
def payload(tmp_path):
    """一份像样的 agent 目录（含子目录）。"""
    root = tmp_path / "demo-agent"
    (root / "skills").mkdir(parents=True)
    (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "skills" / "a.md").write_text("# skill\n", encoding="utf-8")
    (root / "cert.json").write_text("{}\n", encoding="utf-8")
    return root


def pack(source, out, trust, **fields):
    manifest = trmpkg.build_manifest(
        source,
        **{
            "name": "demo-agent",
            "type": "agent",
            "version": "1.2.3",
            "entry": "main.py",
            **fields,
        },
    )
    return trmpkg.create_package(
        source,
        out,
        signer_private_pem=trust["signer_key"],
        signer_cert=trust["signer_doc"],
        chain=[trust["signer_doc"], trust["root_doc"]],
        manifest=manifest,
    )


def rewrite(package: Path, dest: Path, mutate) -> Path:
    """把包解开、按 ``mutate`` 改一改、再打回去（模拟「有人在路上动了包」）。"""
    with tarfile.open(package, "r:gz") as tar:
        blobs = {
            m.name: tar.extractfile(m).read()
            for m in tar.getmembers()
            if m.isfile() and tar.extractfile(m) is not None
        }
    blobs = mutate(dict(blobs))
    with tarfile.open(dest, "w:gz") as tar:
        for name, payload_bytes in blobs.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload_bytes)
            tar.addfile(info, io.BytesIO(payload_bytes))
    return dest


class TestRoundTrip:
    def test_package_verifies_against_the_builtin_root(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)

        result = trmpkg.verify_package(package, root_path=trust["root_path"])

        assert result.ok, result.errors
        assert (result.name, result.version, result.type) == ("demo-agent", "1.2.3", "agent")
        assert result.files_checked == 3
        assert set(result.manifest["files"]) == {"main.py", "skills/a.md", "cert.json"}
        assert result.manifest["entry"] == "main.py"

    def test_signer_capabilities_travel_with_the_package(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)

        result = trmpkg.verify_package(package, root_path=trust["root_path"])

        assert result.capabilities() == {"tools": ["shell"], "max_risk": "medium"}
        assert result.signer["issued_by"] == "trimum-root"

    def test_every_file_digest_is_sha256_of_the_payload(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)

        manifest = trmpkg.read_manifest(package)

        assert manifest["format"] == trmpkg.FORMAT
        assert manifest["files"]["main.py"] == trmpkg.file_digest(payload / "main.py")

    def test_extract_writes_the_payload_and_skips_metadata(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)
        dest = tmp_path / "out"

        written = trmpkg.extract_package(
            package, dest, root_path=trust["root_path"]
        )

        assert sorted(written) == ["cert.json", "main.py", "skills/a.md"]
        assert (dest / "skills" / "a.md").read_text(encoding="utf-8") == "# skill\n"
        assert not (dest / trmpkg.MANIFEST_NAME).exists()


class TestRejections:
    def test_tampered_payload_is_rejected(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)
        tampered = rewrite(
            package,
            tmp_path / "tampered.trmpkg",
            lambda blobs: {**blobs, "main.py": b"print('pwned')\n"},
        )

        result = trmpkg.verify_package(tampered, root_path=trust["root_path"])

        assert not result.ok
        assert any("哈希不符：main.py" in err for err in result.errors)

    def test_tampered_manifest_breaks_the_signature(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)

        def mutate(blobs):
            manifest = json.loads(blobs[trmpkg.MANIFEST_NAME].decode("utf-8"))
            manifest["version"] = "9.9.9"
            blobs[trmpkg.MANIFEST_NAME] = json.dumps(manifest).encode("utf-8")
            return blobs

        tampered = rewrite(package, tmp_path / "t2.trmpkg", mutate)

        result = trmpkg.verify_package(tampered, root_path=trust["root_path"])

        assert not result.ok
        assert any("签名验证失败" in err for err in result.errors)

    def test_extra_file_absent_from_the_manifest_is_rejected(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)
        tampered = rewrite(
            package,
            tmp_path / "t3.trmpkg",
            lambda blobs: {**blobs, "backdoor.sh": b"echo pwned\n"},
        )

        result = trmpkg.verify_package(tampered, root_path=trust["root_path"])

        assert not result.ok
        assert any("额外文件：backdoor.sh" in err for err in result.errors)

    def test_a_different_root_does_not_trust_the_package(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)
        other_root, _ = trmpkg.make_root("trimum-root")  # 同名不同钥匙
        other_path = tmp_path / "other-root.crt"
        other_path.write_text(json.dumps(other_root), encoding="utf-8")

        result = trmpkg.verify_package(package, root_path=other_path)

        assert not result.ok
        assert any("不是本机内置根" in err for err in result.errors)
        assert any("签名者证书不是内置根签发的" in err for err in result.errors)

    def test_no_builtin_root_means_no_trust(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)
        missing = tmp_path / "nope" / "trimum-root.crt"

        result = trmpkg.verify_package(package, root_path=missing)

        assert not result.ok
        assert any("找不到内置根证书" in err for err in result.errors)
        assert any("无法验证签发者" in err for err in result.errors)

    def test_path_traversal_member_is_rejected(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)
        escaped = rewrite(
            package,
            tmp_path / "escape.trmpkg",
            lambda blobs: {**blobs, "../evil.sh": b"echo pwned\n"},
        )

        result = trmpkg.verify_package(escaped, root_path=trust["root_path"])

        assert not result.ok
        assert any("路径越界" in err for err in result.errors)

        with pytest.raises(TrimumError):
            trmpkg.extract_package(escaped, tmp_path / "out", root_path=trust["root_path"])

    def test_symlink_member_is_rejected(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)
        dest = tmp_path / "link.trmpkg"
        with tarfile.open(package, "r:gz") as tar:
            blobs = [
                (m.name, tar.extractfile(m).read() if m.isfile() else None)
                for m in tar.getmembers()
            ]
        with tarfile.open(dest, "w:gz") as tar:
            for name, data in blobs:
                if data is None:
                    continue
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            link = tarfile.TarInfo("link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tar.addfile(link)

        result = trmpkg.verify_package(dest, root_path=trust["root_path"])

        assert not result.ok
        assert any("链接" in err for err in result.errors)

    def test_extract_refuses_a_package_that_does_not_verify(self, payload, tmp_path, trust):
        package = pack(payload, tmp_path / "demo.trmpkg", trust)
        tampered = rewrite(
            package,
            tmp_path / "t4.trmpkg",
            lambda blobs: {**blobs, "main.py": b"print('pwned')\n"},
        )

        with pytest.raises(TrimumError) as excinfo:
            trmpkg.extract_package(tampered, tmp_path / "out", root_path=trust["root_path"])

        assert excinfo.value.code is TRMErrorCode.PACKAGE_VERIFY_FAILED
        assert not (tmp_path / "out" / "main.py").exists()


class TestManifest:
    def test_unknown_type_is_refused(self, payload):
        with pytest.raises(TrimumError) as excinfo:
            trmpkg.build_manifest(payload, type="plugin")

        assert excinfo.value.code is TRMErrorCode.PACKAGE_INVALID

    def test_symlinks_are_not_packed(self, payload):
        link = payload / "linked.md"
        try:
            link.symlink_to(payload / "main.py")
        except (OSError, NotImplementedError):  # Windows 无权限时跳过
            pytest.skip("本机不允许创建符号链接")

        manifest = trmpkg.build_manifest(payload, type="agent")

        assert "linked.md" not in manifest["files"]

    def test_a_non_tarball_is_package_invalid(self, tmp_path):
        broken = tmp_path / "broken.trmpkg"
        broken.write_bytes(b"not a tar at all")

        with pytest.raises(TrimumError) as excinfo:
            trmpkg.verify_package(broken, root_path=tmp_path / "root.crt")

        assert excinfo.value.code is TRMErrorCode.PACKAGE_INVALID

    def test_missing_package_raises(self, tmp_path):
        with pytest.raises(TrimumError):
            trmpkg.verify_package(tmp_path / "nope.trmpkg")