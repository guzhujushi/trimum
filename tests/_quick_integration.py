"""Quick integration smoke test for certificate + source_type + policy."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import trimum_core.agent_cert as ac
from trimum_core.agent_cert import (
    CertificateType, AgentCert, ensure_cert_dirs, check_agent_trust,
)
from trimum_core.models import AgentManifest, AgentPermissions, AgentEvents, SourceType
from trimum_core.agent_registry import AgentRegistry
from trimum_core.policy_engine import PolicyEngine

passes = 0
fails = 0

def check(name, ok):
    global passes, fails
    if ok:
        passes += 1
        print(f"  [PASS] {name}")
    else:
        fails += 1
        print(f"  [FAIL] {name}")

# === 1. Certificate + AgentRegistry ===
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    orig_fn = ac.cert_dirs
    ac.cert_dirs = lambda: {
        "official": base / "official",
        "trusted": base / "trusted",
        "pending": base / "pending",
    }
    ensure_cert_dirs()

    # Official cert agent
    AgentCert("planner-agent", CertificateType.OFFICIAL, issued_by="trimum").save(base / "official")
    reg = AgentRegistry()
    m1 = AgentManifest(
        name="planner-agent", version="1.0.0",
        capabilities=["planner.decompose"],
        permissions=AgentPermissions(), events=AgentEvents(),
        entry="trimum_core.planner_agent:PlannerAgent",
    )
    reg.register(m1)
    check("official cert agent registered", reg.get_agent("planner-agent") is not None)

    # No-cert agent (confirm stub returns True)
    m2 = AgentManifest(
        name="user-agent", version="1.0",
        capabilities=["custom.do"],
        permissions=AgentPermissions(), events=AgentEvents(),
        entry="user_agent:main",
    )
    reg.register(m2)
    cert = AgentCert.load("user-agent", base / "trusted")
    check("no-cert agent creates self-signed after confirm", cert is not None)
    if cert:
        check("self-signed cert type", cert.cert_type == CertificateType.SELF_SIGNED)

    ac.cert_dirs = orig_fn

# === 2. PolicyEngine source_type ===
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "policy.yaml"
    p.write_text(
        "rules:\n"
        '  - pattern: "rm"\n'
        "    risk: critical\n"
        "    action: deny\n"
        '  - pattern: ".*"\n'
        "    risk: low\n"
        "    action: auto\n"
        "    source: ai\n",
        encoding="utf-8",
    )
    pe = PolicyEngine(policy_path=p)

    r1 = pe.evaluate("rm -rf /tmp", source_type=SourceType.AI)
    check("AI rm -> deny", r1[1].value == "deny")

    r2 = pe.evaluate("ls -la", source_type=SourceType.AI)
    check("AI ls -> auto", r2[1].value == "auto")

    r3 = pe.evaluate("ls -la", source_type=SourceType.HUMAN)
    check("HUMAN ls -> default confirm (no source:human rule)", r3[1].value == "confirm")

print(f"\n=== {passes} pass, {fails} fail ===")
sys.exit(0 if fails == 0 else 1)
