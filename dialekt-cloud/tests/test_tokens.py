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
    admin_key = "a" * 64
    token = create_admin_session_token(admin_key, SECRET)
    assert verify_admin_session_token(token, admin_key, SECRET)


def test_admin_session_token_wrong_key():
    admin_key = "a" * 64
    token = create_admin_session_token(admin_key, SECRET)
    assert not verify_admin_session_token(token, "b" * 64, SECRET)


def test_admin_session_token_expired():
    admin_key = "a" * 64
    token = create_admin_session_token(admin_key, SECRET, ttl=-1)
    assert not verify_admin_session_token(token, admin_key, SECRET)


def test_different_users_different_tokens():
    t1 = create_bearer_token(user_id="u1", tenant_id="t1", role="admin", license_key=LICENSE_KEY, secret=SECRET)
    t2 = create_bearer_token(user_id="u2", tenant_id="t1", role="user", license_key=LICENSE_KEY, secret=SECRET)
    assert t1 != t2
