# v0.21.0 — MCP Server Templates + Bulk Import/Export

**Branch:** `feat/mcp-templates-and-bulk-import` (off `128b1017` — v0.20.0 merge commit)
**Status:** draft, awaiting mentor review
**Why this exists:** v0.20.0 ships the manual Settings → MCP Servers form. Pilots discovered (forecast in `M2_POST_RC_BACKLOG.md` "pilot rollout friction") that without curated templates and bulk import, every seat hand-types `npx -y @modelcontextprotocol/server-github` from a docs page. v0.21.0 closes that gap with two surfaces:

1. **Quick Add from template** — curated tiles at the top of Settings → MCP Servers; click → modal with command locked + only credentials editable.
2. **Bulk export / import** — admin exports configured servers (without secrets) as JSON, ships to seats; seats import in one click and only fill credentials.

Together these handle the two real pilot scenarios:
- Individual / small team → templates make popular MCPs one-click
- Enterprise → admin sets up an HTTP MCP gateway once, exports JSON, every seat imports + plugs in their own bearer token

Explicitly **not** v0.21.0 (per mentor's prior ruling on Phase 1.5 design):
- Cloud-synced templates (was L3 — over-engineered; HTTP gateway pattern via existing transport handles enterprise without it)
- Per-tool `allow_tools` / `deny_tools` UI (M2 Month 2)
- Slack MCP validation (pending maintained server)

---

## 1. Template catalog — shape and storage

Storage: a single bundled JSON file at
`python/dialekt/mcp_templates/catalog.json`. Shipped in the repo,
served by the backend. Easier than hardcoding into JS (lets
non-frontend folks edit), simpler than a database table (no migration,
no admin UI). Migration path to backend-managed marketplace later
is a one-table schema change.

### Catalog shape

```json
{
  "version": 1,
  "templates": [
    {
      "id": "github",
      "label": "GitHub",
      "icon": "github",
      "description": "Issue triage, PR review, repo housekeeping. Needs a GitHub PAT with repo scope.",
      "transport": "stdio",
      "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
      "env_refs": {"GITHUB_PERSONAL_ACCESS_TOKEN": "github_token"},
      "secret_prompts": [
        {
          "ref": "github_token",
          "label": "GitHub Personal Access Token",
          "placeholder": "ghp_...",
          "help_url": "https://github.com/settings/tokens?type=beta",
          "help_text": "Fine-grained token, repo scope (read for triage; write to create issues/PRs)."
        }
      ],
      "default_timeout_seconds": 30,
      "validated": true,
      "validation_notes": "Validated 2026-04-25 against @modelcontextprotocol/server-github 2025.4.8. See docs/MCP_PRODUCTION_VALIDATION.md.",
      "upstream_status_warning": "@modelcontextprotocol/server-github is marked deprecated by upstream (npm warning at install). Still functional. M2 Month 2 candidate to switch to github.com/github/github-mcp-server (Go binary, official)."
    },
    {
      "id": "filesystem",
      "label": "Filesystem",
      "icon": "folder",
      "description": "Bounded filesystem access (read/write within an explicit sandbox path). No credentials.",
      "transport": "stdio",
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "${prompt:sandbox_path}"],
      "env_refs": {},
      "secret_prompts": [],
      "string_prompts": [
        {
          "ref": "sandbox_path",
          "label": "Sandbox directory path",
          "placeholder": "/home/<user>/safe-workspace",
          "help_text": "Filesystem MCP can only touch paths under this directory. Use an explicit subdir, never your home."
        }
      ],
      "default_timeout_seconds": 60,
      "validated": true,
      "validation_notes": "Used as the canonical reference MCP in unit tests + cross-thread regression suite."
    },
    {
      "id": "slack-byos",
      "label": "Slack (bring your own server)",
      "icon": "chat",
      "description": "Connects dialekt to a Slack-aware HTTP MCP gateway YOU run. dialekt does NOT bundle a Slack MCP — pick a maintained one or run your own (e.g. an internal HTTP wrapper around the Slack Web API).",
      "transport": "http",
      "url_placeholder": "https://your-slack-mcp.example.com/mcp",
      "auth_type": "bearer",
      "secret_prompts": [
        {
          "ref": "auth_token",
          "label": "Bearer token",
          "placeholder": "...",
          "help_text": "Your Slack MCP gateway's auth token, NOT a Slack bot token directly. The gateway handles Slack auth on its side."
        }
      ],
      "default_timeout_seconds": 30,
      "validated": false,
      "validation_notes": "Slack MCP server quality varies. v0.21.0 ships this template as a starting point only — bring your own MCP server."
    },
    {
      "id": "linear",
      "label": "Linear",
      "icon": "diamond",
      "description": "Issue tracking via a Linear MCP server. Community package — bring your own API key.",
      "transport": "stdio",
      "command": ["npx", "-y", "@hatcloud/linear-mcp@1.2.2"],
      "env_refs": {"LINEAR_API_KEY": "linear_api_key"},
      "secret_prompts": [
        {
          "ref": "linear_api_key",
          "label": "Linear API key",
          "placeholder": "lin_api_...",
          "help_url": "https://linear.app/settings/api",
          "help_text": "Personal API key from Linear settings → API → Create new key."
        }
      ],
      "default_timeout_seconds": 30,
      "validated": false,
      "validation_notes": "Pinned to @hatcloud/linear-mcp@1.2.2 (latest as of 2026-04-25). Single-maintainer community package; no public source repo linked from npm metadata. Verify with [Test] before committing pilots."
    },
    {
      "id": "notion",
      "label": "Notion",
      "icon": "file",
      "description": "Notion read/write via a maintained community fork of the official Notion MCP server. Needs a Notion integration token.",
      "transport": "stdio",
      "command": ["npx", "-y", "@mieubrisse/notion-mcp-server@2.1.2"],
      "env_refs": {"NOTION_API_KEY": "notion_api_key"},
      "secret_prompts": [
        {
          "ref": "notion_api_key",
          "label": "Notion integration token",
          "placeholder": "secret_...",
          "help_url": "https://www.notion.so/my-integrations",
          "help_text": "Create a Notion integration, copy its secret, share specific pages with the integration so the MCP server can see them."
        }
      ],
      "default_timeout_seconds": 30,
      "validated": false,
      "validation_notes": "Pinned to @mieubrisse/notion-mcp-server@2.1.2 — explicitly described as a maintained fork of the official server. Verify with [Test] before pilot rollout."
    },
    {
      "id": "figma",
      "label": "Figma",
      "icon": "sparkle",
      "description": "Read Figma files / inspect frames via a community Claude-Desktop-oriented MCP. Needs a Figma personal access token.",
      "transport": "stdio",
      "command": ["npx", "-y", "claude-talk-to-figma-mcp@1.0.0"],
      "env_refs": {"FIGMA_TOKEN": "figma_token"},
      "secret_prompts": [
        {
          "ref": "figma_token",
          "label": "Figma personal access token",
          "placeholder": "figd_...",
          "help_url": "https://www.figma.com/developers/api#access-tokens",
          "help_text": "Settings → Personal access tokens. Read scope is enough for inspection-only agents."
        }
      ],
      "default_timeout_seconds": 30,
      "validated": false,
      "validation_notes": "Pinned to claude-talk-to-figma-mcp@1.0.0. Community package — verify with [Test] before pilot rollout."
    },
    {
      "id": "custom-http",
      "label": "Custom HTTP gateway",
      "icon": "globe",
      "description": "Connects to your company's HTTP MCP gateway behind a VPN. Use this when you have ONE gateway aggregating multiple tool sources for the whole company.",
      "transport": "http",
      "url_placeholder": "https://mcp.<your-org>.internal/",
      "auth_type": "bearer",
      "secret_prompts": [
        {
          "ref": "auth_token",
          "label": "Bearer token",
          "placeholder": "...",
          "help_text": "Seat-specific token from your gateway. The gateway holds the actual upstream credentials, not dialekt."
        }
      ],
      "default_timeout_seconds": 30,
      "validated": false,
      "validation_notes": "Generic template — pilots fill in their own gateway URL."
    },
  ]
}
```

**Custom stdio path** is intentionally NOT a Quick Add tile (mentor
ruling 5 — would clutter the curated row). The existing
`[+ Add server]` button at the bottom of the page is **relabeled
to `[+ Add custom server]`** and remains the home for stdio with
arbitrary commands or any non-templated transport.

### Schema notes

- `transport`, `command`, `env_refs` mirror the `MCPServerCreate` Pydantic shape so the modal can submit a near-identical payload.
- `secret_prompts: list` — drives the modal's masked input rows. Each entry maps to one `env_secrets` payload entry on submit.
- `string_prompts: list` — drives non-secret editable fields (e.g. filesystem sandbox path). The placeholder `${prompt:sandbox_path}` in `command` gets substituted **frontend-side at submit time** (see Substitution boundary below).
- `default_timeout_seconds` — modal pre-fills the timeout field; user can override.
- `validated: bool` + `validation_notes` — UI surfaces a green checkmark or yellow "untested" pill.
- `upstream_status_warning` — pinned amber banner inside the modal for templates whose npm package has a known concern (e.g. `@modelcontextprotocol/server-github` deprecation).
- All community-package commands are **version-pinned** (`@pkg@x.y.z`) so an upstream churn doesn't break a pilot's `npx -y` install. Catalog refresh = bump the pin.

### Substitution boundary (mentor P1)

`${prompt:<key>}` placeholders inside template `command` arrays
are substituted **only by the frontend**, immediately before submitting
to `POST /mcp-servers`. The backend never parses template vocabulary
— it receives a fully-resolved `command: list[str]` via the standard
`MCPServerCreate` payload. Reasons:

1. **No template vocabulary leaks into Pydantic.** `MCPServerCreate`
   stays the single source of truth for what a "server config" is.
2. **No new attack surface.** A backend-side substituter would need
   to defend against `${prompt:cwd}/../../etc/passwd` style injection;
   keeping it frontend-only makes the catalog a pure JSON data
   contract.
3. **Forward-compatible with cloud-served catalogs (M3).** A future
   cloud-synced template can be delivered verbatim — no backend
   handler needs to update.

### Backend endpoint

```
GET /mcp-templates  →  200 OK with the catalog JSON above
```

No auth (matches the rest of dialekt's local-app endpoints). Reads
`python/dialekt/mcp_templates/catalog.json` once at module load via
a memoized helper. Reload-on-change deferred (catalog is immutable
per release).

---

## 2. Frontend — Quick Add bar + Template modal

### 2.1 Layout change in Settings → MCP Servers

Above the existing "Configured servers" list, add a "Quick add"
section:

```
┌──────────────────────────────────────────────────────────────┐
│ 02 / CAPABILITIES → MCP SERVERS                              │
│                                                              │
│ MCP Servers                                                  │
│ External tool servers that agents can call. Credentials      │
│ are stored in your OS keychain — never in config files.      │
│                                                              │
│ ┌─ Quick add from template ─────────────────────────────┐   │
│ │  [GitHub ✓]  [Filesystem ✓]  [Slack BYOS]             │   │
│ │  [Linear ⚠]  [Notion ⚠]  [Figma ⚠]                    │   │
│ │  [Custom HTTP gateway]  [Custom stdio MCP]            │   │
│ │                                                       │   │
│ │  [Import from JSON ▸]                                 │   │
│ └───────────────────────────────────────────────────────┘   │
│                                                              │
│ Configured servers                          [Export JSON]    │
│ ╔═══════════════════════════════════════════════════════╗    │
│ ║ github                              ● 26 tools        ║    │
│ ║ stdio · npx -y @modelcontextprotocol/server-github    ║    │
│ ╚═══════════════════════════════════════════════════════╝    │
└──────────────────────────────────────────────────────────────┘
```

- ✓ badge on validated templates (green)
- ⚠ badge on community / untested templates (amber)
- The `[+ Add server]` button at the bottom of the empty state
  remains for users who want the existing inline freeform form —
  this is the route for advanced edits or transports the templates
  don't cover.
- `[Import from JSON ▸]` and `[Export JSON]` are L2 surfaces — see
  §3.

### 2.2 Template tile click → TemplateModal

```
┌────────────────────────────────────────────────────────────┐
│  GitHub MCP                                          [×]   │
├────────────────────────────────────────────────────────────┤
│  ✓ Validated 2026-04-25                                    │
│                                                            │
│  Issue triage, PR review, repo housekeeping. Needs a       │
│  GitHub PAT with repo scope.                               │
│                                                            │
│  ⚠ Upstream notice                                         │
│  @modelcontextprotocol/server-github is marked deprecated  │
│  by upstream (npm warning at install). Still functional.   │
│                                                            │
│  Server name *                                             │
│  [ github                                              ]   │
│                                                            │
│  How dialekt will call it (locked):                        │
│  [ npx -y @modelcontextprotocol/server-github          ]   │
│                                                            │
│  GitHub Personal Access Token *                            │
│  [ ********************                                ]   │
│  ↳ How to create: Fine-grained token, repo scope.          │
│    [Open GitHub →]                                         │
│                                                            │
│  Timeout (seconds)                                         │
│  [ 30                                                  ]   │
│                                                            │
│                          [Cancel]  [Test & Save]           │
└────────────────────────────────────────────────────────────┘
```

Behavior:
- `Server name` defaults to template `id`, editable — pilot can have multiple
  GitHub MCPs (e.g. `github` and `github-personal`).
- Locked command line displays for transparency but is not editable.
- Each `secret_prompts` entry → one masked `<input type="password">` row
  with help text + optional `[Open <site> →]` link.
- Each `string_prompts` entry → one regular text input row.
- For `custom-stdio` and `custom-http` templates (no fixed command/url),
  the lock turns into an editable textarea / URL input pre-filled with
  the placeholder.
- `[Test & Save]` flow:
  1. POST `/mcp-servers` (writes keyring + row)
  2. POST `/mcp-servers/{id}/test`
  3. If test succeeds → modal closes, success toast, list refreshes
  4. If test **fails** → modal stays open with red inline error +
     two buttons: `[Save anyway]` (keeps the row, closes modal,
     pilot can debug from Settings) and `[Retry test]` (re-issues
     `/test` without recreating the row). On `Save anyway`, the row
     persists with `last_test_ok=false`, surfacing as a red dot in
     the list. On every other modal-failure path (POST 422 / 409),
     the modal stays open with the inline error and never auto-saves
     a partial config — matches the existing inline form behavior.

### 2.3 Component layout

Single new file `frontend/src/components/McpTemplateModal.jsx` (~150-200 lines).
SettingsScreen.jsx grows by ~80 lines for the Quick Add row + tile
rendering + state management for which template is open in the modal.

Modal styling matches `ConsentModal.jsx` from v0.20.0 (centered overlay,
shrinks at narrow widths, scrim background) but is dismissible by Esc /
clicking the scrim — unlike consent, this is configuration, not a
permission gate.

### 2.4 Open question for mentor on §2

Mentor previously ruled "inline form, not modal" for the Add Server
flow (Phase 1.3 ruling 1) for consistency with `ConnectionsSection`.
The TemplateModal is a NEW affordance with a different mental model
(known thing, locked structure, only credentials editable). My read:
modal is right here, the original ruling was for the freeform CRUD
shape. Re-ruling please.

---

## 3. Bulk export / import

### 3.1 Export shape

```
GET /mcp-servers/export
→ 200 OK + Content-Disposition: attachment; filename="dialekt-mcp-servers.json"
```

Body:

```json
{
  "version": 1,
  "exported_at": "2026-04-25T14:30:00+05:00",
  "servers": [
    {
      "schema_version": 1,
      "name": "github",
      "transport": "stdio",
      "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
      "env_refs": {"GITHUB_PERSONAL_ACCESS_TOKEN": "github_token"},
      "cwd": null,
      "url": null,
      "auth_type": null,
      "auth_ref": null,
      "timeout_seconds": 30
    }
  ]
}
```

**Schema versioning** (mentor P1). Each server entry carries its own
`schema_version: 1` field. Future migrations (e.g. M3 cloud-synced
templates adding `template_id` / `template_version` for upgrade
tracking) bump per-entry to `schema_version: 2` while v1 imports
continue to work — the import endpoint dispatches by per-entry
version. Costs one JSON line; makes the contract self-describing.

**`exported_by` field** (mentor ruling 3). Omitted. dialekt's
positioning is local-first, regulated-market, no telemetry. Even
hostname is leakage with no UX value — admins who need to label
exports rename the file themselves.

**Critical:** the export NEVER includes secret values, only the env
var → ref name mapping. The endpoint reads from `mcp_servers` rows
directly — secrets live in the keyring and are not touched. Test
asserts no plaintext secret can ever appear in the export response
body (regression test analogous to the existing
`test_response_never_leaks_secret_value`).

### 3.2 Import shape

```
POST /mcp-servers/import
Content-Type: application/json

{ "version": 1, "servers": [...] }
```

Behavior per server in the array:
- If a server with the same `name` already exists → skip, return
  `skipped: [<name>]` in the response
- Else → insert (same Pydantic validation as `POST /mcp-servers`)
- Secrets are NOT in the import — `secrets_needed: list[str]` in the
  response lists every (server_name, env_var, ref_name) tuple the
  pilot still needs to fill in via Settings → MCP Servers → Edit

Response:

```json
{
  "imported": [{"id": "...", "name": "github"}],
  "skipped": ["already-existed"],
  "secrets_needed": [
    {"server": "github", "env_var": "GITHUB_PERSONAL_ACCESS_TOKEN", "ref": "github_token"}
  ]
}
```

### 3.3 Frontend Export / Import UI

- `[Export JSON]` button in the "Configured servers" header — one
  click, browser downloads `dialekt-mcp-servers.json`. No modal.
- `[Import from JSON ▸]` button below the Quick Add tile row.
  Click opens a small modal with two tabs: Upload file / Paste JSON.
  After upload/paste:
  - Preview list: "Will import: github, jira, internal-mcp. Will skip: filesystem (already exists)."
  - `[Import]` button submits → POST → server list refetches →
    success toast lists `secrets_needed` so the pilot knows which
    rows still need credentials.

### 3.4 Validation

Import endpoint runs each entry through `MCPServerCreate` Pydantic
validation. **Atomic semantics** (mentor ruling 4): any single
validation failure aborts the whole import — no partial state
lands. The response surfaces the failing entry's index + error
message so the pilot can fix the JSON and re-upload. Names that
collide with existing rows are reported in `skipped` (non-failures).
Trade-off accepted: one bad entry blocks the rest, and pilot has
to fix the file. Loud failure beats silent partial state.

---

## 4. Tests

### Backend (pytest)

New file `python/tests/test_mcp_templates_endpoint.py`:
- `GET /mcp-templates` returns 200 + non-empty templates array
- Each template has the required shape (id, label, transport, secret_prompts list)
- Catalog version is a positive int

New file `python/tests/test_mcp_servers_bulk.py`:
- `GET /mcp-servers/export` returns 200 with correct shape, no secrets
- Round-trip: create 3 servers (one with secrets) → export → wipe DB → import → verify count + names + that secrets_needed lists the missing refs
- Import respects name collisions (skipped, not duplicated rows)
- Import rejects malformed JSON with 400
- Import rejects entries that fail MCPServerCreate validation atomically (no partial state)
- Export response body never contains a stored plaintext secret
  (regression test — paranoid check identical in spirit to existing
  test_response_never_leaks_secret_value)

### Frontend (zero unit tests baseline preserved)

Visual smoke in Tauri dev build — same posture as v0.20.0.

---

## 5. Commits — split for revertable history

1. `feat(mcp/templates): catalog JSON + GET /mcp-templates endpoint`
   — backend only, JSON file + endpoint + tests
2. `feat(frontend/settings): Quick Add tiles + TemplateModal`
   — frontend only, consumes the endpoint
3. `feat(server): bulk export/import for /mcp-servers`
   — backend only, two new endpoints + tests
4. `feat(frontend/settings): Export/Import JSON buttons`
   — frontend only, consumes the endpoints

Each commit followed by mentor commit review per the v0.20.0
discipline rule.

---

## 6. Line-budget ceiling

| Commit | Estimate | Hard ceiling |
|---|---|---|
| 1. Catalog + endpoint | ~250 lines (catalog JSON) + ~30 lines (endpoint) + ~80 lines (tests) | 500 |
| 2. Quick Add + TemplateModal | ~80 lines (SettingsScreen delta) + ~180 lines (TemplateModal) | 350 |
| 3. Bulk export/import | ~120 lines (endpoints) + ~150 lines (tests) | 350 |
| 4. Export/Import buttons | ~150 lines (modal + handlers + Settings delta) | 250 |

If any commit breaches its ceiling, pause + re-invoke mentor.

---

## 7. Mentor rulings — applied

All five open questions from v1 of this plan are now closed. Rulings
applied directly into the body above:

1. **Modal for TemplateModal** (re-ruling §2 from prior Phase 1.3 inline-only ruling). TemplateModal is structurally different from the freeform CRUD form: known catalog entry, locked command, only credentials editable, time-bounded interaction. Modal is the right affordance. `[+ Add custom server]` inline path stays unchanged for freeform CRUD.
2. **JSON file in repo** (§1). Memoized read at module load. Cloud-served catalog is M3 territory.
3. **Omit `exported_by`** (§3.1). Local-first / regulated-market positioning — no leakage with no UX value. Admins rename files themselves.
4. **Atomic import** (§3.4). Surprise partial state is the worst failure mode for a config-import flow.
5. **Remove `custom-stdio` from Quick Add tile row, relabel `[+ Add server]` → `[+ Add custom server]`** (§1, §2.1). Curated tile row stays clean; custom path is one button click away below.

---

## 8. Change log

- `2026-04-25 v1` — initial plan, post-v0.20.0 ship.
- `2026-04-25 v2` — applied mentor's first-pass review:
  - **P1 unverified npm packages fixed.** All three placeholder
    package names did NOT exist on npm (verified via `npm view`).
    Replaced with real packages, version-pinned:
    - linear: `@hatcloud/linear-mcp@1.2.2`
    - notion: `@mieubrisse/notion-mcp-server@2.1.2` (maintained
      fork of official)
    - figma: `claude-talk-to-figma-mcp@1.0.0`
  - **P1 substitution boundary documented** as frontend-only
    (§1 Substitution boundary).
  - **P1 per-server `schema_version: 1`** added to export shape
    (§3.1).
  - **P2 atomic import ruling** moved into §3.4 body, removed from
    open questions.
  - **P2 Test+Save failure spec** added to §2.2 (modal stays open,
    inline error, `[Save anyway]` / `[Retry test]` actions).
  - **Custom-stdio tile removed** per mentor ruling 5; existing
    `[+ Add server]` button relabeled `[+ Add custom server]`.
  - All 5 mentor rulings applied directly into the plan body; §7
    converted from open questions to rulings-applied summary.
