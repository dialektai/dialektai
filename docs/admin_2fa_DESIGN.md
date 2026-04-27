# Admin 2FA — Design Doc (Phase 1)

**Status:** Pre-implementation. Awaiting mentor APPROVE before any code lands.

**Owner:** Dias · **Reviewer:** mentor agent

**Scope:** Phase 1 only — replace static `DIALEKT_ADMIN_KEY` with email + argon2id password + TOTP for the founder admin (Dias). Phase 2 (tenant-owner 2FA) is **explicitly out of scope** — see §6.

---

## 1. Why this exists

The current admin auth is a single static 64-char `DIALEKT_ADMIN_KEY` env var. Worse, that key is rendered into `dashboard.html` via Jinja and used by client-side JS as `X-Admin-Key` on every API call. Any XSS, browser extension, screen-share during a customer demo, or `view-source` on the dashboard page = total compromise of the admin surface.

The dashboard sees: every customer's `admin_email`, `intended_use`, `country`, IP, full audit log, license keys, can extend tenants, generate invoices, suspend accounts. Blast radius = full customer book. Single static credential is unacceptable for that level of access.

This doc describes the replacement: a real `admins` table with email + password + TOTP, served via httpOnly session cookies, with the static env key demoted to break-glass-only.

## 2. Non-goals (do not do these now)

These are deliberately deferred or rejected per the mentor verdict:

- **No tenant-user 2FA.** Tenant users authenticate via license-key + machine_id binding; that's adequate. Bolting TOTP onto `validate-license` would break the offline-friendly UX with zero security gain. Defer indefinitely.
- **No tenant-owner web portal login.** That portal doesn't exist yet. When it does (M3 earliest), it gets its own 2FA design.
- **No WebAuthn / passkeys in v1.** TOTP first. Passkeys can be added as a parallel second factor in M3 if asked.
- **No second admin in v1.** Multi-admin requires its own threat model (mutual revocation, audit-trail-of-admin-acting-on-admin). Stay single-admin.
- **No SSO.** Enterprise tenant-side SSO is a separate plan-level feature.

## 3. Schema

```sql
CREATE TABLE IF NOT EXISTS admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,                     -- argon2id, includes salt + params
    totp_secret_encrypted TEXT,                      -- AES-GCM(base32 secret), NULL = not enrolled
    totp_enrolled_at TIMESTAMPTZ,                    -- NULL means user must enroll on next login
    backup_codes TEXT[],                             -- argon2id-hashed; one-shot use
    backup_codes_generated_at TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    last_login_ip TEXT,
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,                        -- progressive lockout after N failures
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Login audit (separate from founder_admin_log because that table tracks
-- post-auth admin ACTIONS; this tracks AUTH events themselves).
CREATE TABLE IF NOT EXISTS admin_login_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT,                                      -- nullable — failed-on-bad-email case
    ip TEXT,
    user_agent TEXT,
    stage TEXT NOT NULL,                             -- 'password' | 'totp' | 'backup_code'
    succeeded BOOL NOT NULL,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_login_attempts_email_time ON admin_login_attempts(email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_login_attempts_ip_time ON admin_login_attempts(ip, created_at DESC);
```

**Bootstrap:** on first cloud start with a fresh DB, if `admins` is empty, create one row from env vars `DIALEKT_BOOTSTRAP_ADMIN_EMAIL` + `DIALEKT_BOOTSTRAP_ADMIN_PASSWORD` (argon2id-hashed at insert). After that the env-bootstrap path is inert. `DIALEKT_ADMIN_KEY` env stays defined but is **break-glass only** (see §5).

## 4. Login flow state machine

