"""Shared test fixtures for dialekt-cloud tests.

All async fixtures and tests share the session event loop to avoid
asyncpg pool / event loop mismatch (pools are tied to their creation loop).
"""
import asyncio
import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ─── Test DB config ──────────────────────────────────────────────────────────

TEST_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://dialekt_cloud:dialekt_cloud_pass@localhost:5433/dialekt_cloud_test",
)
TEST_ADMIN_KEY = "a" * 64
TEST_JWT_SECRET = "test_jwt_secret_for_ci"

# Set env vars BEFORE importing app modules
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["DIALEKT_ADMIN_KEY"] = TEST_ADMIN_KEY
os.environ["JWT_SECRET"] = TEST_JWT_SECRET
os.environ.setdefault("SMTP_HOST", "localhost")
os.environ.setdefault("SMTP_PORT", "1025")
os.environ.setdefault("SMTP_TLS", "false")
os.environ.setdefault("SMTP_USER", "")
os.environ.setdefault("SMTP_PASSWORD", "")
# Relax signup anti-abuse for tests — both ASGI test client and parallel
# test workers share the same IP (127.0.0.1) which would otherwise trip
# the 3-per-week production limit after the third signup test.
os.environ.setdefault("DIALEKT_SIGNUP_IP_LIMIT", "10000")
# Tests create admins via the helper fixture with throwaway @dialekt.ai
# emails. Production policy enforces @dias.now; we relax it here so the
# tests don't require knowledge of the production domain.
os.environ.setdefault("DIALEKT_ADMIN_EMAIL_DOMAIN", "")
# Don't spawn the lifecycle scheduler during tests — they invoke the
# scheduler pass directly when they want to verify behaviour.
os.environ.setdefault("DIALEKT_DISABLE_SCHEDULER", "true")
# Force dev mode so the production-readiness gate stays out of the way of
# tests, even when a real .env file in cwd has ENV=production set.
os.environ["ENV"] = "development"


def _can_connect_db() -> bool:
    try:
        import asyncpg
        async def _check():
            conn = await asyncpg.connect(TEST_DB_URL, timeout=3)
            await conn.close()
        asyncio.run(_check())
        return True
    except Exception:
        return False


DB_AVAILABLE = _can_connect_db()


# ─── Shared session event loop ───────────────────────────────────────────────
# asyncio_default_test_loop_scope = "session" in pyproject.toml ensures all
# async tests share the session loop (same loop as the asyncpg pool).

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ─── Mock email service ───────────────────────────────────────────────────────

class MockEmailService:
    def __init__(self):
        self.sent = []

    async def send(self, *, to, subject, template, context, from_addr=None, reply_to=None):
        self.sent.append({
            "to": to, "subject": subject,
            "template": template, "context": context,
            "from_addr": from_addr, "reply_to": reply_to,
        })
        return True

    async def send_invite(self, *, to, invite_token, company_name, landing_url):
        self.sent.append({"type": "invite", "to": to, "token": invite_token})
        return True

    async def send_license_activated(self, *, to, license_key, company_name, plan, seats, landing_url):
        self.sent.append({"type": "license_activated", "to": to, "key": license_key})
        return True

    async def send_welcome(self, *, to, company_name, landing_url):
        self.sent.append({"type": "welcome", "to": to})
        return True

    async def send_trial_expiring(self, **kwargs):
        self.sent.append({"type": "trial_expiring", **kwargs})
        return True

    async def send_license_extended(self, **kwargs):
        self.sent.append({"type": "license_extended", **kwargs})
        return True

    async def send_admin_signup_notification(self, **kwargs):
        self.sent.append({"type": "admin_signup_notification", **kwargs})
        return True

    async def send_admin_security_alert(self, **kwargs):
        self.sent.append({"type": "admin_security_alert", **kwargs})
        return True


# ─── Core fixtures ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def pool():
    if not DB_AVAILABLE:
        pytest.skip("PostgreSQL not reachable for dialekt-cloud tests")
    import asyncpg
    from dialekt_cloud.db import migrate
    p = await asyncpg.create_pool(TEST_DB_URL, min_size=2, max_size=10)
    await migrate(p)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="session")
async def app(pool):
    from dialekt_cloud.main import app as _app
    from dialekt_cloud.services import releases as _releases
    _app.state.pool = pool
    _app.state.email = MockEmailService()
    # Stub the GitHub-fetching releases service so tests don't hammer the
    # network and have deterministic download URLs to assert on.
    _releases._cache = {
        "at": float("inf"),  # never expire during test session
        "data": {
            "version": "v0.21.0",
            "published_at": "2026-04-25T00:00:00Z",
            "page_url": "https://github.com/dialektai/dialektai/releases/latest",
            "linux_deb_x86_64":  "https://github.com/dialektai/dialektai/releases/download/v0.21.0/dialekt_0.21.0_amd64.deb",
            "linux_deb_arm64":   "https://github.com/dialektai/dialektai/releases/download/v0.21.0/dialekt_0.21.0_arm64.deb",
            "linux_app_x86_64":  "https://github.com/dialektai/dialektai/releases/download/v0.21.0/dialekt_0.21.0_amd64.AppImage",
            "linux_app_arm64":   "https://github.com/dialektai/dialektai/releases/download/v0.21.0/dialekt_0.21.0_arm64.AppImage",
            "macos_dmg_arm64":   "https://github.com/dialektai/dialektai/releases/download/v0.21.0/dialekt_0.21.0_aarch64.dmg",
            "macos_dmg_x86_64":  "https://github.com/dialektai/dialektai/releases/download/v0.21.0/dialekt_0.21.0_x86_64.dmg",
            "windows_exe_x64":   "https://github.com/dialektai/dialektai/releases/download/v0.21.0/dialekt_0.21.0_x64-setup.exe",
            "windows_exe_arm64": "https://github.com/dialektai/dialektai/releases/download/v0.21.0/dialekt_0.21.0_arm64-setup.exe",
        },
    }
    return _app


@pytest_asyncio.fixture(scope="session")
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers():
    return {"X-Admin-Key": TEST_ADMIN_KEY}


# ─── Per-test fixtures ───────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def tenant_id(client, admin_headers):
    """Create a fresh tenant for each test that needs one."""
    import uuid
    unique = uuid.uuid4().hex[:8]
    r = await client.post("/admin/tenants", headers=admin_headers, json={
        "company_name": f"Test Corp {unique}",
        "admin_email": f"admin-{unique}@testcorp.kz",
        "plan": "team",
        "seats": 5,
    })
    assert r.status_code == 201, r.text
    return r.json()["tenant_id"]


@pytest_asyncio.fixture
async def active_tenant(client, admin_headers, tenant_id):
    """Create + activate a tenant, return {tenant_id, license_key}."""
    r = await client.post(f"/admin/tenants/{tenant_id}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"tenant_id": tenant_id, "license_key": data["license_key"]}


@pytest_asyncio.fixture
async def bearer_token(client, active_tenant):
    """Get a bearer token for the tenant admin."""
    r = await client.post("/auth/validate-license", json={
        "license_key": active_tenant["license_key"],
        "machine_id": "test-machine",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["valid"], "License should be valid"
    return data["bearer_token"]


@pytest_asyncio.fixture
async def auth_headers(bearer_token):
    return {"Authorization": f"Bearer {bearer_token}"}
