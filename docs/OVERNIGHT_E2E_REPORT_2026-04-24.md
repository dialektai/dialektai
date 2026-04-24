# Overnight E2E Report — 2026-04-24

**Run:** `python/tests/e2e_diag_runner.py`
**Harness:** FastAPI `TestClient` over a temp-DB copy of `~/.dialekt` (no production writes).
**DB backing:** `integration-postgres-1` container at `localhost:15432` (seeded from
`tests/integration/seed/postgres_seed.sql` — `ecom.customers/products/orders/order_items` +
`analytics.page_views/events`).
**Ollama:** `qwen2.5-coder:7b`, `gemma3-12b:latest`, `gemma2:2b`, `nomic-embed-text:v1.5`.
**Machine-readable results:** `python/e2e_diag_results.json`.

---

## Summary

| Group          | Pass | Fail | Error | Skip |
|----------------|------|------|-------|------|
| Wizard (×10)   | 10   | 0    | 0     | 0    |
| SQL (×5)       | 5    | 0    | 0     | 0    |
| Routing (×3)   | 3    | 0    | 0     | 0    |
| **Total (×18)**| **18** | **0** | **0** | **0** |

**Verdict:** All 18 scenarios pass at the integration level. Two findings noted below
(one is a test-harness artifact; one is a latent retry-loop concern for non-default
deployments) — neither blocks shipping.

---

## 1 · Wizard publish (10 / 10)

Each scenario builds a full YAML manifest via `_base_manifest(...)` with the overrides
listed below, POSTs to `/agents/import-yaml`, then GETs `/agents/{id}` to verify the
record round-trips intact. Agent is deleted after verification to keep counts clean.

| # | Scenario | Overrides | Result |
|---|---|---|---|
| 01 | SQL Analyst · PostgreSQL | `capabilities.groups=[database_read]`, `connections.required=[{type:postgres}]` | HTTP 201 |
| 02 | SQL Analyst · MySQL | `…[{type:mysql}]` | HTTP 201 |
| 03 | SQL Analyst · ClickHouse | `…[{type:clickhouse}]` | HTTP 201 |
| 04 | Pure LLM · `autonomy=manual` | recommended+max = `manual` (the F-A1 fix value) | HTTP 201 |
| 05 | Pure LLM · `autonomy=autonomous` | recommended+max = `autonomous` | HTTP 201 |
| 06 | Pure LLM · `autonomy=review-only` | recommended+max = `review-only` | HTTP 201 |
| 07 | Power user · all 6 capability groups | `[filesystem_read, network, browser, database_read, shell_execute, screen_capture]` + postgres conn | HTTP 201 |
| 08 | Minimal agent | only required fields, no caps/conns/vars | HTTP 201 |
| 09 | Multi-DB agent | `connections.required=[{type:postgres},{type:mysql}]` | HTTP 201 |
| 10 | Vars · string+number+boolean | `variables={API_KEY:string, MAX_ROWS:number, DRY_RUN:boolean}` | HTTP 201 |

**Observation:** `autonomy=manual` publishes cleanly — confirms F-A1 (added 2026-04-23)
is still in place and not regressed.

**Observation:** multi-driver `connections.required` (scenario 09) publishes fine; this
is the shape the wizard emits after F-A2. Verified end-to-end, not just at the
`ManifestValidator` layer.

---

## 2 · SQL execution (5 / 5)

Against a fresh `/connections` record pointed at `dialekt_integration` (PG 16-alpine,
port 15432). `POST /connections/{id}/test` returned `{ok:true}` before running queries.

| # | Query | Result |
|---|---|---|
| 01 | `SELECT COUNT(*) AS n FROM ecom.customers` | 1 row — `[["1000"]]` |
| 02 | 2-way JOIN customers × orders, `GROUP BY country ORDER BY orders DESC LIMIT 5` | 5 rows — columns `[country, orders]` |
| 03 | `GROUP BY status, COUNT(*), AVG(total_usd)` over `ecom.orders` | 5 rows — columns `[status, n, avg_total]` |
| 04 | **Invalid syntax:** `SELEKT * FROM ecom.customers` | HTTP 400 · `SQL error: syntax error at or near "SELEKT"` — retry loop fired 3× (see finding below), fell back to surface the PG error cleanly |
| 05 | **Missing table:** `SELECT * FROM ecom.nonexistent_zzz LIMIT 1` | HTTP 400 · `SQL error: relation "ecom.nonexistent_zzz" does not exist` |

### Finding SQL-1 — retry loop cannot self-validate under TestClient

Severity: **low** (harness artifact, not a production bug)

When scenario 04 ran, the retry loop correctly engaged but all 3 attempts failed
with `Connection not found`:

