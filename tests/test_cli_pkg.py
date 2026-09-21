"""`trm pkg` CLI（E5 第二片）：打包 / 校验 / 解包 / 信任锚。

覆盖真实入口（``main([...])``）而不是内部函数：CLI 的退出码、错误码与
「私钥别写进仓库」这类守卫都在这一层。
"""

from __future__ import annotations

import io
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import trmpkg  # noqa: E402
from trimum_core.cli import main  # noqa: E402


@pytest.fixture
def keys(tmp_path):
    """Trust root + a signer certificate issued by it, both on disk."""
    base = tmp_path / "keys"
    base.mkdir()
    root_doc, root_key = trmpkg.make_root("trimum-root")
    (base / "trimum-root.crt").write_text(json.dumps(root_doc, indent=2), encoding="utf-8")
    (base / "trimum-root.key").write_text(root_key, encoding="utf-8")
    signer_doc, signer_key = trmpkg.make_signer_cert(
        "trimum-release",
        root_doc,
        root_key,
        capabilities={"tools": ["shell"], "max_risk": "medium", "scope": "official"},
    )
    (base / "release.crt").write_text(json.dumps(signer_doc, indent=2), encoding="utf-8")
    (base / "release.key").write_text(signer_key, encoding="utf-8")
    return {
        "root_doc": root_doc,
        "root_key": root_key,
        "root_cert": base / "trimum-root.crt",
        "root_key_file": base / "trimum-root.key",
        "signer_doc": signer_doc,
        "signer_cert": base / "release.crt",
        "signer_key": base / "release.key",
    }


@pytest.fixture
def payload(tmp_path):
    """A plausible agent directory."""
    root = tmp_path / "demo-agent"
    (root / "skills").mkdir(parents=True)
    (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "skills" / "a.md").write_text("# skill\n", encoding="utf-8")
    return root


def create_args(payload: Path, out: Path, keys: dict, **overrides) -> list[str]:
    args = [
        "pkg", "create", str(payload),
        "-o", str(out),
        "--name", "demo-agent",
        "--type", "agent",
        "--version", "1.2.3",
        "--entry", "main.py",
        "--signer-cert", str(keys["signer_cert"]),
        "--key", str(keys["signer_key"]),
        "--root-cert", str(keys["root_cert"]),
    ]
    for key, value in overrides.items():
        flag = "--" + key.replace("_", "-")
        if value is True:
            args.append(flag)
        elif value is not False and value is not None:
            args.extend([flag, str(value)])
    return args


def make_package(payload: Path, out: Path, keys: dict) -> Path:
    assert main(create_args(payload, out, keys)) == 0
    return out


def rewrite(package: Path, dest: Path, mutate) -> Path:
    """Unpack, tamper, repack — simulates someone editing the package in transit."""
    with tarfile.open(package, "r:gz") as tar:
        blobs = {
            member.name: tar.extractfile(member).read()
            for member in tar.getmembers()
            if member.isfile() and tar.extractfile(member) is not None
        }
    blobs = mutate(dict(blobs))
    with tarfile.open(dest, "w:gz") as tar:
        for name, blob in blobs.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
    return dest


class TestCreateAndVerify:
    def test_round_trip(self, payload, tmp_path, keys, capsys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)
        capsys.readouterr()

        code = main([
            "--json", "pkg", "verify", str(package), "--root-cert", str(keys["root_cert"])
        ])
        data = json.loads(capsys.readouterr().out)

        assert code == 0
        assert data["ok"] is True
        assert (data["name"], data["version"], data["type"]) == ("demo-agent", "1.2.3", "agent")
        assert data["files_checked"] == 2
        assert data["signer"]["name"] == "trimum-release"
        assert data["root"]["name"] == "trimum-root"
        assert data["capabilities"]["tools"] == ["shell"]

    def test_human_output_reports_failure_and_exit_code(self, payload, tmp_path, keys, capsys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)
        tampered = rewrite(package, tmp_path / "tampered.trmpkg", lambda blobs: {
            **blobs, "main.py": b"print('pwned')\n"
        })
        capsys.readouterr()

        code = main(["pkg", "verify", str(tampered), "--root-cert", str(keys["root_cert"])])
        captured = capsys.readouterr()

        assert code == 1
        assert "FAIL" in captured.out
        assert "哈希不符" in captured.err

    def test_verify_uses_the_trust_root_env_override(self, payload, tmp_path, keys, monkeypatch, capsys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)
        monkeypatch.setenv("TRIMUM_TRUST_ROOT", str(keys["root_cert"]))
        capsys.readouterr()

        assert main(["pkg", "verify", str(package)]) == 0
        assert "OK" in capsys.readouterr().out

    def test_foreign_root_is_rejected(self, payload, tmp_path, keys, capsys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)
        other_root, _ = trmpkg.make_root("someone-else")
        other_path = tmp_path / "other-root.crt"
        other_path.write_text(json.dumps(other_root, indent=2), encoding="utf-8")
        capsys.readouterr()

        code = main(["pkg", "verify", str(package), "--root-cert", str(other_path)])

        assert code == 1
        assert "根" in capsys.readouterr().err

    def test_missing_package_is_invalid(self, tmp_path, capsys):
        assert main(["pkg", "verify", str(tmp_path / "nope.trmpkg")]) == 1
        assert "TRM-4009" in capsys.readouterr().err