```
[anon]
   │
   ├─→ POST /admin/login {email, password}
   │      ├─ wrong creds → 401 + log + bump failed_attempts (lockout at 5/15min)
   │      └─ correct → if totp_enrolled_at IS NULL:
   │                       → return {next: "enroll_totp", challenge_token}
   │                   else:
   │                       → return {next: "totp_challenge", challenge_token}
   │
   ├─→ POST /admin/login/totp {challenge_token, code}
   │      ├─ wrong → 401 + log + bump failed_attempts
   │      ├─ valid TOTP → set httpOnly cookie + 200 {ok: true}
   │      └─ valid backup_code → mark used + set cookie + 200 {ok: true, backup_codes_remaining: N}
   │
   └─→ POST /admin/login/enroll-totp {challenge_token, password_reconfirm}
          → return {provisioning_uri, qr_data_url, secret_b32}
       POST /admin/login/enroll-totp/confirm {challenge_token, code}
          → on first valid code, persist totp_secret + enrolled_at + generate
            10 backup codes, return them plaintext ONCE in response
            (frontend offers a "Download backup codes" button)
```

**State machine notes:**

- `challenge_token` is a short-lived (5min) HMAC-signed JWT containing `{stage, admin_id, exp}`. Issued only after password success. Required on subsequent `/totp` and `/enroll-totp` calls. Cannot be reused.
- TOTP window: 30 seconds, ±1 step skew tolerance (so total accepted window is 90 seconds — clock-drift forgiveness).
- After 3rd password failure: 15-minute lockout via `locked_until`. After 6th in 24h: 1-hour lockout.
- After successful login: clear `failed_attempts`, set `last_login_at` + `last_login_ip`, log to `admin_login_attempts`.
- Session cookie: `dialekt_admin_session` (already exists), `httpOnly + Secure + SameSite=Strict`, 4h TTL. Sliding refresh on each authenticated API call.

## 5. Break-glass (env-key fallback)

The static `DIALEKT_ADMIN_KEY` env var is **kept** but its semantics change:

- It NO LONGER works as a credential for the dashboard (no rendering into HTML, no client-side JS use of `X-Admin-Key`).
- It DOES still work for direct API calls (`X-Admin-Key` header). This is the break-glass for "Dias lost his phone AND backup codes AND can't SSH".
- A SHA-256 of the env value is logged on every break-glass use to `admin_login_attempts` with `stage='break-glass-key'`.
- On launch, if `admins` is empty AND env-key is unset, server refuses to start with a clear error message.

**Why keep it:** the alternative is an unrecoverable lockout if all factors are lost simultaneously. Documenting the break-glass in the runbook with a strong rotation policy is safer than no fallback.

## 6. Recovery — the human paths

**Lost phone (TOTP), have backup codes:** use a backup code on the login page. After login, regenerate: `POST /admin/totp/regenerate-backup-codes`.

**Lost phone AND lost backup codes, have password + SSH:** SSH to the server, run:
```bash
$ uv run dialekt-admin reset-2fa --email=dias@dias.now
TOTP secret cleared. Next login will trigger re-enrollment.
```

**Lost everything (password + phone + backup + SSH):** in theory only the env-key break-glass remains. Mitigations:
- Document `DIALEKT_ADMIN_KEY` in a password manager (1Password / Bitwarden) with a separate vault.
- Rotate the env key every 90 days. (Manual reminder in the runbook.)

## 7. UI changes (`templates/admin/login.html` + `dashboard.html`)

- `login.html`: replace single-field "admin key" form with email + password form. After submission, swap form for TOTP-code field if status code says so. After TOTP success, redirect to dashboard.
- `dashboard.html`: **REMOVE** `admin_key={{ admin_key | tojson }}` line. The Alpine.js `headers` object becomes `{ 'Content-Type': 'application/json' }` only — auth comes from the httpOnly cookie. All API calls must accept the cookie path.
- Add a "Security" tab to the dashboard for: changing password, regenerating backup codes, viewing login history (`admin_login_attempts` for own admin_id).

## 8. Crypto + library choices

