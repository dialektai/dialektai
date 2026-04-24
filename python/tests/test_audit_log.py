"""Tests for dialekt.audit — the universal audit_log table + log_event
helper introduced in M2 Month 1.

See docs/M2_MCP_DESIGN.md Decision 7 for the design rationale.
"""
import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path

import aiosqlite


def test_audit_schema_creates_table_and_indexes():
    from dialekt.audit import AUDIT_SCHEMA

    con = sqlite3.connect(":memory:")
    con.executescript(AUDIT_SCHEMA)

    tables = {
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "audit_log" in tables

    cols = {r[1] for r in con.execute("PRAGMA table_info(audit_log)").fetchall()}
    expected_cols = {
        "id",
        "ts",
        "agent_id",
        "binding_id",
        "kind",
        "target",
        "action",
        "result",
        "duration_ms",
        "error_kind",
        "extra_json",
    }
    assert expected_cols <= cols, f"missing columns: {expected_cols - cols}"

    indexes = {
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='audit_log'"
        ).fetchall()
    }
    assert "idx_audit_log_ts" in indexes
    assert "idx_audit_log_agent_id" in indexes
    assert "idx_audit_log_kind" in indexes
    con.close()


def test_audit_schema_idempotent():
    """Running the schema twice must not fail — uses IF NOT EXISTS everywhere."""
    from dialekt.audit import AUDIT_SCHEMA

    con = sqlite3.connect(":memory:")
    con.executescript(AUDIT_SCHEMA)
    con.executescript(AUDIT_SCHEMA)
    con.close()


def test_log_event_writes_row_and_returns_id():
    from dialekt.audit import AUDIT_SCHEMA, log_event

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(AUDIT_SCHEMA)

            row_id = await log_event(
                db,
                kind="mcp_tool_call",
                action="list_repos",
                result="success",
                agent_id="agent-a",
                binding_id="binding-1",
                target="github",
                duration_ms=42,
            )
            assert isinstance(row_id, int) and row_id > 0

            cursor = await db.execute(
                "SELECT * FROM audit_log WHERE id=?", (row_id,)
            )
            row = await cursor.fetchone()
            assert row["kind"] == "mcp_tool_call"
            assert row["action"] == "list_repos"
            assert row["result"] == "success"
            assert row["agent_id"] == "agent-a"
            assert row["binding_id"] == "binding-1"
            assert row["target"] == "github"
            assert row["duration_ms"] == 42
            assert row["error_kind"] is None
            assert row["extra_json"] is None
            assert row["ts"] is not None

    asyncio.run(run())


def test_log_event_minimal_kwargs():
    """Only kind/action/result are required; everything else nullable."""
    from dialekt.audit import AUDIT_SCHEMA, log_event

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(AUDIT_SCHEMA)

            await log_event(
                db, kind="system", action="startup", result="success"
            )

            cursor = await db.execute("SELECT * FROM audit_log")
            row = await cursor.fetchone()
            assert row["kind"] == "system"
            assert row["action"] == "startup"
            assert row["result"] == "success"
            for nullable in (
                "agent_id",
                "binding_id",
                "target",
                "duration_ms",
                "error_kind",
                "extra_json",
            ):
                assert row[nullable] is None

    asyncio.run(run())


def test_log_event_serializes_extra_as_json():
    from dialekt.audit import AUDIT_SCHEMA, log_event

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(AUDIT_SCHEMA)

            await log_event(
                db,
                kind="mcp_tool_call",
                action="call",
                result="error",
                error_kind="timeout",
                extra={"retry_count": 3, "limit": 60, "server": "github"},
            )

            cursor = await db.execute("SELECT extra_json FROM audit_log")
            row = await cursor.fetchone()
            parsed = json.loads(row["extra_json"])
            assert parsed == {
                "retry_count": 3,
                "limit": 60,
                "server": "github",
            }

    asyncio.run(run())


def test_log_event_concurrent_writes_preserve_all_rows():
    """50 concurrent log_event calls on one connection — no lost rows, unique ids."""
    from dialekt.audit import AUDIT_SCHEMA, log_event

    async def run(path: Path):
        async with aiosqlite.connect(str(path)) as db:
            await db.executescript(AUDIT_SCHEMA)

            async def one(i: int) -> int:
                return await log_event(
                    db,
                    kind="mcp_tool_call",
                    action=f"call_{i}",
                    result="success",
                    agent_id=f"a{i % 5}",
                )

            ids = await asyncio.gather(*[one(i) for i in range(50)])
            assert len(set(ids)) == 50, "row ids collided — concurrency unsafe"

            cursor = await db.execute("SELECT COUNT(*) FROM audit_log")
            count = (await cursor.fetchone())[0]
            assert count == 50

    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(run(Path(tmp) / "audit.db"))


def test_server_schema_includes_audit_log():
    """server._SCHEMA must wire AUDIT_SCHEMA so the main DB picks it up at startup."""
    import sqlite3 as _sq
    from server import _SCHEMA

    con = _sq.connect(":memory:")
    con.executescript(_SCHEMA)
    tables = {
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "audit_log" in tables, (
        "server._SCHEMA must include audit_log — wire AUDIT_SCHEMA into it"
    )
    con.close()
