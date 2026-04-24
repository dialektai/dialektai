# dialekt Capabilities Inventory — 2026-04-23

Honest snapshot of everything an agent can (and *cannot*) do today without touching the codebase. Compiled by greps, schema reads, and cross-reference against the SQL Analyst end-to-end demo we verified earlier in the day.

Legend:

- ✅ WORKS — verified end-to-end at least once
- ⚠️ PARTIAL — path exists but has caveats (see note)
- ❓ UNVERIFIED — code exists, I didn't run it through
- ❌ BROKEN / NOT IMPLEMENTED — surface visible (UI/schema/docs) but no runtime

---

## 1. MCP servers / language plugins

### dialekt-owned FastAPI routers (`python/mcp_servers/`)

| Router | Prefix | Status | What it does | Example agent use |
|---|---|---|---|---|
| `postgres_mcp` | `/connections` | ✅ WORKS | Full PostgreSQL surface: list/create/patch/delete connection, test, list schemas, list tables, describe table, foreign keys, sample rows, query (with retry-loop & row-limit), reindex (Schema RAG), search (semantic over indexed schema) | SQL Analyst — verified today |
| `mysql_mcp` | `/mysql-connections` | ❓ UNVERIFIED | Same surface as postgres_mcp (list/test/query/reindex/search) but for MySQL | "Sales MySQL Analyst" — code exists, not E2E tested |
| `clickhouse_mcp` | `/ch-connections` | ❓ UNVERIFIED | Same surface for ClickHouse | "Events Warehouse Analyst" — code exists, not E2E tested |
| `schema_rag` | *(no prefix — helper)* | ✅ WORKS | nomic-embed-text:v1.5 embeddings over discovered table+column metadata; stored in `~/.dialekt/schema_cache.db`; powers `/search` and `/reindex` endpoints | Used internally by the three SQL routers above |

### Open Interpreter Language plugins (registered via `interpreter.computer.terminal.languages`)

| Language | Status | Notes |
|---|---|---|
| **DialektSQL** (dialekt-specific) | ✅ WORKS | Registered in `make_interpreter`; reads `interpreter._dialekt_sql_conn` and POSTs to `/connections/{id}/query` with `retry:false`. Aliases: `sql, postgres, postgresql, psql, mysql, clickhouse`. Verified with SQL Analyst. |
| python | ✅ WORKS | OI native. Agents can import httpx and call any dialekt endpoint this way. |
| shell / bash / sh | ✅ WORKS | OI native. Autonomy slider controls confirm prompts. |
| javascript | ❓ UNVERIFIED | OI native — subprocess via node. |
| applescript, html, java, jupyter, powershell, react, ruby, r | ❓ UNVERIFIED | OI defaults. `html` renders static only. |

### Open Interpreter `computer` API

OI also exposes a fat "computer" namespace to any agent whose code block is Python (when `import_computer_api` is on — **currently default**): `browser, mail, sms, calendar, clipboard, contacts, display, docs, files, keyboard, mouse, os, skills, terminal, vision, ai`.

**⚠️ Unverified for dialekt.** These are OI upstream and depend on OI's own dependencies (selenium, AppleScript on macOS, etc). I did not test any of them on this Linux server. Do not assume they work until verified per-feature.

### MCP servers you might expect but don't exist

- No **filesystem MCP** — agents read/write the local FS via OI's Python/shell, not a dialekt route.
- No **web/HTTP MCP** — agents fetch URLs via Python `httpx` or `requests` directly.
- No **remote MCP server protocol** — the manifest schema accepts `connection.type: mcp-server` and `http-api`, but the backend has no router for those types. Only `postgres / mysql / clickhouse` are wired.

---

## 2. Builder Wizard — Capabilities checklist

The six checkboxes in Wizard Step 4 (`AgentWizardScreen.jsx:410-415`) map to the manifest's `capabilities.groups` field.

