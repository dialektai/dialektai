# v0.22.0 — Per-tool allow_tools / deny_tools

**Branch:** `feat/mcp-per-tool-scoping` off `3f1c089` (v0.21.0 merge)
**Status:** draft, awaiting mentor review
**Why this exists:** v0.21 ships server-level selection ("agent X can call any tool from server Y"). Schema 1.1.0 supports per-tool scoping (`mcp_servers[].allow_tools` / `deny_tools`) but neither the UI nor the runtime enforces it. Enterprise pilots ("junior analyst can READ from GitHub but not CREATE issues") cannot self-serve without YAML hand-edits. v0.22 closes both gaps.

---

## 1. Schema confirmation

`MCPServerSpec` in `dialekt-manifest-validator/src/dialekt_manifest/schema.py:438-439`:

```py
allow_tools: Optional[list[str]] = None
deny_tools: list[str] = Field(default_factory=list)
```

Semantics:
- `allow_tools = None` → all tools advertised by the server are allowed
- `allow_tools = [...]` → ONLY those tools allowed; everything else denied
- `deny_tools = []` → no extra blacklist
- `deny_tools = [...]` → these names are denied even if `allow_tools` permits

Both can coexist: `deny` always subtracts from `allow`.

**No schema change required.** Validator already accepts both fields; manifests with them parse cleanly today.

## 2. Runtime enforcement (currently missing)

`dialekt.mcp.runtime.MCPRuntime.invoke_tool()` does not consult these fields. Confirmed by `grep -n "allow_tools\|deny_tools" python/dialekt/mcp/*.py` → zero matches.

### Design

Add an optional `tool_policies: dict[str, ToolPolicy]` to `MCPRuntime.__init__`, where:

```py
@dataclass(frozen=True)
class ToolPolicy:
    allow: Optional[frozenset[str]] = None  # None = all allowed
    deny: frozenset[str] = frozenset()
```

`MCPRuntime.invoke_tool(server_name, tool_name, ...)` gains an early check:

```py
policy = self._tool_policies.get(server_name)
if policy is not None:
    if tool_name in policy.deny:
        raise MCPToolNotAllowed(...)  # new error class
    if policy.allow is not None and tool_name not in policy.allow:
        raise MCPToolNotAllowed(...)
```

`MCPToolNotAllowed` extends `MCPError` (new class in `dialekt/mcp/errors.py`). Audit-log row of kind `mcp_tool_blocked` emitted when policy denies.

ws_chat's `_build_session_mcp_runtime` reads the manifest's per-server `allow_tools`/`deny_tools` and passes the policy dict to `MCPRuntime`.

## 3. Backend — new `/mcp-servers/{id}/tools` endpoint

Why: Wizard step 5 needs to render a tool checklist when a server is selected. Currently `/mcp-servers/{id}/test` returns only `tool_count`, not names.

### Design

```
GET /mcp-servers/{id}/tools
→ 200 OK
{
  "tools": [
    {"name": "search_repositories", "destructive": false, "description": "..."},
    {"name": "create_issue",        "destructive": true,  "description": "..."},
    ...
  ],
  "fetched_at": "2026-04-25T...",
  "from_cache": true
}
```

Implementation:
- Look up server config + resolve secrets (same as `/test`)
- Cache result for 60 seconds keyed on `(server_name, config_hash)` where `config_hash` = SHA-256 of (command_json + env_refs_json + cwd + url + auth_type + auth_ref). Editing config busts the cache.
- Cache miss → spawn `MCPClient` briefly, `list_tools()`, project to the array shape above
- `destructive` field uses `dialekt.mcp.consent.is_destructive_tool()` — same heuristic the consent runtime uses
- Failure (server unreachable, bad credentials) → 200 with `{"error": "...", "tools": []}` to mirror `/test` UX. Frontend renders an inline error in the expander, not a global toast.

Tests in `python/tests/test_mcp_servers_tools.py`:
- happy path against npx fs MCP (auto-skip if no Node)
- unreachable server returns error + empty tools
- cache hits within 60s window (assert `from_cache: true`)
- cache busts on config edit

