# dialekt-cloud — Production Deployment Runbook

**Last updated:** 2026-04-25
**Target:** `api.dias.now` (single-host Docker Compose)
**Estimated time:** 25–35 min cold, 5 min if you've done it before
**Risk:** medium — first deploy invalidates all existing admin sessions

This runbook walks one operator (Dias) through deploying the v0.22 release of `dialekt-cloud` from a clean checkout to a fully-running, production-ready service: license issuance + multi-LLM catalog + email lifecycle + admin 2FA + multi-admin readiness.

> **Heads up — breaking change.** This release replaces the static `DIALEKT_ADMIN_KEY`-as-credential model with email + argon2id password + TOTP, and changes the session-cookie signing scheme. **Every existing admin session cookie will be rejected on first hit** after deploy. The break-glass `X-Admin-Key` header still works as fallback, but you'll need to log in fresh through the new flow.

---

## 0. Pre-flight checklist

Before touching anything in production, verify on your laptop:

```bash
ssh dias-server 'whoami && hostname && df -h /home/dias'
ssh dias-server 'docker ps --filter name=dialekt'   # current containers
ssh dias-server 'cd ~/projects/desktop/dialekt && git log --oneline -3'
```

You should see:
- 4 dialekt containers running (`dialekt-api`, `dialekt-db`, `dialekt-landing`, `dialekt-cloud-test-pg`)
- Last commit is the v0.21 release or earlier (so this deploy is forward-progress, not a re-run)
- ≥5 GB free in `/home/dias`

If you don't have ≥5 GB free, prune Docker first: `docker system prune -af --volumes`. **Do not run prune without confirming `docker volume ls` first** — `dialekt-cloud_pgdata` is the production database; losing it loses every tenant + license + audit log.

---

## 1. Generate the three new secrets

These are the secrets the `assert_production_ready()` gate refuses to boot without. Generate them locally first, paste into `.env` later — never store in chat or git.

```bash
# JWT_SECRET — 48 bytes, base64. Used for tenant bearer tokens AND admin
# session cookies (domain-separated internally).
python3 -c 'import os, base64; print(base64.b64encode(os.urandom(48)).decode())'

# DIALEKT_ADMIN_KEY — 64-char break-glass key. Hex or base64 both fine, just
# not the string "aaaa..." that the dev default uses.
python3 -c 'import os; print(os.urandom(32).hex())'

# DIALEKT_ADMIN_TOTP_KEY — 32 bytes base64. AES-256-GCM key encrypting
# admins.totp_secret_encrypted at rest. MUST decode to exactly 32 bytes.
python3 -c 'import os, base64; print(base64.b64encode(os.urandom(32)).decode())'
```

Save all three in 1Password (or Bitwarden, etc.) under separate items:
- `dialekt-cloud · JWT_SECRET`
- `dialekt-cloud · DIALEKT_ADMIN_KEY (break-glass)`
- `dialekt-cloud · DIALEKT_ADMIN_TOTP_KEY`

The break-glass key has its own runbook (rotate every 90 days, document SHA-256 in 1Password).

---

## 2. Zoho SMTP — generate app password

The application password Dias mentioned earlier (`dWj01k253Gm5`) **must be revoked** before this deploy if it's ever been pasted into a chat / log / commit. Generate a fresh one:

1. Go to <https://accounts.zoho.com/home#sieve>
2. **Mail → Settings → Security → Application Passwords**
3. Revoke any existing password named "dialekt-cloud SMTP" (if rotating)
4. Click **Generate** → give the new password a label like `dialekt-cloud SMTP 2026-04`
5. Copy the password (Zoho shows it once)
6. Save in 1Password as `dialekt-cloud · SMTP_PASSWORD`

You can sanity-check the credentials work *before* deploying by running this from your laptop:

```bash
python3 - <<'EOF'
import smtplib
s = smtplib.SMTP_SSL('smtp.zoho.com', 465, timeout=10)
s.login('zhumagaliyev@dias.now', 'PASTE_NEW_APP_PASSWORD')
s.quit()
print('Zoho SMTP login OK')
EOF
```

