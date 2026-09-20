"""Tests for agent_cert.py — 证书体系。"""

import json
import os
import tempfile
from pathlib import Path

import pytest

import trimum_core.agent_cert as ac  # noqa: E402
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
    """check_agent_trust 集成测试。

    #21 — 查找顺序：
    1. ``agents/<name>/cert.json``（Agent 文件夹优先）
    2. ``certs/official/<name>.cert.json``
    3. ``certs/trusted/<name>.cert.json``（迁移兼容）
    4. 无证 → CONFIRM
    """

    @pytest.fixture
    def monkey_ac(self, monkeypatch):
        """临时替换 _agents_dir 和 cert_dirs 到 tempdir。"""
        import trimum_core.agent_cert as ac
        tmp = Path(tempfile.mkdtemp())
        agents_dir = tmp / "agents"
        agents_dir.mkdir()
        monkeypatch.setattr(ac, "_agents_dir", lambda: agents_dir)
        certs_base = tmp / "certs"
        monkeypatch.setattr(ac, "cert_dirs", lambda: {
            "official": certs_base / "official",
            "trusted": certs_base / "trusted",
            "pending": certs_base / "pending",
        })
        ensure_cert_dirs()
        return tmp, agents_dir, certs_base

    def test_agent_folder_cert_priority(self, monkey_ac):
        """Agent 文件夹的 cert.json 优先于 certs/official。"""
        tmp, agents_dir, certs_base = monkey_ac
        import trimum_core.agent_cert as ac

        # 在 official 放一个官方证书
        cert_official = AgentCert("agent-x", CertificateType.OFFICIAL, issued_by="trimum")
        cert_official.save(certs_base / "official")

        # 在 Agent 文件夹放一个自签证书（应该优先）
        agent_dir = agents_dir / "agent-x"
        agent_dir.mkdir(parents=True)
        cert_self = create_self_signed_cert("agent-x")
        (agent_dir / "cert.json").write_text(json.dumps(cert_self.to_dict()), encoding="utf-8")

        level, loaded = check_agent_trust("agent-x")
        assert level == CertTrustLevel.TRUSTED
        assert loaded is not None
        assert loaded.cert_type == CertificateType.SELF_SIGNED  # Agent 文件夹的生效

    def test_official_dir(self, monkey_ac):
        """official 证书仍作为第二优先级。"""
        tmp, agents_dir, certs_base = monkey_ac

        cert = AgentCert("official-agent", CertificateType.OFFICIAL, issued_by="trimum")
        cert.save(certs_base / "official")
        level, loaded = check_agent_trust("official-agent")
        assert level == CertTrustLevel.TRUSTED
        assert loaded is not None

    def test_trusted_dir_fallback(self, monkey_ac):
        """old trusted 作为第三优先级（迁移兼容）。"""
        tmp, agents_dir, certs_base = monkey_ac

        cert = create_self_signed_cert("legacy-agent")
        cert.save(certs_base / "trusted")
        level, loaded = check_agent_trust("legacy-agent")
        assert level == CertTrustLevel.TRUSTED
        assert loaded is not None

    def test_no_cert(self, monkey_ac):
        """无证 → CONFIRM。"""
        tmp, agents_dir, certs_base = monkey_ac

        level, loaded = check_agent_trust("unknown-agent")
        assert level == CertTrustLevel.CONFIRM
        assert loaded is None


class TestConfirmAndTrust:
    """用户确认流程（#21 — 证书写入 Agent 文件夹）。"""

    def test_confirm_creates_agent_folder_cert(self):
        """confirm_and_trust 现在写入 agents/<name>/cert.json（同时保留旧 trusted 兼容）。"""
        with tempfile.TemporaryDirectory() as tmp:
            import trimum_core.agent_cert as ac
            import trimum_core.agent_cert as ac_mod

            orig_cert = ac.cert_dirs
            orig_agents = ac._agents_dir

            base = Path(tmp)
            agents_dir = base / "agents"
            agents_dir.mkdir()

            ac._agents_dir = lambda: agents_dir
            ac.cert_dirs = lambda: {
                "official": base / "certs" / "official",
                "trusted": base / "certs" / "trusted",
                "pending": base / "certs" / "pending",
            }
            ensure_cert_dirs()

            result = confirm_and_trust("new-agent")
            assert result is True

            # 1. Agent 文件夹 cert.json 必须存在
            agent_cert_path = agents_dir / "new-agent" / "cert.json"
            assert agent_cert_path.is_file(), "Agent cert.json not created"
            data = json.loads(agent_cert_path.read_text(encoding="utf-8"))
            assert data["agent_name"] == "new-agent"
            assert data["cert_type"] == "self_signed"

            # 2. 旧 trusted 兼容副本也应存在
            assert (base / "certs" / "trusted" / "new-agent.cert.json").is_file()

            ac._agents_dir = orig_agents
            ac.cert_dirs = orig_cert


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

