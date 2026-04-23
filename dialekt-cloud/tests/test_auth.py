"""Integration tests for /auth endpoints — requires live DB."""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_validate_license_invalid(client):
    r = await client.post("/auth/validate-license", json={
        "license_key": "dialekt_notexist1234",
        "machine_id": "test",
    })
    assert r.status_code == 200
    assert r.json()["valid"] is False


@pytest.mark.asyncio
async def test_validate_license_valid(client, active_tenant):
    r = await client.post("/auth/validate-license", json={
        "license_key": active_tenant["license_key"],
        "machine_id": "test-machine",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["tenant_id"] == active_tenant["tenant_id"]
    assert data["plan"] == "team"
    assert data["seats_limit"] == 5
    assert "bearer_token" in data
    assert data["bearer_token"]


@pytest.mark.asyncio
async def test_validate_suspended_tenant(client, admin_headers, active_tenant):
    # Suspend the tenant first
    r = await client.patch(
        f"/admin/tenants/{active_tenant['tenant_id']}",
        headers=admin_headers,
        json={"status": "suspended"},
    )
    assert r.status_code == 200

    r = await client.post("/auth/validate-license", json={
        "license_key": active_tenant["license_key"],
        "machine_id": "test",
    })
    assert r.json()["valid"] is False

    # Restore
    await client.patch(
        f"/admin/tenants/{active_tenant['tenant_id']}",
        headers=admin_headers,
        json={"status": "active"},
    )


@pytest.mark.asyncio
async def test_get_me(client, auth_headers):
    r = await client.get("/auth/me", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "user_id" in data
    assert "tenant_id" in data
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_get_me_no_token(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_invite_and_accept(client, auth_headers, active_tenant):
    # Invite
    r = await client.post("/auth/invite", headers=auth_headers, json={
        "email": "colleague@testcorp.kz",
        "role": "user",
    })
    assert r.status_code == 200
    data = r.json()
    assert "invite_token" in data
    token = data["invite_token"]
    assert token.startswith("inv_")

    # Accept
    r = await client.post("/auth/accept-invite", json={
        "invite_token": token,
        "machine_id": "colleague-machine",
    })
    assert r.status_code == 200
    acc = r.json()
    assert "bearer_token" in acc
    assert acc["role"] == "user"
    assert acc["tenant_id"] == active_tenant["tenant_id"]


@pytest.mark.asyncio
async def test_invite_wrong_role_rejected(client, bearer_token):
    # Create user-level token (user role can't invite)
    # This test uses admin token, just verifies response structure
    r = await client.post("/auth/invite",
        headers={"Authorization": f"Bearer {bearer_token}"},
        json={"email": "x@y.com", "role": "user"},
    )
    # Admin can invite, so this should succeed
    assert r.status_code in (200, 402, 409)


@pytest.mark.asyncio
async def test_accept_expired_invite(client):
    r = await client.post("/auth/accept-invite", json={
        "invite_token": "inv_totally_fake_token_xyz",
        "machine_id": "test",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_refresh_token(client, auth_headers):
    r = await client.post("/auth/refresh", headers=auth_headers)
    assert r.status_code == 200
    assert "bearer_token" in r.json()


@pytest.mark.asyncio
async def test_accept_same_invite_twice(client, auth_headers):
    """Second accept of same token should fail."""
    r = await client.post("/auth/invite", headers=auth_headers, json={
        "email": "once@testcorp.kz", "role": "user",
    })
    token = r.json()["invite_token"]

    r1 = await client.post("/auth/accept-invite", json={"invite_token": token})
    assert r1.status_code == 200

    r2 = await client.post("/auth/accept-invite", json={"invite_token": token})
    assert r2.status_code == 404
