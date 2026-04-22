"""
Migration tests: existing sessions are assigned the General Assistant agent.
Also verifies the migration is idempotent (safe to run multiple times).
"""
import asyncio
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / ".dialekt"
        d.mkdir(parents=True)
        yield d


def _make_client(srv, tmp_dir):
    from fastapi.testclient import TestClient

    srv.DB_PATH       = tmp_dir / "dialekt.db"
    srv.SETTINGS_FILE = tmp_dir / "config.json"
    srv.DIALEKT_DIR   = tmp_dir

    return TestClient(srv.app, raise_server_exceptions=True)


def test_general_assistant_seeded_on_fresh_db(tmp_dir):
    import server as srv

    originals = (srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR)
    try:
        with _make_client(srv, tmp_dir) as client:
            r = client.get("/agents")
            assert r.status_code == 200
            agents = r.json()
            ga = [a for a in agents if a["name"] == "General Assistant"]
            assert len(ga) == 1
            assert ga[0]["status"] == "published"
    finally:
        srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = originals


def test_existing_sessions_get_general_assistant_agent(tmp_dir):
    """Simulate sessions that existed before agents were introduced (agent_id = NULL)."""
    import aiosqlite
    import server as srv

    originals = (srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR)
    db_path = tmp_dir / "dialekt.db"

    # Pre-populate DB with sessions that have no agent_id column
    async def seed_old_db():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    model TEXT NOT NULL DEFAULT 'gemma3-12b',
                    title TEXT,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    type TEXT NOT NULL,
                    format TEXT,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.execute(
                "INSERT INTO sessions (id, model, title) VALUES (?,?,?)",
                ("old-session-001", "gemma3-12b", "Old Session"),
            )
            await db.commit()

    asyncio.run(seed_old_db())

    try:
        srv.DB_PATH       = db_path
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR   = tmp_dir

        with TestClient(srv.app, raise_server_exceptions=True) as client:
            # Migration should have run; old session should now have agent_id set
            r = client.get("/sessions")
            assert r.status_code == 200
            sessions = r.json()
            old = [s for s in sessions if s["id"] == "old-session-001"]
            assert len(old) == 1
            assert old[0].get("agent_id") is not None

            # The assigned agent should be General Assistant
            agent_id = old[0]["agent_id"]
            r = client.get(f"/agents/{agent_id}")
            assert r.status_code == 200
            assert r.json()["name"] == "General Assistant"
    finally:
        srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = originals


def test_migration_is_idempotent(tmp_dir):
    """Running migration twice doesn't create duplicate General Assistant agents."""
    import server as srv

    originals = (srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR)
    try:
        srv.DB_PATH       = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR   = tmp_dir

        async def run_migration_twice():
            import aiosqlite
            async with aiosqlite.connect(str(srv.DB_PATH)) as db_conn:
                db_conn.row_factory = aiosqlite.Row
                await db_conn.execute("PRAGMA journal_mode=WAL")
                await db_conn.execute("PRAGMA foreign_keys=ON")
                old_db = srv.db
                srv.db = db_conn
                await srv._init_db()
                await srv._migrate_agents()
                await srv._migrate_agents()  # second call must be a no-op
                cursor = await db_conn.execute(
                    "SELECT COUNT(*) FROM agents WHERE name = 'General Assistant'"
                )
                count = (await cursor.fetchone())[0]
                srv.db = old_db
                return count

        count = asyncio.run(run_migration_twice())
        assert count == 1, f"Expected 1 General Assistant, got {count}"
    finally:
        srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = originals


# Need TestClient import at module level for the fixture above
from fastapi.testclient import TestClient  # noqa: E402
