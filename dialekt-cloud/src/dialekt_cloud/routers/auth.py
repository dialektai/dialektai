"""Tenant-facing authentication: license validation, invites, token refresh, self-serve signup."""
import logging
import secrets as _secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from ..config import settings
from ..services.tokens import (
    create_bearer_token,
    generate_invite_token,
    generate_license_key,
    verify_bearer_token,
)


# Self-serve signup tuning. Mentor verdict locked these values:
# - 1 successful signup per email per lifetime (no farming via email reuse)
# - 3 attempts per IP per 7 rolling days (catches bot rings, allows
#   legit shared-office IPs to retry after typos)
# - 30-day trial, 3 seats — matches the Starter plan's minimum seat count
#   so conversion is "just pay, same shape" rather than "rebuild your team"
#
# All overridable via env so tests + load tests can relax limits without
# patching code.
import os as _os
SIGNUP_IP_LIMIT = int(_os.environ.get("DIALEKT_SIGNUP_IP_LIMIT", "3"))
SIGNUP_IP_WINDOW_DAYS = int(_os.environ.get("DIALEKT_SIGNUP_IP_WINDOW_DAYS", "7"))
TRIAL_DAYS = int(_os.environ.get("DIALEKT_TRIAL_DAYS", "30"))
TRIAL_SEATS = int(_os.environ.get("DIALEKT_TRIAL_SEATS", "3"))

# Authoritative ToS / Privacy Policy version strings. Bump these when the
# legal docs change — clients submit the version they saw, server logs both
# (client-claimed and server-current). Mismatch is logged but not rejected
# — the user still consented to the version they saw on their screen.
# Source documents: docs/legal/terms-of-service-{en,ru}.md,
#                   docs/legal/privacy-policy-{en,ru}.md
TOS_VERSION = _os.environ.get("DIALEKT_TOS_VERSION", "1.0")
PRIVACY_VERSION = _os.environ.get("DIALEKT_PRIVACY_VERSION", "1.0")

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class ValidateLicenseRequest(BaseModel):
    license_key: str
    machine_id: str = ""


class ValidateLicenseResponse(BaseModel):
    valid: bool
    tenant_id: str | None = None
    plan: str | None = None
    seats_limit: int | None = None
    expires_at: str | None = None
    user_role: str | None = None
    bearer_token: str | None = None


class InviteRequest(BaseModel):
    email: str
    role: str = "user"


class AcceptInviteRequest(BaseModel):
    invite_token: str
    machine_id: str = ""


