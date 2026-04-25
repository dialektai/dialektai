# v0.24.0 — heavy-user happiness

**Branch:** `feat/v0.24-approve-all-and-gh-go` off `4970583` (v0.23.1)
**Status:** draft, awaiting mentor review

Two scope items targeting agents that fire MCP tools heavily:

1. **"Approve all pending"** — fourth ConsentModal button to clear the consent queue in one click when an agent fires a multi-tool burst (e.g. "create 5 issues, label them all").
2. **GitHub MCP migration to the official Go binary** (`github.com/github/github-mcp-server`) — replacing the upstream-deprecated `@modelcontextprotocol/server-github` npm package the catalog has pinned since v0.21.

---

## 1. Approve all pending — design

### Current pain

ConsentModal shows three buttons: `Deny (Esc)` · `Approve for session (⇧⏎)` · `Approve once (⏎)`. When N destructive tools queue (visible as `1 of N` indicator), the user makes N decisions sequentially. Heavy workflows hit consent fatigue.

### Proposed decision: `approved_all`

A fourth button appears only when `queueLength > 1`. Click → resolves the head request AS APPROVED + resolves every other currently-pending consent future for this ws_id AS APPROVED. **Snapshot semantics** — only requests already pending at click time. Future requests in the same turn re-prompt normally.

Rationale: user sees "5 pending", makes one decision over those visible 5. If the agent later fires another 3 tools in the same turn, those are NEW requests the user didn't see at click time — re-prompting matches expectation. Less surprise than "approve everything for this session" which `Approve for session` already covers per-(server,tool).

### WS protocol extension

```json
// Frontend → backend
{ "type": "mcp_consent_response", "request_id": "<head>", "decision": "approved_all" }
```

Backend handler (`server._handle_consent_response`):

```py
if raw == "approved_all":
    # Resolve head with APPROVED
    fut.set_result(ConsentDecision.APPROVED)
    # Snapshot all OTHER pending futures for this ws_id; resolve same.
    prefix = f"{ws_id}:"
    siblings = [k for k in _pending_consents
                if k.startswith(prefix) and k != key]
    for sk in siblings:
        sf = _pending_consents.get(sk)
        if sf and not sf.done():
            sf.set_result(ConsentDecision.APPROVED)
    return True
```

`ConsentDecision` enum **does NOT change** — `approved_all` is a wire-level shorthand that resolves to a batch of `APPROVED` decisions. This keeps the runtime layer unchanged: every `invoke_tool` still sees a normal `APPROVED` decision, audit rows are normal `mcp_consent_decision` with `result: "approved"`. The "batch" nature is invisible to the runtime but tracked at audit-log level via a `batch_request_id` extra field set on the head AND propagated to siblings.

### Audit semantics (mentor question 1)

Two options:

(a) **Per-call audit rows** — N decision rows, each with `result: "approved"` and `extra: {batch_request_id: "<head>"}`. Forensic queries can group by batch_request_id to see "this user approved 5 calls in one click".

(b) **Single audit row** — 1 decision row with `result: "approved_all_burst"` and `extra: {batch_size: 5, batch_request_ids: [...]}`. Cleaner audit log, harder to join against per-call `mcp_tool_call` rows.

My lean: (a). Symmetric with existing per-call audit; preserves linkage between consent and tool_call by request_id.

### Frontend modal

`ConsentModal.jsx` gains a fourth action when `queueLength > 1`:

```
[Deny (Esc)]  [Approve for session]  [Approve all 5 pending (⇧⌘⏎)]  [Approve once (⏎)]
```

Keyboard: `Shift+Cmd/Ctrl+Enter`. Disabled when queue size = 1.

### Tests

