"""
dialekt ClickHouse MCP — SQL tools for the SQL Analyst agent.

REST endpoints registered on dialekt's FastAPI app under /ch-connections.
The SQL Analyst agent calls these via Python httpx code blocks in OI.

Security:
  - Credentials stored in OS keychain (keyring), never in DB or manifests
  - All queries executed with readonly=1 setting
  - DDL/DML detection rejects writes at parse time before execution
  - ClickHouse-specific dangerous keywords (SYSTEM, KILL, OPTIMIZE) are also rejected
  - Row limit (default 1000) + query timeout (30s) enforced
  - clickhouse_connect is sync; all client calls run in executor for async compat
"""
import asyncio
import logging
import re
import uuid
from typing import Optional

import clickhouse_connect
from fastapi import APIRouter, HTTPException

log = logging.getLogger("dialekt.clickhouse")

router = APIRouter(prefix="/ch-connections", tags=["clickhouse"])

# ── Keyring ──────────────────────────────────────────────────────────────────

_KEYRING_SERVICE = "dialekt.ch"


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


# ── Client factory (no pool — clickhouse_connect is lightweight per-request) ──

def _get_client(conn_id: str, conn: dict):
    """Create and return a clickhouse_connect client. Empty password is valid for ClickHouse."""
    password = _load_password(conn_id) or ""
    try:
        client = clickhouse_connect.get_client(
            host=conn["host"],
            port=int(conn["port"]),
            database=conn["database"],
            username=conn["username"],
            password=password,
        )
        return client
    except Exception as e:
        raise HTTPException(503, f"Cannot connect to database: {e}")


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
# ClickHouse-specific dangerous keywords
_CH_DANGEROUS = re.compile(r'\b(SYSTEM|KILL|OPTIMIZE)\b', re.IGNORECASE)


def _check_sql_safety(sql: str) -> None:
    """Raise HTTPException 422 if SQL contains DDL, DML, or ClickHouse-specific dangerous statements."""
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
    if _CH_DANGEROUS.search(clean):
        m = _CH_DANGEROUS.search(clean).group()
        raise HTTPException(422, f"Statement rejected: '{m}' is not allowed. Only SELECT queries are permitted.")


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
    for field in ("name", "host", "database", "username"):
        if not body.get(field):
            raise HTTPException(400, f"'{field}' is required")
    conn_id = str(uuid.uuid4())
    await _db.execute(
        "INSERT INTO connections (id, name, type, host, port, database, username, row_limit)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (conn_id,
         body["name"],
         body.get("type", "clickhouse"),
         body["host"],
         int(body.get("port", 8123)),
         body["database"],
         body["username"],
         int(body.get("row_limit", 1000))),
    )
    await _db.commit()
    _save_password(conn_id, body.get("password", ""))
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
    if updates:
        set_parts = [f"{k} = ?" for k in updates] + ["updated_at = datetime('now')"]
        await _db.execute(
            f"UPDATE connections SET {', '.join(set_parts)} WHERE id = ?",
            [*updates.values(), conn_id],
        )
        await _db.commit()
    return {"ok": True}


@router.delete("/{conn_id}")
async def delete_connection(conn_id: str):
    await _require_connection(conn_id)
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
        client = _get_client(conn_id, conn)
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: client.query("SELECT version()")
        )
        ver = result.result_rows[0][0] if result.result_rows else None
        return {"ok": True, "version": ver}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── SQL tools ────────────────────────────────────────────────────────────────

@router.get("/{conn_id}/schemas")
async def list_schemas(conn_id: str):
    conn = await _require_connection(conn_id)
    client = _get_client(conn_id, conn)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.query(
            "SELECT DISTINCT database FROM system.tables "
            "WHERE database NOT IN ('system','information_schema','INFORMATION_SCHEMA') "
            "ORDER BY database"
        )
    )
    return [r[0] for r in result.result_rows]


@router.get("/{conn_id}/schemas/{schema}/tables")
async def list_tables(conn_id: str, schema: str):
    conn = await _require_connection(conn_id)
    safe_schema = re.sub(r'[^a-zA-Z0-9_]', '', schema)
    client = _get_client(conn_id, conn)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.query(
            f"SELECT name FROM system.tables WHERE database='{safe_schema}' ORDER BY name"
        )
    )
    return [{"name": r[0], "type": "BASE TABLE"} for r in result.result_rows]


@router.get("/{conn_id}/schemas/{schema}/tables/{table}/describe")
async def describe_table(conn_id: str, schema: str, table: str):
    conn = await _require_connection(conn_id)
    safe_schema = re.sub(r'[^a-zA-Z0-9_]', '', schema)
    safe_table = re.sub(r'[^a-zA-Z0-9_]', '', table)
    client = _get_client(conn_id, conn)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.query(
            "SELECT name, type, is_in_partition_key, is_in_primary_key, is_in_sorting_key "
            "FROM system.columns "
            f"WHERE database='{safe_schema}' AND table='{safe_table}' "
            "ORDER BY position"
        )
    )
    return [
        {
            "column": r[0],
            "type": r[1],
            "in_partition_key": bool(r[2]),
            "in_primary_key": bool(r[3]),
            "in_sorting_key": bool(r[4]),
        }
        for r in result.result_rows
    ]


@router.get("/{conn_id}/schemas/{schema}/tables/{table}/fkeys")
async def list_foreign_keys(conn_id: str, schema: str, table: str):
    # ClickHouse has no FK constraints
    await _require_connection(conn_id)
    return []


@router.get("/{conn_id}/schemas/{schema}/tables/{table}/sample")
async def sample_rows(conn_id: str, schema: str, table: str, limit: int = 3):
    conn = await _require_connection(conn_id)
    if limit > 20:
        limit = 20
    safe_schema = re.sub(r'[^a-zA-Z0-9_]', '', schema)
    safe_table = re.sub(r'[^a-zA-Z0-9_]', '', table)
    client = _get_client(conn_id, conn)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.query(
            f"SELECT * FROM `{safe_schema}`.`{safe_table}` LIMIT {limit}"
        )
    )
    columns = result.column_names
    rows = result.result_rows
    if not rows:
        return {"columns": list(columns), "rows": []}
    return {
        "columns": list(columns),
        "rows": [[str(v) if v is not None else None for v in row] for row in rows],
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

    client = _get_client(conn_id, conn)

    def _run_query():
        return client.query(sql, settings={"readonly": 1})

    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _run_query),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise HTTPException(408, f"Query timed out after {timeout}s")
    except Exception as e:
        raise HTTPException(400, f"SQL error: {e}")

    columns = list(result.column_names)
    all_rows = result.result_rows

    if not all_rows:
        return {"columns": columns, "rows": [], "row_count": 0, "truncated": False, "warning": None}

    truncated = len(all_rows) > row_limit
    rows = all_rows[:row_limit]

    return {
        "columns": columns,
        "rows": [[str(v) if v is not None else None for v in row] for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "row_limit": row_limit,
        "warning": None,
    }
