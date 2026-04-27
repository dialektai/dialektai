"""Tests for dialekt.batch.job — schema + CRUD helpers.

Mirrors the test style in ``test_audit_log.py``: free functions,
asyncio.run, in-memory SQLite. No FastAPI / Ollama needed.
"""
import asyncio
import json
import sqlite3

import aiosqlite
import pytest


def test_batch_schema_creates_tables_and_indexes():
    from dialekt.batch import BATCH_SCHEMA

    con = sqlite3.connect(":memory:")
    con.executescript(BATCH_SCHEMA)

    tables = {
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "batch_jobs" in tables
    assert "batch_job_files" in tables

    job_cols = {r[1] for r in con.execute("PRAGMA table_info(batch_jobs)").fetchall()}
    assert {
        "id", "agent_id", "tenant_id", "status", "total", "done",
        "variables_json", "error", "created_at", "updated_at",
    } <= job_cols

    file_cols = {r[1] for r in con.execute("PRAGMA table_info(batch_job_files)").fetchall()}
    assert {
        "id", "job_id", "ordinal", "input_path", "input_name",
        "output_path", "status", "duration_ms", "error",
        "started_at", "finished_at",
    } <= file_cols

    indexes = {
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert "idx_batch_jobs_agent_id" in indexes
    assert "idx_batch_jobs_status" in indexes
    assert "idx_batch_files_job_id" in indexes
    con.close()


def test_batch_schema_idempotent():
    from dialekt.batch import BATCH_SCHEMA
    con = sqlite3.connect(":memory:")
    con.executescript(BATCH_SCHEMA)
    con.executescript(BATCH_SCHEMA)
    con.close()


def test_server_schema_includes_batch_tables():
    """server._SCHEMA must wire BATCH_SCHEMA so the live DB picks it up."""
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
    assert "batch_jobs" in tables and "batch_job_files" in tables, (
        "server._SCHEMA must include batch_jobs + batch_job_files"
    )
    con.close()


def test_create_job_seeds_files_and_returns_populated_job():
    from dialekt.batch import BATCH_SCHEMA, create_job, list_files

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(BATCH_SCHEMA)

            job = await create_job(
                db,
                agent_id="agent-x",
                file_paths=["/tmp/a.txt", "/tmp/b.txt", "/tmp/c.txt"],
                variables={"instruction": "rewrite", "output_ext": "md"},
                tenant_id="tenant-1",
            )
            assert job.agent_id == "agent-x"
            assert job.tenant_id == "tenant-1"
            assert job.status == "pending"
            assert job.total == 3 and job.done == 0
            assert job.variables == {"instruction": "rewrite", "output_ext": "md"}

            files = await list_files(db, job.id)
            assert [f.ordinal for f in files] == [0, 1, 2]
            assert all(f.status == "pending" for f in files)
            assert files[0].input_name == "a.txt"
            assert files[2].input_path == "/tmp/c.txt"

    asyncio.run(run())


def test_create_job_rejects_empty_file_list():
    from dialekt.batch import BATCH_SCHEMA, create_job

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(BATCH_SCHEMA)
            with pytest.raises(ValueError, match="must not be empty"):
                await create_job(db, agent_id="x", file_paths=[])

    asyncio.run(run())


def test_increment_done_returns_new_value_atomically():
    from dialekt.batch import (
        BATCH_SCHEMA, create_job, increment_done,
    )

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(BATCH_SCHEMA)
            job = await create_job(db, agent_id="x", file_paths=["/a", "/b", "/c"])
            assert await increment_done(db, job.id) == 1
            assert await increment_done(db, job.id) == 2
            assert await increment_done(db, job.id) == 3

    asyncio.run(run())


def test_set_job_status_validates_status_value():
    from dialekt.batch import BATCH_SCHEMA, create_job, set_job_status

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(BATCH_SCHEMA)
            job = await create_job(db, agent_id="x", file_paths=["/a"])
            with pytest.raises(ValueError, match="unknown status"):
                await set_job_status(db, job.id, "totally-bogus")

    asyncio.run(run())


def test_record_file_done_and_error_persist():
    from dialekt.batch import (
        BATCH_SCHEMA, create_job, list_files,
        record_file_done, record_file_error, record_file_cancelled,
    )

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(BATCH_SCHEMA)
            job = await create_job(db, agent_id="x", file_paths=["/a", "/b", "/c"])
            files = await list_files(db, job.id)
            await record_file_done(db, files[0].id, output_path="/out/a.md", duration_ms=42)
            await record_file_error(db, files[1].id, message="boom", duration_ms=10)
            await record_file_cancelled(db, files[2].id)

            files2 = await list_files(db, job.id)
            assert files2[0].status == "done"
            assert files2[0].output_path == "/out/a.md"
            assert files2[0].duration_ms == 42
            assert files2[1].status == "error"
            assert files2[1].error == "boom"
            assert files2[1].duration_ms == 10
            assert files2[2].status == "cancelled"

    asyncio.run(run())


def test_set_job_error_marks_failed_with_message():
    from dialekt.batch import BATCH_SCHEMA, create_job, get_job, set_job_error

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(BATCH_SCHEMA)
            job = await create_job(db, agent_id="x", file_paths=["/a"])
            await set_job_error(db, job.id, "agent missing")
            j = await get_job(db, job.id)
            assert j.status == "failed"
            assert j.error == "agent missing"

    asyncio.run(run())


def test_job_to_dict_round_trips_variables():
    from dialekt.batch import BATCH_SCHEMA, create_job, get_job

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(BATCH_SCHEMA)
            job = await create_job(
                db, agent_id="x", file_paths=["/a"],
                variables={"instruction": "Перепиши", "output_ext": "md"},
            )
            d = (await get_job(db, job.id)).to_dict()
            assert d["variables"] == {"instruction": "Перепиши", "output_ext": "md"}
            assert d["agent_id"] == "x"

    asyncio.run(run())


def test_get_job_returns_none_for_unknown_id():
    from dialekt.batch import BATCH_SCHEMA, get_job

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(BATCH_SCHEMA)
            assert (await get_job(db, "no-such-job")) is None

    asyncio.run(run())


def test_cascade_delete_removes_files():
    """Deleting a job should drop its files via ON DELETE CASCADE."""
    from dialekt.batch import BATCH_SCHEMA, create_job, list_files

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript(BATCH_SCHEMA)
            job = await create_job(db, agent_id="x", file_paths=["/a", "/b"])
            await db.execute("DELETE FROM batch_jobs WHERE id = ?", (job.id,))
            await db.commit()
            assert await list_files(db, job.id) == []

    asyncio.run(run())