# Self-serve signup. Four required fields per mentor verdict — anything
# beyond that gets captured in the desktop first-run wizard.
class SignupRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=120)
    intended_use: str = Field(..., min_length=10, max_length=500)
    country: str = Field(..., min_length=2, max_length=2)  # ISO 3166-1 alpha-2
    signup_source: str | None = Field(default=None, max_length=80)
    accept_tos: bool = Field(..., description="Must be true; logged for audit")
    # Versions of ToS / Privacy the client actually saw at consent time.
    # Lawyer requirement (KZ ПДн §6 + GDPR Art. 7): proof of WHAT the user
    # agreed to. Optional in payload because old clients may not send it,
    # but server stamps current version if missing. Mismatch with current
    # server version is allowed (user genuinely saw their cached version).
    tos_version: str | None = Field(default=None, max_length=64)
    privacy_version: str | None = Field(default=None, max_length=64)
    # Email locale chosen by the client. None = let the server default it
    # from country (KZ/RU → ru, else en) so the welcome email lands in the
    # language the signup form was rendered in.
    locale: str | None = Field(default=None, max_length=8)

    @field_validator("locale")
    @classmethod
    def locale_known(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in ("en", "ru"):
            raise ValueError("locale must be 'en' or 'ru'")
        return v

    @field_validator("country")
    @classmethod
    def country_upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("accept_tos")
    @classmethod
    def must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Terms of Service must be accepted")
        return v


class SignupResponse(BaseModel):
    ok: bool
    tenant_id: str | None = None
    license_key: str | None = None
    expires_at: str | None = None
    verification_required: bool = True
    message: str


class TokenResponse(BaseModel):
    user_id: str
    tenant_id: str
    bearer_token: str
    role: str


# ─── Dependency: extract pool from app state ─────────────────────────────────

def get_pool(request: Request):
    return request.app.state.pool


def get_email_service(request: Request):
    return request.app.state.email


def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth[7:]
    # We need the license_key to verify; look up from DB is expensive per-request.
    # Instead we store a second signature with a master secret (no license_key needed).
    payload = _verify_with_master_secret(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


def _sign_token(user_id: str, tenant_id: str, role: str, license_key: str) -> str:
    return create_bearer_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        license_key=license_key,
        secret=settings.JWT_SECRET,
        ttl_seconds=86400,
    )


def _verify_with_master_secret(token: str) -> dict | None:
    """Verify using JWT_SECRET directly (license_key baked into secret, not re-looked-up)."""
    from ..services.tokens import verify_bearer_token
    return verify_bearer_token(token, license_key="", secret=settings.JWT_SECRET + "_master")


def _sign_token_master(user_id: str, tenant_id: str, role: str) -> str:
    return create_bearer_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        license_key="",
        secret=settings.JWT_SECRET + "_master",
        ttl_seconds=86400,
    )


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/validate-license", response_model=ValidateLicenseResponse)
async def validate_license(body: ValidateLicenseRequest, pool=Depends(get_pool)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.id, t.plan, t.seats_limit, t.status, t.expires_at,
                   t.email_verified_at,
                   l.id AS license_id, l.active
            FROM licenses l
            JOIN tenants t ON t.id = l.tenant_id
            WHERE l.license_key = $1
            """,
            body.license_key,
        )

    if not row:
        return ValidateLicenseResponse(valid=False)

    if row["status"] == "suspended" or not row["active"]:
        return ValidateLicenseResponse(valid=False)

    if row["expires_at"] and row["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return ValidateLicenseResponse(valid=False)

    # Self-serve trials must verify email before the license activates.
    # Admin-created tenants (manual-onboarded enterprise) skip this gate
    # because we set email_verified_at at creation time on the admin path.
    if row["status"] == "trial" and row["email_verified_at"] is None:
        return ValidateLicenseResponse(valid=False)

    # Update last validated timestamp
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE licenses SET last_validated_at = now() WHERE license_key = $1",
            body.license_key,
        )

    # Fetch or create tenant admin user
    tenant_id = str(row["id"])
    async with pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT id, role FROM tenant_users WHERE tenant_id = $1 AND role = 'admin' LIMIT 1",
            row["id"],
        )

    if not user_row:
        user_id = "system"
        role = "admin"
    else:
        user_id = str(user_row["id"])
        role = user_row["role"]

    bearer = _sign_token_master(user_id, tenant_id, role)

    return ValidateLicenseResponse(
        valid=True,
        tenant_id=tenant_id,
        plan=row["plan"],
        seats_limit=row["seats_limit"],
        expires_at=row["expires_at"].isoformat() if row["expires_at"] else None,
        user_role=role,
        bearer_token=bearer,
    )


# ── Self-serve signup ────────────────────────────────────────────────────────
#
# Replaces the local-only "trial" stub the desktop app used to fake. Now a
# real cloud-issued license key tied to a tenant the admin can extend, revoke,
# or convert to paid via the dashboard.
#
# Flow: signup → email with verify link → license becomes active → user
# pastes key in desktop. Without verification, the license refuses to
# validate (no 7-day grace — mentor flagged grace as farm bait).


@router.get("/legal/versions")
async def legal_versions():
    """Return the authoritative current ToS / Privacy version strings.
    Frontend reads on signup-page load to display the right version under
    the consent checkbox and submit it back with the signup payload."""
    return {
        "tos_version": TOS_VERSION,
        "privacy_version": PRIVACY_VERSION,
    }


async def _record_tos_acceptance(
    conn,
    *,
    tenant_id: str | None,
    email: str,
    body: "SignupRequest",
    ip: str,
    user_agent: str,
    source: str = "signup",
):
    """Append a ToS acceptance row. Logs both what the client claims they saw
    and what the server thinks is current — mismatches surface in audits but
    don't block consent (user agreed to whatever was on their screen)."""
    claimed_tos = body.tos_version or TOS_VERSION
    claimed_privacy = body.privacy_version or PRIVACY_VERSION
    if claimed_tos != TOS_VERSION or claimed_privacy != PRIVACY_VERSION:
        logger.info(
            "tos-version-mismatch email=%s claimed=(%s,%s) current=(%s,%s)",
            email, claimed_tos, claimed_privacy, TOS_VERSION, PRIVACY_VERSION,
        )
    await conn.execute(
        """
        INSERT INTO tos_acceptances(
            tenant_id, email, tos_version, privacy_version, ip, user_agent, source
        ) VALUES($1,$2,$3,$4,$5,$6,$7)
        """,
        tenant_id, email, claimed_tos, claimed_privacy, ip, user_agent, source,
    )


@router.post("/signup", response_model=SignupResponse)
async def signup(
    body: SignupRequest,
    request: Request,
    pool=Depends(get_pool),
    email_svc=Depends(get_email_service),
):
    email = body.email.lower().strip()
    ip = (request.client.host if request.client else "0.0.0.0") or "0.0.0.0"
    user_agent = request.headers.get("user-agent", "")[:500]
    now = datetime.now(timezone.utc)

    # Anti-abuse: per-IP rolling window. Per-email check is done after
    # tenant lookup so we can return the right 409 message.
    async with pool.acquire() as conn:
        ip_attempts = await conn.fetchval(
            """
            SELECT COUNT(*) FROM signup_attempts
            WHERE ip = $1 AND created_at > $2 AND succeeded = TRUE
            """,
            ip, now - timedelta(days=SIGNUP_IP_WINDOW_DAYS),
        )
        if ip_attempts >= SIGNUP_IP_LIMIT:
            await conn.execute(
                "INSERT INTO signup_attempts(email, ip, user_agent, succeeded) VALUES($1,$2,$3,FALSE)",
                email, ip, user_agent,
            )
            raise HTTPException(
                status_code=429,
                detail=f"Too many signups from this network. Try again in {SIGNUP_IP_WINDOW_DAYS} days or contact hello@dias.now.",
            )

        # Existing tenant lookup. Idempotency is window-bound: within an
        # active trial we re-issue the verify email; after expiry we refuse
        # and route to sales (mentor P0 — perpetual idempotency = farming
        # via email re-use).
        existing = await conn.fetchrow(
            """
            SELECT t.id, t.expires_at, t.email_verified_at, t.plan, t.status,
                   t.locale, l.license_key
            FROM tenants t
            LEFT JOIN licenses l ON l.tenant_id = t.id AND l.active = TRUE
            WHERE t.admin_email = $1
            ORDER BY t.created_at DESC LIMIT 1
            """,
            email,
        )

        if existing:
            still_active = (
                existing["expires_at"]
                and existing["expires_at"].replace(tzinfo=timezone.utc) > now
            )
            if not still_active:
                await conn.execute(
                    "INSERT INTO signup_attempts(email, ip, user_agent, succeeded) VALUES($1,$2,$3,FALSE)",
                    email, ip, user_agent,
                )
                raise HTTPException(
                    status_code=409,
                    detail="An account with this email already had a trial. Contact hello@dias.now for an extension.",
                )
            # Active trial — resend verification email if not yet verified,
            # or just acknowledge.
            if not existing["email_verified_at"]:
                verify_token = _secrets.token_urlsafe(32)
                await conn.execute(
                    """
                    INSERT INTO email_verifications(tenant_id, email, verify_token)
                    VALUES($1,$2,$3)
                    """,
                    existing["id"], email, verify_token,
                )
                await _send_verify_email(
                    email_svc, email, body.full_name, verify_token,
                    license_key=existing["license_key"],
                    expires_at=existing["expires_at"],
                    locale=existing["locale"] or "en",
                )
            # Re-acceptance: the user clicked through the form again,
            # so log a new consent row. ToS audit is append-only.
            await _record_tos_acceptance(
                conn, tenant_id=str(existing["id"]), email=email, body=body,
                ip=ip, user_agent=user_agent, source="re-accept",
            )
            await conn.execute(
                "INSERT INTO signup_attempts(email, ip, user_agent, succeeded) VALUES($1,$2,$3,TRUE)",
                email, ip, user_agent,
            )
            return SignupResponse(
                ok=True,
                tenant_id=str(existing["id"]),
                license_key=existing["license_key"],
                expires_at=existing["expires_at"].isoformat() if existing["expires_at"] else None,
                verification_required=existing["email_verified_at"] is None,
                message="Trial already active. Verification email resent if needed.",
            )

        # Fresh signup. Create tenant + license + user atomically.
        license_key = generate_license_key()
        verify_token = _secrets.token_urlsafe(32)
        expires_at = now + timedelta(days=TRIAL_DAYS)
        locale = body.locale or ("ru" if body.country in ("KZ", "RU") else "en")

        async with conn.transaction():
            tenant_id = await conn.fetchval(
                """
                INSERT INTO tenants(
                    name, company_name, admin_email, plan, seats_limit,
                    status, expires_at, signup_source, intended_use, country,
                    locale
                )
                VALUES($1,$1,$2,'trial',$3,'trial',$4,$5,$6,$7,$8)
                RETURNING id
                """,
                body.full_name,
                email,
                TRIAL_SEATS,
                expires_at,
                body.signup_source,
                body.intended_use,
                body.country,
                locale,
            )
            await conn.execute(
                "INSERT INTO licenses(tenant_id, license_key) VALUES($1,$2)",
                tenant_id, license_key,
            )
            user_id = await conn.fetchval(
                """
                INSERT INTO tenant_users(
                    tenant_id, email, full_name, role, invite_accepted_at
                )
                VALUES($1,$2,$3,'admin',now())
                RETURNING id
                """,
                tenant_id, email, body.full_name,
            )
            await conn.execute(
                """
                INSERT INTO email_verifications(tenant_id, email, verify_token)
                VALUES($1,$2,$3)
                """,
                tenant_id, email, verify_token,
            )
            await conn.execute(
                """
                INSERT INTO founder_admin_log(action, details)
                VALUES('self_signup', $1::jsonb)
                """,
                f'{{"tenant_id":"{tenant_id}","email":"{email}","country":"{body.country}","ip":"{ip}"}}',
            )
            # Lawyer-required: log ToS / Privacy consent with timestamp,
            # version, and IP/UA evidence.
            await _record_tos_acceptance(
                conn, tenant_id=str(tenant_id), email=email, body=body,
                ip=ip, user_agent=user_agent, source="signup",
            )
            await conn.execute(
                "INSERT INTO signup_attempts(email, ip, user_agent, succeeded) VALUES($1,$2,$3,TRUE)",
                email, ip, user_agent,
            )

    # Email is fire-and-forget — failure to send shouldn't block signup
    # (user can request resend). Errors logged inside email_svc.
    await _send_verify_email(
        email_svc, email, body.full_name, verify_token,
        license_key=license_key,
        expires_at=expires_at,
        locale=locale,
    )

    # Internal heads-up to the founder so leads land in the inbox without
    # opening the dashboard. Only on FRESH signups (not the idempotent
    # re-accept branch above), and only when an admin-notify inbox is set.
    if settings.ADMIN_NOTIFY_TO:
        try:
            await email_svc.send_admin_signup_notification(
                to=settings.ADMIN_NOTIFY_TO,
                signup_email=email,
                full_name=body.full_name,
                country=body.country,
                intended_use=body.intended_use,
                signup_source=body.signup_source,
                ip=ip,
                tenant_id=str(tenant_id),
            )
        except Exception as exc:
            logger.warning("admin_signup_notification email failed: %s", exc)

    return SignupResponse(
        ok=True,
        tenant_id=str(tenant_id),
        license_key=license_key,
        expires_at=expires_at.isoformat(),
        verification_required=True,
        message="Trial created. Check your email to verify and activate your license.",
    )


async def _send_verify_email(
    email_svc,
    email: str,
    full_name: str,
    verify_token: str,
    *,
    license_key: str | None = None,
    expires_at: datetime | None = None,
    seats: int = TRIAL_SEATS,
    locale: str = "en",
):
    """Send the verify-email message — also serves as the welcome email
    since download URLs + license key + verify link are bundled together.

    Per the gated-download policy: the only place download URLs surface
    is this email. Landing pages don't expose them. So the user must
    sign up to get the app, and we capture every download lead.
    """
    from ..services.releases import get_latest_releases, releases_summary, RELEASES_PAGE

    verify_url = f"{settings.LANDING_URL}/verify-email.html?token={verify_token}"
    try:
        releases = await get_latest_releases()
    except Exception as exc:
        logger.warning("releases fetch failed in verify-email: %s", exc)
        releases = {"page_url": RELEASES_PAGE}

    expires_human = expires_at.strftime("%d %b %Y") if expires_at else f"in {TRIAL_DAYS} days"

    try:
        await email_svc.send(
            to=email,
            template="verify_email",
            locale=locale,
            context={
                "full_name": full_name,
                "verify_url": verify_url,
                "landing_url": settings.LANDING_URL,
                "license_key": license_key or "(activates after verification)",
                "downloads": releases_summary(releases),
                "releases_page": releases.get("page_url", RELEASES_PAGE),
                "seats": seats,
                "expires_at_human": expires_human,
            },
        )
    except Exception as exc:
        logger.warning("verify-email send failed for %s: %s", email, exc)


@router.get("/verify-email/{verify_token}")
async def verify_email(verify_token: str, pool=Depends(get_pool), email_svc=Depends(get_email_service)):
    """Confirm email ownership. Activates the license for validate-license calls."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT v.id, v.tenant_id, v.email, v.verified_at, v.expires_at,
                   t.email_verified_at AS tenant_verified_at, t.company_name,
                   t.plan, t.seats_limit, t.expires_at AS tenant_expires_at,
                   t.locale, l.license_key
            FROM email_verifications v
            JOIN tenants t ON t.id = v.tenant_id
            LEFT JOIN licenses l ON l.tenant_id = t.id AND l.active = TRUE
            WHERE v.verify_token = $1
            """,
            verify_token,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Invalid or unknown verification token")
        if row["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Verification link expired. Request a new one from /signup.")

        already_verified = row["tenant_verified_at"] is not None
        if not already_verified:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE email_verifications SET verified_at = now() WHERE id = $1",
                    row["id"],
                )
                await conn.execute(
                    "UPDATE tenants SET email_verified_at = now() WHERE id = $1",
                    row["tenant_id"],
                )

    if not already_verified and row["license_key"]:
        tenant_locale = row["locale"] or "en"
        # Send the license-activated email (the "your key works now" message)
        # followed by the welcome onboarding mail (the "here's where to go
        # next" message). Two distinct beats — the first is transactional
        # confirmation, the second is the onboarding nudge. Failures don't
        # block the verify response since the user already has the key from
        # signup.
        try:
            await email_svc.send_license_activated(
                to=row["email"],
                license_key=row["license_key"],
                company_name=row["company_name"],
                plan=row["plan"],
                seats=row["seats_limit"],
                landing_url=settings.LANDING_URL,
                locale=tenant_locale,
            )
        except Exception as exc:
            logger.warning("license_activated email failed for %s: %s", row["email"], exc)
        try:
            await email_svc.send_welcome(
                to=row["email"],
                company_name=row["company_name"],
                landing_url=settings.LANDING_URL,
                locale=tenant_locale,
            )
        except Exception as exc:
            logger.warning("welcome email failed for %s: %s", row["email"], exc)

    return {
        "ok": True,
        "already_verified": already_verified,
        "tenant_id": str(row["tenant_id"]),
        "license_key": row["license_key"],
        "expires_at": row["tenant_expires_at"].isoformat() if row["tenant_expires_at"] else None,
    }


