# dialekt Capabilities Status — 2026-04-23

Per-capability runtime status. Paired with `docs/CAPABILITIES_INVENTORY.md` (broader map) but focused on **what works vs what's broken** and **what it would take to fix**.

Tested by: grep in `python/server.py`, `python/mcp_servers/*`, `python/dialekt/llm/*`, `frontend/src/screens/AgentWizardScreen.jsx`, live validator round-trip (`dialekt_manifest.ManifestValidator`), and the SQL Analyst end-to-end demo verified earlier today.

---

## 1. Builder Wizard Step 4 — capability checkboxes

UI shows 6 checkboxes (`AgentWizardScreen.jsx:409-415`). When ticked, the key is pushed into `manifest.capabilities.groups` at save time.

Two failure modes possible: **(a) schema invalid** — the manifest fails validation on publish, or **(b) schema valid but no runtime enforcement** — it writes metadata that nothing reads.

Validated by posting a stub manifest with each single capability group against `dialekt_manifest.ManifestValidator.validate_string()`.

| # | Checkbox label (UI) | Emitted group name | Schema valid? | Runtime enforcement? | Underlying OI capability actually works? | Net status |
|---|---|---|---|---|---|---|
| 1 | Filesystem | `filesystem_read` ✅ (was `filesystem` — **F1 applied**) | ✅ | ❌ Metadata only | ✅ Agents can read/write via OI Python+shell regardless | ⚠️ **MISLEADING** (publish works, check does nothing) |
| 2 | Network | `network` | ✅ | ❌ Metadata only | ✅ Agents call any URL via Python httpx regardless | ⚠️ **MISLEADING** (publish works, check does nothing) |
| 3 | Browser | `browser` | ✅ | ❌ Metadata only | ❓ `interpreter.computer.browser` exists (Selenium); **untested on this Linux server**, OS deps unclear | ⚠️ **MISLEADING + UNVERIFIED** |
| 4 | Database Read | `database_read` | ✅ | ❌ Metadata only — DialektSQL executes regardless of this flag. The *actual* DB gate is the per-agent `agent_bindings` row. | ✅ via DialektSQL + Schema RAG (E2E verified) | ⚠️ **MISLEADING** (works, but not because of the check) |
| 5 | Terminal | `shell_execute` ✅ (was `terminal` — **F1 applied**) | ✅ | ❌ Metadata only | ✅ Agents run shell via OI regardless | ⚠️ **MISLEADING** (publish works, check does nothing) |
| 6 | Screen | `screen_capture` ✅ (was `screen` — **F1 applied**) | ✅ | ❌ Metadata only | ❓ `interpreter.computer.display` exists; untested on this Linux server | ⚠️ **MISLEADING + UNVERIFIED** |

**F1 fix applied (v0.21+):** The 3 broken checkboxes (Filesystem/Terminal/Screen) now emit valid group names `filesystem_read`, `shell_execute`, `screen_capture`. Verified in `test_wizard_capability_names.py` (part of 846-test passing suite).

**Summary (post-F1):** 0 of 6 checkboxes are hard-broken (all publish). 6 of 6 emit schema-valid names. 0 of 6 provide a runtime security boundary. Zero checkboxes provide the security guarantee the UI copy (*"Grant permissions — select what this agent is allowed to do"*) promises.

Valid group names accepted by schema (`schema.py:11`):
`filesystem_read, filesystem_write, database_read, database_write, shell_execute, network, browser, screen_capture`.

---

## 2. MCP servers (`python/mcp_servers/`)

