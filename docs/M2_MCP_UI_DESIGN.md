# M2 Этап 2.5 — Frontend MCP UI Design

**Status:** draft, awaiting mentor review
**Author:** Claude Code (acting on mission from Dias, 2026-04-24)
**Scope:** UI surface that turns dialekt's already-shipped MCP client
(`dialekt.mcp.*`, shipped in v0.11.x Этап 1) into something a
non-technical pilot can drive without editing YAML.
**Related:**
- `docs/M2_MCP_DESIGN.md` — Этап 1 architecture (manager, transports, consent)
- `docs/M2_MCP_SERVER_DESIGN.md` — Этап 2 (dialekt-as-MCP-server)
- `docs/MCP_CLIENT_USAGE.md` — how manager/runtime are used today
- Existing patterns in `frontend/src/screens/SettingsScreen.jsx` and
  `frontend/src/screens/AgentWizardScreen.jsx`

---

## 0. Scope findings up front (read before the rest)

Two facts the mission doc assumed but the code on `feat/m2-mcp-server`
contradicts. The design below assumes these get resolved **before or
during** Этап 2.5 implementation.

### 0.1 WS consent bridge is NOT wired in ws_chat

The mission brief says

> Backend (python/server.py WS handler) already emits
> `mcp_consent_request` messages from Этап 1 Commit 9.

Current state on `feat/m2-mcp-server + main`:

- `python/dialekt/mcp/consent.py` documents the protocol in docstrings
  (`mcp_consent_request` / `mcp_consent_response`) but is transport-agnostic.
- `python/dialekt/mcp/runtime.py` emits **audit-log rows** of kind
  `mcp_consent_requested` / `mcp_consent_decision`, not WebSocket frames.
- `python/server.py` `ws_chat` does not construct an `MCPClientManager`,
  does not pass a `PromptConsentProvider` with a prompt function that
  talks over the WS, and does not listen for `mcp_consent_response` frames.

**Implication:** the consent modal (Step 1.5) is not a pure frontend
task. It needs a backend bridge: given an active WS session, wrap
`PromptConsentProvider` with a prompt function that sends JSON over
that WS and awaits the matching response. That work belongs to this
phase — defer to mentor for explicit scope ruling.

### 0.2 Wizard step numbers in the mission do not match code

Mission says "insert between Capabilities (step 6) and Review (step 9)".
Actual `STEPS` in `AgentWizardScreen.jsx` (9 steps, 0..8):

| # | Label         | Relevant to MCP? |
|---|---------------|------------------|
| 0 | Identity      | —                |
| 1 | Model         | —                |
| 2 | System Prompt | —                |
| 3 | Capabilities  | adds `mcp_tools` |
| 4 | Connections   | —                |
| 5 | Variables     | —                |
| 6 | Autonomy      | consent policy   |
| 7 | Trigger       | —                |
| 8 | Publish       | —                |

There is no "Review" step. This doc anchors the new MCP step
**between Capabilities (3) and Connections (4)** because:

- Conceptually MCP is "external tools", same family as Connections
  (databases), and both answer the question "what can this agent talk to?"
- `capabilities.groups` drives visibility of `Connections` today
  (requires `sql`); MCP will drive the equivalent for `mcp_tools`.
- Placing it after Autonomy would be wrong — autonomy describes the
  consent policy for the tools selected earlier.

Also: current wizard emits `spec_version: "1.0.1"`. To carry an
`mcp_servers:` block it must emit `"1.1.0"` (per dialekt-manifest
schema 1.1.0). Bump the `buildManifestYaml` template when the new
step is wired.

---

## 1. Settings → MCP Servers page

### 1.1 Navigation

`SettingsScreen.jsx` uses a sidebar + body shell. New entry in the
Capabilities section of the left nav, sitting next to "Database
Connections" so tenants find external tools in one place:

```
CAPABILITIES
  └─ Connections          (existing — databases)
  └─ MCP Servers          (new — external MCP tools)
  └─ Permissions          (existing)
```

Crumb label (same convention as `02 / CAPABILITIES → CONNECTIONS`):
`02 / CAPABILITIES → MCP SERVERS`.

### 1.2 Page layout

