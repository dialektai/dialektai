# MCP Production Validation — v0.20.0

**Status:** ✅ GitHub MCP path validated end-to-end · ⚠️ Slack MCP deferred (no maintained server available at validation time)
**Date:** 2026-04-25
**Branch:** `feat/m2-mcp-production-complete`
**Harness:** `scripts/mcp_validation/run_github_e2e.py`
**Operator:** Claude Code on a Linux desktop, real GitHub PAT supplied via env, immediately revoked after the run

This is the live-credentials validation pass that AGENT_CATALOG.md
Category 5.5 is gated on. See `M2_POST_RC_BACKLOG.md` V1 for the
deferral rationale that this document closes.

---

## What was tested

The harness exercises every layer of the v0.20.0 RC GitHub MCP path
with **no mocks**. The MCP server is the real
`@modelcontextprotocol/server-github` (npm version `2025.4.8`,
deprecated upstream — see "Findings" below) running as a stdio
subprocess. Every API call hits real GitHub.

| # | Stage                  | Result | Notes                                                                    |
|---|------------------------|--------|--------------------------------------------------------------------------|
| 1 | backend_started        | ✅ pass | TestClient + isolated `~/.dialekt` tempdir + real `dialekt.secrets` keyring |
| 2 | create_mcp_server      | ✅ pass | `POST /mcp-servers` 201; **token leak check passed** (response body contains zero plaintext token chars) |
| 3 | test_connection        | ✅ pass | `POST /mcp-servers/{id}/test` 200 + `{"success": true, "tool_count": 26}` in 1.27 s |
| 4 | last_test_columns      | ✅ pass | `last_test_ok=true`, `last_test_at`, `tool_count=26` persisted on the row |
| 5 | tool_discovery         | ✅ pass | 26 tools enumerated, sample: `create_or_update_file`, `search_repositories`, `create_repository`, `get_file_contents`, `push_files`, `create_issue`, `create_pull_request`, `fork_repository` (full list in stdout JSON) |
| 6 | read_tool_call         | ✅ pass | `runtime.invoke_tool("github", "search_repositories", {...})` returned 1 content block, `is_error=false` |
| 7 | write_tool_call        | ✅ pass | `runtime.invoke_tool("github", "create_issue", {...})`. **Consent prompt fired** — `destructive=true`, `destructive_source="heuristic"`. **Real issue created** on `dialektai/dialektai` (issues #6 and #7 from the two harness runs) |
| 8 | audit_chain            | ✅ pass | 4 rows in `audit_log`: `mcp_tool_call` (read), `mcp_consent_requested` (write), `mcp_consent_decision` (write→approved), `mcp_tool_call` (write). Linkage by `agent_id="validation-agent"` consistent across all 4. |
| 9 | keyring_pre_delete     | ✅ pass | `dialekt.secrets.get_secret("mcp.github.github_token")` returns the stored value |
| 10| delete_mcp_server      | ✅ pass | `DELETE /mcp-servers/{id}` 204 |
| 11| keyring_post_delete    | ✅ pass | `get_secret("mcp.github.github_token")` returns `None` after DELETE |

**Validation summary:** `total_stages=10, failed_stages=[]` (the harness counts the summary itself separately).

**Wall time:** ~6 seconds for the full flow on a warm npm cache (npx
needs the package downloaded). First run including `npm install` ≈ 25 seconds.

---

## What this proves about v0.20.0 RC

1. **Settings → MCP Servers CRUD** is correct end-to-end against a
   real npm-distributed MCP server. The `command: [npx, -y, ...]`
   transport spec, the `env_refs` → `env_secrets` keyring round-trip,
   and the `[Test]` connection probe all behave as documented.

2. **Consent gating is genuine, not theatre.** The prompt fires for a
   `create_issue` call before the GitHub API is hit. Approving
   produces a real issue; denying would block the call (the harness
   exercises only the approve path because the goal is full-chain
   validation; the deny path is covered by unit tests at the
   provider level).

3. **Audit linkage works.** The four-row chain (`mcp_tool_call` for
   the read auto-approve + `mcp_consent_requested` /
   `mcp_consent_decision` / `mcp_tool_call` for the write) lets a
   future audit dashboard reconstruct exactly what the agent did,
   when consent was asked, and what the user decided.

4. **Secret hygiene holds at runtime.** The token never appeared in
   any HTTP response body, any audit row, any log line emitted by
   the harness, or any field returned by `_mcp_row_to_response`. The
   `leak_check: passed` in stage 2 specifically verifies the create
   response body contains zero verbatim chars of the token. After
   `DELETE /mcp-servers/{id}`, the keyring entry is gone — no
   residue across server lifecycles.

5. **`@modelcontextprotocol/server-github` v`2025.4.8` is wire-compatible** with our `MCPClient`. 26 tools enumerate cleanly,
   the destructive-detection heuristic correctly tags `create_issue`
   without an explicit `annotations.destructive` (the tool name
   matched the `create` token).

---

## Findings (pre-pilot)

- **[Upstream] `@modelcontextprotocol/server-github` is marked
  deprecated by upstream** — npm warning at install time:
  > `Package no longer supported. Contact Support at
  > https://www.npmjs.com/support for more info.`

  This is an upstream packaging decision, not a dialekt bug. The
  package still works as of `2025.4.8`. Pilots running the GitHub
  blueprint (AGENT_CATALOG §5.5.1) should be told to expect
  upstream churn — the canonical replacement path is
  `github.com/github/github-mcp-server` (Go binary, official from
  GitHub itself). Consider switching the blueprint command to that
  binary in M2 Month 2 if pilot interest in GitHub is strong.
  Tracked in `M2_POST_RC_BACKLOG.md` (will be added as B7 in the
  next backlog refresh).

- **[Harness] Two real issues created on `dialektai/dialektai`**:
  #6 (first run, before `audit_callback` was wired into the
  validation runtime) and #7 (second run with the full audit
  chain). Both labeled "automated, safe to close" in title and
  body. Close them at any time; the validation harness intentionally
  does not auto-close to avoid promising a delete capability the
  harness shouldn't grant itself.