## 4. Wizard step 5 (MCP Tools) — per-server tool checklist

### Current shape (v0.21)

User picks servers via tile-list checkboxes. Manifest emits `mcp_servers[]` with no `allow_tools`/`deny_tools`. Effectively "all-tools mode".

### v0.22 expansion

When user checks a server tile, an **inline expander** opens beneath it:

```
[✓] github                  ● 26 tools                    [▾ tools]
    │
    └── ┌─ Tools (26) ────────────────────────────────────────┐
        │  Mode: ( • ) All tools  ( ) Pick specific  ( ) Block some │
        │                                                          │
        │  (when "Pick specific")                                  │
        │  [✓] search_repositories          read                   │
        │  [✓] get_file_contents            read                   │
        │  [ ] create_issue                  ⚠ destructive          │
        │  [ ] create_pull_request           ⚠ destructive          │
        │  ...                                                     │
        └──────────────────────────────────────────────────────────┘
```

Three modes:
- **All tools** (default) — emits no `allow_tools` / `deny_tools` in manifest
- **Pick specific** — checklist; manifest emits `allow_tools: [<checked names>]`
- **Block some** — checklist; manifest emits `deny_tools: [<checked names>]`

Mode toggle is per-server, stored on `data.mcp_server_scopes: dict[str, ToolScope]` where `ToolScope = {mode: "all" | "allow" | "deny", tools: string[]}`.

### Manifest emission

In `buildManifestYaml`:

```js
mcpServers.forEach(s => {
  const scope = data.mcp_server_scopes?.[s.name] || { mode: 'all' };
  const entry = { name: s.name, transport: s.transport, /* ...existing fields... */ };
  if (scope.mode === 'allow' && scope.tools.length > 0) {
    entry.allow_tools = scope.tools;
  } else if (scope.mode === 'deny' && scope.tools.length > 0) {
    entry.deny_tools = scope.tools;
  }
  // mode === 'all' → omit both fields → "all tools allowed"
  yaml += emitMcpServer(entry);
});
```

### Tool list source

Each server tile's expander fetches `GET /mcp-servers/{id}/tools` on first open (lazy), shows skeleton rows while loading. Cached via the backend's 60s window so re-opening is instant.

If the fetch returns `{error}`: expander shows `⚠ Couldn't list tools: <error>. Defaulting to "All tools" mode.` and disables the radio toggle.

## 5. Settings → MCP Servers — tool inspector (read-only)

### Why read-only

Allow/deny is **per-agent**, not per-server. A pilot might want one agent with `allow: [search_*]` and another with no scoping pointing at the same `github` server. Settings is server-level config; tool scoping is agent-level. Putting allow/deny editing here would conflate the two.

What lands instead: each server card gains an `[Inspect tools ▾]` expander showing the same tool list (name, destructive flag, description) — admins can audit what each server exposes without spawning the wizard.

Same `/mcp-servers/{id}/tools` endpoint, same 60s cache.

## 6. Frontend file changes

| File | Delta | What |
|---|---|---|
| `frontend/src/screens/AgentWizardScreen.jsx` | +120 | `mcp_server_scopes` state; `StepMcpServers` expander with mode radio + tool checklist; `buildManifestYaml` emission for `allow_tools` / `deny_tools` |
| `frontend/src/screens/SettingsScreen.jsx` | +80 | Per-server `[Inspect tools ▾]` expander on the row card with skeleton + error states |
| `frontend/src/components/McpToolList.jsx` (new) | +90 | Shared tool-list rendering: name + destructive pill + description tooltip + optional checkbox in checklist mode |

Total frontend: ~290 lines.

## 7. Backend file changes

| File | Delta | What |
|---|---|---|
| `python/dialekt/mcp/errors.py` | +6 | New `MCPToolNotAllowed(MCPError)` exception |
| `python/dialekt/mcp/runtime.py` | +30 | `tool_policies` constructor arg; `invoke_tool` early-policy-check; emits `mcp_tool_blocked` audit row on deny |
| `python/server.py` | +110 | `/mcp-servers/{id}/tools` endpoint with 60s cache; `_build_session_mcp_runtime` parses manifest's per-server allow/deny → ToolPolicy dict |
| `python/dialekt/mcp_templates/catalog.json` | 0 | unchanged |

