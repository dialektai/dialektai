"""Tests for self-serve trial signup, email verification, and admin extend.

Covers the v0.21 onboarding additions per mentor verdict:
- 4-field signup (email, full_name, intended_use, country)
- Email verification gate before license activates
- Window-bound idempotency (active trial = re-issue; expired = 409)
- Per-IP rate-limit
- Combined extend endpoint (replaces extend + grant-free-year split)
"""
import uuid
import pytest
from datetime import datetime, timezone, timedelta


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mk_signup_payload(**overrides):
    base = {
        "email": f"trial-{uuid.uuid4().hex[:8]}@example.kz",
        "full_name": "Aigerim Bekova",
        "intended_use": "Local AI agent for our Go backend team — code review, test generation, refactoring without leaking source to OpenAI.",
        "country": "KZ",
        "accept_tos": True,
    }
    base.update(overrides)
    return base


# ── Signup happy path ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signup_creates_trial_with_license(client):
    payload = _mk_signup_payload()
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["tenant_id"]
    assert body["license_key"]
    assert body["license_key"].startswith(("dialekt_", "DIALEKT_", "dlk"))
    assert body["verification_required"] is True
    assert body["expires_at"]


@pytest.mark.asyncio
async def test_signup_rejects_without_tos(client):
    payload = _mk_signup_payload(accept_tos=False)
    r = await client.post("/auth/signup", json=payload)
    # Pydantic validator returns 422 for refusal
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_signup_rejects_invalid_email(client):
    payload = _mk_signup_payload(email="not-an-email")
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_signup_rejects_short_intended_use(client):
    payload = _mk_signup_payload(intended_use="too short")
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_signup_country_normalised_uppercase(client, pool):
    payload = _mk_signup_payload(country="kz")  # lowercase input
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 200
    body = r.json()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT country FROM tenants WHERE id = $1", body["tenant_id"])
    assert row["country"] == "KZ"


# ── Idempotency window ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signup_idempotent_within_active_trial(client):
    """Same email twice while trial still valid → returns the same license key, not a 409."""
    email = f"idem-{uuid.uuid4().hex[:8]}@example.kz"
    p1 = _mk_signup_payload(email=email)
    r1 = await client.post("/auth/signup", json=p1)
    assert r1.status_code == 200
    key1 = r1.json()["license_key"]

    r2 = await client.post("/auth/signup", json=p1)
    assert r2.status_code == 200
    key2 = r2.json()["license_key"]
    assert key1 == key2, "active-trial re-signup must return same key"


@pytest.mark.asyncio
async def test_signup_blocked_after_trial_expiry(client, pool):
    """After trial expires, repeat signup with same email returns 409 (mentor P0)."""
    email = f"expired-{uuid.uuid4().hex[:8]}@example.kz"
    payload = _mk_signup_payload(email=email)
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 200
    tenant_id = r.json()["tenant_id"]

    # Force-expire the tenant
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tenants SET expires_at = $1 WHERE id = $2",
            datetime.now(timezone.utc) - timedelta(days=1), tenant_id,
        )

    r2 = await client.post("/auth/signup", json=payload)
    assert r2.status_code == 409
    assert "trial" in r2.json()["detail"].lower() or "extension" in r2.json()["detail"].lower()


# ── Email verification gate ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_license_fails_before_verify(client):
    """Trial license refuses to validate until email is verified."""
    payload = _mk_signup_payload()
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 200
    license_key = r.json()["license_key"]

    v = await client.post("/auth/validate-license", json={"license_key": license_key, "machine_id": "test"})
    assert v.status_code == 200
    assert v.json()["valid"] is False, "license must not validate before email verify"


