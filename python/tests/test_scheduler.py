"""Tests for the v0.27 scheduled-trigger runtime.

Strategy: every test injects a deterministic interpreter-and-chat
stand-in through the CronSession constructor, so neither Open
Interpreter nor real network is touched. The only "real" thing that
runs is APScheduler — and only in the one E2E test that needs to
verify a cron tick actually fires a job.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _scheduled_manifest(
    *,
    schedule: str = "0 9 * * MON",
    tz: str = "Asia/Almaty",
    policy: str = "run_on_startup",
    message: str | None = "Test trigger message.",
    destination: str = "notification",
    telegram_chat_id: str | None = None,
) -> str:
    """Build a minimal manifest YAML the runner can parse. We don't run
    these through the strict ManifestValidator — the runner reads the
    YAML directly via PyYAML, so the YAML just needs the fields the
    runner pokes at."""
    msg_block = f"\n  message: |\n    {message}" if message else ""
    dest_block = f'    type: "{destination}"'
    if telegram_chat_id:
        dest_block += f'\n    telegram_chat_id: "{telegram_chat_id}"'
    return f"""\
metadata:
  name: "Test agent"
trigger:
  type: "scheduled"
  schedule: "{schedule}"
  timezone: "{tz}"
  missed_run_policy: "{policy}"{msg_block}
