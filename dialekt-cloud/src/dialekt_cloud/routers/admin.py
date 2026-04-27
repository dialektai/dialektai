"""Founder-only admin API: tenant CRUD, invoice, activation, auth."""
import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import settings
from ..services.invoice import generate_pdf, seller_from_env
from ..services.tokens import generate_license_key

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


# ─── Auth ────────────────────────────────────────────────────────────────────
#
# Three accepted paths (in order tried):
#  1. X-Admin-Key header == DIALEKT_ADMIN_KEY → break-glass. Per
#     admin_2fa_DESIGN: this path NEVER mints a session cookie, NEVER
#     resolves to a specific admin_id (because the env key isn't owned by
#     anyone). Endpoints that need an admin_id must reject break-glass.
#  2. dialekt_admin_session cookie → daily auth (issued only after
#     email + password + TOTP via /admin/login flow). Cookie payload
#     carries admin_id + email — multi-admin ready.
#  3. Authorization: Bearer <session_token> — same shape as cookie, for
#     CLI / API clients. Same payload semantics.
SESSION_COOKIE_NAME = "dialekt_admin_session"


class AdminContext:
    """Resolved admin auth context. ``admin_id`` is None for break-glass
    (env-key) — endpoints that need an identified admin must reject it."""
    __slots__ = ("via", "admin_id", "email")

    def __init__(self, via: str, admin_id: str | None = None, email: str | None = None):
        self.via = via
        self.admin_id = admin_id
        self.email = email


def _require_admin(request: Request) -> AdminContext:
    admin_key = request.headers.get("X-Admin-Key", "")
    if admin_key and admin_key == settings.DIALEKT_ADMIN_KEY:
        ctx = AdminContext(via="break-glass-key")
        request.state.admin_auth_via = ctx.via
        request.state.admin_ctx = ctx
        return ctx
    from ..services.tokens import verify_admin_session_token
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        payload = verify_admin_session_token(cookie_token, settings.JWT_SECRET)
        if payload:
            ctx = AdminContext(via="session-cookie",
                               admin_id=payload["admin_id"], email=payload.get("email"))
            request.state.admin_auth_via = ctx.via
            request.state.admin_ctx = ctx
            return ctx
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        payload = verify_admin_session_token(auth[7:], settings.JWT_SECRET)
        if payload:
            ctx = AdminContext(via="bearer",
                               admin_id=payload["admin_id"], email=payload.get("email"))
            request.state.admin_auth_via = ctx.via
            request.state.admin_ctx = ctx
            return ctx
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_identified_admin(ctx: AdminContext = Depends(_require_admin)) -> AdminContext:
    """Like _require_admin, but rejects break-glass (no resolvable admin_id).
    Use on endpoints that mutate the acting admin's own state."""
    if not ctx.admin_id:
        raise HTTPException(
            status_code=403,
            detail="This endpoint requires a logged-in admin (break-glass key not allowed here)",
        )
    return ctx


def get_pool(request: Request):
    return request.app.state.pool


def get_email_service(request: Request):
    return request.app.state.email


# ─── Schemas ─────────────────────────────────────────────────────────────────

class CreateTenantRequest(BaseModel):
    company_name: str
    admin_email: str
    plan: str = "team"
    seats: int = 3
    expiration_months: int | None = None
    notes: str | None = None


class UpdateTenantRequest(BaseModel):
    plan: str | None = None
    seats: int | None = None
    status: str | None = None
    notes: str | None = None
    expiration_months: int | None = None


class GenerateInvoiceRequest(BaseModel):
    amount_kzt: float
    period_months: int = 1
    company_address: str | None = None
    notes: str | None = None


# ─── Endpoints ───────────────────────────────────────────────────────────────

# ─── Login flow (email + password → TOTP → cookie) ──────────────────────────


class LoginPasswordRequest(BaseModel):
    email: str
    password: str


class LoginTotpRequest(BaseModel):
    challenge_token: str
    code: str
    is_backup_code: bool = False


class EnrollTotpRequest(BaseModel):
    challenge_token: str
    password_reconfirm: str


class EnrollTotpConfirmRequest(BaseModel):
    challenge_token: str
    code: str


# Lockout knobs — env-overridable for tests.
import os as _os
LOCKOUT_BURST_COUNT = int(_os.environ.get("DIALEKT_ADMIN_LOCKOUT_BURST", "3"))
LOCKOUT_BURST_MIN = int(_os.environ.get("DIALEKT_ADMIN_LOCKOUT_BURST_MIN", "15"))
LOCKOUT_HARD_COUNT = int(_os.environ.get("DIALEKT_ADMIN_LOCKOUT_HARD", "6"))
LOCKOUT_HARD_HOURS = int(_os.environ.get("DIALEKT_ADMIN_LOCKOUT_HARD_HOURS", "1"))


