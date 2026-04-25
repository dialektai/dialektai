"""Unit tests for HMAC token service — no DB needed."""
import time
import pytest
from dialekt_cloud.services.tokens import (
    create_bearer_token,
    create_admin_session_token,
    generate_invite_token,
    generate_license_key,
    verify_admin_session_token,
    verify_bearer_token,
)

SECRET = "test_secret"
LICENSE_KEY = "dialekt_" + "a" * 64


def test_generate_license_key():
    key = generate_license_key()
    assert key.startswith("dialekt_")
    assert len(key) == 72  # "dialekt_" + 64 hex chars


def test_generate_invite_token():
    token = generate_invite_token()
    assert token.startswith("inv_")
    assert len(token) > 10


def test_generate_unique_keys():
    keys = {generate_license_key() for _ in range(50)}
    assert len(keys) == 50


def test_bearer_token_roundtrip():
    token = create_bearer_token(
        user_id="u1", tenant_id="t1", role="admin",
        license_key=LICENSE_KEY, secret=SECRET,
    )
    assert "." in token
    payload = verify_bearer_token(token, license_key=LICENSE_KEY, secret=SECRET)
    assert payload is not None
    assert payload["user_id"] == "u1"
    assert payload["tenant_id"] == "t1"
    assert payload["role"] == "admin"


def test_bearer_token_wrong_secret():
    token = create_bearer_token(
        user_id="u1", tenant_id="t1", role="admin",
        license_key=LICENSE_KEY, secret=SECRET,
    )
    result = verify_bearer_token(token, license_key=LICENSE_KEY, secret="wrong_secret")
    assert result is None


def test_bearer_token_wrong_license():
    token = create_bearer_token(
        user_id="u1", tenant_id="t1", role="admin",
        license_key=LICENSE_KEY, secret=SECRET,
    )
    result = verify_bearer_token(token, license_key="wrong_key", secret=SECRET)
    assert result is None


def test_bearer_token_expired():
    token = create_bearer_token(
        user_id="u1", tenant_id="t1", role="admin",
        license_key=LICENSE_KEY, secret=SECRET,
        ttl_seconds=-1,  # already expired
    )
    result = verify_bearer_token(token, license_key=LICENSE_KEY, secret=SECRET)
    assert result is None


def test_bearer_token_malformed():
    assert verify_bearer_token("notavalidtoken", license_key=LICENSE_KEY, secret=SECRET) is None
    assert verify_bearer_token("", license_key=LICENSE_KEY, secret=SECRET) is None
    assert verify_bearer_token("a.b.c.d", license_key=LICENSE_KEY, secret=SECRET) is None


def test_admin_session_token_roundtrip():
    """Multi-admin v1.1: admin_id + email baked into payload, JWT_SECRET-only signing."""
    token = create_admin_session_token(admin_id="abc-123", email="dias@dialekt.ai", secret=SECRET)
    payload = verify_admin_session_token(token, SECRET)
    assert payload is not None
    assert payload["admin_id"] == "abc-123"
    assert payload["email"] == "dias@dialekt.ai"
    assert payload["role"] == "founder_admin"


def test_admin_session_token_wrong_secret():
    token = create_admin_session_token(admin_id="abc", email="x@y.z", secret=SECRET)
    assert verify_admin_session_token(token, "different_secret") is None


def test_admin_session_token_expired():
    token = create_admin_session_token(admin_id="abc", email="x@y.z", secret=SECRET, ttl=-1)
    assert verify_admin_session_token(token, SECRET) is None


def test_admin_session_token_signing_does_not_use_admin_key():
    """Mentor P2 fix: DIALEKT_ADMIN_KEY is no longer in the signing material.
    Two tokens minted with the same admin_id but the same secret must verify
    against ONLY the JWT_SECRET, regardless of any 'admin_key' env var."""
    token = create_admin_session_token(admin_id="abc", email="x@y.z", secret=SECRET)
    # Verifies under JWT_SECRET, no extra key parameter accepted by the new sig.
    assert verify_admin_session_token(token, SECRET) is not None


def test_admin_session_token_rejects_old_shape_without_admin_id():
    """Pre-v1.1 tokens (no admin_id in payload) MUST be refused — caller
    must not be able to authenticate as 'whoever' with a legacy token."""
    import json, base64, hmac, hashlib
    # Forge a payload missing admin_id — same shape as old tokens.
    legacy_payload = {"role": "founder_admin", "iat": 0, "exp": 9_999_999_999}
    body = base64.urlsafe_b64encode(
        json.dumps(legacy_payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(
        hmac.new((SECRET + "_admin_session").encode(), body.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    forged = f"{body}.{sig}"
    # Even though the signature is technically correct, the missing
    # admin_id must trigger refusal.
    assert verify_admin_session_token(forged, SECRET) is None


def test_different_users_different_tokens():
    t1 = create_bearer_token(user_id="u1", tenant_id="t1", role="admin", license_key=LICENSE_KEY, secret=SECRET)
    t2 = create_bearer_token(user_id="u2", tenant_id="t1", role="user", license_key=LICENSE_KEY, secret=SECRET)
    assert t1 != t2
