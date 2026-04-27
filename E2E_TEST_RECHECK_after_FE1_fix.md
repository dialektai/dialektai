# E2E Re-check — after FE1 fix

Date: 2026-04-23
Follow-up to `E2E_TEST_FINDINGS.md` after `setuptools<81` pin unblocked the WebSocket chat flow. Re-tested items that were marked ❓ CANNOT TEST in the first pass.

Environment: vite dev server, Chrome MCP, `server.py` running with `setuptools 80.10.2`. Fresh state (`~/.dialekt` wiped before onboarding).

## Summary

| Section | Pass | Partial | Broken | N/A |
|---|---|---|---|---|
| 2 (Chat) | 3 | 1 | 3 | 0 |
| 4 (SQL Analyst) | 0 | 2 | 5 | 0 |
| 6 (Schema RAG) | 2 (API) | 0 | 2 (UI) | 0 |

**Top new findings:**
1. **❌ SQL Analyst agent does not follow its system prompt.** Even when bound to a working PostgreSQL connection via `/agents/{id}/binding`, the agent generates `sqlite3 /home/dias/database.db ...` / `mysql -e ...` shell commands instead of calling dialekt's `/connections/{id}/query` HTTP endpoint that its own system_prompt explicitly documents. The Open Interpreter default prompt appears to dominate the agent-level prompt. No SQL result table ever renders. **This kills the SQL Analyst investor demo.**
2. **❌ No UI to bind an existing agent to a connection.** The Builder Wizard has a connection picker for *new* agents, but pre-seeded agents (SQL Analyst, General Assistant) have no bind UI on the main chat screen. Must go through API `POST /agents/{id}/binding` manually.
3. **❌ Message context menu actions are mostly stubs.** Right-click opens a rich menu (Regenerate, Continue from here, Make more concise, Explain step-by-step, Branch conversation, Delete message) but all of these have `action: onClose` — they only dismiss the menu, doing nothing. Only Copy / Copy-as-markdown / Save-to-file actually work.
4. **⚠️ Session delete lacks confirmation.** Sidebar `×` button removes the session immediately. Test plan expected a confirmation prompt.

---

## Section 2 — Main chat (re-tested)

| # | Status | Notes |
|---|---|---|
| 2.5 | ✅ WORKS | Sent "Расскажи мне короткую историю про дракона" → `STREAM` indicator appeared, "exec · thinking · Processing…" in right panel, text streamed in. Agent Activity shows per-step progress. LLM (gemma3-12b) returned a Zephyr dragon story in English. |
| 2.6 | ✅ WORKS | Right-click → "Copy message" / "Copy as markdown" / "Save to file…" all wired to `navigator.clipboard.writeText()` (ChatColumn.jsx:439-452). Clipboard write doesn't prompt permission. Save to file triggers a Blob download. |
| 2.7 | ❌ **BROKEN** | Right-click → Regenerate does **nothing**. Source (`ChatColumn.jsx:456`): `{ icon: 'refresh', label: 'Regenerate', kbd: '⌘R', action: onClose }` — the action is literally just `onClose`. **Stub.** Same applies to: Continue from here, Make more concise, Explain step-by-step, Branch conversation, Delete message (all `action: onClose`). |
| 2.8 | ⚠️ PARTIAL | Session delete via sidebar `×` works — session gone, returns to empty state, backend removes it. BUT no confirmation dialog (test plan required one). Losing an active chat takes one click. |
| 2.9 | ✅ WORKS | Empty state after delete shows "What are we working on?" hero with shortcuts `⌘N new · ⌘K palette` + 4 quick-action templates (Debug this trace, Audit the repo, Explain a file, Research + summarize). Clicking SQL Analyst in sidebar starts a new session. |

## Section 4 — SQL Analyst agent

Setup for this pass: created `e2e_sqldemo` DB on host PostgreSQL with `customers` (5 rows) + `orders` (10 rows, foreign key to customers). Registered it as dialekt connection `E2E Demo`. Test connection: `{"ok":true,"version":"PostgreSQL 17.8"}`. Bound SQL Analyst to it via `POST /agents/{id}/binding`.