class TestCreateGuards:
    def test_packing_requires_signing_material(self, payload, tmp_path, capsys):
        args = ["pkg", "create", str(payload), "-o", str(tmp_path / "x.trmpkg")]

        assert main(args) == 1
        assert "--signer-cert" in capsys.readouterr().err

    def test_signer_from_another_root_is_refused(self, payload, tmp_path, keys, capsys):
        other_root, other_key = trmpkg.make_root("someone-else")
        other_signer, _ = trmpkg.make_signer_cert("not-ours", other_root, other_key)
        cert_path = tmp_path / "not-ours.crt"
        cert_path.write_text(json.dumps(other_signer, indent=2), encoding="utf-8")

        args = create_args(
            payload,
            tmp_path / "x.trmpkg",
            keys,
            signer_cert=str(cert_path),
        )

        assert main(args) == 1
        assert "不是这个根签发的" in capsys.readouterr().err

    def test_existing_output_needs_force(self, payload, tmp_path, keys, capsys):
        out = tmp_path / "demo.trmpkg"
        make_package(payload, out, keys)
        capsys.readouterr()

        assert main(create_args(payload, out, keys)) == 1
        assert "--force" in capsys.readouterr().err
        assert main(create_args(payload, out, keys, force=True)) == 0

    def test_packing_an_unknown_type_is_refused(self, payload, tmp_path, keys, capsys):
        args = create_args(payload, tmp_path / "x.trmpkg", keys, type="extension")

        assert main(args) == 1
        assert "未知包类型" in capsys.readouterr().err


class TestInfo:
    def test_reports_the_manifest(self, payload, tmp_path, keys, capsys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)
        capsys.readouterr()

        assert main(["--json", "pkg", "info", str(package)]) == 0
        data = json.loads(capsys.readouterr().out)

        assert data["entry"] == "main.py"
        assert data["files"] == ["main.py", "skills/a.md"]
        assert data["format"] == trmpkg.FORMAT

    def test_missing_package(self, tmp_path, capsys):
        assert main(["pkg", "info", str(tmp_path / "nope.trmpkg")]) == 1
        assert "TRM-4009" in capsys.readouterr().err


