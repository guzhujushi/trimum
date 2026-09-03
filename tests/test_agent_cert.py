"""Tests for agent_cert.py — 证书体系。"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from trimum_core.agent_cert import (
    AgentCert,
    CertificateType,
    CertTrustLevel,
    check_agent_trust,
    confirm_and_trust,
    create_self_signed_cert,
    ensure_cert_dirs,
    verify_cert,
)


class TestAgentCert:
    """AgentCert 创建、序列化、保存、加载。"""

    def test_create_official(self):
        cert = AgentCert("planner", CertificateType.OFFICIAL, issued_by="trimum")
        assert cert.agent_name == "planner"
        assert cert.cert_type == CertificateType.OFFICIAL
        assert cert.issued_by == "trimum"

    def test_create_self_signed(self):
        cert = create_self_signed_cert("my-agent")
        assert cert.agent_name == "my-agent"
        assert cert.cert_type == CertificateType.SELF_SIGNED
        assert cert.issued_by == "user"
        assert cert.machine_id  # 应该绑定了本机

    def test_to_dict_from_dict_roundtrip(self):
        cert = AgentCert("test", CertificateType.OFFICIAL, "sha256:abc", "trimum", "m1")
        d = cert.to_dict()
        restored = AgentCert.from_dict(d)
        assert restored.agent_name == "test"
        assert restored.cert_type == CertificateType.OFFICIAL
        assert restored.fingerprint == "sha256:abc"

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert = AgentCert("demo", CertificateType.OFFICIAL, issued_by="trimum", machine_id="m1")
            cert.save(tmp)
            # 文件存在
            p = Path(tmp) / "demo.cert.json"
            assert p.is_file()
            # 加载回来
            loaded = AgentCert.load("demo", tmp)
            assert loaded is not None
            assert loaded.agent_name == "demo"
            assert loaded.cert_type == CertificateType.OFFICIAL

    def test_load_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            AgentCert("a1", CertificateType.OFFICIAL).save(tmp)
            AgentCert("a2", CertificateType.SELF_SIGNED).save(tmp)
            results = AgentCert.load_all(tmp)
            assert len(results) == 2
            assert "a1" in results
            assert "a2" in results

    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert = AgentCert.load("ghost", tmp)
            assert cert is None


class TestVerifyCert:
    """证书验证逻辑。"""

    def test_no_cert(self):
        level = verify_cert("any", None)
        assert level == CertTrustLevel.CONFIRM

    def test_official_trusted(self):
        cert = AgentCert("x", CertificateType.OFFICIAL)
        level = verify_cert("x", cert)
        assert level == CertTrustLevel.TRUSTED

    def test_self_signed_same_machine(self):
        cert = create_self_signed_cert("local-agent")
        level = verify_cert("local-agent", cert)
        assert level == CertTrustLevel.TRUSTED

    def test_self_signed_diff_machine(self):
        cert = AgentCert("remote", CertificateType.SELF_SIGNED, machine_id="other-machine-123")
        level = verify_cert("remote", cert)
        assert level == CertTrustLevel.CONFIRM  # 跨机→允许用户确认


class TestCheckAgentTrust:
    """check_agent_trust 集成测试。"""

    def test_official_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            import trimum_core.agent_cert as ac
            # 临时替换 cert_dirs
            orig = ac.cert_dirs
            base = Path(tmp)
            ac.cert_dirs = lambda: {
                "official": base / "official",
                "trusted": base / "trusted",
                "pending": base / "pending",
            }
            ensure_cert_dirs()
            # 放一个官方证书
            cert = AgentCert("official-agent", CertificateType.OFFICIAL, issued_by="trimum")
            cert.save(base / "official")
            level, loaded = check_agent_trust("official-agent")
            assert level == CertTrustLevel.TRUSTED
            assert loaded is not None
            ac.cert_dirs = orig  # 恢复

    def test_trusted_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            import trimum_core.agent_cert as ac
            orig = ac.cert_dirs
            base = Path(tmp)
            ac.cert_dirs = lambda: {
                "official": base / "official",
                "trusted": base / "trusted",
                "pending": base / "pending",
            }
            ensure_cert_dirs()
            cert = create_self_signed_cert("trusted-agent")
            cert.save(base / "trusted")
            level, loaded = check_agent_trust("trusted-agent")
            assert level == CertTrustLevel.TRUSTED
            assert loaded is not None
            ac.cert_dirs = orig

    def test_no_cert(self):
        with tempfile.TemporaryDirectory() as tmp:
            import trimum_core.agent_cert as ac
            orig = ac.cert_dirs
            base = Path(tmp)
            ac.cert_dirs = lambda: {
                "official": base / "official",
                "trusted": base / "trusted",
                "pending": base / "pending",
            }
            ensure_cert_dirs()
            level, loaded = check_agent_trust("unknown-agent")
            assert level == CertTrustLevel.CONFIRM
            assert loaded is None
            ac.cert_dirs = orig


class TestConfirmAndTrust:
    """用户确认流程。"""

    def test_confirm_creates_cert(self):
        with tempfile.TemporaryDirectory() as tmp:
            import trimum_core.agent_cert as ac
            orig = ac.cert_dirs
            base = Path(tmp)
            ac.cert_dirs = lambda: {
                "official": base / "official",
                "trusted": base / "trusted",
                "pending": base / "pending",
            }
            ensure_cert_dirs()
            result = confirm_and_trust("new-agent")
            assert result is True  # 当前 stub 返回 True
            # 检查证书是否被创建
            assert (base / "trusted" / "new-agent.cert.json").is_file()
            ac.cert_dirs = orig


class TestCertDirs:
    """证书目录结构。"""

    def test_ensure_cert_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            import trimum_core.agent_cert as ac
            orig = ac.cert_dirs
            base = Path(tmp)
            ac.cert_dirs = lambda: {
                "official": base / "official",
                "trusted": base / "trusted",
                "pending": base / "pending",
            }
            ensure_cert_dirs()
            assert (base / "official").is_dir()
            assert (base / "trusted").is_dir()
            assert (base / "pending").is_dir()
            ac.cert_dirs = orig
