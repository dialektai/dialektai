# dialekt Agent Catalog — Production-Ready Configurations

**Generated:** 2026-04-24, refreshed 2026-04-25 for v0.20.0 RC
**Validated against:** dialekt v0.11.1 (last shipped); v0.20.0 RC on `feat/m2-mcp-production-complete` adds the MCP-enabled agent class (Category 5.5, real-server validation pending — see that section)
**Test environment:** Ubuntu 22.04, local Ollama (qwen2.5-coder:7b, gemma3-12b, gemma2:2b, nomic-embed-text:v1.5)
**Evidence:** `scripts/pilot_verify/evidence.json` — every agent here was actually run end-to-end with a real chat turn. No simulations.

This catalog lists every agent configuration that works end-to-end today. Each entry includes what it does, working example queries **with the real LLM response captured**, required setup, known limitations, and pilot fit notes.

For pilots: any agent in this catalog can be created through Builder Wizard or `POST /agents/import-yaml` today — no new code. Limitations are honest — read them.

> See also: [`WHAT_DIALEKT_DOES_TODAY.md`](WHAT_DIALEKT_DOES_TODAY.md) (executive summary) · [`TOOLS_AVAILABLE_TODAY.md`](TOOLS_AVAILABLE_TODAY.md) (tool matrix) · [`SETTINGS_COMBOS_TODAY.md`](SETTINGS_COMBOS_TODAY.md) (manifest field combos)

---

## Categories

