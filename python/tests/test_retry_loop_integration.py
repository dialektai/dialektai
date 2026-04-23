"""
Integration tests for Goal 8.3 — SQLRetryLoop wired into the live PG /query
endpoint.

End-to-end behaviour verified here (all unit-level, no live PG needed):

- When a valid SELECT is posted, the endpoint does NOT invoke the retry path
  and returns the normal execution result.
- When an invalid SELECT is posted, the endpoint calls the Ollama fix-up,
  retries with the corrected SQL, logs each attempt with 🔄 markers, and
  returns the final result (with `retry_attempts` in the response).
- DIALEKT_SQL_RETRY=0 disables the retry path entirely (no Ollama call made).
- Per-request `retry: false` in the body disables retry for one call.
- If all retries fail, the endpoint surfaces the last error (falls back to
  the normal execution path, which raises HTTP 400).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_servers import postgres_mcp as pg_mcp


pytestmark = pytest.mark.asyncio


# ── Test helpers ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _env_default_on(monkeypatch):
    """Ensure env defaults don't leak between tests."""
    monkeypatch.setenv("DIALEKT_SQL_RETRY", "1")
    yield


@pytest.fixture
def mock_conn():
    """Patch _require_connection and _get_pool so we don't need a real DB."""
    with patch.object(pg_mcp, "_require_connection", new=AsyncMock(return_value={
        "id": "conn-x", "host": "localhost", "port": 5432,
        "database": "test", "username": "u", "row_limit": 100,
    })) as mreq, patch.object(pg_mcp, "_get_pool", new=AsyncMock()) as mpool:
        yield mreq, mpool


# ── Valid SQL: retry path must NOT engage ────────────────────────────────────

async def test_valid_sql_bypasses_retry(mock_conn):
    """If the first EXPLAIN succeeds, no Ollama call, no retry_attempts field."""
    mreq, mpool = mock_conn

    # Mock a successful pool.acquire().fetch() cycle for execution.
    fake_row = type("R", (), {"values": lambda self: ["1"], "keys": lambda self: ["?column?"]})()
    fake_c = AsyncMock()
    fake_c.fetch = AsyncMock(side_effect=[
        # first call = explain inside execute path (JSON EXPLAIN)
        [["[{\"Plan\": {\"Plan Rows\": 10}}]"]],
        # second = actual SELECT
        [fake_row],
    ])
    # transaction returns async context manager
    fake_c.transaction = lambda **kw: AsyncTxCM()
    class FakePool:
        def acquire(self):
            return FakeAcquire(fake_c)
    mpool.return_value = FakePool()

    # Pre-flight EXPLAIN called by _retry_fix_sql — make it succeed
    with patch.object(pg_mcp, "_retry_fix_sql", new=AsyncMock(return_value=("SELECT 1", []))):
        with patch("httpx.AsyncClient"):  # never used because retry_fix_sql is mocked
            result = await pg_mcp.execute_query("conn-x", {"sql": "SELECT 1"})

    assert "retry_attempts" not in result


# ── Invalid SQL: retry engages, Ollama called, corrected SQL executed ────────

async def test_invalid_sql_triggers_retry_then_succeeds(mock_conn, caplog):
    """Invalid first SQL → EXPLAIN fails → Ollama returns fix → second EXPLAIN
    passes → query runs, response includes retry_attempts + executed_sql."""
    import logging
    caplog.set_level(logging.WARNING, logger="dialekt.postgres")

    mreq, mpool = mock_conn

    # Sequence of validate_sql calls:
    #   1. initial check inside _retry_fix_sql → fail
    #   2. inside SQLRetryLoop.validate_and_maybe_retry after regenerate → success
    validate_calls = [
        (False, "column \"customerz\" does not exist"),  # initial probe
        (False, "column \"customerz\" does not exist"),  # first loop attempt, same SQL
        (True,  ""),                                      # after Ollama fix
    ]
    async def fake_validate_sql(conn_id, sql):
        return validate_calls.pop(0)

    async def fake_ollama_fix(bad_sql, error_msg, question, schema_hint):
        # Return corrected SQL in a fenced block
        return "```sql\nSELECT name FROM customers LIMIT 5\n```"

    # Mock the actual pool execution at the end — valid SELECT path
    fake_row = type("R", (), {"values": lambda self: ["Alice"], "keys": lambda self: ["name"]})()
    fake_c = AsyncMock()
    fake_c.fetch = AsyncMock(side_effect=[
        [["[{\"Plan\": {\"Plan Rows\": 5}}]"]],
        [fake_row],
    ])
    fake_c.transaction = lambda **kw: AsyncTxCM()
    class FakePool:
        def acquire(self):
            return FakeAcquire(fake_c)
    mpool.return_value = FakePool()

    with patch("dialekt.llm.retry_loop.validate_sql", side_effect=fake_validate_sql), \
         patch.object(pg_mcp, "_ollama_fix_sql", side_effect=fake_ollama_fix):
        result = await pg_mcp.execute_query(
            "conn-x",
            {
                "sql": "SELECT name FROM customerz LIMIT 5",
                "retry_context": {"question": "show me some customer names"},
            },
        )

    assert "retry_attempts" in result
    assert result["executed_sql"] == "SELECT name FROM customers LIMIT 5"
    # Retry log contains at least one 🔄 marker
    retry_logs = [rec for rec in caplog.records if "🔄" in rec.getMessage()]
    assert len(retry_logs) >= 1, f"expected 🔄 markers in logs; got: {[r.getMessage() for r in caplog.records]}"


