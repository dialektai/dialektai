"""GPU Relay key issuance + lifecycle.

Per-tenant Bearer keys for the gpu-relay.dias.now proxy. Plaintext is
shown exactly once at creation time and never re-readable; only the
SHA-256 hash hits the DB. Revocation is soft (sets ``revoked_at``) so
audit history survives.
"""
from __future__ import annotations

import hashlib
import secrets as _secrets
import uuid


KEY_PREFIX = "dlk_relay_"


def generate_key() -> tuple[str, str]:
    """Mint a fresh Bearer key.

    Returns ``(plaintext, sha256_hex)``. The plaintext format is
    ``dlk_relay_<urlsafe-token>`` — matches the prefix the desktop UI
    expects (placeholder + masking strip the prefix off in display).
    """
    plaintext = KEY_PREFIX + _secrets.token_urlsafe(32)
    return plaintext, _hash(plaintext)


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def create_key(
    pool,
    *,
    tenant_id: str,
    name: str,
    rate_limit_per_minute: int = 120,
    monthly_token_quota: int | None = None,
) -> dict:
    """Insert a new relay key. Returns a dict containing both the
    plaintext (caller must surface to the user immediately) and the
    metadata row.
    """
    plaintext, key_hash = generate_key()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO relay_keys
              (tenant_id, name, key_hash, rate_limit_per_minute,
               monthly_token_quota)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, tenant_id, name, rate_limit_per_minute,
                      monthly_token_quota, created_at, last_used_at,
                      revoked_at
            """,
            uuid.UUID(tenant_id), name, key_hash,
            rate_limit_per_minute, monthly_token_quota,
        )
    return {
        "plaintext": plaintext,    # shown exactly once
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "name": row["name"],
        "rate_limit_per_minute": row["rate_limit_per_minute"],
        "monthly_token_quota": row["monthly_token_quota"],
        "created_at": row["created_at"].isoformat(),
        "last_used_at": (
            row["last_used_at"].isoformat() if row["last_used_at"] else None
        ),
        "revoked_at": (
            row["revoked_at"].isoformat() if row["revoked_at"] else None
        ),
        "key_preview": _preview(plaintext),
    }


async def list_keys(pool, *, tenant_id: str, include_revoked: bool = False) -> list[dict]:
    """Return relay keys for a tenant. ``key_hash`` is never surfaced —
    only an opaque ``key_preview`` derived from the prefix + last 4
    chars of the hash (so the admin UI can distinguish keys at a glance
    without exposing material that would help attackers brute-force)."""
    where = "tenant_id = $1"
    if not include_revoked:
        where += " AND revoked_at IS NULL"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, tenant_id, name, key_hash, rate_limit_per_minute,
                   monthly_token_quota, created_at, last_used_at,
                   revoked_at
            FROM relay_keys
            WHERE {where}
            ORDER BY created_at DESC
            """,
            uuid.UUID(tenant_id),
        )
    return [
        {
            "id": str(r["id"]),
            "tenant_id": str(r["tenant_id"]),
            "name": r["name"],
            "rate_limit_per_minute": r["rate_limit_per_minute"],
            "monthly_token_quota": r["monthly_token_quota"],
            "created_at": r["created_at"].isoformat(),
            "last_used_at": (
                r["last_used_at"].isoformat() if r["last_used_at"] else None
            ),
            "revoked_at": (
                r["revoked_at"].isoformat() if r["revoked_at"] else None
            ),
            "key_preview": f"{KEY_PREFIX}…{r['key_hash'][-4:]}",
        }
        for r in rows
    ]


async def revoke_key(pool, *, key_id: str) -> bool:
    """Soft-revoke a key. Returns ``True`` on hit, ``False`` when the
    key didn't exist or was already revoked. Idempotent on repeat calls
    against the same revoked key."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE relay_keys
            SET revoked_at = now()
            WHERE id = $1 AND revoked_at IS NULL
            RETURNING id
            """,
            uuid.UUID(key_id),
        )
    return row is not None


async def get_usage_rollup(
    pool,
    *,
    tenant_id: str,
    days: int = 30,
) -> list[dict]:
    """Daily aggregate of relay_usage for a tenant — the admin UI's
    consumption chart hits this. Returns most-recent-first; days
    without traffic are absent (UI fills zeroes if it cares)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              date_trunc('day', created_at)::date AS day,
              count(*)                            AS requests,
              sum(prompt_tokens)::bigint          AS prompt_tokens,
              sum(completion_tokens)::bigint      AS completion_tokens,
              avg(latency_ms)::int                AS avg_latency_ms
            FROM relay_usage
            WHERE tenant_id = $1
              AND created_at >= now() - ($2 || ' days')::interval
            GROUP BY day
            ORDER BY day DESC
            """,
            uuid.UUID(tenant_id), str(days),
        )
    return [
        {
            "day": r["day"].isoformat(),
            "requests": r["requests"],
            "prompt_tokens": int(r["prompt_tokens"] or 0),
            "completion_tokens": int(r["completion_tokens"] or 0),
            "avg_latency_ms": int(r["avg_latency_ms"] or 0),
        }
        for r in rows
    ]


def _preview(plaintext: str) -> str:
    if len(plaintext) <= 8:
        return ""
    return f"{plaintext[:len(KEY_PREFIX) + 4]}…{plaintext[-4:]}"