```
┌──────────────────────────────────────────────────────────────┐
│ 02 / CAPABILITIES → MCP SERVERS                              │
│                                                              │
│ MCP Servers                                                  │
│ External tool servers that agents can call. Credentials are  │
│ stored in your OS keychain — never in config files.          │
│                                                              │
│                                             [+ Add server]   │
│                                                              │
│ ╔════════════════════════════════════════════════════╗       │
│ ║ github                                    ● ready ║       │
│ ║ stdio · npx @modelcontextprotocol/server-github    ║       │
│ ║ 12 tools discovered                                ║       │
│ ║                              [Test]  [Edit]  [⋯]   ║       │
│ ╚════════════════════════════════════════════════════╝       │
│                                                              │
│ ╔════════════════════════════════════════════════════╗       │
│ ║ slack                                     ● error ║       │
│ ║ http · https://slack.example/mcp                   ║       │
│ ║ Auth failed · last tested 2 min ago                ║       │
│ ║                              [Test]  [Edit]  [⋯]   ║       │
│ ╚════════════════════════════════════════════════════╝       │
│                                                              │
│ ╔════════════════════════════════════════════════════╗       │
│ ║ filesystem                              ○ untested║       │
│ ║ stdio · npx @modelcontextprotocol/server-filesys…  ║       │
│ ║ Not yet tested                                     ║       │
│ ║                              [Test]  [Edit]  [⋯]   ║       │
│ ╚════════════════════════════════════════════════════╝       │
└──────────────────────────────────────────────────────────────┘
```

Status dot colours match existing `T.ok` / `T.warn` / `T.dim`.
Three states: `ready` (tested, healthy), `error` (last test failed),
`untested` (never tested or config changed since last test).

Empty state (no servers): `"No MCP servers yet. Add one to expose
external tools to your agents."` with a centered `[+ Add server]` CTA.

### 1.3 Card affordances

- **Name** — kebab-case, unique within tenant.
- **Transport summary line** — `stdio · <argv[0]> <argv[1]>` or
  `http · <url host>` (no credentials).
- **Status line** — `N tools discovered` / `Auth failed · last tested …` /
  `Not yet tested`.
- **Buttons**
  - `[Test]` — spawn briefly, list_tools, show result inline. The
    result (success toast or error text) persists until the user
    takes another action (edit, retest, navigate away) — a 3-second
    auto-dismiss would be too short to read a multi-line stderr.
  - `[Edit]` — opens the Add/Edit modal pre-filled.
  - `[⋯]` — menu with `Delete` only (confirmation dialog). No
    YAML-export affordance — users who want YAML go through the
    agent-wizard publish step.

Order: most-recently-used first, then alphabetical.

---

## 2. Add / Edit MCP Server modal

### 2.1 Layout

```
┌──────────────────────────────────────────────────────┐
│ Add MCP Server                               [×]     │
├──────────────────────────────────────────────────────┤
│                                                      │
│ Name *                                               │
│ ┌────────────────────────────────────────────────┐   │
│ │ github                                         │   │
│ └────────────────────────────────────────────────┘   │
│ kebab-case, must be unique                           │
│                                                      │
│ Transport *                                          │
│ ( • ) stdio   spawn a local subprocess               │
│ (   ) http    connect to a remote Streamable HTTP    │
│                                                      │
│ ── stdio ────────────────────────────────────────    │
│                                                      │
│ Command *        (argv list, one per line)           │
│ ┌────────────────────────────────────────────────┐   │
│ │ npx                                            │   │
│ │ -y                                             │   │
│ │ @modelcontextprotocol/server-github            │   │
│ └────────────────────────────────────────────────┘   │
│                                                      │
│ Environment variables                                │
│ ┌────────────────────────────────┬─────────────┐     │
│ │ GITHUB_TOKEN                   │ ••••••••••  │ [−] │
│ ├────────────────────────────────┼─────────────┤     │
│ │ + add variable                                     │
│ └────────────────────────────────────────────────┘   │
│                                                      │
│ Working directory     (optional)                     │
│ ┌────────────────────────────────────────────────┐   │
│ │                                                │   │
│ └────────────────────────────────────────────────┘   │
│                                                      │
│ Timeout     [ 30 ] seconds                           │
│                                                      │
│           [Cancel]        [Test & Save]              │
└──────────────────────────────────────────────────────┘
```

