# M2 Этап 2.5 — Phase 1.4 implementation plan: Builder Wizard "MCP Tools" step

**Scope:** insert a new "MCP Tools" step in `AgentWizardScreen.jsx`
between `Capabilities` (step 3) and `Connections` (step 4). Users
pick from MCP servers registered in Settings; selection populates an
`mcp_servers:` block in the generated manifest and silently adds the
`mcp_tools` capability.

**Related:**
- Product design — `docs/M2_MCP_UI_DESIGN.md` §3 (mentor-approved)
- Phase 1.3 backend contract (`GET /mcp-servers` returns list incl.
  `has_auth_token`, `last_test_ok`, `tool_count`, `transport`)
- Existing wizard state + `buildManifestYaml` in
  `frontend/src/screens/AgentWizardScreen.jsx`

---

## 1. File scope

Single file: `frontend/src/screens/AgentWizardScreen.jsx`.

Changes:
- `STEPS` array: insert `{ label: 'MCP Tools', icon: 'plug' }` at
  index 4. (`plug` icon — verify it exists in `Icon.jsx`; fall back
  to `cog` if not.)
- `data` default state: add `mcp_server_names: []` (array of strings).
- Add `StepMcpServers({ data, setData })` component function.
- `renderStep` switch: insert case 4 for the new step; renumber
  cases 4→5, 5→6, 6→7, 7→8, 8→9.
- `buildManifestYaml(data)`:
  - If `data.mcp_server_names.length > 0`:
    - Append `mcp_servers:` block with an entry per selected server
      (fetched via `GET /mcp-servers` at save time — see §3 below).
    - Ensure `mcp_tools` is in `capabilities.groups` (silent add, no
      prompt, per mentor design doc ruling).
    - Bump `spec_version: "1.1.0"` and `minimum_dialekt_version:
      "0.20.0"`.
  - Else: unchanged (stays at `spec_version: "1.0.1"`).
- `validate(stepIdx)`: no new validation for the MCP step (empty
  selection is valid — design doc §3.2 "Skip this step").

---

## 2. Component: `StepMcpServers`

UI responsibilities:
- Fetch `/mcp-servers` on mount (useEffect).
- Render one row per server with a checkbox, status dot (from
  `last_test_ok` / `has_auth_token`), transport summary, tool count.
- Disable the checkbox if `last_test_ok === false` or `null`
  (untested) — show an inline `[Test first]` button that POSTs to
  `/mcp-servers/{id}/test` and refetches.
- Expanded tool list on `▸ Preview`: fetches `/mcp-servers/{id}/test`
  lazily (reuses the endpoint — it returns `tool_count` only; for
  full tool names we need a new `/mcp-servers/{id}/tools` endpoint).

**Scope trim:** `Preview ▾` showing individual tool names is
**deferred** — backend's current `/test` returns only `tool_count`,
not the tool list. Adding `/mcp-servers/{id}/tools` is Phase 1.6
territory or a Phase 1.4 sub-commit. My lean: defer to post-1.6
hardening, ship this step with "N tools discovered" summary only.
Design doc §3.2 mentions Preview but acknowledges the server-has-to-
be-listable fetch — calling this a matched deferral with Phase 1.3
skeleton deferral pattern.

- Empty state: `No MCP servers configured. Open Settings → MCP
  Servers to add one.` with a link that fires `onNav('settings')`
  — but `onNav` isn't currently passed to step components. Fix:
  read from `useContext` if available, or just render plain copy
  (non-clickable), since users already know where Settings live.
  Defer the deep link to hardening.
- Silent capability notice at the top of the step: `[i] Selecting
  any server here will add the 'mcp_tools' capability automatically.`

---

## 3. Manifest generation

Two options for how to embed `mcp_servers:` in the YAML:

**(A) By-name-only** — list just `name:` entries, assume the desktop
runtime will resolve each name against its local `mcp_servers` SQLite
row at load time.

**(B) Inline full transport spec** — emit `command`, `env`, `url`,
`timeout_seconds`, `${secrets.<ref>}` references. Portable across
machines as long as the keyring has the same refs.

Product design doc §3.3 item 1 explicitly chose **(B)** — manifests
are the portable unit; agents shared between machines should
reconstruct the server config without access to the source tenant's
SQLite. Implementation in `buildManifestYaml`:

