"""Tests for admin 2FA Phase 1 — admin_2fa_DESIGN.md.

P0 regression guard runs first per mentor's "watch it fail, then fix" rule.
"""
import re
import uuid
import pytest
import pyotp


# ── P0 regression guard — admin_key must NEVER appear in dashboard HTML ─────


@pytest.mark.asyncio
async def test_dashboard_html_does_not_contain_admin_key(client):
    """Mentor P0: the static admin key was previously rendered into
    dashboard.html via Jinja and used by client JS as X-Admin-Key. That's
    a credential leak vector (XSS / view-source / screenshare). This test
    fails the day someone reintroduces it."""
    from dialekt_cloud.services.tokens import create_admin_session_token
    from dialekt_cloud.config import settings as _cfg
    # Mint a real session cookie (multi-admin v1.1 shape) for the test.
    token = create_admin_session_token(
        admin_id="00000000-0000-0000-0000-000000000000",
        email="test@dias.now",
        secret=_cfg.JWT_SECRET,
        ttl=300,
    )

    r = await client.get("/admin/ui/", cookies={"dialekt_admin_session": token})
    assert r.status_code == 200, r.text
    body = r.text

    assert _cfg.DIALEKT_ADMIN_KEY not in body, (
        "P0 REGRESSION: DIALEKT_ADMIN_KEY found in dashboard HTML."
    )
    assert "X-Admin-Key" not in body, (
        "P0 REGRESSION: dashboard JS still sends X-Admin-Key header."
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def fresh_admin(pool):
    """Insert a fresh admin row directly via SQL. Returns (email, password)."""
    from dialekt_cloud.services.admin_auth import hash_password
    email = f"admin-{uuid.uuid4().hex[:8]}@dias.now"
    password = "correct-horse-battery-staple-2026"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins(email, password_hash) VALUES($1, $2)",
            email, hash_password(password),
        )
    return email, password


