# Multi-Role E2E Test Plan — dialekt

**Date:** 2026-04-24
**Status:** Stage 1 diagnostic only. **Do not write tests until this plan is approved.**

Goal: validate dialekt is pilot-ready for three distinct user populations — the **Admin** (dialekt-cloud tenant operator), the **Agent Developer** (desktop-app power user building agents), and the **End User** (desktop-app chat-only consumer). 18 base E2E scenarios already green; this extends to realistic user journeys across every Settings page and every available tool.

---

## 1 · Role 1 — Admin (dialekt-cloud)

Admin UI lives at `https://dialekt-cloud.dias.now/admin/ui` and is backed by `dialekt-cloud/src/dialekt_cloud/routers/admin.py`. All endpoints auth via `X-Admin-Key` header or the JWT minted from `POST /admin/login`.

| Endpoint | UI button? | Does | Already tested |
|---|---|---|---|
| `POST /admin/login` | login.html | Exchange key → session JWT | ✅ test_admin.py |
| `GET /admin/stats` | dashboard overview | Tenant/user/agent/invoice counters | ✅ test_admin.py |
| `GET /admin/tenants` | dashboard list | List tenants + user/license counts | ✅ test_admin.py |
| `POST /admin/tenants` | "Create tenant" | Create draft tenant | ✅ test_admin.py |
| `GET /admin/tenants/{id}` | dashboard modal | Detail + users + invoices + license | ✅ test_admin.py |
| `PATCH /admin/tenants/{id}` | dashboard modal | Update plan / seats / status / notes / expiry | ✅ test_admin.py |
| `POST /admin/tenants/{id}/activate` | dashboard modal | Flip draft→active, mint license, send email | ✅ test_admin.py |
| `POST /admin/tenants/{id}/invoice` | dashboard modal | Generate invoice row + PDF | ✅ test_invoice.py |
| `GET /admin/invoices/{id}/download` | dashboard modal (opens URL) | Stream invoice PDF | ❌ **no test** |
| `GET /admin/tenants/{id}/users` | dashboard modal | List tenant users | ✅ test_admin.py |
| `DELETE /users/{id}` | **no UI** | Remove a tenant user | ❌ **no test** |