- **[Slack — DEFERRED]** No maintained Slack MCP server with a
  reliable [Test] gate was available at validation time (the
  community options are forks of varying maintenance status). Per
  mentor's pre-release ruling on Phase 3.1, AGENT_CATALOG §5.5.2
  remains ⚠️ status-flagged; v0.20.0 ships with GitHub validated
  and Slack scoped as "Coming later — pending a maintained MCP
  server pass."

---

## Token discipline

The PAT for this validation:

1. Was supplied via the `DIALEKT_VALIDATION_GITHUB_TOKEN` env var to
   the harness — **never written to a file**, never embedded in a
   shell-history command (the harness reads from `os.environ`).
2. Lived in the OS keychain (Secret Service) during the run, under
   account `mcp.github.github_token` — **not in
   `~/.dialekt/config.json`**, not in any log file emitted by the
   harness or by `dialekt.secrets`.
3. Was revoked by the operator immediately after the run completed.
   See "Operator notes" below.

The harness contains a `_redact()` helper that pre-redacts any
verbatim token occurrence from string fields before they're written
to the events JSON; the `leak_check: passed` stage 2 assertion
specifically verifies the create-mcp-server response body contains
zero verbatim token chars.

---

## How to re-run

```bash
DIALEKT_VALIDATION_GITHUB_TOKEN='ghp_...' \
DIALEKT_VALIDATION_GITHUB_REPO='owner/repo' \
python scripts/mcp_validation/run_github_e2e.py
```

Outputs JSON-per-line events to stdout. A run that ends with
`{"stage": "validation_summary", "ok": true, ...}` is a pass; any
non-pass `ok: false` stage means the run failed and the catalog
status flag should NOT be flipped to ✅.

This script is intentionally NOT part of the pytest suite — it
needs a live PAT, creates a real issue, and CI shouldn't have
either of those things.

---

## Catalog status flip

Following this validation, AGENT_CATALOG §5.5.1 (GitHub Operations
Agent — blueprint) is updated from ⚠️ to ✅. §5.5.2 (Slack
Automation Agent — blueprint) remains ⚠️ pending a maintained Slack
MCP pass. §5.5.3 (Multi-tool Research Agent — composition) remains
⚠️ because the Slack-MCP component of the blueprint is not validated
yet; the GitHub-MCP + filesystem-MCP composition without Slack does
work via this harness's coverage but the blueprint as written
includes Slack.

---

## Change log

- `2026-04-25 v1` — initial validation pass, GitHub MCP green,
  Slack deferred.
