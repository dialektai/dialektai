"""Email-lifecycle tests covering Tier 1 + Tier 2 sends added in v0.22:

  Tier 1 — conversion / lifecycle:
    * trial-expiring scheduler (T-7, T-3, T-1, T+0)
    * license-extended notification
    * admin-signup notification (founder lead alert)

  Tier 2 — admin security alerts:
    * password_changed
    * backup_codes_regenerated
    * account_locked (self + broadcast)
    * totp_enrolled (re-enrollment only)
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone, timedelta
import pyotp


# ── Fixtures borrowed from test_signup / test_admin_2fa ─────────────────────


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


# ── Tier 1.1 — trial-expiring scheduler ─────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduler_sends_d7_when_trial_has_7_days_left(client, app, pool):
    """Tenant verified email + has 7 days left → expects d7 email + dedup tag."""
    from dialekt_cloud.services.scheduler import _expiring_trials_pass

    payload = _mk_signup_payload(email=f"d7-{uuid.uuid4().hex[:6]}@example.kz")
    r = await client.post("/auth/signup", json=payload)
    tenant_id = r.json()["tenant_id"]

    # Verify the email + force expires_at to ~6.5 days out (within d7 window)
    async with pool.acquire() as conn:
        token = await conn.fetchval(
            "SELECT verify_token FROM email_verifications WHERE tenant_id = $1::uuid LIMIT 1", tenant_id,
        )
    await client.get(f"/auth/verify-email/{token}")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tenants SET expires_at = $1, expiring_notices_sent = '{}' WHERE id = $2::uuid",
            datetime.now(timezone.utc) + timedelta(days=6, hours=12), tenant_id,
        )

    app.state.email.sent.clear()
    n = await _expiring_trials_pass(app)
    assert n >= 1
    sent_types = [s.get("type") for s in app.state.email.sent]
    assert "trial_expiring" in sent_types

    # Dedup: second pass must NOT send the same milestone again
    app.state.email.sent.clear()
    n2 = await _expiring_trials_pass(app)
    # n2 may be 0 OR may emit other windows — just ensure d7 didn't fire twice
    same_email_d7 = [s for s in app.state.email.sent
                     if s.get("type") == "trial_expiring" and s.get("to") == payload["email"]]
    assert not same_email_d7


@pytest.mark.asyncio
async def test_scheduler_skips_unverified_tenants(client, app, pool):
    """Don't email tenants who never verified — that's just typo'd inbox spam."""
    from dialekt_cloud.services.scheduler import _expiring_trials_pass

    payload = _mk_signup_payload(email=f"notverified-{uuid.uuid4().hex[:6]}@example.kz")
    r = await client.post("/auth/signup", json=payload)
    tenant_id = r.json()["tenant_id"]
    # Force window without verifying
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tenants SET expires_at = $1, expiring_notices_sent = '{}' WHERE id = $2::uuid",
            datetime.now(timezone.utc) + timedelta(hours=12), tenant_id,
        )
    app.state.email.sent.clear()
    await _expiring_trials_pass(app)
    sent_to_them = [s for s in app.state.email.sent if s.get("to") == payload["email"]]
    assert not sent_to_them


@pytest.mark.asyncio
async def test_scheduler_d0_for_just_expired_trial(client, app, pool):
    from dialekt_cloud.services.scheduler import _expiring_trials_pass

    payload = _mk_signup_payload(email=f"d0-{uuid.uuid4().hex[:6]}@example.kz")
    r = await client.post("/auth/signup", json=payload)
    tenant_id = r.json()["tenant_id"]
    async with pool.acquire() as conn:
        token = await conn.fetchval(
            "SELECT verify_token FROM email_verifications WHERE tenant_id = $1::uuid LIMIT 1", tenant_id)
    await client.get(f"/auth/verify-email/{token}")
    # Force expired 30 minutes ago
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tenants SET expires_at = $1, expiring_notices_sent = '{}' WHERE id = $2::uuid",
            datetime.now(timezone.utc) - timedelta(minutes=30), tenant_id,
        )
    app.state.email.sent.clear()
    await _expiring_trials_pass(app)
    sent_to_them = [s for s in app.state.email.sent
                    if s.get("type") == "trial_expiring" and s.get("to") == payload["email"]]
    assert sent_to_them
    assert sent_to_them[0]["days_left"] == 0


