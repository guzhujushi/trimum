"""Agent 证书体系 — 官方/自签/无证 三档信任

信任层级：
  官方证书  → AgentRegistry 自动加载，忽略所有弹窗
  自签证书  → 同机可用，跨机不可用（基于机器指纹校验）
  无证      → 加载时弹出确认入口，用户确认后才注册

目录结构：
  ~/.trimum/certs/
  ├── official/      — 官方证书（随 trimum 发行版拷入即可）
  ├── trusted/       — 用户自签 / 用户信任的第三方证书
  └── pending/       — 等待用户确认的 Agent（临时，确认后移入 trusted/）

证书文件格式 (.cert.json)：
  {
    "agent_name": "planner-agent",
    "cert_type": "official" | "self_signed",
    "fingerprint": "sha256:abc123...",
    "issued_by": "trimum" | "user",
    "machine_id": "uuid-or-empty",
    "expires_at": "2027-01-01T00:00:00Z"
  }
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Optional

from .paths import trimum_path


class CertificateType(str, Enum):
    OFFICIAL = "official"
    SELF_SIGNED = "self_signed"
    NONE = "none"


class CertTrustLevel(str, Enum):
    TRUSTED = "trusted"
    CONFIRM = "confirm"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# 目录结构
# ---------------------------------------------------------------------------


def _certs_dir() -> Path:
    return trimum_path("certs")


def _agents_dir() -> Path:
    return trimum_path("agents")


def cert_dirs() -> dict[str, Path]:
    base = _certs_dir()
    return {
        "official": base / "official",
        "trusted": base / "trusted",
        "pending": base / "pending",
    }


def ensure_cert_dirs() -> None:
    for d in cert_dirs().values():
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 机器指纹（带缓存，同一进程内不变）
# ---------------------------------------------------------------------------

_MACHINE_ID_CACHE: str | None = None


def _get_machine_id() -> str:
    """获取本机唯一标识。结果会被缓存，同一进程内不变。"""
    global _MACHINE_ID_CACHE
    if _MACHINE_ID_CACHE is not None:
        return _MACHINE_ID_CACHE

    # Linux machine-id
    try:
        mid = Path("/etc/machine-id").read_text(encoding="utf-8").strip()
        if mid:
            _MACHINE_ID_CACHE = mid
            return mid
    except (OSError, FileNotFoundError):
        pass

    # Windows 卷序列号
    try:
        import subprocess
        result = subprocess.run(
            ["cmd", "/c", "vol", "C:"],
            capture_output=True, text=True, timeout=5,
        )
        stdout = result.stdout or ""
        for line in stdout.splitlines():
            if "Serial Number" in line or "序列号" in line:
                _MACHINE_ID_CACHE = line.split()[-1].strip()
                return _MACHINE_ID_CACHE
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        pass

    # 兜底：生成一次并缓存
    _MACHINE_ID_CACHE = f"fallback-{hashlib.sha256(b'trimum').hexdigest()[:8]}"
    return _MACHINE_ID_CACHE


def machine_id() -> str:
    """Public accessor for the cached machine fingerprint.

    Exposed so the identity module can bind a self-signed certificate to this
    machine without reaching into a private helper.
    """
    return _get_machine_id()


# ---------------------------------------------------------------------------
# 证书文件 IO
# ---------------------------------------------------------------------------


class AgentCert:
    def __init__(
        self,
        agent_name: str,
        cert_type: CertificateType = CertificateType.NONE,
        fingerprint: str = "",
        issued_by: str = "unknown",
        machine_id: str = "",
        expires_at: Optional[str] = None,
        capabilities: Optional[dict] = None,
    ) -> None:
        self.agent_name = agent_name
        if isinstance(cert_type, str):
            cert_type = CertificateType(cert_type)
        self.cert_type = cert_type
        self.fingerprint = fingerprint or ""
        self.issued_by = issued_by
        self.machine_id = machine_id or ""
        self.expires_at = expires_at
        #: 「这个身份可以动用哪些工具、风险上限多少」——只收紧内置策略，
        #: 具体判定在 ToolGateway / security_rule 层（接线见 STATUS.md 遗留项）。
        self.capabilities = dict(capabilities) if capabilities else {}

    @staticmethod
    def compute_fingerprint(path: str) -> str:
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return f"sha256:{h.hexdigest()}"
        except (OSError, FileNotFoundError):
            return ""

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "cert_type": self.cert_type.value,
            "fingerprint": self.fingerprint,
            "issued_by": self.issued_by,
            "machine_id": self.machine_id,
            "expires_at": self.expires_at or "",
            "capabilities": dict(self.capabilities),
        }

    @staticmethod
    def from_dict(data: dict) -> "AgentCert":
        return AgentCert(
            agent_name=data.get("agent_name", ""),
            cert_type=data.get("cert_type", CertificateType.NONE),
            fingerprint=data.get("fingerprint", ""),
            issued_by=data.get("issued_by", "unknown"),
            machine_id=data.get("machine_id", ""),
            expires_at=data.get("expires_at") or None,
            capabilities=data.get("capabilities") or {},
        )

    def save(self, directory: str | Path) -> None:
        p = Path(directory) / f"{self.agent_name}.cert.json"
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @staticmethod
    def load(name: str, directory: str | Path) -> Optional["AgentCert"]:
        p = Path(directory) / f"{name}.cert.json"
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return AgentCert.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def load_all(directory: str | Path) -> dict[str, "AgentCert"]:
        result: dict[str, AgentCert] = {}
        d = Path(directory)
        if not d.is_dir():
            return result
        for f in sorted(d.iterdir()):
            if f.suffix == ".json" and f.name.endswith(".cert.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    cert = AgentCert.from_dict(data)
                    result[cert.agent_name] = cert
                except (json.JSONDecodeError, OSError):
                    continue
        return result


# ---------------------------------------------------------------------------
# 证书验证
# ---------------------------------------------------------------------------


def verify_cert(agent_name: str, cert: Optional[AgentCert]) -> CertTrustLevel:
    """验证 Agent 的信任等级。

    策略：
    1. official → TRUSTED（跨机信任）
    2. self_signed + machine_id 匹配 → TRUSTED
    3. self_signed + machine_id 不匹配 → CONFIRM（允许用户决定）
    4. 无证 → CONFIRM
    """
    if cert is None:
        return CertTrustLevel.CONFIRM

    if cert.cert_type == CertificateType.OFFICIAL:
        return CertTrustLevel.TRUSTED

    if cert.cert_type == CertificateType.SELF_SIGNED:
        if cert.machine_id:
            return (
                CertTrustLevel.TRUSTED
                if cert.machine_id == _get_machine_id()
                else CertTrustLevel.CONFIRM
            )
        return CertTrustLevel.CONFIRM

    return CertTrustLevel.CONFIRM


# ---------------------------------------------------------------------------
# 官方 Agent（trimum 自己开发的 Agent 一律走官方证书）
# ---------------------------------------------------------------------------

#: 官方 Agent 的能力上限：``scope=official`` 表示「随 trimum 发行包分发」，
#: 它与用户自签证书（``scope=local``）互不覆盖：官方证书回答「这是我们自己的
#: Agent」，用户证书回答「这台机器上的这个人允许它干什么」。
OFFICIAL_SCOPE = "official"


def default_capabilities(*, scope: str = OFFICIAL_SCOPE) -> dict:
    """Return the default capability block written into a certificate."""
    return {
        "tools": ["*"],
        "max_risk": "inherit",
        "expires_at": None,
        "scope": scope,
    }


def bundled_agent_dirs() -> list[Path]:
    """Directories that ship trimum's own (official) agents.

    Source checkout (``<repo>/agents``) and the deployed tree
    (``/opt/trimum/agents``).  ``~/.trimum/agents`` is deliberately excluded:
    that is where *copied* — possibly third-party — agents live.
    """
    return [
        Path(__file__).resolve().parents[2] / "agents",
        Path("/opt/trimum/agents"),
    ]


def discover_bundled_agents(dirs: Optional[list[Path]] = None) -> list[str]:
    """Return the names of the official agents shipped with trimum."""
    names: list[str] = []
    for directory in dirs if dirs is not None else bundled_agent_dirs():
        base = Path(directory)
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            if any(
                (child / marker).is_file()
                for marker in ("agent.json", "manifest.json", "agent.yaml", "manifest.yaml")
            ):
                if child.name not in names:
                    names.append(child.name)
    return names


def issue_official_cert(
    agent_name: str,
    *,
    capabilities: Optional[dict] = None,
    directory: str | Path | None = None,
    force: bool = False,
) -> Optional["AgentCert"]:
    """Write an ``official`` certificate for a trimum-developed agent.

    Official agents need no user confirmation, so this is what turns a bundled
    agent into ``CertTrustLevel.TRUSTED``.  Returns the certificate, or ``None``
    when the certificate already exists and *force* is false.
    """
    target = Path(directory) if directory is not None else cert_dirs()["official"]
    target.mkdir(parents=True, exist_ok=True)
    if AgentCert.load(agent_name, target) is not None and not force:
        return None

    cert = AgentCert(
        agent_name=agent_name,
        cert_type=CertificateType.OFFICIAL,
        issued_by="trimum",
        machine_id="",
        capabilities=capabilities or default_capabilities(),
    )
    cert.save(target)
    return cert


def ensure_official_certs(
    *,
    dirs: Optional[list[Path]] = None,
    force: bool = False,
) -> dict:
    """Issue missing official certificates for every bundled agent.

    Read-only discovery plus idempotent issuance — safe to call from the
    first-run wizard on every start.
    """
    bundled = discover_bundled_agents(dirs)
    issued: list[str] = []
    existing: list[str] = []
    for name in bundled:
        if issue_official_cert(name, force=force) is None:
            existing.append(name)
        else:
            issued.append(name)
    return {"bundled": bundled, "issued": issued, "existing": existing}


# ---------------------------------------------------------------------------
# 创建自签证书
# ---------------------------------------------------------------------------


def create_self_signed_cert(agent_name: str, entry_path: str = "") -> AgentCert:
    fingerprint = AgentCert.compute_fingerprint(entry_path) if entry_path else ""
    machine_id = _get_machine_id()
    return AgentCert(
        agent_name=agent_name,
        cert_type=CertificateType.SELF_SIGNED,
        fingerprint=fingerprint,
        issued_by="user",
        machine_id=machine_id,
    )


# ---------------------------------------------------------------------------
# 用户确认入口（预留）
# ---------------------------------------------------------------------------


class ConfirmEntry:
    """用户确认 Agent 的入口接口 —— 预留实现。

    当前行为：返回 True（模拟确认通过）。
    Phase 6 接入桌面弹窗时替换。
    """

    @staticmethod
    def request_confirmation(agent_name: str, description: str = "") -> bool:
        import logging

        log = logging.getLogger("trimum_core.agent_cert")
        log.info(
            "cert.confirm_pending",
            agent=agent_name,
            description=description,
            note="ConfirmEntry stub — pending Phase 6 UI integration",
        )
        return True


# ---------------------------------------------------------------------------
# AgentRegistry 集成入口（#21 — 证书移入 Agent 文件夹）
# ---------------------------------------------------------------------------


def check_agent_trust(
    agent_name: str,
) -> tuple[CertTrustLevel, Optional[AgentCert]]:
    """检查 Agent 的信任等级。

    搜索顺序：
    1. ``~/.trimum/agents/<name>/cert.json`` — Agent 文件夹自带证书
    2. ``~/.trimum/certs/official/<name>.cert.json`` — 官方证书仓库
    3. ``~/.trimum/certs/trusted/<name>.cert.json`` — 旧信任证书（迁移兼容）
    4. 无证 → CONFIRM
    """
    ensure_cert_dirs()
    dirs = cert_dirs()

    # 优先：Agent 文件夹自带 cert.json
    agent_cert_path = _agents_dir() / agent_name / "cert.json"
    if agent_cert_path.is_file():
        try:
            data = json.loads(agent_cert_path.read_text(encoding="utf-8"))
            cert = AgentCert.from_dict(data)
            return verify_cert(agent_name, cert), cert
        except (json.JSONDecodeError, OSError):
            pass

    # 次优先：官方证书仓库
    cert = AgentCert.load(agent_name, dirs["official"])
    if cert:
        return verify_cert(agent_name, cert), cert

    # 旧 trusted 目录（迁移兼容）
    cert = AgentCert.load(agent_name, dirs["trusted"])
    if cert:
        return verify_cert(agent_name, cert), cert

    return CertTrustLevel.CONFIRM, None


def confirm_and_trust(agent_name: str, entry_path: str = "") -> bool:
    """用户确认后，将证书写入 Agent 文件夹（不是旧 certs/trusted）。

    #21 — cp 即走：复制 Agent 文件夹 = 代码+证书+记忆+经验完整打包。
    """
    if not ConfirmEntry.request_confirmation(agent_name):
        return False

    agent_memory_dir = _agents_dir() / agent_name / "memory"
    agent_memory_dir.mkdir(parents=True, exist_ok=True)

    cert = create_self_signed_cert(agent_name, entry_path)
    # 保存到 Agent 文件夹
    cert_path = _agents_dir() / agent_name / "cert.json"
    cert_path.write_text(json.dumps(cert.to_dict(), indent=2), encoding="utf-8")

    # 同时保留旧 trusted 目录的副本（旧代码迁移兼容）
    ensure_cert_dirs()
    cert.save(cert_dirs()["trusted"])
    return True


__all__ = [
    "CertificateType",
    "CertTrustLevel",
    "AgentCert",
    "verify_cert",
    "create_self_signed_cert",
    "machine_id",
    "OFFICIAL_SCOPE",
    "default_capabilities",
    "bundled_agent_dirs",
    "discover_bundled_agents",
    "issue_official_cert",
    "ensure_official_certs",
    "check_agent_trust",
    "confirm_and_trust",
    "ConfirmEntry",
    "ensure_cert_dirs",
    "cert_dirs",
]
