"""Tenant-facing authentication: license validation, invites, token refresh."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from ..config import settings
from ..services.tokens import (
    create_bearer_token,
    generate_invite_token,
    generate_license_key,
    verify_bearer_token,
)

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
            "SELECT company_name FROM tenants WHERE id = $1", tenant_id
        )

    await email_svc.send_invite(
        to=body.email,
        invite_token=token,
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