| Server | Auto-loaded at startup? | Endpoints reachable? | Usable via UI? | Status |
|---|---|---|---|---|
| `postgres_mcp` → `/connections` | ✅ `server.py:324 app.include_router(pg_router)` | ✅ (SQL Analyst demo today) | ✅ Settings → Connections UI supports it | ✅ **WORKS** |
| `mysql_mcp` → `/mysql-connections` | ✅ `server.py:325 app.include_router(mysql_router)` | ✅ GET `/mysql-connections` returns `[]` cleanly on a fresh install | ⚠️ New connection form is PostgreSQL-only — no driver selector. MySQL connections can only be created via API. | ⚠️ **PARTIAL** — backend works, UI doesn't let you create one |
| `clickhouse_mcp` → `/ch-connections` | ✅ `server.py:326 app.include_router(ch_router)` | ✅ | ⚠️ Same as MySQL — API-only creation | ⚠️ **PARTIAL** — backend works, UI can't create one |
| `schema_rag` (helper module, not router) | ✅ used by all three SQL routers | ✅ (`/reindex` + `/search` verified earlier today) | ✅ Indirectly, via SQL Analyst | ✅ **WORKS** |

**Gap:** MySQL / ClickHouse are visible in the UI (existing connections render) but new ones can only be added through the API. Wizard Step 5 *does* show MySQL / ClickHouse in the "Connection Type" dropdown, but there's no "Add MySQL connection" form on Settings → Connections.

---

## 3. Language plugins

| Plugin | Registered in OI? | Works end-to-end? | Status |
|---|---|---|---|
| **DialektSQL** (`dialekt/llm/sql_language.py`) | ✅ `make_interpreter` prepends it to `interpreter.computer.terminal.languages` when invoked | ✅ E2E verified today (SQL Analyst on qwen2.5-coder:7b emits sql block → backend executes → 10 rows returned) | ✅ **WORKS** |
| OI native: `python` | ✅ default | ✅ (used implicitly by every agent) | ✅ **WORKS** |
| OI native: `shell` / `bash` / `sh` | ✅ default | ✅ (seen in earlier E2E — `sqlite3` attempt, `apt-get install` attempt) | ✅ **WORKS** |
| OI native: `javascript` | ✅ default | ❓ untested | ❓ UNVERIFIED |
| OI native: `applescript, html, java, jupyter_language, powershell, react, ruby, r` | ✅ defaults | ❓ none exercised | ❓ UNVERIFIED (likely OS-dependent) |

---

## 4. Verdict by capability surface

| Surface | What works right now | What's broken / misleading |
|---|---|---|
| Agent manifests, schema | Identity, model, system_prompt, autonomy, interactive trigger, connections (postgres/mysql/ch), streaming output | Scheduled trigger (no scheduler); webhook (not in schema); mcp-server + http-api connection types (no backend); variables beyond `{{connection_id}}`; output destinations other than `notification` |
| Per-agent model routing | `pick_model_for_agent` (exact → acceptable → family match → default) | — |
| Agent ↔ connection binding | DB table + API + Wizard Step 5 + Settings → Agents UI + Chat empty-state nudge | — |
| SQL execution | DialektSQL on Postgres (E2E verified) | MySQL/ClickHouse same code path, not E2E verified; recursive-validate bug in `retry_loop` worked around via `retry: false` |
| Capabilities checkboxes | — | **3 of 6 publish-breaking** (filesystem, terminal, screen emit schema-invalid group names). Other 3 (network, browser, database_read) publish but enforce nothing. |
| MCP servers | Postgres fully wired UI+backend | MySQL/ClickHouse backends wired, **no UI to add a new connection** |
| OI native languages | python, shell | js/applescript/etc all untested on this machine |
| OI native `computer.*` API (browser, mail, display, clipboard, …) | — | Exists via OI; untested on this Linux server; may need OS-level deps (Selenium, xdotool) |

---

## 5. Proposed fixes, in order of effort

All fixes follow the rule: **fix, don't delete.** Keep the surfaces the UI promises; make them real (or at least honest).

### Small (~30 min each) — low-risk