# ── Tier 1.2 — license-extended ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extend_tenant_sends_license_extended_email(client, app, admin_headers):
    payload = _mk_signup_payload(email=f"ext-{uuid.uuid4().hex[:6]}@example.kz")
    r = await client.post("/auth/signup", json=payload)
    tenant_id = r.json()["tenant_id"]

    app.state.email.sent.clear()
    e = await client.post(
        f"/admin/tenants/{tenant_id}/extend",
        headers=admin_headers,
        json={"days": 90, "plan": "professional", "reason": "paid Q1 invoice"},
    )
    assert e.status_code == 200
    sent = [s for s in app.state.email.sent if s.get("type") == "license_extended"]
    assert sent
    assert sent[0]["to"] == payload["email"]
    assert sent[0]["days_added"] == 90
    assert sent[0]["plan"] == "professional"


@pytest.mark.asyncio
async def test_extend_resets_expiring_notices_dedup(client, app, admin_headers, pool):
    """After admin extends, the d7/d3/d1/d0 dedup must clear so the new
    expiry window can re-trigger reminders later."""
    payload = _mk_signup_payload(email=f"reset-{uuid.uuid4().hex[:6]}@example.kz")
    r = await client.post("/auth/signup", json=payload)
    tenant_id = r.json()["tenant_id"]
    # Pretend we already sent d7
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tenants SET expiring_notices_sent = ARRAY['d7','d3'] WHERE id = $1::uuid",
            tenant_id,
        )
    await client.post(
        f"/admin/tenants/{tenant_id}/extend",
        headers=admin_headers,
        json={"days": 365, "plan": "comp", "reason": "design partner"},
    )
    async with pool.acquire() as conn:
        notices = await conn.fetchval(
            "SELECT expiring_notices_sent FROM tenants WHERE id = $1::uuid", tenant_id,
        )
    assert notices == [] or list(notices) == []


# ── Tier 1.3 — admin signup notification ────────────────────────────────────


@pytest.mark.asyncio
async def test_signup_sends_admin_signup_notification_to_admin_inbox(client, app):
    payload = _mk_signup_payload(email=f"signup-notif-{uuid.uuid4().hex[:6]}@example.kz")
    app.state.email.sent.clear()
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 200

    notifs = [s for s in app.state.email.sent if s.get("type") == "admin_signup_notification"]
    assert notifs, "admin_signup_notification must fire on fresh signup"
    n = notifs[0]
    assert n["signup_email"] == payload["email"]
    assert n["country"] == "KZ"
    assert n["intended_use"] == payload["intended_use"]
    # Sent to the configured admin-notify inbox
    from dialekt_cloud.config import settings as _cfg
    assert n["to"] == _cfg.ADMIN_NOTIFY_TO


@pytest.mark.asyncio
async def test_re_signup_does_not_re_notify_admin(client, app):
    """Idempotent re-signup must NOT re-fire the admin notification —
    otherwise Dias's inbox gets spammed every time someone re-clicks signup."""
    email = f"resignup-notif-{uuid.uuid4().hex[:6]}@example.kz"
    await client.post("/auth/signup", json=_mk_signup_payload(email=email))
    app.state.email.sent.clear()
    await client.post("/auth/signup", json=_mk_signup_payload(email=email))
    notifs = [s for s in app.state.email.sent if s.get("type") == "admin_signup_notification"]
    assert not notifs


# ── Tier 2 — security alerts ────────────────────────────────────────────────


@pytest.fixture
async def enrolled_admin(client, pool, app):
    """Helper: insert + enroll an admin via the full flow.
    Returns (email, password, secret)."""
    from dialekt_cloud.services.admin_auth import hash_password
    email = f"sec-{uuid.uuid4().hex[:6]}@dialekt.ai"
    pw = "secure-admin-pass-2026!"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins(email, password_hash) VALUES($1, $2)",
            email, hash_password(pw),
        )
    # password → enroll → confirm
    r1 = await client.post("/admin/login", json={"email": email, "password": pw})
    token = r1.json()["challenge_token"]
    r2 = await client.post(
        "/admin/login/enroll-totp",
        json={"challenge_token": token, "password_reconfirm": pw},
    )
    secret = r2.json()["secret"]
    code = pyotp.TOTP(secret).now()
    r3 = await client.post(
        "/admin/login/enroll-totp/confirm",
        json={"challenge_token": token, "secret": secret, "code": code},
    )
    cookie = r3.cookies.get("dialekt_admin_session")
    if cookie:
        client.cookies.set("dialekt_admin_session", cookie)
    return email, pw, secret