1. At save time (inside `onSave`), issue a `GET /mcp-servers` and
   filter to the names in `data.mcp_server_names`. This gives us
   the full server config for YAML emission.
2. For each selected server, emit:
   ```yaml
   mcp_servers:
     - name: <name>
       transport: <stdio|http>
       command: [...]          # stdio only
       env:
         <ENV_NAME>: "${secrets.<ref_name>}"   # one line per env_refs entry
       cwd: <cwd>              # omitted if null
       url: <url>              # http only
       auth:
         type: bearer           # http only, when has_auth_token
         token: "${secrets.<auth_ref>}"
       timeout_seconds: <n>
   ```
3. `env_refs` is a `{env_name: ref_name}` dict on the server row; the
   YAML `env` block maps env_name → `${secrets.<ref_name>}`
   interpolation tokens. This matches the Этап 1 resolver (one-
   segment `secrets.<name>`), relying on the per-entry `name:` field
   to disambiguate.

**Alternative considered (and rejected):** emit YAML at wizard-step
save time, keep a stashed copy in `data.mcp_servers_yaml_snapshot`.
Cleaner state model but creates a staleness bug if the user edits
the server config in Settings between wizard steps. Resolving fresh
at save time is correct.

---

## 4. Capability auto-add logic

Inside `buildManifestYaml`, before computing `enabledCaps`:

```js
if (data.mcp_server_names && data.mcp_server_names.length > 0) {
  data = { ...data, capabilities: { ...data.capabilities, mcp_tools: true } };
}
```

This is a **read-only shim** — we do not mutate the React `data`
state. The capability flag is injected only into the YAML. Rationale:
mutating React state from a serializer would be a surprising side
effect; the UI's capabilities step shows what the user explicitly
selected, not what MCP added behind the scenes.

Trade-off: if the user goes back to the Capabilities step after
selecting MCP servers, `mcp_tools` won't show as checked. Acceptable
for v0.20.0 (user sees the passive note on the MCP step) — noted in
post-1.6 hardening as candidate for a reactive badge.

---

## 5. `spec_version` bump logic

```js
const hasMcp = (data.mcp_server_names || []).length > 0;
const specVersion = hasMcp ? '1.1.0' : '1.0.1';
const minVersion  = hasMcp ? '0.20.0' : '1.0.0';
```

Rationale: agents that use MCP require the MCP runtime shipped in
v0.20.0. Non-MCP agents stay back-compat with 1.0.x dialekt
installs. Schema validator accepts both `spec_version` values.

---

## 6. Validation and navigation

- `validate(4)` returns empty `errs` — empty selection is valid.
- `Next` button on the MCP step always enabled.
- Back/forward navigation preserves `mcp_server_names` as part of
  `data`, same as every other step.

---

## 7. Error states

| Condition                         | Render                                                |
|-----------------------------------|-------------------------------------------------------|
| Fetch `/mcp-servers` fails        | Inline error + `[Retry]` button                        |
| Server list empty                 | Empty-state copy (described above)                    |
| Selected server in state no longer exists (deleted in Settings) | Silently drop from `data.mcp_server_names` on fetch; no warning (low-likelihood race) |
| `last_test_ok !== true`           | Checkbox disabled + inline `[Test first]` button      |

---

## 8. Line-budget ceiling

Target: ~150-250 added lines total (step component + generator
changes + renderStep switch renumber).

If I hit 300 lines, pause and re-invoke mentor — wizard is one file,
and exceeding that threshold suggests the step body is growing
beyond a simple checklist.

---

## 9. Commit plan

Single commit: `feat(frontend/wizard): MCP Tools step for agent builder`.

Follow-up (post-1.6 hardening pass):
- `Preview ▾` full tool list (requires `/mcp-servers/{id}/tools`
  endpoint).
- Reactive `mcp_tools` capability badge on the Capabilities step.
- Deep-link to Settings → MCP Servers from the empty state.

---

## 10. Known deferrals

- Per-tool `allow_tools` / `deny_tools` scoping — design doc §10,
  deferred to M2 Month 2.
- Preview tool list beyond count — this commit, deferred to
  post-1.6.
- Navigation helper (onNav) from step component — this commit,
  deferred to post-1.6.

---

## 11. Change log

- `2026-04-24 v1` — initial plan (Claude Code, pending mentor review).