class TestExtract:
    def test_verifies_then_unpacks(self, payload, tmp_path, keys, capsys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)
        dest = tmp_path / "out"
        capsys.readouterr()

        code = main([
            "pkg", "extract", str(package), "--dest", str(dest),
            "--root-cert", str(keys["root_cert"]),
        ])

        assert code == 0
        assert (dest / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
        assert (dest / "skills" / "a.md").is_file()

    def test_tampered_package_writes_nothing(self, payload, tmp_path, keys, capsys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)
        tampered = rewrite(package, tmp_path / "tampered.trmpkg", lambda blobs: {
            **blobs, "main.py": b"print('pwned')\n"
        })
        dest = tmp_path / "out"
        capsys.readouterr()

        code = main([
            "pkg", "extract", str(tampered), "--dest", str(dest),
            "--root-cert", str(keys["root_cert"]),
        ])

        assert code == 1
        assert not (dest / "main.py").exists()

    def test_non_empty_destination_needs_force(self, payload, tmp_path, keys, capsys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)
        dest = tmp_path / "out"
        dest.mkdir()
        (dest / "keep.txt").write_text("mine\n", encoding="utf-8")
        capsys.readouterr()

        args = [
            "pkg", "extract", str(package), "--dest", str(dest),
            "--root-cert", str(keys["root_cert"]),
        ]
        assert main(args) == 1
        assert "--force" in capsys.readouterr().err

        assert main(args + ["--force"]) == 0
        assert (dest / "keep.txt").is_file()


class TestRootInit:
    def test_generates_cert_and_key(self, tmp_path, capsys):
        out = tmp_path / "trust"

        code = main(["--json", "pkg", "root-init", "--out", str(out), "--insecure-key-output"])
        data = json.loads(capsys.readouterr().out)

        assert code == 0
        cert = json.loads((out / trmpkg.ROOT_CERT_NAME).read_text(encoding="utf-8"))
        assert cert["role"] == "root"
        assert cert["alg"] == trmpkg.ALG
        assert cert["key_id"] == data["key_id"] == trmpkg.key_id(cert["public_key"])
        assert (out / "trimum-root.key").is_file()

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_key_is_not_world_readable(self, tmp_path, capsys):
        out = tmp_path / "trust"

        assert main(["pkg", "root-init", "--out", str(out), "--insecure-key-output"]) == 0

        mode = (out / "trimum-root.key").stat().st_mode & 0o777
        assert mode == 0o600

    def test_refuses_to_drop_the_key_into_a_git_tree(self, tmp_path, capsys):
        """``--out`` inside the repository working tree must not receive a key."""
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        out = repo / "config" / "trust"

        code = main(["pkg", "root-init", "--out", str(out)])
        captured = capsys.readouterr()

        assert code == 1
        assert "git 仓库" in captured.err
        assert not (out / "trimum-root.key").exists()
        assert not (out / trmpkg.ROOT_CERT_NAME).exists()

    def test_refuses_overwrite_without_force(self, tmp_path, capsys):
        out = tmp_path / "trust"
        assert main(["pkg", "root-init", "--out", str(out), "--insecure-key-output"]) == 0
        capsys.readouterr()

        assert main(["pkg", "root-init", "--out", str(out), "--insecure-key-output"]) == 1
        assert "--force" in capsys.readouterr().err


class TestSignerInit:
    def signer_args(self, keys, out, **overrides) -> list[str]:
        args = [
            "pkg", "signer-init", "--name", "trimum-release",
            "--out", str(out),
            "--root-cert", str(keys["root_cert"]),
            "--root-key", str(keys["root_key_file"]),
            "--insecure-key-output",
        ]
        for key, value in overrides.items():
            args.extend(["--" + key.replace("_", "-"), str(value)])
        return args

    def test_root_can_verify_the_minted_certificate(self, tmp_path, keys, capsys):
        out = tmp_path / "signers"

        code = main(self.signer_args(keys, out, tools="shell,fs", max_risk="high"))
        assert code == 0
        cert = json.loads((out / "trimum-release.crt").read_text(encoding="utf-8"))
        signature = cert.pop("issuer_signature")
        assert trmpkg.verify_bytes(
            trmpkg.canonical_bytes(cert), signature, keys["root_doc"]["public_key"]
        )
        assert cert["capabilities"] == {
            "tools": ["shell", "fs"],
            "max_risk": "high",
            "expires_at": None,
            "scope": "official",
        }
        assert cert["issuer_key_id"] == keys["root_doc"]["key_id"]

    def test_rejects_an_unknown_risk_ceiling(self, tmp_path, keys, capsys):
        code = main(self.signer_args(keys, tmp_path / "signers", max_risk="extreme"))

        assert code == 1
        assert "--max-risk" in capsys.readouterr().err

    def test_missing_root_key_is_reported(self, tmp_path, keys, capsys):
        args = [
            "pkg", "signer-init", "--name", "release", "--out", str(tmp_path / "signers"),
            "--root-cert", str(keys["root_cert"]),
            "--root-key", str(tmp_path / "nope.key"),
        ]

        assert main(args) == 1
        assert "根私钥不存在" in capsys.readouterr().err


class TestBuiltinRoot:
    """The repository ships a real anchor — not a placeholder."""

    def test_repo_ships_a_well_formed_root_certificate(self):
        text = trmpkg.REPO_ROOT_CERT.read_text(encoding="utf-8")
        cert = json.loads(text)

        assert trmpkg.REPO_ROOT_CERT.is_file()
        assert cert["role"] == "root"
        assert cert["alg"] == trmpkg.ALG
        assert cert["key_id"] == trmpkg.key_id(cert["public_key"])
        assert "PRIVATE" not in text

    def test_repo_root_rejects_a_chain_from_another_root(self, payload, tmp_path, keys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)

        result = trmpkg.verify_package(package, root_path=trmpkg.REPO_ROOT_CERT)

        assert not result.ok
        assert any("不是本机内置根" in err for err in result.errors)
        assert any("签名者证书不是内置根签发的" in err for err in result.errors)

    def test_lookup_order_is_env_then_home_then_repo(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        monkeypatch.setenv("TRIMUM_HOME", str(home))
        monkeypatch.delenv("TRIMUM_TRUST_ROOT", raising=False)

        assert trmpkg.default_root_path() == trmpkg.REPO_ROOT_CERT

        (home / "trust").mkdir(parents=True)
        (home / "trust" / trmpkg.ROOT_CERT_NAME).write_text("{}\n", encoding="utf-8")
        assert trmpkg.default_root_path() == home / "trust" / trmpkg.ROOT_CERT_NAME

        override = tmp_path / "elsewhere.crt"
        monkeypatch.setenv("TRIMUM_TRUST_ROOT", str(override))
        assert trmpkg.default_root_path() == override


class TestSignerCapabilitiesReachTheRuntimeContract:
    def test_package_carries_the_signers_capabilities(self, payload, tmp_path, keys, capsys):
        package = make_package(payload, tmp_path / "demo.trmpkg", keys)
        result = trmpkg.verify_package(package, root_path=keys["root_cert"])

        assert result.capabilities()["max_risk"] == "medium"

    def test_trust_root_dir_is_under_the_data_root(self, monkeypatch, tmp_path):
        from trimum_core.cli.commands import pkg as pkg_mod

        monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
        assert pkg_mod.trust_dir() == tmp_path / "home" / "trust"
        assert pkg_mod.signer_dir() == tmp_path / "home" / "trust" / "signers"