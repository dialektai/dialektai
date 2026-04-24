# Terminology clarification — "MCP servers" in dialekt

**Status:** Этап 0.2 deliverable for M2 Month 1.
**Date:** 2026-04-24.
**Audience:** contributors to dialekt internals; future-me reading
this in v1.0 and wondering why there's a `db_connectors/` alongside
a `mcp/`.

---

## The problem

Dialekt's codebase contains a directory named `python/mcp_servers/`
with three files:

```
python/mcp_servers/
├── postgres_mcp.py
├── mysql_mcp.py
├── clickhouse_mcp.py
└── schema_rag.py
```

**None of these are actual MCP servers.** They are FastAPI
`APIRouter` instances mounted into the dialekt backend at
`/postgres_mcp/...`, `/mysql_mcp/...`, `/ch_mcp/...`. They speak
plain HTTP+JSON, not JSON-RPC-over-stdio. They don't advertise
capabilities, they don't expose `tools/list`, they don't implement
the MCP handshake.

The naming was aspirational when dialekt was a smaller prototype —
"these are the things the LLM-plugin calls into for data access,
conceptually like MCP" — and it stuck. With M2 bringing in a
*real* MCP client (`dialekt.mcp.client`) and a *real* MCP server
(`dialekt.mcp.server`), the ambiguity is no longer tolerable.

## What they actually are

| What the code calls them | What they actually are |
|---|---|
| `python/mcp_servers/postgres_mcp.py` | FastAPI router implementing `/postgres_mcp/connect`, `/postgres_mcp/schemas`, `/postgres_mcp/query`, etc. Read-only DB connector, exposed via dialekt's own HTTP API. |
| `python/mcp_servers/mysql_mcp.py` | Same pattern for MySQL. |
| `python/mcp_servers/clickhouse_mcp.py` | Same pattern for ClickHouse. |
| `python/mcp_servers/schema_rag.py` | In-process helper for schema retrieval with embeddings. Never had a routing surface. |

The `_mcp` filename suffix on each router is **not** a protocol
marker — it's a historical "this file handles a connector" tag.

## Terminology going forward

### Layer A — internal DB connectors

The existing `postgres_mcp.py` / `mysql_mcp.py` / `clickhouse_mcp.py`
files are **internal connectors**: dialekt-specific FastAPI routers
that wrap a DB driver + credential store + safety parser and
expose a HTTP API consumed by our LLM plugins through
`PluginContext`. They are not going away; they are being renamed so
their purpose is obvious.

- **Old location:** `python/mcp_servers/`
- **New location:** `python/db_connectors/`
- **Old class/module suffix:** `_mcp` (e.g. `postgres_mcp`)
- **New module suffix:** none or `_connector` (preference: just drop
  the `_mcp`, so `postgres.py`, `mysql.py`, `clickhouse.py`).
- **New router prefixes (HTTP):** `/postgres/`, `/mysql/`,
  `/clickhouse/` — the current `/postgres_mcp/` etc. prefixes become
  backward-compat aliases until v1.0.

### Layer B — the MCP protocol (new in M2)

The new code for **real** MCP integration lives under
`python/dialekt/mcp/`:

```
python/dialekt/mcp/
├── __init__.py
├── client.py          # consumes external MCP servers
├── connection.py
├── transport.py       # stdio + Streamable HTTP adapters
├── auth.py
└── server/
    ├── __init__.py
    ├── server.py      # exposes dialekt as an MCP server
    ├── registry.py
    ├── database_tools.py
    └── file_tools.py
```

- **Protocol:** Model Context Protocol, spec revision `2025-11-25`.
- **SDK:** `mcp>=1.25,<1.27` from PyPI (pin rationale in
  `docs/M2_MCP_DESIGN.md` Decision 1 addendum — 1.27 transitively
  upgrades starlette past the fastapi + open-interpreter ceiling).
- **Transports:** stdio (primary) and Streamable HTTP.
- In user-facing docs and manifest YAML, "MCP server" means
  **exactly and only** this — a process speaking the Model Context
  Protocol.

### What to call each thing when speaking/writing

