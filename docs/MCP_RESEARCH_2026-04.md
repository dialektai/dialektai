# MCP Ecosystem Research — April 2026

**Status:** Этап 0.1 deliverable for M2 Month 1.
**Date:** 2026-04-24.
**Sources:** modelcontextprotocol.io, pypi.org/project/mcp, github.com/modelcontextprotocol/servers.

The purpose of this document is to answer: *what does the MCP world
actually look like as we enter Q3 2026, and what does that mean for
the scope of our own client + server work?*

---

## 1. Protocol spec

- **Latest revision:** `2025-11-25` — the spec at
  modelcontextprotocol.io/specification is pinned to this revision.
- **Transport:** JSON-RPC 2.0 over one of three wire formats.
  - `stdio` — process-local. Host spawns server as subprocess, talks
    JSON-RPC over stdin/stdout. This is the dominant pattern for
    desktop integrations (Claude Desktop, Cursor, VSCode).
  - **Streamable HTTP** — the current recommended remote transport
    (supersedes the standalone `SSE` transport). Single HTTP endpoint
    that can upgrade to SSE for server-to-client streaming.
  - `SSE` — legacy two-endpoint variant (`/sse` + `/message`). Still
    supported for backwards compat but new servers should ship
    Streamable HTTP.
- **Topology:**
  - **Host** — the LLM application (Claude Desktop, our dialekt).
  - **Client** — the connector inside the host that speaks to ONE
    server. A host with three connected servers runs three clients.
  - **Server** — the thing exposing resources/tools/prompts.
- **Server-offered features:**
  - `Resources` — read-only context (files, records, pages) loaded
    into the model's context. GET-shaped.
  - `Tools` — callable functions the model can invoke. POST-shaped,
    side-effects allowed.
  - `Prompts` — reusable prompt templates parameterised by the user.
- **Client-offered features (for servers to request back):**
  - `Sampling` — server asks the host to run an LLM call on its
    behalf (server-initiated agentic recursion).
  - `Roots` — server asks "which URIs / filesystem paths am I allowed
    to operate on?"
  - `Elicitation` — server asks the user a follow-up question
    mid-flow.
- **Security posture per spec:** consent-first. The spec explicitly
  says the protocol can't enforce this at the wire level; the host
  MUST build consent UIs, tool-gating, and sampling controls.

**Implication for dialekt:** as a host, we need a consent/approval
UI before any external MCP tool runs. This is already implicit in
our `autonomy` field (`ask-before-write`) — we extend that to cover
MCP tool calls.

---

## 2. Python SDK status

- **Package:** `mcp` on PyPI, managed by `modelcontextprotocol/python-sdk`.
- **Latest:** `1.27.0`, released **2026-04-02**.
- **Python:** `>=3.10` (dialekt runs Python 3.12, fine).
- **Dev status classifier:** `4 - Beta` — the SDK is still labelled
  beta, BUT it's at version 1.27 and has 22k+ GitHub stars, so
  "beta" is conservative tagging, not "experimental."
- **Transports supported:** stdio, SSE, Streamable HTTP — all three.
- **High-level API:** `FastMCP` (decorator-based, Flask-like) for
  servers; client side exposes `stdio_client`, `streamablehttp_client`,
  `sse_client` helpers plus a `ClientSession` wrapper.
- **Extras:** `cli`, `rich`, `ws` (optional features).
- **Auth:** SDK supports OAuth 2.1 and token verification on the
  server side. Not all flows are needed for v0.20.0 — we start with
  static bearer tokens and env-var API keys, defer OAuth to M3.

**Dependency impact:** adding `mcp>=1.27,<2` to
`python/requirements.txt` brings in `anyio`, `httpx`, `pydantic`,
`jsonschema`, `sse-starlette`, `starlette`, `uvicorn` — all of which
dialekt already pulls in transitively through FastAPI. No new heavy
dependencies.

---

## 3. Reference servers (current)

The `modelcontextprotocol/servers` repo now holds a small, curated
set of reference servers. Everything else has been pushed out to
community maintenance or dedicated repos.

**Currently maintained reference servers:**

| Name | Language | What it does |
|---|---|---|
| `everything` | TS | Test/demo server exercising every MCP feature |
| `fetch` | TS | Fetch a URL and return cleaned content |
| `filesystem` | TS | Bounded file read/write/list/watch |
| `git` | Python | Read/search/manipulate Git repos |
| `memory` | TS | Knowledge-graph persistent memory |
| `sequential-thinking` | TS | Structured reasoning helper |
| `time` | Python | Time and timezone conversions |

**Archived (still usable from `servers-archived`):**

- `postgres` (read-only SQL) — **most relevant to us**; this was
  the original reference for database MCP.
- `sqlite`, `redis`.
- `google-drive`, `google-maps`.
- `brave-search` — replaced by Brave's own official server.
- `github`, `gitlab` — moved out to vendor-owned repos
  (`github/github-mcp-server` is the canonical GitHub one).
- `slack` — now maintained by Zencoder.
- `puppeteer` — archived; community is on Playwright forks.
- `sentry`, `aws-kb-retrieval`, `everart`.

**Takeaway:** the reference repo is shrinking; MCP is now a real
ecosystem where vendors own their own servers (GitHub, Brave,
Zencoder/Slack). Our choice of which third-party servers to test
dialekt against should follow the **vendor-owned** ones, not the
archived community refs — those are likely to be better maintained
and audited.