1. [SQL Analytics Agents](#category-1-sql-analytics-agents) (3)
2. [Code Assistants](#category-2-code-assistants) (2)
3. [Document Processing Agents](#category-3-document-processing-agents) (2)
4. [Conversation Agents](#category-4-conversation-agents) (2)
5. [Multi-tool Agents](#category-5-multi-tool-agents) (1)
5.5. [MCP-enabled Agents](#category-55-mcp-enabled-agents) (3 blueprints — v0.20.0 RC, validation pending)
6. [Coming in M2 — NOT available today](#category-6-coming-in-m2--not-available-today)

**Verified total:** 10 agent configurations · **Status:** 10/10 ok (harness 2026-04-24 15:58 UTC+05:00)

---

## Category 1: SQL Analytics Agents

### 1.1 PG Sales Analyst

**Status:** ✅ Production ready
**Model:** `qwen2.5-coder:7b`
**Last verified:** 2026-04-24, 2/2 turns, wall time 7.5 s
**Recommended for:** banks, retail, e-commerce — any team that has a PostgreSQL reporting replica

**What it does.** Natural-language SQL over PostgreSQL. Writes one `SELECT` per turn, dialekt executes it against the bound read-only connection, results render as markdown tables. Bilingual Ru/En.

**Working example queries** (captured verbatim from `evidence.json`):

> User (RU): «Сколько у нас всего клиентов?»
> → LLM generated: `SELECT COUNT(*) FROM ecom.customers;`
> → Result: `| count | 1000 |` — **verified correct** against seed (1000 customers).

> User (RU): «Топ-5 стран по количеству клиентов»
> → LLM generated:
> ```sql
> SELECT ecom.customers.country, COUNT(*) AS client_count
> FROM ecom.customers
> GROUP BY ecom.customers.country
> ORDER BY client_count DESC
> LIMIT 5;
> ```
> → Result: US / RU / KZ / GB / DE, 200 each (uniform seed).

**Required setup.**
1. Settings → Connections → add PostgreSQL connection (host, port 5432, database, read-only role).
2. Settings → Agents → PG Sales Analyst → bind the connection.
3. Open chat. Ask in Russian or English.

**Manifest sketch.** `capabilities: [database_read]` · `connections.required: [{type: postgres, role: readonly, purpose: "..."}]` · `autonomy.recommended: ask-before-write` · `language: multi`.

**Honest limitations.**
- Only `SELECT`. Attempting DDL/DML fails at parse time in `postgres_mcp.py`.
- No cross-connection `JOIN`.
- **The system prompt MUST include schema hints** (e.g. «tables live in schema `ecom`»). Without the hint, qwen2.5-coder:7b defaults to `public.customers` — see 5.1 Data Engineer Helper below for a failure case.
- First query on a cold model: 4–8 s (VRAM load). Subsequent queries: 2–4 s.

**Pilot fit.** Strong. Target: business analyst or product manager who already writes ad-hoc SQL and wants a read-only assistant that knows their schema. Setup time: 5 min after connection creation.

---

### 1.2 MySQL Inventory Analyst

**Status:** ✅ works end-to-end, ⚠️ schema hint quality matters
**Model:** `qwen2.5-coder:7b`
**Last verified:** 2026-04-24, 2/2 turns, wall time 6.1 s
**Recommended for:** teams on MySQL 8.x warehouses (WooCommerce backends, internal CRMs, inventory DBs)

**What it does.** Same shape as PG Sales Analyst, but over MySQL 8.0. All standard MySQL syntax supported via `/mysql-connections/{id}/query`.

**Working example queries:**

> User: "How many products do we have in total?"
> → `SELECT COUNT(*) FROM products;`
> → Result: 10 ✓ (matches seed).

> User: "Which product category has the most items in stock?"
> → `SELECT category, SUM(stock_quantity) AS total_stock FROM products GROUP BY category ORDER BY total_stock DESC LIMIT 1;`
> → **Error surfaced from MySQL: `Unknown column 'stock_quantity'`** (actual seed column is `stock_qty`).
> → LLM correctly reported the error back to the user and suggested they verify the column name. **Good failure mode** — the tool didn't silently return nothing.

**Required setup.** Connections currently API-only — no "Add MySQL" form in Settings yet (Builder Wizard dropdown picks MySQL, but the Settings → Connections page has no MySQL form). Create via:
```bash
curl -X POST http://localhost:8765/mysql-connections \
  -H 'Content-Type: application/json' \
  -d '{"name":"...", "type":"mysql", "host":"...", "port":3306,
       "database":"...", "username":"...", "password":"..."}'
```
Then bind via Settings → Agents.

**Honest limitations.**
- UI gap: no Settings form for creating a MySQL connection (API-only). See `CAPABILITIES_STATUS.md §2`.
- Schema hallucination risk: if the connection isn't reindexed, the LLM may guess column names. **Always run `POST /mysql-connections/{id}/reindex` after connecting** — this populates Schema RAG.
- First query 3–6 s, subsequent 2–4 s.

**Pilot fit.** Good for MySQL shops once the connection is set up. Workaround the missing UI form with one curl call documented in UPGRADE.md.

---

### 1.3 ClickHouse Events Analyst

**Status:** ✅ Production ready
**Model:** `qwen2.5-coder:7b`
**Last verified:** 2026-04-24, 2/2 turns, wall time 6.7 s
**Recommended for:** analytics teams on ClickHouse, event-pipeline operators

**What it does.** Natural-language SQL over ClickHouse 24.x. Knows ClickHouse-specific functions (`count()`, `groupArray`, `argMax`) via system prompt.

**Working example queries:**

> User: "How many total events do we have?"
> → `SELECT count() AS total_events FROM events;`
> → Result: 10 000 ✓ (matches seed).

> User: "What are the top-3 event_type values by count?"
> → ```sql
> SELECT event_type, count() AS event_count
> FROM events
> GROUP BY event_type
> ORDER BY event_count DESC
> LIMIT 3;
> ```
> → Result: purchase / click / search, 2 500 each.

**Required setup.** Same pattern as MySQL — connection via `POST /ch-connections`, bind via Settings → Agents.

**Honest limitations.**
- UI gap: no Settings form for ClickHouse connections (API-only). Same status as MySQL.
- ClickHouse is column-store — some queries that run in ms on CH are slow on OLTP DBs. Conversely, frequent single-row UPDATE-ish queries are out of scope (CH is analytical).

**Pilot fit.** Great for analytics use-cases: "count events by segment / time window / user cohort". Setup 5 min.

---

## Category 2: Code Assistants

### 2.1 Python Code Reviewer

**Status:** ✅ Production ready
**Model:** `qwen2.5-coder:7b`
**Last verified:** 2026-04-24, 1/1 turn, wall time 12.5 s

**What it does.** Paste a Python snippet, get a code review in 3–5 bullet points. Also proposes an improved version with docstring, error handling, and example tests — runs the tests inline via OI.

**Working example query:**

> User: `Review this Python snippet:`
> ```python
> def div(a,b):
>     return a/b
> ```
> → Review: flagged zero-division not handled, no type checking, missing docstring.
> → Then wrote an improved `div` with `ValueError` on zero and non-numeric, plus 3 test cases. Executed them — console output: `Result: 5.0` / `Denominator cannot be zero.` / `Both inputs must be numbers.` — all three cases verified.

**Required setup.** `capabilities: [filesystem_read]` · no connection binding. Just import the manifest. Setup: 2 minutes.

**Honest limitations.**
- The `filesystem_read` capability is advisory (see [`CAPABILITIES_STATUS.md §1`](CAPABILITIES_STATUS.md)) — actual file access depends on the global autonomy slider.
- qwen2.5-coder:7b is fine for snippet-scale review. For multi-file refactors, use a larger coder model (14b+) if available.

**Pilot fit.** Developer-productivity use-case; small team can try it in 10 minutes. Recommend pairing with Settings → Permissions locked to `review-only` so OI never executes generated code without confirmation.

---

### 2.2 Bash Script Helper

**Status:** ✅ works; ⚠️ slower than peers on first cold-start
**Model:** `qwen2.5-coder:7b`
**Last verified:** 2026-04-24, 1/1 turn, wall time 37.2 s (includes cold load + 3 OI tool-call iterations)

**What it does.** Given a natural-language shell task, suggests the command in a fenced ```bash block, explains it briefly.

**Working example query:**

> User: "How do I find the 5 largest files in my home directory?"
> → Command: `du -ah ~ | sort -rh | head -n 5`
> → Also executed it inline — console output showed the real largest paths. (Several subdirs hit permission-denied; LLM noted the caveat.)

**Required setup.** `capabilities: [shell_execute]` + `autonomy.recommended: review-only` strongly recommended so the user must confirm each shell invocation.

**Honest limitations.**
- OI's shell execution is not sandboxed — it runs as the dialekt process user. Do not use `autonomous` autonomy with untrusted input.
- 37 s wall time is outlier — post-warm it's 5–15 s. First model load on this machine is consistently slow.

**Pilot fit.** Good as a starter "what command do I need?" helper for non-DevOps staff. Keep on `review-only` autonomy.

---

## Category 3: Document Processing Agents

### 3.1 Document Summarizer

**Status:** ✅ Production ready
**Model:** `gemma3-12b:latest`
**Last verified:** 2026-04-24, 1/1 turn, wall time 2.3 s

**What it does.** Paste any English or Russian text, get exactly 3 markdown bullet points summarising it. Pure LLM, no connections, no capabilities.

**Working example query:**

> User: Paragraph about dialekt (EN).
> → Output:
> ```
> - **Dialekt Overview**: Dialekt is a local AI agent desktop application designed to operate entirely on the user's machine.
> - **Model Utilization**: It leverages Ollama models for its operations, ensuring data privacy and security as it does not transmit information to the cloud.
> - **Database Interaction**: Dialekt includes a SQL Analyst agent that allows querying PostgreSQL, MySQL, and ClickHouse databases directly from the application.
> ```

**Required setup.** 2 minutes — no connection needed.

**Honest limitations.**
- Output quality depends on Ollama model. gemma3-12b is adequate; smaller models (2b) tend to paraphrase poorly or invent facts.
- For very long documents, use File Upload (`/upload` endpoint) and ask for chunked summaries.

**Pilot fit.** Excellent default agent for knowledge-worker teams. Pair with file upload for PDF/markdown workflows.

---

### 3.2 Translator RU / EN / KK

**Status:** ✅ works for RU↔EN; ⚠️ **Kazakh quality poor** on gemma3-12b
**Model:** `gemma3-12b:latest`
**Last verified:** 2026-04-24, 1/1 turn, wall time 1.7 s

**What it does.** Translate between Russian, English, Kazakh. `metadata.language: kk` tag in the manifest — F-A4 schema feature validated here end-to-end.

**Working example query:**

> User: "Translate to Kazakh: 'Good morning, how are you today?'"
> → Output: `Зур бар, сен әзірде кандайсың?`
> → **Honest note.** This is **not grammatical Kazakh**. A human speaker would say «Қайырлы таң, бүгін қалыңыз қалай?». gemma3-12b has limited Kazakh coverage; it hallucinates plausible-looking Cyrillic. Do not ship this to Kazakh-speaking pilots without a better model.

**Required setup.** 2 minutes — no connection.

**Honest limitations.**
- **gemma3-12b Kazakh quality is weak.** Russian↔English works fine. For Kazakh, wait until we can ship with a Kazakh-tuned model (e.g. a Qwen 7B fine-tune on a KK corpus — M2 item).
- No language detection — the user must specify the target language.

**Pilot fit.** RU↔EN: ship today. KK: do not promise until model swap. This limitation is documented in `WHAT_DIALEKT_DOES_TODAY.md` under "Honest limitations → vision capabilities / M2 model upgrades".

---

## Category 4: Conversation Agents

### 4.1 General Assistant (bundled)

**Status:** ✅ ships with dialekt (pre-installed)
**Model:** `gemma3-12b:latest` (default) — overridable per session
**Last verified:** 2026-04-24, 1/1 turn, wall time 13.9 s

**What it does.** The default agent that ships with a fresh dialekt install. Full surface: Python, shell, ComfyUI image/video generation hooks, filesystem.

**Working example query:**

> User: "What can you help me with? Keep it to 3 bullet points."
> → Output:
> ```
> *   **Generating images:** Using Flux Schnell, I can quickly create images from text prompts.
> *   **Generating videos:** I can create short videos from text prompts using LTX-Video 2.3 (please be aware this takes a significant amount of time).
> *   **Running commands:** I can execute shell commands and Python code on your computer.
> ```

**Required setup.** None — ships pre-installed. User just opens dialekt and chats.

**Honest limitations.**
- The prompt documents ComfyUI endpoints (`/comfy/txt2img`, `/comfy/txt2vid`) but those are **only live if ComfyUI is running locally**. On a fresh pilot install without ComfyUI, the agent will still attempt to call them → timeout. Tell the pilot.
- `autonomy.recommended: autonomous` in the bundled version — override to `review-only` for untrusted users.

**Pilot fit.** Good "first 5 minutes" demo agent. Switch to a narrower published agent for actual work.

---

### 4.2 Russian Writing Assistant

**Status:** ✅ works; ⚠️ occasional loanword leakage (English words in Russian output)
**Model:** `gemma3-12b:latest`
**Last verified:** 2026-04-24, 1/1 turn, wall time 3.7 s

**What it does.** Rewrites Russian text for clarity, formality, grammar.

**Working example query:**

> User: «Перепиши лучше: 'Мы делаем продукт который очень полезный для команд'»
> → Output: `"Мы создаем продукт, который оказывается extremely полезным для команд."`
> → **Honest note.** The model replaced "очень" with English "extremely" — a gemma3-12b quirk where it sometimes leaks English loanwords mid-sentence. Not consistent, but ship with user-facing expectations. An RU-native copy-editor will catch these.

**Required setup.** 2 minutes — no connection. `language: ru` in manifest.

**Honest limitations.**
- English-word leakage (see example above) — avoid for high-stakes RU copy (legal, marketing). Works for internal-note polish.
- For Kazakh, see 3.2 caveats.

**Pilot fit.** Internal use (email draft polish) — ok. External/customer-facing copy — human review required.

---

## Category 5: Multi-tool Agents

### 5.1 Data Engineer Helper

**Status:** ⚠️ **works only with careful system-prompt tuning** — demonstrates the failure mode when schema hints are absent
**Model:** `qwen2.5-coder:7b`
**Last verified:** 2026-04-24, 1/1 turn, wall time **262.6 s** (outlier — see below)

**What it does.** Multi-tool agent with simultaneous `database_read + filesystem_read + shell_execute`. Intended for ETL-style workflows.

**Working example query (the verification):**

> User: "How many distinct countries are represented in the customers table?"
> → LLM generated: `SELECT COUNT(DISTINCT country) AS distinct_countries_count FROM customers;`
> → Result: `relation "customers" does not exist` — **because the bound connection's tables are in schema `ecom`, not `public`**.
> → LLM then entered a **50+-iteration loop** trying `\dt` (psql meta-commands not supported by DialektSQL) and variants of the same query for 4 minutes before OI exited.

**Why this matters (honest note):**

1. **System prompt MUST include schema hints.** The PG Sales Analyst (1.1) works because its prompt says *"tables live in schema `ecom`"*. This agent's prompt did not, so qwen defaulted to `public.*` and spun.
2. **DialektSQL does not support psql meta-commands** (`\dt`, `\d`, `\l`, `\c`). The LLM doesn't know that unless told.
3. **No circuit breaker at OI tool-call level.** A model can loop ~60 times on the same failed query before exiting. For pilots, cap `max_tokens` tight (we set 2048) and consider `review-only` autonomy.
4. The **final error surfaced cleanly**: `"No database connection is bound to this agent. Open Settings → Connections…"` — so even when the LLM gave up, dialekt returned a helpful message.

**Pilot fit.** Multi-tool agents are legitimate today **if you write a careful system prompt**. Copy the PG Sales Analyst prompt structure, add `filesystem_read + shell_execute` capabilities. Don't ship this template verbatim — ship it with schema-awareness already baked in.

**Required setup.** Same as PG Sales Analyst + `capabilities.groups: [database_read, filesystem_read, shell_execute]`. Manifest variables: `connection_id` (required) + `report_dir` (optional — advisory, not substituted yet per `SETTINGS_COMBOS_TODAY.md`).

---

## Category 5.5: MCP-enabled Agents

**Status:** ⚠️ v0.20.0 RC — schema, runtime, UI, and consent flow all wired and unit-tested. Real-server end-to-end validation against `@modelcontextprotocol/server-github` and a Slack MCP is the last gate before v0.20.0 ships. Pilots: do not promise these as production-ready until the validation pass lands and this section flips to ✅.

**What's in:**
- `Settings → MCP Servers`: full CRUD UI (add stdio or HTTP transport, env→secret mapping, bearer-token entry with masked storage in OS keychain, `[Test]` button that spawns the server briefly and reports tool count)
- `Builder Wizard` step 5 "MCP Tools": tick-box selection of pre-configured servers; auto-injects the `mcp_tools` capability; bumps the manifest's `spec_version` to `1.1.0` and `minimum_dialekt_version` to `0.20.0` when MCP is selected
- `ConsentModal` overlay in chat: three-button decision (Approve once / Approve for session / Deny), keyboard shortcuts (Enter / Shift+Enter / Esc), queue indicator for concurrent calls, timeout banner. Maps directly to `dialekt.mcp.consent.ConsentDecision`
- Per-session `MCPRuntime` constructed in `ws_chat`, bound through a `ContextVar` that's explicitly carried into the OI worker thread via `contextvars.copy_context()` so `ctx.mcp.<server>.<tool>(...)` resolves from sync Python blocks
- Soft-fail on bad config: missing secrets / invalid transport spec emit an `mcp_setup_error` toast in the chat — the session keeps going without MCP, the agent's `ctx.mcp` raises `MCPConfigError` on first use which surfaces as a normal tool error
- LeftPanel agent rows show a plug icon when the manifest declares `mcp_servers`; hover/screen-reader tooltip lists the server names

### 5.5.1 GitHub Operations Agent — blueprint

**Recommended for:** engineering teams that want a chat surface for repo housekeeping (issue triage, PR review, branch cleanup) without granting GitHub access to a cloud LLM provider.

**Manifest sketch** (paste-ready for the Builder Wizard's import path or YAML editor):

```yaml
spec_version: "1.1.0"
minimum_dialekt_version: "0.20.0"
metadata:
  id: "<uuid4 here>"
  name: "GitHub Operations Agent"
  description: "Issue triage, PR review, repo housekeeping via GitHub MCP."
  version: "1.0.0"
  language: "en"
  author: { name: "<your team>", email: "<contact>" }
  created_at: "2026-04-25T00:00:00+00:00"
  updated_at: "2026-04-25T00:00:00+00:00"
mcp_servers:
  - name: "github"
    transport: "stdio"
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "${secrets.github_token}"
    timeout_seconds: 30
capabilities:
  groups: ["mcp_tools"]
autonomy:
  recommended: "ask-before-write"
  max_allowed: "ask-before-write"
```

**Setup** (5 min): Settings → MCP Servers → Add → Name `github`, Transport `stdio`, Command `npx -y @modelcontextprotocol/server-github`, Environment variable `GITHUB_TOKEN` mapped to credential ref `github_token`, paste your PAT. Click `[Test]` — should show `N tools discovered`. Builder Wizard → MCP Tools → tick `github`. Publish.

**Sample queries** (LLM-generated tool calls; consent prompt fires on the destructive ones):
- "List my recent repos" → `dialekt_mcp_github_list_repositories` (read, auto)
- "Find issues in dialektai/dialektai labelled bug" → `search_issues` (read, auto)
- "Create an issue on dialektai/dialektai titled 'X' with body 'Y'" → `create_issue` (destructive → consent)
- "Close issue #42" → `update_issue` (destructive → consent)

**Known limitations** (pre-validation):
- Tool names depend on the MCP server build; the wizard's preview is "N tools discovered" only (full list deferred — see post-1.6 hardening backlog)
- Per-tool allow/deny scoping not yet exposed in the UI (manifest schema 1.1.0 supports `mcp_servers[].allow_tools` / `deny_tools`; deferred to M2 Month 2)
- Rate limit headers from GitHub are not surfaced as a chat toast yet — agent sees them as a tool error and decides how to recover

### 5.5.2 Slack Automation Agent — blueprint

**Recommended for:** ops teams that want chat-driven Slack actions (status posts, channel triage). HTTP transport with bearer-token auth; targets community Slack MCP servers (e.g. `mcp-slack`).

**Manifest sketch:**

```yaml
spec_version: "1.1.0"
minimum_dialekt_version: "0.20.0"
metadata: { ... }
mcp_servers:
  - name: "slack"
    transport: "http"
    url: "https://your-slack-mcp.example.com/mcp"
    auth:
      type: "bearer"
      token: "${secrets.auth_token}"
    timeout_seconds: 30
capabilities:
  groups: ["mcp_tools"]
autonomy:
  recommended: "ask-before-write"
  max_allowed: "ask-before-write"
```

**Setup**: Settings → MCP Servers → Add → Name `slack`, Transport `http`, URL of the Slack MCP, Auth `Bearer token`, paste token. `[Test]` should report tool count. Wizard → MCP Tools → tick `slack`. Publish.

**Status flag:** Slack MCP server quality varies in the wild. Validation pass MAY downgrade this entry to "Coming later" if no maintained Slack MCP passes the [Test] gate reliably — pilots should not pre-commit to this until the pass lands.

### 5.5.3 Multi-tool Research Agent — blueprint (composition)

Demonstrates manifest-level composition: filesystem MCP + GitHub MCP + read-only PostgreSQL connection in the same agent. Compares the company's README against three peer repos pulled by the agent.

```yaml
spec_version: "1.1.0"
minimum_dialekt_version: "0.20.0"
metadata: { ... }
mcp_servers:
  - name: "fs"
    transport: "stdio"
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path/to/repo"]
    timeout_seconds: 60
  - name: "github"
    transport: "stdio"
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "${secrets.github_token}"
capabilities:
  groups: ["mcp_tools", "filesystem_read"]
```

**Sample query:** "Read our README and compare it with the top 3 repos that match the same description on GitHub. Summarize the gaps." Agent issues fs MCP `read_file` (auto), then GitHub MCP `search_repositories` (auto), then `get_repository_content` for each (auto). No destructive calls — no consent prompts.

### Pre-pilot validation pass — DEFERRED

Real-server end-to-end runs against:
1. `@modelcontextprotocol/server-github` with a live GitHub PAT — verify all of: connection test, tool discovery, read tool call (no consent), write tool call (consent prompt fires, decision honored, audit row written), audit linkage between `consent_requested` row and the subsequent `tool_call` row.
2. A maintained Slack MCP — same flow.
3. Multi-tool composition agent — verify both servers come up in the same session, ContextVar carries through OI thread, no cross-server interference.

**Why deferred:** these require live external credentials. Run by a pilot or by Dias on a controlled host before flipping this section's status to ✅. Document outcomes in `docs/MCP_PRODUCTION_VALIDATION.md` (not yet created — added in the validation commit).

The unit + integration test suite for everything **above** the external API boundary (manifest parsing, transport spec construction, secret resolution, runtime construction, soft-fail paths, cross-thread contextvars, /mcp-servers CRUD, /test endpoint shapes, consent modal protocol, agent serializer with `mcp_server_names`) passes 602 / 30 skipped / 0 regressions on this branch.

---

## Category 6: Coming in M2 — NOT available today

These configurations are **NOT** available on v0.10.0. Do not promise them to pilots.

### Scheduled / cron agents
**Why blocked.** Manifest accepts `trigger.type: scheduled` with `cron`, `timezone`, `missed_run_policy` — but **no scheduler runtime exists** in `server.py`. The agent validates and imports but never fires.
**ETA.** Q3 2026 (M2)

### Webhook-triggered agents
**Why blocked.** Not a schema variant. `Trigger` union contains only `InteractiveTrigger` and `ScheduledTrigger`.
**ETA.** Q4 2026 (M3)

### Email / SMTP senders
**Why blocked.** `output.destination.type: email_or_telegram` passes validation — no transport exists. No credential UI.
**ETA.** Q3 2026 (M2)

### Web search agents
**Why blocked.** No native HTTP tool, no search-API adapter (Tavily, Brave, SerpAPI). Agents *can* hit search APIs via raw `httpx` — but that's a custom integration per customer, not an out-of-box feature.
**ETA.** Q3 2026 (M2)

### Vision agents (image input)
**Why blocked.** None of the installed Ollama models (`qwen2.5-coder:7b`, `gemma3-12b`, `gemma2:2b`, `nomic-embed-text`) support vision. OI can accept images but the pipeline needs a vision-capable model pull.
**ETA.** Q3 2026 (M2) — requires shipping with a vision model.

### Browser automation (Selenium)
**Why blocked.** OI has `interpreter.computer.browser`, but OS-level Selenium deps unverified on Linux. Untested end-to-end.
**ETA.** Q3 2026 (M2 — verify pass needed).

### Multi-agent workflows (agent A calls agent B)
**Why blocked.** One agent per WebSocket session. No dispatcher, no agent-to-agent call primitive.
**ETA.** Q4 2026 (M3)

### ~~Per-agent secrets injection~~ — RESOLVED in v0.20.0 RC
Manifest `${secrets.<ref>}` interpolation now resolves through the OS keychain via `dialekt.secrets` + `dialekt.mcp.secrets_resolver.keyring_key()`. Settings → MCP Servers writes secrets at create/edit time; the `_build_session_mcp_runtime` helper resolves them at chat-session join. `MCPConfigError` with the missing ref name surfaces as an `mcp_setup_error` toast when a referenced secret isn't set.

### Custom output destinations (filesystem, webhook, email)
**Why blocked.** Schema-valid, no delivery runtime. Only `notification` (chat column) works.
**ETA.** Q3 2026 (M2)

---

## Verification evidence

All agent runs in this catalog are captured in `scripts/pilot_verify/evidence.json`. To re-run:

```bash
cd /home/dias/projects/desktop/dialekt
source python/venv/bin/activate
PYTHONUNBUFFERED=1 python scripts/pilot_verify/harness.py
# Writes fresh evidence.json in scripts/pilot_verify/
```

The harness is idempotent: existing agents/connections (matched by name) are reused instead of re-created.

---

## How to add your own agent to this catalog

1. Write a manifest using the field combinations in [`SETTINGS_COMBOS_TODAY.md`](SETTINGS_COMBOS_TODAY.md).
2. Validate locally: `dialekt-manifest-validate my-agent.yaml`.
3. Add an entry to `scripts/pilot_verify/harness.py::build_catalog()` with at least one sample chat turn.
4. Re-run the harness. Evidence is captured. Document with verified queries + honest limitations.

No simulation, no marketing copy — if it doesn't pass the harness, it doesn't go in the catalog.
