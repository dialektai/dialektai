# M2 MCP Server design decisions

**Status:** Этап 2 Commit 0 deliverable — design gate before any
code. The Этап 2 review point from the M2 plan.
**Date:** 2026-04-24.
**Scope:** dialekt exposed as an MCP **server** so external hosts
(Claude Desktop, Cursor, custom clients) can drive it.
**Reviewer stop point:** after this document; NO code written
before sign-off.

References:
- [M2_MCP_DESIGN.md](M2_MCP_DESIGN.md) — client-side Этап 1
- [MCP_RESEARCH_2026-04.md](MCP_RESEARCH_2026-04.md) — ecosystem
- [MCP_OPERATIONS.md](MCP_OPERATIONS.md) — audit schema
- [AGENT_MANIFEST_SPEC.md](../AGENT_MANIFEST_SPEC.md) — agent/connection shapes

Spec revision targeted: **2025-11-25**. SDK: **`mcp>=1.25,<1.27`**
(same pin Этап 1 landed — `FastMCP` server API stable in 1.26).

---

## Decision 1 — What tools dialekt exposes

**Question:** which capabilities of the local dialekt instance are
reachable through the MCP server surface?

**Decision:**

Three categories, ten tools total in v0.20.0. Categories mirror
dialekt's existing internal capabilities — we expose the same surface
LLM plugins already consume, now through the MCP protocol so external
hosts can use it too.

### Category 1 — Database (5 tools)

Reuses the existing `db_connectors` logic (what today lives under the
misnamed `python/mcp_servers/`). No new driver code.

| Tool | Purpose | Security notes |
|---|---|---|
| `dialekt_list_connections` | Enumerate configured DB connections | Returns connection NAMES only, never credentials. Lists connections visible to the caller per permission scope (Decision 5). |
| `dialekt_query_database` | Execute SQL on a specific connection | Read-only by default — the existing `sql_safety` parser enforces `SELECT`-only; any destructive statement is rejected at the dialekt layer before touching the DB. `row_limit` honored. |
| `dialekt_list_tables` | Enumerate schemas/tables on a connection | Pure introspection. Respects the connection's `readonly` role. |
| `dialekt_describe_table` | Return columns, types, PK/FK, sample row | Same. |
| `dialekt_search_schema` | Semantic search over schema via Schema RAG | Reuses `mcp_servers/schema_rag.py` (pre-cleanup name). Embeddings stay local (Ollama nomic-embed-text). |

### Category 2 — File (2 tools)

Limited — dialekt's internal file tools are not as mature as MCP's
official `filesystem` server. We expose a narrow safe subset.

| Tool | Purpose | Security notes |
|---|---|---|
| `dialekt_read_file` | Read a UTF-8 text file by absolute path | **Path allow-list enforced.** Config (Decision 4) declares `allowed_file_roots: list[str]`; every path is resolved and checked for prefix membership. Symlinks are resolved before the check (no directory-traversal via symlink). Default allow-list is empty — the tool refuses everything until the pilot adds roots. |
| `dialekt_list_directory` | List immediate children of a directory | Same allow-list. |

### Category 3 — Agents (2 tools, read-only in v0.20.0)

Lets external hosts see dialekt's agent catalog. Full agent
invocation is M3 territory (sessions, streaming responses, consent
propagation) and intentionally NOT present in v0.20.0 — shipping a
stub that raises "not-implemented" on every call would violate the
MCP protocol's working-tools contract and damage trust. Discovery
surface (`list_agents` + `get_agent`) is enough preview; `invoke_agent`
lands in M3 when it actually works.

| Tool | Purpose | v0.20.0 behavior |
|---|---|---|
| `dialekt_list_agents` | Return the pilot's agent catalog (name, description, capabilities, autonomy) | Live. Same data the Settings UI shows. |
| `dialekt_get_agent` | Get one agent's manifest + binding | Live. Read-only. |

*(Deferred to M3: `dialekt_invoke_agent`. Reserved name; adds to this table when the backend session + streaming + consent-propagation work lands.)*

**What is NOT exposed:**

- DB connection **credentials** — only names + types. Credentials
  never leave dialekt's keyring.