- **F1. Wizard capability name mapping.** ✅ **DONE (v0.21+)** — `filesystem → filesystem_read`, `terminal → shell_execute`, `screen → screen_capture` — applied in `AgentWizardScreen.jsx`. Verified by `test_wizard_capability_names.py` in the 846-test passing suite.
- **F2. Settings → Connections: add MySQL + ClickHouse "Add connection" forms.** Backend endpoints exist; UI currently only exposes PostgreSQL form. Clone the form component, swap the endpoint and default port, add a driver dropdown at the top of the "Add connection" card so all three are creatable from one place. Matches the wizard's own drop-down (postgres / mysql / clickhouse).
  - Files: `frontend/src/screens/SettingsScreen.jsx` (ConnectionsSection) only.
  - Risk: low — purely additive UI.

### Medium (~1-2 hours) — needs product decision

- **F3. Runtime enforcement for `capabilities.groups`.** In `make_interpreter`, read the parsed manifest's capability set and optionally strip `shell` language from `interpreter.computer.terminal.languages` when `shell_execute` is not declared, etc. Then the checkboxes start to *do* something. The open question is: do you *want* a checkbox unticked to mean the model cannot shell out? If yes — do this. If no — drop the idea and keep the declarative-only model (document it clearly). **Needs your call before I code.** Cost is ~1.5 hours plus a careful pass to avoid breaking existing General Assistant / SQL Analyst (we'd have to make sure their manifests actually list the groups they use — SQL Analyst lists `database_read, network`, which is enough for its path).
- **F4. Verify MySQL / ClickHouse E2E via a real agent.** Create a throwaway MySQL instance, register it, bind it to a clone of SQL Analyst, ask a question, confirm DialektSQL routes correctly (should "just work" since the language plugin is DB-agnostic — only the backend `/query` endpoint differs per type). Same for ClickHouse. No code change expected; if something fails, a targeted fix in `DialektSQL._execute` route selection.

### Large (>2 hours) — flag for user decision

- **F5. Scheduled trigger runtime.** ✅ **DONE (v0.27)** — APScheduler runtime in `dialekt.scheduler` (runner, cron_session, missed_run_policy, delivery). Telegram delivery wired. 21/21 tests passing. Email delivery is v0.28.
- **F6. Webhook trigger.** Not in schema. Adding it means a schema bump + backend listener + secret rotation UI. Same "not now" call.
- **F7. OI `computer.*` API verification.** Each sub-module (browser / mail / display / clipboard / vision) needs OS-level deps and a test. Per-item cost ~30 min to verify. Easiest one: `computer.files` (pure Python, no selenium). Hardest: `computer.browser` (Selenium on Linux, needs chromedriver). Recommend: verify `computer.files` only for now, document the rest as "OS-dependent, not tested".

### Micro (15 min each)

- **M1. Recursive validate-loop in `retry_loop.py`.** `validate_sql` POSTs to `/connections/{id}/query` with `EXPLAIN sql` but doesn't set `retry: false`, which re-enters `_retry_fix_sql` and loops. The DialektSQL fix (from earlier today) works around it by always passing `retry: false`. Fix at the source so direct API callers aren't affected: add `"retry": False` to the httpx payload in `retry_loop.py:41`.
- **M2. Wizard Step 4 header copy.** "Grant permissions — select what this agent is allowed to do" overpromises. Even after F1 + F3, the copy will still be stronger than reality. Soften to "Declare what this agent uses" or similar after F3 decision lands.

---

## 6. Recommended order (if you want me to proceed)

1. **F1** ✅ DONE — Wizard naming fix applied.
2. **F5** ✅ DONE — Scheduled trigger runtime ships in v0.27.
3. **M1** — Retry-loop recursion fix. ~15 min. Removes a lurking footgun.
4. **F2** — MySQL / ClickHouse Add-connection UI. ~30-45 min. Unlocks two capabilities that backend already supports.
5. **F4** — Verify MySQL / ClickHouse E2E on a real agent. ~30 min.
6. **F3** — Runtime enforcement for capability groups. **Pause here for your decision** — do we want capabilities to actually gate, or to stay declarative? The answer shapes the rest.
7. F6/F7 — not before pilots.

Remaining for M1 + F2 + F4 = **~1.25 hours**, all low-risk, all additive or trivial.

---

*Not a roadmap — a snapshot. Rerun this status doc after every fix batch.*
