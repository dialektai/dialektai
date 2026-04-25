"""dialekt-admin CLI — founder-only operations."""
import asyncio
import os
import sys
from datetime import datetime

import click


def _api(path: str, method: str = "GET", json=None, admin_key: str | None = None):
    import httpx
    base = os.environ.get("DIALEKT_CLOUD_URL", "http://localhost:8080")
    key = admin_key or os.environ.get("DIALEKT_ADMIN_KEY", "")
    headers = {"X-Admin-Key": key}
    with httpx.Client(timeout=10) as c:
        if method == "GET":
            r = c.get(f"{base}{path}", headers=headers)
        elif method == "POST":
            r = c.post(f"{base}{path}", headers=headers, json=json or {})
        elif method == "PATCH":
            r = c.patch(f"{base}{path}", headers=headers, json=json or {})
        elif method == "DELETE":
            r = c.delete(f"{base}{path}", headers=headers)
    return r


@click.group()
def cli():
    """dialekt-admin — Founder operations CLI.

    Set DIALEKT_CLOUD_URL and DIALEKT_ADMIN_KEY env vars, or pass --url and --key.
    """


@cli.group()
def tenant():
    """Manage tenants."""


@tenant.command("list")
def tenant_list():
    """List all tenants."""
    r = _api("/admin/tenants")
    if r.status_code != 200:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)
    tenants = r.json()
    click.echo(f"\n{'ID':<38} {'Company':<30} {'Status':<12} {'Plan':<10} {'Seats'}")
    click.echo("-" * 100)
    for t in tenants:
        click.echo(f"{t['id']:<38} {t['company_name'][:29]:<30} {t['status']:<12} {t['plan']:<10} {t['seats_limit']}")
    click.echo(f"\nTotal: {len(tenants)}")


@tenant.command("create")
@click.option("--company", prompt="Company name")
@click.option("--email", prompt="Admin email")
@click.option("--plan", default="team", show_default=True)
@click.option("--seats", default=3, type=int, show_default=True)
@click.option("--months", default=12, type=int, help="Subscription months")
@click.option("--notes", default="", help="Internal notes")
def tenant_create(company, email, plan, seats, months, notes):
    """Create a new tenant (draft status)."""
    r = _api("/admin/tenants", "POST", {
        "company_name": company,
        "admin_email": email,
        "plan": plan,
        "seats": seats,
        "expiration_months": months,
        "notes": notes or None,
    })
    if r.status_code == 201:
        data = r.json()
        click.echo(f"✓ Created tenant: {data['tenant_id']} (status: draft)")
        click.echo("  Next: generate invoice with `dialekt-admin tenant invoice <id>`")
    else:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)


@tenant.command("activate")
@click.argument("tenant_id")
def tenant_activate(tenant_id):
    """Activate tenant after payment. Generates license key and sends email."""
    r = _api(f"/admin/tenants/{tenant_id}/activate", "POST")
    if r.status_code == 200:
        data = r.json()
        click.echo(f"✓ Tenant activated")
        click.echo(f"  License key: {data['license_key']}")
        click.echo(f"  Email sent:  {data['email_sent']}")
        click.echo(f"  To:          {data['admin_email']}")
    else:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)


@tenant.command("suspend")
@click.argument("tenant_id")
def tenant_suspend(tenant_id):
    """Suspend a tenant (blocks license validation)."""
    r = _api(f"/admin/tenants/{tenant_id}", "PATCH", {"status": "suspended"})
    if r.status_code == 200:
        click.echo(f"✓ Tenant {tenant_id} suspended")
    else:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)


@tenant.command("resume")
@click.argument("tenant_id")
def tenant_resume(tenant_id):
    """Resume a suspended tenant."""
    r = _api(f"/admin/tenants/{tenant_id}", "PATCH", {"status": "active"})
    if r.status_code == 200:
        click.echo(f"✓ Tenant {tenant_id} resumed")
    else:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)


@tenant.command("invoice")
@click.argument("tenant_id")
@click.option("--amount", prompt="Amount (KZT)", type=float)
@click.option("--months", prompt="Period (months)", default=1, type=int)
@click.option("--address", default="", help="Buyer address")
def tenant_invoice(tenant_id, amount, months, address):
    """Generate invoice PDF for tenant."""
    r = _api(f"/admin/tenants/{tenant_id}/invoice", "POST", {
        "amount_kzt": amount,
        "period_months": months,
        "company_address": address or None,
    })
    if r.status_code == 200:
        data = r.json()
        click.echo(f"✓ Invoice {data['invoice_number']} generated")
        if data.get("pdf_path"):
            click.echo(f"  PDF: {data['pdf_path']}")
        else:
            click.echo("  ⚠ PDF not generated (weasyprint may not be installed)")
    else:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)


@cli.command()
def stats():
    """Show overview statistics."""
    r = _api("/admin/stats")
    if r.status_code != 200:
        click.echo(f"Error: {r.text}", err=True)
        sys.exit(1)
    data = r.json()
    click.echo("\n── dialekt-cloud stats ─────────────────")
    click.echo(f"  Tenants:  {data['tenants']['total']} total / {data['tenants']['active']} active / {data['tenants']['draft']} draft")
    click.echo(f"  Users:    {data['users']['total']}")
    click.echo(f"  Agents:   {data['agents']['total']}")
    click.echo(f"  Invoices: {data['invoices']['total']} / {data['invoices']['paid']} paid")


