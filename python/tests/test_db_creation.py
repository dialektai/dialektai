"""
Smoke test: SQLite DB is created from scratch with correct schema.
Runs in a temp dir — does not touch ~/.dialekt/.
"""
import asyncio
import sqlite3
import tempfile
from pathlib import Path


def test_schema_in_memory():
    """Verifies the schema SQL is valid and creates expected tables."""
    from server import _SCHEMA
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(_SCHEMA)

    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "sessions" in tables, "sessions table missing"
    assert "messages" in tables, "messages table missing"

    # Verify sessions columns
    cols = {r[1] for r in con.execute("PRAGMA table_info(sessions)").fetchall()}
    for expected in ("id", "model", "title", "message_count", "created_at", "updated_at"):
        assert expected in cols, f"sessions.{expected} column missing"

    # Verify messages columns
    cols = {r[1] for r in con.execute("PRAGMA table_info(messages)").fetchall()}
    for expected in ("id", "session_id", "role", "type", "format", "content", "created_at"):
        assert expected in cols, f"messages.{expected} column missing"

    con.close()


def test_db_file_created_in_fresh_dir():
    """Verifies DB file + parent directory are auto-created."""
    import aiosqlite
    from server import _SCHEMA

    async def run(db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(db_path)) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
            cursor = await db.execute("SELECT COUNT(*) FROM sessions")
            count = (await cursor.fetchone())[0]
            assert count == 0

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / ".dialekt" / "dialekt.db"
        assert not db_path.exists()
        asyncio.run(run(db_path))
        assert db_path.exists(), "DB file was not created"


def test_basic_crud():
    """Insert a session + message and verify retrieval."""
    import aiosqlite
    import uuid
    from server import _SCHEMA

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript(_SCHEMA)

            sid = str(uuid.uuid4())
            await db.execute("INSERT INTO sessions(id, model) VALUES(?, ?)", (sid, "test-model"))
            await db.commit()

            mid = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO messages(id, session_id, role, type, content) VALUES(?,?,?,?,?)",
                (mid, sid, "user", "message", "hello"),
            )
            await db.commit()

            cursor = await db.execute("SELECT content FROM messages WHERE id=?", (mid,))
            row = await cursor.fetchone()
            assert row is not None
            assert row["content"] == "hello"

    asyncio.run(run())


def test_cascade_delete():
    """Deleting a session cascades to messages."""
    import aiosqlite
    import uuid
    from server import _SCHEMA

    async def run():
        async with aiosqlite.connect(":memory:") as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript(_SCHEMA)

            sid = str(uuid.uuid4())
            await db.execute("INSERT INTO sessions(id, model) VALUES(?, ?)", (sid, "m"))
            await db.execute(
                "INSERT INTO messages(id, session_id, role, type, content) VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), sid, "user", "message", "test"),
            )
            await db.commit()

            await db.execute("DELETE FROM sessions WHERE id=?", (sid,))
            await db.commit()

            cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (sid,))
            count = (await cursor.fetchone())[0]
            assert count == 0, "Cascade delete failed — orphaned messages remain"

    asyncio.run(run())