- Password hash: **argon2id** via `argon2-cffi`. Params: `time_cost=3, memory_cost=64MB, parallelism=4`. (OWASP 2024 baseline.)
- TOTP: **`pyotp`** (RFC 6238). 6-digit codes, 30s period. Provisioning URI format: `otpauth://totp/dias.now:dias%40dias.now?secret=BASE32&issuer=dias.now`.
- TOTP secret encryption at rest: **AES-256-GCM** with key from `DIALEKT_ADMIN_TOTP_KEY` env var (32 bytes, base64). Rotation runbook: re-encrypt all `totp_secret_encrypted` rows in a single migration.
- Backup codes: 10 codes, 8 chars `[A-Z0-9]` (no ambiguous chars: no 0/O/1/I/L). Hashed with argon2id. Plaintext shown ONCE at generation time, downloadable as `dialekt-admin-backup-codes-YYYYMMDD.txt`.
- QR code: server generates SVG inline via `qrcode[svg]` lib (no external image fetches).

## 9. Endpoints to add

```
POST   /admin/login                       # email + password → challenge_token + next stage
POST   /admin/login/totp                  # challenge_token + 6-digit code → session cookie
POST   /admin/login/backup-code           # challenge_token + 8-char code → session cookie + N remaining
POST   /admin/login/enroll-totp           # challenge_token + password_reconfirm → QR + secret
POST   /admin/login/enroll-totp/confirm   # challenge_token + first code → 10 backup codes (plaintext, ONE TIME)

POST   /admin/totp/regenerate-backup-codes   # authenticated → 10 fresh codes (invalidates old)
POST   /admin/password/change                 # authenticated, requires old + new pw
GET    /admin/security/login-history          # authenticated, last 50 attempts for own admin
```

The existing `POST /admin/login` is replaced. The existing `_require_admin` dependency stays — it just reads the cookie now instead of checking the static key.

## 10. CLI tool

Extend the existing `dialekt-admin` console script with:

```
dialekt-admin admin create --email=... --password-prompt
dialekt-admin admin reset-2fa --email=...
dialekt-admin admin reset-password --email=... --password-prompt
dialekt-admin admin list
```

All run against the DB directly (no HTTP path). Must be invoked over SSH. Logged to `founder_admin_log`.

## 11. Tests

```
test_admin_login_with_password_then_totp_succeeds
test_admin_login_wrong_password_404_logged
test_admin_login_locked_after_5_failures
test_admin_login_unlock_after_window
test_admin_totp_window_skew_tolerance         # ±30s clocks
test_admin_backup_code_one_shot
test_admin_backup_code_after_use_is_invalid
test_admin_regenerate_backup_codes_invalidates_old
test_admin_first_login_triggers_totp_enrollment
test_admin_password_change_requires_old_password
test_admin_session_cookie_httponly_secure_samesite
test_dashboard_html_does_not_contain_admin_key   # P0 regression guard
test_break_glass_key_logs_to_login_attempts
test_admin_endpoint_unauthenticated_returns_401
test_cli_reset_2fa_clears_secret
```

## 12. Rollout

1. Deploy schema migration (idempotent, adds tables only).
2. Deploy backend with new endpoints. Existing `_require_admin` continues to accept env-key during the migration window.
3. Run CLI: `dialekt-admin admin create --email=dias@dias.now --password-prompt`.
4. First login from browser triggers TOTP enrollment; download backup codes.
5. Deploy updated dashboard.html (no admin_key in HTML, cookie-only auth).
6. Restart server with `DIALEKT_ADMIN_KEY` rotated to a new value (so the old shared key stops working everywhere). New value is the break-glass-only key.

## 13. Effort estimate

~1 engineering day:

- DB migration: 1h
- Endpoints + state machine: 4h
- Argon2/TOTP/AES-GCM glue + tests: 2h
- UI rework (login.html, dashboard.html cookie-auth): 2h
- CLI: 1h

## 14. Resolved design decisions (mentor APPROVE 2026-04-25)

