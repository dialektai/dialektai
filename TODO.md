# dialekt TODO — Stage 2 (v0.9)

Started: 2026-04-22 | Target: 13 weeks | Scenario: A (fulltime)

---

## IMMEDIATE (before first commit)

- [ ] Rotate PyPI token — was shared in plaintext
- [ ] Configure PyPI Trusted Publisher → vibecoderkz/dialekt-manifest-validator → publish.yml
- [ ] Create DIALEKT_STATE.md and keep updated every 2-3 days
- [ ] Create `feat/goal-1-agents` branch

---

## WEEK 1-2 — Goal 1: Agent as entity

### DB migration
- [ ] Design SQLite schema: `agents` table (id UUID v4, name, description, manifest_yaml, version, created_at, updated_at, status)
- [ ] Design `sessions` table update: add `agent_id` FK (nullable for migration)
- [ ] Write migration script: existing sessions → "General Assistant" default agent
- [ ] Write and run migration: `python python/migrate_sessions_to_agents.py`
- [ ] Add rollback migration script

### Agent model (Python backend)
- [ ] Create `python/agents.py` — CRUD: create_agent, get_agent, list_agents, update_agent, delete_agent, activate_agent
- [ ] Use `dialekt-manifest-validator` for import/export — no reimplementation
- [ ] Agent lifecycle: draft → published → archived
- [ ] REST endpoints: `GET /agents`, `POST /agents`, `GET /agents/{id}`, `PATCH /agents/{id}`, `DELETE /agents/{id}`
- [ ] Endpoint: `POST /agents/import` — accepts YAML file, validates via dialekt-manifest-validator, saves
- [ ] Endpoint: `GET /agents/{id}/export` — returns manifest YAML

### Two app modes (structural)
- [ ] Add `mode` field to config: `builder` or `user`
- [ ] First-launch screen: "Setting up dialekt for your team?" vs "Someone shared an agent with you?"
- [ ] Store mode in `~/.dialekt/config.json`
- [ ] Mode switch in Settings with confirmation dialog

### Frontend — agent entity
- [ ] `useAgents.js` hook — list, create, select, delete
- [ ] Left sidebar: "My Agents" section (Builder mode only)
- [ ] Agent list item: name, status badge (draft/published), last edited
- [ ] "+ New Agent" button → opens blank agent form (wizard in Week 10-11, for now: name + system_prompt fields only)
- [ ] Agent selector: clicking agent starts new session with that agent's system_prompt
- [ ] Session history grouped by agent

### Tests
- [ ] `tests/test_agents_api.py` — CRUD endpoints
- [ ] `tests/test_agent_import.py` — valid YAML imports, invalid YAML rejected
- [ ] `tests/test_migration.py` — existing sessions correctly migrated

---

## WEEK 3-5 — Goal 4a: SQL Analyst (PostgreSQL MCP)

### MCP server
- [ ] Create `python/mcp_servers/postgres_mcp.py`
- [ ] Connection pool per named connection (asyncpg)
- [ ] Credentials via OS keychain (`keyring` library) — never in manifest
- [ ] Tools exposed to agent:
  - [ ] `list_schemas()`
  - [ ] `list_tables(schema)`
  - [ ] `describe_table(schema, table)` — columns, types, nullable, default
  - [ ] `list_foreign_keys(schema, table)`
  - [ ] `sample_rows(schema, table, limit=3)`
  - [ ] `execute_query(sql)` — read-only enforced
- [ ] SQL parser: reject DDL (CREATE, DROP, ALTER) and DML (INSERT, UPDATE, DELETE)
- [ ] Row limit: default 1000, configurable per connection
- [ ] Query timeout: 30s default
- [ ] EXPLAIN for queries projected >10k rows — show in UI before execution

### Schema RAG
- [ ] Install `sqlite-vec` extension
- [ ] Embedding pipeline: `{schema}.{table}: {columns} | {sample_rows}` per table
- [ ] Model: `nomic-embed-text:v1.5` via Ollama
- [ ] Store embeddings in `~/.dialekt/schema_cache.db`
- [ ] Query: embed user input → retrieve top-10 tables → inject schema into context
- [ ] Cache TTL: 24h, invalidate on schema hash change
- [ ] `GET /connections/{id}/reindex` endpoint to force re-embed