If login fails: re-generate, double-check `zhumagaliyev@dias.now` has SMTP access enabled in Zoho mail settings, ensure the alias `hello@`, `security@`, `privacy@`, `billing@` are all configured to point to that mailbox.

---

## 3. Deploy code

```bash
ssh dias-server
cd ~/projects/desktop/dialekt
git fetch origin
git status                                    # confirm clean
git log --oneline -5                          # confirm we're behind origin
git pull --ff-only origin main                # fast-forward only
```

If `git pull` is not fast-forward, **stop**. Investigate first — there's local state on the server.

---

## 4. Fill `.env` with real values

```bash
cd ~/projects/desktop/dialekt/dialekt-cloud
cp -n .env.example .env.new                   # don't overwrite existing .env
vim .env.new                                   # paste the secrets from §1 + §2
diff .env .env.new                             # eyeball the deltas
mv .env.new .env
chmod 600 .env                                 # restrict to owner
```

Required fills (paste into `.env`):

| Key | Source |
|---|---|
| `DATABASE_URL` | already there from previous deploy — keep |
| `DIALEKT_ADMIN_KEY` | §1 — break-glass |
| `JWT_SECRET` | §1 — JWT |
| `DIALEKT_ADMIN_TOTP_KEY` | §1 — AES-32 |
| `SMTP_PASSWORD` | §2 — fresh Zoho app password |
| `SMTP_USER` | `zhumagaliyev@dias.now` |
| `INVOICE_SELLER_BIN` | `260140001608` |
| `INVOICE_SELLER_IBAN` | when bank account opens |
| `ENV` | `production` |

Leave defaults for: `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_FROM_*`, `LANDING_URL`, `ADMIN_URL`, `DIALEKT_ADMIN_EMAIL_DOMAIN`.

---

## 5. Restart the API container

The lifespan-time production-readiness gate runs at boot. If anything's wrong, the container will refuse to start with a clear error. Watch logs as it comes up.

```bash
cd ~/projects/desktop/dialekt/dialekt-cloud
docker compose pull api      # pull rebuilt image if you have CI-built ones
docker compose up -d --build api
docker logs -f dialekt-api    # follow until you see "dialekt-cloud ready"
```

**Expected boot output (good case):**

```
INFO:dialekt_cloud.main:Starting dialekt-cloud (env=production)...
INFO:dialekt_cloud.main:running schema migrate
WARNING:dialekt_cloud.main:no admins in DB yet — dashboard login will refuse everyone
                          except the break-glass key. Bootstrap with:
                          dialekt-admin admin create --email=zhumagaliyev@dias.now
INFO:dialekt_cloud.services.scheduler:lifecycle scheduler: started
INFO:dialekt_cloud.main:dialekt-cloud ready
```

**Failure case 1 — production gate trips:**

```
ERROR:dialekt_cloud.main:Production-readiness check FAILED:
ERROR:dialekt_cloud.main:  - DIALEKT_ADMIN_TOTP_KEY is still the dev default
ERROR:dialekt_cloud.main:  - SMTP_PASSWORD is empty — admins and users will receive NO emails
RuntimeError: dialekt-cloud refuses to start in production with 2 unresolved issues
```

Fix `.env`, restart. The container is in a crash loop; `docker compose down api && docker compose up -d api` to retry cleanly.

**Failure case 2 — DB migration error:**

If the schema migration throws (rare; the migration is idempotent), the container also fails. Inspect: `docker exec -it dialekt-db psql -U dialekt_cloud dialekt_cloud -c "\d admins"`. The `admins` table must exist after the migration. If it doesn't, the deploy hit a pre-existing schema conflict — escalate to manual investigation.

---

## 6. Bootstrap the primary admin

This is the only step that runs the CLI directly against the DB. Required because there's no other way to create the first admin row (the `/admin/login` endpoint won't accept anyone if the table is empty).

