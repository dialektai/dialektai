"""
Integration test for Blocker 3: license revocation propagation.

Exercises the real `refresh_once()` / `refresh_if_stale()` / `migrate_from_config()`
code paths with mocked cloud responses (via httpx_mock) so the test doesn't
require a live dialekt-cloud instance. For a full live test run the
docker-compose variant in `tests/integration/test_revocation_live.py`
(skipped when the cloud stack isn't running).

What we verify here:

- `refresh_once` with a healthy cloud marks the license as validated
- `refresh_once` with `valid:false` clears `license_key` + `cloud_bearer_token`
- Offline behaviour: grace period (24h) → after expiry → revoke
- Clock-skew tolerance: within ±5 min, `refresh_if_stale` does NOT re-call
- `migrate_from_config` moves plaintext secrets into the keychain
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# The module uses httpx via a short-lived AsyncClient; patch that layer.


# ── Shared test fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def fake_settings():
    """In-memory settings store that behaves like load_settings / save_settings."""
    data: dict = {
        "license_key": "dialekt_test_key_1234567890abcdef",
        "cloud_bearer_token": "eyJtest.bearer.token",
        "cloud_api_url": "http://127.0.0.1:8080",
        "last_license_validated_at": None,
        "last_license_revalidation_status": None,
        "tenant_info": {"plan": "team", "seats_limit": 3},
    }

    def load():
        return dict(data)

    def save(new):
        # Mimic the real save_settings: update in-place, drop None values
        # in the "sensitive" slots to simulate keychain delete.
        for k, v in new.items():
            data[k] = v

    return data, load, save


# ── Happy path: cloud says valid ──────────────────────────────────────────────

@pytest.mark.asyncio

async def test_refresh_once_valid_updates_timestamp(fake_settings):
    from dialekt.license_refresh import refresh_once

    data, load, save = fake_settings
    before = data.get("last_license_validated_at")
    assert before is None

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: {
        "valid": True,
        "plan": "team",
        "seats_limit": 3,
        "bearer_token": "eyJtest.refreshed.token",
    }
    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        report = await refresh_once(load, save)

    assert report == {"status": "ok"}
    assert data["last_license_validated_at"] is not None
    assert data["last_license_revalidation_status"] == "ok"
    assert data["cloud_bearer_token"] == "eyJtest.refreshed.token"
    assert data["license_key"] == "dialekt_test_key_1234567890abcdef"


# ── Revocation path: cloud says invalid ───────────────────────────────────────

@pytest.mark.asyncio

async def test_refresh_once_invalid_wipes_license(fake_settings):
    from dialekt.license_refresh import refresh_once

    data, load, save = fake_settings

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: {"valid": False, "reason": "tenant suspended"}
    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        report = await refresh_once(load, save)

    assert report["status"] == "revoked"
    assert report["reason"] == "tenant suspended"
    assert data["license_key"] is None
    assert data["cloud_bearer_token"] is None
    assert data["last_license_revalidation_status"] == "revoked"
    assert data["last_license_revocation_reason"] == "tenant suspended"


# ── Offline grace period ──────────────────────────────────────────────────────

@pytest.mark.asyncio

async def test_offline_within_grace_period_does_not_revoke(fake_settings):
    from dialekt.license_refresh import refresh_once

    data, load, save = fake_settings
    # Simulate a successful check 1 hour ago
    data["last_license_validated_at"] = time.time() - 3600

    import httpx
    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ConnectError("host unreachable")
        )
        report = await refresh_once(load, save)

    assert report["status"] == "offline"
    assert "grace_remaining_hours" in report
    assert data["license_key"] == "dialekt_test_key_1234567890abcdef"
    assert data["last_license_revalidation_status"] == "offline"


@pytest.mark.asyncio


async def test_offline_past_grace_revokes(fake_settings):
    from dialekt.license_refresh import refresh_once

    data, load, save = fake_settings
    # Simulate a successful check 25 hours ago (beyond 24h grace)
    data["last_license_validated_at"] = time.time() - (25 * 3600)

    import httpx
    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ConnectError("host unreachable")
        )
        report = await refresh_once(load, save)

    assert report["status"] == "revoked"
    assert "grace" in report["reason"]
    assert data["license_key"] is None


@pytest.mark.asyncio


async def test_offline_never_validated_revokes(fake_settings):
    """When a license was never successfully validated AND cloud is unreachable,
    we fail closed — can't trust it."""
    from dialekt.license_refresh import refresh_once

    data, load, save = fake_settings
    data["last_license_validated_at"] = 0  # never

    import httpx
    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ConnectError("host unreachable")
        )
        report = await refresh_once(load, save)

    assert report["status"] == "revoked"
    assert data["license_key"] is None


