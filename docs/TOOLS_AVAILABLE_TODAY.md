# dialekt Tools — Available Today

**Generated:** 2026-04-24
**Validated against:** dialekt v0.10.0 (PR #2 merge)
**Audience:** Pilot customers, agent authors, pre-sales. For developer-level reference see [`CAPABILITIES_INVENTORY.md`](CAPABILITIES_INVENTORY.md) and [`TOOLS_COVERAGE.md`](TOOLS_COVERAGE.md).

What an agent's runtime code can actually call today. Everything in this document is either verified end-to-end in [`AGENT_CATALOG.md`](AGENT_CATALOG.md) or in the `python/tests/` suite (440+ tests, 5/5 CI workflows green on v0.10.0).

---

## Tools matrix

| Tool | Status | How an agent gets access | Typical latency | Notes / limitations |
|---|---|---|---|---|
| **DialektSQL — PostgreSQL** | ✅ verified E2E | `capabilities.groups: [database_read]` + `connections.required: [{type: postgres}]` + bind via Settings → Agents | 1–3 s per query (small result) | Read-only transaction on every query. Row limit (default 1000) + 30 s query timeout enforced. Schema RAG indexes column/table metadata automatically. |
| **DialektSQL — MySQL** | ✅ verified E2E | Same as PG with `type: mysql`; bind via Settings → Agents | 1–3 s | MySQL 8.0 compatible. Same row-limit + timeout envelope. Connections currently API-only (no "Add MySQL" form in Settings UI yet — create via `POST /mysql-connections`). |
| **DialektSQL — ClickHouse** | ✅ verified E2E | Same with `type: clickhouse` | 0.5–2 s | Optimised for analytical queries. Connection creation currently API-only. |
| **Python execution (Open Interpreter)** | ✅ shipped | Available by default (no explicit capability). Gated by `autonomy.recommended` at publish time. | 0.5–2 s (simple code) | Full `httpx`, stdlib, and OI-installed packages available. This is the primary tool an agent uses to call dialekt's own REST endpoints (e.g. `/connections/{id}/query`). |
| **Shell execution (bash)** | ✅ shipped | `capabilities.groups: [shell_execute]`. Autonomy slider controls per-command confirmation. | 0.3–1 s | OS process isolation only; dialekt does not sandbox commands. Use `autonomy: review-only` for strangers. |
| **Filesystem read** | ✅ shipped | `capabilities.groups: [filesystem_read]`. Runtime access is actually OI's Python/shell — the capability is advisory metadata. | <0.5 s | No path traversal guard — the agent sees whatever the dialekt process can see. Set user expectations accordingly. |
| **Filesystem write** | ✅ shipped | `capabilities.groups: [filesystem_write]`. Same advisory note as read. | <0.5 s | No quota. |
| **Schema RAG search** (`/connections/{id}/search?q=…`) | ✅ verified | Implicit for any agent bound to a connection. Explicit call from Python is fine too. | 0.5–1 s | Uses `nomic-embed-text:v1.5`. Index built on first reindex or after connection creation. |
| **Reindex** (`POST /connections/{id}/reindex`) | ✅ verified | Any agent with access to the connection; user-invokable from Settings → Connections. | 2–10 s on typical ecom schemas | Rebuilds the embedding index after DDL changes. |
| **Few-shot memory** | ✅ shipped, untested in catalog | Automatic — persists the last successful (question, answer) on every turn; retrieves k=3 most-similar for next turn. | <0.5 s retrieval | Scoped per `agent_id`. Coverage test deferred to M2 per plan §6. |
| **History summarisation** | ✅ | Automatic once session tokens exceed ~6000 | <1 s | Older turns compressed to ≤1500 chars. Transparent to the agent. |
| **File upload into chat** | ✅ | `POST /upload` + WS `@file:ID` reference | <1 s | File content is injected into the prompt on the next turn. |
| **HTTP outbound (`httpx` from agent code)** | ✅ works — no gating | `capabilities.groups: [network]` is advisory metadata; the Python runtime can hit any URL regardless. | depends on target | No domain allow-list today. Treat as ungated. |
| **Browser / Selenium** (`interpreter.computer.browser`) | ❓ untested on Linux server | `capabilities.groups: [browser]` | n/a | OI's Selenium deps not validated in this codebase. Do not promise to pilots. |
| **Screen capture** | ❌ not usable headless | `capabilities.groups: [screen_capture]` | n/a | No display on production server; macOS-centric in OI. |
| **Vision input** | ❌ no vision model | n/a | n/a | None of the installed Ollama models (`qwen2.5-coder:7b`, `gemma3-12b`, `gemma2:2b`, `nomic-embed-text:v1.5`) support images. |
| **ComfyUI txt2img** (`POST /comfy/txt2img`) | ✅ shipped, not in regression | Available to any agent via Python; the bundled General Assistant demonstrates the contract. | 10–30 s per image | Flux Schnell; ComfyUI auto-starts if needed. Coverage deferred — requires ComfyUI running locally. |
| **ComfyUI txt2vid** (`POST /comfy/txt2vid`) | ✅ shipped, not in regression | Same. Surface tested via General Assistant system prompt but not in automated suite. | 5–20 min per clip | LTX-Video 2.3 (22B). Warn users before invoking. |

## Tools NOT available (M2 / M3 backlog)

These are asked-about regularly in discovery calls. They do NOT exist in v0.10.0.

| Missing tool | Why blocked | Target milestone |
|---|---|---|
| Web search API integration (Tavily / Brave / SerpAPI) | No adapter; no API-key UI | M2 (Q3 2026) |
| Email / SMTP send | No transport, no credential UI | M2 |
| Native declarative HTTP tool (as opposed to raw `httpx`) | No schema + runtime for typed HTTP tool | M2 |
| Scheduled agent runtime (cron) | Manifest accepts `trigger.type: scheduled` — no runner process reads it | M2 |
| Webhook trigger receiver | Not a schema variant yet (see `schema.py::Trigger` union) | M3 |
| Multi-agent orchestration (A → B) | One agent per WS session; no dispatcher | M3 |
| Per-agent secrets UI | `secrets_required` in manifest is advisory; nothing asks the user | M2 |
| Output destinations beyond `notification` (`filesystem`, `webhook`, `email_or_telegram`) | Schema-valid — no delivery runtime | M2 |

---

## Agents → tools → settings — how the three map

A pilot wondering "what do I need to flip to let an agent do X" should follow this path.

| Tool the agent needs | Manifest field(s) required | Settings page the user must visit |
|---|---|---|
| Any SQL tool | `connections.required: [{type: postgres\|mysql\|clickhouse}]` + `capabilities.groups: [database_read]` | Settings → Connections (create connection) → Settings → Agents (bind the new connection to this agent) |
| Filesystem | `capabilities.groups: [filesystem_read]` and/or `filesystem_write` | Settings → Permissions (global autonomy level) — capability itself is metadata |
| Shell | `capabilities.groups: [shell_execute]` + pick appropriate `autonomy.recommended` | Settings → Permissions |
| Network / HTTP | `capabilities.groups: [network]` (advisory) | none |
| None of the above (pure LLM) | `capabilities.groups: []` | none |

**Honest note.** The capability *name* in the manifest is documentation for the agent author and pilot reviewer. Runtime enforcement of "what this agent can touch" is the **global autonomy level**, not the capability checkbox. This is a known architecture gap on the M2 roadmap (per-agent sandboxing).

---

## Quick reference — REST endpoints agents call

Everything below is reachable from an agent's Python code block as `http://localhost:8765/...`:

- `GET /connections/{id}/schemas` — list schemas
- `GET /connections/{id}/schemas/{schema}/tables` — list tables (works for all 3 DB drivers with the right prefix: `/connections`, `/mysql-connections`, `/ch-connections`)
- `GET /.../tables/{table}/describe` — column types
- `GET /.../tables/{table}/fkeys` — foreign keys
- `GET /.../tables/{table}/sample?limit=N` — sample rows
- `POST /.../query` — execute read-only SQL; body `{"sql": "...", "retry": false}`
- `GET /connections/{id}/search?q=...` — semantic schema search
- `POST /connections/{id}/reindex` — rebuild RAG index
- `POST /terminal` — server-side shell run
- `POST /upload` — upload a file
- `GET /system` — host resources
- `GET /health` — Ollama + model liveness

See `python/server.py` + `python/mcp_servers/*.py` for the authoritative list.

---

**See also:**
- [`AGENT_CATALOG.md`](AGENT_CATALOG.md) — real working agent configurations with sample queries
- [`SETTINGS_COMBOS_TODAY.md`](SETTINGS_COMBOS_TODAY.md) — manifest field combinations that pass validation and work at runtime
- [`WHAT_DIALEKT_DOES_TODAY.md`](WHAT_DIALEKT_DOES_TODAY.md) — executive summary