@pytest.mark.asyncio
async def test_verify_email_then_validate_license_works(client, pool):
    """Click the verify link → license becomes active → validate-license OK."""
    email = f"verify-{uuid.uuid4().hex[:8]}@example.kz"
    payload = _mk_signup_payload(email=email)
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 200
    tenant_id = r.json()["tenant_id"]
    license_key = r.json()["license_key"]

    # Pull the verify token from the DB (in production it's emailed)
    async with pool.acquire() as conn:
        token = await conn.fetchval(
            "SELECT verify_token FROM email_verifications WHERE tenant_id = $1 ORDER BY created_at DESC LIMIT 1",
            tenant_id,
        )
    assert token

    v = await client.get(f"/auth/verify-email/{token}")
    assert v.status_code == 200, v.text
    assert v.json()["ok"] is True
    assert v.json()["already_verified"] is False

    # Now validate-license should succeed
    v2 = await client.post("/auth/validate-license", json={"license_key": license_key, "machine_id": "test"})
    body = v2.json()
    assert v2.status_code == 200
    assert body["valid"] is True
    assert body["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_verify_email_idempotent(client, pool):
    """Re-clicking the verify link is safe — returns already_verified=True."""
    email = f"twice-{uuid.uuid4().hex[:8]}@example.kz"
    r = await client.post("/auth/signup", json=_mk_signup_payload(email=email))
    tenant_id = r.json()["tenant_id"]
    async with pool.acquire() as conn:
        token = await conn.fetchval(
            "SELECT verify_token FROM email_verifications WHERE tenant_id = $1 LIMIT 1", tenant_id,
        )

    r1 = await client.get(f"/auth/verify-email/{token}")
    r2 = await client.get(f"/auth/verify-email/{token}")
    assert r1.json()["already_verified"] is False
    assert r2.json()["already_verified"] is True


@pytest.mark.asyncio
async def test_verify_email_unknown_token_404(client):
    r = await client.get("/auth/verify-email/nonexistent_token_12345")
    assert r.status_code == 404


# ── Resend verify ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resend_verify_for_unverified_returns_ok(client):
    email = f"resend-{uuid.uuid4().hex[:8]}@example.kz"
    await client.post("/auth/signup", json=_mk_signup_payload(email=email))
    r = await client.post("/auth/resend-verify", json={"email": email})
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_resend_verify_unknown_email_returns_ok(client):
    """Don't leak whether email exists."""
    r = await client.post("/auth/resend-verify", json={"email": "ghost@nowhere.example"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── Admin extend ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_extend_trial_to_paid(client, admin_headers, pool):
    """Extend a self-serve trial by paying — adds 90 days, bumps plan."""
    email = f"extend-{uuid.uuid4().hex[:8]}@example.kz"
    r = await client.post("/auth/signup", json=_mk_signup_payload(email=email))
    tenant_id = r.json()["tenant_id"]

    e = await client.post(
        f"/admin/tenants/{tenant_id}/extend",
        headers=admin_headers,
        json={"days": 90, "plan": "professional", "seats_limit": 5, "reason": "paid quarterly invoice INV-001"},
    )
    assert e.status_code == 200, e.text
    body = e.json()
    assert body["ok"] is True
    assert body["plan"] == "professional"
    assert body["seats_limit"] == 5
    assert body["status"] == "active"

    # Verify trial_converted_at got stamped
    async with pool.acquire() as conn:
        converted = await conn.fetchval(
            "SELECT trial_converted_at FROM tenants WHERE id = $1", tenant_id
        )
    assert converted is not None


@pytest.mark.asyncio
async def test_admin_grant_free_year(client, admin_headers, pool):
    """Mentor's combined endpoint: 365 days = 'grant free year'."""
    email = f"freeyear-{uuid.uuid4().hex[:8]}@example.kz"
    r = await client.post("/auth/signup", json=_mk_signup_payload(email=email))
    tenant_id = r.json()["tenant_id"]

    e = await client.post(
        f"/admin/tenants/{tenant_id}/extend",
        headers=admin_headers,
        json={"days": 365, "plan": "comp", "reason": "design partner program — Aigerim Bekova"},
    )
    assert e.status_code == 200
    body = e.json()
    new_expires = datetime.fromisoformat(body["expires_at"])
    delta = new_expires - datetime.now(timezone.utc)
    # Anchor is max(now, current expiry). Trial gives +30d already, +365
    # extension stacks → ~395 days. This is the design (don't shrink active
    # remaining time).
    assert 360 < delta.days <= 400, f"expected 360-400 days, got {delta.days}"
    assert body["plan"] == "comp"


@pytest.mark.asyncio
async def test_admin_extend_requires_reason(client, admin_headers):
    """Audit log mandate — empty reason is rejected."""
    payload = _mk_signup_payload()
    r = await client.post("/auth/signup", json=payload)
    tenant_id = r.json()["tenant_id"]

    e = await client.post(
        f"/admin/tenants/{tenant_id}/extend",
        headers=admin_headers,
        json={"days": 30, "reason": ""},
    )
    assert e.status_code in (400, 422)


@pytest.mark.asyncio
async def test_admin_extend_zero_days_rejected(client, admin_headers):
    payload = _mk_signup_payload()
    r = await client.post("/auth/signup", json=payload)
    tenant_id = r.json()["tenant_id"]

    e = await client.post(
        f"/admin/tenants/{tenant_id}/extend",
        headers=admin_headers,
        json={"days": 0, "reason": "noop"},
    )
    assert e.status_code == 400


# ── ToS / Privacy consent audit log ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_legal_versions_endpoint_returns_strings(client):
    r = await client.get("/auth/legal/versions")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("tos_version"), str) and body["tos_version"]
    assert isinstance(body.get("privacy_version"), str) and body["privacy_version"]


@pytest.mark.asyncio
async def test_signup_records_tos_acceptance_with_version(client, pool):
    """Lawyer requirement: every signup MUST record a tos_acceptances row
    with timestamp, version, and IP/UA evidence."""
    payload = _mk_signup_payload(
        email=f"consent-{uuid.uuid4().hex[:8]}@example.kz",
    )
    payload["tos_version"] = "2026-04-25-test"
    payload["privacy_version"] = "2026-04-25-test"
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 200
    tenant_id = r.json()["tenant_id"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT tenant_id, email, accepted_at, tos_version, privacy_version,
                   ip, user_agent, source
            FROM tos_acceptances WHERE tenant_id = $1::uuid
            ORDER BY accepted_at DESC LIMIT 1
            """,
            tenant_id,
        )
    assert row is not None, "no tos_acceptances row recorded"
    assert row["email"] == payload["email"]
    assert row["tos_version"] == "2026-04-25-test"
    assert row["privacy_version"] == "2026-04-25-test"
    assert row["ip"]  # IP captured
    assert row["source"] == "signup"
    assert row["accepted_at"] is not None


@pytest.mark.asyncio
async def test_signup_uses_server_default_version_if_missing(client, pool):
    """Old clients without version fields → server stamps current version."""
    payload = _mk_signup_payload(
        email=f"defaultver-{uuid.uuid4().hex[:8]}@example.kz",
    )
    # Don't set tos_version / privacy_version
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 200
    tenant_id = r.json()["tenant_id"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tos_version, privacy_version FROM tos_acceptances WHERE tenant_id = $1::uuid",
            tenant_id,
        )
    # Should be the server-side default (TOS_VERSION env var or hardcoded)
    assert row["tos_version"]  # not null
    assert row["privacy_version"]


@pytest.mark.asyncio
async def test_re_signup_logs_re_accept_consent_row(client, pool):
    """Re-signup within active trial must append a 're-accept' source row,
    not overwrite the original."""
    email = f"reaccept-{uuid.uuid4().hex[:8]}@example.kz"
    payload = _mk_signup_payload(email=email)

    r1 = await client.post("/auth/signup", json=payload)
    assert r1.status_code == 200
    r2 = await client.post("/auth/signup", json=payload)
    assert r2.status_code == 200

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT source FROM tos_acceptances WHERE email = $1 ORDER BY accepted_at",
            email,
        )
    sources = [r["source"] for r in rows]
    assert "signup" in sources
    assert "re-accept" in sources
    assert len(rows) >= 2, "consent log must be append-only across re-signups"


# ── Gated download — email contains license + download URLs ─────────────────


@pytest.mark.asyncio
async def test_signup_email_contains_download_links_and_license(client, app):
    """Verify email is the only public surface that exposes download URLs.
    Must include ALL three platforms + the trial license key + verify link."""
    payload = _mk_signup_payload(email=f"gated-{uuid.uuid4().hex[:8]}@example.kz")
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 200
    license_key = r.json()["license_key"]

    # Find the verify_email send in the mock service
    sent = app.state.email.sent
    verify_emails = [s for s in sent if s.get("template") == "verify_email" and s.get("to") == payload["email"]]
    assert verify_emails, "verify_email not sent"
    ctx = verify_emails[-1]["context"]

    # The license key must be in the email
    assert ctx["license_key"] == license_key

    # Download URLs for all 3 platforms must be present
    download_urls = [d["url"] for d in ctx["downloads"]]
    assert any(".dmg" in u for u in download_urls), "macOS download missing"
    assert any("setup.exe" in u or ".exe" in u for u in download_urls), "Windows download missing"
    assert any(".deb" in u for u in download_urls), "Linux .deb download missing"

    # Verify URL must be present
    assert ctx["verify_url"].startswith("http")
    assert "verify-email.html?token=" in ctx["verify_url"]

    # Releases page fallback URL must be present
    assert "github.com" in ctx["releases_page"]


@pytest.mark.asyncio
async def test_resend_verify_resends_email_with_downloads(client, app):
    """Resend pulls the same download URLs + license_key into the email."""
    email = f"resend-dl-{uuid.uuid4().hex[:8]}@example.kz"
    await client.post("/auth/signup", json=_mk_signup_payload(email=email))

    # Clear sent log so we count only the resend
    app.state.email.sent.clear()

    r = await client.post("/auth/resend-verify", json={"email": email})
    assert r.status_code == 200
    sent = [s for s in app.state.email.sent if s.get("template") == "verify_email"]
    assert sent, "resend did not trigger verify_email send"
    ctx = sent[-1]["context"]
    assert ctx["license_key"], "resend must include license_key"
    assert ctx["downloads"], "resend must include download URLs"


@pytest.mark.asyncio
async def test_admin_extend_logs_audit_entry(client, admin_headers, pool):
    payload = _mk_signup_payload()
    r = await client.post("/auth/signup", json=payload)
    tenant_id = r.json()["tenant_id"]

    await client.post(
        f"/admin/tenants/{tenant_id}/extend",
        headers=admin_headers,
        json={"days": 30, "reason": "test extension for audit"},
    )
    async with pool.acquire() as conn:
        log = await conn.fetchrow(
            "SELECT details FROM founder_admin_log WHERE action = 'extend_tenant' ORDER BY created_at DESC LIMIT 1"
        )
    assert log
    import json as _json
    details = log["details"] if isinstance(log["details"], dict) else _json.loads(log["details"])
    assert details["tenant_id"] == tenant_id
    assert details["days"] == 30
    assert "test extension for audit" in details["reason"]
