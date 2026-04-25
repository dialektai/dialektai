# M2 Этап 2.5 — post-RC backlog

Items that landed as **mentor-approved deferrals** during the v0.20.0
RC cycle. Each is documented in the design or impl-plan section
referenced below; this file is the single roll-up so AGENT_CATALOG and
WHAT_DIALEKT_DOES_TODAY can point to one place instead of multiple.

Mentor framing: these are not bugs. They are scope decisions taken
to keep the v0.20.0 RC narrow and revertable. None blocks pilot use
of the surfaces that did ship.

---

## Frontend

### F1. Per-tool `allow_tools` / `deny_tools` UI
- **Where deferred:** `docs/M2_MCP_UI_DESIGN.md` §10, `M2_MCP_UI_PHASE_1_4_IMPL.md` §10
- **What's missing:** Builder Wizard MCP Tools step ticks whole servers, not individual tools. Manifest schema 1.1.0 supports per-tool allow/deny lists; the runtime honors them; only the UI is absent.
- **Workaround until built:** edit YAML by hand and re-import via /agents/import-yaml.
- **Target:** M2 Month 2.

### F2. Full tool-name preview in Wizard
- **Where deferred:** `M2_MCP_UI_PHASE_1_4_IMPL.md` §2 (scope trim)
- **What's missing:** the Wizard step shows "N tools discovered" only, not individual names. Backend `/mcp-servers/{id}/test` returns `tool_count` but not the list. Adding a `/mcp-servers/{id}/tools` endpoint + rendering the names is straightforward but out of scope for the RC.
- **Workaround:** Settings → MCP Servers → [Test] surfaces the count too; users can also try a tool from the chat and see what the agent picks.
- **Target:** M2 Month 2.

### F3. Reactive `mcp_tools` capability badge on the Capabilities step
- **Where deferred:** `M2_MCP_UI_PHASE_1_4_IMPL.md` §4 (mentor ruling 3)
- **What's missing:** if the user picks MCP servers in step 5 and then navigates back to step 3 (Capabilities), `mcp_tools` is silently injected into the YAML at save time but does not appear checked in the step 3 UI. Mild UI surprise, no functional impact.
- **Workaround:** the silent-add note on the MCP Tools step explains it.
- **Target:** post-pilot polish pass.

### F4. Frontend test harness (Vitest + RTL)
- **Where deferred:** `M2_MCP_UI_PHASE_1_3_IMPL.md` §11 (mentor approved as project baseline)
- **What's missing:** the dialekt frontend has zero unit tests project-wide. The RC does not change that baseline. Regression catcher for the MCP UI is the deferred Phase 2.1 real-server E2E.
- **Target:** separate track. Should land before the frontend surface doubles in the next phase.

### F5. Deep-link from Wizard MCP Tools empty state to Settings
- **Where deferred:** `M2_MCP_UI_PHASE_1_4_IMPL.md` §2
- **What's missing:** when no MCP servers are configured yet, the Wizard step shows plain copy ("Open Settings → MCP Servers to add one") instead of a clickable button — `onNav` isn't currently passed to step components. Two-line fix once the prop wiring exists.
- **Target:** opportunistic with any other Wizard prop refactor.

### F6. `FInput` defined inside the section component
- **Where deferred:** mentor commit-1.3 review P2
- **What's missing:** `FInput` is a closure inside `MCPSection` (and `ConnectionsSection`); React unmounts and re-mounts inputs on every parent render, which can drop focus mid-edit. Project baseline pattern, not introduced by the RC; flagged for a sweep across both sections together.
- **Target:** "Settings form ergonomics" hardening commit.

### F7. Status-dot title hover on agent rows for failed `last_test_*`
- **Where deferred:** mentor commit-1.3 review P2
- **What's missing:** the LeftPanel agent indicator surfaces `mcp_server_names`; the Settings page row's red status dot doesn't surface `last_test_error` on hover (the line below does, but the dot itself doesn't).
- **Target:** opportunistic.

---

## Backend

### B1. Custom HTTP headers on HTTP transport
- **Where deferred:** `docs/M2_MCP_UI_DESIGN.md` §10
- **What's missing:** `HttpTransportSpec` ships with `auth: {type: "bearer", token}` only. Servers requiring AWS SigV4 / vendor-specific headers are out of scope for the RC. Bearer covers ~95% of public MCP servers.
- **Target:** when a pilot brings a concrete server that requires it; will need its own mentor-approved transport-spec extension.