async def _log_attempt(conn, *, email, ip, ua, stage, succeeded, reason=None):
    await conn.execute(
        """
        INSERT INTO admin_login_attempts(email, ip, user_agent, stage, succeeded, failure_reason)
        VALUES($1,$2,$3,$4,$5,$6)
        """,
        email, ip, ua, stage, succeeded, reason,
    )


def _admin_email_passes_domain_policy(email: str) -> bool:
    """True if the email satisfies the DIALEKT_ADMIN_EMAIL_DOMAIN policy
    (or if no policy is set). Defence-in-depth alongside the CLI gate —
    catches the case where someone inserts an admin row directly via SQL
    but has the wrong domain."""
    domain = (settings.DIALEKT_ADMIN_EMAIL_DOMAIN or "").strip().lower()
    return not domain or email.lower().endswith(domain)


@router.post("/login")
async def admin_login(
    body: LoginPasswordRequest,
    request: Request,
    pool=Depends(get_pool),
    email_svc=Depends(get_email_service),
):
    """Stage 1: email + password. On success, issue a 5min challenge_token
    for the TOTP step. Lockout after 3/15min and 6/1h failures."""
    from ..services.admin_auth import verify_password, issue_challenge

    ip = request.client.host if request.client else "0.0.0.0"
    ua = request.headers.get("user-agent", "")[:500]
    email = body.email.strip().lower()

    if not _admin_email_passes_domain_policy(email):
        # Don't leak that the admin doesn't exist vs. has wrong domain —
        # use the same 401 + "Invalid email or password" as bad creds.
        async with pool.acquire() as conn:
            await _log_attempt(conn, email=email, ip=ip, ua=ua, stage="password",
                               succeeded=False, reason="domain_policy")
        raise HTTPException(401, "Invalid email or password")

    async with pool.acquire() as conn:
        admin = await conn.fetchrow(
            """
            SELECT id, email, password_hash, totp_secret_encrypted, totp_enrolled_at,
                   failed_attempts, locked_until
            FROM admins WHERE email = $1
            """,
            email,
        )
        if not admin:
            await _log_attempt(conn, email=email, ip=ip, ua=ua, stage="password",
                               succeeded=False, reason="unknown_email")
            raise HTTPException(401, "Invalid email or password")

        # Lockout check (locked_until in the future = blocked)
        if admin["locked_until"] and admin["locked_until"].replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
            await _log_attempt(conn, email=email, ip=ip, ua=ua, stage="password",
                               succeeded=False, reason="locked_out")
            raise HTTPException(429, "Account temporarily locked. Try again later.")

        if not verify_password(body.password, admin["password_hash"]):
            new_fails = (admin["failed_attempts"] or 0) + 1
            lock_for = None
            crossed_burst = (admin["failed_attempts"] or 0) < LOCKOUT_BURST_COUNT <= new_fails
            crossed_hard  = (admin["failed_attempts"] or 0) < LOCKOUT_HARD_COUNT  <= new_fails
            if new_fails >= LOCKOUT_HARD_COUNT:
                lock_for = datetime.now(timezone.utc) + timedelta(hours=LOCKOUT_HARD_HOURS)
            elif new_fails >= LOCKOUT_BURST_COUNT:
                lock_for = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_BURST_MIN)
            await conn.execute(
                "UPDATE admins SET failed_attempts = $1, locked_until = $2 WHERE id = $3",
                new_fails, lock_for, admin["id"],
            )
            await _log_attempt(conn, email=email, ip=ip, ua=ua, stage="password",
                               succeeded=False, reason="bad_password")
            # Security alert: account just got locked. Notify the affected
            # admin AND broadcast to other admins (attack-in-progress signal
            # — they should know their colleague is locked out so they can
            # cross-check via the dashboard or pick up on-call duties).
            if crossed_burst or crossed_hard:
                from ..services.email import EmailService  # for type only
                # Get all admin emails for broadcast
                broadcast_rows = await conn.fetch("SELECT email FROM admins WHERE email != $1", admin["email"])
                broadcast_to = [r["email"] for r in broadcast_rows]
                lock_minutes = LOCKOUT_HARD_HOURS * 60 if crossed_hard else LOCKOUT_BURST_MIN
                # Notify primary affected
                try:
                    await email_svc.send_admin_security_alert(
                        to=admin["email"],
                        full_name=admin["email"],
                        kind="account_locked", ip=ip, user_agent=ua,
                        when_human=datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
                        extra={"failed_attempts": new_fails, "locked_minutes": lock_minutes},
                    )
                except Exception as exc:
                    logger.warning("account_locked alert (self) failed: %s", exc)
                # Broadcast to other admins
                if broadcast_to:
                    try:
                        await email_svc.send_admin_security_alert(
                            to=broadcast_to,
                            full_name="team",
                            kind="account_locked", ip=ip, user_agent=ua,
                            when_human=datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
                            extra={
                                "failed_attempts": new_fails,
                                "locked_minutes": lock_minutes,
                                "affected_email": admin["email"],
                                "broadcast": True,
                            },
                        )
                    except Exception as exc:
                        logger.warning("account_locked broadcast failed: %s", exc)
            raise HTTPException(401, "Invalid email or password")

        # Password OK — log success, issue challenge for next stage.
        await _log_attempt(conn, email=email, ip=ip, ua=ua, stage="password", succeeded=True)
        # Don't reset failed_attempts yet — only after the TOTP stage succeeds.

        next_stage = "totp_challenge" if admin["totp_enrolled_at"] else "enroll_totp"
        token = issue_challenge(str(admin["id"]), next_stage)
        return {"next": next_stage, "challenge_token": token}


