"""Integration tests for /admin endpoints."""
import pytest


@pytest.mark.asyncio
async def test_admin_login_valid(client):
    import os
    r = await client.post("/admin/login", json={"admin_key": os.environ["DIALEKT_ADMIN_KEY"]})
    assert r.status_code == 200
    assert "session_token" in r.json()


@pytest.mark.asyncio
async def test_admin_login_invalid(client):
    r = await client.post("/admin/login", json={"admin_key": "wrongkey"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_tenants(client, admin_headers, tenant_id):
    r = await client.get("/admin/tenants", headers=admin_headers)
    assert r.status_code == 200
    tenants = r.json()
    assert isinstance(tenants, list)
    ids = [str(t["id"]) for t in tenants]
    assert tenant_id in ids


@pytest.mark.asyncio
async def test_create_tenant(client, admin_headers):
    r = await client.post("/admin/tenants", headers=admin_headers, json={
        "company_name": "Acme Corp",
        "admin_email": "admin@acme.kz",
        "plan": "team",
        "seats": 10,
        "expiration_months": 12,
    })
    assert r.status_code == 201
    data = r.json()
    assert "tenant_id" in data
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_get_tenant_detail(client, admin_headers, tenant_id):
    r = await client.get(f"/admin/tenants/{tenant_id}", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["company_name"].startswith("Test Corp")
    assert "users" in data
    assert "invoices" in data


@pytest.mark.asyncio
async def test_update_tenant(client, admin_headers, tenant_id):
    r = await client.patch(f"/admin/tenants/{tenant_id}", headers=admin_headers, json={
        "plan": "enterprise",
        "seats": 20,
        "notes": "High priority pilot",
    })
    assert r.status_code == 200
    assert r.json()["updated"] is True

    # Verify update
    r = await client.get(f"/admin/tenants/{tenant_id}", headers=admin_headers)
    data = r.json()
    assert data["plan"] == "enterprise"
    assert data["seats_limit"] == 20


@pytest.mark.asyncio
async def test_activate_draft_tenant(client, admin_headers, tenant_id):
    r = await client.post(f"/admin/tenants/{tenant_id}/activate", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["activated"] is True
    assert data["license_key"].startswith("dialekt_")
    assert len(data["license_key"]) == 72
    assert data["email_sent"] is True  # mock returns True


@pytest.mark.asyncio
async def test_activate_already_active_fails(client, admin_headers, active_tenant):
    r = await client.post(
        f"/admin/tenants/{active_tenant['tenant_id']}/activate",
        headers=admin_headers,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_suspend_and_resume(client, admin_headers, active_tenant):
    tid = active_tenant["tenant_id"]
    r = await client.patch(f"/admin/tenants/{tid}", headers=admin_headers, json={"status": "suspended"})
    assert r.status_code == 200

    r = await client.get(f"/admin/tenants/{tid}", headers=admin_headers)
    assert r.json()["status"] == "suspended"

    r = await client.patch(f"/admin/tenants/{tid}", headers=admin_headers, json={"status": "active"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_stats(client, admin_headers):
    r = await client.get("/admin/stats", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert "tenants" in data
    assert "users" in data
    assert data["tenants"]["total"] >= 0


@pytest.mark.asyncio
async def test_admin_without_key_rejected(client):
    r = await client.get("/admin/tenants")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_generate_invoice(client, admin_headers, active_tenant):
    r = await client.post(
        f"/admin/tenants/{active_tenant['tenant_id']}/invoice",
        headers=admin_headers,
        json={"amount_kzt": 150000, "period_months": 3},
    )
    assert r.status_code == 200
    data = r.json()
    assert "invoice_id" in data
    assert data["invoice_number"].startswith("INV-")


@pytest.mark.asyncio
async def test_list_tenant_users(client, admin_headers, active_tenant):
    r = await client.get(
        f"/admin/tenants/{active_tenant['tenant_id']}/users",
        headers=admin_headers,
    )
    assert r.status_code == 200
    users = r.json()
    assert isinstance(users, list)
    # After activation, admin user should be there (email is unique per fixture run)
    roles = [u["role"] for u in users]
    assert "admin" in roles