### SQL Analyst manifest
- [ ] Write `agents/sql_analyst/manifest.yaml` — matches AGENT_MANIFEST_SPEC.md v1.0.1 exactly
- [ ] Write `agents/sql_analyst/system_prompt.md` — production prompt for qwen2.5-coder:32b
  - Shows SQL before executing
  - Asks clarifying questions for ambiguous requests
  - Handles Cyrillic identifiers
  - Formats results as table
  - Warns on expensive queries
  - Bilingual Ru/En
- [ ] Bundle manifest in app: auto-import on first launch if no agents exist

### Connection UI
- [ ] "Connections" section in Settings
- [ ] Add connection: name, type (PostgreSQL), host, port, database, username
- [ ] Password via OS keychain prompt (never shown again after save)
- [ ] Test connection button
- [ ] Connection list with status indicator

### Tests
- [ ] `tests/test_postgres_mcp.py` — tools, read-only enforcement, row limit
- [ ] `tests/test_schema_rag.py` — embedding, retrieval accuracy
- [ ] `tests/test_sql_safety.py` — DDL/DML rejection

---

## WEEK 6-7 — Goal 4a: MySQL + ClickHouse

- [ ] Create `python/mcp_servers/mysql_mcp.py` — same interface as postgres_mcp
- [ ] Create `python/mcp_servers/clickhouse_mcp.py` — same interface
- [ ] Abstract `BaseDatabaseMCP` class — tools identical, SQL dialect layer handles differences
- [ ] SQL dialect layer: date functions, LIMIT syntax, window functions per engine
- [ ] Connection type selector in UI: PostgreSQL / MySQL / ClickHouse
- [ ] Tests for each engine — same test matrix as PostgreSQL

---

## WEEK 8-9 — Goal 3: Cloud sync + Goal 6: Licensing

### dialekt-cloud repo
- [ ] Create new repo `dialektai/dialekt-cloud`
- [ ] FastAPI + asyncpg + PostgreSQL
- [ ] DB schema (6 tables): tenants, users, agent_templates, agent_assignments, subscriptions, audit_log
- [ ] Docker setup: `Dockerfile` + `docker-compose.yml`

### Deployment (home server)
- [ ] Deploy Docker on home server
- [ ] Cloudflare Tunnel → `api.dias.now`
- [ ] SSL automatic via Cloudflare
- [ ] Daily pg_dump → Wasabi S3
- [ ] UptimeRobot monitor on `/health`

### API endpoints
- [ ] `POST /auth/signup` — creates tenant + admin user
- [ ] `POST /auth/validate-license` — desktop startup check
- [ ] `POST /auth/invite` + `POST /auth/accept-invite`
- [ ] `GET /agents/assigned-to-me`
- [ ] `GET /agents/{id}/manifest` — validates on return via dialekt-manifest-validator
- [ ] `POST /agents/publish` — validates on receipt
- [ ] `POST /agents/assign`, `DELETE /agents/unassign`
- [ ] `GET /tenants/me/users`, `PATCH /tenants/me/users/{id}`, `DELETE /tenants/me/users/{id}`
- [ ] `GET /audit-log` (paginated)
- [ ] `GET /health`

### Auth
- [ ] HMAC-SHA256(license_key + user_id + timestamp) bearer tokens
- [ ] Token refresh logic

### Desktop cloud sync
- [ ] Sync service in backend: check for new assignments on startup + every 15min
- [ ] Offline cache: `~/.dialekt/agent_cache.db`
- [ ] Conflict resolution: last-write-wins, log conflicts
- [ ] Sync status indicator in UI (online/offline/syncing)

### Licensing
- [ ] License key generation (ULID-based, cryptographically random)
- [ ] Free tier: 3 seats
- [ ] Stripe integration: Team tier ($15/seat/mo)
- [ ] Stripe Customer Portal for self-service
- [ ] Seat enforcement: prevent invite if over limit

### Email (Resend)
- [ ] Signup confirmation email
- [ ] Invite email: bilingual Ru+En, download link + token
- [ ] License activation email

### Signup page (`app.dias.now/signup`)
- [ ] Simple HTML form: company name, email, password
- [ ] Email confirmation flow
- [ ] Post-signup: show license key + download link

---