For HTTP transport, the form swaps the stdio fieldset for a URL
input and an optional **Bearer token** field (masked) that maps
directly to `HttpTransportSpec.auth = {type: "bearer", token: …}` per
Этап 1 Decision 3. No custom-headers grid — `HttpTransportSpec` does
not accept arbitrary headers in v0.20.0; servers requiring custom
headers are deferred (see §10). The token is stored in the keychain
and referenced from the manifest via the standard `${secrets.<name>}`
interpolation (§3.3), never inlined.

### 2.2 Field validation

| Field              | Rule                                                                 |
|--------------------|----------------------------------------------------------------------|
| name               | required, kebab-case regex `^[a-z][a-z0-9-]*$`, unique per tenant    |
| transport          | required, one of `stdio` / `http`                                    |
| command (stdio)    | required, ≥1 non-empty line, never includes shell metacharacters     |
| env values (stdio) | masked on display; stored in OS keychain, not SQLite                 |
| cwd (stdio)        | optional absolute path; existence check on save, not on type         |
| url (http)         | required, RFC 3986 absolute URL, `https://` recommended (warn on http) |
| bearer token (http)| optional; stored masked in keychain; maps to `auth.token`            |
| timeout            | 5..300 seconds, default 30                                           |

`cwd` for stdio is collapsed behind an **Advanced** disclosure — 95%
of pilot MCP servers don't need it, and the concept is opaque to
non-technical users. Timeout default (30s) is surfaced at top level
for the edge case of slow-starting servers.

Command is taken as a list of strings on purpose — no shell string —
same reason `dialekt.mcp.transport.StdioTransportSpec` enforces
`list[str]` (shell-interpolation safety, Этап 1 Decision 5).

### 2.3 Credential handling

- Env values and HTTP auth never round-trip through the UI once saved:
  the form shows `••••••••` plus an explicit `[Change]` button per
  credential, matching how the Database Connections form already works.
- On `Test & Save`, the backend:
  1. Writes the non-secret part of the spec to SQLite (`mcp_servers` table).
  2. Writes each secret to the OS keychain under
     `dialekt:mcp:<server_id>:<env_name>`.
  3. Runs a transient test (Step 1.2 endpoint below) and returns
     `{success, tool_count, error?}`. On failure the save still succeeds
     but the card shows `error` status — the user sees the failure
     without losing their input.
- On `Edit`, secrets missing from the payload mean "unchanged" (do not
  clear keychain). This matches the existing connection-editing flow.

---

## 3. Builder Wizard — new step: "External Tools (MCP)"

### 3.1 Placement and naming

Inserted between `Capabilities` (step 3) and `Connections` (step 4).
The STEPS array grows to 10 entries:

```js
const STEPS = [
  { label: 'Identity',      icon: 'diamond'  },
  { label: 'Model',         icon: 'sparkle'  },
  { label: 'System Prompt', icon: 'chat'     },
  { label: 'Capabilities',  icon: 'shield'   },
  { label: 'MCP Tools',     icon: 'plug'     }, // NEW
  { label: 'Connections',   icon: 'folder'   },
  { label: 'Variables',     icon: 'terminal' },
  { label: 'Autonomy',      icon: 'cog'      },
  { label: 'Trigger',       icon: 'screen'   },
  { label: 'Publish',       icon: 'diamond'  },
];
```

Short label `MCP Tools` (the word "external" is implicit — dialekt's
own tools are never listed here).

### 3.2 Step body

```
┌──────────────────────────────────────────────────────────────┐
│ MCP Tools                                                    │
│ Let this agent call tools from external MCP servers you've   │
│ already configured in Settings.                              │
│                                                              │
│ ⚠ Agents using MCP need the `mcp_tools` capability. We'll    │
│   add it for you if you select any server here.              │
│                                                              │
│ ── Servers configured in Settings ────────────────────────── │
│                                                              │
│ [✓] github              ● ready       12 tools · [Preview ▾] │
│ [ ] slack               ● error       Auth failed            │
│ [ ] filesystem          ○ untested    [Test first ▸]         │
│                                                              │
│ No servers configured? [Open Settings → MCP Servers]         │
│                                                              │
│ ── Tool preview (github) ─────────────────────────────────── │
│ • list_repositories        read                              │
│ • search_issues            read                              │
│ • create_issue             write (consent required)          │
│ • update_pull_request      write (consent required)          │
│ …                                                            │
└──────────────────────────────────────────────────────────────┘
```

