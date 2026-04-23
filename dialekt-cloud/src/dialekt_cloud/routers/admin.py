"""Founder-only admin API: tenant CRUD, invoice, activation."""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import settings
from ..services.invoice import generate_pdf, seller_from_env
from ..services.tokens import generate_license_key

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


# ─── Auth ────────────────────────────────────────────────────────────────────

def _require_admin(request: Request):
    """Allow either X-Admin-Key header or valid session token."""
    admin_key = request.headers.get("X-Admin-Key", "")
    if admin_key == settings.DIALEKT_ADMIN_KEY:
        return True
    # Also allow session token from /admin/login
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        from ..services.tokens import verify_admin_session_token
        if verify_admin_session_token(auth[7:], settings.DIALEKT_ADMIN_KEY, settings.JWT_SECRET):
            return True
    raise HTTPException(status_code=403, detail="Invalid admin key")


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

@router.post("/login")
async def admin_login(request: Request):
    body = await request.json()
    if body.get("admin_key") != settings.DIALEKT_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    from ..services.tokens import create_admin_session_token
    token = create_admin_session_token(settings.DIALEKT_ADMIN_KEY, settings.JWT_SECRET)
    return {"session_token": token}


@router.get("/tenants")
async def list_tenants(pool=Depends(get_pool), _=Depends(_require_admin)):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.*,
                   COUNT(DISTINCT tu.id) AS user_count,
                   COUNT(DISTINCT l.id) AS license_count
            FROM tenants t
            LEFT JOIN tenant_users tu ON tu.tenant_id = t.id
            LEFT JOIN licenses l ON l.tenant_id = t.id
            GROUP BY t.id
            ORDER BY t.created_at DESC
            """
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
    )

    return {
        "activated": True,
        "license_key": license_key,
        "email_sent": email_sent,
        "admin_email": tenant["admin_email"],
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