@router.post("/resend-verify")
async def resend_verify(body: dict, pool=Depends(get_pool), email_svc=Depends(get_email_service)):
    """Resend the verify-email link. Idempotent; rate-limited via signup_attempts."""
    email = (body.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.id, t.email_verified_at, t.expires_at, t.seats_limit, t.locale,
                   u.full_name, l.license_key
            FROM tenants t
            LEFT JOIN tenant_users u ON u.tenant_id = t.id AND u.email = t.admin_email
            LEFT JOIN licenses l ON l.tenant_id = t.id AND l.active = TRUE
            WHERE t.admin_email = $1
            ORDER BY t.created_at DESC LIMIT 1
            """,
            email,
        )
        if not row or row["email_verified_at"]:
            # Don't leak whether the address exists; pretend OK.
            return {"ok": True}
        verify_token = _secrets.token_urlsafe(32)
        await conn.execute(
            "INSERT INTO email_verifications(tenant_id, email, verify_token) VALUES($1,$2,$3)",
            row["id"], email, verify_token,
        )
    await _send_verify_email(
        email_svc, email, row["full_name"] or email, verify_token,
        license_key=row["license_key"],
        expires_at=row["expires_at"],
        seats=row["seats_limit"] or TRIAL_SEATS,
        locale=row["locale"] or "en",
    )
    return {"ok": True}


@router.post("/invite")
async def create_invite(
    body: InviteRequest,
    pool=Depends(get_pool),
    email_svc=Depends(get_email_service),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] not in ("admin", "developer"):
        raise HTTPException(status_code=403, detail="Only admins can invite")

    tenant_id = current_user["tenant_id"]

    async with pool.acquire() as conn:
        # Check seat limit
        tenant = await conn.fetchrow("SELECT seats_limit FROM tenants WHERE id = $1", tenant_id)
        active_users = await conn.fetchval(
            "SELECT COUNT(*) FROM tenant_users WHERE tenant_id = $1", tenant_id
        )
        if active_users >= tenant["seats_limit"]:
            raise HTTPException(status_code=402, detail="Seat limit reached")

        # Check existing user
        exists = await conn.fetchval(
            "SELECT id FROM tenant_users WHERE tenant_id = $1 AND email = $2",
            tenant_id, body.email,
        )
        if exists:
            raise HTTPException(status_code=409, detail="User already in tenant")

        token = generate_invite_token()
        invite_id = await conn.fetchval(
            """
            INSERT INTO invites(tenant_id, email, role, invite_token, created_by)
            VALUES($1,$2,$3,$4,$5) RETURNING id
            """,
            tenant_id, body.email, body.role, token, current_user["user_id"],
        )

        tenant_row = await conn.fetchrow(
            "SELECT company_name, locale FROM tenants WHERE id = $1", tenant_id
        )

    await email_svc.send_invite(
        to=body.email,
        invite_token=token,
        locale=(tenant_row["locale"] if tenant_row else None) or "en",
        company_name=tenant_row["company_name"],
        landing_url=settings.LANDING_URL,
    )

    return {"invite_id": str(invite_id), "invite_token": token, "expires_in_days": 7}


@router.post("/accept-invite", response_model=TokenResponse)
async def accept_invite(body: AcceptInviteRequest, pool=Depends(get_pool)):
    async with pool.acquire() as conn:
        invite = await conn.fetchrow(
            """
            SELECT i.*, t.company_name FROM invites i
            JOIN tenants t ON t.id = i.tenant_id
            WHERE i.invite_token = $1 AND i.accepted_at IS NULL
              AND i.expires_at > now()
            """,
            body.invite_token,
        )
        if not invite:
            raise HTTPException(status_code=404, detail="Invalid or expired invite token")

        user_id = await conn.fetchval(
            """
            INSERT INTO tenant_users(tenant_id, email, role, invited_by, invite_accepted_at)
            VALUES($1,$2,$3,$4,now()) RETURNING id
            """,
            invite["tenant_id"], invite["email"], invite["role"],
            invite["created_by"],
        )

        await conn.execute(
            "UPDATE invites SET accepted_at = now() WHERE invite_token = $1",
            body.invite_token,
        )

    tenant_id = str(invite["tenant_id"])
    bearer = _sign_token_master(str(user_id), tenant_id, invite["role"])

    return TokenResponse(
        user_id=str(user_id),
        tenant_id=tenant_id,
        bearer_token=bearer,
        role=invite["role"],
    )


@router.post("/refresh")
async def refresh_token(current_user: dict = Depends(get_current_user)):
    new_token = _sign_token_master(
        current_user["user_id"], current_user["tenant_id"], current_user["role"]
    )
    return {"bearer_token": new_token}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user), pool=Depends(get_pool)):
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT email, role FROM tenant_users WHERE id = $1",
            current_user["user_id"],
        )
    return {
        "user_id": current_user["user_id"],
        "tenant_id": current_user["tenant_id"],
        "role": current_user["role"],
        "email": user["email"] if user else None,
    }