1. **Break-glass:** keep `DIALEKT_ADMIN_KEY` as header-only break-glass. **Additional constraint from mentor:** break-glass path MUST NOT mint a session cookie — it stays per-request header auth only. Prevents accidental re-introduction of cookie minting via this path if a render bug surfaces later.
2. **Lockout policy:** 3/15min → 6/1h accepted as written. **Mentor add-on:** also enforce IP-based lockout alongside email-based (use existing `idx_admin_login_attempts_ip_time` index). Single email + multi-IP attempts is the credential-stuffing signal.
3. **Cookie TTL:** 4h sliding, accepted. Don't extend to 24h. Asymmetric trade (Dias pays the friction; every customer benefits from shorter compromise window).
4. **Backup codes shown once:** confirmed. **Mentor add-on:** "Download backup codes" button must trigger client-side blob download (no server roundtrip on download) so plaintext never re-enters server memory.
5. **WebAuthn:** confirmed out of scope. Revisit in M3 only if a pilot customer asks.

---

**Status: APPROVED for implementation.** Mentor will re-review before PR merge.

Implementation order (mentor-specified):
1. Schema migration
2. CLI `dialekt-admin admin create`
3. Endpoints + state machine
4. Tests — write `test_dashboard_html_does_not_contain_admin_key` FIRST (watch it fail), then fix
5. UI rework
6. Rotate `DIALEKT_ADMIN_KEY` to a fresh value (old shared key stops working everywhere)

---

## 15. Post-merge mentor reviews

### Round 1 — 2026-04-25 — APPROVE Phase 1 (single-admin)

14 admin-2FA tests + P0 regression guard, 103 cloud-test suite green. Three follow-ups identified and tracked for the v1.1 multi-admin work below.

### Round 2 — 2026-04-25 — APPROVE multi-admin v1.1

All three follow-ups closed in the same session per Dias's "make it 100% ready including multi-admin" directive. Mentor verdict: **"Ship it."**

What landed:

**[P1 closed] `admin_id` baked into session token payload.** `create_admin_session_token` signature is now `(admin_id, email, secret)` — keyword-only. `verify_admin_session_token` returns the payload `dict | None` (replacing the old bool). `_require_admin` builds an `AdminContext` (via, admin_id, email). `_require_identified_admin` is a stricter dep that rejects break-glass auth on endpoints that mutate the acting admin's state. `regenerate-backup-codes` resolves target via `ctx.admin_id` — never `LIMIT 1`. Multi-admin isolation directly tested.

**[P2.a closed] Password reconfirm gate on regenerate-backup-codes.** New `RegenerateBackupCodesRequest` Pydantic schema requires `password_reconfirm`. Three test cases: missing field → 422, wrong password → 401, correct → 200 + 10 fresh codes. Mirrors the enroll-totp gate.

**[P2.b closed] `DIALEKT_ADMIN_KEY` removed from session-token signing material.** Signing now uses `secret + "_admin_session"` (domain-separated derivation from JWT_SECRET). The old admin-key parameter doesn't exist in the new signature. Token survives admin-key rotation by construction.

New endpoints:
- `GET /admin/me` — who am I, with via-path + 2FA status + backup-codes-remaining (returns `admin_id: null` for break-glass)
- `POST /admin/totp/regenerate-backup-codes` — password-gated, multi-admin safe
- `POST /admin/password/change` — password change with old-password gate, ≥12 char minimum
- `GET /admin/security/login-history` — last 50 attempts for the acting admin

Test math: 103 + 9 multi-admin + 3 token-shape − 3 rewritten = **112 passed**.

Migration impact: any pre-v1.1 cookie shape is rejected on first hit (no admin_id, signing material differs). All currently-logged-in admins (count: 0 today) re-login. Acceptable — security trumps continuity for an unbreached cookie format.

### Round 3 — 2026-04-25 — Domain policy + frontend self-service

Per Dias's directive ("admin emails always @dias.now, primary is zhumagaliyev@dias.now") and the "front тоже готов?" check.