@router.post("/login/totp")
async def admin_login_totp(
    body: LoginTotpRequest,
    request: Request,
    pool=Depends(get_pool),
):
    """Stage 2 (enrolled path): challenge_token + TOTP code. Issues session
    cookie on success. Falls through to backup-code path if is_backup_code=True."""
    from ..services.admin_auth import (
        verify_challenge, verify_totp, decrypt_totp_secret, consume_backup_code,
    )
    from ..services.tokens import create_admin_session_token

    ip = request.client.host if request.client else "0.0.0.0"
    ua = request.headers.get("user-agent", "")[:500]

    challenge = verify_challenge(body.challenge_token, "totp_challenge")
    if not challenge:
        async with pool.acquire() as conn:
            await _log_attempt(conn, email=None, ip=ip, ua=ua,
                               stage="totp" if not body.is_backup_code else "backup_code",
                               succeeded=False, reason="bad_challenge")
        raise HTTPException(401, "Challenge token invalid or expired")

    async with pool.acquire() as conn:
        admin = await conn.fetchrow(
            "SELECT id, email, totp_secret_encrypted, backup_codes FROM admins WHERE id = $1",
            challenge.admin_id,
        )
        if not admin:
            raise HTTPException(404, "Admin not found")

        stage = "backup_code" if body.is_backup_code else "totp"

        if body.is_backup_code:
            matched, remaining = consume_backup_code(body.code, list(admin["backup_codes"] or []))
            if not matched:
                await _log_attempt(conn, email=admin["email"], ip=ip, ua=ua,
                                   stage=stage, succeeded=False, reason="bad_code")
                raise HTTPException(401, "Invalid backup code")
            await conn.execute(
                "UPDATE admins SET backup_codes = $1 WHERE id = $2",
                remaining, admin["id"],
            )
        else:
            secret = decrypt_totp_secret(admin["totp_secret_encrypted"])
            if not verify_totp(secret, body.code):
                await _log_attempt(conn, email=admin["email"], ip=ip, ua=ua,
                                   stage=stage, succeeded=False, reason="bad_code")
                raise HTTPException(401, "Invalid TOTP code")

        # Success — clear lockout, set last_login, mint session cookie.
        await conn.execute(
            "UPDATE admins SET failed_attempts = 0, locked_until = NULL, "
            "last_login_at = now(), last_login_ip = $1 WHERE id = $2",
            ip, admin["id"],
        )
        await _log_attempt(conn, email=admin["email"], ip=ip, ua=ua, stage=stage, succeeded=True)

    token = create_admin_session_token(
        admin_id=str(admin["id"]),
        email=admin["email"],
        secret=settings.JWT_SECRET,
        ttl=4 * 3600,
    )
    body_payload = {"ok": True}
    if body.is_backup_code:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT backup_codes FROM admins WHERE id = $1", admin["id"])
        body_payload["backup_codes_remaining"] = len(row["backup_codes"] or [])
    response = Response(content=json.dumps(body_payload), media_type="application/json")
    response.set_cookie(
        key=SESSION_COOKIE_NAME, value=token,
        httponly=True, secure=settings.ENV != "development",
        samesite="strict", max_age=4 * 3600, path="/",
    )
    return response


@router.post("/login/enroll-totp")
async def admin_enroll_totp(
    body: EnrollTotpRequest,
    request: Request,
    pool=Depends(get_pool),
):
    """First-login path: returns provisioning URI + QR. password_reconfirm
    guards against an attacker hijacking a stolen challenge token."""
    from ..services.admin_auth import (
        verify_challenge, verify_password, new_totp_secret,
        provisioning_uri, qr_svg,
    )

    challenge = verify_challenge(body.challenge_token, "enroll_totp")
    if not challenge:
        raise HTTPException(401, "Challenge token invalid or expired")

    async with pool.acquire() as conn:
        admin = await conn.fetchrow("SELECT id, email, password_hash FROM admins WHERE id = $1",
                                    challenge.admin_id)
        if not admin or not verify_password(body.password_reconfirm, admin["password_hash"]):
            raise HTTPException(401, "Password reconfirmation failed")

    secret = new_totp_secret()
    return {
        "secret": secret,
        "provisioning_uri": provisioning_uri(secret, admin["email"]),
        "qr_svg": qr_svg(secret, admin["email"]),
    }