Selection rules:
- Checkboxes are enabled only for servers whose last test was `ready`.
  `error` shows a read-only badge with `[Test again]` button.
  `untested` shows `[Test first]` which runs the test inline.
- `Preview ▾` expands the tool list with destructiveness badges
  (`read` / `write (consent required)`) — same destructiveness rule
  as `dialekt.mcp.consent.is_destructive_tool`.
- The preview list is read-only in v0.20.0: selecting a server grants
  this agent access to **all** tools that server advertises. Per-tool
  allow/deny scoping (`mcp_servers[].allow_tools` / `deny_tools` in
  schema 1.1.0) is deferred — see §10.
- Tool preview is fetched on first expansion and cached for 60s
  keyed on `(server_name, config_hash)` where `config_hash` is a
  SHA-256 of the non-secret spec fields. Editing the server config
  in Settings changes the hash and busts the cache automatically;
  manual `[Test]` also refreshes.
- `[Skip this step]` button at the bottom — does nothing, advances
  to the next step. Manifest ends up with no `mcp_servers:` block,
  which the validator accepts.

### 3.3 Effect on the generated manifest

When the step saves, two things happen:

1. `mcp_servers:` block populated from the selection. The manifest
   DOES inline the transport spec (command/URL) because the manifest
   is the portable unit — a future share/import should reproduce the
   same server config on another machine. What is NEVER inlined:
   credentials. Secrets are referenced via the standard
   `${secrets.<name>}` interpolation that `dialekt.mcp.secrets_resolver`
   already understands (Этап 1 Decision 3). The keychain namespacing
   (`dialekt:mcp:<server_name>:<ref>`) is composed by the backend
   from the entry's `name:` field — manifest authors never type
   compound paths. Example:
   ```yaml
   mcp_servers:
     - name: github
       transport: stdio
       command:
         - npx
         - -y
         - "@modelcontextprotocol/server-github"
       env:
         GITHUB_TOKEN: "${secrets.github_token}"
       timeout_seconds: 30
   ```
   The wizard writes `${secrets.<name>}` by copying the user-chosen
   credential name from the Settings form. No new resolver path is
   invented for the UI.

2. If the `mcp_tools` capability is not already in `capabilities.groups`,
   it is added silently when the user selects any server, and a
   passive note appears at the top of the step:
   ```
   [i] This agent will include the 'mcp_tools' capability automatically.
   ```
   No confirmation flow — the user already passed through the
   Capabilities step; confronting them again here is wrong UX. This
   mirrors how the `Connections` step silently emits the `connections`
   block without re-asking. If the user deselects all MCP servers,
   the silently-added capability is removed with the last server.

### 3.4 spec_version bump

`buildManifestYaml` currently emits:

```yaml
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"
```

When `mcp_servers:` is non-empty (or when the wizard runs on a
dialekt build that ships schema 1.1.0), the builder must emit:

```yaml
spec_version: "1.1.0"
minimum_dialekt_version: "0.20.0"
```

Back-compat: manifests written before this phase keep `spec_version:
"1.0.1"`; the validator in `dialekt-manifest-validator>=0.1.0`
accepts both.

---

## 4. Consent modal (chat overlay)

### 4.1 Layout

```
     ┌────────────────────────────────────────────────────┐
     │  🔐  Permission required                           │
     ├────────────────────────────────────────────────────┤
     │  Agent wants to call an MCP tool:                  │
     │                                                    │
     │  Server   github                                   │
     │  Tool     create_issue   ⚠ destructive             │
     │                                                    │
     │  Arguments                                         │
     │  ┌──────────────────────────────────────────────┐  │
     │  │ repo:   "dialektai/dialektai"                │  │
     │  │ title:  "Fix critical bug"                   │  │
     │  │ body:   "Reproducer: …"                      │  │
     │  └──────────────────────────────────────────────┘  │
     │                                                    │
     │  [ Deny (Esc) ]  [ Approve once (Enter) ]          │
     │                    [ Approve for this session ]    │
     └────────────────────────────────────────────────────┘
```

Mapping:
- `Approve once` → `ConsentDecision.APPROVED`
- `Approve for this session` → `ConsentDecision.APPROVED_SESSION`
  (scope: **this chat session only**, keyed on `(server, tool)` —
  same as `SessionCachingProvider`; reconnecting the WS clears it).
