"""证书能力清单的运行期交集（E6 遗留，E5 第二片 4/4）。

两条纪律各测一遍：**只收紧**（never widen）与**交集**（每个来源都要过）。
再加两个网关层用例，证明 Layer 2.6 真的接在链路里。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import capability  # noqa: E402
from trimum_core.agent_cert import AgentCert, CertificateType  # noqa: E402
from trimum_core.models import Action, ExecuteRequest, ToolType  # noqa: E402
from trimum_core.tool_gateway import ToolGateway  # noqa: E402


@pytest.fixture
def home(monkeypatch, tmp_path):
    target = tmp_path / "home"
    target.mkdir()
    monkeypatch.setenv("TRIMUM_HOME", str(target))
    return target


def write_agent_cert(home: Path, name: str, capabilities: dict, kind: CertificateType = CertificateType.OFFICIAL) -> None:
    directory = home / "agents" / name
    directory.mkdir(parents=True, exist_ok=True)
    cert = AgentCert(agent_name=name, cert_type=kind, issued_by="trimum", capabilities=capabilities)
    (directory / "cert.json").write_text(
        json.dumps(cert.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


class TestEvaluation:
    def test_an_empty_block_says_nothing(self):
        assert capability.evaluate({}) is None
        assert capability.evaluate(None) is None

    def test_the_wildcard_restricts_nothing(self):
        assert capability.evaluate({"tools": ["*"]}, tool="git.push") is None

    def test_a_tool_outside_the_whitelist_is_denied(self):
        verdict = capability.evaluate({"tools": ["shell"]}, tool="git.push")

        assert verdict is not None
        assert verdict.action == capability.DENY
        assert "git.push" in verdict.reason

    def test_a_family_entry_covers_its_subtools(self):
        assert capability.evaluate({"tools": ["file"]}, tool="file.read") is None
        assert capability.evaluate({"tools": ["file.read"]}, tool="file.write") is not None

    def test_risk_above_the_ceiling_needs_confirmation(self):
        caps = {"tools": ["*"], "max_risk": "low"}

        assert capability.evaluate(caps, risk="low") is None
        verdict = capability.evaluate(caps, risk="medium")
        assert verdict is not None
        assert verdict.action == capability.CONFIRM
        assert "max_risk=low" in verdict.reason

    def test_inherit_means_no_extra_ceiling(self):
        assert capability.evaluate({"tools": ["*"], "max_risk": "inherit"}, risk="high") is None

    def test_an_expired_certificate_is_denied(self):
        caps = {"tools": ["*"], "expires_at": "2020-01-01T00:00:00Z"}

        verdict = capability.evaluate(caps)

        assert verdict is not None
        assert verdict.action == capability.DENY
        assert "已过期" in verdict.reason

    def test_a_future_expiry_is_fine(self):
        assert capability.evaluate({"tools": ["*"], "expires_at": "2999-01-01T00:00:00Z"}) is None

    def test_untrusted_scope_always_needs_confirmation(self):
        verdict = capability.evaluate({"tools": ["*"], "scope": capability.UNTRUSTED})

        assert verdict is not None
        assert verdict.action == capability.CONFIRM
        assert "不可信" in verdict.reason

    def test_a_broken_block_needs_confirmation_instead_of_silence(self):
        verdict = capability.evaluate({"tools": ["*"], "max_risk": "extreme"})

        assert verdict is not None
        assert verdict.action == capability.CONFIRM
        assert "非法" in verdict.reason

    def test_a_lone_string_tool_is_normalised(self):
        caps, problems = capability.normalise({"tools": "shell"})

        assert problems == []
        assert caps["tools"] == ["shell"]


class TestIntersection:
    def test_no_certificate_and_no_identity_means_no_tightening(self, home):
        assert capability.tighten("nobody") is None

    def test_the_agent_certificate_denies_a_foreign_tool(self, home):
        write_agent_cert(home, "agent-x", {"tools": ["shell"], "max_risk": "inherit"})

        assert capability.tighten("agent-x", tool="shell") is None
        verdict = capability.tighten("agent-x", tool="git.push")
        assert verdict is not None
        assert verdict.action == capability.DENY
        assert verdict.source == "agent-cert:agent-x"

    def test_the_strictest_source_wins(self, home):
        """agent 证书允许、身份证书收紧 —— 交集取严的那条。"""
        write_agent_cert(home, "agent-x", {"tools": ["*"], "max_risk": "inherit"})
        from trimum_core import identity

        identity.generate_identity(user="tester", max_risk="low", force=True)

        assert capability.tighten("agent-x", risk="high") is not None
        assert capability.tighten("agent-x", risk="low") is None

    def test_an_untrusted_install_forces_confirmation(self, home):
        """降级安装的包按名字命中：登记表就是运行期的第二个来源。"""
        from trimum_core import pkg_install

        ledger = {"format": pkg_install.INSTALL_FORMAT, "packages": {
            "demo-tool": {"name": "demo-tool", "type": "tool", "trust": pkg_install.TRUST_UNTRUSTED}
        }}
        pkg_install.save_ledger(ledger)

        verdict = capability.tighten("someone", tool_name="demo-tool")

        assert verdict is not None
        assert verdict.action == capability.CONFIRM
        assert verdict.source == "installed-package:demo-tool"

    def test_an_untrusted_agent_certificate_forces_confirmation(self, home):
        write_agent_cert(
            home,
            "outside",
            {"tools": ["*"], "max_risk": "inherit", "scope": capability.UNTRUSTED},
            kind=CertificateType.NONE,
        )

        verdict = capability.tighten("outside")

        assert verdict is not None
        assert verdict.action == capability.CONFIRM


class TestGatewayLayer26:
    def _request(self, tool: ToolType = ToolType.SHELL, args: list[str] | None = None) -> ExecuteRequest:
        return ExecuteRequest(
            tool=tool,
            args=args or ["echo", "cap"],
            agent_id="agent-x",
            skip_cwd_check=True,
        )

    def _audit_types(self, gateway: ToolGateway) -> list[str]:
        return [event.event_type for event in gateway._audit_log]

    @pytest.mark.asyncio
    async def test_a_denied_tool_never_runs_and_is_audited(self, home):
        write_agent_cert(home, "agent-x", {"tools": ["shell"], "max_risk": "inherit"})
        gw = ToolGateway(layer4=False)

        resp = await gw.execute(self._request(ToolType.GIT_PUSH, ["git", "push"]))

        assert resp.status == "denied"
        assert resp.action == Action.DENY
        assert "Capability denied" in resp.error
        assert "capability_denied" in self._audit_types(gw)

    @pytest.mark.asyncio
    async def test_a_risk_ceiling_upgrades_to_confirm(self, home):
        """``touch tmp/x`` 策略风险是 medium（Action 也是 confirm），证书上限 low 更严。"""
        write_agent_cert(home, "agent-x", {"tools": ["shell"], "max_risk": "low"})
        gw = ToolGateway(layer4=False)

        resp = await gw.execute(self._request(ToolType.SHELL, ["tar", "-xzf", "nope.tgz"]))

        assert resp.action == Action.CONFIRM
        assert "capabilities:" in (resp.reason or "")
        assert "max_risk=low" in (resp.reason or "")

    @pytest.mark.asyncio
    async def test_an_untrusted_agent_needs_a_nod_for_every_command(self, home):
        """降级安装的 agent：连 ``echo`` 都要人点头（来源从没被背书过）。"""
        write_agent_cert(
            home,
            "agent-x",
            {"tools": ["*"], "max_risk": "inherit", "scope": capability.UNTRUSTED},
            kind=CertificateType.NONE,
        )
        gw = ToolGateway(layer4=False, interactive=True)
        asked: list[str] = []

        async def _deny(cmd_str, risk, reason, caller) -> bool:
            asked.append(reason)
            return False

        gw._prompt_confirm = _deny
        resp = await gw.execute(self._request(ToolType.SHELL, ["echo", "cap"]))

        assert resp.status == "denied"
        assert asked and "capabilities:" in asked[0] and "不可信" in asked[0]
        assert "user_cancelled" in self._audit_types(gw)

    @pytest.mark.asyncio
    async def test_without_any_declaration_nothing_changes(self, home):
        gw = ToolGateway(layer4=False)

        resp = await gw.execute(self._request())

        assert resp.status in ("allowed", "success")
        assert resp.action == Action.AUTO
        assert "capability_denied" not in self._audit_types(gw)