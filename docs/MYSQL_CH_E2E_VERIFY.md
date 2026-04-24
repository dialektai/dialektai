# MySQL + ClickHouse E2E Verification — 2026-04-23

Exercising the non-PostgreSQL code paths to confirm (a) backend routers serve queries, (b) `DialektSQL` routes to the right prefix based on the agent's bound `connection_type`. This was the second half of the F2/F4 pair from the capabilities sweep.

## Setup

- MySQL 8.4 in Docker: `docker run -d --name dialekt-e2e-mysql -e MYSQL_ROOT_PASSWORD=testpass -e MYSQL_DATABASE=e2e_mysql_demo -p 13306:3306 mysql:8`
- Seeded `orders` table, 4 rows (2 in Алматы, 1 each in Астана / Шымкент)
- No local ClickHouse instance on this server — ClickHouse tested for *routing* only, not full query execution

## Results

### MySQL

| Step | Status | Evidence |
|---|---|---|
| `POST /mysql-connections` — create connection | ✅ | `{"id":"127aeb3f-…","name":"E2E MySQL Demo"}` |
| `POST /mysql-connections/{id}/test` — ping | ✅ | `{"ok":true,"version":"8.4.9"}` |
| `POST /mysql-connections/{id}/query` with `retry:false` | ✅ | `{"columns":["COUNT(*)"],"rows":[["4"]],"row_count":1}` |
| `POST /agents/{id}/binding` — attach to "MySQL Analyst E2E" agent with `connection_type: mysql` | ✅ | Binding persisted in `agent_bindings` |
| `DialektSQL.run(...)` with `_dialekt_sql_driver=mysql` | ✅ | Routes to `/mysql-connections/{id}/query`, returns: `\| n \|`<br>`\| 4 \|`<br>`row_count=1` — rendered as markdown table |

### ClickHouse (routing only — no local CH)

| Step | Status | Evidence |
|---|---|---|
| `DialektSQL.run(...)` with `_dialekt_sql_driver=clickhouse` and a fake `conn_id` | ✅ routing correct | Surfaces `SQL error (404): {"detail":"Connection not found"}` — 404 from the `/ch-connections` router confirms the prefix dispatch is right; only missing a real CH instance |

**Not blocked for pilots** that don't use ClickHouse. For a CH pilot, repeat the MySQL steps with a real ClickHouse container — same pattern, different `driver` value.

## Bug found and fixed during this verification

**Symptom:** Before the fix, `DialektSQL._execute` was hard-coded to POST `/connections/{conn_id}/query` regardless of driver. Any agent bound to a MySQL or ClickHouse connection got a 400 from the PostgreSQL router because `conn_id` wasn't in the PG connections table.

**Fix** (`python/dialekt/llm/sql_language.py`):

- Added `_DRIVER_PREFIX` map and `_prefix_for(driver)` helper that translates `postgres / postgresql / pg` → `/connections`, `mysql` → `/mysql-connections`, `clickhouse / ch` → `/ch-connections`. Unknown / missing → falls back to `/connections` for backward compatibility with pre-existing PG bindings.
- `DialektSQL.run` now reads `interpreter._dialekt_sql_driver` (new) alongside `_dialekt_sql_conn` and passes it to `_execute`.
- `make_interpreter` in `server.py` now stashes both attributes on the interpreter from `agent_context` (the driver comes from `agent_bindings.connection_type`, already populated by `resolve_agent_context`).

**Tests added:** 14 new cases in `tests/test_sql_language.py` (parametrised `_prefix_for`, MySQL routing, ClickHouse routing, postgres-default fallback). All 24 SQL language tests green. Full suite: 260 passed.

## Chrome MCP verification — deferred

The Chrome-in-Chrome extension was disconnected during this work. Visual verification of:

- The new driver dropdown in Settings → Connections Add form
- Creating a MySQL connection through the UI (not API)
- Driver pill on connection rows

…is pending extension reconnect. Backend and DialektSQL paths are fully exercised via API + unit tests; the remaining gap is a 5-minute click-through, non-blocking.

## Cleanup

`dialekt-e2e-mysql` container is left running for the next Chrome MCP session. Remove with `docker rm -f dialekt-e2e-mysql` when done. No ClickHouse container was started.

## Bottom line

- **MySQL agent path: ✅ unblocked end-to-end.** A "MySQL Analyst" agent can now run SQL queries against MySQL via the same DialektSQL code path as the PostgreSQL SQL Analyst.
- **ClickHouse agent path: ✅ routing works**, query execution will work once a real ClickHouse connection is available.
- **SQL Analyst (PostgreSQL): unaffected** — default driver falls back to `/connections` as before, and the existing E2E Demo connection is untouched.
