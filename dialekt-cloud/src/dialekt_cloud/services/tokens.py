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


def create_admin_session_token(admin_key: str, secret: str, ttl: int = 3600) -> str:
    """Short-lived session token for founder admin panel."""
    now = _utcnow()
    payload = {"role": "founder_admin", "iat": now, "exp": now + ttl}
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = _sign(payload_b64 + admin_key, secret)
    return f"{payload_b64}.{sig}"


def verify_admin_session_token(token: str, admin_key: str, secret: str) -> bool:
    try:
        payload_b64, sig = token.rsplit(".", 1)
    except ValueError:
        return False
    expected = _sign(payload_b64 + admin_key, secret)
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        padding = 4 - len(payload_b64) % 4
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * padding))
    except Exception:
        return False
    return payload.get("exp", 0) >= _utcnow()