class EnrollTotpConfirmFullRequest(EnrollTotpConfirmRequest):
    secret: str  # the secret returned by /enroll-totp; client must echo


@router.post("/login/enroll-totp/confirm")
async def admin_enroll_totp_confirm(
    body: EnrollTotpConfirmFullRequest,
    request: Request,
    pool=Depends(get_pool),
    email_svc=Depends(get_email_service),
):
    """Confirm enrollment: verify the user can actually generate codes from
    their authenticator. On success, persist + return 10 backup codes ONCE."""
    from ..services.admin_auth import (
        verify_challenge, verify_totp, encrypt_totp_secret, generate_backup_codes,
    )
    from ..services.tokens import create_admin_session_token

    challenge = verify_challenge(body.challenge_token, "enroll_totp")
    if not challenge:
        raise HTTPException(401, "Challenge token invalid or expired")

    if not verify_totp(body.secret, body.code):
        raise HTTPException(401, "Code did not match — re-scan the QR and try again")

    plaintext_codes, hashed_codes = generate_backup_codes()
    enc = encrypt_totp_secret(body.secret)

    ip = request.client.host if request.client else "0.0.0.0"
    ua = request.headers.get("user-agent", "")[:500]
    async with pool.acquire() as conn:
        # Detect re-enrollment via audit log: if this admin has any prior
        # successful 'enrollment'-reason row, this is a re-enroll (security
        # event). Reading from the totp_enrolled_at column is NOT enough
        # because `dialekt-admin admin reset-2fa` clears it before re-enroll
        # so the column would always look like a first-time enrollment.
        admin_email_for_history = await conn.fetchval(
            "SELECT email FROM admins WHERE id = $1", challenge.admin_id,
        )
        was_enrolled = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM admin_login_attempts
                WHERE email = $1 AND stage = 'totp' AND succeeded = TRUE
                  AND failure_reason = 'enrollment'
            )
            """,
            admin_email_for_history,
        )
        await conn.execute(
            """
            UPDATE admins SET totp_secret_encrypted = $1, totp_enrolled_at = now(),
                              backup_codes = $2, backup_codes_generated_at = now(),
                              last_login_at = now(), last_login_ip = $3,
                              failed_attempts = 0, locked_until = NULL
            WHERE id = $4
            """,
            enc, hashed_codes, ip, challenge.admin_id,
        )
        admin_email = await conn.fetchval("SELECT email FROM admins WHERE id = $1", challenge.admin_id)
        await _log_attempt(conn, email=admin_email, ip=ip,
                           ua=ua,
                           stage="totp", succeeded=True, reason="enrollment")

    token = create_admin_session_token(
        admin_id=str(challenge.admin_id),
        email=admin_email,
        secret=settings.JWT_SECRET,
        ttl=4 * 3600,
    )
    response = Response(
        content=json.dumps({"ok": True, "backup_codes": plaintext_codes}),
        media_type="application/json",
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME, value=token,
        httponly=True, secure=settings.ENV != "development",
        samesite="strict", max_age=4 * 3600, path="/",
    )
    # Security alert ONLY on re-enrollment (after CLI reset). First-time
    # enrollment is part of normal onboarding — no alert needed.
    if was_enrolled:
        try:
            await email_svc.send_admin_security_alert(
                to=admin_email, full_name=admin_email,
                kind="totp_enrolled", ip=ip, user_agent=ua,
                when_human=datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
            )
        except Exception as exc:
            logger.warning("totp_enrolled alert failed: %s", exc)
    return response


# ── Authenticated admin self-service ────────────────────────────────────────


class RegenerateBackupCodesRequest(BaseModel):
    password_reconfirm: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.get("/me")
async def admin_me(ctx: AdminContext = Depends(_require_admin), pool=Depends(get_pool)):
    """Who am I? Used by the dashboard to show the current admin's email
    and to detect break-glass-key sessions (admin_id is null in that case)."""
    if ctx.admin_id is None:
        return {"via": ctx.via, "admin_id": None, "email": None}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT email, last_login_at, last_login_ip, totp_enrolled_at,
                   backup_codes_generated_at,
                   array_length(backup_codes, 1) AS backup_codes_remaining
            FROM admins WHERE id = $1
            """,
            ctx.admin_id,
        )
    if not row:
        # Cookie references a deleted admin — invalidate.
        raise HTTPException(401, "Admin no longer exists")
    return {
        "via": ctx.via,
        "admin_id": ctx.admin_id,
        "email": row["email"],
        "last_login_at": row["last_login_at"].isoformat() if row["last_login_at"] else None,
        "last_login_ip": row["last_login_ip"],
        "totp_enrolled": row["totp_enrolled_at"] is not None,
        "backup_codes_remaining": row["backup_codes_remaining"] or 0,
        "backup_codes_generated_at": row["backup_codes_generated_at"].isoformat()
            if row["backup_codes_generated_at"] else None,
    }


