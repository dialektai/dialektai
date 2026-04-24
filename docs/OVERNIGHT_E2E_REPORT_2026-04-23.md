# Overnight E2E Report — 2026-04-23 19:41

Automated 18-scenario run against a live dialekt server.
Harness: `/tmp/overnight_e2e.py` (not committed).

## Summary

- Total: 18
- ✅ Pass:  18
- ❌ Fail:  0
- ⚠ Error: 0

## Section: Wizard

| # | Scenario | Status | Detail |
|---|---|---|---|
| 1 | 1. SQL Analyst w/ PostgreSQL | ✅ pass | id=d805c734 |
| 2 | 2. SQL Analyst w/ MySQL | ✅ pass | id=180ef035 |
| 3 | 3. SQL Analyst w/ ClickHouse | ✅ pass | id=e7f28c94 |
| 4 | 4. Pure LLM, autonomy=manual | ✅ pass | id=295f8315 |
| 5 | 5. Pure LLM, autonomy=autonomous | ✅ pass | id=42f6c46f |
| 6 | 6. Pure LLM, autonomy=review-only | ✅ pass | id=00f38772 |
| 7 | 7. Power user w/ 6 capabilities | ✅ pass | id=d1e3f401 |
| 8 | 8. Minimal agent | ✅ pass | id=c1f94da6 |
| 9 | 9. Multi-DB (pg + mysql) | ✅ pass | id=d1f73b30 |
| 10 | 10. 3 variables (string / number / boolean) | ✅ pass | id=2b567d47 |

## Section: SQL

| # | Scenario | Status | Detail |
|---|---|---|---|
| 1 | 1. Simple SELECT COUNT (pg) | ✅ pass | \| n \| · \|---\| · \| 10 \| ·  · row_count=1 |
| 2 | 2. JOIN across 2 tables (pg) | ✅ pass | \| name \| orders_count \| · \|---\|---\| · \| Carol \| 3 \| · \| Eve \| 2 \| · \| Alice \| 2 \| ·  · row_count=3 |
| 3 | 3. GROUP BY aggregation (pg) | ✅ pass | \| customer_id \| spent \| · \|---\|---\| · \| 3 \| 800 \| · \| 5 \| 140 \| · \| 4 \| 75 \| · \| 2 \| 350 \| · \| 1 \| 300 \| ·  · row_count=5 |
| 4 | 4. Invalid SQL → clean error (no retry storm) | ✅ pass | SQL error (400): {"detail":"SQL error: syntax error at or near \"public\""} |
| 5 | 5. Non-existent table → clean error | ✅ pass | SQL error (400): {"detail":"SQL error: relation \"public.nonexistent_table_xxx\" does not exist"} |

## Section: Routing

| # | Scenario | Status | Detail |
|---|---|---|---|
| 1 | 1. Preferred installed → exact | ✅ pass | picked=qwen2.5-coder:7b |
| 2 | 2. Family match (32b→7b) | ✅ pass | picked=qwen2.5-coder:7b |
| 3 | 3. No manifest → global default | ✅ pass | picked=gemma3-12b |

---

## Notes & side-findings

These are observations from running the harness — not part of the 18
scenarios but worth capturing before they rot out of memory.

### N1. Stale long-running server masks schema v0.2.0 (reproduced)

**What happened.** First pass of the E2E suite reported W4 (`autonomy=manual`)
as FAIL with

```
HTTP 422 autonomy.recommended: Value error, Autonomy level must be one of
['review-only', 'ask-before-write', 'autonomous', 'sandbox-only']
```

— note the **four**-value list. After `pkill -9 python3 server.py` and a
clean restart, the same scenario passed with `201 Created`. The server's
running process had imported `dialekt_manifest.schema.AUTONOMY_LEVELS` at
boot (v0.1.0, 4 values); upgrading the schema package to 0.2.0 at runtime
via `pip install -e` updated disk but not the in-memory interpreter.

**Impact.** Anyone who upgrades `dialekt-manifest-validator` to 0.2.0
without restarting their local dialekt-server will see Publish fail on
`autonomy=manual` with a misleading 422. Pilot-facing.

**Suggested mitigation (follow-up, not here):** expose a thin
`POST /admin/reload-schema` endpoint that re-imports
`dialekt_manifest`, or document "restart dialekt after updates" in the
release notes.

### N2. `/mysql-connections` and `/ch-connections` return ALL connections (no type filter)

**What happened.** During the pre-run state dump I noticed:

```
GET /connections          → [E2E Demo (pg), E2E MySQL Demo (mysql)]
GET /mysql-connections    → [E2E Demo (pg), E2E MySQL Demo (mysql)]
GET /ch-connections       → [E2E Demo (pg), E2E MySQL Demo (mysql)]
```

All three list endpoints return the union. Source: `mysql_mcp.py:143-148`
and `clickhouse_mcp.py:~130-135` — both do `SELECT * FROM connections
ORDER BY name` with no `WHERE type = ?` filter. The shared `connections`
table holds every driver's rows.

**Impact.** The Settings → Connections UI (shipped earlier today in
commit `e518052`) fetches all three endpoints and merges, tagging each
row with `_driver` based on which endpoint returned it. Because all
three endpoints return the full union, **every connection shows up
three times in the UI — once per driver tag** — which is wrong.

This was not part of the 18 scenarios (no UI test runs today), but
it's a pilot-visible bug the moment the Connections page is opened
with any connections present.

**Suggested fix (follow-up, not here):** add
`WHERE type = 'mysql'` (resp. `'clickhouse'`) to the two list queries.
One-line change per file. Also fix the Settings page load to not
de-dupe by `(id, driver)` — just tag rows by their real `type` field.

### N3. DialektSQL clean error on bad SQL — confirmed no retry storm

SQL scenarios 4 and 5 both returned a single `400 Bad Request` with a
single-line Postgres error. Log shows only ONE `/query` request per
scenario — the earlier recursive-retry bug (fixed in commit
`153691e`) stays fixed.

---

## Artifacts

- Test harness: `/tmp/overnight_e2e.py` (69 LOC wizard scenarios, 40 LOC
  SQL, 30 LOC routing, 50 LOC reporter).
- Server log: `/tmp/dialekt-server.log`.
- Created test agents: 10 per run, all cleaned up (DELETE /agents/{id})
  at end of harness.

No production code modified during the run.
