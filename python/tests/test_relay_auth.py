"""Tests for relay Bearer auth + rate limiting (Commit 2).

Unit-level — fakes the asyncpg pool with AsyncMock. The E2E test in
``tests/integration/test_relay_e2e.py`` (Commit 8) exercises the same
path against a real PG instance.
"""
from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from dialekt.relay.auth import (
    AuthError,
    RateLimiterRegistry,
    RelayKeyContext,
    RevokedKeyError,
    hash_key,
    verify_relay_key,
)
from dialekt.relay.config import RelayConfig
from dialekt.relay.server import create_app


def _ollama_stub() -> httpx.AsyncClient:
    """Always-200 Ollama mock for auth tests — the inference proxy
    isn't under test here."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    return httpx.AsyncClient(
        base_url="http://stub:11434",
        transport=httpx.MockTransport(handler),
    )


def _pool_returning(row):
    """Fake pool whose ``acquire`` yields a conn whose ``fetchrow``
    returns the supplied row regardless of arguments."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool = MagicMock()
    pool.close = AsyncMock()  # asyncpg.Pool.close is awaitable

    @asynccontextmanager
    async def acquire():
        yield conn

    pool.acquire = acquire
    return pool


def _key_row(*, revoked: bool = False, rate: int = 120, quota: int | None = None):
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "rate_limit_per_minute": rate,
        "monthly_token_quota": quota,
        "revoked_at": "2026-01-01T00:00:00Z" if revoked else None,
    }


# ── verify_relay_key ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_returns_context_for_valid_key():
    row = _key_row(rate=200, quota=1_000_000)
    pool = _pool_returning(row)

    ctx = await verify_relay_key("Bearer secret123", pool)

    assert isinstance(ctx, RelayKeyContext)
    assert ctx.tenant_id == str(row["tenant_id"])
    assert ctx.key_id == str(row["id"])
    assert ctx.rate_limit_per_minute == 200
    assert ctx.monthly_token_quota == 1_000_000


@pytest.mark.asyncio
async def test_verify_hashes_with_sha256():
    """The DB query is parameterised by the SHA-256 of the plaintext."""
    captured = {}
    conn = AsyncMock()

    async def fetchrow(query, key_hash):
        captured["hash"] = key_hash
        return _key_row()

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    pool = MagicMock()
    pool.close = AsyncMock()

    @asynccontextmanager
    async def acquire():
        yield conn

    pool.acquire = acquire

    await verify_relay_key("Bearer secret123", pool)
    assert captured["hash"] == hash_key("secret123")


@pytest.mark.asyncio
async def test_verify_raises_auth_for_missing_header():
    pool = _pool_returning(None)
    with pytest.raises(AuthError):
        await verify_relay_key(None, pool)


@pytest.mark.asyncio
async def test_verify_raises_auth_for_wrong_scheme():
    pool = _pool_returning(None)
    with pytest.raises(AuthError):
        await verify_relay_key("Basic dXNlcjpwYXNz", pool)


@pytest.mark.asyncio
async def test_verify_raises_auth_for_empty_token():
    pool = _pool_returning(None)
    with pytest.raises(AuthError):
        await verify_relay_key("Bearer    ", pool)


@pytest.mark.asyncio
async def test_verify_raises_auth_for_unknown_key():
    pool = _pool_returning(None)
    with pytest.raises(AuthError):
        await verify_relay_key("Bearer ghost", pool)


@pytest.mark.asyncio
async def test_verify_raises_revoked_when_revoked_at_set():
    pool = _pool_returning(_key_row(revoked=True))
    with pytest.raises(RevokedKeyError):
        await verify_relay_key("Bearer secret", pool)


# ── RateLimiterRegistry ─────────────────────────────────────────────────────


def test_registry_creates_one_limiter_per_key():
    reg = RateLimiterRegistry()
    reg.check("k1", 120)
    reg.check("k2", 120)
    assert len(reg) == 2


def test_registry_reuses_limiter_for_same_key():
    """Window state must persist across calls for the same key,
    otherwise the limit becomes per-call instead of per-window."""
    fake_now = [0.0]

    def clock():
        return fake_now[0]

    reg = RateLimiterRegistry(clock=clock)
    for _ in range(5):
        reg.check("k1", 5)
    # 5 calls in the same window with limit 5 — next call must trip.
    from dialekt.mcp.server.auth import RateLimitExceeded
    with pytest.raises(RateLimitExceeded):
        reg.check("k1", 5)


def test_registry_replaces_limiter_when_limit_changes():
    """Operator updates rate_limit_per_minute in DB → next request
    sees the new limit, not the old window."""
    reg = RateLimiterRegistry()
    for _ in range(3):
        reg.check("k1", 3)
    # Limit raised: a 4th call at limit 3 would trip, but at limit 10
    # the limiter is reset and the call proceeds.
    reg.check("k1", 10)


def test_registry_evicts_idle_entries():
    fake_now = [0.0]

    def clock():
        return fake_now[0]

    reg = RateLimiterRegistry(idle_ttl=10.0, clock=clock)
    reg.check("k1", 120)
    assert len(reg) == 1
    fake_now[0] = 100.0  # well past idle_ttl
    reg.check("k2", 120)  # triggers eviction sweep
    # k1 should be gone, only k2 remains.
    assert len(reg) == 1


# ── HTTP-level: status codes + JSON shape ───────────────────────────────────


@pytest.fixture
def relay_app():
    config = RelayConfig(port=3050, ollama_url="http://stub:11434")
    return create_app(config)


def test_missing_bearer_returns_401_auth(relay_app):
    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _ollama_stub()
        tc.app.state.pool = _pool_returning(None)
        r = tc.get("/relay/models")  # no Authorization

    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "auth"


def test_unknown_key_returns_401_auth(relay_app):
    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _ollama_stub()
        tc.app.state.pool = _pool_returning(None)  # any hash → no row
        r = tc.get("/relay/models", headers={"Authorization": "Bearer ghost"})

    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "auth"


def test_revoked_key_returns_401_revoked(relay_app):
    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _ollama_stub()
        tc.app.state.pool = _pool_returning(_key_row(revoked=True))
        r = tc.get("/relay/models", headers={"Authorization": "Bearer x"})

    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "revoked"


def test_rate_limit_exceeded_returns_429(relay_app):
    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _ollama_stub()
        tc.app.state.pool = _pool_returning(_key_row(rate=2))
        # Two calls at limit=2 fit; the third trips.
        for _ in range(2):
            assert tc.get(
                "/relay/models",
                headers={"Authorization": "Bearer x"},
            ).status_code == 200
        r = tc.get("/relay/models", headers={"Authorization": "Bearer x"})

    assert r.status_code == 429
    body = r.json()["detail"]
    assert body["error"] == "rate_limited"
    assert body["retry_after"] == 60


def test_unconfigured_relay_returns_503(relay_app):
    """No DB pool configured (cloud_db_url missing) → 503 unconfigured,
    not silent allow-through."""
    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _ollama_stub()
        tc.app.state.pool = None
        r = tc.get("/relay/models", headers={"Authorization": "Bearer x"})

    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "unconfigured"