- `Deny` → `ConsentDecision.DENIED`

### 4.2 Positioning

Center overlay on top of the chat column with a semi-opaque scrim
(`rgba(0,0,0,0.6)`) behind. The chat column is visible but
non-interactive. Modal is non-dismissible by clicking the scrim —
the user must choose. This matches how autonomy=manual already
blocks code execution in the chat UI today.

Always centered — no bottom-sheet variant. At widths < 600px the
modal shrinks to `calc(100vw - 32px)` with internal vertical scroll
if the arguments block is tall. One layout path simplifies keyboard
focus contract and screen-reader testing; the narrow-window edge
case doesn't justify a second code path.

### 4.3 Keyboard

| Key          | Action                              |
|--------------|-------------------------------------|
| Enter        | Approve once                        |
| Shift+Enter  | Approve for this session            |
| Esc          | Deny                                |
| Tab / Shift+Tab | cycle through buttons            |

Focus moves to `Approve once` on open (the safer single-shot choice)
and returns to the chat input on close.

### 4.4 Timeout and stale requests

- No frontend timeout. Backend has its own (30s in the Этап 1 runtime;
  confirm during implementation). When the backend timeout fires it
  emits `mcp_consent_timeout` and the modal shows a dismissable error
  banner with `[OK]`.
- If the user disconnects while a request is pending, reconnection
  should not resurrect the modal — the backend returns `DENIED` on
  reconnect. Runtime already treats lost consent as denial.

### 4.5 Queuing

If the agent fires N tool calls in parallel (current manager supports
concurrent calls), requests stack in the modal with a header
`Request 1 of 3`. The user resolves one at a time; no "approve all"
shortcut in v0.20.0 — explicit consent is the whole point.

### 4.6 WebSocket protocol

Documented here so frontend and backend land on the same wire shape.
This is the piece flagged in §0.1 as not yet wired.

Backend → frontend:

```json
{
  "type": "mcp_consent_request",
  "request_id": "b4f3-…",
  "server_name": "github",
  "tool_name": "create_issue",
  "arguments": { "repo": "dialektai/dialektai", "title": "…", "body": "…" },
  "destructive": true,
  "destructive_source": "explicit"
}
```

Frontend → backend:

```json
{
  "type": "mcp_consent_response",
  "request_id": "b4f3-…",
  "decision": "approved" | "approved_session" | "denied"
}
```

Backend (timeout, connection drop):

```json
{ "type": "mcp_consent_timeout", "request_id": "b4f3-…" }
```

Any unknown `decision` value is coerced to `denied` on the backend
(defensive default — we bias toward safety).

The backend also validates `request_id` against the set of in-flight
requests for that session. Responses for unknown or already-resolved
IDs are dropped with a debug-log line. This prevents a replay, an
out-of-order response race, or a reconnect-then-stale-response from
accidentally approving a tool call.

---

## 5. Agent card MCP indicator

### 5.1 Current landscape

`frontend/src/components/LeftPanel.jsx` renders "My Agents" as a
collapsible list of rows, not cards. The indicator is a 10×10 SVG
plug icon appended next to the agent name when the agent's manifest
has a non-empty `mcp_servers:` block.

```
My Agents · 4
  ┌────────────────────────────────────┐
  │ ⬢  research-agent                  │
  │ ⬢  ops-agent           🔌          │   ← MCP indicator
  │ ⬢  github-ops          🔌          │
  │ ⬢  inbox-triage                    │
  └────────────────────────────────────┘
```

Hover tooltip: `Uses MCP: github, slack`. Click behavior deferred to
M2 Month 2 (expanded info panel).

### 5.2 Data source

`GET /agents` returns each agent's manifest metadata; add
`mcp_server_names: string[]` to the response so the frontend does
not re-parse YAML. The field is **derived** from the parsed manifest
already held in the in-memory agent cache — **no new SQLite column**,
no migration. If an agent's manifest has no `mcp_servers:` block,
the field is an empty list. Backend wiring: extend the existing
agent-serializer to project the names.

---

## 6. Error states (10 scenarios)

Mission asked for 8+; listing 10. Each has a copy template, an
actionable CTA where relevant, and the place it surfaces.

