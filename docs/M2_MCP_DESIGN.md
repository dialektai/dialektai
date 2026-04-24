# M2 MCP design decisions

**Status:** Этап 0.3 deliverable — design gate before Этап 1 code.
**Date:** 2026-04-24.
**Scope:** dialekt as MCP **client** (consume external servers) and
dialekt as MCP **server** (expose itself to external clients).
**Reviewer stop point:** after approving this document; NO code
written before sign-off.

References:
- [MCP_RESEARCH_2026-04.md](MCP_RESEARCH_2026-04.md)
- [TERMINOLOGY_CLARIFICATION.md](TERMINOLOGY_CLARIFICATION.md)
- [PLUGIN_ARCHITECTURE.md](PLUGIN_ARCHITECTURE.md)
- [AGENT_MANIFEST_SPEC.md](../AGENT_MANIFEST_SPEC.md)

Spec revision targeted: **2025-11-25**. SDK: **`mcp>=1.25,<1.27`**
(see Decision 1 addendum below for why 1.27 is held back).

---

## Decision 1 — Transport

**Question:** stdio / Streamable HTTP / legacy SSE / all of the above?

**Decision:**

| Direction | Primary | Secondary | Not shipped |
|---|---|---|---|
| Client (we consume external servers) | **stdio** | **Streamable HTTP** | legacy SSE |
| Server (we expose dialekt) | **stdio** (v0.20.0) | **Streamable HTTP** (v0.25.0) | legacy SSE |

**Why:**

- stdio is the dominant transport across the current ecosystem. Every
  reference server and vendor-owned server (GitHub, Slack, Brave)
  ships a stdio entry point by default. Shipping stdio first means
  on day one we can talk to 95% of available MCP servers.
- Streamable HTTP is the spec-preferred remote transport. We need
  it for two workflows:
  (a) an agent manifest points at a company-hosted internal MCP
      server over HTTPS (no subprocess spawn possible);
  (b) users want Claude Desktop on another machine to reach their
      dialekt as a server over Tailscale / Cloudflare tunnel.
- Legacy SSE (two-endpoint `/sse` + `/message`) is deprecated. New
  code only. If a specific vendor server ships SSE-only, we revisit.
- On the server side, stdio ships in v0.20.0 because it unlocks the
  flagship use case: Claude Desktop users adding dialekt to their
  `mcpServers` config. HTTP is a stretch into v0.25.0 because it
  adds auth and deployment surface we don't need on day one.

**Implementation note:** the Python SDK provides `stdio_client`,
`streamablehttp_client`, and `sse_client` helpers on the client side
and `FastMCP` with `transport="stdio" | "streamable-http"` on the
server side. We don't hand-roll any wire code.

**Addendum (2026-04-24, during Этап 1 setup):** the initial plan
pinned `mcp>=1.27,<2`. Installing 1.27.0 into the existing venv
failed — the 1.27 line requires `sse-starlette>=3.x`, which itself
requires `starlette>=1.0`. Dialekt's current `fastapi==0.115.2` and
`open-interpreter==0.4.3` both cap `starlette<0.38`; the conflict
broke `Router.__init__()` (13 existing tests failed with
`unexpected keyword argument 'on_startup'`).

`mcp 1.26.0` accepts `starlette>=0.27` (loose), and pairing it with
`sse-starlette<3` holds starlette at 0.37.2. All imports we actually
consume (`stdio_client`, `streamablehttp_client`, `ClientSession`,
`types`) are present and stable in 1.26. The 1.27-only additions —
RFC 8707 OAuth resource validation, Streamable HTTP idle timeout,
and stdio non-UTF-8 byte handling — are not required by v0.20.0.

**Effective pin therefore:** `mcp>=1.25,<1.27` with explicit
`sse-starlette<3` to defend against a transitive drift. Upgrade to
1.27+ is scheduled for when we concurrently bump `fastapi` and
`open-interpreter` to versions that accept `starlette>=1.0` — that
is its own task, not part of M2 Month 1.

---

## Decision 2 — Authentication and credentials

**Question:** how do we store and scope credentials for external
MCP servers the user configures?

**Decision:**

1. **Storage mechanism: reuse the existing keyring path** used by
   `python/dialekt/secrets.py` (the same one `connections` uses
   for DB passwords). Keyring service name namespaced as
   `dialekt.mcp.<server_name>.<credential_key>`.
2. **Scoping: per-agent, not per-pilot.** A given agent manifest
   declares which MCP servers it needs; credentials are attached to
   the *binding* in SQLite (`agent_bindings` table, extended with
   `mcp_credentials` JSON column storing keyring lookup keys, NEVER
   the plaintext). This matches how `connections` already scope.