```bash
docker exec -it dialekt-api uv run dialekt-admin admin create \
    --email=zhumagaliyev@dias.now
# Prompts for password twice — use a strong one (≥12 chars, mixed)
# Save in 1Password as `dialekt-cloud · admin password`
```

Expected output:

```
✓ Admin created · id=<uuid> email=zhumagaliyev@dias.now
  TOTP will be enrolled on first login.
```

Verify:

```bash
docker exec -it dialekt-api uv run dialekt-admin admin list
```

You should see one row with TOTP=`—` (not yet enrolled), no last login.

---

## 7. Existing admin sessions — handle the cookie invalidation

Per release notes: every pre-v0.22 admin session cookie is now signed with material that no longer exists in the new code path. Cookies fail `verify_admin_session_token()` → user bounces to `/admin/ui/login`.

**Impact today:** zero — there are no live admin sessions in production today (single admin is Dias, who hasn't been logging into anything since the dev key was the credential). On staging or re-deploys later: every logged-in admin re-logs in. Tell them in advance via the team chat.

**Optional:** explicitly broadcast invalidation by clearing the cookie cookie store (browsers will too on next visit). Not strictly necessary because verification refuses old cookies anyway.

---

## 8. First login + TOTP enrollment

From a clean browser on your laptop (not the server):

1. Go to `https://admin.dias.now/admin/ui/login`
2. Enter `zhumagaliyev@dias.now` + password from §6
3. Server returns `next: enroll_totp` → enrollment page renders QR + base32 secret
4. Open Google Authenticator / 1Password / Authy → scan QR
5. Type the 6-digit code → confirm
6. The page shows 10 backup codes — **click "Download as .txt"**
7. Save `.txt` immediately in 1Password as `dialekt-cloud · admin backup codes 2026-04` (drag and drop)
8. Click "I'VE SAVED THEM — CONTINUE" → dashboard renders

Verify the dashboard:

- Topbar shows `zhumagaliyev@dias.now` (NOT `BREAK-GLASS` badge — that would mean cookie auth failed)
- Sidebar has the `🔒 БЕЗОПАСНОСТЬ` tab (only visible when authenticated as identified admin)
- Click that tab → "МОЙ АККАУНТ" card shows TOTP=✓ enrolled, backup codes=10/10

---

## 9. Smoke-test the email pipeline

Send yourself a verify-email by signing up as a fake tenant on the landing:

```bash
# From your laptop:
curl -sX POST https://api.dias.now/auth/signup \
    -H 'Content-Type: application/json' \
    -d '{
        "email": "test-deploy@dias.now",
        "full_name": "Deploy Smoke Test",
        "intended_use": "Verifying SMTP after fresh deploy on 2026-04-25",
        "country": "KZ",
        "accept_tos": true,
        "tos_version": "1.0",
        "privacy_version": "1.0"
    }' | jq
```

Expected response (200):

```json
{
  "ok": true,
  "tenant_id": "...",
  "license_key": "dialekt_...",
  "expires_at": "2026-05-25T...",
  "verification_required": true,
  "message": "Trial created. Check your email to verify and activate your license."
}
```

Within 30 seconds, you should receive **two** emails to `hello@dias.now` (your alias):
1. The verify-email with download links + license key (`Subject: Welcome to dialekt.ai — your trial + downloads`)
2. The internal lead notification (`Subject: [lead] Deploy Smoke Test from KZ — dialekt.ai trial signup`)

Click the verify link — you should land on `/verify-email.html?token=...` and see the "Email verified" success state with the license key copy button.

If emails don't arrive in 60 seconds:

```bash
docker logs dialekt-api 2>&1 | grep -iE "email|smtp|verify"
# Look for: "Email sent to test-deploy@dias.now (template=verify_email, from=dialekt.ai <hello@dias.now>)"
# If you see "Failed to send email" — SMTP creds wrong or Zoho rate-limit
```

Check Zoho's sent folder at <https://mail.zoho.com> — if the email's there, it left dialekt-cloud successfully and the issue is downstream (recipient inbox, spam folder).

Cleanup the test tenant before going live:

```bash
# In the admin UI: Tenants → find "test-deploy@dias.now" → suspend or delete via SQL
docker exec -it dialekt-db psql -U dialekt_cloud dialekt_cloud \
    -c "DELETE FROM tenants WHERE admin_email = 'test-deploy@dias.now';"
```

---

## 10. Smoke-test the security alerts

Trigger a password-changed alert on yourself to verify `security@dias.now` routing:

1. In the dashboard, go to 🔒 БЕЗОПАСНОСТЬ → СМЕНИТЬ ПАРОЛЬ
2. Enter old password + new password (≥12 chars) twice
3. Click "СМЕНИТЬ ПАРОЛЬ" → "✓ Пароль обновлён"
4. Within 30 seconds, you should receive an email at `zhumagaliyev@dias.now`:
   - `Subject: [security] Your dialekt.ai admin password was changed`
   - `From: dialekt.ai security <security@dias.now>`

If the From address is `hello@dias.now` instead of `security@dias.now`, the per-purpose routing failed — `SMTP_FROM_SECURITY` env var isn't being read. Re-check `.env` and restart.

---

## 11. Rotate `DIALEKT_ADMIN_KEY` (break-glass)

The dev default `aaaa...` is now rejected by the production gate — this only matters if some script or healthcheck still uses the OLD env value. Audit:

```bash
ssh dias-server
grep -rE "X-Admin-Key|DIALEKT_ADMIN_KEY" /home/dias/scripts/ 2>/dev/null
grep -rE "X-Admin-Key|DIALEKT_ADMIN_KEY" /home/dias/projects/ 2>/dev/null --include="*.sh"
```

If anything references the break-glass key (e.g. an old monitoring curl), update it to the new value from §1, otherwise it'll start failing.

---

## 12. Final verification checklist

Before you walk away from the laptop:

- [ ] `docker ps` shows `dialekt-api` running with status `(healthy)`
- [ ] `docker logs dialekt-api 2>&1 | tail -50` ends with `dialekt-cloud ready`, no ERROR lines after that
- [ ] `https://api.dias.now/health` returns `{"status":"healthy", ...}`
- [ ] `https://admin.dias.now/admin/ui/login` renders the email/password form
- [ ] Login as `zhumagaliyev@dias.now` works end-to-end (password → TOTP code → dashboard)
- [ ] Smoke-test email §9 received both emails
- [ ] Smoke-test security alert §10 received the security@-from message
- [ ] `dialekt-admin admin list` shows TOTP=✓ for the primary admin
- [ ] 10 backup codes saved in 1Password as a file
- [ ] All four secrets (`JWT_SECRET`, `DIALEKT_ADMIN_KEY`, `DIALEKT_ADMIN_TOTP_KEY`, `SMTP_PASSWORD`) saved in 1Password
- [ ] Test tenant from §9 deleted

---

## 13. First-week monitoring

Watch these for the first 7 days:

```bash
# Daily — check the lifecycle scheduler is firing
docker logs dialekt-api --since=24h 2>&1 | grep -i "lifecycle scheduler"
# Expect 24 hourly ticks and an occasional "sent N expiring emails" line.

# Daily — check for SMTP failures
docker logs dialekt-api --since=24h 2>&1 | grep -iE "Failed to send email|email send failed"

# Daily — check for production gate or security warnings
docker logs dialekt-api --since=24h 2>&1 | grep -iE "ERROR|production-readiness"

# Weekly — check the admin login history for unexpected IPs
# Open the dashboard → 🔒 БЕЗОПАСНОСТЬ → "ИСТОРИЯ ВХОДА"
# Or via SQL:
docker exec -it dialekt-db psql -U dialekt_cloud dialekt_cloud -c \
    "SELECT email, ip, stage, succeeded, failure_reason, created_at \
     FROM admin_login_attempts WHERE created_at > now() - interval '7 days' \
     ORDER BY created_at DESC LIMIT 50;"
```

Set a reminder on day 7 to actually look at these.

---

## 14. Rollback (if §5 or later catastrophically fails)

The previous version's container image is still on the host (Docker doesn't auto-prune on `compose up`). To roll back:

```bash
ssh dias-server
cd ~/projects/desktop/dialekt
git log --oneline -5
git checkout <previous-release-tag-or-sha>      # e.g. v0.21
cd dialekt-cloud
# Restore the previous .env (you DID back it up, right?)
mv .env .env.v0.22
mv .env.v0.21.backup .env       # or recreate from 1Password v0.21 snapshot
docker compose up -d --build api
docker logs -f dialekt-api
```

Schema-wise: the migration is forward-only but additive (new tables + new columns, no drops/renames). v0.21 code ignores the new columns — it'll keep working without them. **You don't need to roll back the DB.** Just the code.

If the rollback also fails: the dial-tone fallback is `docker compose down api && docker compose up -d db` to keep the database alive, then debug from clean.

---

## 15. Adding a second admin later

Once Dias has done §6–§8, adding additional admins is a one-liner per person:

```bash
docker exec -it dialekt-api uv run dialekt-admin admin create \
    --email=co-founder@dias.now
# Prompt for their password (or temp password to reset on first login)
```

The new admin logs in at `https://admin.dias.now/admin/ui/login`, enrolls their own TOTP, and sees only their own login history + their own backup codes regen. Multi-admin isolation is enforced by `_require_identified_admin` + cookie-derived `admin_id`.

---

## 16. Recovery — Dias loses both phone and backup codes