| # | Scenario                        | Surface                          | Copy                                                                 | CTA                       |
|---|----------------------------------|----------------------------------|----------------------------------------------------------------------|---------------------------|
| 1 | Server unreachable (stdio spawn fails) | Settings card status line   | `Failed to start server: <stderr first line>`                        | `[Retry]` `[Edit config]` |
| 2 | Server unreachable (http timeout)| Settings card status line        | `Connection timed out after 30s`                                     | `[Retry]` `[Edit URL]`    |
| 3 | Auth failed (401/403)            | Settings card + test result      | `Server rejected credentials (HTTP 401)`                             | `[Edit credentials]`      |
| 4 | Credentials missing from env     | Wizard MCP step + modal save     | `Missing env var: GITHUB_TOKEN. Set it in Settings → MCP Servers.`   | `[Open Settings]`         |
| 5 | Tool call timeout                | Chat message + audit log         | `Tool <server.tool> timed out after <N>s`                            | none (agent may retry)    |
| 6 | Rate limit hit                   | Chat message + audit log         | `Server responded: rate limit exceeded. Retry in <N>s.`              | none                      |
| 7 | Consent denied by user           | Chat message                     | `Permission denied for <server.tool>.`                               | none                      |
| 8 | Backend disconnected mid-consent | Modal → error banner             | `Connection lost. Decision discarded. Retry the last message.`       | `[Reconnect]`             |
| 9 | Invalid manifest config (schema) | Wizard + import flow             | `Invalid MCP server config: <validator error>`                       | `[Edit manifest]`         |
| 10| Duplicate server name (CRUD)     | Add/Edit modal                   | `A server named "<name>" already exists. Pick another.`              | focus-returns-to-name     |

All copy stays single-sentence; no stack traces in the UI. Full errors
go into audit_log (kind `mcp_error`) and to the backend log. This
matches the Этап 1 audit-log convention.

---

## 7. Accessibility (WCAG 2.1 AA)

Non-negotiable because pilots include corporate and government
buyers subject to KZ procurement accessibility requirements.

### 7.1 Keyboard

- All interactive elements reachable via Tab in visible order.
- `Esc` dismisses Add/Edit modal (consent modal is an exception —
  `Esc` = deny, not close).
- `Enter` submits forms; `Space` toggles checkboxes.
- Focus ring is a visible 2px `T.accent` outline, not just a colour
  shift — relied on by keyboard-only operators.

### 7.2 Screen reader

- Every icon-only button (⋯ menu, test button if iconified) has a
  `aria-label`.
- Consent modal uses `role="alertdialog"` with
  `aria-labelledby` pointing at the header and `aria-describedby`
  pointing at the arguments block so the tool call reads out
  verbally on open.
- Status dots have an associated `aria-label` (`ready`, `error`,
  `untested`) — colour is not the only signal.

### 7.3 Colour contrast

- Body text on page background: ≥ 7:1 (AAA) — already true in current
  Settings tokens.
- Status dots: min 4.5:1 against card background; destructive badge
  red on dark (`#ff5f5f` on `T.bg2`) verified 5.3:1.
- Never rely on red-vs-green alone — red pairs with `⚠` glyph, green
  pairs with `●` solid vs `○` hollow for ready/untested distinction.

### 7.4 Motion

- Respect `prefers-reduced-motion` — modal fades without slide,
  status dot pulse stops.

---

## 8. Loading states

Every async interaction gets an explicit state, not a silent hang.

| Interaction             | Idle                  | Loading                           | Success                  | Failure                |
|--------------------------|-----------------------|-----------------------------------|--------------------------|------------------------|
| Settings page load       | —                     | skeleton rows (3 ghost cards)     | rendered cards           | inline error + retry   |
| `Test` button            | `[Test]`              | `[Testing…]` + spinner on dot     | dot turns green, card status + result line persist | dot red, error line persists |
| Add/Edit modal save      | `[Test & Save]`       | disabled + spinner inline         | modal closes, card added | inline form error      |
| Wizard MCP step preview  | empty expander        | shimmer of 3 tool rows            | tool list populated      | inline error + retry   |
| Consent modal arrival    | no modal              | backdrop fades in 120ms then modal| —                        | —                      |
| Consent decision send    | buttons active        | buttons disabled + spinner on chosen | modal closes           | error banner + retry   |

Skeleton shimmer uses the existing `T.bg2` / `T.bg3` gradient stack
(same as LeftPanel sessions shimmer, so no new tokens).

---

