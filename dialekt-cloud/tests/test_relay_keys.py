"""Tests for GPU Relay key issuance + lifecycle (Commit 6).

Auto-skipped without a live PG instance — same convention as the rest
of the dialekt-cloud test suite. Uses the session-scoped ``pool``,
``client``, ``admin_headers``, and ``tenant_id`` fixtures from
conftest.py.
"""
from __future__ import annotations

import hashlib

import pytest

pytestmark = pytest.mark.asyncio


async def test_issue_returns_plaintext_once(client, admin_headers, tenant_id):
    r = await client.post(
        f"/admin/tenants/{tenant_id}/relay-keys",
        headers=admin_headers,
        json={"name": "pilot laptop", "rate_limit_per_minute": 200},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plaintext"].startswith("dlk_relay_")
    assert body["name"] == "pilot laptop"
    assert body["rate_limit_per_minute"] == 200
    assert body["revoked_at"] is None
    assert body["last_used_at"] is None
    # Subsequent list never re-surfaces the plaintext.
    list_r = await client.get(
        f"/admin/tenants/{tenant_id}/relay-keys", headers=admin_headers,
    )
    assert list_r.status_code == 200
    keys = list_r.json()
    assert len(keys) == 1
    assert "plaintext" not in keys[0]
    assert keys[0]["key_preview"].startswith("dlk_relay_")


async def test_issue_persists_only_hash_not_plaintext(
    client, admin_headers, tenant_id, pool,
):
    r = await client.post(
        f"/admin/tenants/{tenant_id}/relay-keys",
        headers=admin_headers,
        json={"name": "k1"},
    )
    plaintext = r.json()["plaintext"]
    expected = hashlib.sha256(plaintext.encode()).hexdigest()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key_hash FROM relay_keys WHERE tenant_id = $1",
            r.json()["tenant_id"],
        )
    assert any(row["key_hash"] == expected for row in rows)
    assert not any(plaintext in (row["key_hash"] or "") for row in rows)


async def test_list_excludes_revoked_by_default(client, admin_headers, tenant_id):
    keep = (await client.post(
        f"/admin/tenants/{tenant_id}/relay-keys",
        headers=admin_headers, json={"name": "keep"},
    )).json()
    drop = (await client.post(
        f"/admin/tenants/{tenant_id}/relay-keys",
        headers=admin_headers, json={"name": "drop"},
    )).json()

    rev = await client.delete(
        f"/admin/relay-keys/{drop['id']}", headers=admin_headers,
    )
    assert rev.status_code == 200

    listed = await client.get(
        f"/admin/tenants/{tenant_id}/relay-keys", headers=admin_headers,
    )
    ids = {k["id"] for k in listed.json()}
    assert keep["id"] in ids
    assert drop["id"] not in ids

    listed_all = await client.get(
        f"/admin/tenants/{tenant_id}/relay-keys?include_revoked=true",
        headers=admin_headers,
    )
    ids_all = {k["id"] for k in listed_all.json()}
    assert drop["id"] in ids_all


async def test_revoke_idempotent_on_second_call(client, admin_headers, tenant_id):
    body = (await client.post(
        f"/admin/tenants/{tenant_id}/relay-keys",
        headers=admin_headers, json={"name": "k"},
    )).json()

    first = await client.delete(
        f"/admin/relay-keys/{body['id']}", headers=admin_headers,
    )
    assert first.status_code == 200

    # Second revoke returns 404 — already revoked.
    second = await client.delete(
        f"/admin/relay-keys/{body['id']}", headers=admin_headers,
    )
    assert second.status_code == 404


async def test_revoke_rejects_unknown_key(client, admin_headers):
    import uuid
    r = await client.delete(
        f"/admin/relay-keys/{uuid.uuid4()}", headers=admin_headers,
    )
    assert r.status_code == 404


async def test_admin_auth_required(client, tenant_id):
    """No X-Admin-Key → 401/403; the endpoint must not silently expose
    keys or usage."""
    r1 = await client.post(
        f"/admin/tenants/{tenant_id}/relay-keys", json={"name": "x"},
    )
    assert r1.status_code in (401, 403)

    r2 = await client.get(f"/admin/tenants/{tenant_id}/relay-keys")
    assert r2.status_code in (401, 403)

    import uuid
    r3 = await client.delete(f"/admin/relay-keys/{uuid.uuid4()}")
    assert r3.status_code in (401, 403)


async def test_usage_rollup_returns_empty_for_unused_tenant(
    client, admin_headers, tenant_id,
):
    r = await client.get(
        f"/admin/tenants/{tenant_id}/relay-usage", headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_usage_rollup_aggregates_by_day(
    client, admin_headers, tenant_id, pool,
):
    """Synthesize a few relay_usage rows directly, then verify the
    rollup endpoint returns the right shape."""
    body = (await client.post(
        f"/admin/tenants/{tenant_id}/relay-keys",
        headers=admin_headers, json={"name": "k"},
    )).json()
    key_id = body["id"]

    async with pool.acquire() as conn:
        for tokens in (10, 20, 30):
            await conn.execute(
                """
                INSERT INTO relay_usage
                  (tenant_id, relay_key_id, model,
                   prompt_tokens, completion_tokens, latency_ms)
                VALUES ($1, $2, 'llama3', $3, $4, $5)
                """,
                tenant_id, key_id, tokens, tokens // 2, 50 * tokens,
            )

    r = await client.get(
        f"/admin/tenants/{tenant_id}/relay-usage", headers=admin_headers,
    )
    assert r.status_code == 200
    days = r.json()
    assert len(days) == 1                # all three rows on the same day
    today = days[0]
    assert today["requests"] == 3
    assert today["prompt_tokens"] == 60  # 10 + 20 + 30
    assert today["completion_tokens"] == 30  # 5 + 10 + 15
    assert today["avg_latency_ms"] > 0


async def test_usage_rollup_validates_days_range(client, admin_headers, tenant_id):
    bad_low = await client.get(
        f"/admin/tenants/{tenant_id}/relay-usage?days=0",
        headers=admin_headers,
    )
    assert bad_low.status_code == 400

    bad_high = await client.get(
        f"/admin/tenants/{tenant_id}/relay-usage?days=400",
        headers=admin_headers,
    )
    assert bad_high.status_code == 400