output:
  format: "markdown"
  streaming: false
  destination:
{dest_block}
"""


_TEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    manifest_yaml TEXT,
    version       TEXT NOT NULL DEFAULT '1.0.0',
    status        TEXT NOT NULL DEFAULT 'draft',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def _setup_db(path: Path) -> aiosqlite.Connection:
    """Create a fresh DB with just enough schema to exercise the
    scheduler in isolation. We deliberately don't pull server._SCHEMA
    here — test isolation matters more than DRY, and a parallel agent
    can break server.py at import time on a feature totally unrelated
    to scheduled triggers."""
    from dialekt.audit import AUDIT_SCHEMA
    from dialekt.scheduler import SCHEDULED_RUNS_SCHEMA

    db = await aiosqlite.connect(str(path))
    db.row_factory = aiosqlite.Row
    await db.executescript(_TEST_SCHEMA + AUDIT_SCHEMA + SCHEDULED_RUNS_SCHEMA)
    await db.commit()
    return db


async def _insert_agent(db: aiosqlite.Connection, agent_id: str, manifest_yaml: str) -> None:
    await db.execute(
        "INSERT INTO agents (id, name, manifest_yaml, status) VALUES (?, ?, ?, 'published')",
        (agent_id, f"Test {agent_id}", manifest_yaml),
    )
    await db.commit()


def _run(coro):
    return asyncio.run(coro)


def _stub_interpreter(*_a, **_kw):
    """Substitute for server.make_interpreter — returns a sentinel
    that the stub chat_runner recognises. No Open Interpreter import."""
    class _Stub:
        chat_calls: list[str] = []
    return _Stub()


async def _stub_chat_runner(interpreter, message: str) -> str:
    """Stand-in for the real chat runner. Records the message and
    returns a deterministic completion."""
    interpreter.chat_calls = getattr(interpreter, "chat_calls", []) + [message]
    return f"OK: handled {message[:60]!r}"


# ── missed_run_policy ────────────────────────────────────────────────────────

def test_missed_run_policy_run_on_startup_no_history_fires():
    from dialekt.scheduler.missed_run_policy import (
        MissedAgent, MissedRunPolicy, decide_missed_runs,
    )
    fired = decide_missed_runs([
        MissedAgent("a1", "0 9 * * *", "UTC", MissedRunPolicy.RUN_ON_STARTUP, None),
    ])
    assert fired == ["a1"]


def test_missed_run_policy_skip_never_fires():
    from dialekt.scheduler.missed_run_policy import (
        MissedAgent, MissedRunPolicy, decide_missed_runs,
    )
    long_ago = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fired = decide_missed_runs([
        MissedAgent("a1", "* * * * *", "UTC", MissedRunPolicy.SKIP, long_ago),
    ])
    assert fired == []


def test_missed_run_policy_replays_only_when_window_passed():
    from dialekt.scheduler.missed_run_policy import (
        MissedAgent, MissedRunPolicy, decide_missed_runs,
    )
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    # Last run 1h ago; daily 9am UTC schedule — next fire after last_run
    # is "tomorrow 9am" which is > now → don't replay
    last = datetime(2026, 4, 27, 11, 0, tzinfo=timezone.utc)
    fired = decide_missed_runs(
        [MissedAgent("a1", "0 9 * * *", "UTC",
                     MissedRunPolicy.RUN_ON_STARTUP, last)],
        now=now,
    )
    assert fired == []
    # Last run a week ago; should replay
    week_ago = datetime(2026, 4, 20, 11, 0, tzinfo=timezone.utc)
    fired = decide_missed_runs(
        [MissedAgent("a1", "0 9 * * *", "UTC",
                     MissedRunPolicy.RUN_ON_STARTUP, week_ago)],
        now=now,
    )
    assert fired == ["a1"]


def test_missed_run_policy_invalid_timezone_drops_agent_silently():
    from dialekt.scheduler.missed_run_policy import (
        MissedAgent, MissedRunPolicy, decide_missed_runs,
    )
    fired = decide_missed_runs([
        MissedAgent("a1", "0 9 * * *", "Not/A/Real/TZ",
                    MissedRunPolicy.RUN_ON_STARTUP, None),
    ])
    assert fired == []


# ── CronSession ──────────────────────────────────────────────────────────────

def test_cron_session_records_success_run(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "test.db")
        await _insert_agent(db, "ag-1", _scheduled_manifest(message="Привет"))
        agent = dict(
            (await (await db.execute(
                "SELECT id, name, manifest_yaml FROM agents WHERE id=?", ("ag-1",)
            )).fetchone())
        )

        from dialekt.scheduler.cron_session import CronSession
        sess = CronSession(
            agent_id="ag-1", agent=agent, db=db,
            interpreter_factory=_stub_interpreter,
            chat_runner=_stub_chat_runner,
        )
        result = await sess.run()

        assert result.status == "success"
        assert "Привет" in result.output  # stub echoed the message
        assert result.error is None
        assert result.duration_ms >= 0

        cur = await db.execute(
            "SELECT status, output, completed_at FROM scheduled_runs WHERE id=?",
            (result.run_id,),
        )
        row = await cur.fetchone()
        assert row["status"] == "success"
        assert row["output"] == result.output
        assert row["completed_at"] is not None
        await db.close()

    _run(run())


def test_cron_session_uses_default_when_message_missing(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "ag-2", _scheduled_manifest(message=None))
        agent = dict(
            (await (await db.execute(
                "SELECT id, name, manifest_yaml FROM agents WHERE id=?", ("ag-2",)
            )).fetchone())
        )
        from dialekt.scheduler.cron_session import CronSession, DEFAULT_TRIGGER_MESSAGE
        sess = CronSession(
            agent_id="ag-2", agent=agent, db=db,
            interpreter_factory=_stub_interpreter,
            chat_runner=_stub_chat_runner,
        )
        assert sess.trigger_message == DEFAULT_TRIGGER_MESSAGE
        await db.close()

    _run(run())


def test_cron_session_override_message_wins(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "ag-3", _scheduled_manifest(message="manifest"))
        agent = dict(
            (await (await db.execute(
                "SELECT id, name, manifest_yaml FROM agents WHERE id=?", ("ag-3",)
            )).fetchone())
        )
        from dialekt.scheduler.cron_session import CronSession
        sess = CronSession(
            agent_id="ag-3", agent=agent, db=db,
            override_message="forced-by-test",
            interpreter_factory=_stub_interpreter,
            chat_runner=_stub_chat_runner,
        )
        assert sess.trigger_message == "forced-by-test"
        await db.close()

    _run(run())


def test_cron_session_records_failure_on_chat_exception(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "ag-4", _scheduled_manifest())
        agent = dict(
            (await (await db.execute(
                "SELECT id, name, manifest_yaml FROM agents WHERE id=?", ("ag-4",)
            )).fetchone())
        )
        async def crashing_runner(_itp, _msg):
            raise RuntimeError("boom")

        from dialekt.scheduler.cron_session import CronSession
        sess = CronSession(
            agent_id="ag-4", agent=agent, db=db,
            interpreter_factory=_stub_interpreter,
            chat_runner=crashing_runner,
        )
        result = await sess.run()
        assert result.status == "failed"
        assert "boom" in (result.error or "")
        await db.close()

    _run(run())


def test_cron_session_records_timeout(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "ag-5", _scheduled_manifest())
        agent = dict(
            (await (await db.execute(
                "SELECT id, name, manifest_yaml FROM agents WHERE id=?", ("ag-5",)
            )).fetchone())
        )
        async def slow_runner(_itp, _msg):
            await asyncio.sleep(2)
            return "never"

        from dialekt.scheduler.cron_session import CronSession
        sess = CronSession(
            agent_id="ag-5", agent=agent, db=db,
            interpreter_factory=_stub_interpreter,
            chat_runner=slow_runner,
            timeout_seconds=0,
        )
        result = await sess.run()
        assert result.status == "timeout"
        assert "timeout" in (result.error or "").lower()
        await db.close()

    _run(run())


# ── Delivery ─────────────────────────────────────────────────────────────────

def test_delivery_notification_writes_row(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "ag-n", _scheduled_manifest(destination="notification"))
        agent_row = await (await db.execute(
            "SELECT id, manifest_yaml FROM agents WHERE id=?", ("ag-n",)
        )).fetchone()
        from dialekt.scheduler.delivery import deliver

        result = await deliver(
            db=db, agent=dict(agent_row), run_id="run-x",
            output="hello world", triggered_at=datetime.now(timezone.utc),
        )
        assert result.status == "sent"
        cur = await db.execute("SELECT body FROM scheduled_notifications WHERE run_id='run-x'")
        row = await cur.fetchone()
        assert row["body"] == "hello world"
        await db.close()

    _run(run())


def test_delivery_skips_empty_output(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "ag-empty", _scheduled_manifest(destination="notification"))
        agent_row = await (await db.execute(
            "SELECT id, manifest_yaml FROM agents WHERE id=?", ("ag-empty",)
        )).fetchone()
        from dialekt.scheduler.delivery import deliver
        result = await deliver(
            db=db, agent=dict(agent_row), run_id="run-empty",
            output="   ", triggered_at=datetime.now(timezone.utc),
        )
        assert result.status == "skipped"
        await db.close()

    _run(run())


def test_delivery_filesystem_expands_placeholders(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        out_dir = tmp_path / "out"
        manifest = _scheduled_manifest()
        manifest = manifest.replace(
            '    type: "notification"',
            f'    type: "filesystem"\n    path: "{out_dir}/{{{{date}}}}/{{{{agent_id}}}}.txt"',
        )
        await _insert_agent(db, "ag-fs", manifest)
        agent_row = await (await db.execute(
            "SELECT id, manifest_yaml FROM agents WHERE id=?", ("ag-fs",)
        )).fetchone()
        from dialekt.scheduler.delivery import deliver
        when = datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc)
        result = await deliver(
            db=db, agent=dict(agent_row), run_id="run-fs",
            output="report body", triggered_at=when,
        )
        assert result.status == "sent"
        target = out_dir / "2026-04-27" / "ag-fs.txt"
        assert target.exists()
        assert target.read_text() == "report body"
        await db.close()

    _run(run())


def test_delivery_telegram_secret_resolution_failure(tmp_path):
    """When the secret reference can't resolve, return failed without
    crashing — fixture intentionally points at a key the keyring doesn't have."""
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        manifest = _scheduled_manifest(
            destination="email_or_telegram",
            telegram_chat_id="${secrets.nonexistent_iba_chat_id}",
        )
        await _insert_agent(db, "ag-tg", manifest)
        agent_row = await (await db.execute(
            "SELECT id, manifest_yaml FROM agents WHERE id=?", ("ag-tg",)
        )).fetchone()
        from dialekt.scheduler.delivery import deliver
        with patch("dialekt.secrets.get_secret", return_value=None):
            result = await deliver(
                db=db, agent=dict(agent_row), run_id="run-tg",
                output="hi", triggered_at=datetime.now(timezone.utc),
            )
        assert result.status == "failed"
        assert "telegram" in (result.detail or "").lower()
        await db.close()

    _run(run())