Total backend: ~146 lines.

## 8. Tests

New file `python/tests/test_mcp_tool_scoping.py` (~140 lines):

- `MCPRuntime` with `tool_policies={"github": ToolPolicy(allow={"search_*"})}` denies `create_issue` cleanly with `MCPToolNotAllowed` and emits `mcp_tool_blocked` audit row
- Same with `deny={"create_*"}` — read tools allowed, write denied
- Combined `allow + deny` — deny subtracts from allow
- `mode=all` (no policy) — all tools allowed (regression test)
- ws_chat e2e: agent manifest with `allow_tools: ["search_repositories"]` → `ctx.mcp.github.create_issue(...)` raises `MCPToolNotAllowed` from inside OI thread (cross-thread regression)

New file `python/tests/test_mcp_servers_tools.py` (~100 lines):

- `GET /mcp-servers/{id}/tools` returns shape with `name`/`destructive`/`description` for each tool
- 60s cache hit returns `from_cache: true`
- Edit server config → cache busted, `from_cache: false` on next fetch
- Unreachable server returns 200 with `{error, tools: []}`

Total tests: ~240 lines.

## 9. Commit plan

| # | Title | Frontend / Backend | Estimated lines |
|---|---|---|---|
| 1 | `feat(mcp/runtime): per-tool allow/deny enforcement + MCPToolNotAllowed` | backend | ~80 (runtime + errors + 60-line test) |
| 2 | `feat(server): GET /mcp-servers/{id}/tools endpoint` | backend | ~120 (endpoint + 100-line test) |
| 3 | `feat(server): wire ToolPolicy from manifest into ws_chat runtime` | backend | ~40 (parse + ws_chat hook + e2e test) |
| 4 | `feat(frontend/wizard): per-server tool checklist with allow/deny modes` | frontend | ~150 |
| 5 | `feat(frontend/settings): tool inspector expander on server cards` | frontend | ~100 |
| 6 | (chore) any hygiene that pops out | — | ~20 |

Hard ceiling per commit: 250 lines. Mid-implementation brake at 220 (per the v0.21 discipline that worked).

Total ~530 lines + 240 tests = ~770 lines for v0.22.

## 10. Open questions for mentor

1. **`ToolPolicy` dataclass location** — `dialekt/mcp/runtime.py` (where it's used) or `dialekt/mcp/consent.py` (alongside `ConsentDecision`)? My lean: runtime — it's a runtime-side concept, not a consent-policy concept.

2. **`MCPToolNotAllowed` audit kind** — `mcp_tool_blocked` (clear) or `mcp_tool_call_denied` (parallel to `mcp_consent_decision`)? My lean: `mcp_tool_blocked` — it's a policy block, not a user-decision denial.

3. **Tools endpoint cache key** — `(server_name, config_hash)` mirrors v0.21 plan §3.2 wizard preview cache. OK to share the same in-memory cache across both endpoints (`/test` and `/tools`)? My lean: share — same lifetime, same invalidation rules, single source of truth.

4. **Wizard mode default** — when user FIRST checks a server, does it default to "All tools" or open the picker? My lean: "All tools" (zero friction; advanced users toggle to picker). Mentor design ruling §7.5 set the precedent that the curated path is for the 90% case.

5. **Tool inspector in Settings — destructive-tool warning?** When admin opens the inspector and sees N destructive tools, do we add a banner "This server has N destructive tools that will require consent at runtime"? My lean: yes — admins choosing whether to expose this server to junior agents need that signal upfront.

## 11. Out of scope for v0.22 (deferred)

Per the v0.22 ship-window:
- "Approve all pending" multi-tool bursts (separate UX problem)
- Argument redaction in consent modal (waits on MCP tool annotations support)
- Custom HTTP headers (separate transport-spec extension; mentor design review needed)
- macOS/Windows release artifact verification (lands in v0.23 cross-platform pass)

## 12. Change log

- `2026-04-25 v1` — initial plan post-v0.21 ship.
