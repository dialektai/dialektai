"""End-to-end lifecycle test: founder creates tenant → activates → user validates license → invites colleague → colleague accepts."""
import pytest


@pytest.mark.asyncio
async def test_full_tenant_lifecycle(client, admin_headers):
    # 1. Founder creates draft tenant
    r = await client.post("/admin/tenants", headers=admin_headers, json={
        "company_name": "Lifecycle Corp",
        "admin_email": "cto@lifecycle.kz",
        "plan": "team",
        "seats": 3,
        "expiration_months": 12,
    })
    assert r.status_code == 201
    tenant_id = r.json()["tenant_id"]

    # 2. Tenant starts as draft
    r = await client.get(f"/admin/tenants/{tenant_id}", headers=admin_headers)
    assert r.json()["status"] == "draft"

    # 3. Generate invoice
    r = await client.post(f"/admin/tenants/{tenant_id}/invoice", headers=admin_headers, json={
        "amount_kzt": 90000,
        "period_months": 3,
    })
    assert r.status_code == 200
    assert r.json()["invoice_number"].startswith("INV-")

    # 4. Activate (simulates founder confirming payment)
    r = await client.post(f"/admin/tenants/{tenant_id}/activate", headers=admin_headers)
    assert r.status_code == 200
    license_key = r.json()["license_key"]
    assert license_key.startswith("dialekt_")
    assert r.json()["email_sent"] is True

    # 5. Verify tenant is now active
    r = await client.get(f"/admin/tenants/{tenant_id}", headers=admin_headers)
    assert r.json()["status"] == "active"
    assert r.json()["license"] is not None

    # 6. Tenant admin validates license from desktop app
    r = await client.post("/auth/validate-license", json={
        "license_key": license_key,
        "machine_id": "cto-macbook",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["tenant_id"] == tenant_id
    assert data["plan"] == "team"
    admin_token = data["bearer_token"]

    # 7. Admin invites a colleague
    r = await client.post("/auth/invite",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "dev@lifecycle.kz", "role": "developer"},
    )
    assert r.status_code == 200
    invite_token = r.json()["invite_token"]
    assert invite_token.startswith("inv_")

    # 8. Colleague accepts invite
    r = await client.post("/auth/accept-invite", json={
        "invite_token": invite_token,
        "machine_id": "dev-laptop",
    })
    assert r.status_code == 200
    colleague_data = r.json()
    assert colleague_data["role"] == "developer"
    colleague_token = colleague_data["bearer_token"]

    # 9. Admin publishes an agent
    manifest = """
id: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
name: "Lifecycle Agent"
version: "1.0.0"
description: "Test agent for lifecycle test"
system_prompt: "You help with lifecycle testing."
model:
  provider: "ollama"
  name: "llama3.2"
output:
  format: "markdown"
  destination:
    type: "notification"
"""
    r = await client.post("/agents/publish",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"manifest_yaml": manifest},
    )
    assert r.status_code == 200
    agent_id = r.json()["agent_id"]

    # 10. Admin assigns to colleague
    r = await client.post("/agents/assign",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "agent_id": agent_id,
            "assigned_to_user_id": colleague_data["user_id"],
        },
    )
    assert r.status_code == 200

    # 11. Colleague sees assigned agent
    r = await client.get("/agents/assigned-to-me",
        headers={"Authorization": f"Bearer {colleague_token}"},
    )
    assert r.status_code == 200
    agents = r.json()
    assert any(a["id"] == agent_id for a in agents)

    # 12. Colleague fetches manifest
    r = await client.get(f"/agents/{agent_id}/manifest",
        headers={"Authorization": f"Bearer {colleague_token}"},
    )
    assert r.status_code == 200
    assert "Lifecycle Agent" in r.json()["manifest_yaml"]

    # 13. Stats reflect new data
    r = await client.get("/admin/stats", headers=admin_headers)
    stats = r.json()
    assert stats["tenants"]["active"] >= 1