## WEEK 10-11 — Goal 5: Builder UI wizard

### "My Agents" section
- [ ] Agent list with: name, assignments count, last edited, status badge
- [ ] "+ New Agent" primary button
- [ ] Agent detail view with tabs: Configuration / Assignments / Usage / History

### 9-step wizard
- [ ] Step 1: Start from template (SQL Analyst / Blank / Import YAML)
- [ ] Step 2: Basics — name, description, icon (emoji picker), tags, language
- [ ] Step 3: Model — preferred + acceptable picker, hardware requirements display, parameter sliders
- [ ] Step 4: System prompt — textarea with `{{variable}}` highlighting, variable panel, "Add variable" button
- [ ] Step 5: Connections & Permissions — capability matrix checkboxes, connection requirements builder
- [ ] Step 6: Input & Output — radio chat/form/no-input, form builder for form type, output format + destination pickers
- [ ] Step 7: Schedule — visual cron builder ("every day", "every weekday", "custom"), timezone dropdown
- [ ] Step 8: Test — sandbox runner (fill variables, see live response)
- [ ] Step 9: Save (local) or Publish (cloud upload + assign dialog)

### User mode
- [ ] Left panel: assigned agents grouped by "Shared by {admin}"
- [ ] Dynamic form renderer from `input.fields` in manifest
- [ ] Output renderers: table (sort/filter), markdown, file (download + preview), image, JSON viewer
- [ ] Past runs history (per user, per agent)
- [ ] Zero technical terminology visible

---

## WEEK 12 — Goal 7: Admin panel

### Users section
- [ ] Table: name, email, role, status (pending/active/disabled), last active
- [ ] Actions: change role, disable, remove, resend invite
- [ ] Filter by role/status, search by email

### Invites section
- [ ] List: email, sent_at, expires_at, status
- [ ] Actions: resend, cancel, extend expiry
- [ ] "+ New invite" dialog

### Agents overview
- [ ] All agent templates: name, author, assignments, last updated
- [ ] Admin can: reassign author, archive, view audit trail

### Billing
- [ ] Current plan display
- [ ] Seats used / limit
- [ ] Next renewal date
- [ ] "Manage subscription" → Stripe Customer Portal

### Audit log
- [ ] Paginated table: timestamp, user, action, target
- [ ] Events: user_invited, user_accepted, role_changed, user_removed, agent_published, agent_updated, agent_assigned, agent_unassigned, subscription_changed
- [ ] Export CSV

### Tenant settings
- [ ] Company name (editable)
- [ ] Default language
- [ ] Timezone
- [ ] Company logo (optional)

---

## WEEK 13 — Polish + Acceptance criteria

- [ ] AC1: Admin signup flow end-to-end (app.dias.now → install → build SQL agent → test → publish → assign)
- [ ] AC2: Colleague invite + User mode first run
- [ ] AC3: PostgreSQL + MySQL + ClickHouse same manifest
- [ ] AC4: 500+ table schema, RAG query <5s
- [ ] AC5: Offline — agents work, reconnect syncs
- [ ] AC6: Network monitor — no conversation/credentials in cloud
- [ ] AC7: "удали всех клиентов" → only SELECT generated, no DDL
- [ ] AC8: Admin manages users, audit log, subscription — no CLI
- [ ] AC9: Record developer building custom agent in <10 min
- [ ] AC10: Delivered within 13 weeks

---

## FOUNDER TASKS (parallel, not Claude Code)

- [ ] Cloudflare Tunnel setup for home server (api.dias.now, app.dias.now)
- [ ] Stripe account — start KZ verification NOW (may take 1-2 weeks)
- [ ] Resend.com account + SPF/DKIM/DMARC on dias.now
- [ ] Wasabi S3 account for backups
- [ ] UptimeRobot for api.dias.now/health
- [ ] Apple Developer Program ($99/yr) for macOS code signing
- [ ] Weekly 30-min sync with 3 alpha pilots
- [ ] Weekly update to We Love Claude series

---

## WEEKLY CHECK-IN FORMAT (Claude Code → Founder)

End of each week:
1. What shipped (specific commits/features)
2. What's blocked (specific issue, not vague)
3. Decisions needed from you (specific question, yes/no or A/B)
4. Divergences from spec (what changed and why)
