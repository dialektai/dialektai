# M2 Этап 2.5 — Phase 1.3 implementation plan: Settings → MCP Servers

**Scope:** convert the existing `MCPSection` stub in
`frontend/src/screens/SettingsScreen.jsx` (lines 1127-1147, currently a
`ComingSoonBanner`) into a real CRUD surface that talks to the
`/mcp-servers` endpoints landed in Phase 1.2 (commit `2ed33b9` + hardening
`896f13a`).

**Related:**
- Product design — `docs/M2_MCP_UI_DESIGN.md` §1 (page layout) + §2 (modal)
- Backend contract — `python/server.py` `_mcp_row_to_response`
- Existing analogue — `ConnectionsSection` in `SettingsScreen.jsx`
  (CRUD over keyring-backed entities, same BodyShell pattern)

---

## 0. Fidelity to the approved product design

The big design doc (§1, §2) already covers the page layout, modal,
error states, accessibility, loading states, and keyboard behavior in
detail and is mentor-approved. This doc is a **code-implementation
plan only** — no new product decisions. Every deviation from the
design doc must be flagged here or escalated.

No deviations planned.

---

## 1. File scope

Single-file change: `frontend/src/screens/SettingsScreen.jsx`.

Rationale: matches how `ConnectionsSection` is structured (inline
function, no separate file) — keeps the Settings screen's Context /
toast / confirm wiring in scope without prop-drilling. SettingsScreen
is ~2400 lines already; one more section is not the tipping point.

If the MCP section grows past ~300 lines inline, extract to
`frontend/src/screens/settings/McpServersSection.jsx` in a follow-up.
Not in this commit.

---

## 2. Component tree

```
MCPSection()                                       ← REPLACES existing stub
├── BodyShell (crumb, title, desc, children)       ← existing component
├── {loading ? "Loading…" : …}
├── {empty-state} || {<McpRow />...}               ← row renderer
├── [+ ADD SERVER] button (when list non-empty)
└── {adding && <McpAddEditForm />}                 ← inline form
    └── (on save) POST /mcp-servers or PATCH /mcp-servers/{id}

McpRow({ server })
├── status dot ({ready|error|untested})
├── name + transport summary line
├── "<N tools>" | "<error>" | "Not yet tested"
├── [TEST] → POST /mcp-servers/{id}/test, renders inline
├── [EDIT] → sets `editing=server.id`, opens form
└── [DELETE] → useContext(Ctx).showConfirm → DELETE
```

No drawer, no modal — inline form matches `ConnectionsSection`'s
add/edit behavior. Editing flips the row into form-mode in place.
Fewer layout surfaces = fewer focus bugs.

---

## 3. State shape

```js
const [servers, setServers] = useState([]);
const [loading, setLoading] = useState(true);
const [adding, setAdding] = useState(false);
const [editingId, setEditingId] = useState(null);
const [testStatus, setTestStatus] = useState({});   // id → {loading, result, error}
const [form, setForm] = useState(EMPTY_FORM);
```

`EMPTY_FORM` shape:
```js
const EMPTY_FORM = {
  name: '', transport: 'stdio',
  command_text: '',       // multiline textarea, split on newlines to list[str]
  env_refs: [],           // [{env_name, ref_name}]
  env_secrets: [],        // [{ref, value}] — only populated during add/rotate
  cwd: '',
  url: '',
  auth_type: '',          // '' | 'bearer'
  auth_token: '',         // plaintext entry only, masked input
  timeout_seconds: '30',
};
```

