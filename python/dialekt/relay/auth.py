"""Per-tenant Bearer auth + rate limiting for the dialekt GPU Relay.

Pilots send ``Authorization: Bearer dlk_relay_<token>``. The relay
SHA-256s the token and looks it up in the ``relay_keys`` table
(asyncpg pool against ``dialekt_cloud``). Hits are rate-limited per key
on a rolling 60-second window — same shape as the MCP server uses for
its own API keys, reusing the existing :class:`RateLimiter` so the two
surfaces stay consistent.

Errors map to HTTP status codes with a structured JSON detail:

  401  ``{error: "auth",        message: "..."}``     missing/wrong key
  401  ``{error: "revoked",     message: "..."}``     key was revoked
  429  ``{error: "rate_limited", retry_after: 60, ...}``
  503  ``{error: "unconfigured", message: "..."}``    relay started without cloud_db_url

The 503 path is deliberately distinct: it surfaces an operator
misconfiguration ("relay-server.toml has no cloud_db_url") rather than
silently letting unauthenticated traffic through.
"""
from __future__ import annotations

import hashlib
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import HTTPException, Request

from dialekt.mcp.server.auth import RateLimiter, RateLimitExceeded


@dataclass(frozen=True)
class RelayKeyContext:
    """Decoded relay key — what the request is allowed to do.

    Carried through FastAPI's ``Depends`` chain so billing (Commit 3)
    can attribute usage to ``tenant_id`` + ``key_id`` without re-doing
    the lookup.
    """
    tenant_id: str           # UUID string
    key_id: str              # UUID string
    rate_limit_per_minute: int
    monthly_token_quota: Optional[int]


class AuthError(Exception):
    """Bearer header missing, malformed, or unknown key."""


class RevokedKeyError(AuthError):
    """Key matched the table but ``revoked_at`` is set."""


def hash_key(plaintext: str) -> str:
    """SHA-256 of the Bearer plaintext, hex-encoded.

    Plaintext keys are NEVER stored — only the hash. This is what the
    admin issuance flow (Commit 6) writes into ``relay_keys.key_hash``.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def verify_relay_key(authorization: Optional[str], pool) -> RelayKeyContext:
    """Validate a Bearer header against the ``relay_keys`` table.

    Returns a :class:`RelayKeyContext` on success.
    Raises :class:`AuthError` (or :class:`RevokedKeyError`) on failure.
    Pool must be an ``asyncpg.Pool`` (or a duck-typed equivalent for
    tests — see ``test_relay_auth.py``).
    """
    if not authorization:
        raise AuthError("missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        raise AuthError("expected Authorization: Bearer <key>")
    plaintext = authorization[7:].strip()
    if not plaintext:
        raise AuthError("empty Bearer token")

    key_hash = hash_key(plaintext)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, tenant_id, rate_limit_per_minute,
                   monthly_token_quota, revoked_at
            FROM relay_keys
            WHERE key_hash = $1
            """,
            key_hash,
        )

    if row is None:
        raise AuthError("unknown key")
    if row["revoked_at"] is not None:
        raise RevokedKeyError("key revoked")

    return RelayKeyContext(
        tenant_id=str(row["tenant_id"]),
        key_id=str(row["id"]),
        rate_limit_per_minute=int(row["rate_limit_per_minute"]),
        monthly_token_quota=(
            int(row["monthly_token_quota"])
            if row["monthly_token_quota"] is not None
            else None
        ),
    )


@dataclass
class _Entry:
    limiter: RateLimiter
    limit: int
    last_seen: float


class RateLimiterRegistry:
    """Per-key :class:`RateLimiter` instances, lazily created.

    Idle entries are evicted after ``idle_ttl`` seconds so a long-lived
    relay process doesn't accumulate one limiter per ever-seen key.

    Operator may change ``rate_limit_per_minute`` for a key in the DB;
    the registry honours the new value on the next request by replacing
    the limiter (rather than carrying old window state forward).
    """

    def __init__(
        self,
        *,
        idle_ttl: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._entries: dict[str, _Entry] = {}
        self._idle_ttl = idle_ttl
        self._clock = clock
        self._lock = threading.Lock()

    def check(self, key_id: str, limit_per_minute: int) -> None:
        """Record one call against ``key_id``. Raises
        :class:`RateLimitExceeded` if the rolling window is full.
        """
        with self._lock:
            now = self._clock()
            entry = self._entries.get(key_id)
            if entry is None or entry.limit != limit_per_minute:
                entry = _Entry(
                    limiter=RateLimiter(limit_per_minute, clock=self._clock),
                    limit=limit_per_minute,
                    last_seen=now,
                )
            else:
                entry.last_seen = now
            self._entries[key_id] = entry
            self._evict_idle(now)
            limiter = entry.limiter
        limiter.check_and_record()  # outside the registry lock

    def _evict_idle(self, now: float) -> None:
        cutoff = now - self._idle_ttl
        for kid, e in list(self._entries.items()):
            if e.last_seen < cutoff:
                self._entries.pop(kid, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


async def get_relay_context(request: Request) -> RelayKeyContext:
    """FastAPI dependency: validate Bearer + rate-limit, return context.

    Wired into every authenticated endpoint via
    ``Depends(get_relay_context)``. Maps internal exceptions to HTTP
    status codes + structured JSON details.
    """
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        # Relay started without cloud_db_url. Refuse to authenticate
        # rather than letting traffic through unchecked.
        raise HTTPException(
            status_code=503,
            detail={
                "error": "unconfigured",
                "message": (
                    "relay has no cloud_db_url configured — auth disabled, "
                    "endpoint refusing requests"
                ),
            },
        )

    auth_header = request.headers.get("authorization")
    try:
        ctx = await verify_relay_key(auth_header, pool)
    except RevokedKeyError as e:
        raise HTTPException(
            status_code=401,
            detail={"error": "revoked", "message": str(e)},
        )
    except AuthError as e:
        raise HTTPException(
            status_code=401,
            detail={"error": "auth", "message": str(e)},
        )

    registry: RateLimiterRegistry = request.app.state.rate_limiter_registry
    try:
        registry.check(ctx.key_id, ctx.rate_limit_per_minute)
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "message": str(e),
                "retry_after": 60,
            },
        )

    return ctx