The only path back in is SSH:

```bash
ssh dias-server
docker exec -it dialekt-api uv run dialekt-admin admin reset-2fa \
    --email=zhumagaliyev@dias.now
# Confirms with a y/n prompt — TOTP secret cleared, backup codes wiped.
# Next login at /admin/ui/login triggers re-enrollment (scan new QR, save fresh codes).
```

If SSH is also unavailable: use `DIALEKT_ADMIN_KEY` as `X-Admin-Key` header on read-only and extend endpoints from any HTTP client. This **does NOT mint a session cookie** and **does NOT allow regenerate-backup-codes / password change / login history** — those endpoints reject break-glass via `_require_identified_admin`. So break-glass keeps the lights on but not the keys to your own account.

---

## Glossary of new env vars introduced in v0.22

| Name | Purpose | Required in prod |
|---|---|---|
| `DIALEKT_ADMIN_TOTP_KEY` | AES-256-GCM key for `admins.totp_secret_encrypted` | **yes** |
| `DIALEKT_ADMIN_EMAIL_DOMAIN` | Restrict admin emails to a domain (default `@dias.now`) | recommended |
| `DIALEKT_DISABLE_SCHEDULER` | Skip the trial-expiring scheduler (testing only) | no |
| `DIALEKT_ADMIN_LOCKOUT_BURST` | Failed-login attempts → 15-min lockout | no (default 3) |
| `DIALEKT_ADMIN_LOCKOUT_HARD` | Failed-login attempts → 1-hour lockout | no (default 6) |
| `DIALEKT_TOS_VERSION` | Authoritative ToS version stamped on consent | no (default `1.0`) |
| `DIALEKT_PRIVACY_VERSION` | Authoritative Privacy version stamped on consent | no (default `1.0`) |
| `SMTP_FROM_HELLO`/`SECURITY`/`PRIVACY`/`BILLING` | Per-purpose Zoho-alias From addresses | no (defaults provided) |
| `ADMIN_NOTIFY_TO` | Internal inbox receiving lead alerts + lockout broadcasts | no (default `hello@dias.now`) |

Production-gated: `JWT_SECRET`, `DIALEKT_ADMIN_KEY`, `DIALEKT_ADMIN_TOTP_KEY`, `SMTP_USER`, `SMTP_PASSWORD`, `DIALEKT_ADMIN_EMAIL_DOMAIN`, `INVOICE_SELLER_BIN`, `INVOICE_SELLER_IBAN`. The `assert_production_ready()` boot check refuses to start without all eight resolved.
