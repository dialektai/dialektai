"""
dialekt PostgreSQL MCP — SQL tools for the SQL Analyst agent.

REST endpoints registered on dialekt's FastAPI app under /connections.
The SQL Analyst agent calls these via Python httpx code blocks in OI.

Security:
  - Credentials stored in OS keychain (keyring), never in DB or manifests
  - All queries executed in READ ONLY transactions
  - DDL/DML detection rejects writes at parse time before execution
  - Row limit (default 1000) + query timeout (30s) enforced
  - EXPLAIN check warns before running queries projecting >10k rows
"""
import asyncio
import json
import logging
import re
import uuid
from typing import Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Depends

log = logging.getLogger("dialekt.postgres")

router = APIRouter(prefix="/connections", tags=["connections"])

# ── Keyring ──────────────────────────────────────────────────────────────────

_KEYRING_SERVICE = "dialekt.pg"


def _cred_key(conn_id: str) -> str:
    return f"{_KEYRING_SERVICE}.{conn_id}"


def _save_password(conn_id: str, password: str) -> None:
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, conn_id, password)
    except Exception as e:
        log.warning(f"keyring unavailable ({e}); password not saved securely")


def _load_password(conn_id: str) -> Optional[str]:
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, conn_id)
    except Exception:
        return None


def _delete_password(conn_id: str) -> None:
    try:
        import keyring
        keyring.delete_password(_KEYRING_SERVICE, conn_id)
    except Exception:
        pass


# ── Connection pool registry ──────────────────────────────────────────────────

_pools: dict[str, asyncpg.Pool] = {}


async def _get_pool(conn_id: str, conn: dict) -> asyncpg.Pool:
    if conn_id not in _pools:
        password = _load_password(conn_id)
        if password is None:
            raise HTTPException(400, "No credentials stored for this connection. "
                                "Re-save with a password via POST /connections.")
        try:
            pool = await asyncpg.create_pool(
                host=conn["host"],
                port=int(conn["port"]),
                database=conn["database"],
                user=conn["username"],
                password=password,
                min_size=1,
                max_size=5,
                command_timeout=30,
            )
        except Exception as e:
            raise HTTPException(503, f"Cannot connect to database: {e}")
        _pools[conn_id] = pool
    return _pools[conn_id]


async def close_all_pools() -> None:
    for pool in _pools.values():
        try:
            await pool.close()
        except Exception:
            pass
    _pools.clear()


# ── SQL safety ────────────────────────────────────────────────────────────────

_DDL = re.compile(
    r'\b(CREATE|DROP|ALTER|TRUNCATE|RENAME|GRANT|REVOKE|COMMENT|'
    r'VACUUM|ANALYZE|CLUSTER|REINDEX|REFRESH)\b',
    re.IGNORECASE,
)
_DML = re.compile(
    r'\b(INSERT|UPDATE|DELETE|MERGE|UPSERT|REPLACE|COPY|'
    r'CALL|EXEC|EXECUTE)\b',
    re.IGNORECASE,
)
_SET_ROLE = re.compile(r'\bSET\s+(ROLE|SESSION|LOCAL)\b', re.IGNORECASE)


def _check_sql_safety(sql: str) -> None:
    """Raise HTTPException 422 if SQL contains DDL or DML."""
    clean = re.sub(r"--[^\n]*", " ", sql)          # strip line comments
    clean = re.sub(r"/\*.*?\*/", " ", clean, flags=re.DOTALL)  # strip block comments
    if _DDL.search(clean):
        m = _DDL.search(clean).group()
        raise HTTPException(422, f"DDL statement rejected: '{m}' is not allowed. Only SELECT queries are permitted.")
    if _DML.search(clean):
        m = _DML.search(clean).group()
        raise HTTPException(422, f"DML statement rejected: '{m}' is not allowed. Only SELECT queries are permitted.")
    if _SET_ROLE.search(clean):
        raise HTTPException(422, "SET ROLE/SESSION statements are not allowed.")


# ── DB helpers (injected from server.py at startup) ───────────────────────────

_db = None  # aiosqlite.Connection injected by server.py


def init_db(db_conn):
    global _db
    _db = db_conn


