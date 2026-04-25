# v0.25 — MCP Audit Dashboard (Design Doc)

**Status:** v3 — APPROVED by mentor (pass 3) on 2026-04-25. Pass 1 caught
phantom consent_id work + dishonest auth + missing null-row rule. Pass 2
caught fabricated `mcp_consent_decision.result=timed_out` + missing
`mcp_tool_call.result=server_unavailable` + phantom `⊕ approved_all`
legend entry. Pass 3 confirmed all corrections grounded in code.

## Goal

Surface the MCP rows already present in `audit_log` to pilots in **Settings → Admin → Usage → MCP** so a regulated KZ buyer can answer: *"show me what your AI did on my data."*

Pre-pilot demo asset. Reuses existing data. No new data model.

## What's already in the DB

`audit_log` schema (server.py:503):

```
id, ts, agent_id, binding_id, kind, target, action, result,
duration_ms, error_kind, extra_json
```

Four MCP `kind` values are emitted today:

| kind                       | emitted from              | target          | action       | result                                                 |
|----------------------------|---------------------------|-----------------|--------------|--------------------------------------------------------|
| `mcp_consent_requested`    | runtime.py:310            | `<server_name>` | `<tool>`     | `asked`                                                |
| `mcp_consent_decision`     | runtime.py:328            | `<server_name>` | `<tool>`     | `approved` / `approved_session` / `denied` (the `ConsentDecision` enum has exactly these three; consent timeouts resolve as `denied` per server.py and emit a separate `mcp_consent_timeout` WS frame, not a new audit `result` value) |
| `mcp_tool_call`            | manager.py:191, 222       | `<server_name>` | `<tool>`     | `success` / `error` / `rate_limited` / `timeout` / `server_unavailable` |
| `mcp_tool_blocked`         | runtime.py:245            | `<server_name>` | `<tool>`     | `blocked`                                              |

**`consent_id` already wired** (runtime.py:265-284): `_ask_and_audit` returns the INT primary key of the `mcp_consent_decision` row it just inserted, and the runtime threads it into the subsequent `mcp_tool_call.extra` as `consent_id`. Covered by the `test_mcp_runtime` and `test_mcp_e2e_filesystem` suites (line numbers omitted to survive future refactors). **Zero backend changes needed for grouping** — the join key already exists in production data since v0.20.0.

## Backend — GET endpoint

Single read-only endpoint, served from `python/server.py`:

```
GET /audit/log?kind=mcp_*&since=<iso8601>&limit=<int>
```

**Filters (all optional, AND-composed):**
- `kind` — exact match OR `mcp_*` glob (the dashboard only uses `mcp_*`)
- `since` — ISO-8601, default = `now - 7d`. Server caps at `now - 30d` to keep the query fast on the existing `idx_audit_log_ts`.
- `limit` — default `100`, max `500`. No pagination cursor in v0.25 — just "show more" by widening `since`.

**Response shape:** flat list of rows, newest first. `extra` is the parsed JSON object (not a string).

```json
{
  "rows": [
    {
      "id": 1234,
      "ts": "2026-04-25T10:42:18Z",
      "agent_id": "ag_abc",
      "kind": "mcp_consent_decision",
      "target": "github",
      "action": "create_issue",
      "result": "approved",
      "duration_ms": 1840,
      "error_kind": null,
      "extra": { "destructive": true, "destructive_source": "annotation" }
    },
    {
      "id": 1235,
      "ts": "2026-04-25T10:42:20Z",
      "agent_id": "ag_abc",
      "kind": "mcp_tool_call",
      "target": "github",
      "action": "create_issue",
      "result": "success",
      "duration_ms": 1840,
      "error_kind": null,
      "extra": { "consent_id": 1234 }
    }
  ],
  "truncated": false
}
```

**Auth:** **none**. The existing `POST /audit/log` (server.py:970-1007) is unauthenticated; v0.25 read-side matches that. Acceptable because the desktop is single-user and binds to localhost. **Cloud / multi-user requires auth on both ends — tracked as new B7 entry in `M2_POST_RC_BACKLOG.md`** (added in this PR).

**Indexes:** the existing `idx_audit_log_kind` + `idx_audit_log_ts` cover the query. No schema migration.

## Frontend — Settings → Admin → Usage → MCP tab

Pre-named slot per `M2_POST_RC_BACKLOG.md` B6.

**Layout:** single-column list view, monospace, brutalist (matches the rest of Settings). One row per `audit_log` row, newest at top.

**Row template (collapsed):**

```
10:42:20  github · create_issue          ✓ success         1.8s
10:42:18  github · create_issue   [!]    ✓ approved        1.8s
10:42:15  github · create_issue          ? asked
10:42:09  filesystem · read_file         ✓ success         12ms
10:41:55  github · delete_repository [!] ⊘ blocked          —
```