## 9. Resolved decisions (mentor ruled 2026-04-24)

1. **WS consent bridge scope** — lands in THIS phase. Implementation
   order §11 makes it the first commit (`feat(backend): wire
   PromptConsentProvider into ws_chat`) before any frontend consent
   code. Consent modal without a real backend is test-theatre.

2. **Credential scoping** — tenant-scoped config, shared tenant
   credentials for v0.20.0. User-scoped credentials (per-seat tokens)
   deferred to M2 Month 2 / M3 — adds a permission model (ownership,
   visibility, cascade-delete) that is its own design doc. See §10.

3. **"Copy YAML snippet" on card menu** — cut. Leaks YAML mental
   model to users who shouldn't need it. Power users still have
   manifest export via the agent-wizard Publish step. §1.3 reflects
   this.

4. **Tool preview caching** — 60s TTL, keyed on `(server_name,
   config_hash)` where `config_hash` is SHA-256 over non-secret spec
   fields. Editing config busts cache automatically; `[Test]` also
   refreshes. Documented in §3.2.

5. **Narrow-window consent modal** — stay centered at all widths.
   At <600px shrink to `calc(100vw - 32px)` with internal scroll.
   One layout path keeps keyboard/SR contract single-sourced. §4.2
   reflects this.

---

## 10. Out of scope for v0.20.0

Explicitly deferred to M2 Month 2 or later so no one pads this phase:

- **Per-user credential overrides** (mentor ruling §9.2). Pilots at
  1–3 seats can share tenant tokens; user-scoped credentials require
  a real permission model (ownership, visibility rules, delete
  cascade) and its own design doc.
- **Per-agent tool scoping** (`mcp_servers[].allow_tools` /
  `deny_tools` in schema 1.1.0). v0.20.0 UI treats server selection
  as all-tools-or-none — selecting a server gives the agent every
  tool that server advertises, with consent gating on destructive
  calls. Per-tool allow/deny lists are schema-supported but not
  surfaced in the wizard. Deferred to M2 Month 2 when pilots have
  concrete need (e.g. expose `github.list_*` but not `github.delete_*`
  to a junior-analyst agent).
- **Custom HTTP headers** on HTTP-transport servers. `HttpTransportSpec`
  ships with `auth: {type: "bearer", token}` only. Servers requiring
  arbitrary headers (e.g. AWS SigV4, custom vendor auth) will need
  a `HttpTransportSpec.headers` extension and its own mentor review;
  deferred because bearer covers 95% of public MCP servers.
- Analytics on MCP tool usage (count, latency, cost).
- "Approve all pending" during multi-tool bursts.
- Tool search / filter in the Wizard preview (pilots rarely have >20
  tools per server).
- MCP server marketplace / directory (would need external curation).

---

## 11. Implementation order (proposed)

Matches the phase breakdown in the mission but with §0.1 pulled forward:

1. Backend: WS consent bridge in `ws_chat` (prereq for consent modal).
2. Backend: `/mcp-servers` CRUD + `/test` + SQLite table + keyring wiring.
3. Frontend: Settings MCP Servers page (Part A).
4. Frontend: Wizard MCP step (Part B).
5. Frontend: Consent modal + WS handler in chat (Part C).
6. Frontend: Agent card indicator (Part D).
7. Integration tests: GitHub MCP end-to-end, Slack MCP if reliable.

Each step is revertable in its own commit; the phase merges as a
single PR.

---

## 12. Change log

- `2026-04-24 v1` — initial draft (Claude Code, pending mentor review).
- `2026-04-24 v2` — applied mentor P0/P1 fixes + all 5 open-question
  rulings. Changes: manifest interpolation corrected to
  `${secrets.<name>}`; HTTP form scoped to bearer-token only with
  custom-headers deferred (§10); per-tool allow/deny scoping
  explicitly deferred (§10); `mcp_tools` capability added silently
  with passive note instead of confirmation banner; agent-card
  `mcp_server_names` specified as parsed-manifest derived (no DB
  column); WS protocol validates `request_id` against in-flight
  requests; `[Test]` result persists until next action (no 3s
  auto-dismiss); `cwd` moved behind Advanced disclosure; "Copy YAML
  snippet" card affordance cut; tool preview cache spec'd (60s,
  `(name, config_hash)`); consent modal stays centered at all
  widths. §9 converted from open questions to resolved decisions.