async def _require_connection(conn_id: str) -> dict:
    cursor = await _db.execute("SELECT * FROM connections WHERE id = ?", (conn_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, "Connection not found")
    return dict(row)


# ── Connection CRUD ───────────────────────────────────────────────────────────

@router.get("")
async def list_connections():
    cursor = await _db.execute(
        "SELECT id, name, type, host, port, database, username, row_limit, created_at, updated_at "
        "FROM connections ORDER BY name"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@router.post("", status_code=201)
async def create_connection(body: dict):
    for field in ("name", "host", "database", "username", "password"):
        if not body.get(field):
            raise HTTPException(400, f"'{field}' is required")
    conn_id = str(uuid.uuid4())
    await _db.execute(
        "INSERT INTO connections (id, name, type, host, port, database, username, row_limit)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (conn_id,
         body["name"],
         body.get("type", "postgresql"),
         body["host"],
         int(body.get("port", 5432)),
         body["database"],
         body["username"],
         int(body.get("row_limit", 1000))),
    )
    await _db.commit()
    _save_password(conn_id, body["password"])
    return {"id": conn_id, "name": body["name"]}


@router.get("/{conn_id}")
async def get_connection(conn_id: str):
    return await _require_connection(conn_id)


@router.patch("/{conn_id}")
async def update_connection(conn_id: str, body: dict):
    await _require_connection(conn_id)
    allowed = {"name", "host", "port", "database", "username", "row_limit"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if "password" in body and body["password"]:
        _save_password(conn_id, body["password"])
        if conn_id in _pools:
            await _pools.pop(conn_id).close()
    if updates:
        set_parts = [f"{k} = ?" for k in updates] + ["updated_at = datetime('now')"]
        await _db.execute(
            f"UPDATE connections SET {', '.join(set_parts)} WHERE id = ?",
            [*updates.values(), conn_id],
        )
        await _db.commit()
        if conn_id in _pools:
            await _pools.pop(conn_id).close()
    return {"ok": True}


@router.delete("/{conn_id}")
async def delete_connection(conn_id: str):
    await _require_connection(conn_id)
    if conn_id in _pools:
        await _pools.pop(conn_id).close()
    _delete_password(conn_id)
    await _db.execute("DELETE FROM connections WHERE id = ?", (conn_id,))
    await _db.commit()
    from mcp_servers import schema_rag
    schema_rag.clear(conn_id)
    return {"ok": True}


@router.post("/{conn_id}/test")
async def test_connection(conn_id: str):
    conn = await _require_connection(conn_id)
    try:
        pool = await _get_pool(conn_id, conn)
        async with pool.acquire() as c:
            ver = await c.fetchval("SELECT version()")
        return {"ok": True, "version": ver}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── SQL tools ────────────────────────────────────────────────────────────────

@router.get("/{conn_id}/schemas")
async def list_schemas(conn_id: str):
    conn = await _require_connection(conn_id)
    pool = await _get_pool(conn_id, conn)
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('pg_catalog','pg_toast','information_schema') "
            "AND schema_name NOT LIKE 'pg_%' "
            "ORDER BY schema_name"
        )
    return [r["schema_name"] for r in rows]


@router.get("/{conn_id}/schemas/{schema}/tables")
async def list_tables(conn_id: str, schema: str):
    conn = await _require_connection(conn_id)
    pool = await _get_pool(conn_id, conn)
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT table_name, table_type "
            "FROM information_schema.tables "
            "WHERE table_schema = $1 "
            "ORDER BY table_name",
            schema,
        )
    return [{"name": r["table_name"], "type": r["table_type"]} for r in rows]


@router.get("/{conn_id}/schemas/{schema}/tables/{table}/describe")
async def describe_table(conn_id: str, schema: str, table: str):
    conn = await _require_connection(conn_id)
    pool = await _get_pool(conn_id, conn)
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT column_name, data_type, is_nullable, column_default, "
            "character_maximum_length, numeric_precision, numeric_scale "
            "FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = $2 "
            "ORDER BY ordinal_position",
            schema, table,
        )
        # Primary key info
        pk_rows = await c.fetch(
            "SELECT kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "  AND tc.table_schema = kcu.table_schema "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "AND tc.table_schema = $1 AND tc.table_name = $2",
            schema, table,
        )
    pk_cols = {r["column_name"] for r in pk_rows}
    return [
        {
            "column": r["column_name"],
            "type": r["data_type"],
            "nullable": r["is_nullable"] == "YES",
            "default": r["column_default"],
            "primary_key": r["column_name"] in pk_cols,
            "max_length": r["character_maximum_length"],
            "precision": r["numeric_precision"],
            "scale": r["numeric_scale"],
        }
        for r in rows
    ]