@router.post("/totp/regenerate-backup-codes")
async def admin_regenerate_backup_codes(
    body: RegenerateBackupCodesRequest,
    request: Request,
    pool=Depends(get_pool),
    email_svc=Depends(get_email_service),
    ctx: AdminContext = Depends(_require_identified_admin),
):
    """Generate 10 fresh codes ONCE for the AUTHENTICATED admin (not LIMIT 1).

    Mirrors enroll-totp: requires password reconfirm even with valid cookie,
    so a stolen 4h cookie alone can't rotate codes silently."""
    from ..services.admin_auth import generate_backup_codes, verify_password

    ip = request.client.host if request.client else "0.0.0.0"
    ua = request.headers.get("user-agent", "")[:500]
    async with pool.acquire() as conn:
        admin = await conn.fetchrow(
            "SELECT id, email, password_hash FROM admins WHERE id = $1",
            ctx.admin_id,
        )
        if not admin:
            raise HTTPException(401, "Admin no longer exists")
        if not verify_password(body.password_reconfirm, admin["password_hash"]):
            await _log_attempt(conn, email=admin["email"], ip=ip, ua=ua,
                               stage="password", succeeded=False,
                               reason="regenerate_backup_codes_reconfirm")
            raise HTTPException(401, "Password reconfirmation failed")
        plaintext, hashed = generate_backup_codes()
        await conn.execute(
            """
            UPDATE admins SET backup_codes = $1, backup_codes_generated_at = now()
            WHERE id = $2
            """,
            hashed, admin["id"],
        )
        await conn.execute(
            "INSERT INTO founder_admin_log(action, details) VALUES('regenerate_backup_codes', $1::jsonb)",
            json.dumps({"admin_id": ctx.admin_id, "email": admin["email"], "ip": ip}),
        )
    # Security alert — fire-and-forget, don't block on email
    try:
        await email_svc.send_admin_security_alert(
            to=admin["email"], full_name=admin["email"],
            kind="backup_codes_regenerated", ip=ip, user_agent=ua,
            when_human=datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
        )
    except Exception as exc:
        logger.warning("backup_codes_regenerated alert failed: %s", exc)
    return {"backup_codes": plaintext}


@router.post("/password/change")
async def admin_change_password(
    body: ChangePasswordRequest,
    request: Request,
    pool=Depends(get_pool),
    email_svc=Depends(get_email_service),
    ctx: AdminContext = Depends(_require_identified_admin),
):
    """Change own password. Requires the current one (mirrors industry norm)."""
    from ..services.admin_auth import verify_password, hash_password

    if len(body.new_password) < 12:
        raise HTTPException(400, "New password must be at least 12 characters")

    ip = request.client.host if request.client else "0.0.0.0"
    ua = request.headers.get("user-agent", "")[:500]
    async with pool.acquire() as conn:
        admin = await conn.fetchrow(
            "SELECT id, email, password_hash FROM admins WHERE id = $1",
            ctx.admin_id,
        )
        if not admin:
            raise HTTPException(401, "Admin no longer exists")
        if not verify_password(body.old_password, admin["password_hash"]):
            await _log_attempt(conn, email=admin["email"], ip=ip, ua=ua,
                               stage="password", succeeded=False,
                               reason="change_password_old_mismatch")
            raise HTTPException(401, "Old password is incorrect")
        new_hash = hash_password(body.new_password)
        await conn.execute(
            "UPDATE admins SET password_hash = $1 WHERE id = $2",
            new_hash, admin["id"],
        )
        await conn.execute(
            "INSERT INTO founder_admin_log(action, details) VALUES('change_password', $1::jsonb)",
            json.dumps({"admin_id": ctx.admin_id, "email": admin["email"], "ip": ip}),
        )
    # Security alert — sent AFTER the change so the recipient can act if it
    # wasn't them. We deliberately send to the OLD email-on-record (which
    # IS the same as new — we don't allow email changes) so even if the
    # attacker stole a session and changed pw, the legit admin sees this.
    try:
        await email_svc.send_admin_security_alert(
            to=admin["email"], full_name=admin["email"],
            kind="password_changed", ip=ip, user_agent=ua,
            when_human=datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
        )
    except Exception as exc:
        logger.warning("password_changed alert failed: %s", exc)
    return {"ok": True}


@router.get("/security/login-history")
async def admin_login_history(
    pool=Depends(get_pool),
    ctx: AdminContext = Depends(_require_identified_admin),
):
    """Last 50 login attempts for the acting admin (multi-admin safe —
    filters by email rather than dumping the global table).

    NOTE: filters by email rather than admin_id because admin_login_attempts
    rows for the unknown-email failure case have email but no admin_id.
    Safe today because admins.email is UNIQUE; if email reuse across admin
    rows ever becomes possible, switch to admin_id with a JOIN."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT created_at, ip, user_agent, stage, succeeded, failure_reason
            FROM admin_login_attempts
            WHERE email = $1 ORDER BY created_at DESC LIMIT 50
            """,
            ctx.email,
        )
    return [
        {
            "at": r["created_at"].isoformat(),
            "ip": r["ip"],
            "user_agent": r["user_agent"],
            "stage": r["stage"],
            "succeeded": r["succeeded"],
            "failure_reason": r["failure_reason"],
        }
        for r in rows
    ]