# ── Admin user management (DIRECT DB — no HTTP) ─────────────────────────────
# Per admin_2fa_DESIGN: these run against the DB directly. Must be invoked
# over SSH on the server. Recovery flows that bypass HTTP entirely.


async def _db_pool():
    import asyncpg
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        click.echo("DATABASE_URL not set", err=True)
        sys.exit(2)
    return await asyncpg.create_pool(dsn, min_size=1, max_size=2)


@cli.group()
def admin():
    """Manage founder admin accounts (direct DB access — SSH only)."""


def _validate_admin_email_domain(email: str) -> None:
    """Enforce DIALEKT_ADMIN_EMAIL_DOMAIN policy. Empty value = no restriction
    (used in tests / dev). Production default: '@dias.now'."""
    from dialekt_cloud.config import settings as _cfg
    domain = (_cfg.DIALEKT_ADMIN_EMAIL_DOMAIN or "").strip().lower()
    if not domain:
        return
    if not email.lower().endswith(domain):
        click.echo(
            f"✗ Admin email must end in '{domain}'. Got: {email}\n"
            f"  Override via env: DIALEKT_ADMIN_EMAIL_DOMAIN='' (not recommended in prod).",
            err=True,
        )
        sys.exit(1)


@admin.command("create")
@click.option("--email", required=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True,
              help="Will be argon2id-hashed before storage.")
def admin_create(email, password):
    """Create a new founder admin. TOTP enrollment happens at first login.

    Email must end in @dias.now (or whatever DIALEKT_ADMIN_EMAIL_DOMAIN is
    set to). Primary admin: zhumagaliyev@dias.now."""
    from dialekt_cloud.services.admin_auth import hash_password

    _validate_admin_email_domain(email)

    async def _go():
        pool = await _db_pool()
        try:
            async with pool.acquire() as conn:
                existing = await conn.fetchval("SELECT id FROM admins WHERE email = $1", email.lower())
                if existing:
                    click.echo(f"Admin {email} already exists ({existing})", err=True)
                    sys.exit(1)
                admin_id = await conn.fetchval(
                    "INSERT INTO admins(email, password_hash) VALUES($1,$2) RETURNING id",
                    email.lower(), hash_password(password),
                )
                click.echo(f"✓ Admin created · id={admin_id} email={email}")
                click.echo("  TOTP will be enrolled on first login.")
        finally:
            await pool.close()

    asyncio.run(_go())


@admin.command("list")
def admin_list():
    """List founder admins."""
    async def _go():
        pool = await _db_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, email, totp_enrolled_at, last_login_at, last_login_ip,
                           failed_attempts, locked_until, created_at
                    FROM admins ORDER BY created_at
                    """
                )
            if not rows:
                click.echo("No admins. Bootstrap with: dialekt-admin admin create --email=...")
                return
            click.echo(f"\n{'EMAIL':<32} {'TOTP':<6} {'LAST LOGIN':<22} {'FAILS':<6} {'LOCKED?'}")
            click.echo("-" * 80)
            for r in rows:
                totp = "✓" if r["totp_enrolled_at"] else "—"
                last = r["last_login_at"].strftime("%Y-%m-%d %H:%M") if r["last_login_at"] else "—"
                locked = "yes" if (r["locked_until"] and r["locked_until"] > datetime.now(r["locked_until"].tzinfo)) else "no"
                click.echo(f"{r['email']:<32} {totp:<6} {last:<22} {r['failed_attempts']:<6} {locked}")
        finally:
            await pool.close()

    asyncio.run(_go())


@admin.command("reset-2fa")
@click.option("--email", required=True)
@click.confirmation_option(prompt="This clears the TOTP secret AND backup codes. Confirm?")
def admin_reset_2fa(email):
    """Clear TOTP enrolment so the admin can re-enroll on next login."""
    async def _go():
        pool = await _db_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.execute(
                    """
                    UPDATE admins SET totp_secret_encrypted = NULL,
                                      totp_enrolled_at = NULL,
                                      backup_codes = NULL,
                                      backup_codes_generated_at = NULL,
                                      failed_attempts = 0,
                                      locked_until = NULL
                    WHERE email = $1
                    """,
                    email.lower(),
                )
                if row.endswith("0"):
                    click.echo(f"No admin {email}", err=True)
                    sys.exit(1)
                click.echo(f"✓ TOTP cleared for {email}. Next login triggers re-enrollment.")
        finally:
            await pool.close()

    asyncio.run(_go())


@admin.command("reset-password")
@click.option("--email", required=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def admin_reset_password(email, password):
    """Set a fresh password for an admin (argon2id)."""
    from dialekt_cloud.services.admin_auth import hash_password

    async def _go():
        pool = await _db_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.execute(
                    """
                    UPDATE admins SET password_hash = $1, failed_attempts = 0, locked_until = NULL
                    WHERE email = $2
                    """,
                    hash_password(password), email.lower(),
                )
                if row.endswith("0"):
                    click.echo(f"No admin {email}", err=True)
                    sys.exit(1)
                click.echo(f"✓ Password updated for {email}.")
        finally:
            await pool.close()

    asyncio.run(_go())


@admin.command("unlock")
@click.option("--email", required=True)
def admin_unlock(email):
    """Clear lockout flags for an admin."""
    async def _go():
        pool = await _db_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE admins SET failed_attempts = 0, locked_until = NULL WHERE email = $1",
                    email.lower(),
                )
            click.echo(f"✓ {email} unlocked.")
        finally:
            await pool.close()

    asyncio.run(_go())
