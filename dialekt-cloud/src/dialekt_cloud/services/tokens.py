"""HMAC-SHA256 bearer tokens for dialekt-cloud."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone


def _utcnow() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def generate_license_key() -> str:
    return "dialekt_" + secrets.token_hex(32)


def generate_invite_token() -> str:
    return "inv_" + secrets.token_urlsafe(24)


def _sign(payload_b64: str, secret: str) -> str:
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def create_bearer_token(
    *,
    user_id: str,
    tenant_id: str,
    role: str,
    license_key: str,
    secret: str,
    ttl_seconds: int = 86400,
) -> str:
    now = _utcnow()
    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = _sign(payload_b64 + license_key, secret)
    return f"{payload_b64}.{sig}"


def verify_bearer_token(token: str, *, license_key: str, secret: str) -> dict | None:
    """Returns decoded payload dict or None if invalid/expired."""
    try:
        payload_b64, sig = token.rsplit(".", 1)
    except ValueError:
        return None

    expected_sig = _sign(payload_b64 + license_key, secret)
    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        padding = 4 - len(payload_b64) % 4
        payload_json = base64.urlsafe_b64decode(payload_b64 + "=" * padding)
        payload = json.loads(payload_json)
    except Exception:
        return None

    if payload.get("exp", 0) < _utcnow():
        return None

    return payload


def create_admin_session_token(
    *,
    admin_id: str,
    email: str,
    secret: str,
    ttl: int = 4 * 3600,
) -> str:
    """Short-lived session token for founder admin panel.

    Multi-admin ready (v1.1): admin_id + email baked into the payload so
    every authenticated endpoint can resolve the acting admin from the
    cookie alone — no more `SELECT id FROM admins LIMIT 1` footguns.

    Signing material is `secret + "_admin_session"` (a domain-separating
    derivation) — DIALEKT_ADMIN_KEY is no longer used here, per mentor P2.
    The break-glass key authenticates separately via the X-Admin-Key
    header path; it never participates in cookie minting or signing.
    """
    now = _utcnow()
    payload = {
        "admin_id": admin_id,
        "email": email,
        "role": "founder_admin",
        "iat": now,
        "exp": now + ttl,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = _sign(payload_b64, secret + "_admin_session")
    return f"{payload_b64}.{sig}"


def verify_admin_session_token(token: str, secret: str) -> dict | None:
    """Returns the payload dict if valid + unexpired, else None.

    Caller MUST treat None as authentication failure. The returned dict
    contains: admin_id, email, role, iat, exp.
    """
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = _sign(payload_b64, secret + "_admin_session")
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padding = 4 - len(payload_b64) % 4
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * padding))
    except Exception:
        return None
    if payload.get("exp", 0) < _utcnow():
        return None
    if not payload.get("admin_id"):
        # Old-shape token from before v1.1 — refuse rather than accept
        # ambiguously. Forces a fresh login through the new flow.
        return None
    return payload