class TestCapabilities:
    """证书携带「可以动用哪些工具」——只收紧内置策略。"""

    def test_capabilities_round_trip(self, tmp_path):
        cert = AgentCert(
            "a1",
            CertificateType.OFFICIAL,
            issued_by="trimum",
            capabilities={"tools": ["shell"], "max_risk": "low"},
        )
        AgentCert("a1", CertificateType.OFFICIAL, issued_by="trimum").save(tmp_path)
        cert.save(tmp_path)
        loaded = AgentCert.load("a1", tmp_path)
        assert loaded.capabilities == {"tools": ["shell"], "max_risk": "low"}

    def test_missing_capabilities_default_to_empty(self, tmp_path):
        cert = AgentCert("a2", CertificateType.SELF_SIGNED)
        cert.save(tmp_path)
        assert AgentCert.load("a2", tmp_path).capabilities == {}

    def test_default_capabilities_scope(self):
        assert ac.default_capabilities()["scope"] == ac.OFFICIAL_SCOPE
        assert ac.default_capabilities(scope="local")["scope"] == "local"

    def test_legacy_cert_without_capabilities_is_accepted(self, tmp_path):
        (tmp_path / "old.cert.json").write_text(
            json.dumps(
                {
                    "agent_name": "old",
                    "cert_type": "official",
                    "fingerprint": "",
                    "issued_by": "trimum",
                    "machine_id": "",
                    "expires_at": "",
                }
            ),
            encoding="utf-8",
        )
        loaded = AgentCert.load("old", tmp_path)
        assert loaded.cert_type == CertificateType.OFFICIAL
        assert loaded.capabilities == {}


class TestOfficialAgents:
    """trimum 自己开发的 Agent 一律是官方 Agent，免用户确认。"""

    @pytest.fixture()
    def bundled(self, tmp_path):
        base = tmp_path / "agents"
        for name, marker in (("maintenance", "agent.json"), ("fs-helper", "agent.yaml")):
            (base / name).mkdir(parents=True)
            (base / name / marker).write_text("{}", encoding="utf-8")
        (base / "not-an-agent").mkdir()  # 没有清单文件 → 不算 Agent
        (base / "loose.txt").write_text("x", encoding="utf-8")
        return base

    def test_discovery_requires_a_manifest(self, bundled):
        assert ac.discover_bundled_agents([bundled]) == ["fs-helper", "maintenance"]

    def test_discovery_ignores_missing_dirs(self, tmp_path):
        assert ac.discover_bundled_agents([tmp_path / "nope"]) == []

    def test_issue_official_cert_writes_official(self, tmp_path):
        cert = ac.issue_official_cert("maintenance", directory=tmp_path, force=True)
        assert cert.cert_type == CertificateType.OFFICIAL
        assert cert.issued_by == "trimum"
        stored = AgentCert.load("maintenance", tmp_path)
        assert stored.capabilities["scope"] == ac.OFFICIAL_SCOPE
        assert verify_cert("maintenance", stored) == CertTrustLevel.TRUSTED

    def test_issue_is_idempotent_unless_forced(self, tmp_path):
        assert ac.issue_official_cert("x", directory=tmp_path) is not None
        assert ac.issue_official_cert("x", directory=tmp_path) is None
        assert ac.issue_official_cert("x", directory=tmp_path, force=True) is not None

    def test_ensure_official_certs_reports_issued_and_existing(
        self, bundled, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(ac, "cert_dirs", lambda: {"official": tmp_path, "trusted": tmp_path, "pending": tmp_path})
        first = ac.ensure_official_certs(dirs=[bundled])
        assert first["bundled"] == ["fs-helper", "maintenance"]
        assert first["issued"] == ["fs-helper", "maintenance"]
        assert first["existing"] == []

        second = ac.ensure_official_certs(dirs=[bundled])
        assert second["issued"] == []
        assert second["existing"] == ["fs-helper", "maintenance"]

    def test_user_self_signed_cert_is_not_overwritten(self, bundled, tmp_path, monkeypatch):
        monkeypatch.setattr(ac, "cert_dirs", lambda: {"official": tmp_path, "trusted": tmp_path, "pending": tmp_path})
        ac.issue_official_cert("maintenance", directory=tmp_path)
        ac.ensure_official_certs(dirs=[bundled])
        stored = AgentCert.load("maintenance", tmp_path)
        assert stored.cert_type == CertificateType.OFFICIAL