Edit vs create: on edit, form pre-fills from the server row. Secrets
are NOT pre-filled (backend never returns them). The form shows
`••••••••` for existing secret fields with a `[Replace]` button that
reveals an empty input; submitting the form without touching the
`[Replace]` leaves the secret untouched (backend's PATCH semantics).

---

## 4. has_auth_token UX (mentor P2 gap closure)

Backend response surfaces `has_auth_token: bool` rather than the
plaintext token. Row affordances:

| State            | Display                                 | CTA                         |
|------------------|-----------------------------------------|-----------------------------|
| has_auth_token=true | `Bearer: ••••••••`                   | `[Replace]` in edit form    |
| has_auth_token=false + auth_type=bearer | `Bearer: ⚠ no token`  | `[Set token]` → opens edit  |
| auth_type=null   | (hidden)                                | —                           |

Replace flow: user clicks `[Replace]`, the masked display swaps to an
empty input, user types new token, save → backend overwrites keyring
entry atomically (existing PATCH logic).

---

## 5. API plumbing

All calls via the existing `API` constant (`http://localhost:8765`)
with plain `fetch`. No new HTTP client — `ConnectionsSection` uses
fetch directly and so do we.

| Trigger              | Call                              | On success                        | On error                        |
|----------------------|-----------------------------------|-----------------------------------|---------------------------------|
| mount / refresh      | GET /mcp-servers                  | setServers + setLoading(false)    | addToast('Failed to load servers', 'error') |
| add form submit      | POST /mcp-servers                 | refetch, close form, toast success | inline error under form        |
| edit form submit     | PATCH /mcp-servers/{id}           | refetch, close form, toast success | inline error under form        |
| delete (after confirm) | DELETE /mcp-servers/{id}        | optimistic-remove + toast         | rollback + toast error          |
| [TEST]               | POST /mcp-servers/{id}/test       | update testStatus[id] + refetch  | update testStatus[id].error     |

Empty 200 + `{success: false, error}` from /test is shown under the
row. 4xx/5xx from any endpoint: show inline error with HTTP status
and message; use existing `addToast` for transient feedback.

---

## 6. Form validation (frontend mirrors backend)

Client-side validation prevents obvious mistakes before submit:

- `name`: regex `/^[a-z][a-z0-9-]{0,63}$/`, uniqueness checked against
  `servers` (case-sensitive).
- `transport === 'stdio'`: `command_text` non-empty after trimming.
- `transport === 'http'`: `url` matches `/^https?:\/\//` (warn on
  plain http).
- `auth_type === 'bearer'`: `auth_token` required on create (matches
  backend's v2 hardening).
- `timeout_seconds`: parseFloat in [5, 300].

Server-side validation is authoritative — frontend validation is UX
lubricant, not a security boundary.

---

## 7. Loading / error states (design doc §8 fidelity)

- Initial list load: plain `"Loading…"` text (matches
  ConnectionsSection). Skeleton cards described in design doc §8 are
  **deferred** — same as ConnectionsSection defers its skeleton —
  because we don't have a shared skeleton primitive yet. Flag to
  revisit when we extract a `<Skeleton>` component.
- [TEST] button: disabled + `"Testing…"` while in-flight. Result
  text persists under the row until another action (per mentor's P2
  on design doc review).
- Form submit: submit button disabled + `"Saving…"`, errors inline.

---

## 8. Accessibility

Inherits from SettingsScreen's existing conventions (Tab order, focus
rings via `:focus-visible`, color-on-dark palette). MCP-specific:

- Status dots have `aria-label` (`ready` / `error` / `untested`).
- `[TEST] / [EDIT] / [DELETE]` buttons have visible text — no
  icon-only fallback (matches ConnectionsSection).
- Form inputs carry `<label>` elements — not placeholder-only.
- Delete confirmation goes through the existing `showConfirm` Ctx
  method (keyboard-accessible modal already used by Connections).

---

## 9. Keyboard shortcuts

None in v0.20.0. Enter submits the form. The design doc's consent
modal keyboard map (Enter/Esc) lives in Phase 1.5, not here.

---

## 10. Known-good-to-defer (commit-B P2 findings, acknowledged)

From mentor's commit-B review — acknowledged, NOT expected to change
frontend work:

- Orphan keyring entries on `env_refs` dropped via PATCH — backend
  silently leaves them. Frontend does not display these. Deferred
  until a credentials-inspector UI exists. Frontend makes no promises
  about them.
- PATCH with `auth_ref` change without `auth_token` change can leave
  old token under old ref. Same story. Deferred.

Both are harmless; no frontend workaround needed.

---

## 11. Testing strategy

The dialekt frontend is React without a component test harness today
(no Jest/Vitest setup in `frontend/`). This phase ships with **no
frontend unit tests** — matching project baseline. The verification
surface for this commit is:

1. Visual smoke: run the Tauri dev build, add a server, test, edit,
   rename (verify keyring migration from the UI by checking the
   `last_test_*` UI state after rename), delete.
2. Backend tests unchanged — 592 green, guarantees the API contract
   the frontend consumes.
3. Phase 2.1 (GitHub MCP real-server E2E) is the end-to-end
   regression catcher; failures there flag frontend bugs.

If the team adopts Vitest + React Testing Library as a separate
effort, backfill unit tests for `MCPSection` in that follow-up. Out
of scope for this commit.

---

## 12. Commit plan

Single commit: `feat(frontend/settings): MCP Servers CRUD page`.

- Replaces `MCPSection` implementation in `SettingsScreen.jsx`.
- No other files touched.
- Expected diff: ~350-500 lines net additions (new section code
  replaces a ~20-line stub).

If during implementation the section grows past ~450 lines or touches
more than one file, pause for a mentor ruling on extraction — do not
ship a multi-file commit under this plan without re-review.

---

## 13. Change log

- `2026-04-24 v1` — initial plan (Claude Code, pending mentor review).