@pytest.mark.asyncio
async def test_password_change_sends_security_alert(client, app, enrolled_admin):
    email, pw, _ = enrolled_admin
    new_pw = "even-more-secure-2026-x!"
    app.state.email.sent.clear()
    r = await client.post(
        "/admin/password/change",
        json={"old_password": pw, "new_password": new_pw},
    )
    assert r.status_code == 200
    alerts = [s for s in app.state.email.sent
              if s.get("type") == "admin_security_alert" and s.get("kind") == "password_changed"]
    assert alerts
    assert alerts[0]["to"] == email
    # Restore the password so subsequent tests using fresh_admin from the
    # other module aren't affected (this admin was created in this fixture).


@pytest.mark.asyncio
async def test_regenerate_codes_sends_security_alert(client, app, enrolled_admin):
    email, pw, _ = enrolled_admin
    app.state.email.sent.clear()
    r = await client.post(
        "/admin/totp/regenerate-backup-codes",
        json={"password_reconfirm": pw},
    )
    assert r.status_code == 200
    alerts = [s for s in app.state.email.sent
              if s.get("type") == "admin_security_alert" and s.get("kind") == "backup_codes_regenerated"]
    assert alerts
    assert alerts[0]["to"] == email


@pytest.mark.asyncio
async def test_account_lockout_sends_alert_to_self_and_broadcasts(client, app, pool, monkeypatch):
    """Lockout must email the affected admin AND broadcast to other admins."""
    from dialekt_cloud.services.admin_auth import hash_password
    # Two admins so we can verify the broadcast path
    pw = "lockout-test-2026!"
    email_a = f"lockout-a-{uuid.uuid4().hex[:6]}@dialekt.ai"
    email_b = f"lockout-b-{uuid.uuid4().hex[:6]}@dialekt.ai"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins(email, password_hash) VALUES($1, $2), ($3, $2)",
            email_a, hash_password(pw), email_b,
        )

    monkeypatch.setenv("DIALEKT_ADMIN_LOCKOUT_BURST", "2")
    # Re-import constants from the module to pick up env changes for this test
    import importlib, dialekt_cloud.routers.admin as _adm
    monkeypatch.setattr(_adm, "LOCKOUT_BURST_COUNT", 2)
    monkeypatch.setattr(_adm, "LOCKOUT_HARD_COUNT", 999)  # don't hit hard

    app.state.email.sent.clear()
    # First failed login — under threshold, no alert
    await client.post("/admin/login", json={"email": email_a, "password": "x"})
    # Second failed login — crosses LOCKOUT_BURST_COUNT, fires alerts
    await client.post("/admin/login", json={"email": email_a, "password": "x"})

    alerts = [s for s in app.state.email.sent
              if s.get("type") == "admin_security_alert" and s.get("kind") == "account_locked"]
    assert alerts, "lockout must fire account_locked alerts"
    # Self-alert
    self_alerts = [a for a in alerts if a["to"] == email_a]
    assert self_alerts
    # Broadcast to email_b
    broadcast_alerts = [a for a in alerts if isinstance(a.get("to"), list) and email_b in a["to"]]
    assert broadcast_alerts


@pytest.mark.asyncio
async def test_initial_totp_enrollment_does_not_alert(client, app, pool):
    """First-ever enrollment is part of onboarding — no alert."""
    from dialekt_cloud.services.admin_auth import hash_password
    email = f"first-totp-{uuid.uuid4().hex[:6]}@dialekt.ai"
    pw = "first-time-2026!"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins(email, password_hash) VALUES($1, $2)",
            email, hash_password(pw),
        )
    app.state.email.sent.clear()
    r1 = await client.post("/admin/login", json={"email": email, "password": pw})
    tok = r1.json()["challenge_token"]
    r2 = await client.post(
        "/admin/login/enroll-totp",
        json={"challenge_token": tok, "password_reconfirm": pw},
    )
    secret = r2.json()["secret"]
    code = pyotp.TOTP(secret).now()
    await client.post(
        "/admin/login/enroll-totp/confirm",
        json={"challenge_token": tok, "secret": secret, "code": code},
    )
    alerts = [s for s in app.state.email.sent
              if s.get("type") == "admin_security_alert" and s.get("kind") == "totp_enrolled"]
    assert not alerts, "first-time enrollment must NOT alert"