---

## 4. Community / third-party server landscape

The repo's README now redirects server discovery to the **MCP
Registry** (registry.modelcontextprotocol.io) and points at several
community indexes:

- **PulseMCP** (pulsemcp.com) — has an API, easy to scrape for
  dialekt's in-app discovery UI later.
- **Smithery** (smithery.ai) — registry + hosted MCP servers.
- **mcp.run** — hosted control plane for running MCP servers.
- **Klavis AI** — open-source MCP infrastructure, notable because
  it's the OSS alternative to Smithery for self-hosters.
- `awesome-mcp-servers` lists (punkpeye, appcypher, wong2) —
  traditional Awesome-style curated inventories.

**High-signal community servers we should make sure our client
works with:**

1. `@modelcontextprotocol/server-github` (official from GitHub)
2. `server-slack` (Zencoder)
3. `mcp-server-git` (official reference, Python)
4. `server-filesystem` (official reference, TS)
5. `github/github-mcp-server` — now the canonical GitHub MCP

**Frameworks worth noting:**

- `mxcp` (Python) — "enterprise MCP servers using YAML + SQL +
  Python, with built-in auth, monitoring, ETL and policy
  enforcement." This is **directly adjacent to dialekt's territory**
  (database-as-MCP-tool). We should read its design for prior art.
- `FastAPI-to-MCP` adapters (Tadata) — auto-expose FastAPI as MCP.
  We could consider this for exposing dialekt-as-server in v1.0, but
  for v0.20.0 we'll write our server by hand using FastMCP so we
  keep fine-grained tool control.

---

## 5. TypeScript vs Python SDK maturity

| Dimension | TypeScript | Python |
|---|---|---|
| First-party SDK | ✅ `@modelcontextprotocol/sdk` | ✅ `mcp` |
| Reference-server language | Dominant (5/7) | Minor (2/7 — git, time) |
| Desktop ecosystem (Claude Desktop, Cursor) | Primary integration surface | Works via stdio |
| Streamable HTTP support | Mature | Mature (1.27) |
| Observed community velocity | Higher | Growing |

**Neutral:** both SDKs implement the full spec. TS has more
reference surface because it ships the most reference servers, but
for dialekt — a Python backend already — Python is the obvious
choice. No compromise.

---

## 6. Competitive landscape specific to dialekt's lane

Dialekt's differentiator is **local-first AI agents with BYO data**.
The MCP angle intersects with:

1. **`mxcp`** — closest direct competitor in positioning. YAML-
   configured MCP servers over SQL, enterprise auth, ETL. But
   `mxcp` is server-side only; dialekt is a full desktop agent host
   AND eventually a server. We don't overlap 1:1 — we're adjacent.
2. **Archived `postgres` reference server** — the "obvious" way to
   do database MCP right now. Read-only, schema inspect, execute
   SQL. Dialekt's existing `postgres_mcp.py` internal router already
   does this, it just isn't addressable as real MCP yet.
3. **Smithery / Klavis / mcp.run** — hosting/registry plays. Not
   competitors to dialekt's desktop agent; potential distribution
   partners once we have a published dialekt MCP server package.

**Strategic read:** nobody in the landscape today bundles
(a) desktop agent host, (b) local LLM runtime, (c) its own MCP
server exposing *that agent's databases* back out to external hosts.
Shipping Этап 2 (dialekt-as-MCP-server) is what would make dialekt
uniquely an **ecosystem member** rather than just another host.

---

## 7. Implications for our M2 plan

1. **Python SDK is ready.** `mcp>=1.27,<2` is fine as a hard
   dependency. Pin to `~=1.27` so we pick up 1.27.x patches but
   don't auto-jump to a future 2.x that may break.
2. **Transport priority:** stdio first (matches everything the
   ecosystem actually ships), Streamable HTTP second (for our own
   exposed server so Claude Desktop can reach us remotely). Skip
   legacy SSE — new code only.
3. **Spec version to test against:** `2025-11-25`. Record this in
   manifest schema as a compatibility floor so an older manifest
   can refuse to load if the host supports only an older spec.
4. **First external MCP servers to integrate-test against (Этап 1):**
   - `server-filesystem` (easy, no auth, already a reference)
   - `mcp-server-git` (Python, same SDK, good smoke test)
   - `github/github-mcp-server` (proves token-auth path works)
5. **Server exposure choices (Этап 2):** use `FastMCP` to get stdio
   server up fast; add Streamable HTTP for hosted/remote scenarios
   (matches how our existing MCP servers ship — `/sse` + `/mcp`).
6. **No need to write our own reference protocol code.** SDK
   handles handshake, negotiation, serialization. Our code is the
   glue: credential storage, manifest wiring, PluginContext
   integration, audit log.

---

## 8. Open questions (move to design doc)

- How do we store per-agent MCP credentials — reuse the existing
  keyring pattern from DB connections, or a separate keyspace?
- Do MCP tool calls count against the same audit log as SQL queries,
  or a separate one? (Likely: same; it's all "agent actions.")
- Do we expose dialekt's own DB connections through our MCP server,
  or only the higher-level "run this agent" / "search schema" tools?
  (Lean: higher-level only, raw DB access stays local.)
- Rate-limiting: per-agent, per-MCP-server, both? Answer in design.

These are taken up in `M2_MCP_DESIGN.md`.