def test_delivery_chunks_long_telegram_messages():
    """Pure-unit test for the chunker — no DB / network."""
    from dialekt.scheduler.delivery import _chunk_for_telegram
    # Two ~3000-char paragraphs separated by a blank line — the chunker
    # should split at the boundary, not in the middle of either run.
    text = ("x" * 3000) + "\n\n" + ("y" * 3000) + "\n\nfinal paragraph"
    chunks = _chunk_for_telegram(text, limit=4000)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 4000
    assert "final paragraph" in chunks[-1]


def test_delivery_unknown_destination_type_returns_failed(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        manifest = _scheduled_manifest(destination="webhook")  # not supported
        await _insert_agent(db, "ag-webh", manifest)
        agent_row = await (await db.execute(
            "SELECT id, manifest_yaml FROM agents WHERE id=?", ("ag-webh",)
        )).fetchone()
        from dialekt.scheduler.delivery import deliver
        result = await deliver(
            db=db, agent=dict(agent_row), run_id="run-webh",
            output="hi", triggered_at=datetime.now(timezone.utc),
        )
        assert result.status == "failed"
        assert "unknown destination" in (result.detail or "").lower()
        await db.close()

    _run(run())


# ── DialektScheduler integration ─────────────────────────────────────────────

def test_scheduler_reload_registers_only_scheduled_agents(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "sched-1", _scheduled_manifest())
        await _insert_agent(db, "interactive-1",
                            'metadata:\n  name: "I"\ntrigger:\n  type: "interactive"\n')
        from dialekt.scheduler.runner import DialektScheduler
        sched = DialektScheduler(db)
        diff = await sched.reload()
        assert diff["added"] == 1
        assert diff["updated"] == 0
        ids = [j.id for j in sched._scheduler.get_jobs()]
        assert ids == ["agent_sched-1"]
        await db.close()

    _run(run())


def test_scheduler_run_now_executes_through_full_pipeline(tmp_path):
    """End-to-end without APScheduler ticking: run_now → CronSession
    (with stub OI) → delivery (notification) → audit row."""
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "sched-ax",
                            _scheduled_manifest(message="hello", destination="notification"))
        from dialekt.scheduler.runner import DialektScheduler
        from dialekt.scheduler.cron_session import CronSession

        def factory(**kwargs):
            return CronSession(
                **kwargs,
                interpreter_factory=_stub_interpreter,
                chat_runner=_stub_chat_runner,
            )
        sched = DialektScheduler(db, cron_session_factory=factory)
        result = await sched.run_now("sched-ax")
        assert result.status == "success"

        notif = await (await db.execute(
            "SELECT body FROM scheduled_notifications WHERE run_id=?", (result.run_id,)
        )).fetchone()
        assert notif is not None and "hello" in notif["body"]

        audit = await (await db.execute(
            "SELECT kind, target, action, result FROM audit_log WHERE kind='scheduled_run'"
        )).fetchall()
        assert len(audit) == 1
        assert audit[0]["target"] == "sched-ax"
        assert audit[0]["result"] == "success"
        await db.close()

    _run(run())


