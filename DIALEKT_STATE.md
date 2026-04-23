# dialekt state, updated 2026-04-22

## Current stage
Stage 2 COMPLETE — All goals 1–8 done, dialekt-cloud service + admin panel, desktop↔cloud integration, MySQL/ClickHouse integration tests, Ollama heartbeat.

## Code state
- `dialektai/dialektai` main: v0.8.2
- `dialektai/dialekt-manifest-validator`: v0.1.0 on PyPI, 28/28 tests
- **203 Python tests passing** (13 integration auto-skipped without live DB)
- **22 dialekt-cloud tests passing** (34 skipped — need live PG)
- Frontend: clean Vite production build

## Goal 1 — COMPLETE ✓
- SQLite agents table + agent_bindings table (agent_id → connection_id + type)
- CRUD endpoints GET/POST/PATCH/DELETE /agents + GET/POST/DELETE /agents/{id}/binding
- Import/export via dialekt-manifest-validator
- Two app modes: GET/POST /config/mode
- resolve_agent_context() async lookup for template var substitution
- ModeSetupScreen.jsx first-launch selector; sessions grouped by agent in builder mode

## Goal 1 — Ollama lifecycle — COMPLETE ✓
- GET /ollama/check: {installed, running, version, install_url, platform}
- POST /ollama/start: starts daemon via subprocess
- GET /ollama/pull/stream?model=...: SSE stream of /api/pull progress
- OllamaInstallScreen.jsx: polls every 3s, handles install/start/running states
- DownloadScreen.jsx: SSE consumption with real layer-level progress tracking

## Goal 2 — License system — COMPLETE ✓
- GET /license/status, POST /license/save, POST /license/trial (30-day, 3 seats)
- LicenseScreen.jsx: validates against api.dialekt.ai/auth/validate-license
- InviteRedemptionScreen.jsx: accepts inv_ tokens from cloud service
- Manual activation flow: founder creates tenant → generates invoice → activates → system emails license_key

## Goal 4a — PostgreSQL MCP — COMPLETE ✓
(unchanged from previous)

## Goal 4b — MySQL MCP — COMPLETE ✓
(unchanged from previous)

## Goal 4c — ClickHouse MCP — COMPLETE ✓
(unchanged from previous)

## Goal 6 — Admin Dashboard Screen — COMPLETE ✓
- AdminDashboardScreen.jsx — 4 tabs: Users, Agents, Usage, Subscription
- Users tab: invite form (POST api.dialekt.ai/auth/invite) + member list
- Agents tab: list with export buttons
- Usage tab: StatCards + per-agent breakdown bars
- Subscription tab: plan info, seat count, contact link

## Goal 8 — LLM Performance Layer — COMPLETE ✓

### 8.1: Structured prompt templating
- `python/dialekt/llm/prompt_wrapper.py`
- `build_system_prompt()`: wraps in ROLE/LANGUAGE/OUTPUT FORMAT/CONTEXT/HISTORY/EXAMPLES
- `should_wrap()`: per-agent opt-out via `prompt_wrapping: false` in manifest YAML
- 24 tests passing

### 8.2: JSON schema constraints
- `output.format: json/table/markdown/file` in agent manifest drives OUTPUT FORMAT section
- System prompt injection enforces format at LLM level
- `make_interpreter()` reads `manifest.output.format`, passes to `build_system_prompt`

### 8.3: Self-correcting retry loop
- `python/dialekt/llm/retry_loop.py`
- `SQLRetryLoop`: validate_sql() EXPLAIN check → on failure inject error → retry (max 3)
- `RetryExhausted` exception with full attempts list

### 8.4: History summarization
- `summarize_history()` in prompt_wrapper.py (truncation-based, max_chars=1500)
- `ws_chat` join handler: if total session tokens > 6K, summarize old messages, keep last 10
- History summary injected into system prompt via `CONVERSATION HISTORY (summarized)` section

### 8.5: Few-shot memory
- `python/dialekt/llm/few_shot_memory.py`: SQLite DB at `~/.dialekt/few_shots.db`
- `save_interaction(agent_id, question, answer)`: embeds question with nomic-embed-text
- `get_few_shots(agent_id, query, k=3)`: cosine similarity search; falls back to most-recent
- `ws_chat` join handler: retrieves few-shots for the current agent + last user message
- `ws_chat` run_oi: saves interaction after AI response (non-empty, agent-scoped)
- 11 new tests passing