@router.get("/{conn_id}/schemas/{schema}/tables/{table}/fkeys")
async def list_foreign_keys(conn_id: str, schema: str, table: str):
    conn = await _require_connection(conn_id)
    pool = await _get_pool(conn_id, conn)
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT kcu.column_name, ccu.table_schema AS ref_schema, "
            "ccu.table_name AS ref_table, ccu.column_name AS ref_column, "
            "rc.update_rule, rc.delete_rule "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "  AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.referential_constraints rc "
            "  ON tc.constraint_name = rc.constraint_name "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON rc.unique_constraint_name = ccu.constraint_name "
            "WHERE tc.constraint_type = 'FOREIGN KEY' "
            "AND tc.table_schema = $1 AND tc.table_name = $2",
            schema, table,
        )
    return [
        {
            "column": r["column_name"],
            "references": f"{r['ref_schema']}.{r['ref_table']}.{r['ref_column']}",
            "on_update": r["update_rule"],
            "on_delete": r["delete_rule"],
        }
        for r in rows
    ]


@router.get("/{conn_id}/schemas/{schema}/tables/{table}/sample")
async def sample_rows(conn_id: str, schema: str, table: str, limit: int = 3):
    conn = await _require_connection(conn_id)
    if limit > 20:
        limit = 20
    pool = await _get_pool(conn_id, conn)
    safe_schema = re.sub(r'[^a-zA-Z0-9_]', '', schema)
    safe_table = re.sub(r'[^a-zA-Z0-9_]', '', table)
    async with pool.acquire() as c:
        async with c.transaction(readonly=True):
            rows = await c.fetch(
                f'SELECT * FROM "{safe_schema}"."{safe_table}" LIMIT $1', limit
            )
    if not rows:
        return {"columns": [], "rows": []}
    columns = list(rows[0].keys())
    return {
        "columns": columns,
        "rows": [[str(v) if v is not None else None for v in r.values()] for r in rows],
    }