**Domain policy:** new env var `DIALEKT_ADMIN_EMAIL_DOMAIN` (default `@dias.now`) gates admin creation at two layers:
- CLI `dialekt-admin admin create` — refuses non-policy emails before insert
- `POST /admin/login` — refuses non-policy emails with the same `401 Invalid email or password` (no leak about whether the row exists vs. policy mismatch); failure logged with `failure_reason="domain_policy"`

Tests run with `DIALEKT_ADMIN_EMAIL_DOMAIN=""` (no restriction) so throwaway `@dias.now` admins still work; two new tests pin the policy when active.

**Frontend self-service** — Security tab in `templates/admin/dashboard.html`:
- Topbar shows current admin email + `BREAK-GLASS` badge if env-key auth path
- 🔒 БЕЗОПАСНОСТЬ tab in sidebar (only visible when `me.admin_id` is set — hidden under break-glass)
- "МОЙ АККАУНТ" card — email, auth-path, TOTP enrolled, backup codes remaining, last login + IP
- "СМЕНИТЬ ПАРОЛЬ" form — old + new + confirm, ≥12 chars, calls `POST /admin/password/change`
- "РЕГЕНЕРАЦИЯ BACKUP-КОДОВ" — password-gated, shows 10 fresh codes inline, client-side blob `.txt` download
- "ИСТОРИЯ ВХОДА" table — last 50 attempts (per-admin via `email` filter)
- Logout link in topbar

Test count: 112 + 2 (domain policy) = **114 passed**.

### Primary admin bootstrap (production)

```bash
# On the cloud host, after deploy:
ssh dias-server
cd /home/dias/projects/desktop/dialekt/dialekt-cloud
source venv/bin/activate
DATABASE_URL='postgresql://...' \
  uv run dialekt-admin admin create --email=zhumagaliyev@dias.now
# Type strong password (≥12 chars). The password is argon2id-hashed at insert.
```

Then visit `https://admin.dias.now/admin/ui/login`, sign in with email + password, scan QR, save the 10 backup codes to 1Password / Bitwarden, and you're in.

To add a second admin later (e.g. ops co-founder):

```bash
uv run dialekt-admin admin create --email=second.person@dias.now
```

The multi-admin isolation tests guarantee that one admin's actions on `regenerate-backup-codes` / password change / login history won't bleed into another's.

### What's locked & shipped

- `admins` + `admin_login_attempts` tables (idempotent migration)
- argon2id passwords + AES-256-GCM TOTP secrets + argon2id backup codes
- 4-stage state machine: password → challenge_token (HMAC, 5min, stage-discriminated) → TOTP/backup → httpOnly cookie
- 3/15min burst lockout, 6/1h hard lockout, env-overridable
- Break-glass `X-Admin-Key` header (NEVER mints a cookie, NEVER renders to HTML)
- CLI: `dialekt-admin admin {create, list, reset-2fa, reset-password, unlock}` — DB-only, SSH-only
- Login UI: 4 stages (password / TOTP / enroll / backup-codes-display) with client-side blob download
- 14 dedicated tests including `test_dashboard_html_does_not_contain_admin_key` regression guard

### Deployment runbook (Dias)

1. Pull main, deploy schema migration (idempotent — adds tables, no DROPs).
2. Deploy backend with new admin auth.
3. SSH to host: `dialekt-admin admin create --email=dias@dias.now`. Set strong password.
4. Visit `https://admin.dias.now/admin/ui/login` from a clean browser. Sign in. First login triggers TOTP enrollment — scan QR with Google Authenticator / 1Password / Authy.
5. Download the 10 backup codes (.txt) at the prompt. Store in 1Password / Bitwarden in a "dialekt break-glass" vault.
6. Generate a fresh `DIALEKT_ADMIN_TOTP_KEY` (32 bytes base64): `python -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())'`. Update `.env` and restart.
7. Rotate `DIALEKT_ADMIN_KEY` to a fresh 64-char string. Document in 1Password as break-glass-only.