- `POST`/`PATCH`/`DELETE` on anything — the server is read-biased.
  Creating connections, editing agents, managing secrets: still
  goes through the dialekt desktop UI and the local HTTP API.
- Chat history / conversation transcripts — pilot's private data.
  An agent that needs a past session's content reads it through
  its own (client-side) MCP tool call, not through this server.
- Raw settings / config — the dialekt settings file stays internal.

---

## Decision 2 — Transport

**Question:** stdio, Streamable HTTP, both?

**Decision:**

| Transport | v0.20.0 | v0.25.0+ | Not shipped |
|---|---|---|---|
| **stdio** | ✅ primary | ✅ | — |
| **Streamable HTTP** | ❌ | ✅ (behind feature flag, API key in `Authorization`) | — |
| legacy SSE | ❌ | ❌ | ✗ |

**Why stdio only in v0.20.0:**

- The flagship use case is *Claude Desktop adds dialekt to its
  `mcpServers` config*. That's stdio-spawned-by-host. No port
  binding, no network surface, no TLS story needed.
- Streamable HTTP unlocks Tailscale / Cloudflare-tunnel remote
  access. That's genuinely useful (reach your home dialekt from
  work) but introduces TLS, public-URL, OAuth-vs-bearer tradeoffs.
  Ship it in v0.25.0 after v0.20.0 pilot feedback.

**Why no SSE ever:**

Deprecated in the MCP spec (replaced by Streamable HTTP). No new
code on a dying transport.

**Implementation note:** the SDK's `FastMCP.run(transport="stdio")`
handles the stdio loop; we hand-roll nothing.

---

## Decision 3 — How `dialekt-mcp` reaches dialekt's data

**Question:** when Claude Desktop spawns `dialekt-mcp`, how does
that subprocess obtain DB connections, agents, audit sink?

**Decision:**