3. **Per-pilot storage** (shared across all that pilot's agents) is
   deferred to M3 when multi-pilot pilot-aware credential
   management lands. For v0.20.0, each agent ↔ each MCP server
   ↔ its own credential row.
4. **Auth schemes supported in v0.20.0:**
   - **Env vars for stdio servers** — passed into the subprocess
     environment (this is how GitHub MCP wants its `GITHUB_TOKEN`).
   - **Bearer token header for HTTP servers** — `Authorization:
     Bearer <token>`.
   - **None** (for loopback / trusted subprocess servers).
5. **Auth schemes deferred:**
   - OAuth 2.1 flows for remote MCP servers — the SDK supports this
     but it's a multi-step consent UX; land it in M3 alongside the
     pilot-scoped credential store.
   - Mutual TLS for internal HTTP servers — enterprise-only, no
     demand from current design partners.

**Audit:** every MCP tool invocation writes an audit row via the
universal `audit_log` table introduced in Commit 0 (see Decision 7
below). Fields: `(kind='mcp_tool_call', agent_id, binding_id,
target=mcp_server_name, action=tool_name, result, duration_ms,
error_kind?, extra_json?)`. Tool *arguments* and *results* are not
stored at rest by default — they may be large and may contain user
data. A per-agent "verbose audit" flag (off by default) can opt into
storing truncated arg/result summaries in `extra_json` for debugging.

**Rationale for not inventing a new storage layer:** dialekt already
solved credential storage for DB connections (keyring + SQLite
pointer rows). Re-using it means one threat model, one backup story,
one test surface. Introducing a parallel credential system just
because the consumer is "MCP" instead of "Postgres" would be
gratuitous complexity.

---

## Decision 3 — Manifest schema integration

**Question:** how does a manifest declare that an agent needs
external MCP servers?

**Decision:**

Add a new top-level key `mcp_servers` (plural, list). Bump manifest
spec from **`1.0.1`** → **`1.1.0`** (minor, additive — existing
1.0.x manifests remain valid in 1.1.0 loaders). Bump the
`dialekt-manifest-validator` package to `0.3.0` and publish via a
GitHub tag, same release mechanic as `0.2.0`.

**Schema shape:**

```yaml
spec_version: "1.1.0"
minimum_dialekt_version: "0.20.0"

# ... existing fields unchanged ...

mcp_servers:
  - name: "github"                  # unique within manifest, kebab-case
    description: "GitHub repo ops"  # human summary
    transport: "stdio"              # stdio | http
    # stdio-only fields:
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "${secrets.github_token}"
    # http-only fields:
    # url: "https://jira.company.internal/mcp"
    # auth:
    #   type: "bearer"
    #   token: "${secrets.jira_token}"
    timeout_seconds: 30
    # Scoping — which tools from this server are allowed.
    # Default: all tools the server advertises.
    allow_tools: ["*"]
    # OR: explicit allow-list
    # allow_tools: ["list_repos", "create_issue"]
    deny_tools: []
```

**Validator changes (`dialekt-manifest-validator` 0.3.0):**

- New Pydantic model `MCPServerSpec` with discriminated union on
  `transport`.
- `spec_version` accepts `1.0.x` or `1.1.x`; the `mcp_servers` key
  is disallowed for `spec_version < 1.1.0` (clear error message).
- `secrets_required` auto-extends to include any `${secrets.*}`
  references inside `mcp_servers[].env` or `mcp_servers[].auth.token`,
  so the existing secret-onboarding UX works without code changes.
- 8-12 new validator tests covering: valid stdio, valid http, both
  transports mixed, missing command, unknown transport, unknown
  auth.type, version-gating, secret auto-extension.

**`capabilities.groups` interaction:** we add a new group name
`mcp_tools`. If an agent's `mcp_servers` list is non-empty, the
validator requires `mcp_tools` to be present in `capabilities.groups`.
This gives dialekt a single switch to refuse an agent that tries to
"smuggle in" MCP access via manifest without declaring the capability
it needs.

---

## Decision 4 — Runtime integration with `PluginContext`

**Question:** how does an agent's Python runtime actually call an
MCP tool?

**Decision:**

The existing `PluginContext` grows one new method — a **factory**,
not a cache:

```python
class PluginContext:
    def new_mcp_manager(self, agent_id: str, **kwargs) -> MCPClientManager: ...
```

Inside the manager, individual `MCPClient`s are created **lazily**
on first use (first `call_tool` for a given `server_name`) and
**cached until `manager.shutdown()`**. Subsequent calls reuse the
open `ClientSession`.

**Factory, not cache — revised during Этап 1 (2026-04-24):** the
original plan cached managers inside `PluginContext`. The first-
pass design doc (pre-implementation) used the wording "cached for
the agent's lifetime," which — in retrospect — conflates *agent*
(a manifest template) with *agent session* (one WebSocket chat).
Caching managers in the context means they would survive across
chat sessions, which leaks MCP subprocesses and HTTP clients every
time a pilot opens a new chat.

Factory semantics make ownership unambiguous: each `ws_chat` session
creates its own manager at connect, tears it down at disconnect.
This matches existing `PluginContext` patterns (DB pools, file
handles) — the context provides the wiring, the session owns the
state.

**Tool-call path:**

1. `ws_chat` session connects → handler calls
   `mgr = ctx.new_mcp_manager(agent_id)`.
2. Agent's Open Interpreter Python block calls a thin generated
   wrapper: `ctx.mcp.github.list_repos(org="dialektai")` (Commit 9
   wires the wrapper).
3. Wrapper resolves to
   `await mgr.call_tool("github", "list_repos", {...}, transport=...,
   credentials=..., binding_id=...)`.
4. Manager lazily opens the MCPClient if needed, enforces rate
   limit + timeout, calls JSON-RPC `tools/call`, classifies any
   error via `classify_sdk_error`, emits an audit row, returns
   the structured result.
5. `ws_chat` session disconnect → handler awaits `mgr.shutdown()`,
   which closes every open client.

**Why lazy + cached _inside the manager_:** eager init at agent
start would spawn every configured MCP server every time an agent
loads, even if the user never triggers its tools. On resource-
constrained laptops this is unacceptable (we already fight RAM for
the Ollama model). Lazy means subprocess spawns happen on demand;
cached-within-manager means we're not paying handshake cost per
message.

**Lifecycle:** when a chat session ends (`ws_chat` disconnect), the
session handler — the owner — awaits `mgr.shutdown()`. The context
does NOT register managers, does NOT chase them on `ctx.close()`.
This keeps the ownership rule ("the creator shuts it down") crisp.

**Thread/loop safety:** the existing persistent-portal pattern
(see PLUGIN_ARCHITECTURE.md) already solves "asyncpg pool bound to
a specific loop." MCP's `anyio`-based client is similarly
loop-pinned. The portal handles this uniformly; we don't introduce
a separate async executor.

**Open Interpreter exposure:** since OI doesn't natively await, the
wrappers call `asyncio.to_thread` internally to dispatch onto the
portal. Agents write straight synchronous-looking Python.

---

## Decision 5 — Security and sandboxing

**Question:** what keeps a malicious or compromised MCP server from
doing damage?

**Decision:**

A layered posture, not one big switch:

1. **Subprocess isolation (stdio servers):** spawned with explicit
   `env=` (not inherited — we hand-pass only what's declared in the
   manifest), `cwd=` set to the agent's workspace dir under
   `~/.dialekt/agents/<id>/workspace/`, and file descriptors other
   than stdin/stdout/stderr closed. On Linux we additionally apply
   a `preexec_fn` setting a low `RLIMIT_NPROC` + `RLIMIT_AS` so a
   runaway MCP server can't fork-bomb or OOM the host. This is
   best-effort, not a true sandbox — users who need real isolation
   are directed to run dialekt inside a container.
2. **No shell interpolation, ever.** Commands are `list[str]`, not
   a string. The validator enforces `command` is a list.
3. **Allow/deny tool lists at the manifest layer** (Decision 3)
   limit what the agent is even *allowed* to call on a connected
   server, independent of what the server advertises.
4. **Tool-call rate limiting:** per agent session, default 60 tool
   calls/min across all MCP servers, configurable per manifest via
   a new optional `mcp_rate_limit` block. Rate-limit breach raises
   `MCPRateLimitError`, which the LLM can recover from (it's just a
   tool error), but repeated breaches get logged as a warning and
   shown in the UI.
5. **Per-tool-call timeout:** default 30s (from Decision 3's
   `timeout_seconds`). Hitting it cancels the JSON-RPC request,
   logs a `timeout` audit row, and returns a structured error to
   the LLM.
6. **Consent gating on write-shaped tools:** when an MCP tool is
   declared by the server with the MCP `annotations.destructive`
   or `annotations.writeable` hint, dialekt enforces the agent's
   `autonomy` setting. `autonomy: ask-before-write` means the UI
   surfaces a consent card before the call dispatches. `full-auto`
   skips. Read-only tools dispatch without consent.
7. **Audit log everywhere** (see Decision 2).
8. **Server process dies → fail closed.** If an MCP subprocess
   crashes, its client is marked dead; subsequent tool calls return
   `MCPServerUnavailableError` immediately (no silent restart). The
   UI shows a "server disconnected" banner and offers an explicit
   restart button — user stays in control.

**What we explicitly DO NOT promise:** sandboxing at the OS
container level. That is out of scope for v0.20.0 and documented as
a known limitation.

---

## Decision 6 — Error handling and graceful degradation

**Question:** what happens when an MCP server is unreachable,
misconfigured, times out, or returns garbage?

**Decision:**

A small error taxonomy — every failure maps to exactly one of:

| Error class | When | Agent-visible? | Retry? |
|---|---|---|---|
| `MCPConfigError` | Manifest/credentials wrong at load time | No — surfaces in UI, agent won't start | Manual |
| `MCPServerUnavailableError` | Subprocess dead or HTTP 5xx / connect refused | Yes, as tool error | Next call triggers lazy reconnect once |
| `MCPToolNotFoundError` | Agent asked for a tool the server doesn't advertise | Yes | Never (deterministic) |
| `MCPToolError` | Server returned an MCP-level tool error payload | Yes (full error.message passed to LLM) | Up to LLM to decide |
| `MCPTimeoutError` | Per-call timeout hit | Yes | Up to LLM |
| `MCPRateLimitError` | Our own rate limit tripped | Yes | Backoff |
| `MCPProtocolError` | Malformed JSON-RPC, unknown method, version mismatch | Yes, log as warning | Never |

**Startup-time checks:**

- Manifest load fails (and shows a clear error in the UI) if:
  - Any required `${secrets.*}` for an MCP server is missing.
  - stdio `command[0]` cannot be located on PATH.
  - `spec_version` is `1.1.0+` but the dialekt version in use is
    older than `minimum_dialekt_version`.
- Manifest loads with a **warning** (agent starts, but MCP features
  degraded) if:
  - An `http` MCP server URL doesn't resolve on initial DNS probe.
    The client will retry on first actual call; we don't block
    agent start on a network blip.

**Runtime fallback:**

- If an MCP server used by an agent becomes unavailable mid-session,
  the UI shows an inline "some tools unavailable" banner but the
  agent keeps running — the LLM simply gets "tool unavailable"
  errors if it tries to call those tools and can route around them.
  This matches the existing pattern where a DB connection drop
  doesn't kill the chat.
- An agent whose `capabilities.groups` includes `mcp_tools` but
  whose configured servers are all down falls back to same behaviour
  as if they weren't configured — it just can't do MCP things until
  servers return.

**No silent retries.** Transport-level retries are bounded to exactly
one reconnect attempt per call path and never hidden from the audit
log. If the LLM wants to retry, it retries visibly.

---

---

## Decision 7 — Audit log storage

**Question:** where and how do MCP tool invocations get recorded?

**Decision:**

Audit data lives **SQLite-locally** in the pilot's desktop DB at
`~/.dialekt/dialekt.db`, in a new universal `audit_log` table
shipped in Commit 0. It is **not** sent to dialekt-cloud. Audit
data belongs to the pilot; it follows the desktop-first architecture
of dialekt and mirrors how conversations, connections, and
credentials already stay local.

**Discovered during Этап 0 verification:** no pre-existing audit
sink existed in the desktop backend (grep on `audit` in `python/`
returned zero hits). The cloud service has a `founder_admin_log`
table, but that covers cross-tenant admin actions and is not a fit
for per-agent tool-call auditing. Rather than retrofitting one of
the chat-oriented tables (`sessions` / `messages`) to double as an
audit log, we ship a purpose-built table with a discriminator column
so future action kinds (SQL queries, file ops, lifecycle events)
can migrate into the same table without a schema change. Variant B
(narrow v0.20.0 scope, migrations later) was chosen over Variant A
(migrate all three DB connectors in this release) to keep Этап 1
inside its timebox.

**Schema (shipped in Commit 0, `audit_log` table):**

```sql
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    agent_id    TEXT,                        -- NULL for system actions
    binding_id  TEXT,                        -- NULL if no binding
    kind        TEXT NOT NULL,               -- 'mcp_tool_call' | future: 'sql_query', 'file_op', ...
    target      TEXT,                        -- mcp_server_name | connection_name | file_path
    action      TEXT NOT NULL,               -- tool_name | 'execute_sql' | 'read_file'
    result      TEXT NOT NULL,               -- 'success' | 'error' | 'timeout' | 'rate_limited'
    duration_ms INTEGER,
    error_kind  TEXT,                        -- NULL when result='success'
    extra_json  TEXT                         -- flexible payload
);

CREATE INDEX idx_audit_log_ts       ON audit_log(ts);
CREATE INDEX idx_audit_log_agent_id ON audit_log(agent_id, ts);
CREATE INDEX idx_audit_log_kind     ON audit_log(kind, ts);
```

**`kind` is an unconstrained string** on the schema level — future
values are added by writing code that emits them, no migration
needed. Indexes are provisioned up front so that once SQL-query
logging lands in M2 Month 2 and the table grows to 100k+ rows, it
performs. This is the point where adding indexes after the fact
would be painful.

**Universal helper API** (in `python/dialekt/audit/log.py`):

```python
async def log_event(
    db: aiosqlite.Connection,
    *,
    kind: str,
    action: str,
    result: str,
    agent_id: str | None = None,
    binding_id: str | None = None,
    target: str | None = None,
    duration_ms: int | None = None,
    error_kind: str | None = None,
    extra: dict | None = None,
) -> int: ...
```

**No MCP-specific helper** (no `log_mcp_tool_call()`). That would
lock in the current shape and force a rewrite when SQL-query or
file-op logging joins. MCP-call sites build kwargs like
`kind="mcp_tool_call", target=server_name, action=tool_name` and
hand them to `log_event`. The helper stays universal.

**v0.20.0 coverage:** MCP tool calls only. SQL queries, file ops,
and lifecycle events migrate into the same table in M2 Month 2
(separate task, separate PR).

**Why SQLite and not PostgreSQL:** dialekt is desktop-first. The
pilot owns their data; sending audit rows to a cloud store without
explicit consent would violate the trust model we already applied
to chat history and DB credentials. If a pilot wants cross-machine
audit consolidation later, that's a consent-gated sync feature,
not a default.

---

## Summary table — what ships in v0.20.0

| Area | Decision |
|---|---|
| Protocol spec | MCP 2025-11-25 |
| Python SDK | `mcp>=1.25,<1.27` + `sse-starlette<3` (1.27 held back pending fastapi/open-interpreter bump — see Decision 1 addendum) |
| Transports (client) | stdio, Streamable HTTP |
| Transports (server) | stdio only (HTTP deferred to v0.25.0) |
| Manifest | new `mcp_servers:` block, spec `1.1.0`, validator `0.3.0` |
| Capability group | new `mcp_tools` |
| Credentials | keyring, per-agent-binding, env-var or bearer |
| OAuth | deferred to M3 |
| Runtime surface | `PluginContext.get_mcp_client()`, lazy, cached per agent |
| Sandboxing | subprocess isolation + rlimits + rate limit + consent gating |
| Audit log | SQLite-local universal `audit_log` table, MCP-only coverage in v0.20.0; SQL queries + file ops migrate in M2 Month 2 |
| Error model | 7 concrete exception classes, one reconnect, no silent retry |

## Этап 1 commit list (11 commits)

Updated to include audit infrastructure as Commit 0 — see
Decision 7.

```
0.  feat(audit): audit_log table + log_event universal helper
1.  feat(mcp): add Python MCP SDK dependency
2.  feat(mcp/client): module skeleton
3.  feat(mcp/client): MCPClient basic implementation
4.  feat(mcp/client): stdio transport
5.  feat(mcp/client): HTTP transport
6.  feat(mcp/client): credentials storage integration
7.  feat(mcp/client): integration with PluginContext
8.  feat(schema): v0.3.0 add mcp_servers to manifest
9.  feat(runtime): expose MCP tools to agents
10. docs: MCP client documentation
11. test(mcp): client integration tests
```

STOP point (per user instruction): after commits 0-3 (audit infra +
SDK dep + skeleton + basic MCPClient), run the full test suite and
hand back a diff summary before writing transports in commit 4.

---

## What this document is not answering

- **Which specific third-party MCP servers dialekt bundles in its
  first-run experience.** That's a catalog/product question, not an
  architecture question. Decided closer to release.
- **Whether the dialekt MCP server (Этап 2) exposes multi-tenant
  endpoints.** Single-user-per-process for v0.20.0; revisit in M3
  when cloud workspaces land.
- **Discovery UI** — in-app "browse and install an MCP server" flow.
  Manual paste-manifest-YAML only in v0.20.0; a registry browser is
  post-M2.

## Sign-off

Approve this document (or request changes) before Этап 1 code starts.