@router.post("/logout")
async def admin_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/tenants")
async def list_tenants(
    status: str | None = Query(
        None,
        description="Filter by tenant status (draft / active / suspended). "
                    "Unknown values are rejected with 400.",
    ),
    pool=Depends(get_pool),
    _=Depends(_require_admin),
):
    _ALLOWED_STATUSES = {"draft", "active", "suspended"}
    if status is not None and status not in _ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(_ALLOWED_STATUSES)}",
        )

    async with pool.acquire() as conn:
        base_query = """
            SELECT t.*,
                   COUNT(DISTINCT tu.id) AS user_count,
                   COUNT(DISTINCT l.id) AS license_count
            FROM tenants t
            LEFT JOIN tenant_users tu ON tu.tenant_id = t.id
            LEFT JOIN licenses l ON l.tenant_id = t.id
            {where}
            GROUP BY t.id
            ORDER BY t.created_at DESC
        """
        if status is None:
            rows = await conn.fetch(base_query.format(where=""))
        else:
            rows = await conn.fetch(
                base_query.format(where="WHERE t.status = $1"),
                status,
            )
    return [dict(r) for r in rows]


@router.post("/tenants", status_code=201)
async def create_tenant(
    body: CreateTenantRequest,
    pool=Depends(get_pool),
    _=Depends(_require_admin),
):
    from datetime import timedelta
    expires_at = None
    if body.expiration_months:
        expires_at = datetime.now(timezone.utc) + timedelta(days=30 * body.expiration_months)

    async with pool.acquire() as conn:
        tenant_id = await conn.fetchval(
            """
            INSERT INTO tenants(company_name, name, admin_email, plan, seats_limit, status, notes, expires_at)
            VALUES($1,$2,$3,$4,$5,'draft',$6,$7) RETURNING id
            """,
            body.company_name, body.company_name, body.admin_email,
            body.plan, body.seats, body.notes, expires_at,
        )
        await conn.execute(
            "INSERT INTO founder_admin_log(action, details) VALUES('create_tenant', $1)",
            json.dumps({"tenant_id": str(tenant_id), "company": body.company_name}),
        )

    return {"tenant_id": str(tenant_id), "status": "draft"}


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, pool=Depends(get_pool), _=Depends(_require_admin)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tenants WHERE id = $1", tenant_id)
        if not row:
            raise HTTPException(status_code=404)
        users = await conn.fetch(
            "SELECT id, email, role, invited_at, invite_accepted_at FROM tenant_users WHERE tenant_id = $1",
            tenant_id,
        )
        invoices = await conn.fetch(
            "SELECT id, invoice_number, amount_kzt, issued_at, paid_at FROM invoices WHERE tenant_id = $1 ORDER BY issued_at DESC",
            tenant_id,
        )
        license_row = await conn.fetchrow(
            "SELECT license_key, activated_at, last_validated_at, active FROM licenses WHERE tenant_id = $1",
            tenant_id,
        )
    return {
        **dict(row),
        "users": [dict(u) for u in users],
        "invoices": [dict(i) for i in invoices],
        "license": dict(license_row) if license_row else None,
    }


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    body: UpdateTenantRequest,
    pool=Depends(get_pool),
    _=Depends(_require_admin),
):
    from datetime import timedelta
    updates = {}
    if body.plan is not None:
        updates["plan"] = body.plan
    if body.seats is not None:
        updates["seats_limit"] = body.seats
    if body.status is not None:
        updates["status"] = body.status
    if body.notes is not None:
        updates["notes"] = body.notes
    if body.expiration_months is not None:
        updates["expires_at"] = datetime.now(timezone.utc) + timedelta(days=30 * body.expiration_months)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
    values = list(updates.values())

    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE tenants SET {set_clause} WHERE id = $1",
            tenant_id, *values,
        )
        await conn.execute(
            "INSERT INTO founder_admin_log(action, details) VALUES('update_tenant', $1)",
            json.dumps({"tenant_id": tenant_id, "updates": list(updates.keys())}),
        )

    return {"updated": True}