| Thing | Correct term | Avoid |
|---|---|---|
| `python/db_connectors/postgres.py` | "Postgres connector" / "internal Postgres router" | ~~"Postgres MCP server"~~ |
| A manifest's `connections.required` entry for Postgres | "required connection" | ~~"MCP server requirement"~~ |
| A manifest's new `mcp_servers` entry (Этап 1) | "external MCP server" / "MCP server dependency" | ~~"connector"~~ |
| `dialekt.mcp.client.MCPClient` | "MCP client" | ~~"connector client"~~ |
| `dialekt.mcp.server.MCPServer` | "dialekt MCP server" / "dialekt-as-MCP" | — |
| HTTP endpoint like `/postgres_mcp/query` | "the legacy Postgres connector endpoint" | — |

---

## Migration path

### Phase 1 — v0.20.0 release (end of M2 Month 1)

- `python/mcp_servers/` is renamed to `python/db_connectors/` in a
  single commit. All imports updated in the same commit so the
  test suite stays green.
- At the old import path, ship a deprecation shim:
  ```python
  # python/mcp_servers/__init__.py
  import warnings
  from dialekt._deprecation import deprecated_module_redirect
  warnings.warn(
      "python/mcp_servers has been renamed to python/db_connectors; "
      "update imports. This shim is removed in v1.0.",
      DeprecationWarning,
      stacklevel=2,
  )
  from db_connectors import *  # noqa: F401,F403
  ```
- FastAPI legacy route prefixes (`/postgres_mcp/...`) continue to
  work — they simply proxy to the new `/postgres/...` handlers —
  so any third-party tooling that hits the dialekt HTTP API keeps
  working. A deprecation header is added to responses.
- **Introduced in v0.20.0:** `python/dialekt/mcp/` as described
  in Layer B above.

### Phase 2 — v0.25.0 (mid-M2)

- New code MUST NOT import from `mcp_servers`. CI job grep-guards
  against it.
- Release notes carry a migration guide.

### Phase 3 — v1.0.0

- Remove `python/mcp_servers/` shim entirely.
- Remove `/postgres_mcp/` HTTP aliases (keep `/postgres/`).
- Any lingering `_mcp` filenames in internal code are gone.

At v1.0 the codebase reads unambiguously: "mcp" means the protocol,
"connector" means an internal dialekt abstraction.

---

## A note on `audit_log` (introduced in v0.20.0)

A third term that benefits from disambiguation now that we're adding
it:

- **`audit_log`** (SQLite, `~/.dialekt/dialekt.db`, v0.20.0+) —
  universal action log for the dialekt desktop backend. Records
  MCP tool calls in v0.20.0; will also cover SQL queries, file
  operations, and agent lifecycle events in M2 Month 2 via the same
  `kind` discriminator column. Pilot-local, never sent to cloud.
- **Not related to `founder_admin_log`** (PostgreSQL, dialekt-cloud
  service) which records cross-tenant administrative actions by
  dialekt founders — license issuance, tenant creation, invoice
  generation. Different table, different database, different
  audience. The names are similar by coincidence; the datasets
  never mix.

---

## User-facing documentation rules

In public docs — `README.md`, `CAPABILITIES_INVENTORY.md`,
`TOOLS_AVAILABLE_TODAY.md`, `AGENT_MANIFEST_SPEC.md` — follow this
discipline:

1. **Never write "MCP server" when you mean "database connector."**
   If an agent manifest uses `connections.required`, it's a
   *connection*, not an MCP server. This is the #1 source of
   confusion for new contributors today.
2. **Use "external MCP server" for third-party MCP processes** the
   agent wants to talk to (GitHub MCP, Slack MCP, a custom
   internal one). In manifest YAML this lives under the new
   `mcp_servers:` key (Этап 1).
3. **Use "dialekt MCP server"** when referring to the process
   started by `dialekt-mcp` (Этап 2) that exposes dialekt itself.
4. When editing old docs that use the confusing terminology, leave
   the original sentence intact but add a footnote or parenthetical:
   `"Postgres MCP server (renamed to 'Postgres connector' in
   v0.20.0)"`. Don't silently rewrite history.

## Summary (one paragraph)

Before M2, "mcp_servers" in dialekt meant "the internal FastAPI
routers that expose DB drivers to our LLM plugins." From M2
onwards, those are renamed `db_connectors`, and "MCP" in dialekt
means exclusively the open Model Context Protocol — consumed by
`dialekt.mcp.client` (external servers in) and produced by
`dialekt.mcp.server` (dialekt exposed as server out). Old import
paths and HTTP route aliases stay working with deprecation warnings
through v0.25.0, then are removed in v1.0.
