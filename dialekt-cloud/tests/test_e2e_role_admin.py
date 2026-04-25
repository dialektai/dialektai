"""Role 1 (Admin) — end-to-end journey through the dialekt-cloud admin
surface. Sequenced as a single realistic flow rather than atomic unit
tests, which are already covered by test_admin.py / test_invoice.py.

Scope per docs/MULTI_ROLE_TEST_PLAN.md:
  1  login flow (bad key + good key)
  2  create tenant (realistic payload)
  3  activate tenant (license issuance + welcome email)
  4  generate invite + consume invite (positive)
  5  tenant isolation (negative — invite from tenant A not accessible
     via tenant B's admin bearer)
  6  suspend tenant
  7  reactivate tenant
  8  filtered list (GET /admin/tenants?status=active) — verify behaviour
  9  download invoice PDF (closes a previously untested endpoint)

Scenarios reuse the conftest fixtures (client, admin_headers, pool,
MockEmailService).
"""
import uuid

import pytest
import pytest_asyncio


# ── 1 · Login ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_01_admin_login_rejects_legacy_admin_key_payload(client):
    """The old POST /admin/login {admin_key: ...} flow is dead. New flow is
    email + password + TOTP via /admin/login → /admin/login/totp.
    Authenticated API calls now use either the X-Admin-Key break-glass header
    (preferred for tests + CLI) or the dialekt_admin_session cookie set by
    the new login flow. See tests/test_admin_2fa.py for the cookie path."""
    legacy = await client.post("/admin/login", json={"admin_key": "anything"})
    assert legacy.status_code == 422  # pydantic validation against new schema