@router.post("/tenants/{tenant_id}/invoice")
async def generate_invoice(
    tenant_id: str,
    body: GenerateInvoiceRequest,
    pool=Depends(get_pool),
    _=Depends(_require_admin),
):
    async with pool.acquire() as conn:
        tenant = await conn.fetchrow("SELECT * FROM tenants WHERE id = $1", tenant_id)
        if not tenant:
            raise HTTPException(status_code=404)

        # Sequential invoice number
        count = await conn.fetchval("SELECT COUNT(*) FROM invoices")
        year = datetime.now(timezone.utc).year
        invoice_number = f"INV-{year}-{int(count)+1:04d}"

        invoice_id = await conn.fetchval(
            """
            INSERT INTO invoices(tenant_id, invoice_number, amount_kzt, seats, plan, period_months, notes)
            VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id
            """,
            tenant_id, invoice_number, body.amount_kzt,
            tenant["seats_limit"], tenant["plan"], body.period_months, body.notes,
        )

    try:
        pdf_path = generate_pdf(
            invoice_number=invoice_number,
            company_name=tenant["company_name"],
            company_address=body.company_address,
            plan=tenant["plan"],
            seats=tenant["seats_limit"],
            period_months=body.period_months,
            amount_kzt=body.amount_kzt,
            seller=seller_from_env(),
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE invoices SET pdf_path = $1 WHERE id = $2",
                str(pdf_path), invoice_id,
            )
        pdf_available = True
    except Exception as exc:
        logger.warning("PDF generation failed: %s", exc)
        pdf_available = False
        pdf_path = None

    return {
        "invoice_id": str(invoice_id),
        "invoice_number": invoice_number,
        "pdf_available": pdf_available,
        "pdf_path": str(pdf_path) if pdf_path else None,
    }