# ── Disable via env var ───────────────────────────────────────────────────────

async def test_env_disable_bypasses_retry(mock_conn, monkeypatch):
    """DIALEKT_SQL_RETRY=0 — the retry helper must NOT be called."""
    monkeypatch.setenv("DIALEKT_SQL_RETRY", "0")

    fake_row = type("R", (), {"values": lambda self: ["1"], "keys": lambda self: ["?column?"]})()
    fake_c = AsyncMock()
    fake_c.fetch = AsyncMock(side_effect=[
        [["[{\"Plan\": {\"Plan Rows\": 1}}]"]],
        [fake_row],
    ])
    fake_c.transaction = lambda **kw: AsyncTxCM()
    class FakePool:
        def acquire(self):
            return FakeAcquire(fake_c)
    _, mpool = mock_conn
    mpool.return_value = FakePool()

    with patch.object(pg_mcp, "_retry_fix_sql", new=AsyncMock()) as mretry:
        result = await pg_mcp.execute_query("conn-x", {"sql": "SELECT 1"})
        assert mretry.await_count == 0, "retry helper should not be invoked when env=0"

    assert "retry_attempts" not in result


# ── Disable via per-request flag ──────────────────────────────────────────────

async def test_body_retry_false_bypasses_retry(mock_conn):
    """{"retry": false} in body disables retry even when env is on."""
    fake_row = type("R", (), {"values": lambda self: ["1"], "keys": lambda self: ["?column?"]})()
    fake_c = AsyncMock()
    fake_c.fetch = AsyncMock(side_effect=[
        [["[{\"Plan\": {\"Plan Rows\": 1}}]"]],
        [fake_row],
    ])
    fake_c.transaction = lambda **kw: AsyncTxCM()
    class FakePool:
        def acquire(self):
            return FakeAcquire(fake_c)
    _, mpool = mock_conn
    mpool.return_value = FakePool()

    with patch.object(pg_mcp, "_retry_fix_sql", new=AsyncMock()) as mretry:
        await pg_mcp.execute_query("conn-x", {"sql": "SELECT 1", "retry": False})
        assert mretry.await_count == 0


# ── Retries exhausted: fall back to original SQL ──────────────────────────────

async def test_retries_exhausted_falls_back_and_raises(mock_conn):
    """When Ollama never fixes the SQL, the endpoint executes the original
    bad SQL and lets PG raise — caller sees HTTP 400."""
    from fastapi import HTTPException

    async def always_fail(conn_id, sql):
        return False, "relation does not exist"
    async def ollama_keeps_failing(bad_sql, error_msg, question, schema_hint):
        return f"```sql\n{bad_sql}\n```"  # returns the same bad sql

    _, mpool = mock_conn
    # Real asyncpg.PostgresError simulation via execution raising
    import asyncpg as _pg
    fake_c = AsyncMock()
    # EXPLAIN in execution path fails (non-fatal for row-estimate step),
    # then real fetch raises.
    fake_c.fetch = AsyncMock(side_effect=[
        Exception("EXPLAIN irrelevant"),
        _pg.exceptions.UndefinedTableError("relation does not exist"),
    ])
    fake_c.transaction = lambda **kw: AsyncTxCM()
    class FakePool:
        def acquire(self):
            return FakeAcquire(fake_c)
    mpool.return_value = FakePool()

    with patch("dialekt.llm.retry_loop.validate_sql", side_effect=always_fail), \
         patch.object(pg_mcp, "_ollama_fix_sql", side_effect=ollama_keeps_failing):
        with pytest.raises(HTTPException) as exc:
            await pg_mcp.execute_query(
                "conn-x",
                {"sql": "SELECT * FROM no_such_table", "retry_context": {}},
            )
        assert exc.value.status_code == 400


# ── Plumbing: async context manager stubs ────────────────────────────────────

class AsyncTxCM:
    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): return False


class FakeAcquire:
    def __init__(self, client): self.client = client
    async def __aenter__(self): return self.client
    async def __aexit__(self, exc_type, exc, tb): return False