| Checkbox UI | Manifest group | Runtime enforcement? | What actually happens |
|---|---|---|---|
| Filesystem | `filesystem_read`, `filesystem_write` | ❌ NONE | Metadata only. OI's Python/shell can read/write the FS regardless of this checkbox. Actual access gating lives in Settings → Permissions (global, not per-agent). |
| Network | `network` | ❌ NONE | Metadata only. Python `httpx` works regardless. |
| Browser | `browser` | ❌ NONE | Metadata only. `interpreter.computer.browser` (Selenium-based) is available regardless. Untested on this machine. |
| Database Read | `database_read` | ❌ NONE | Metadata only. DialektSQL works if the agent has an `agent_binding` row, not because this box is ticked. |
| Terminal | `shell_execute` | ❌ NONE | Metadata only. OI shell language runs regardless. |
| Screen | `screen_capture` | ❌ NONE | Metadata only. `interpreter.computer.display` on supported OS. |

**⚠️ Honest finding.** The Wizard Capabilities step is *documentation*, not a security boundary. Manifest validator rejects unknown group names (`schema.py:131`) but no runtime component reads `manifest.capabilities.groups` before allowing an action. The only runtime gate is **autonomy level** (`review-only / ask-before-write / autonomous / sandbox-only`) which controls whether OI asks the user before executing code.

Valid group names in schema (`schema.py:11`): `filesystem_read, filesystem_write, database_read, database_write, shell_execute, network, browser, screen_capture`.

---

## 3. Manifest schema — fields you can declare

Source: `dialekt_manifest.schema.AgentManifest` (`venv/…/dialekt_manifest/schema.py:387`).

### Required

| Field | Purpose | Enforced at runtime? |
|---|---|---|
| `spec_version` | semver; manifest format version | validator only |
| `minimum_dialekt_version` | semver; app compatibility gate | validator only (no runtime check) |
| `metadata` (id, name, description, version, language, tags, author, timestamps) | Identity / display | id is unique; rest is cosmetic |
| `model` (preferred, acceptable, min_context_window, requirements, parameters) | Pick the LLM for this agent | ✅ **`pick_model_for_agent`** reads preferred+acceptable with family-match fallback (verified). `parameters.temperature/max_tokens` currently **ignored** — global settings win. |
| `system_prompt` | The prompt | ✅ Injected by `make_interpreter`, supports `{{connection_id}}` substitution |
| `capabilities.groups` | Declared access intentions | ❌ Metadata only (see §2) |
| `autonomy.recommended` / `.max_allowed` | Default + ceiling for the confirmation slider | ⚠️ Global autonomy is what actually runs; max_allowed is not currently enforced to cap the slider |
| `input.type` | chat / form / none | Only `chat` path exists in UI |
| `output` (format, streaming, destination) | Result format | `streaming` ✅. `destination.type` — only `notification` is live; `filesystem / webhook / email_or_telegram` schema-valid but not wired. |
| `trigger.type` | `interactive` or `scheduled` | `interactive` ✅. `scheduled` (cron + timezone + missed_run_policy) is **schema-valid but there is no scheduler process**. |

### Optional

| Field | Purpose | Enforced? |
|---|---|---|
| `connections.required[*]` — type (postgres/mysql/clickhouse/mcp-server/http-api), role, database_category, purpose, required_permissions | Declare DB needs so UI can bind a connection | types `postgres/mysql/clickhouse` ✅; `mcp-server/http-api` schema-valid but no backend |
| `variables` — dict of name → {type, required, description}. Types: string/number/boolean/list | Placeholder substitution in system_prompt (`{{var}}`) | Only `{{connection_id}}`, `{{connection_name}}`, `{{database_type}}` are filled by server. Generic variables are **not prompted for** in UI and **not substituted**. |
| `environments` — dict of env name → arbitrary settings | Per-env overrides | Not read by runtime |
| `secrets_required` — list of {name, description, required} | Declare what secrets the agent expects | No UI surface to supply them; not read by runtime |

---