## dialekt-cloud — COMPLETE ✓
- `/home/dias/projects/desktop/dialekt/dialekt-cloud/`
- FastAPI + asyncpg, 8 tables: tenants, licenses, tenant_users, invites, agent_templates, agent_assignments, invoices, founder_admin_log
- HMAC-SHA256 bearer tokens (24h TTL), master-secret approach (no per-request DB lookup)
- SMTP via aiosmtplib: bilingual invite (RU/EN), license-activated email
- WeasyPrint PDF: Kazakhstan standard invoice (INV-YYYY-NNNN)
- Routers: auth, agents, admin (JSON API), admin_ui (HTML SPA at /admin/ui)
- Admin panel: Alpine.js SPA with stats, tenant CRUD, activate/suspend/invoice, cookie session auth
- CLI: `dialekt-admin` Click CLI (list/create/activate/suspend/invoice/stats)
- 22 passing tests (34 skipped — need live PG for DB-backed tests)

## CI/CD — COMPLETE ✓
- `.github/workflows/ci.yml`: unit-tests + frontend-build + integration-tests + cloud-tests
- `.github/workflows/release.yml`: macOS universal DMG + AppImage + deb + msi
- `docs/RELEASE.md`: full release procedure
- `docs/adr/ADR-001-invoice-billing.md`: no Stripe, KZ bank transfer
- `docs/adr/ADR-002-llm-performance-layer.md`: prompt wrapping architecture

## Onboarding flow — COMPLETE ✓
- App.jsx: license → mode → OllamaGateway → model picker (step3) → perms (step4) → first chat (step5)
- OnboardingPermsScreen: step={4}, onCtaClick=onComplete (navigation loop fixed 2026-04-22)
- OnboardingScreen: "Download & continue" / "Skip for now" → onboarding-step4 (fixed)

## Builder Wizard — COMPLETE ✓
(unchanged)

## Admin Panel (Settings) — COMPLETE ✓
(unchanged)

## Cloud Sync — SKELETON ✓
(unchanged)

## Integration tests
- `tests/integration/docker-compose.yml`: postgres 15432, mysql 13306, clickhouse 18123
- `seed/postgres_seed.sql`: ecom + analytics schemas, 1000+ rows
- `seed/mysql_seed.sql`: same schema adapted for MySQL 8.0
- `seed/clickhouse_seed.sql`: same schema in ClickHouse MergeTree format
- `test_pg_integration.py`: 15 tests, auto-skip without live PG
- `test_mysql_integration.py`: 13 tests, auto-skip without live MySQL
- `test_clickhouse_integration.py`: 11 tests, auto-skip without live ClickHouse

## Test Summary (203 python + 22 dialekt-cloud)
- test_agents.py, test_config_mode.py, test_connections.py
- test_schema_rag.py (12), test_mysql_mcp.py (11), test_clickhouse_mcp.py (9)
- test_import_yaml.py (8), test_admin_and_sync.py (11)
- test_prompt_wrapper.py (24), test_retry_loop.py (12), test_new_endpoints.py (16)
- **test_few_shot_memory.py (11) — NEW**
- tests/integration/ (39 total, auto-skipped without live DBs)
- dialekt-cloud: test_tokens.py (12), test_admin.py (10 real + 34 DB-skipped)

## Goal 1.7 — Ollama heartbeat — COMPLETE ✓
- `useChat.js`: 30-second `setInterval(checkHealth, 30_000)` polling `/health`
- `Shell.jsx`: `AppFrame` accepts optional `ollamaOnline` prop → colored status dot (7px circle, glow)
- `MainScreen.jsx`: passes `ollamaOnline` to AppFrame

## Desktop ↔ Cloud integration — COMPLETE ✓
- `LicenseScreen.jsx`: saves `bearer_token` from validate-license response + triggers /sync/pull
- `InviteRedemptionScreen.jsx`: saves `bearer_token` from accept-invite response + triggers /sync/pull
- `server.py`: `/sync/pull` calls cloud `/agents/assigned-to-me`, imports new agents to local SQLite
- `server.py`: `/license/save` accepts `bearer_token`, saves as `cloud_bearer_token` in settings

## Pending (manual steps only)
- OnboardingScreen: wire DownloadScreen with real SSE for selected model (UX polish, not blocking)
- nomic-embed-text "Download now?" modal (UX polish)
- tauri.conf.json updater pubkey — run `npm run tauri -- signer generate -w ~/.tauri/dialekt.key` in a TTY (requires interactive terminal)

## Pilot status
- No pilots contacted yet — outreach pending

## Business decisions pending
- PyPI token rotation (urgent)
- Contact 3 pilot companies — first outreach