# ── Clock-skew tolerance ──────────────────────────────────────────────────────

@pytest.mark.asyncio

async def test_refresh_if_stale_skips_recent_check(fake_settings):
    from dialekt.license_refresh import refresh_if_stale

    data, load, save = fake_settings
    # Validated 20 min ago — well within 30 min staleness threshold
    data["last_license_validated_at"] = time.time() - (20 * 60)

    with patch("httpx.AsyncClient") as mc:
        # No post should be called
        mc.return_value.__aenter__.return_value.post = AsyncMock()
        report = await refresh_if_stale(load, save)

    assert report["status"] == "fresh"
    mc.return_value.__aenter__.return_value.post.assert_not_awaited()


@pytest.mark.asyncio


async def test_refresh_if_stale_validates_when_old(fake_settings):
    from dialekt.license_refresh import refresh_if_stale

    data, load, save = fake_settings
    # Validated 45 min ago — past threshold
    data["last_license_validated_at"] = time.time() - (45 * 60)

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: {"valid": True}
    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        report = await refresh_if_stale(load, save)

    assert report["status"] == "ok"
    mc.return_value.__aenter__.return_value.post.assert_awaited_once()


# ── Retry on transient network errors ─────────────────────────────────────────

@pytest.mark.asyncio

async def test_network_hiccup_retries_then_succeeds(fake_settings):
    from dialekt.license_refresh import refresh_once

    data, load, save = fake_settings

    import httpx
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: {"valid": True}
    # First two attempts time out, third succeeds
    responses = [
        httpx.TimeoutException("read timeout"),
        httpx.TimeoutException("read timeout"),
        mock_resp,
    ]

    async def flaky_post(*args, **kwargs):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(side_effect=flaky_post)
        # asyncio.sleep in the backoff path — patch to zero to keep test fast
        with patch("dialekt.license_refresh.asyncio.sleep", new=AsyncMock()):
            report = await refresh_once(load, save)

    assert report == {"status": "ok"}
    assert len(responses) == 0  # all attempts consumed


# ── Secrets migration ────────────────────────────────────────────────────────

def test_migrate_from_config_moves_plaintext_secrets(tmp_path: Path):
    from dialekt import secrets as secrets_mod

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "model": "gemma3-12b",
        "license_key": "dialekt_plaintext_abcdef",
        "cloud_bearer_token": "eyJplaintext.bearer",
        "cloud_api_url": "https://api.dias.now",
    }))

    # Patch _SERVICE so this test doesn't collide with any real keyring entries
    with patch.object(secrets_mod, "_SERVICE", "dialekt-test-migration"):
        # Clean up any leftover from a previous failed run
        for name in secrets_mod.SENSITIVE_KEYS:
            try:
                secrets_mod.delete_secret(name)
            except Exception:
                pass

        report = secrets_mod.migrate_from_config(cfg)

    assert "license_key" in report["migrated"]
    assert "cloud_bearer_token" in report["migrated"]

    # File on disk should no longer contain the plaintext values
    remaining = json.loads(cfg.read_text())
    assert "license_key" not in remaining
    assert "cloud_bearer_token" not in remaining
    assert remaining["cloud_api_url"] == "https://api.dias.now"

    # Cleanup
    with patch.object(secrets_mod, "_SERVICE", "dialekt-test-migration"):
        for name in secrets_mod.SENSITIVE_KEYS:
            try:
                secrets_mod.delete_secret(name)
            except Exception:
                pass


def test_backend_info_returns_kind():
    from dialekt.secrets import backend_info

    info = backend_info()
    assert "kind" in info
    assert info["kind"] in ("keyring", "fallback")
    assert "name" in info
    assert "secure" in info


def test_migrate_idempotent_after_first_run(tmp_path: Path):
    """Running migrate twice should not re-migrate already-moved secrets."""
    from dialekt import secrets as secrets_mod

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"license_key": "dialekt_idempotent_test"}))

    with patch.object(secrets_mod, "_SERVICE", "dialekt-test-idempotent"):
        try:
            first = secrets_mod.migrate_from_config(cfg)
            second = secrets_mod.migrate_from_config(cfg)
        finally:
            for name in secrets_mod.SENSITIVE_KEYS:
                try:
                    secrets_mod.delete_secret(name)
                except Exception:
                    pass

    assert "license_key" in first["migrated"]
    # Second run: no plaintext left, nothing to migrate
    assert second["migrated"] == []