def test_scheduler_status_reports_jobs(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "sched-stat", _scheduled_manifest(schedule="*/5 * * * *"))
        from dialekt.scheduler.runner import DialektScheduler
        sched = DialektScheduler(db)
        await sched.reload()
        snap = await sched.status()
        assert snap["running"] is False  # we didn't call .start()
        agent_ids = [j["agent_id"] for j in snap["jobs"]]
        assert agent_ids == ["sched-stat"]
        await db.close()

    _run(run())


def test_scheduler_reload_is_idempotent(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "sched-i", _scheduled_manifest())
        from dialekt.scheduler.runner import DialektScheduler
        sched = DialektScheduler(db)
        first = await sched.reload()
        assert first["added"] == 1
        second = await sched.reload()
        assert second["updated"] == 1
        assert second["added"] == 0
        await db.close()

    _run(run())


def test_scheduler_reload_drops_removed_agent(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        await _insert_agent(db, "sched-d", _scheduled_manifest())
        from dialekt.scheduler.runner import DialektScheduler
        sched = DialektScheduler(db)
        await sched.reload()
        assert len(sched._scheduler.get_jobs()) == 1
        await db.execute("DELETE FROM agents WHERE id=?", ("sched-d",))
        await db.commit()
        diff = await sched.reload()
        assert diff["removed"] == 1
        assert sched._scheduler.get_jobs() == []
        await db.close()

    _run(run())


def test_scheduler_run_now_fails_on_missing_agent(tmp_path):
    async def run():
        db = await _setup_db(tmp_path / "t.db")
        from dialekt.scheduler.runner import DialektScheduler
        sched = DialektScheduler(db)
        with pytest.raises(RuntimeError):
            await sched.run_now("does-not-exist")
        await db.close()

    _run(run())
