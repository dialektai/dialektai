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

-- Public agent library. Distinct from `agent_templates` (which is
-- tenant-private, used by agent_assignments). `library_entries` is the
-- public catalog any first-time visitor can read via /public/library
-- — no auth, rate-limited at the edge.
--
-- name/description/version are read from manifest_yaml at serve time
-- (we do NOT denormalize) — manifest is the single source of truth.
-- requires_connection / requires_mcp are computed from the manifest at
-- seed time and cached as columns purely so the catalog list page can
-- filter without parsing 100 YAML strings client-side.
--
-- Curation flow for v1: PRs add YAML + a row to `seeds/library/`. Cloud
-- redeploy refreshes the table. v2 will add a founder-admin UI.
CREATE TABLE IF NOT EXISTS library_entries (
    id TEXT PRIMARY KEY,             -- stable slug, e.g. "sql-analyst-postgres"
    manifest_yaml TEXT NOT NULL,
    category TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]',
    requires_connection BOOLEAN NOT NULL DEFAULT FALSE,
    requires_mcp BOOLEAN NOT NULL DEFAULT FALSE,
    signature TEXT,                  -- HMAC of manifest_yaml; desktop verifies on cache
    version TEXT NOT NULL DEFAULT '1.0.0',
    published BOOLEAN NOT NULL DEFAULT TRUE,  -- soft-hide without deletion
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_library_entries_category ON library_entries(category) WHERE published;
CREATE INDEX IF NOT EXISTS idx_library_entries_published ON library_entries(published);

-- Self-serve signup additions (v0.21).
-- ALTER inside DO blocks is idempotent (skips on duplicate_column).
DO $$
BEGIN
    BEGIN ALTER TABLE tenants ADD COLUMN email_verified_at TIMESTAMPTZ NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN signup_source TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN intended_use TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN country TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN trial_converted_at TIMESTAMPTZ NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenant_users ADD COLUMN full_name TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenant_users ADD COLUMN role_in_company TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    -- v0.22 expiring-trial scheduler dedup. Stores which milestones already
    -- triggered an email so the hourly task can't double-send. Format:
    -- '{"d7","d3","d1","d0"}' — one entry per fired email.
    BEGIN ALTER TABLE tenants ADD COLUMN expiring_notices_sent TEXT[] NOT NULL DEFAULT '{}'; EXCEPTION WHEN duplicate_column THEN NULL; END;
    -- Email locale. Drives which {en,ru} folder the mailer reads from.
    -- Set at signup from form (defaults country-based KZ/RU → 'ru' else 'en');
    -- admin can override later. CHECK constraint kept narrow — adding a new
    -- locale requires an explicit migration AND new template folder.
    BEGIN ALTER TABLE tenants ADD COLUMN locale TEXT NOT NULL DEFAULT 'en'; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD CONSTRAINT tenants_locale_chk CHECK (locale IN ('en','ru')); EXCEPTION WHEN duplicate_object THEN NULL; END;
    -- KZ legal billing details, used to render the "Покупатель" block on
    -- invoice PDFs. All nullable — drafts don't need them; admin fills
    -- before issuing the first invoice. talon_number is only meaningful
    -- for legal_form='ИП' (УВД-issued registration receipt — corporates
    -- don't have one).
    BEGIN ALTER TABLE tenants ADD COLUMN legal_form TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN bin TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN talon_number TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN postal_code TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN legal_address TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN phone TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN bank_iban TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN bank_name TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN bank_bik TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN kbe TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
    BEGIN ALTER TABLE tenants ADD COLUMN signatory_name TEXT NULL; EXCEPTION WHEN duplicate_column THEN NULL; END;
END $$;

-- Email verification tokens for self-serve signup. Separate from `invites`
-- because invites are admin-driven and don't need email verification.
CREATE TABLE IF NOT EXISTS email_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    verify_token TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '7 days',
    verified_at TIMESTAMPTZ
);

-- Anti-abuse for self-serve signup. Per-IP and per-email limits enforced
-- at endpoint level reading from this table.
CREATE TABLE IF NOT EXISTS signup_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    ip TEXT NOT NULL,
    user_agent TEXT,
    succeeded BOOL NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Terms-of-Service / Privacy Policy acceptance audit log.
-- KZ ПДн §6 + GDPR Art. 7 require provable consent: WHO + WHEN + WHAT
-- VERSION + HOW (IP/UA evidence). Append-only — re-acceptance after a
-- ToS/Privacy revision lands as a new row, never overwrites.
-- tenant_id is nullable for the rare case where signup fails after
-- consent but before tenant insert (we still want the consent on record).
CREATE TABLE IF NOT EXISTS tos_acceptances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL,
    email TEXT NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    tos_version TEXT NOT NULL,
    privacy_version TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT,
    source TEXT NOT NULL DEFAULT 'signup'  -- 'signup', 're-accept', 'admin-recorded'
);

CREATE INDEX IF NOT EXISTS idx_tenant_users_tenant ON tenant_users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invites_token ON invites(invite_token);
CREATE INDEX IF NOT EXISTS idx_agent_assignments_user ON agent_assignments(assigned_to);
CREATE INDEX IF NOT EXISTS idx_licenses_tenant ON licenses(tenant_id);
CREATE INDEX IF NOT EXISTS idx_email_verifications_token ON email_verifications(verify_token);
CREATE INDEX IF NOT EXISTS idx_email_verifications_tenant ON email_verifications(tenant_id);
CREATE INDEX IF NOT EXISTS idx_signup_attempts_email_time ON signup_attempts(email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signup_attempts_ip_time ON signup_attempts(ip, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tenants_admin_email ON tenants(admin_email);
CREATE INDEX IF NOT EXISTS idx_tos_acceptances_email ON tos_acceptances(email, accepted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tos_acceptances_tenant ON tos_acceptances(tenant_id);

-- ── Admin 2FA (Phase 1) ──────────────────────────────────────────────────
-- Replaces the static DIALEKT_ADMIN_KEY-as-credential model. The env var
-- is demoted to break-glass-only (header-auth, no cookie minting).
CREATE TABLE IF NOT EXISTS admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,                    -- argon2id, includes salt + params
    totp_secret_encrypted TEXT,                     -- AES-256-GCM(base32 secret), NULL = unenrolled
    totp_enrolled_at TIMESTAMPTZ,
    backup_codes TEXT[],                            -- argon2id-hashed, one-shot
    backup_codes_generated_at TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    last_login_ip TEXT,
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Auth-event audit (separate from founder_admin_log which tracks post-auth
-- ACTIONS; this tracks AUTH events themselves).
CREATE TABLE IF NOT EXISTS admin_login_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT,                                     -- null when bad-email
    ip TEXT,
    user_agent TEXT,
    stage TEXT NOT NULL,                            -- 'password' | 'totp' | 'backup_code' | 'break-glass-key'
    succeeded BOOL NOT NULL,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_admin_login_attempts_email_time ON admin_login_attempts(email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_login_attempts_ip_time ON admin_login_attempts(ip, created_at DESC);
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