@router.post("/{conn_id}/query")
async def execute_query(conn_id: str, body: dict):
    sql = (body.get("sql") or "").strip()
    if not sql:
        raise HTTPException(400, "sql is required")
    conn = await _require_connection(conn_id)
    row_limit = int(body.get("row_limit") or conn.get("row_limit", 1000))
    timeout = float(body.get("timeout_s", 30))

    _check_sql_safety(sql)

    # ── Goal 8.3: optional self-correcting retry loop ────────────────────────
    # Controlled by DIALEKT_SQL_RETRY env var (default "1" / on).
    # When on, a pre-flight EXPLAIN validates the SQL before we execute it.
    # On failure, SQLRetryLoop asks a local LLM to fix the SQL using the
    # PG error message as feedback, and retries up to max_retries times.
    # Callers can disable per-request by passing {"retry": false} in the body.
    # `retry_context` may include {"question": "...", "agent_id": "..."} to
    # give the fix-up LLM more context.
    import os
    retry_enabled = (
        body.get("retry", True)
        and os.environ.get("DIALEKT_SQL_RETRY", "1").lower() in ("1", "true", "yes")
    )
    retry_context = body.get("retry_context") or {}
    retry_attempts_log: list[dict] = []
    if retry_enabled:
        sql, retry_attempts_log = await _retry_fix_sql(conn_id, sql, retry_context)

    pool = await _get_pool(conn_id, conn)
    async with pool.acquire() as c:
        # EXPLAIN check — warn if estimated rows > 10k
        explain_warning = None
        try:
            plan_rows = await c.fetch(f"EXPLAIN (FORMAT JSON) {sql}")
            plan = json.loads(plan_rows[0][0])
            est = plan[0]["Plan"].get("Plan Rows", 0)
            if est > 10_000:
                explain_warning = f"Query may return ~{est:,} rows — consider adding a LIMIT clause."
        except Exception:
            pass

        # Execute in READ ONLY transaction with timeout
        try:
            async with c.transaction(readonly=True):
                result = await asyncio.wait_for(
                    c.fetch(sql),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            raise HTTPException(408, f"Query timed out after {timeout}s")
        except asyncpg.PostgresError as e:
            raise HTTPException(400, f"SQL error: {e}")

    if not result:
        payload: dict = {"columns": [], "rows": [], "row_count": 0, "warning": explain_warning}
    else:
        columns = list(result[0].keys())
        rows = result[:row_limit]
        truncated = len(result) > row_limit
        payload = {
            "columns": columns,
            "rows": [[str(v) if v is not None else None for v in r.values()] for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
            "row_limit": row_limit,
            "warning": explain_warning,
        }

    if retry_attempts_log:
        payload["retry_attempts"] = retry_attempts_log
        payload["executed_sql"] = sql
    return payload


# ── Goal 8.3 retry helper ─────────────────────────────────────────────────────

async def _retry_fix_sql(
    conn_id: str,
    sql: str,
    retry_context: dict,
) -> tuple[str, list[dict]]:
    """Validate SQL via EXPLAIN; on failure, ask a local LLM to fix it
    (up to SQLRetryLoop.max_retries). Returns (final_sql, attempt_log).
    Always returns — even if retries exhausted — the last SQL tried, so
    the normal execution path surfaces the error to the caller.
    """
    from dialekt.llm.retry_loop import SQLRetryLoop, validate_sql

    # First check: is the initial SQL already valid? If so, short-circuit.
    ok, _ = await validate_sql(conn_id, sql)
    if ok:
        return sql, []

    loop = SQLRetryLoop(conn_id, max_retries=3)
    log.warning(f"🔄 SQL retry: initial SQL failed EXPLAIN validation; starting fix-up loop")

    async def llm_regenerate(bad_sql: str, error_feedback: str) -> str:
        attempt_n = len(loop.attempts) + 1
        log.warning(
            f"🔄 SQL retry attempt {attempt_n}/{loop.max_retries} — "
            f"previous error: {error_feedback.splitlines()[0][:120]}"
        )
        return await _ollama_fix_sql(
            bad_sql=bad_sql,
            error_msg=error_feedback,
            question=retry_context.get("question", ""),
            schema_hint=retry_context.get("schema_hint", ""),
        )

    try:
        # SQLRetryLoop expects a full code block; give it a fenced wrapper.
        fenced = f"```sql\n{sql}\n```"
        fixed_fenced = await loop.validate_and_maybe_retry(fenced, llm_regenerate)
        # Extract the corrected SQL back out of the fence.
        import re as _re
        m = _re.search(r"```(?:sql)?\s*([\s\S]+?)```", fixed_fenced, _re.IGNORECASE)
        fixed_sql = m.group(1).strip() if m else fixed_fenced.strip()
        if fixed_sql != sql:
            log.info(f"🔄 SQL retry succeeded on attempt {len(loop.attempts)} — using corrected SQL")
        return fixed_sql, loop.attempts
    except Exception as e:
        # Retries exhausted or regeneration failed — fall through with original SQL
        # so the caller gets the raw PG error from the execution path.
        log.warning(f"🔄 SQL retry exhausted ({e}); falling back to original SQL")
        return sql, loop.attempts


async def _ollama_fix_sql(
    bad_sql: str,
    error_msg: str,
    question: str,
    schema_hint: str,
) -> str:
    """Call local Ollama to produce a corrected SQL query.
    Returns a fenced ```sql ... ``` block (matches SQLRetryLoop expectations)."""
    import httpx as _httpx
    import os

    model = os.environ.get("DIALEKT_RETRY_MODEL", "gemma3-12b")
    base = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    prompt = (
        "You are a PostgreSQL expert. A query failed validation. Produce a corrected "
        "version. OUTPUT ONLY the corrected SQL inside a ```sql fenced block — no prose.\n\n"
    )
    if question:
        prompt += f"USER QUESTION: {question}\n\n"
    if schema_hint:
        prompt += f"SCHEMA HINT:\n{schema_hint}\n\n"
    prompt += f"FAILED SQL:\n```sql\n{bad_sql}\n```\n\nPG ERROR: {error_msg}\n\nCORRECTED SQL:"

    try:
        async with _httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{base}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            r.raise_for_status()
            data = r.json()
            text = (data.get("response") or "").strip()
    except Exception as e:
        log.warning(f"🔄 ollama fix-sql call failed: {e}")
        # Return the original so validate-and-retry breaks out of the loop.
        return f"```sql\n{bad_sql}\n```"

    # If the model produced a fenced block, return as-is; otherwise wrap.
    if "```" in text:
        return text
    return f"```sql\n{text}\n```"


@router.post("/{conn_id}/reindex")
async def reindex_schema(conn_id: str):
    """Embed table schemas for semantic search via nomic-embed-text:v1.5."""
    conn = await _require_connection(conn_id)
    pool = await _get_pool(conn_id, conn)
    from mcp_servers import schema_rag
    result = await schema_rag.reindex(conn_id, pool)
    return {"ok": True, **result}


@router.get("/{conn_id}/search")
async def search_schema(conn_id: str, q: str, k: int = 5):
    """Semantic search over indexed schemas. Returns top-k relevant tables."""
    await _require_connection(conn_id)
    from mcp_servers import schema_rag
    results = await schema_rag.search(conn_id, q, k)
    return {"results": results, "count": len(results)}