- `test_approved_all_resolves_all_pending` — three pending consents, head gets `approved_all` decision, all three resolve to APPROVED
- `test_approved_all_does_not_affect_other_ws_id` — second WS session's pending consents untouched
- `test_approved_all_late_request_reprompts` — request arrives AFTER approved_all → fresh prompt fires (snapshot semantics)
- `test_approved_all_with_queue_of_one` — falls through to APPROVED behavior (no batching effect, but doesn't crash)

---

## 2. GitHub MCP migration to Go binary

### Status quo

`python/dialekt/mcp_templates/catalog.json` `github` template:

```json
"command": ["npx", "-y", "@modelcontextprotocol/server-github"],
"env_refs": {"GITHUB_PERSONAL_ACCESS_TOKEN": "github_token"},
"validated": true,
"upstream_status_warning": "@modelcontextprotocol/server-github is marked deprecated by upstream..."
```

Validated 2026-04-25 against `2025.4.8`. Upstream npm-deprecated. The replacement is `github.com/github/github-mcp-server` — a Go binary, official from GitHub, actively maintained.

### Proposed catalog change

Replace the github template:

```json
{
  "id": "github",
  "label": "GitHub",
  "icon": "diamond",
  "description": "Issue triage, PR review, repo housekeeping. Official MCP server from GitHub. Requires the `github-mcp-server` binary on PATH (install via `go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest`).",
  "transport": "stdio",
  "command": ["github-mcp-server", "stdio"],
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
  "string_prompts": [],
  "default_timeout_seconds": 30,
  "validated": false,
  "validation_notes": "Migrated 2026-04-25 from upstream-deprecated @modelcontextprotocol/server-github (which was validated against 2025.4.8). New target: github.com/github/github-mcp-server (Go binary, official GitHub maintainer). Install via `go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest`. **PATH caveat (mentor P1):** GUI-launched desktop apps on macOS inherit a stripped PATH that often excludes `~/go/bin`. If [Test] reports `command not found`, either (a) symlink the binary to `/usr/local/bin/github-mcp-server` or (b) edit the command to use the absolute path. Re-validation against this command pending — flip to validated:true after a fresh harness run with a real PAT (must include the Tauri-bundle launch path, not just dev-mode python -m server)."
}
```

Key changes:
- `command` switches from `npx -y @modelcontextprotocol/server-github` → `github-mcp-server stdio`
- `description` includes the install hint
- `validated: false` — flip back to `true` after a fresh harness run with a real PAT
- `upstream_status_warning` field removed (resolved by migration)

### Backwards compatibility (mentor question 2)

Existing pilots with the old `command` saved to their local `mcp_servers` SQLite row keep working — `npm view @modelcontextprotocol/server-github 2025.4.8` still resolves, the package still functions, just nobody maintains it. Their installs don't break on upgrade.

New installs hit the Go-binary template. They must `go install ...` first, OR fall back to manually editing the command to `npx -y @modelcontextprotocol/server-github` if they can't install Go.

### Should we keep a `github-npm-legacy` fallback template? (mentor question 3)

Three options:

(a) Single template, Go-binary only. Pilots without Go are SOL until they install it.
(b) Two templates: `github` (Go, recommended) and `github-npm-legacy` (npm, deprecated). Pilots without Go have a working path.
(c) Single template, command is `["npx", "-y", "@modelcontextprotocol/server-github"]` with `description` recommending the Go binary as faster/maintained. Aspirational migration over time.

My lean: (a). The catalog already has `custom-stdio` as the freeform escape hatch — pilots with niche setups use that. Two GitHub templates clutters the curated row and signals indecision.

### Re-validation (mentor question 4)

The `scripts/mcp_validation/run_github_e2e.py` harness from v0.20.0 still applies — same flow (Settings create → /test → tools list → read tool call → write tool call with consent → audit chain → keyring lifecycle). Only the `command` argv changes.

The user can re-run with a fresh PAT once they're ready (current PATs revoked per security hygiene). Until then: catalog ships with `validated: false` honest pill.

Alternative: I run validation now if user provides a fresh PAT in this session. Same drill as v0.20 — token in env, never in commit, revoked after run, two cleanup issues to close on dialektai/dialektai.

---

## 3. Open questions for mentor

1. **Audit semantics for approved_all** — per-call rows with `batch_request_id` (a, my lean) vs single batch row (b)?
2. **WS protocol extension** — adds `decision: "approved_all"` value. Forward-compat: existing v0.23 backend treats unknown decision as DENIED (defensive coercion shipped in v0.20 hardening). Old backends harmlessly deny — desirable failure mode. Confirm.
3. **GitHub template strategy** — single Go template (a) vs Go + legacy npm (b) vs npm with Go-recommendation (c)?
4. **Re-validation timing** — ship v0.24.0 with `validated: false` and run validation post-ship as v0.24.1 (like v0.20.0 → v0.20.0 RC pattern), OR block ship on fresh real-PAT validation?
5. **Approve-all keyboard shortcut** — `Shift+Cmd/Ctrl+Enter` collides with macOS app-level shortcuts in some contexts. Alternative: `A` key with focus on the modal. My lean: `Shift+Enter` only (already used for Approve session); use a NEW key — `Cmd/Ctrl+A` (select-all metaphor) or `Shift+Cmd/Ctrl+A`.

## 4. Commit plan

| # | Title | Files | Estimated lines |
|---|---|---|---|
| 1 | `feat(server): approved_all WS decision resolves all pending consents in burst` | `python/server.py` + tests | ~80 (handler ext + 4 tests) |
| 2 | `feat(frontend/chat): Approve all pending button + keyboard shortcut` | `ConsentModal.jsx` + `useChat.js` | ~50 (button + handler + queue check) |
| 3 | `feat(mcp/templates): migrate github template to official Go binary` | `catalog.json` + tests | ~30 (template swap + test update) |
| 4 | `docs+chore`: any post-implementation cleanups | — | ~20 |

Total ~180 lines + tests. Hard ceiling 250 per commit. Mid brake at 220.

## 5. Out of scope (deferred to v0.25 or later)

- Approve-all-for-rest-of-turn (broader scope) — would need turn boundaries, separate commit
- "Always approve this server" persistent config — already covered by `Approve for session` + manifest-level `autonomy: autonomous`
- File upload in Bulk Import (v0.21 carry-over)
- B6 audit dashboard
- Multi-LLM × MCP real-cred E2E
- macOS/Windows release artifacts

## 6. Change log

- `2026-04-25 v1` — initial plan post-v0.23.1 ship.