**HTTP-connect to the running dialekt backend** on
`http://127.0.0.1:8765` (or whatever port the pilot's `~/.dialekt/
config.json` says). `dialekt-mcp` is a *thin protocol adapter* —
it speaks MCP on stdin/stdout and dialekt's existing HTTP API on
the other side.

Rejected alternatives:

- **Spawn its own backend** — duplicates Ollama, duplicates the
  SQLite, doubles memory footprint, hideous.
- **Direct SQLite read** — partial answers (can't reach
  `db_connectors` which live in the backend process), plus
  concurrent-writer issues if the desktop app edits the DB while
  dialekt-mcp reads it.

**Precondition:** dialekt desktop app (or `python server.py`)
must be running. If not, `dialekt-mcp` exits immediately with a
clear stderr message. We document this in the Claude Desktop
integration guide.

**Auth between dialekt-mcp and dialekt backend:** the backend
trusts localhost today (no auth on internal endpoints). For
v0.20.0 this is unchanged. M3 adds a `local_api_token` the
backend mints and stores in `~/.dialekt/config.json`, which
`dialekt-mcp` reads; until then, dialekt-mcp just hits the
loopback API directly. The threat model: a local attacker with
shell access could already read the same files; adding token
auth on loopback is security theater.

**Consequence:** the `PluginContext` pattern from Этап 1 is
reused — `dialekt-mcp` constructs a `PluginContext(base_url=…)`
on startup and every tool implementation calls `ctx.post(...)` /
`ctx.get(...)` against the running backend.

---

## Decision 4 — Configuration + Authentication

**Question:** how is the server configured, and who proves they
should be talking to it?

**Decision:**

A new TOML file at `~/.dialekt/mcp-server.toml` captures server
configuration. It is separate from `config.json` (settings) so
pilot-level knobs don't mix with server-specific ones and so the
file can live under `chmod 600` without affecting other settings.

```toml
[server]
# List of acceptable API keys. Caller must match one to be allowed in.
# Keys themselves are opaque strings; we recommend `uuid4` or
# `secrets.token_urlsafe(32)`. Stored as a list so a pilot can
# rotate (add the new, remove the old after a day).
api_keys = [
    {id = "claude-desktop", value = "..."},
    {id = "cursor",         value = "..."},
]

# Which tool categories are enabled. Default = all three.
enabled_categories = ["database", "file", "agent"]

# Per-category tool enable/disable — defaults to "all tools in
# the enabled categories".
# enabled_tools = ["dialekt_list_connections", ...]
# disabled_tools = ["dialekt_invoke_agent"]

# Rate limit (calls/minute per API key).
rate_limit_per_minute = 120

# File tool allow-list (Decision 1 Category 2).
allowed_file_roots = []  # empty = file tools are effectively disabled

[server.transport.stdio]
enabled = true

[server.transport.http]
# Streamable HTTP defer to v0.25.0.
enabled = false
port = 8766
```

**Key management UX:**

- Settings → Integrations → "Copy MCP API Key" button generates
  a fresh key, stores it in the config, shows it once for the
  pilot to paste into Claude Desktop.
- "Rotate key" regenerates, keeping the old one valid for 24 h.
- Keys NOT stored in the dialekt keyring — the config file is
  already per-user and the keys are opaque identifiers, not
  long-lived credentials worth the extra moving parts.

**Claude Desktop / Cursor config example:**

```json
{
  "mcpServers": {
    "dialekt": {
      "command": "dialekt-mcp",
      "args": ["--api-key", "<paste from dialekt Settings>"]
    }
  }
}
```

The Settings UI offers a "Copy config snippet" button so the
pilot doesn't hand-assemble this.

**CLI flags on `dialekt-mcp`:**

```
dialekt-mcp --api-key KEY [--backend URL] [--config PATH]
```

- `--api-key` is required unless `--dev` (which short-circuits
  auth for development against a local dialekt — documented).
- `--backend` overrides the default `http://127.0.0.1:8765` for
  dev / multi-install scenarios.
- `--config` overrides the default `~/.dialekt/mcp-server.toml`.

**Environment variables (override mechanism):**

The flags above accept values from env vars when missing. Env vars
also work when `dialekt-mcp` is launched by Claude Desktop which may
set `env` in its config block rather than argv:

| Variable | Overrides | Default |
|---|---|---|
| `DIALEKT_BACKEND_URL` | `--backend` | `http://127.0.0.1:8765` |
| `DIALEKT_MCP_CONFIG_PATH` | `--config` | `~/.dialekt/mcp-server.toml` |
| `DIALEKT_MCP_API_KEY` | `--api-key` | — (one or the other required) |
| `DIALEKT_MCP_LOG_LEVEL` | — | `INFO` |

Claude Desktop example using env instead of argv:

```json
{
  "mcpServers": {
    "dialekt": {
      "command": "dialekt-mcp",
      "env": {
        "DIALEKT_MCP_API_KEY": "dsk_...",
        "DIALEKT_BACKEND_URL": "http://127.0.0.1:8765"
      }
    }
  }
}
```

Both forms are documented in the integration guide.

---

## Decision 5 — Multi-tenancy + Tool permissions

**Question:** one dialekt-mcp process per pilot, per API key, or
per arbitrary client?

**Decision:**

**One process per MCP client session.** Claude Desktop spawns one
`dialekt-mcp` subprocess for its single connection. Cursor spawns
its own. Each subprocess carries one API key (from its spawn
argv), authenticates against the config's allow-list, and runs
until the parent host disconnects the stdio pipe. Concurrent
connections = concurrent processes.

**No in-process multi-tenancy.** A single process serves a single
API key's perspective. This is simpler than a session-mux model
and matches how the ecosystem ships (every MCP server I surveyed
is single-session-per-process).

**Per-key tool scoping (v0.20.0: coarse):**

A key MAY declare a subset of tools it can access:

```toml
[server]
api_keys = [
    {id = "claude-desktop",
     value = "...",
     enabled_tools = ["dialekt_list_connections", "dialekt_query_database",
                      "dialekt_list_tables", "dialekt_describe_table"]},
    {id = "cursor",
     value = "..."},   # no enabled_tools = all tools allowed
]
```

If `enabled_tools` is omitted, the key can call anything in the
server-wide `enabled_categories`. If present, it's the exact
allow-list for that key.

**Per-agent scoping deferred.** The richer model — "API key X
represents agent A and can only reach tools agent A's manifest
permits" — requires a manifest-to-server-permission mapping that
is out of scope for v0.20.0. It lands in M3 when `dialekt_invoke_agent`
goes live and an API-key-as-agent-proxy makes sense.

---

## Decision 6 — Audit log

**Question:** how do server-side tool invocations appear in the
audit trail, and does the existing `audit_log` table accommodate
them?

**Decision:**

**Reuse the universal `audit_log` table** introduced in Commit 0
of Этап 1. Emit rows with `kind = "mcp_server_tool_call"`. The
helper is `dialekt.audit.log.log_event` — same entry point.

Column mapping:

| Column | Value on server-side tool call |
|---|---|
| `kind` | `"mcp_server_tool_call"` |
| `agent_id` | `NULL` — the server isn't agent-scoped; requests come from an external client that may not correspond to an agent |
| `binding_id` | `NULL` — same |
| `target` | API key id (e.g. `"claude-desktop"`) — i.e. *who* called |
| `action` | Tool name (e.g. `"dialekt_query_database"`) |
| `result` | `success`, `error`, `timeout`, `auth_failed`, `rate_limited`, `permission_denied` |
| `duration_ms` | Server-side handling time |
| `error_kind` | Exception class name when failing; NULL on success |
| `extra_json` | `{"args_preview": <truncated>, "backend_status": <HTTP code>}` |

**What is NOT logged:**

- Full tool arguments — a `query_database` SQL string could be
  thousands of characters with PII. We log a truncated preview
  (first 200 chars) and a hash of the full argument blob so a
  compliance query can correlate without storing the secret.
- Tool results — potentially huge (a 10,000-row SELECT). Results
  are NOT stored; only `result` status, `duration_ms`, and row
  count (for queries).

**Querying server activity per client:**

```sql
SELECT ts, action, result, duration_ms, error_kind
FROM audit_log
WHERE kind = 'mcp_server_tool_call'
  AND target = 'claude-desktop'
ORDER BY ts DESC LIMIT 50;
```

This is the same join surface operators already use for client-side
MCP events — one table, one discriminator, one SQL dialect.

---

## Decision 7 — Claude Desktop integration UX

**Question:** how does a pilot go from *"I installed dialekt"* to
*"Claude Desktop is talking to dialekt"* with the fewest clicks?

**Decision:**

Three-step flow, the last step is outside dialekt (in Claude
Desktop's own config UI).

**Step 1** — Pilot opens dialekt → Settings → Integrations.
A new panel "MCP Server (advanced)" shows:

- **Status**: running / not running (green dot / grey dot)
- **API Key**: `dsk_...` with "Copy" button
- **Claude Desktop snippet**: the JSON block, pre-populated with
  the pilot's key, with a "Copy snippet" button
- **Logs**: recent tool calls from the audit table, filtered to
  `kind = 'mcp_server_tool_call'`, readable by the pilot
- **Disable** toggle — if off, the `dialekt-mcp` binary refuses
  all authentication attempts

**Step 2** — Pilot clicks "Copy snippet". Dialekt surfaces a
toast: *"Copied. Paste into ~/Library/Application Support/Claude/
claude_desktop_config.json on macOS, or %APPDATA%\\Claude\\
claude_desktop_config.json on Windows. Restart Claude Desktop."*

**Step 3** — Pilot pastes, restarts Claude Desktop. Claude Desktop
spawns `dialekt-mcp --api-key ...`, `dialekt-mcp` authenticates
against the config, handshake completes, Claude Desktop lists
dialekt's tools in its UI.

**Discoverability fallback:** if pilot skips Settings and tries to
run `dialekt-mcp` without a valid key, the stderr message points
them at the Settings panel explicitly:

```
dialekt-mcp: no valid API key.

Open dialekt → Settings → Integrations → MCP Server to copy a key.
Then pass it via: dialekt-mcp --api-key <paste>

Configuration file: ~/.dialekt/mcp-server.toml
```

---

## Decision addendum — Packaging the `dialekt-mcp` binary

Not on the 7-question list but unavoidable for UX: how does
`dialekt-mcp` get on the pilot's `PATH`?

**v0.20.0 shipping modes:**

1. **Packaged desktop install (Tauri bundle)** — the dialekt
   installer (.dmg / .msi / .deb / AppImage) ships the
   `dialekt-mcp` Python script + its deps as a sidecar. Post-
   install hook creates a launcher on `PATH`:
   - macOS: symlink to `/usr/local/bin/dialekt-mcp`
   - Linux: symlink to `~/.local/bin/dialekt-mcp` (user-scoped,
     no sudo required)
   - Windows: add the install dir to user `PATH` via the installer
2. **Manual / dev install** — the Python source ships a
   `bin/dialekt-mcp` wrapper that runs `python -m dialekt.mcp.server.cli`.
   The pilot can symlink this wherever they like.

**Why not pip-install?** Because dialekt isn't currently a pip-
installable package — it's a Tauri desktop app. Adding a pip
distribution pathway is a separate project (packaging polish for
v1.0). For now, the installer-side symlink is simpler and keeps
the single-source-of-truth (the installed desktop app).

---

## Summary table — what ships in v0.20.0

| Area | Decision |
|---|---|
| Tools exposed | 9 total (5 DB + 2 file + 2 agent); `dialekt_invoke_agent` deferred to M3 to avoid shipping a non-working stub |
| Transport | stdio only; Streamable HTTP deferred to v0.25.0 |
| Backend access | HTTP to running dialekt instance via PluginContext |
| Config file | `~/.dialekt/mcp-server.toml` |
| Auth | API keys from config file; required on every connection |
| Multi-tenancy | One process per MCP client session |
| Tool scoping | Per-key `enabled_tools` allow-list (coarse); per-agent deferred to M3 |
| Audit | `audit_log` table, `kind='mcp_server_tool_call'`, reuses Этап 1 helper |
| Rate limit | 120 calls / min / key |
| Path safety (file tools) | `allowed_file_roots` allow-list in config; defaults empty |
| Invoke-agent | **Omitted** in v0.20.0 (lands in M3 as a real tool, not a stub) |
| Claude Desktop UX | Settings → Integrations → Copy snippet → paste → restart |
| Packaging | Installer-side symlink to `dialekt-mcp` wrapper |

---

## Этап 2 commit list (9 commits)

```
 1. feat(mcp/server): FastMCP skeleton + config loading
 2. feat(mcp/server): API key authentication + rate limiting
 3. feat(mcp/server/tools): database category (5 tools)
 4. feat(mcp/server/tools): file category (2 tools, allow-list enforced)
 5. feat(mcp/server/tools): agent category (list + get — invoke deferred to M3)
 6. feat(mcp/server): `dialekt-mcp` CLI entry point
 7. feat(server): /audit endpoint already shipped в Этап 1 — no-op
 8. docs: MCP Server integration guide for Claude Desktop
 9. test(mcp/server): e2e via MCPClient from Этап 1
```

Expected test count: +25-35, same ballpark as Этап 1 per-commit
deliveries.

---

## Review rulings (2026-04-24)

All four open questions resolved by the reviewer:

| # | Decision | Ruling |
|---|---|---|
| 1 | `dialekt_` tool-name prefix | **Keep.** Matches industry convention (`github_create_issue`, `slack_post_message`). Disambiguates when a host has multiple MCP servers connected. |
| 2 | Empty `allowed_file_roots` default | **Keep.** Secure by default — auto-creating a shared dir would expose files the pilot didn't explicitly grant. First-run experience is "file tools disabled until configured," which is the correct explicit-consent posture. Integration guide ships a worked example. |
| 3 | `dialekt_invoke_agent` shape | **Omit in v0.20.0.** MCP protocol contract is that advertised tools work when called. Shipping a stub that raises "not implemented" would violate that contract and damage trust with clients. `list_agents` + `get_agent` provide sufficient preview / discovery surface. `invoke_agent` lands in M3 as a real tool. |
| 4 | Backend precondition | **Keep explicit failure.** Auto-start would mask real problems (e.g. memory pressure from repeated restarts, config drift). The stderr message is actionable and points at the Settings panel. |

Additionally:

5. **Environment variable section added** (see Decision 4 block
   above) — `DIALEKT_BACKEND_URL`, `DIALEKT_MCP_CONFIG_PATH`,
   `DIALEKT_MCP_API_KEY`, `DIALEKT_MCP_LOG_LEVEL`. Saves hours of
   debugging for pilots deploying in custom environments.

## Sign-off

Approved by reviewer on 2026-04-24. Proceeding to Commit 1
(FastMCP skeleton + config loading).