**Bottom line:** admin surface is already extensively covered by the 56-test dialekt-cloud suite (all green in CI after Fix #2). The only genuine gaps are (a) invoice PDF download endpoint and (b) tenant-user deletion. Plus the *full journey* — login → create tenant → activate → invite → suspend → reactivate → invoice download — isn't exercised as one sequence anywhere.

**Proposed `test_e2e_role_admin.py` (8 scenarios):**
1. **Login — bad key rejected, good key → JWT** *(already covered, replicate as the entry of the journey)*
2. **Create tenant** *(existing `test_create_tenant` pattern, with realistic payload)*
3. **Activate tenant** *(covers license issuance + email send via the aiosmtpd fake)*
4. **Generate invite** — *deferred: invite flow lives in `routers/invites.py`, separate from admin.py; confirm scope below*
5. **Suspend tenant** (PATCH status=suspended) + verify license deactivated downstream
6. **Reactivate** (PATCH status=active) + verify license re-activated
7. **Filtered list** (GET `/admin/tenants?status=active`) — *confirm the query param is actually supported; spec says "if it exists"*
8. **Download invoice PDF** — close one of the untested endpoints
9. **Delete tenant** — *DELETE endpoint does not exist; skip or write a "documented behavior" test asserting 405*

> ⚠ Items 4 and 7 need your input — see "Clarifications needed" below.

---

## 2 · Role 2 — Agent Developer (desktop app)

All flows go through `frontend/src/screens/SettingsScreen.jsx` + `AgentWizardScreen.jsx` against the `python/server.py` FastAPI app. Chat + agent binding + validator-reload all shipped on `feat/stage-2-partial`.

### Flows by category

| Category | Frontend | Backend | Tested today |
|---|---|---|---|
| Connections CRUD — PG | SettingsScreen §1468–1627 | `/connections` (postgres_mcp.py) | ✅ test_postgres_mcp.py, test_connections_filter.py |
| Connections CRUD — MySQL | SettingsScreen (same) | `/mysql-connections` | ✅ test_mysql_mcp.py |
| Connections CRUD — CH | SettingsScreen (same) | `/ch-connections` | ✅ test_clickhouse_mcp.py |
| Builder Wizard (9 steps) | AgentWizardScreen | `POST /agents/import-yaml` + binding | ✅ test_wizard_*.py (schema-level) |
| Agent binding editor | SettingsScreen §1891–2097 | `/agents/{id}/binding` GET/POST/DELETE | ✅ test_agent_binding.py |
| Agent edit (PATCH) | SettingsScreen (export/reimport) | `PATCH /agents/{id}` | ✅ test_agents_api.py |
| Agent delete | SettingsScreen | `DELETE /agents/{id}` | ✅ test_agents_api.py |
| Schema reload | Admin → Maintenance | `POST /admin/reload-schema` | ✅ test_reload_schema.py |
| Cloud sync / License | Settings → About / Cloud | `/license/*`, `/sync/*` | ❌ **untested** |

### Tool exercisability

| Tool | Reachable from a wizard-built agent? | Practical to exercise in a test? |
|---|---|---|
| DialektSQL — PG | ✅ via capability `database_read` + `connections.required: postgres` | ✅ real integration PG at :15432 |
| DialektSQL — MySQL | ✅ | ✅ real integration MySQL at :13306 |
| DialektSQL — ClickHouse | ✅ | ✅ real integration CH at :18123 |
| Python (Open Interpreter) | ✅ via capability `code_execution` (default on) | ✅ trivial script with deterministic output |
| Shell (Open Interpreter) | ✅ via capability `shell_execute` | ⚠ needs strict sandbox in CI; local only |
| Filesystem read | ✅ via `filesystem_read` | ✅ read a tempfile |
| Browser / Selenium | ✅ via `browser` capability | ❌ not practical headless without Chromium — **defer** |
| Screen capture | ✅ via `screen_capture` | ❌ no display in CI — **defer** |
| Schema RAG | ✅ implicit (`/connections/{id}/search`) | ✅ already exercised indirectly in overnight suite |
| Few-shot memory | ✅ auto-invoked on session join | ⚠ requires 2 sessions; possible but slow |
| ComfyUI txt2img / txt2vid | ✅ via Python+httpx in agent code | ❌ requires ComfyUI running — **defer** |
| HTTP (Python httpx) | ✅ | ✅ mock via `respx` or hit a tiny local server |

**Proposed `test_e2e_role_developer.py` (14 scenarios):**

*Connection management (3)* — not 4; a 4th would duplicate `test_connections_filter.py`.
1. Add PG connection through POST /connections → verify row + /test returns ok
2. Add MySQL connection + /test
3. Add ClickHouse connection + /test

*Agent creation & binding (5)*
4. SQL Analyst (PG) — publish wizard manifest → bind → execute `SELECT COUNT(*)` via the live chat path *(requires Ollama + real SQL)*
5. Pure LLM agent (no caps, no conns) — publish → send plain-text prompt → any reply
6. MySQL Analyst — publish → bind MySQL → execute query
7. Code-review agent (filesystem_read + shell_execute) — publish → ask "cat a tempfile and summarize" → verify both tools fire in `/sessions/{id}/messages`
8. Python-only agent (code_execution) — publish → ask "compute fib(10)" → verify Python block in reply

*Agent lifecycle (3)*
9. List — `GET /agents` returns the 5 created + bundled ones
10. Edit — PATCH system_prompt, verify persists, verify next chat turn uses new prompt
11. Delete — verify row gone + `agent_bindings` CASCADE cleaned

*Settings pages (3)*
12. Schema reload — `POST /admin/reload-schema` returns 200 with current `package_version`
13. Connection test — `POST /connections/{id}/test` returns `{ok: true, version: ...}`
14. Schema RAG reindex — `POST /connections/{id}/reindex` returns 200 with indexed count

---

## 3 · Role 3 — End User (desktop app, chat-only)

All surfaces live in `MainScreen.jsx` + `ChatColumn.jsx` + `LeftPanel.jsx`, driven by WebSocket `/ws` on server.py.

| Flow | Backend | Tested today |
|---|---|---|
| Agent selection (sidebar) | `GET /agents`, `GET /agents/{id}`, `GET /agents/{id}/binding` | ❌ |
| Send message (streaming) | `WebSocket /ws` (type=chat) | ⚠ indirect — `test_websocket_boot.py` only verifies connection |
| Multi-turn context | `GET /sessions/{id}/messages` + WS replays | ❌ |
| Session create / switch / delete | `POST /sessions` (implicit) / `PATCH` / `DELETE` | ✅ test_api_health.py |
| Copy message | frontend-only | n/a |
| Empty state (missing binding) | `GET /agents/{id}/binding` | ❌ |
| Error recovery (Ollama down, SQL retry, WS close) | `/health`, WS reconnect | ❌ |
| Agent switching mid-session | WS `type=chat` with new `agent_id` | ❌ |

**Caveat:** every non-trivial chat test needs a live Ollama with a small model. `gemma2:2b` is installed locally (~1 GB, ~1.5s cold) and will be used as the test model. Target: total suite runtime ≤3 min local, ≤5 min CI.

**Proposed `test_e2e_role_user.py` (9 scenarios):**

*Selection & send (3)*
1. Select bundled "General Assistant", send "reply with the word OK" → verify non-empty reply containing "OK"
2. Create SQL Analyst bound to PG, send "count rows in ecom.customers" → verify reply contains `1000` (from seed)
3. Multi-turn: after (2), send "and in ecom.orders?" → verify reply contains `5000` (seed count) *(context retention — second query must share the session)*

*Session mgmt (2)*
4. `POST /sessions` (first message) → session appears in `GET /sessions`
5. `DELETE /sessions/{id}` → gone from list; next `GET /sessions/{id}/messages` returns 404

*Empty states (2)*
6. Agent with `connections.required: [{type: postgres}]` and no binding → `GET /agents/{id}/binding` returns `{connection_id: null}` ; attempting chat returns guard error
7. Pure LLM agent → `GET /agents/{id}/binding` returns `{connection_id: null}` but `hasRequirements=false` → chat proceeds normally

*Error paths (2)*
8. SQL Analyst → "SELECT * FROM ecom.nonexistent_table" → retry loop fires (observable via logs) → final reply is graceful error, **not** a 500
9. Agent switching mid-session — start with General Assistant, switch to SQL Analyst, send query → verify session row's `agent_id` updated + new system_prompt in effect

---

## 4 · Tools coverage matrix (draft)

| Tool | Covered by | Status |
|---|---|---|
| DialektSQL — PG | role_developer 4, role_user 2 | ✅ will cover |
| DialektSQL — MySQL | role_developer 6 | ✅ will cover |
| DialektSQL — ClickHouse | role_developer 3 (test only) | ⚠ listed under conns, not under chat — **add chat-level CH test?** |
| Python execution | role_developer 8 | ✅ will cover |
| Shell execution | role_developer 7 | ✅ will cover (local only) |
| Filesystem read | role_developer 7 | ✅ will cover |
| Schema RAG | role_developer 14 | ✅ will cover |
| Few-shot memory | none | ❌ **defer — adds significant runtime** |
| HTTP (via Python) | none proposed | ❌ **defer or add?** |
| Browser / Selenium | none | ❌ defer — practically untestable |
| Screen capture | none | ❌ defer |
| ComfyUI txt2img / txt2vid | none | ❌ defer — not part of pilot scope |

---

## 5 · Settings coverage matrix (draft)

| Settings page | User can do | Covered by | Status |
|---|---|---|---|
| Models | Pick model, pull new | developer 12 (indirect via `/health`) | ⚠ partial |
| Personality | Tone/verbosity/prompt | none | ❌ pure POST /settings blob |
| Appearance | Theme/fonts | none | ❌ UI-only |
| Shortcuts | View only | n/a | ❌ display-only |
| Permissions | Autonomy + allow-lists | none | ❌ POST /settings blob |
| Filesystem | Access rules | none | ❌ POST /settings blob |
| Terminal & shell | Env vars / allow-list | none | ❌ POST /settings blob |
| Browser | Headless / cookies | n/a | — placeholder "v1.1" |
| Screen control | capture cfg | n/a | — placeholder "v1.1" |
| MCP tools | list | n/a | — placeholder "v1.1" |
| Connections | PG/MySQL/CH CRUD + reindex | developer 1–3, 13, 14 | ✅ |
| Agents | Binding editor | developer 4, 6, 10, 11 | ✅ |
| Storage & memory | Facts + wipe | none | ❌ would need 1 scenario for wipe |
| Performance | LLM knobs | none | ❌ POST /settings blob |
| Privacy & telemetry | Toggles | none | ❌ POST /settings blob |
| Admin | Stats + reload | developer 12 + admin 2 | ✅ |
| About | License list | none | ❌ display-only |

**Proposal:** add two tiny scenarios (`test_e2e_role_developer.py` #15, #16) for `POST /settings` round-trip and `DELETE /sessions` wipe, covering the pure-state-blob pages in aggregate. The individual UI-only Settings pages don't warrant per-page tests — they all persist through the same `POST /settings` endpoint.

---

## 6 · Proposed test files & ETA

| File | Scenarios | Requires | ETA |
|---|---|---|---|
| `python/tests/test_e2e_role_admin.py` | 8 | live PG on :5433 + in-memory SMTP fake (aiosmtpd) | ~1h |
| `python/tests/test_e2e_role_developer.py` | 16 (with 2 Settings add-ons) | integration compose (PG/MySQL/CH) + Ollama (gemma2:2b) | ~2h |
| `python/tests/test_e2e_role_user.py` | 9 | integration PG + Ollama + 1 bundled agent + 1 built SQL Analyst | ~1h |
| `docs/TOOLS_COVERAGE.md` | — | — | ~10m |
| `docs/SETTINGS_COVERAGE.md` | — | — | ~10m |
| `docs/MULTI_ROLE_E2E_REPORT.md` (after runs) | — | — | ~20m |
| **Total proposed** | **33 scenarios** | — | **~4h 40m** |

---

## 7 · Clarifications needed before Stage 3

**Please answer these before I write tests:**

1. **Admin scope.** The dialekt-cloud invite flow (`routers/invites.py`) is adjacent to admin but not part of the `/admin/*` prefix. Is it in scope for Role 1? If yes I'll add a "generate invite + consume invite" scenario; if no I'll skip.
2. **`/admin/tenants?status=active` filter.** I'll confirm at test time whether the filter is implemented; if not I'll drop scenario 7 or assert the current behavior. OK?
3. **ClickHouse chat-level coverage.** Today I only propose a CRUD test for CH (developer #3). Want me to add a role_user-style chat query against CH too, or is PG+MySQL chat coverage enough?
4. **Ollama model for chat tests.** Using `gemma2:2b` — smallest installed, deterministic-ish with low temperature. Sound right? If you want `qwen2.5-coder:7b` for better SQL generation I'll switch but runtime will roughly triple.
5. **Shell-execution scenario (developer #7).** Will run `echo` + `cat /tmp/...` inside Open Interpreter's real subprocess. Fine locally but I'll gate it behind a `DIALEKT_E2E_ALLOW_SHELL=1` env flag so CI doesn't accidentally run shell-risky steps. OK?
6. **Few-shot memory + HTTP tool.** Both doable but add ~1h runtime each. Skip for this sweep? (I'd vote skip — pilot-readiness doesn't hinge on either.)

Once you sign off, I'll move to Stage 3 (write the three test files), then Stage 4–6 (coverage docs + run + final report).

---

## 8 · Known constraints / risks

- **Ollama-dependent tests are non-deterministic.** I'll assert on structure ("reply contains a number", "reply is non-empty", "SQL block present") not exact strings.
- **Keyring.** Local runs need `PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring`; CI already sets this (commit `bb2858e`).
- **Integration compose.** Runner script will `docker compose up -d --wait` before the suite; tests still `pytest.skip` if services unreachable (matches existing convention).
- **Ship gate:** spec says pass-rate ≥95% → truly pilot-ready; <80% → regression session. Given the mostly-green base state, realistic target is 90%+ on first run, with any failures documented in `MULTI_ROLE_E2E_REPORT.md` for prioritization, not fixed inline (per rules).