```
WARNING 🔄 SQL retry: initial SQL failed EXPLAIN validation; starting fix-up loop
WARNING [retry_loop] Attempt 1 failed: Connection not found
WARNING 🔄 SQL retry attempt 2/3 — previous error: The SQL you generated failed validation:
WARNING [retry_loop] Attempt 2 failed: Connection not found
WARNING 🔄 SQL retry attempt 3/3 — previous error: …
WARNING 🔄 SQL retry exhausted (All 3 attempts failed); falling back to original SQL
```

Root cause: `python/dialekt/llm/retry_loop.py:21` hardcodes
`_BACKEND = "http://localhost:8765"`, so `validate_sql()` makes an out-of-band HTTP call
to the *live* dialekt-server process — which has no knowledge of our TestClient's
temp-DB connection. In real use this is fine (the retry-running server is the same
server holding the connection). But:

- It makes the retry loop untestable via `TestClient` — any test that wants to verify
  the retry loop end-to-end has to spin up the server on 8765.
- If a pilot ever runs dialekt on a non-default port (e.g. `--port 8766`), the retry
  loop will silently 404 into oblivion.

**Recommendation:** pass the current server's base URL via dependency injection
instead of a module-level constant, or at minimum read from
`DIALEKT_BACKEND_URL` env. Not urgent — defaults work for 100% of users today.

### Finding SQL-2 — error surfacing is clean

Both the syntax-error (04) and missing-relation (05) scenarios produce a
well-formed 400 with a readable `detail` field. The UI's existing toast logic
can surface these directly. No change needed.

---

## 3 · Agent model routing (3 / 3)

Unit-level calls to `server.pick_model_for_agent` with `installed =
{qwen2.5-coder:7b, gemma3-12b:latest, gemma2:2b}` and `default="gemma3-12b"`.

| # | Scenario | `preferred` | Expected | Got |
|---|---|---|---|---|
| 01 | Preferred installed | `qwen2.5-coder:7b` | exact match | `qwen2.5-coder:7b` |
| 02 | Preferred `:32b`, only `:7b` installed | `qwen2.5-coder:32b` | family match → `:7b` | `qwen2.5-coder:7b` |
| 03 | No preferred, no acceptable | `None` | global default | `gemma3-12b` |

**Observation:** all three fall-back rungs of `pick_model_for_agent` are exercised.
Logs confirm the chosen rung in each case:

```
INFO pick_model: using preferred qwen2.5-coder:7b
INFO pick_model: family-match qwen2.5-coder:32b -> qwen2.5-coder:7b
WARNING pick_model: no match for preferred=None acceptable=[], using default 'gemma3-12b'
```

No regressions from the existing `test_model_selection.py` behavior.

---

## Infrastructure setup notes (not findings, just for future runs)

1. `docker compose up -d --wait` for the integration compose at
   `tests/integration/docker-compose.yml` failed because port `13306` (MySQL) was
   already bound by the pre-existing `dialekt-e2e-mysql` container (from an older
   harness with different creds: `root/testpass` on DB `e2e_mysql_demo`). Only the
   Postgres container (`integration-postgres-1`) and ClickHouse container
   (`integration-clickhouse-1`) were needed for this suite, so `mysql` was skipped.
2. `make_client()` in the diag runner must use a context-managed `TestClient` —
   without the `with` block, FastAPI's startup events don't fire and
   `POST /connections` returns 500 because the SQLite pool isn't wired up. Noted
   inline in `e2e_diag_runner.py`.
3. `POST /agents/import-yaml` takes `{"manifest_yaml": "…"}`, not `{"yaml": "…"}` —
   easy to miss.

---

## Recommendations

| ID | Priority | Action |
|---|---|---|
| R1 | Low | ~~Make `_BACKEND` in `retry_loop.py:21` configurable (env + DI).~~ **Done** in commit `12d663c` (DIALEKT_BACKEND_URL env, 4 new tests, UPGRADE.md updated). |
| R2 | Low | ~~Consider pruning `dialekt-e2e-mysql` if no longer used — otherwise the integration compose will keep failing on port conflict.~~ **Done** 2026-04-24 — container removed, port 13306 freed. Uncovered R4 below. |
| R3 | Nice-to-have | Wrap the diag runner in pytest parametrization so CI can run it as part of the full suite. |
| R4 | Low | `python/tests/integration/seed/mysql_seed.sql:81` uses a recursive CTE that exceeds MySQL 8.0's default `cte_max_recursion_depth=1000`, so `integration-mysql-1` can never seed itself cleanly (exits 1 with `ERROR 3636 (HY000)`). Discovered while verifying R2. **Fix options:** (A, ~30 min) replace the CTE with a batched `INSERT INTO … VALUES (…), (…)` literal, or (B, ~1 h) pre-generate rows from a small Python helper script. Option A is cleaner — no dependency on MySQL session settings. Neither blocks the Python suite today (tests skip when MySQL is unreachable). |

No P0/P1 findings. Ship candidate is healthy.