## 4. Runtime features

| Feature | Status | Notes |
|---|---|---|
| Interactive chat | ✅ | Streaming via WS, OI as reasoning loop. |
| Agent ↔ connection binding | ✅ | `agent_bindings` DB + UI (Settings → Agents, shipped earlier today). |
| Per-agent model routing | ✅ | `pick_model_for_agent` with exact → acceptable → family-match → default fallback. |
| DialektSQL execution | ✅ | Routes `sql` code blocks through `/connections/{id}/query`. |
| SQL Retry Loop (EXPLAIN-validate + LLM-fix) | ⚠️ PARTIAL | Lives in `postgres_mcp._retry_fix_sql`. Fires for direct API callers. DialektSQL disables it (`retry: false`) to avoid a pre-existing recursive-validate bug. Same logic exists in `mysql_mcp` / `clickhouse_mcp` via `retry_loop.py`. |
| Schema RAG (semantic table search) | ✅ | nomic-embed-text over schema cache. Exposed as `/connections/{id}/search`. Agents can call it from Python code blocks. |
| Few-shot memory (per agent, per question-type) | ✅ | `~/.dialekt/few_shots.db`, nomic-embed lookup at chat time. `save_interaction` on turn end, `get_few_shots(k=3)` on turn start. |
| History summarisation when context overflows | ✅ | `TOKEN_BUDGET = 6000`; old turns get compressed to ≤1500 chars. |
| File upload to chat | ✅ | `/upload` endpoint exists; file contents become part of the context. |
| Screenshot input | ⚠️ UNVERIFIED | OI can ingest images if the model is vision-capable. None of the locally-installed Ollama models (`qwen2.5-coder:7b, gemma3-12b, gemma2:2b`) are vision-enabled today. |
| License revocation refresh | ✅ | Background poller; desktop config flips to `revoked` when the cloud suspends the tenant. |
| **Scheduled (cron) agents** | ❌ NOT IMPLEMENTED | No `APScheduler / croniter` runner in `server.py`. Manifest accepts the config but nothing runs it. |
| **Webhook-triggered agents** | ❌ NOT IN SCHEMA | `Trigger` is a `Union[InteractiveTrigger, ScheduledTrigger]`. Webhook isn't a schema variant. |
| **Multi-agent (A calls B)** | ❌ NOT SUPPORTED | No code path for agent-to-agent invocation. Each WS session binds one agent. |
| **Context menu actions on messages** — Regenerate / Delete / Branch / Make concise / Explain step-by-step | ❌ STUBS | From earlier E2E report: `ChatColumn.jsx:456-466` all have `action: onClose`. Only Copy / Copy-as-markdown / Save-to-file actually do something. |
| **Destination: filesystem / webhook / email_or_telegram** | ❌ NOT WIRED | Schema-valid; no runtime delivery. |
| **Input type: form / none** | ❌ NOT IN UI | Schema-valid; only `chat` input renders. |

---

## 5. Endpoints an agent's Python code can hit

Everything listed under `server.py` plus the three SQL routers. Key ones for agent authors:

- `GET /connections/{id}/schemas` — list schemas (per connection type; use the right prefix: `/connections`, `/mysql-connections`, `/ch-connections`)
- `GET /connections/{id}/schemas/{schema}/tables`
- `GET /.../tables/{table}/describe` — columns + types
- `GET /.../tables/{table}/fkeys`
- `GET /.../tables/{table}/sample?limit=3`
- `POST /.../query` — body `{"sql": "SELECT …", "retry": false}` (DialektSQL already calls this; direct calls work too)
- `GET /connections/{id}/search?q=...` — semantic schema search
- `POST /connections/{id}/reindex` — rebuild the RAG index
- `POST /terminal` — run a shell command server-side
- `POST /upload` — accept a file
- `GET /files` — list uploads
- `GET /system` — CPU / RAM / GPU / disk, `ram_total_gb`
- `GET /health` — Ollama + model liveness