@router.get("/invoices/{invoice_id}/download")
async def download_invoice(invoice_id: str, pool=Depends(get_pool), _=Depends(_require_admin)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT pdf_path, invoice_number FROM invoices WHERE id = $1", invoice_id)
    if not row or not row["pdf_path"]:
        raise HTTPException(status_code=404, detail="PDF not generated yet")
    from pathlib import Path
    pdf_path = Path(row["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file missing")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=f"{row['invoice_number']}.pdf")


@router.post("/tenants/{tenant_id}/activate")
async def activate_tenant(
    tenant_id: str,
    pool=Depends(get_pool),
    email_svc=Depends(get_email_service),
    _=Depends(_require_admin),
):
    async with pool.acquire() as conn:
        tenant = await conn.fetchrow("SELECT * FROM tenants WHERE id = $1", tenant_id)
        if not tenant:
            raise HTTPException(status_code=404)
        if tenant["status"] == "active":
            raise HTTPException(status_code=409, detail="Tenant already active")

        # Check for existing license
        existing = await conn.fetchrow("SELECT license_key FROM licenses WHERE tenant_id = $1", tenant_id)
        if existing:
            license_key = existing["license_key"]
        else:
            license_key = generate_license_key()
            await conn.execute(
                "INSERT INTO licenses(tenant_id, license_key) VALUES($1,$2)",
                tenant_id, license_key,
            )

        await conn.execute(
            "UPDATE tenants SET status = 'active' WHERE id = $1", tenant_id
        )

        # Create admin user record
        await conn.execute(
            """
            INSERT INTO tenant_users(tenant_id, email, role, invite_accepted_at)
            VALUES($1,$2,'admin',now())
            ON CONFLICT(tenant_id, email) DO NOTHING
            """,
            tenant_id, tenant["admin_email"],
        )

        await conn.execute(
            "INSERT INTO founder_admin_log(action, details) VALUES('activate_tenant', $1)",
            json.dumps({"tenant_id": tenant_id}),
        )

    email_sent = await email_svc.send_license_activated(
        to=tenant["admin_email"],
        license_key=license_key,
        company_name=tenant["company_name"],
        plan=tenant["plan"],
        seats=tenant["seats_limit"],
        landing_url=settings.LANDING_URL,
        locale=tenant["locale"] or "en",
    )

    return {
        "activated": True,
        "license_key": license_key,
        "email_sent": email_sent,
        "admin_email": tenant["admin_email"],
    }


class ExtendTenantRequest(BaseModel):
    days: int  # add this many days to expires_at (positive); use negative to shrink
    plan: str | None = None  # optional: bump plan as part of extension
    seats_limit: int | None = None  # optional: bump seats too
    reason: str  # required for audit log; keep terse


@router.post("/tenants/{tenant_id}/extend")
async def extend_tenant(
    tenant_id: str,
    body: ExtendTenantRequest,
    pool=Depends(get_pool),
    email_svc=Depends(get_email_service),
    _=Depends(_require_admin),
):
    """Extend (or shrink) a tenant's expiry. Combined endpoint replaces the
    proposed split of /extend + /grant-free-year per mentor verdict —
    `days=365` does the same thing.
    """
    if body.days == 0:
        raise HTTPException(400, "days must be non-zero")
    if not body.reason or len(body.reason.strip()) < 3:
        raise HTTPException(400, "reason required for audit log")

    async with pool.acquire() as conn:
        tenant = await conn.fetchrow("SELECT id, expires_at, plan, seats_limit, status, admin_email, locale FROM tenants WHERE id = $1", tenant_id)
        if not tenant:
            raise HTTPException(404)

        # Anchor the new expiry at the LATER of (now, current expires_at).
        # Otherwise extending an already-expired trial by 30 days would
        # leave it expired.
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        current = tenant["expires_at"].replace(tzinfo=timezone.utc) if tenant["expires_at"] else now
        anchor = max(now, current)
        new_expires = anchor + timedelta(days=body.days)

        new_plan = body.plan or tenant["plan"]
        new_seats = body.seats_limit if body.seats_limit is not None else tenant["seats_limit"]
        # If we're extending past now, ensure status is active (was likely 'trial' or 'expired')
        new_status = "active" if new_expires > now and tenant["status"] != "active" else tenant["status"]

        await conn.execute(
            """
            UPDATE tenants
            SET expires_at = $1, plan = $2, seats_limit = $3, status = $4
            WHERE id = $5
            """,
            new_expires, new_plan, new_seats, new_status, tenant_id,
        )

        # If trial just got converted to paid, stamp the conversion time
        if tenant["status"] == "trial" and new_status == "active":
            await conn.execute(
                "UPDATE tenants SET trial_converted_at = now() WHERE id = $1 AND trial_converted_at IS NULL",
                tenant_id,
            )

        await conn.execute(
            "INSERT INTO founder_admin_log(action, details) VALUES('extend_tenant', $1)",
            json.dumps({
                "tenant_id": tenant_id,
                "days": body.days,
                "plan": new_plan,
                "seats_limit": new_seats,
                "previous_expires_at": current.isoformat(),
                "new_expires_at": new_expires.isoformat(),
                "reason": body.reason,
            }),
        )

        # Reset expiring-notice dedup so a future re-extension fires the
        # T-7/T-3 emails again. Without this, a tenant extended for a year
        # would silently miss the next year's reminder pass.
        await conn.execute(
            "UPDATE tenants SET expiring_notices_sent = '{}' WHERE id = $1",
            tenant_id,
        )

        # Pull customer name for the email greeting
        full_name_row = await conn.fetchrow(
            "SELECT full_name FROM tenant_users WHERE tenant_id = $1 AND email = $2 LIMIT 1",
            tenant_id, tenant["admin_email"],
        )

    # Notify the customer that they got more time / a comp year. Failure
    # to send the email doesn't roll back the extension.
    try:
        await email_svc.send_license_extended(
            to=tenant["admin_email"],
            full_name=(full_name_row["full_name"] if full_name_row else tenant["admin_email"]) or tenant["admin_email"],
            plan=new_plan,
            seats_limit=new_seats,
            new_expires_at_human=new_expires.strftime("%d %b %Y"),
            days_added=body.days,
            landing_url=settings.LANDING_URL,
            locale=tenant["locale"] or "en",
        )
    except Exception as exc:
        logger.warning("license-extended email failed for tenant %s: %s", tenant_id, exc)

    return {
        "ok": True,
        "tenant_id": tenant_id,
        "expires_at": new_expires.isoformat(),
        "plan": new_plan,
        "seats_limit": new_seats,
        "status": new_status,
    }


@router.get("/stats")
async def get_stats(pool=Depends(get_pool), _=Depends(_require_admin)):
    async with pool.acquire() as conn:
        total_tenants = await conn.fetchval("SELECT COUNT(*) FROM tenants")
        active_tenants = await conn.fetchval("SELECT COUNT(*) FROM tenants WHERE status = 'active'")
        draft_tenants = await conn.fetchval("SELECT COUNT(*) FROM tenants WHERE status = 'draft'")
        total_users = await conn.fetchval("SELECT COUNT(*) FROM tenant_users WHERE invite_accepted_at IS NOT NULL")
        total_agents = await conn.fetchval("SELECT COUNT(*) FROM agent_templates")
        total_invoices = await conn.fetchval("SELECT COUNT(*) FROM invoices")
        paid_invoices = await conn.fetchval("SELECT COUNT(*) FROM invoices WHERE paid_at IS NOT NULL")

    return {
        "tenants": {
            "total": total_tenants,
            "active": active_tenants,
            "draft": draft_tenants,
        },
        "users": {"total": total_users},
        "agents": {"total": total_agents},
        "invoices": {"total": total_invoices, "paid": paid_invoices},
    }


@router.get("/tenants/{tenant_id}/users")
async def list_tenant_users(tenant_id: str, pool=Depends(get_pool), _=Depends(_require_admin)):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, role, invited_at, invite_accepted_at FROM tenant_users WHERE tenant_id = $1",
            tenant_id,
        )
    return [dict(r) for r in rows]


@router.delete("/users/{user_id}")
async def remove_user(user_id: str, pool=Depends(get_pool), _=Depends(_require_admin)):
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM tenant_users WHERE id = $1 RETURNING id", user_id
        )
    if not deleted:
        raise HTTPException(status_code=404)
    return {"deleted": str(deleted)}
