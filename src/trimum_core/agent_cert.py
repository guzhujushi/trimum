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
    return Path.home() / ".trimum" / "certs"


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
        for line in result.stdout.splitlines():
            if "Serial Number" in line or "序列号" in line:
                _MACHINE_ID_CACHE = line.split()[-1].strip()
                return _MACHINE_ID_CACHE
    except (OSError, subprocess.SubprocessError):
        pass

    # 兜底：生成一次并缓存
    _MACHINE_ID_CACHE = f"fallback-{hashlib.sha256(b'trimum').hexdigest()[:8]}"
    return _MACHINE_ID_CACHE


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
    ) -> None:
        self.agent_name = agent_name
        if isinstance(cert_type, str):
            cert_type = CertificateType(cert_type)
        self.cert_type = cert_type
        self.fingerprint = fingerprint or ""
        self.issued_by = issued_by
        self.machine_id = machine_id or ""
        self.expires_at = expires_at

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
# AgentRegistry 集成入口
# ---------------------------------------------------------------------------


def check_agent_trust(
    agent_name: str,
) -> tuple[CertTrustLevel, Optional[AgentCert]]:
    ensure_cert_dirs()

    dirs = cert_dirs()

    cert = AgentCert.load(agent_name, dirs["official"])
    if cert:
        return verify_cert(agent_name, cert), cert

    cert = AgentCert.load(agent_name, dirs["trusted"])
    if cert:
        return verify_cert(agent_name, cert), cert

    return CertTrustLevel.CONFIRM, None


def confirm_and_trust(agent_name: str, entry_path: str = "") -> bool:
    if not ConfirmEntry.request_confirmation(agent_name):
        return False

    ensure_cert_dirs()
    cert = create_self_signed_cert(agent_name, entry_path)
    cert.save(cert_dirs()["trusted"])
    return True


__all__ = [
    "CertificateType",
    "CertTrustLevel",
    "AgentCert",
    "verify_cert",
    "create_self_signed_cert",
    "check_agent_trust",
    "confirm_and_trust",
    "ConfirmEntry",
    "ensure_cert_dirs",
    "cert_dirs",
]
