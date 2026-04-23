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
