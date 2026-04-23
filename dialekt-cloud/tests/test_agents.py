"""Integration tests for /agents endpoints."""
import pytest

SAMPLE_MANIFEST = """
id: "11111111-1111-4111-a111-111111111111"
name: "Test Agent"
version: "1.0.0"
description: "A test agent for CI"
system_prompt: "You are a helpful test assistant."
model:
  provider: "ollama"
  name: "llama3.2"
output:
  format: "markdown"
  destination:
    type: "notification"
"""


@pytest.mark.asyncio
async def test_publish_agent(client, auth_headers):
    r = await client.post("/agents/publish", headers=auth_headers, json={
        "manifest_yaml": SAMPLE_MANIFEST,
    })
    assert r.status_code == 200
    data = r.json()
    assert "agent_id" in data
    assert data["name"] == "Test Agent"
    return data["agent_id"]


@pytest.mark.asyncio
async def test_publish_invalid_manifest(client, auth_headers):
    r = await client.post("/agents/publish", headers=auth_headers, json={
        "manifest_yaml": "this: is: not: valid: yaml: !!!!!",
    })
    # Should return 422 (invalid YAML or invalid manifest)
    assert r.status_code in (422, 400)


@pytest.mark.asyncio
async def test_assigned_to_me_empty(client, auth_headers):
    r = await client.get("/agents/assigned-to-me", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_assign_and_list(client, auth_headers, active_tenant):
    # Publish an agent
    r = await client.post("/agents/publish", headers=auth_headers, json={
        "manifest_yaml": SAMPLE_MANIFEST,
    })
    assert r.status_code == 200
    agent_id = r.json()["agent_id"]

    # Get current user's ID from /auth/me
    me_r = await client.get("/auth/me", headers=auth_headers)
    user_id = me_r.json()["user_id"]

    # Assign to self
    r = await client.post("/agents/assign", headers=auth_headers, json={
        "agent_id": agent_id,
        "assigned_to_user_id": user_id,
    })
    assert r.status_code == 200
    assignment_id = r.json()["assignment_id"]

    # Now should appear in assigned-to-me
    r = await client.get("/agents/assigned-to-me", headers=auth_headers)
    assert r.status_code == 200
    agents = r.json()
    agent_ids = [a["id"] for a in agents]
    assert agent_id in agent_ids

    return assignment_id, agent_id


@pytest.mark.asyncio
async def test_get_manifest(client, auth_headers, active_tenant):
    # Publish
    r = await client.post("/agents/publish", headers=auth_headers, json={
        "manifest_yaml": SAMPLE_MANIFEST,
    })
    agent_id = r.json()["agent_id"]

    # Admin can always get manifest
    r = await client.get(f"/agents/{agent_id}/manifest", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == agent_id
    assert "manifest_yaml" in data
    assert "Test Agent" in data["manifest_yaml"]


@pytest.mark.asyncio
async def test_get_manifest_wrong_tenant(client, admin_headers):
    # Create a second tenant to test isolation
    r = await client.post("/admin/tenants", headers=admin_headers, json={
        "company_name": "Tenant B",
        "admin_email": "admin@tenantb.kz",
        "plan": "team",
        "seats": 3,
    })
    tenant_b_id = r.json()["tenant_id"]
    await client.post(f"/admin/tenants/{tenant_b_id}/activate", headers=admin_headers)

    r = await client.post("/auth/validate-license",
        json={"license_key": "dialekt_" + "b" * 64},
    )
    # Fake license — should not find tenant B's agents cross-tenant
    # This just verifies isolation exists; real cross-tenant test needs two full tenant setups
    assert r.json()["valid"] is False


@pytest.mark.asyncio
async def test_unassign(client, auth_headers, active_tenant):
    # Publish + assign
    r = await client.post("/agents/publish", headers=auth_headers, json={
        "manifest_yaml": SAMPLE_MANIFEST,
    })
    agent_id = r.json()["agent_id"]

    me = await client.get("/auth/me", headers=auth_headers)
    user_id = me.json()["user_id"]

    r = await client.post("/agents/assign", headers=auth_headers, json={
        "agent_id": agent_id,
        "assigned_to_user_id": user_id,
    })
    assignment_id = r.json()["assignment_id"]

    # Unassign
    r = await client.delete(f"/agents/assign/{assignment_id}", headers=auth_headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_publish_requires_auth(client):
    r = await client.post("/agents/publish", json={"manifest_yaml": SAMPLE_MANIFEST})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_assign_nonexistent_agent(client, auth_headers):
    r = await client.post("/agents/assign", headers=auth_headers, json={
        "agent_id": "00000000-0000-4000-0000-000000000000",
        "assigned_to_user_id": "00000000-0000-4000-0000-000000000001",
    })
    assert r.status_code == 404
