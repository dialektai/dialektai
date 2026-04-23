"""
dialekt MySQL MCP — SQL tools for the SQL Analyst agent.

REST endpoints registered on dialekt's FastAPI app under /mysql-connections.
The SQL Analyst agent calls these via Python httpx code blocks in OI.

Security:
  - Credentials stored in OS keychain (keyring), never in DB or manifests
  - All queries executed with autocommit=False, then rolled back after fetch
  - DDL/DML detection rejects writes at parse time before execution
  - Row limit (default 1000) + query timeout (30s) enforced
"""
import asyncio
import logging
import re
import uuid
from typing import Optional

import aiomysql
from fastapi import APIRouter, HTTPException

log = logging.getLogger("dialekt.mysql")

router = APIRouter(prefix="/mysql-connections", tags=["mysql"])

# ── Keyring ──────────────────────────────────────────────────────────────────

_KEYRING_SERVICE = "dialekt.mysql"


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

_pools: dict[str, aiomysql.Pool] = {}


async def _get_pool(conn_id: str, conn: dict) -> aiomysql.Pool:
    if conn_id not in _pools:
        password = _load_password(conn_id)
        if password is None:
            raise HTTPException(400, "No credentials stored for this connection. "
                                "Re-save with a password via POST /mysql-connections.")
        try:
            pool = await aiomysql.create_pool(
                host=conn["host"],
                port=int(conn["port"]),
                db=conn["database"],
                user=conn["username"],
                password=password,
                minsize=1,
                maxsize=5,
                connect_timeout=30,
                autocommit=True,
            )
        except Exception as e:
            raise HTTPException(503, f"Cannot connect to database: {e}")
        _pools[conn_id] = pool
    return _pools[conn_id]


async def close_all_pools_mysql() -> None:
    for pool in _pools.values():
        try:
            pool.close()
            await pool.wait_closed()
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
         body.get("type", "mysql"),
         body["host"],
         int(body.get("port", 3306)),
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
            pool = _pools.pop(conn_id)
            pool.close()
            await pool.wait_closed()
    if updates:
        set_parts = [f"{k} = ?" for k in updates] + ["updated_at = datetime('now')"]
        await _db.execute(
            f"UPDATE connections SET {', '.join(set_parts)} WHERE id = ?",
            [*updates.values(), conn_id],
        )
        await _db.commit()
        if conn_id in _pools:
            pool = _pools.pop(conn_id)
            pool.close()
            await pool.wait_closed()
    return {"ok": True}


@router.delete("/{conn_id}")
async def delete_connection(conn_id: str):
    await _require_connection(conn_id)
    if conn_id in _pools:
        pool = _pools.pop(conn_id)
        pool.close()
        await pool.wait_closed()
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
            async with c.cursor() as cur:
                await cur.execute("SELECT VERSION()")
                row = await cur.fetchone()
                ver = row[0] if row else None
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
        async with c.cursor() as cur:
            await cur.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('information_schema','performance_schema','mysql','sys') "
                "ORDER BY schema_name"
            )
            rows = await cur.fetchall()
    return [r[0] for r in rows]


@router.get("/{conn_id}/schemas/{schema}/tables")
async def list_tables(conn_id: str, schema: str):
    conn = await _require_connection(conn_id)
    pool = await _get_pool(conn_id, conn)
    async with pool.acquire() as c:
        async with c.cursor() as cur:
            await cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s AND table_type='BASE TABLE' "
                "ORDER BY table_name",
                (schema,),
            )
            rows = await cur.fetchall()
    return [{"name": r[0], "type": "BASE TABLE"} for r in rows]


@router.get("/{conn_id}/schemas/{schema}/tables/{table}/describe")
async def describe_table(conn_id: str, schema: str, table: str):
    conn = await _require_connection(conn_id)
    pool = await _get_pool(conn_id, conn)
    async with pool.acquire() as c:
        async with c.cursor() as cur:
            await cur.execute(
                "SELECT column_name, column_type, is_nullable, column_default, "
                "column_key, extra "
                "FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s "
                "ORDER BY ordinal_position",
                (schema, table),
            )
            rows = await cur.fetchall()
    return [
        {
            "column": r[0],
            "type": r[1],
            "nullable": r[2] == "YES",
            "default": r[3],
            "key": r[4],
            "extra": r[5],
        }
        for r in rows
    ]


@router.get("/{conn_id}/schemas/{schema}/tables/{table}/fkeys")
async def list_foreign_keys(conn_id: str, schema: str, table: str):
    conn = await _require_connection(conn_id)
    pool = await _get_pool(conn_id, conn)
    async with pool.acquire() as c:
        async with c.cursor() as cur:
            await cur.execute(
                "SELECT constraint_name, column_name, referenced_table_name, "
                "referenced_column_name "
                "FROM information_schema.key_column_usage "
                "WHERE table_schema=%s AND table_name=%s "
                "AND referenced_table_name IS NOT NULL",
                (schema, table),
            )
            rows = await cur.fetchall()
    return [
        {
            "constraint": r[0],
            "column": r[1],
            "references": f"{schema}.{r[2]}.{r[3]}",
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
        async with c.cursor() as cur:
            await cur.execute(
                f"SELECT * FROM `{safe_schema}`.`{safe_table}` LIMIT {limit}"
            )
            rows = await cur.fetchall()
            columns = [d[0] for d in cur.description] if cur.description else []
    if not rows:
        return {"columns": columns, "rows": []}
    return {
        "columns": columns,
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

    pool = await _get_pool(conn_id, conn)

    async def _run_query():
        async with pool.acquire() as c:
            # Disable autocommit so we can roll back after the fetch
            await c.autocommit(False)
            try:
                async with c.cursor() as cur:
                    await cur.execute(sql)
                    result = await cur.fetchall()
                    columns = [d[0] for d in cur.description] if cur.description else []
                    return columns, result
            finally:
                await c.rollback()

    try:
        columns, result = await asyncio.wait_for(_run_query(), timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(408, f"Query timed out after {timeout}s")
    except aiomysql.Error as e:
        raise HTTPException(400, f"SQL error: {e}")

    if not result:
        return {"columns": columns, "rows": [], "row_count": 0, "truncated": False, "warning": None}

    rows = result[:row_limit]
    truncated = len(result) > row_limit

    return {
        "columns": columns,
        "rows": [[str(v) if v is not None else None for v in row] for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "row_limit": row_limit,
        "warning": None,
    }