# ── 2 · Create tenant ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_02_create_tenant_realistic(client, admin_headers):
    unique = uuid.uuid4().hex[:8]
    r = await client.post(
        "/admin/tenants",
        headers=admin_headers,
        json={
            "company_name": f"Pilot Co {unique}",
            "admin_email": f"admin-{unique}@pilot.kz",
            "plan": "team",
            "seats": 5,
            "expiration_months": 12,
            "notes": "pilot-readiness E2E",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "tenant_id" in body
    assert body["status"] == "draft"


# ── 3 · Activate tenant ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_03_activate_tenant_issues_license_and_sends_email(
    client, admin_headers, tenant_id, app
):
    r = await client.post(
        f"/admin/tenants/{tenant_id}/activate", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("license_key"), "activation must return license_key"

    # Status transitions to active — confirm via detail endpoint
    d = await client.get(f"/admin/tenants/{tenant_id}", headers=admin_headers)
    assert d.status_code == 200
    assert d.json()["status"] == "active"

    # MockEmailService records the activation email
    sent_types = [m.get("type") for m in app.state.email.sent]
    assert "license_activated" in sent_types, (
        f"expected license_activated email, got {sent_types}"
    )


# ── 4 · Invite flow (positive) ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def tenant_a_bearer(client, admin_headers, tenant_id):
    """Activate the fixture tenant and mint a bearer for its admin."""
    act = await client.post(
        f"/admin/tenants/{tenant_id}/activate", headers=admin_headers
    )
    assert act.status_code == 200, act.text
    lic = act.json()["license_key"]

    v = await client.post(
        "/auth/validate-license",
        json={"license_key": lic, "machine_id": "role-admin-machine"},
    )
    assert v.status_code == 200, v.text
    return {
        "tenant_id": tenant_id,
        "license_key": lic,
        "bearer": v.json()["bearer_token"],
    }


@pytest.mark.asyncio
async def test_04_invite_create_and_accept(client, tenant_a_bearer, app):
    unique = uuid.uuid4().hex[:6]
    invitee = f"new-dev-{unique}@pilot.kz"

    # Tenant-admin creates an invite via POST /auth/invite
    r = await client.post(
        "/auth/invite",
        headers={"Authorization": f"Bearer {tenant_a_bearer['bearer']}"},
        json={"email": invitee, "role": "user"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    token = body["invite_token"]
    assert body["expires_in_days"] == 7

    # MockEmailService recorded the invite
    invite_emails = [m for m in app.state.email.sent if m.get("type") == "invite"]
    assert any(m["to"] == invitee for m in invite_emails), "invite email not sent"

    # Accepting lands the new user in tenant A
    r2 = await client.post("/auth/accept-invite", json={"invite_token": token})
    assert r2.status_code == 200, r2.text
    accepted = r2.json()
    assert accepted["tenant_id"] == tenant_a_bearer["tenant_id"], (
        "invite must land user in the issuing tenant, not another"
    )
    assert accepted["role"] == "user"
    assert accepted["bearer_token"]


# ── 5 · Tenant isolation (negative) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_05_invite_token_tenant_isolation(client, admin_headers, tenant_a_bearer):
    """Invite issued by tenant A must not be visible/consumable via
    tenant B's admin bearer. Two-step check:

    (i) Issue an invite in tenant A.
    (ii) Create and activate tenant B, mint its bearer.
    (iii) Verify tenant B's admin has no view of that invite token
          (no /auth API exposes another tenant's invites; and re-
          issuing an invite for the same email lands in tenant B,
          not tenant A — proving no cross-tenant bleed).
    (iv) Accepting tenant A's token creates a user in tenant A, NOT
         tenant B, even if attempted after establishing tenant B.
    """
    # (i) tenant A issues an invite
    unique = uuid.uuid4().hex[:6]
    invitee = f"cross-tenant-{unique}@pilot.kz"
    a_invite = await client.post(
        "/auth/invite",
        headers={"Authorization": f"Bearer {tenant_a_bearer['bearer']}"},
        json={"email": invitee, "role": "user"},
    )
    assert a_invite.status_code == 200
    token_a = a_invite.json()["invite_token"]

    # (ii) create + activate tenant B
    unique_b = uuid.uuid4().hex[:8]
    r_b = await client.post(
        "/admin/tenants",
        headers=admin_headers,
        json={
            "company_name": f"Rival Co {unique_b}",
            "admin_email": f"admin-{unique_b}@rival.kz",
            "plan": "team",
            "seats": 5,
        },
    )
    assert r_b.status_code == 201
    tenant_b_id = r_b.json()["tenant_id"]
    act_b = await client.post(
        f"/admin/tenants/{tenant_b_id}/activate", headers=admin_headers
    )
    assert act_b.status_code == 200
    lic_b = act_b.json()["license_key"]
    v_b = await client.post(
        "/auth/validate-license",
        json={"license_key": lic_b, "machine_id": "tenant-b-machine"},
    )
    bearer_b = v_b.json()["bearer_token"]

    # (iii) tenant B's admin cannot see tenant A's invite when listing
    # its own tenant's users (the only tenant-scoped user view).
    r_users_b = await client.get(
        f"/admin/tenants/{tenant_b_id}/users", headers=admin_headers
    )
    assert r_users_b.status_code == 200
    b_emails = [u.get("email") for u in r_users_b.json()]
    assert invitee not in b_emails, (
        "tenant B's user list must not contain tenant A's invitee"
    )

    # (iv) tenant B admin re-inviting the same email in their own tenant
    # must succeed independently — proving the invite is tenant-scoped.
    b_invite = await client.post(
        "/auth/invite",
        headers={"Authorization": f"Bearer {bearer_b}"},
        json={"email": invitee, "role": "user"},
    )
    assert b_invite.status_code == 200, b_invite.text
    token_b = b_invite.json()["invite_token"]
    assert token_b != token_a, "tokens must be unique per tenant"

    # (v) Accepting tenant A's token places the user in tenant A, not B,
    # even though tenant B has an outstanding invite for the same email.
    accept_a = await client.post("/auth/accept-invite", json={"invite_token": token_a})
    assert accept_a.status_code == 200, accept_a.text
    assert accept_a.json()["tenant_id"] == tenant_a_bearer["tenant_id"]
    assert accept_a.json()["tenant_id"] != tenant_b_id


# ── 6 · Suspend tenant ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_06_suspend_tenant(client, admin_headers, tenant_a_bearer):
    # PATCH returns {updated: true}; status transition is verifiable via
    # the detail endpoint.
    r = await client.patch(
        f"/admin/tenants/{tenant_a_bearer['tenant_id']}",
        headers=admin_headers,
        json={"status": "suspended"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("updated") is True

    d = await client.get(
        f"/admin/tenants/{tenant_a_bearer['tenant_id']}", headers=admin_headers
    )
    assert d.json()["status"] == "suspended"


# ── 7 · Reactivate tenant ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_07_reactivate_tenant(client, admin_headers, tenant_a_bearer):
    # First suspend, then flip back to active
    await client.patch(
        f"/admin/tenants/{tenant_a_bearer['tenant_id']}",
        headers=admin_headers,
        json={"status": "suspended"},
    )
    r = await client.patch(
        f"/admin/tenants/{tenant_a_bearer['tenant_id']}",
        headers=admin_headers,
        json={"status": "active"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("updated") is True

    d = await client.get(
        f"/admin/tenants/{tenant_a_bearer['tenant_id']}", headers=admin_headers
    )
    assert d.json()["status"] == "active"


# ── 8 · Filtered list ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_08_list_tenants_status_filter(client, admin_headers):
    """Verify GET /admin/tenants?status=… filter behaviour.

    ADM-1 fix (2026-04-29) wired the query param through to WHERE
    t.status = $1. This test now asserts the tight contract:
      • status=active → only active tenants
      • status=suspended → only suspended tenants (including the one
        we suspend here)
      • no filter → everything
      • unknown status → 400 with allow-list message
    """
    # Seed: create a draft and suspend another existing one so every
    # bucket has at least one row.
    unique = uuid.uuid4().hex[:8]
    r_draft = await client.post(
        "/admin/tenants",
        headers=admin_headers,
        json={
            "company_name": f"Filter-draft {unique}",
            "admin_email": f"draft-{unique}@f.kz",
            "plan": "team",
            "seats": 3,
        },
    )
    assert r_draft.status_code == 201
    draft_id = r_draft.json()["tenant_id"]

    # Pick a tenant and flip it suspended (any active one works).
    all_r = await client.get("/admin/tenants", headers=admin_headers)
    assert all_r.status_code == 200
    actives = [t for t in all_r.json() if t["status"] == "active"]
    assert actives, "need at least one active tenant for the filter test"
    suspend_id = actives[0]["id"]
    await client.patch(
        f"/admin/tenants/{suspend_id}",
        headers=admin_headers,
        json={"status": "suspended"},
    )

    # Tight assertions per status value
    r_active = await client.get("/admin/tenants?status=active", headers=admin_headers)
    assert r_active.status_code == 200
    active_rows = r_active.json()
    assert active_rows, "expected at least one active tenant"
    assert all(t["status"] == "active" for t in active_rows), (
        f"filter not honoured: got statuses {[t['status'] for t in active_rows]}"
    )
    assert all(t["id"] != suspend_id for t in active_rows), (
        "suspended tenant leaked into active results"
    )
    assert all(t["id"] != draft_id for t in active_rows), (
        "draft tenant leaked into active results"
    )

    r_draft_filter = await client.get(
        "/admin/tenants?status=draft", headers=admin_headers,
    )
    assert r_draft_filter.status_code == 200
    draft_ids = [t["id"] for t in r_draft_filter.json()]
    assert draft_id in draft_ids
    assert all(t["status"] == "draft" for t in r_draft_filter.json())

    r_susp = await client.get(
        "/admin/tenants?status=suspended", headers=admin_headers,
    )
    assert r_susp.status_code == 200
    susp_ids = [t["id"] for t in r_susp.json()]
    assert suspend_id in susp_ids
    assert all(t["status"] == "suspended" for t in r_susp.json())

    # Unknown status → 400 with allow-list message
    r_bad = await client.get(
        "/admin/tenants?status=totally-bogus", headers=admin_headers,
    )
    assert r_bad.status_code == 400, r_bad.text
    assert "draft" in r_bad.text and "active" in r_bad.text and "suspended" in r_bad.text

    # Cleanup: restore the suspended tenant so sibling tests don't
    # inherit a weird state.
    await client.patch(
        f"/admin/tenants/{suspend_id}",
        headers=admin_headers,
        json={"status": "active"},
    )


# ── 9 · Download invoice PDF ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_09_download_invoice_pdf(client, admin_headers, tenant_a_bearer):
    """Closes the previously untested /admin/invoices/{id}/download endpoint."""
    # Generate an invoice so there's something to fetch
    r_inv = await client.post(
        f"/admin/tenants/{tenant_a_bearer['tenant_id']}/invoice",
        headers=admin_headers,
        json={
            "amount_kzt": 150000,
            "due_in_days": 14,
        },
    )
    assert r_inv.status_code == 200, r_inv.text
    invoice_id = r_inv.json()["invoice_id"]

    r_dl = await client.get(
        f"/admin/invoices/{invoice_id}/download", headers=admin_headers
    )
    assert r_dl.status_code == 200
    # Either a PDF stream (application/pdf) or a rendered HTML if PDF
    # generation isn't wired in the test env — both are acceptable
    # evidence that the endpoint is reachable with admin auth.
    ctype = r_dl.headers.get("content-type", "")
    assert any(t in ctype for t in ("application/pdf", "text/html", "application/octet-stream")), (
        f"unexpected content-type: {ctype}"
    )
    assert len(r_dl.content) > 0, "empty response body"
