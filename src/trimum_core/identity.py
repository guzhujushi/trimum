"""Per-user identity — keystore plus a self-signed identity certificate.

The certificate model has three layers (``docs/ECOSYSTEM-STRATEGY.md`` §7.1):

* **provenance** — the official root key says *who published* a package (E5);
* **identity** — this module: a per-user Ed25519 key pair and the self-signed
  document that binds it to one user on one machine;
* **capability** — the ``capabilities`` block inside that document: which tools
  the identity may use, up to which risk level, until when.

A self-signed identity is bound to ``machine_id`` + user, so copying it to
another machine or another user does **not** transfer any authority: the other
side has to sign again with its own key.  Capabilities may only *tighten* the
built-in policy, never widen it — enforcement itself lives in the ToolGateway
and the policy layer, not here.

``cryptography`` is an optional dependency: without it the wizard reports the
identity step as ``skipped`` instead of writing a half-broken keystore, so a
bare install (no third-party packages at all) still completes.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .paths import trimum_path

SCHEMA = "trimum.identity/v1"
DOC_FILE = "identity.json"
KEY_FILE = "identity-ed25519.key"
PUB_FILE = "identity-ed25519.pub"

#: ``inherit`` means "add no restriction of its own" — the identity document is
#: then purely an anchor, and the built-in policy decides everything.
MAX_RISK_VALUES = ("inherit", "low", "medium", "high")


def identity_dir() -> Path:
    """Return the per-user identity directory (``~/.trimum/identity``)."""
    return trimum_path("identity")


def doc_path() -> Path:
    return identity_dir() / DOC_FILE


def key_path() -> Path:
    return identity_dir() / KEY_FILE


def pub_path() -> Path:
    return identity_dir() / PUB_FILE


def user_name() -> str:
    """Best-effort current user name (never raises)."""
    for variable in ("TRIMUM_USER", "USER", "USERNAME", "LOGNAME"):
        value = os.environ.get(variable)
        if value and value.strip():
            return value.strip()
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - platform specific
        return "unknown"


def machine_id() -> str:
    """Machine fingerprint, reusing the certificate module's implementation."""
    from .agent_cert import machine_id as cert_machine_id

    return cert_machine_id()


def crypto_available() -> bool:
    """Return True when Ed25519 support (``cryptography``) is importable."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
    except Exception:
        return False
    return True


def load_identity() -> dict | None:
    """Return the stored identity document, or None when absent/invalid."""
    path = doc_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_bound_to_machine(doc: dict | None) -> bool:
    """True when *doc* was issued for this machine."""
    if not doc:
        return False
    stored = str(doc.get("machine_id") or "")
    return bool(stored) and stored == machine_id()


def status() -> dict:
    """Report the identity state without modifying anything."""
    doc = load_identity()
    return {
        "exists": doc is not None,
        "path": str(doc_path()),
        "key_file": key_path().is_file(),
        "crypto": crypto_available(),
        "bound_to_machine": is_bound_to_machine(doc),
        "doc": doc,
    }


def _normalise_capabilities(
    *, max_risk: str, tools: list[str] | None
) -> dict:
    risk = (max_risk or "inherit").strip().lower()
    if risk not in MAX_RISK_VALUES:
        raise ValueError(
            f"max_risk must be one of {', '.join(MAX_RISK_VALUES)} (got {max_risk!r})"
        )
    return {
        "tools": list(tools) if tools else ["*"],
        "max_risk": risk,
        "expires_at": None,
        "scope": "local",
    }


def generate_identity(
    *,
    user: str = "",
    max_risk: str = "inherit",
    tools: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Create (or replace) the user's key pair and self-signed identity.

    Returns a result dict with ``status`` one of ``created`` / ``existing`` /
    ``replaced`` / ``skipped`` / ``dry-run``.  Nothing is written when the
    crypto backend is missing or when *dry_run* is set.
    """
    capabilities = _normalise_capabilities(max_risk=max_risk, tools=tools)
    existing = load_identity()

    if existing is not None and not force:
        return {
            "status": "existing",
            "path": str(doc_path()),
            "bound_to_machine": is_bound_to_machine(existing),
            "doc": existing,
        }

    if not crypto_available():
        return {
            "status": "skipped",
            "reason": "cryptography is not installed",
            "hint": "pip install cryptography  # then re-run trm setup",
            "doc": None,
        }

    if dry_run:
        return {
            "status": "dry-run",
            "path": str(doc_path()),
            "would_write": [str(KEY_FILE), str(PUB_FILE), str(DOC_FILE)],
            "capabilities": capabilities,
        }

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private_key = ed25519.Ed25519PrivateKey.generate()
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    raw_pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    directory = identity_dir()
    directory.mkdir(parents=True, exist_ok=True)
    key_path().write_bytes(key_pem)
    pub_path().write_bytes(pub_pem)
    try:  # POSIX: keep the private key readable by its owner only
        os.chmod(key_path(), 0o600)
    except OSError:  # pragma: no cover - Windows / restricted filesystems
        pass

    doc = {
        "schema": SCHEMA,
        "user": user or user_name(),
        "machine_id": machine_id(),
        "issued_by": "self",
        "key_type": "ed25519",
        "public_key_fingerprint": "sha256:" + hashlib.sha256(raw_pub).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "capabilities": capabilities,
        "notes": (
            "self-signed identity: valid for this user on this machine only. "
            "Another user or machine must sign again with its own key. "
            "Capabilities can only tighten the built-in policy."
        ),
    }
    doc_path().write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    return {
        "status": "replaced" if existing is not None else "created",
        "path": str(doc_path()),
        "bound_to_machine": True,
        "doc": doc,
    }


__all__ = [
    "SCHEMA",
    "MAX_RISK_VALUES",
    "identity_dir",
    "doc_path",
    "key_path",
    "pub_path",
    "user_name",
    "machine_id",
    "crypto_available",
    "load_identity",
    "is_bound_to_machine",
    "status",
    "generate_identity",
]