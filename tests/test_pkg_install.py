"""`trm install` / `pkg_install` —— 官方渠道的安装与登记（E5 第三片）。

覆盖：按类型落地、登记表、agent 证书（official → TRUSTED / 降级 → CONFIRM）、
签名索引（哈希承诺、未签名索引、目录里没有的名字）、以及
``--allow-untrusted`` 只放宽「来源」而**不放宽包内路径**这条红线。
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import pkg_index, pkg_install, trmpkg  # noqa: E402
from trimum_core.agent_cert import CertTrustLevel, check_agent_trust  # noqa: E402
from trimum_core.cli import main  # noqa: E402
from trimum_core.models import TRMErrorCode, TrimumError  # noqa: E402

TYPES = (
    ("demo-agent", "agent", "agents"),
    ("demo-tool", "tool", "tools"),
    ("demo-flow", "workflow", "workflows"),
    ("demo-skill", "skill", "skills"),
)


@pytest.fixture
def keys(tmp_path):
    """A trust root plus the signer certificate it issued (both on disk)."""
    base = tmp_path / "keys"
    base.mkdir()
    root_doc, root_key = trmpkg.make_root("trimum-root")
    root_path = base / "trimum-root.crt"
    root_path.write_text(json.dumps(root_doc, indent=2), encoding="utf-8")
    signer_doc, signer_key = trmpkg.make_signer_cert(
        "trimum-release",
        root_doc,
        root_key,
        capabilities={"tools": ["shell"], "max_risk": "medium", "scope": "official"},
    )
    signer_path = base / "release.crt"
    signer_path.write_text(json.dumps(signer_doc, indent=2), encoding="utf-8")
    return {
        "root_doc": root_doc,
        "root_key": root_key,
        "root_path": root_path,
        "signer_doc": signer_doc,
        "signer_key": signer_key,
        "signer_path": signer_path,
    }


def make_payload(root: Path, *, body: str = "print('hi')\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.py").write_text(body, encoding="utf-8")
    return root


def build_package(payload: Path, out: Path, keys: dict, *, name: str, kind: str = "agent") -> Path:
    manifest = trmpkg.build_manifest(
        payload, name=name, type=kind, version="1.0.0", entry="main.py"
    )
    trmpkg.create_package(
        payload,
        out,
        signer_private_pem=keys["signer_key"],
        signer_cert=keys["signer_doc"],
        chain=[keys["signer_doc"], keys["root_doc"]],
        manifest=manifest,
    )
    return out


@pytest.fixture
def channel(tmp_path, keys):
    """A local stand-in for the official directory: signed index + packages."""
    root = tmp_path / "channel"
    root.mkdir()
    packages: dict[str, Path] = {}
    entries: list[dict] = []
    for name, kind, _ in TYPES:
        payload = make_payload(tmp_path / "src" / name)
        package = build_package(
            payload, root / f"{name}-1.0.0.trmpkg", keys, name=name, kind=kind
        )
        packages[name] = package
        entries.append(
            pkg_index.package_entry(
                name,
                type=kind,
                version="1.0.0",
                url=package.name,
                sha256=trmpkg.file_digest(package),
                entry="main.py",
                description=f"{name} demo",
            )
        )
    container = pkg_index.sign_index(
        pkg_index.build_index(entries),
        signer_cert=keys["signer_doc"],
        signer_private_pem=keys["signer_key"],
        chain=[keys["signer_doc"], keys["root_doc"]],
    )
    index = pkg_index.write_index(root / pkg_index.INDEX_NAME, container)
    return {"dir": root, "index": index, "packages": packages, "entries": entries}


@pytest.fixture
def foreign_package(tmp_path):
    """A package signed by a root this machine has never heard of."""
    other_root, other_key = trmpkg.make_root("someone-else")
    signer_doc, signer_key = trmpkg.make_signer_cert("someone-release", other_root, other_key)
    payload = make_payload(tmp_path / "src" / "outside")
    package = tmp_path / "outside-1.0.0.trmpkg"
    manifest = trmpkg.build_manifest(
        payload, name="outside", type="agent", version="1.0.0", entry="main.py"
    )
    trmpkg.create_package(
        payload,
        package,
        signer_private_pem=signer_key,
        signer_cert=signer_doc,
        chain=[signer_doc, other_root],
        manifest=manifest,
    )
    return package


@pytest.fixture
def home(monkeypatch, tmp_path, keys):
    """Point the data root and the trust anchor at throwaway test values.

    ``TRIMUM_HOME`` keeps the install out of the developer's real ``~/.trimum``;
    ``TRIMUM_TRUST_ROOT`` pins the anchor to this test's root, so the assertions
    do not depend on which root the machine happens to have built in.
    """
    target = tmp_path / "home"
    monkeypatch.setenv("TRIMUM_HOME", str(target))
    monkeypatch.setenv("TRIMUM_TRUST_ROOT", str(keys["root_path"]))
    return target


class TestInstallFromFile:
    def test_installs_registers_and_issues_an_official_cert(self, home, channel, keys, capsys):
        package = channel["packages"]["demo-agent"]

        code = main(["--json", "install", "--file", str(package)])
        record = json.loads(capsys.readouterr().out)

        assert code == 0
        assert record["trust"] == pkg_install.TRUST_OFFICIAL
        assert record["signer"] == "trimum-release"
        assert (home / "agents" / "demo-agent" / "main.py").is_file()
        assert record["package_sha256"] == trmpkg.file_digest(package)

        stored = json.loads((home / "config" / "installed.json5").read_text(encoding="utf-8"))
        assert stored["packages"]["demo-agent"]["trust"] == pkg_install.TRUST_OFFICIAL

    def test_the_agent_certificate_makes_the_agent_trusted(self, home, channel, capsys):
        main(["install", "--file", str(channel["packages"]["demo-agent"])])
        capsys.readouterr()

        level, cert = check_agent_trust("demo-agent")

        assert level is CertTrustLevel.TRUSTED
        assert cert.cert_type.value == "official"
        assert cert.capabilities["tools"] == ["shell"]

    @pytest.mark.parametrize("name,kind,data_dir", TYPES)
    def test_each_type_lands_in_its_own_root(self, home, channel, name, kind, data_dir, capsys):
        code = main(["install", "--file", str(channel["packages"][name])])

        assert code == 0
        assert (home / data_dir / name / "main.py").is_file()
        assert not (home / "agents" / name).exists() or kind == "agent"

    def test_an_unknown_type_is_refused(self, tmp_path, home, keys, capsys):
        payload = make_payload(tmp_path / "src" / "weird")
        manifest = trmpkg.build_manifest(payload, name="weird", type="agent", version="1.0.0")
        manifest["type"] = "extension"  # 手改 manifest：类型不在白名单
        package = tmp_path / "weird.trmpkg"
        trmpkg.create_package(
            payload,
            package,
            signer_private_pem=keys["signer_key"],
            signer_cert=keys["signer_doc"],
            chain=[keys["signer_doc"], keys["root_doc"]],
            manifest=manifest,
        )
        capsys.readouterr()

        assert main(["install", "--file", str(package)]) == 1
        assert "未知包类型" in capsys.readouterr().err

    def test_reinstalling_needs_force(self, home, channel, capsys):
        package = channel["packages"]["demo-agent"]
        main(["install", "--file", str(package)])
        capsys.readouterr()

        assert main(["install", "--file", str(package)]) == 1
        assert "--force" in capsys.readouterr().err
        assert main(["install", "--file", str(package), "--force"]) == 0

    def test_a_name_and_a_file_together_are_refused(self, home, channel, capsys):
        args = ["install", "demo-agent", "--file", str(channel["packages"]["demo-agent"])]

        assert main(args) == 1
        assert "not both" in capsys.readouterr().err


class TestUntrustedPath:
    def test_foreign_package_is_refused_by_default(self, home, foreign_package, capsys):
        assert main(["install", "--file", str(foreign_package)]) == 1
        captured = capsys.readouterr()

        assert "TRM-4010" in captured.err
        assert not (home / "agents" / "outside").exists()

    def test_allow_untrusted_registers_it_as_untrusted(self, home, foreign_package, capsys):
        code = main(["--json", "install", "--file", str(foreign_package), "--allow-untrusted"])
        record = json.loads(capsys.readouterr().out)

        assert code == 0
        assert record["trust"] == pkg_install.TRUST_UNTRUSTED
        assert "强制逐条确认" in record["warning"]
        assert (home / "agents" / "outside" / "main.py").is_file()

    def test_untrusted_agent_needs_confirmation_at_runtime(self, home, foreign_package, capsys):
        main(["install", "--file", str(foreign_package), "--allow-untrusted"])
        capsys.readouterr()

        level, cert = check_agent_trust("outside")

        assert level is CertTrustLevel.CONFIRM
        assert cert.capabilities["scope"] == pkg_install.TRUST_UNTRUSTED

    def test_untrusted_names_lists_the_downgraded_installs(self, home, channel, foreign_package, capsys):
        main(["install", "--file", str(channel["packages"]["demo-tool"])])
        main(["install", "--file", str(foreign_package), "--allow-untrusted"])
        capsys.readouterr()

        assert pkg_install.untrusted_names() == {"outside"}
        assert pkg_install.untrusted_names(kind="tool") == set()

    def test_path_traversal_is_still_refused_when_untrusted(self, home, tmp_path, keys, capsys):
        """``--allow-untrusted`` 放宽的是来源，不是「包内路径越界」。"""
        payload = make_payload(tmp_path / "src" / "escape")
        manifest = trmpkg.build_manifest(
            payload, name="escape", type="agent", version="1.0.0", entry="main.py"
        )
        package = tmp_path / "escape.trmpkg"
        trmpkg.create_package(
            payload,
            package,
            signer_private_pem=keys["signer_key"],
            signer_cert=keys["signer_doc"],
            chain=[keys["signer_doc"], keys["root_doc"]],
            manifest=manifest,
        )
        with tarfile.open(package, "r:gz") as tar:
            blobs = [(m.name, tar.extractfile(m).read()) for m in tar.getmembers() if m.isfile()]
        with tarfile.open(package, "w:gz") as tar:
            for name, data in blobs:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            info = tarfile.TarInfo("../pwned.sh")
            info.size = len(b"echo pwned\n")
            tar.addfile(info, io.BytesIO(b"echo pwned\n"))
        capsys.readouterr()

        with pytest.raises(TrimumError) as excinfo:
            pkg_install.install_package(package, allow_untrusted=True)

        assert excinfo.value.code is TRMErrorCode.PACKAGE_VERIFY_FAILED
        assert not (home / "pwned.sh").exists()


class TestInstallFromIndex:
    def test_resolves_a_relative_url_and_installs(self, home, channel, capsys):
        code = main(["install", "demo-tool", "--index", str(channel["index"])])

        assert code == 0
        assert (home / "tools" / "demo-tool" / "main.py").is_file()
        assert (home / "cache" / "pkgs" / "demo-tool-1.0.0.trmpkg").is_file()

    def test_index_env_override_is_honoured(self, home, channel, monkeypatch, capsys):
        monkeypatch.setenv(pkg_install.INDEX_ENV, str(channel["index"]))

        assert main(["install", "demo-skill"]) == 0
        assert (home / "skills" / "demo-skill" / "main.py").is_file()

    def test_unknown_name_is_package_not_found(self, home, channel, capsys):
        code = main(["install", "nope", "--index", str(channel["index"])])

        assert code == 1
        assert "TRM-4011" in capsys.readouterr().err

    def test_the_indexes_hash_promise_is_enforced(self, home, channel, keys, capsys):
        """索引是签名的：改内容要重签 —— 这里签一份「承诺了错哈希」的索引。"""
        document = json.loads(channel["index"].read_text(encoding="utf-8"))["document"]
        document["packages"][0]["sha256"] = "sha256:" + "0" * 64
        container = pkg_index.sign_index(
            document,
            signer_cert=keys["signer_doc"],
            signer_private_pem=keys["signer_key"],
            chain=[keys["signer_doc"], keys["root_doc"]],
        )
        pkg_index.write_index(channel["index"], container)
        capsys.readouterr()

        code = main(["install", TYPES[0][0], "--index", str(channel["index"])])

        assert code == 1
        assert "哈希与下载到的包不符" in capsys.readouterr().err
        assert not (home / "agents" / TYPES[0][0]).exists()

    def test_an_unsigned_index_is_refused(self, home, channel, capsys):
        container = json.loads(channel["index"].read_text(encoding="utf-8"))
        unsigned = channel["dir"] / "unsigned.json5"
        unsigned.write_text(json.dumps({"document": container["document"]}), encoding="utf-8")

        code = main(["install", "demo-agent", "--index", str(unsigned)])

        assert code == 1
        assert "索引缺少签名" in capsys.readouterr().err
        assert not (home / "agents" / "demo-agent").exists()

    def test_an_unsigned_index_falls_back_to_the_package_signature(self, home, channel, capsys):
        """索引不签名只说明「这份清单没人背书」，包的来源仍由包自己的签名决定。"""
        container = json.loads(channel["index"].read_text(encoding="utf-8"))
        unsigned = channel["dir"] / "unsigned.json5"
        unsigned.write_text(json.dumps({"document": container["document"]}), encoding="utf-8")
        capsys.readouterr()

        code = main(["--json", "install", "demo-agent", "--index", str(unsigned), "--allow-untrusted"])
        record = json.loads(capsys.readouterr().out)

        assert code == 0
        assert record["index_verified"] is False
        assert record["trust"] == pkg_install.TRUST_OFFICIAL

    def test_a_verified_index_is_recorded_as_such(self, home, channel, capsys):
        capsys.readouterr()

        assert main(["--json", "install", "demo-agent", "--index", str(channel["index"])]) == 0
        record = json.loads(capsys.readouterr().out)

        assert record["index_verified"] is True
        assert record["index_source"] == str(channel["index"])

    def test_a_tampered_package_fails_against_the_index_hash(self, home, channel, capsys):
        package = channel["packages"]["demo-flow"]
        package.write_bytes(package.read_bytes() + b"junk")
        capsys.readouterr()

        code = main(["install", "demo-flow", "--index", str(channel["index"])])

        assert code == 1
        assert "哈希与下载到的包不符" in capsys.readouterr().err
        assert not (home / "workflows" / "demo-flow").exists()

    def test_missing_index_is_reported(self, home, tmp_path, capsys):
        code = main(["install", "demo-agent", "--index", str(tmp_path / "nope.json5")])

        assert code == 1
        assert "找不到文件" in capsys.readouterr().err


class TestCliWiring:
    def test_list_reports_the_ledger(self, home, channel, capsys):
        main(["install", "--file", str(channel["packages"]["demo-agent"])])
        capsys.readouterr()

        assert main(["--json", "install", "--list"]) == 0
        data = json.loads(capsys.readouterr().out)

        assert data["count"] == 1
        assert data["packages"][0]["name"] == "demo-agent"

    def test_install_without_arguments_runs_the_legacy_wizard(self, home, monkeypatch):
        called: list[bool] = []
        import trimum_core.install_fn as install_fn

        monkeypatch.setattr(install_fn, "install", lambda *a, **k: called.append(True))

        assert main(["install"]) == 0
        assert called == [True]

    def test_resolve_url_handles_paths_file_urls_and_http(self, tmp_path):
        index = tmp_path / "dist" / "index.json5"

        assert pkg_install.resolve_url(str(index), "demo.trmpkg") == str(tmp_path / "dist" / "demo.trmpkg")
        assert pkg_install.resolve_url("https://x.dev/p/index.json5", "demo.trmpkg") == "https://x.dev/p/demo.trmpkg"
        assert pkg_install.resolve_url(str(index), "https://y.dev/demo.trmpkg") == "https://y.dev/demo.trmpkg"