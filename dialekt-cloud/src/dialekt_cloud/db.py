"""asyncpg pool + schema bootstrap."""
import asyncpg

_pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    company_name TEXT NOT NULL,
    admin_email TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'team',
    seats_limit INT NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'draft',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS licenses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    license_key TEXT UNIQUE NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_validated_at TIMESTAMPTZ,
    active BOOL NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS tenant_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    invited_by UUID,
    invited_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    invite_accepted_at TIMESTAMPTZ,
    UNIQUE(tenant_id, email)
);

CREATE TABLE IF NOT EXISTS invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    invite_token TEXT UNIQUE NOT NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '7 days',
    accepted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    manifest_yaml TEXT NOT NULL,
    created_by UUID NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_template_id UUID NOT NULL REFERENCES agent_templates(id) ON DELETE CASCADE,
    assigned_to UUID NOT NULL,
    assigned_by UUID NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_pulled_at TIMESTAMPTZ,
    UNIQUE(agent_template_id, assigned_to)
);

CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invoice_number TEXT UNIQUE NOT NULL,
    amount_kzt DECIMAL(12,2) NOT NULL,
    seats INT NOT NULL,
    plan TEXT NOT NULL,
    period_months INT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at TIMESTAMPTZ,
    pdf_path TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS founder_admin_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_users_tenant ON tenant_users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invites_token ON invites(invite_token);
CREATE INDEX IF NOT EXISTS idx_agent_assignments_user ON agent_assignments(assigned_to);
CREATE INDEX IF NOT EXISTS idx_licenses_tenant ON licenses(tenant_id);
"""


async def get_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def migrate(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