Plus anything local via OI's `computer` API (untested here).

---

## 6. Verified working agent recipes

Things you can build **right now** without writing a line of new dialekt code:

1. **SQL Analyst over PostgreSQL** — declare `connections.required: [{type: postgres}]`, bind a connection from Settings → Agents, ask questions in Ru/En. ✅ Verified E2E today.
2. **General chat assistant** (no DB) — declare no `connections` block, prompt the model to be a subject-matter expert. ✅ Verified (gemma3-12b responded to "Привет").
3. **Read-only agent on MySQL** — same pattern as #1 but manifest `connections.required: [{type: mysql}]`. ❓ Unverified end-to-end but symmetric code path.
4. **Read-only agent on ClickHouse** — same as #3 with `type: clickhouse`. ❓ Unverified end-to-end.

Plausible but need testing before you promise a pilot:

5. **Code review / debug agent** — prompt that eats a stack trace or a file via `/upload` and produces analysis. OI has access to Python+shell so it can even run tests. Model: qwen2.5-coder:7b. **Test this before demo.**
6. **File/folder summariser** — uses OI's native filesystem access through Python. **Test path traversal + user expectations before demo.**
7. **Web-scraper** — needs OI browser module which has OS-level selenium deps, untested on this server.

---

## 7. Known gaps you will hit if you promise them to a pilot

(Ordered roughly by "how often will this bite you")

1. **Scheduled / cron agents** — nothing runs them. If a pilot asks "daily KPI digest at 9am", you need to build this first.
2. **Webhook triggers** — not in schema, not wired. "Run this agent when Stripe fires a webhook" → not today.
3. **Capabilities checkboxes as a security story** — they are metadata, not a sandbox. Do **not** tell a pilot "you can safely let it access FS because Filesystem is checked off in the agent". The actual gate is autonomy level + global Settings → Permissions (which are per-install, not per-agent).
4. **Variables beyond `connection_id`** — if your manifest declares `variables: {region: {type: string, required: true}}`, nothing in the UI will ask the user for `region` and `{{region}}` will be left literal in the prompt.
5. **Destination: email / webhook / filesystem** — `output.destination.type` only supports `notification` (= shows in the chat) at runtime.
6. **Multi-agent workflows** — "SQL Analyst queries data, then Summariser writes a report" = not possible without code.
7. **MCP-server and http-api connection types** — schema accepts them, no router serves them.
8. **Context-menu "Regenerate" / "Make concise" / "Branch conversation" / "Delete message"** — all stubs.
9. **Retry loop on direct API calls** — has the recursive-validate bug. Fine as long as agents go through DialektSQL (which disables retry). Direct callers will spin.
10. **Vision input** — OI supports it but no vision-capable model is currently installed in Ollama.

---

## 8. Suggested portfolio seeds (safe to promise)

Given the above, the agents you can legitimately offer to a KZ pilot **today, no new code**, are narrow and honest:

- **"SQL Analyst" — PostgreSQL**, read-only, RU/EN, schema-aware. (Shipped.)
- **"MySQL Analyst"** — same as above, one-time E2E verification required.
- **"ClickHouse Analyst"** — same, E2E verify first.
- **"Code review assistant"** — upload a file, get feedback. Needs explicit prompt + test.
- **"Meeting notes summariser"** — paste text, get bullets. Pure LLM, safest bet.

Anything that needs scheduling, webhooks, cross-agent orchestration, or per-agent sandboxing is **a product milestone, not a pilot deliverable**.

---

*Compiled by greps against `python/server.py`, `python/dialekt/llm/*`, `python/mcp_servers/*`, `venv/.../dialekt_manifest/schema.py`, `frontend/src/screens/AgentWizardScreen.jsx`, `frontend/src/components/ChatColumn.jsx`, and the live SQLite at `~/.dialekt/dialekt.db`. Not a forecast — a snapshot. Rerun this inventory after every milestone that changes the agent surface.*