**Result-glyph map** (rendered in a small legend strip at the top of the tab so demo viewers don't have to guess):

| glyph | meaning                          |
|-------|----------------------------------|
| `?`   | asked (consent prompted)         |
| `✓`   | approved / success               |
| `△`   | approved_session                 |
| `⊘`   | blocked / denied                 |
| `✗`   | error / server_unavailable (both surface to the LLM as a failed call — collapsed onto one glyph; the `error_kind` column in the expanded row distinguishes transport-level vs tool-level failure) |
| `⏱`   | rate_limited / timeout           |
| `[!]` | destructive badge (when `extra.destructive === true`) |

`approved_all` is a WS-bridge wire shorthand only — it resolves to
`APPROVED` for the head request before any audit row is written, so it
never appears as a `mcp_consent_decision.result` value and gets no glyph.

**Row expand (inline, click anywhere on the row):** renders the parsed `extra_json` in a monospace block + the linked `agent_id` (clickable to Settings → Agents detail if present). Inline expand matches the existing MCP Servers row pattern in SettingsScreen.jsx — no new container component cost.

**Filter strip (top of tab):**
- Time range pills: `24h` / `7d` / `30d` (no custom picker)
- Kind dropdown: `All MCP events` / `Consent only` / `Tool calls only` / `Blocked only`
- Static legend strip: shows the 8 glyphs with one-word meanings

**Empty state:** `No MCP activity in the selected window.` plus a link to Settings → MCP Servers.

**Truncation banner:** if response `truncated=true`, render a single line — `Showing newest 500 of N rows in this window — narrow time range to see more.` (No promise of CSV/JSON export.)

**No charts. No CSV. No live tail. No search.** Per mentor P0.

## Row-grouping rule (uses existing `consent_id`)

Frontend join — pure JS, no backend support beyond the already-emitted field:

```
For each row r where r.kind === "mcp_consent_decision":
    GROUP r with all rows q where q.extra?.consent_id === r.id
For rows with no consent_id (auto-approved non-destructive calls,
    or autonomy-bypassed): render STANDALONE — no group affordance.
```

Auto-approved non-destructive `mcp_tool_call` rows are the **majority case** in normal pilot use (filesystem reads, no consent prompt). They render as plain rows. The grouping only collapses around explicit consent decisions.

## Non-goals (explicit)

Per mentor P0 ruling — anything in this list waits for v0.26+:

- ❌ CSV/JSON export
- ❌ Charts (sparklines, histograms, latency p50/p95)
- ❌ Live tail / WebSocket push
- ❌ Custom time-range picker (only 24h/7d/30d)
- ❌ Search box
- ❌ Free-text filter on `extra_json`
- ❌ Per-tenant scoping (single-tenant desktop today)
- ❌ Row-level redaction of `arguments` (B5 backlog)
- ❌ Tying to consent UI replay ("re-prompt with these args")
- ❌ Auth on the read endpoint (B7 backlog — required before cloud / multi-user)

## LOC budget

**Re-floored after removing phantom consent_id work** — that's already shipped in v0.20.0. Total target **280-330 LOC including tests**, two commits (not three).

| Slice                              | LOC   |
|------------------------------------|-------|
| Backend GET endpoint               | ~50   |
| Backend pytest (integration)       | ~80   |
| Frontend tab + row component       | ~180  |
| Glyph legend strip                 | ~12   |
| **Subtotal**                       | ~322  |
| Frontend tests                     | deferred — see F4 in M2_POST_RC_BACKLOG; project baseline ships FE untested |

**Mid-brake at 220 LOC frontend:** if frontend exceeds 220 LOC, **stop**, drop the kind dropdown, ship 24h-only, **re-invoke mentor before continuing** (per discipline §2 — does not unilaterally proceed).

## Commit ordering (two, not three)

1. **Backend GET endpoint + pytest** — ≤180 LOC. Adds `GET /audit/log`, kind/since/limit filters, response shape, 30-day cap, JSON-parses `extra_json`, returns `truncated` flag. Tests cover: filter combinations, cap behaviour, the truncated boundary, malformed `extra_json` rows (treat as `null`).
2. **Frontend tab + row component + B7 backlog entry** — ≤220 LOC frontend. Adds Settings → Admin → Usage → MCP tab, row template + glyph legend + filter strip + inline expand + empty state + truncation banner + grouping JS. Updates `M2_POST_RC_BACKLOG.md` to add B7 (auth on audit endpoints before cloud).

## Open questions for mentor's second pass — RESOLVED

All 5 from doc v1 ruled by mentor in pass 1:

1. ~~consent_id wiring~~ — **Already wired (INT row id). Doc rewritten.**
2. ~~Auth on GET~~ — **None for v0.25 single-user localhost. B7 added.**
3. ~~Commit ordering~~ — **Two commits, not three. Order: backend → frontend.**
4. ~~Expand-row UX~~ — **Inline.**
5. ~~Result glyphs~~ — **Unicode set above + legend strip.**

## Risks I am pre-binding myself against

Per mentor P0 ruling pass 1:
- No filters/charts/CSV/exports beyond the listed strip
- No backend retry/restart code in this release — pure read surface
- No refactoring of MCPClientManager / ConsentRequest beyond what's already shipped
- No new schema migration — `consent_id` already lives in `extra_json`
- No stub auth — match the existing endpoint's posture, document the gap

## Next step after mentor APPROVE

Commit 1: backend GET endpoint + pytest. ≤180 LOC.

If mid-brake fires on commit 2, stop and re-invoke mentor.