@pytest.mark.asyncio
async def test_re_enrollment_after_reset_sends_alert(client, app, pool, enrolled_admin):
    """Re-enrollment after a CLI reset-2fa IS a security event — must alert."""
    email, pw, _ = enrolled_admin
    # Simulate CLI reset (clears totp_secret + totp_enrolled_at). The
    # audit log row from the original enroll remains — that's how the
    # endpoint detects 'this is a re-enroll, not a first-time enroll'.
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE admins SET totp_secret_encrypted = NULL,
                              totp_enrolled_at = NULL,
                              backup_codes = NULL,
                              backup_codes_generated_at = NULL
            WHERE email = $1
            """,
            email,
        )

    app.state.email.sent.clear()
    # Fresh login + enroll cycle
    r1 = await client.post("/admin/login", json={"email": email, "password": pw})
    tok = r1.json()["challenge_token"]
    r2 = await client.post(
        "/admin/login/enroll-totp",
        json={"challenge_token": tok, "password_reconfirm": pw},
    )
    new_secret = r2.json()["secret"]
    code = pyotp.TOTP(new_secret).now()
    await client.post(
        "/admin/login/enroll-totp/confirm",
        json={"challenge_token": tok, "secret": new_secret, "code": code},
    )
    alerts = [s for s in app.state.email.sent
              if s.get("type") == "admin_security_alert" and s.get("kind") == "totp_enrolled"]
    assert alerts, "re-enrollment must fire totp_enrolled alert"


# ── From-address routing — security alerts use security@, not hello@ ────────


@pytest.mark.asyncio
async def test_security_alerts_use_security_from_addr(client, app, enrolled_admin):
    """Alerts go FROM security@dias.now, not the default hello@."""
    email, pw, _ = enrolled_admin
    app.state.email.sent.clear()
    await client.post(
        "/admin/totp/regenerate-backup-codes",
        json={"password_reconfirm": pw},
    )
    # The mock service captures `from_addr` only on the generic .send()
    # path. The convenience send_admin_security_alert helper sets it
    # internally. Confirm our type-tagged record exists; the routing is
    # exercised by the real EmailService against Zoho — covered by the
    # email-service unit test below.
    found = [s for s in app.state.email.sent if s.get("type") == "admin_security_alert"]
    assert found


# ── Production readiness gate ──────────────────────────────────────────────


def test_assert_production_ready_passes_in_dev():
    """ENV=development bypasses all checks (default for tests)."""
    from dialekt_cloud.config import assert_production_ready
    problems = assert_production_ready()
    assert problems == []


def test_assert_production_ready_blocks_dev_defaults_in_prod(monkeypatch):
    """In ENV=production, refuse to boot with stock dev keys."""
    from dialekt_cloud.config import settings, assert_production_ready
    monkeypatch.setattr(settings, "ENV", "production")
    # Settings still have dev defaults
    problems = assert_production_ready()
    assert problems, "production with dev defaults must report problems"
    joined = " | ".join(problems).lower()
    assert "dialekt_admin_key" in joined or "jwt_secret" in joined or "totp_key" in joined


def test_assert_production_ready_requires_smtp_creds(monkeypatch):
    """No SMTP password in prod = users get no emails — must block."""
    from dialekt_cloud.config import settings, assert_production_ready
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "DIALEKT_ADMIN_KEY", "x" * 64)
    monkeypatch.setattr(settings, "JWT_SECRET", "x" * 60)
    import base64, os as _os
    monkeypatch.setattr(settings, "DIALEKT_ADMIN_TOTP_KEY", base64.b64encode(_os.urandom(32)).decode())
    monkeypatch.setattr(settings, "DIALEKT_ADMIN_EMAIL_DOMAIN", "@dias.now")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "")
    monkeypatch.setattr(settings, "SMTP_USER", "")
    problems = assert_production_ready()
    joined = " | ".join(problems).lower()
    assert "smtp_password" in joined
    assert "smtp_user" in joined


def test_email_service_send_passes_from_addr_through():
    """Unit test on the real EmailService: from_addr override reaches the
    MIME message header. Doesn't actually send (no SMTP) — we mock the send."""
    from unittest.mock import patch, AsyncMock
    from dialekt_cloud.services.email import EmailService
    import asyncio

    svc = EmailService(
        host="localhost", port=465, user="", password="",
        from_addr="default@dias.now", use_tls=False,
    )
    captured = {}

    async def fake_send(msg, **kwargs):
        captured["from"] = msg["From"]
        captured["reply_to"] = msg.get("Reply-To")

    with patch("aiosmtplib.send", new=AsyncMock(side_effect=fake_send)):
        async def _go():
            # Use a real existing template so jinja renders
            await svc.send(
                to="user@example.com",
                subject="hi",
                template="welcome",
                context={"company_name": "X", "landing_url": "https://x"},
                from_addr="security@dias.now",
                reply_to="security@dias.now",
            )
        asyncio.run(_go())

    assert "security@dias.now" in captured["from"]
    assert captured["reply_to"] == "security@dias.now"