### B2. Per-user (vs per-tenant) credential overrides
- **Where deferred:** `docs/M2_MCP_UI_DESIGN.md` §10 (mentor ruling 2 on Phase 1.1)
- **What's missing:** v0.20.0 stores credentials at the tenant scope (single set of secrets shared by all seats of one license). Per-user GITHUB_TOKEN / Slack token would require a real ownership/visibility/cascade-delete permission model — its own design doc.
- **Target:** M2 Month 2 / M3.

### B3. Orphan keyring entries on PATCH
- **Where deferred:** mentor commit-B review P2
- **What's missing:** dropping an entry from `env_refs` via PATCH leaves a stale secret in the keyring under the old ref name. Same for `auth_ref` rotation. Harmless (never read), but messy. A future "Credentials inspector" UI can double as garbage collector.
- **Target:** when the inspector lands.

### B4. Stale `command_json` / `cwd` on transport switch
- **Where deferred:** mentor commit-1.3 review P2
- **What's missing:** PATCH that flips `transport: stdio → http` keeps the old `command_json` populated in the row. The `/test` endpoint branches on `transport` so stale fields are inert, but the row is messy. Either null sibling fields server-side on transport switch, or have the frontend explicitly null them.
- **Target:** opportunistic with any other CRUD hardening.

### B5. Argument-redaction in consent modal
- **Where deferred:** `docs/M2_MCP_UI_DESIGN.md` §6 INFO + Phase 1.5 plan §5 (mentor ruling 5)
- **What's missing:** `ConsentRequest.arguments` is forwarded untouched into the WS frame. By design — the modal must show what's about to be sent so the user can vet it. If a tool's argument schema knows which fields are sensitive (a future MCP enhancement), redaction can plug in there.
- **Target:** when MCP argument schemas land upstream.

### B6. /audit/log audit-row consumer view for MCP events
- **Where deferred:** out of scope for the RC.
- **Status:** Closed in **v0.25** by `MCPAuditDashboard` mounted under Settings → Admin → Usage tab (mentor-approved 2026-04-25 after 3 design passes; backend `GET /audit/log` shipped commit 1/2 PR #17, frontend tab shipped commit 2/2).

### B7. Auth on `/audit/log` (both directions) before cloud / multi-user
- **Where deferred:** v0.25 audit dashboard mentor pass 1 ruling.
- **What's missing:** both `POST /audit/log` (write side, shipped M2 Month 1) and `GET /audit/log` (read side, shipped v0.25) are unauthenticated. Acceptable today because the desktop is single-user, binds to localhost, and the dashboard only views local data. The moment dialekt-cloud or any multi-user surface starts proxying audit reads/writes, both endpoints need a real auth check (bearer token, license-key bind, or session token — to be designed alongside the cloud admin surface).
- **Target:** before any non-localhost deployment of `dialekt-cloud` proxies `/audit/log`. Tracked here so it cannot be silently shipped without a corresponding auth layer.

---

## Validation

### V1. Real-server E2E pass (GitHub MCP, Slack MCP)
- **Where deferred:** `docs/AGENT_CATALOG.md` Category 5.5 "Pre-pilot validation pass — DEFERRED"
- **What's pending:** every Category 5.5 entry is labeled ⚠️ until live `@modelcontextprotocol/server-github` (with a real PAT) and a maintained Slack MCP have been driven end-to-end through Settings → Wizard → Chat → consent prompt → audit row. Slack 5.5.2 specifically may downgrade to "Coming later" if no maintained server passes the [Test] gate.
- **Target file:** `docs/MCP_PRODUCTION_VALIDATION.md` (to be created in the validation commit).
- **Target:** within 7 days post-merge (if shipped as RC) or before merge (if shipped as v0.20.0 without -rc).

---

## Operational

### O1. Multi-worker uvicorn support
- **Where deferred:** comment on `_pending_consents` + `_active_mcp_runtimes` in `server.py`
- **What's missing:** both registries are process-local. Running uvicorn with `--workers 2+` would silently break consent + tool dispatch (request_id known to one worker, response landing on another). Desktop is single-process, so this is a documentation-only constraint.
- **Target:** if dialekt-cloud ever fronts multi-worker for MCP, the registries need a Redis-backed substrate.

---

## Change log

- `2026-04-25 v1` — initial roll-up after mentor pre-release review
  flagged a dangling "post-1.6 hardening backlog" reference in
  `AGENT_CATALOG.md`. This file is the single resolution.