| # | Status | Notes |
|---|---|---|
| 4.1 | ✅ WORKS | Click SQL Analyst in sidebar → highlights "active", new session starts |
| 4.2 | ❌ **NO UI** | No connection-picker UI for existing agents on main chat screen. Binding exists only as a backend API (`POST /agents/{id}/binding`) — can't be set from the app. Builder Wizard has it only for *new* agents. |
| 4.3 | ❌ **BROKEN** | Even with binding active (`agent_bindings.connection_id` set, `resolve_agent_context` returning real IDs, `substitute_template_vars` replacing `{{connection_id}}`), the LLM ignored the system prompt's instruction to use `POST /connections/{CONN}/query` and instead wrote: `sqlite3 /home/dias/database.db "SELECT COUNT(*) FROM orders;"`. Shell returned "sqlite3: команда не найдена". Agent then tried `sudo apt-get install sqlite3`. Previous attempt (no binding) generated `mysql -e "SHOW TABLES;"`. The Open Interpreter wrapper around the agent prompt appears to dominate — model treats this as a generic computer-use task. |
| 4.5 | ❌ CANNOT TEST | Depends on 4.3. Never got to a JOIN query. |
| 4.6 | ⚠️ PARTIAL EVIDENCE | `dialekt.postgres` retry loop firing visible in server log (`🔄 SQL retry attempt 2/3`, `🔄 SQL retry attempt 3/3`, `[retry_loop] Attempt 1 failed: <empty error>`). So the retry mechanism IS wired. But because the agent never goes through the `/connections/{id}/query` path, the retry loop isn't exercised from the UI flow — only from direct API calls with invalid SQL. Also: retry loop errors are empty strings in logs, which hurts diagnostics. |
| 4.7 | ❌ NOT TRIGGERED | No SQL result table component ever rendered because no query reached the backend via the SQL Analyst flow. |

## Section 6 — Schema RAG

| # | Status | Notes |
|---|---|---|
| 6.3 (API) | ✅ WORKS | `POST /connections/{id}/reindex` → `{"ok":true,"indexed":2,"skipped":0}`. `GET /connections/{id}/search?q=orders` returns `[{"schema":"public","table":"orders","score":0.6586}, {"schema":"public","table":"customers","score":0.538}]`. nomic-embed-text:v1.5 embeddings work correctly. |
| 6.4 (API) | ✅ WORKS | `GET /connections/{id}/schemas/public/tables/orders/describe` works (verified via agent's own documented endpoint list). Column metadata is exposed correctly. |
| 6.3 (via agent) | ❌ BROKEN | Same root cause as §4.3. Agent asks for `sqlite3` or `mysql`, never calls `/connections/{id}/schemas` or `/search`. |
| 6.4 (via agent) | ❌ BROKEN | Same. Agent never reached schema lookup. |

---

## What's fixed since the first report

| From initial report | Now |
|---|---|
| ❌ Chat Send button permanently dead (code 1006) | ✅ Chat works end-to-end after `setuptools<81` pin |
| `connected` state never true in React | ✅ WS stable, indicator green, session persists |
| Sessions list refresh after send | ✅ Works (new session appears after first reply) |

---

## Evidence

- Screenshots captured via Chrome MCP (session screenshots during dragon story stream, right-click context menu, SQL Analyst using `sqlite3 /home/dias/database.db`, SQL Analyst using `mysql -e`, empty state after session delete).
- Source refs: context-menu stubs at `frontend/src/components/ChatColumn.jsx:456-466`. Retry loop at `python/dialekt/postgres.py` (log tag `dialekt.postgres:🔄`).
- API verification:
  - `POST /agents/{id}/binding` returns `{"ok":true,"connection_id":...}` — binding persists in `agent_bindings` table.
  - `GET /agents/{id}/binding` confirms post-bind state.
  - Search after reindex returns scored results — RAG pipeline healthy.

---

## Recommended fix order (for next prompts)

1. **Agent execution path.** Make the LLM actually use the documented HTTP API instead of shell. Options: (a) wrap the agent prompt so OI's generic computer-use system prompt is suppressed, (b) add a dialekt-specific code executor that intercepts SQL and routes to `/connections/{id}/query` automatically, (c) fine-tune / few-shot the SQL Analyst prompt with explicit Python `httpx` examples so the model doesn't default to shell. This is *the* unblocker for the SQL demo.
2. **Agent ↔ Connection binding UI.** When user selects an agent that has `connections.required` in its manifest and no binding exists, show a picker modal: "Pick a connection for SQL Analyst" with existing connections + create-new option. Should also show current binding somewhere (agent detail pane, top of chat).
3. **Wire up the stub menu actions.** Either delete them from the menu entirely or implement them. Regenerate and Delete are the most user-visible; others can ship later.
4. **Session delete confirmation.** Single-click delete with no undo is an easy way to lose work.
5. **Retry-loop error copy.** Logs show `Attempt 1 failed: <empty>` — the error payload isn't being serialized. Makes diagnosis harder.

---

_End of re-check. ~30 minutes._