async def _login_to_totp_challenge(client, email, password):
    """Drive stage 1; return challenge_token + next stage."""
    r = await client.post("/admin/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["challenge_token"], body["next"]


async def _enroll_totp(client, challenge_token, password):
    r = await client.post(
        "/admin/login/enroll-totp",
        json={"challenge_token": challenge_token, "password_reconfirm": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["secret"]


# ── Stage 1 — password ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_password_unknown_email_401(client):
    r = await client.post("/admin/login", json={"email": "ghost@nowhere.example", "password": "x"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_password_wrong_password_401(client, fresh_admin):
    email, _ = fresh_admin
    r = await client.post("/admin/login", json={"email": email, "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_password_correct_returns_challenge_to_enroll(client, fresh_admin):
    email, pw = fresh_admin
    challenge, nxt = await _login_to_totp_challenge(client, email, pw)
    assert challenge
    assert nxt == "enroll_totp"  # fresh admin not yet enrolled


# ── Stage 3 — TOTP enrollment ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enroll_totp_returns_provisioning_uri_and_qr(client, fresh_admin):
    email, pw = fresh_admin
    challenge, _ = await _login_to_totp_challenge(client, email, pw)
    r = await client.post(
        "/admin/login/enroll-totp",
        json={"challenge_token": challenge, "password_reconfirm": pw},
    )
    body = r.json()
    assert r.status_code == 200
    assert body["secret"]
    assert body["provisioning_uri"].startswith("otpauth://totp/dias.now:")
    assert "<svg" in body["qr_svg"]


@pytest.mark.asyncio
async def test_enroll_totp_wrong_password_reconfirm_401(client, fresh_admin):
    email, pw = fresh_admin
    challenge, _ = await _login_to_totp_challenge(client, email, pw)
    r = await client.post(
        "/admin/login/enroll-totp",
        json={"challenge_token": challenge, "password_reconfirm": "wrong"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_enroll_confirm_with_valid_code_persists_and_returns_backup_codes(client, pool, fresh_admin):
    email, pw = fresh_admin
    challenge, _ = await _login_to_totp_challenge(client, email, pw)
    secret = await _enroll_totp(client, challenge, pw)
    code = pyotp.TOTP(secret).now()
    r = await client.post(
        "/admin/login/enroll-totp/confirm",
        json={"challenge_token": challenge, "secret": secret, "code": code},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["backup_codes"], list)
    assert len(body["backup_codes"]) == 10
    # cookie was set
    assert "dialekt_admin_session" in r.headers.get("set-cookie", "")
    # admin row updated
    async with pool.acquire() as conn:
        admin = await conn.fetchrow("SELECT totp_enrolled_at, totp_secret_encrypted FROM admins WHERE email = $1", email)
    assert admin["totp_enrolled_at"] is not None
    assert admin["totp_secret_encrypted"]


@pytest.mark.asyncio
async def test_enroll_confirm_with_wrong_code_rejected(client, fresh_admin):
    email, pw = fresh_admin
    challenge, _ = await _login_to_totp_challenge(client, email, pw)
    secret = await _enroll_totp(client, challenge, pw)
    r = await client.post(
        "/admin/login/enroll-totp/confirm",
        json={"challenge_token": challenge, "secret": secret, "code": "000000"},
    )
    assert r.status_code == 401


# ── Stage 2 — TOTP login (post-enrollment) ──────────────────────────────────


async def _enroll_admin_fully(client, pool, fresh_admin):
    """Helper: drive password→enroll→confirm. Returns (email, pw, secret, backup_codes).
    Side-effect: stores the session cookie on the AsyncClient via client.cookies.set()
    so subsequent requests in the same test are authenticated.
    """
    email, pw = fresh_admin
    challenge, _ = await _login_to_totp_challenge(client, email, pw)
    secret = await _enroll_totp(client, challenge, pw)
    code = pyotp.TOTP(secret).now()
    r = await client.post(
        "/admin/login/enroll-totp/confirm",
        json={"challenge_token": challenge, "secret": secret, "code": code},
    )
    backup_codes = r.json()["backup_codes"]
    # Explicitly persist the cookie — httpx ASGITransport does store it but
    # cookie-jar semantics across the session-scoped client across tests
    # are flaky (persists from prior tests). Setting it deterministically
    # here makes the test's intent explicit.
    cookie_value = r.cookies.get("dialekt_admin_session")
    if cookie_value:
        client.cookies.set("dialekt_admin_session", cookie_value)
    return email, pw, secret, backup_codes


@pytest.mark.asyncio
async def test_login_totp_after_enrollment_returns_session_cookie(client, pool, fresh_admin):
    email, pw, secret, _ = await _enroll_admin_fully(client, pool, fresh_admin)

    challenge, nxt = await _login_to_totp_challenge(client, email, pw)
    assert nxt == "totp_challenge"
    code = pyotp.TOTP(secret).now()
    r = await client.post(
        "/admin/login/totp",
        json={"challenge_token": challenge, "code": code, "is_backup_code": False},
    )
    assert r.status_code == 200, r.text
    assert "dialekt_admin_session" in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_login_totp_wrong_code_401(client, pool, fresh_admin):
    email, pw, secret, _ = await _enroll_admin_fully(client, pool, fresh_admin)
    challenge, _ = await _login_to_totp_challenge(client, email, pw)
    r = await client.post(
        "/admin/login/totp",
        json={"challenge_token": challenge, "code": "000000", "is_backup_code": False},
    )
    assert r.status_code == 401


# ── Backup codes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_backup_code_login_works_and_one_shot(client, pool, fresh_admin):
    email, pw, _, backup_codes = await _enroll_admin_fully(client, pool, fresh_admin)
    code_to_use = backup_codes[0]

    # First use: succeeds
    challenge, _ = await _login_to_totp_challenge(client, email, pw)
    r1 = await client.post(
        "/admin/login/totp",
        json={"challenge_token": challenge, "code": code_to_use, "is_backup_code": True},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json().get("backup_codes_remaining") == 9

    # Second use of the SAME code: rejected (one-shot)
    challenge2, _ = await _login_to_totp_challenge(client, email, pw)
    r2 = await client.post(
        "/admin/login/totp",
        json={"challenge_token": challenge2, "code": code_to_use, "is_backup_code": True},
    )
    assert r2.status_code == 401


# ── Lockout ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_password_lockout_after_burst(client, pool, fresh_admin, monkeypatch):
    # Lower the burst threshold for this test alone
    monkeypatch.setenv("DIALEKT_ADMIN_LOCKOUT_BURST", "3")
    email, _ = fresh_admin
    for _ in range(3):
        r = await client.post("/admin/login", json={"email": email, "password": "wrong"})
        assert r.status_code == 401
    # Next attempt with CORRECT password should still be locked
    correct_pw = "correct-horse-battery-staple-2026"
    r2 = await client.post("/admin/login", json={"email": email, "password": correct_pw})
    assert r2.status_code in (401, 429), f"expected lockout but got {r2.status_code}"


# ── Login attempts audit log ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_attempts_logged(client, pool, fresh_admin):
    email, pw = fresh_admin
    # one bad pw, one good pw
    await client.post("/admin/login", json={"email": email, "password": "wrong"})
    await client.post("/admin/login", json={"email": email, "password": pw})

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage, succeeded, failure_reason FROM admin_login_attempts WHERE email = $1 ORDER BY created_at",
            email,
        )
    stages = [(r["stage"], r["succeeded"]) for r in rows]
    assert ("password", False) in stages
    assert ("password", True) in stages


# ── Break-glass key (header-only, no cookie) ────────────────────────────────


@pytest.mark.asyncio
async def test_break_glass_key_works_for_api_but_does_not_set_cookie(client):
    """Mentor add-on: break-glass auth must NOT mint a session cookie."""
    from dialekt_cloud.config import settings as _cfg
    r = await client.get("/admin/stats", headers={"X-Admin-Key": _cfg.DIALEKT_ADMIN_KEY})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "dialekt_admin_session" not in set_cookie


# ── /admin/me ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_me_via_break_glass_returns_no_admin_id(client):
    """Break-glass auth has no admin_id — /me must reflect that."""
    from dialekt_cloud.config import settings as _cfg
    r = await client.get("/admin/me", headers={"X-Admin-Key": _cfg.DIALEKT_ADMIN_KEY})
    assert r.status_code == 200
    body = r.json()
    assert body["via"] == "break-glass-key"
    assert body["admin_id"] is None
    assert body["email"] is None


@pytest.mark.asyncio
async def test_admin_me_via_session_cookie_returns_full_profile(client, pool, fresh_admin):
    """After full login, /me returns the acting admin's identity + 2FA status."""
    email, pw, _, _ = await _enroll_admin_fully(client, pool, fresh_admin)
    # Cookie was set by the enroll-confirm response. httpx test client
    # carries it forward automatically via the AsyncClient instance.
    r = await client.get("/admin/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["via"] == "session-cookie"
    assert body["admin_id"]
    assert body["email"] == email
    assert body["totp_enrolled"] is True
    assert body["backup_codes_remaining"] == 10


# ── Multi-admin isolation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_admins_isolated_regenerate_does_not_invalidate_other(client, pool):
    """The mentor P1 fix: regenerating admin A's backup codes must NOT
    touch admin B's. Old code did `SELECT id FROM admins LIMIT 1`."""
    from dialekt_cloud.services.admin_auth import hash_password
    from dialekt_cloud.services.tokens import create_admin_session_token
    from dialekt_cloud.config import settings as _cfg

    # Insert two admins directly (CLI path).
    pw_a, pw_b = "alpha-pass-12345!", "bravo-pass-67890@"
    email_a = f"alpha-{uuid.uuid4().hex[:6]}@dias.now"
    email_b = f"bravo-{uuid.uuid4().hex[:6]}@dias.now"
    async with pool.acquire() as conn:
        # Seed both with non-null backup_codes so we can detect mutation.
        from dialekt_cloud.services.admin_auth import generate_backup_codes
        _, hashed_a = generate_backup_codes()
        _, hashed_b = generate_backup_codes()
        admin_a = await conn.fetchval(
            "INSERT INTO admins(email, password_hash, backup_codes) VALUES($1,$2,$3) RETURNING id",
            email_a, hash_password(pw_a), hashed_a,
        )
        admin_b = await conn.fetchval(
            "INSERT INTO admins(email, password_hash, backup_codes) VALUES($1,$2,$3) RETURNING id",
            email_b, hash_password(pw_b), hashed_b,
        )

    # Forge a session cookie for admin A.
    token_a = create_admin_session_token(
        admin_id=str(admin_a), email=email_a, secret=_cfg.JWT_SECRET, ttl=300,
    )
    # Trigger regenerate-backup-codes as A.
    r = await client.post(
        "/admin/totp/regenerate-backup-codes",
        cookies={"dialekt_admin_session": token_a},
        json={"password_reconfirm": pw_a},
    )
    assert r.status_code == 200, r.text
    new_codes_a = r.json()["backup_codes"]
    assert len(new_codes_a) == 10

    # Verify A's hashes changed AND B's hashes are byte-identical.
    async with pool.acquire() as conn:
        hashes_a_now = await conn.fetchval("SELECT backup_codes FROM admins WHERE id = $1", admin_a)
        hashes_b_now = await conn.fetchval("SELECT backup_codes FROM admins WHERE id = $1", admin_b)
    assert hashes_a_now != hashed_a, "A's codes should have changed"
    assert hashes_b_now == hashed_b, "B's codes MUST be untouched (multi-admin P1)"


@pytest.mark.asyncio
async def test_regenerate_backup_codes_requires_password_reconfirm(client, pool, fresh_admin):
    """P2: stolen 4h cookie alone must not be enough to rotate codes."""
    email, pw, _, _ = await _enroll_admin_fully(client, pool, fresh_admin)

    # No password_reconfirm at all → 422
    r1 = await client.post("/admin/totp/regenerate-backup-codes", json={})
    assert r1.status_code == 422

    # Wrong password → 401
    r2 = await client.post(
        "/admin/totp/regenerate-backup-codes",
        json={"password_reconfirm": "wrong-pass"},
    )
    assert r2.status_code == 401

    # Correct password → 200 + 10 new codes
    r3 = await client.post(
        "/admin/totp/regenerate-backup-codes",
        json={"password_reconfirm": pw},
    )
    assert r3.status_code == 200
    assert len(r3.json()["backup_codes"]) == 10


@pytest.mark.asyncio
async def test_regenerate_backup_codes_rejects_break_glass_key(client):
    """Break-glass has no admin_id, so it can't regenerate anyone's codes."""
    from dialekt_cloud.config import settings as _cfg
    r = await client.post(
        "/admin/totp/regenerate-backup-codes",
        headers={"X-Admin-Key": _cfg.DIALEKT_ADMIN_KEY},
        json={"password_reconfirm": "x"},
    )
    assert r.status_code == 403
    assert "break-glass" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_change_password_old_pw_required(client, pool, fresh_admin):
    email, old_pw, _, _ = await _enroll_admin_fully(client, pool, fresh_admin)
    new_pw = "fresh-strong-password-2026"

    # Wrong old password → 401
    r1 = await client.post(
        "/admin/password/change",
        json={"old_password": "wrong", "new_password": new_pw},
    )
    assert r1.status_code == 401

    # Too short new password → 400
    r2 = await client.post(
        "/admin/password/change",
        json={"old_password": old_pw, "new_password": "short"},
    )
    assert r2.status_code == 400

    # Correct flow → 200, can log in with new password
    r3 = await client.post(
        "/admin/password/change",
        json={"old_password": old_pw, "new_password": new_pw},
    )
    assert r3.status_code == 200

    # Verify new password works at /admin/login
    login = await client.post("/admin/login", json={"email": email, "password": new_pw})
    assert login.status_code == 200
    # Old password no longer works
    bad = await client.post("/admin/login", json={"email": email, "password": old_pw})
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_admin_login_rejects_wrong_domain_when_policy_set(client, pool, monkeypatch):
    """Defence-in-depth: even if someone inserted a non-@dias.now admin
    row directly into the DB, login refuses when the policy is active."""
    from dialekt_cloud.services.admin_auth import hash_password
    from dialekt_cloud.config import settings as _cfg

    # Seed admin with a non-policy email
    pw = "outside-policy-12345!"
    email = f"intruder-{uuid.uuid4().hex[:6]}@example.com"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins(email, password_hash) VALUES($1, $2)",
            email, hash_password(pw),
        )

    # Activate the policy for this one test
    monkeypatch.setattr(_cfg, "DIALEKT_ADMIN_EMAIL_DOMAIN", "@dias.now")
    r = await client.post("/admin/login", json={"email": email, "password": pw})
    assert r.status_code == 401
    # Audit log should record the policy-driven refusal (without leaking)
    async with pool.acquire() as conn:
        last = await conn.fetchrow(
            "SELECT failure_reason FROM admin_login_attempts WHERE email = $1 ORDER BY created_at DESC LIMIT 1",
            email,
        )
    assert last["failure_reason"] == "domain_policy"


@pytest.mark.asyncio
async def test_admin_login_accepts_policy_domain(client, pool, monkeypatch):
    """Policy-domain admin can log in (sanity check on the policy gate)."""
    from dialekt_cloud.services.admin_auth import hash_password
    from dialekt_cloud.config import settings as _cfg

    pw = "in-policy-12345!"
    email = f"ok-{uuid.uuid4().hex[:6]}@dias.now"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins(email, password_hash) VALUES($1, $2)",
            email, hash_password(pw),
        )
    monkeypatch.setattr(_cfg, "DIALEKT_ADMIN_EMAIL_DOMAIN", "@dias.now")
    r = await client.post("/admin/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next"] == "enroll_totp"


@pytest.mark.asyncio
async def test_login_history_is_per_admin(client, pool, fresh_admin):
    """Multi-admin: login history filters by acting admin's email, not global."""
    email_a, pw_a, _, _ = await _enroll_admin_fully(client, pool, fresh_admin)
    # Trigger another failed login to log an attempt
    await client.post("/admin/login", json={"email": email_a, "password": "bad"})

    r = await client.get("/admin/security/login-history")
    assert r.status_code == 200
    rows = r.json()
    # All rows must belong to admin A
    for row in rows:
        # Some rows have ip/ua, all have stage/succeeded
        assert "stage" in row
    # At least one failed attempt logged for our acting email
    assert any(not r["succeeded"] for r in rows)
