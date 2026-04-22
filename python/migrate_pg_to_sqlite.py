#!/usr/bin/env python3
"""
dialekt v0.8.x → v0.9.x database migration
Copies sessions + messages from PostgreSQL to SQLite (~/.dialekt/dialekt.db)

SAFETY GUARANTEES:
  • PostgreSQL is never modified or deleted — this script only reads from it
  • If the SQLite target already exists, a timestamped backup is created first
  • If the migration fails mid-way, the backup is automatically restored
  • --dry-run shows what would happen without writing anything

Usage:
  python migrate_pg_to_sqlite.py
  python migrate_pg_to_sqlite.py --dsn "postgresql://user:pass@host:5432/dialekt"
  python migrate_pg_to_sqlite.py --dry-run
"""
import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

DIALEKT_DIR = Path.home() / ".dialekt"
SQLITE_PATH = DIALEKT_DIR / "dialekt.db"
OLD_SETTINGS = Path.home() / ".config" / "dialekt" / "settings.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    model         TEXT NOT NULL DEFAULT 'gemma3-12b',
    title         TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    type       TEXT NOT NULL,
    format     TEXT,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"


def ok(msg):    print(f"  {_GREEN}✓{_RESET} {msg}")
def info(msg):  print(f"  {_CYAN}→{_RESET} {msg}")
def warn(msg):  print(f"  {_YELLOW}⚠{_RESET} {msg}")
def err(msg):   print(f"  {_RED}✗{_RESET} {msg}")
def hr():       print("  " + "─" * 58)


def _backup_sqlite() -> Path | None:
    """Create a timestamped backup of the existing SQLite DB. Returns backup path."""
    if not SQLITE_PATH.exists():
        return None
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = SQLITE_PATH.with_suffix(f".backup_{ts}.db")
    shutil.copy2(SQLITE_PATH, backup)
    ok(f"Existing DB backed up → {backup.name}")
    return backup


def _restore_backup(backup: Path | None):
    """Restore backup if something went wrong."""
    if backup and backup.exists():
        shutil.copy2(backup, SQLITE_PATH)
        warn(f"Migration failed — original DB restored from {backup.name}")


def migrate(pg_dsn: str, dry_run: bool = False) -> bool:
    try:
        import asyncpg
    except ImportError:
        err("asyncpg not installed.")
        err("Run: pip install asyncpg")
        return False

    import asyncio

    result = {"ok": False, "sessions": 0, "messages": 0}

    async def _fetch():
        info(f"Connecting to PostgreSQL: {pg_dsn.split('@')[-1]}")
        try:
            pg = await asyncpg.connect(pg_dsn, timeout=10)
        except Exception as e:
            err(f"Cannot connect to PostgreSQL: {e}")
            return None, None

        sessions = await pg.fetch(
            "SELECT id, model, title, message_count, created_at, updated_at "
            "FROM sessions ORDER BY created_at"
        )
        messages = await pg.fetch(
            "SELECT id, session_id, role, type, format, content, created_at "
            "FROM messages ORDER BY created_at"
        )
        await pg.close()
        return sessions, messages

    sessions, messages = asyncio.run(_fetch())
    if sessions is None:
        return False

    ok(f"Read from PostgreSQL: {len(sessions)} sessions, {len(messages)} messages")

    if dry_run:
        hr()
        warn("DRY RUN — nothing written. Re-run without --dry-run to apply.")
        return True

    # Backup existing SQLite DB (if any)
    backup = _backup_sqlite()
    DIALEKT_DIR.mkdir(parents=True, exist_ok=True)

    # Write to a temp file first — rename on success (atomic-ish)
    tmp_path = SQLITE_PATH.with_suffix(".tmp")
    try:
        con = sqlite3.connect(str(tmp_path))
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(_SCHEMA)

        with con:  # single transaction — all-or-nothing
            for s in sessions:
                con.execute(
                    "INSERT OR IGNORE INTO sessions"
                    "(id, model, title, message_count, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (str(s["id"]), s["model"], s["title"], s["message_count"],
                     s["created_at"].isoformat(), s["updated_at"].isoformat()),
                )
            for m in messages:
                con.execute(
                    "INSERT OR IGNORE INTO messages"
                    "(id, session_id, role, type, format, content, created_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (str(m["id"]), str(m["session_id"]), m["role"], m["type"],
                     m["format"], m["content"], m["created_at"].isoformat()),
                )

        # Verify counts match
        s_count = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        m_count = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        con.close()

        if s_count != len(sessions) or m_count != len(messages):
            raise RuntimeError(
                f"Row count mismatch: got {s_count}/{m_count}, "
                f"expected {len(sessions)}/{len(messages)}"
            )

        # Atomic rename
        tmp_path.replace(SQLITE_PATH)
        ok(f"Written to {SQLITE_PATH}")
        ok(f"Verified: {s_count} sessions, {m_count} messages")

    except Exception as e:
        con.close() if "con" in dir() else None
        tmp_path.unlink(missing_ok=True)
        _restore_backup(backup)
        err(f"Migration failed: {e}")
        return False

    # Migrate settings file location
    new_config = DIALEKT_DIR / "config.json"
    if OLD_SETTINGS.exists() and not new_config.exists():
        shutil.copy2(OLD_SETTINGS, new_config)
        ok(f"Settings copied to {new_config}")
        info("Original settings at ~/.config/dialekt/ left untouched")

    result["ok"] = True
    result["sessions"] = len(sessions)
    result["messages"] = len(messages)
    return True


def main():
    print(f"\n{_BOLD}dialekt — PostgreSQL → SQLite Migration{_RESET}")
    print(f"  Target: {SQLITE_PATH}")
    hr()
    print(f"  {_YELLOW}Note:{_RESET} PostgreSQL data is never modified or deleted.")
    print(f"  This script only reads from PostgreSQL and writes to SQLite.")
    hr()

    parser = argparse.ArgumentParser(
        description="Migrate dialekt conversation history from PostgreSQL to SQLite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dsn", default=None,
                        help="PostgreSQL connection string (postgresql://user:pass@host:5432/db)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be migrated without writing anything")
    args = parser.parse_args()

    pg_dsn = args.dsn
    if not pg_dsn:
        if OLD_SETTINGS.exists():
            try:
                stored = json.loads(OLD_SETTINGS.read_text())
                pg_dsn = stored.get("pg_dsn")
                if pg_dsn:
                    info(f"Found DSN in old settings file")
            except Exception:
                pass
    if not pg_dsn:
        print()
        pg_dsn = input("  PostgreSQL DSN (e.g. postgresql://user:pass@localhost:5432/dialekt): ").strip()
    if not pg_dsn:
        err("No DSN provided — aborting.")
        sys.exit(1)

    print()
    success = migrate(pg_dsn, dry_run=args.dry_run)
    hr()
    if success:
        ok("Migration complete.")
        if not args.dry_run:
            print(f"\n  Next: start dialekt normally. Your history will be in SQLite.")
            print(f"  Your PostgreSQL database is untouched — you can verify before removing it.\n")
    else:
        err("Migration failed. Check the error above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
