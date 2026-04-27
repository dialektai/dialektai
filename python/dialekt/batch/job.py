"""Job model + SQLite tables for batch processing."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite


BATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS batch_jobs (
    id             TEXT PRIMARY KEY,
    agent_id       TEXT NOT NULL,
    tenant_id      TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    total          INTEGER NOT NULL DEFAULT 0,
    done           INTEGER NOT NULL DEFAULT 0,
    variables_json TEXT,
    error          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS batch_job_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES batch_jobs(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    input_path  TEXT NOT NULL,
    input_name  TEXT NOT NULL,
    output_path TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    duration_ms INTEGER,
    error       TEXT,
    started_at  TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_batch_jobs_agent_id ON batch_jobs(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_status   ON batch_jobs(status);
CREATE INDEX IF NOT EXISTS idx_batch_files_job_id  ON batch_job_files(job_id, ordinal);
"""


JOB_STATUSES = ("pending", "running", "completed", "failed", "cancelled")
FILE_STATUSES = ("pending", "running", "done", "error", "cancelled")


@dataclass
class Job:
    id: str
    agent_id: str
    tenant_id: str | None
    status: str
    total: int
    done: int
    variables: dict[str, Any]
    error: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Job":
        raw = row["variables_json"]
        return cls(
            id=row["id"],
            agent_id=row["agent_id"],
            tenant_id=row["tenant_id"],
            status=row["status"],
            total=row["total"],
            done=row["done"],
            variables=json.loads(raw) if raw else {},
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "variables": self.variables,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class BatchFile:
    id: int
    job_id: str
    ordinal: int
    input_path: str
    input_name: str
    output_path: str | None
    status: str
    duration_ms: int | None
    error: str | None
    started_at: str | None
    finished_at: str | None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "BatchFile":
        return cls(
            id=row["id"],
            job_id=row["job_id"],
            ordinal=row["ordinal"],
            input_path=row["input_path"],
            input_name=row["input_name"],
            output_path=row["output_path"],
            status=row["status"],
            duration_ms=row["duration_ms"],
            error=row["error"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ordinal": self.ordinal,
            "input_path": self.input_path,
            "input_name": self.input_name,
            "output_path": self.output_path,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ── CRUD ──────────────────────────────────────────────────────────────


async def create_job(
    db: aiosqlite.Connection,
    *,
    agent_id: str,
    file_paths: list[str],
    variables: dict[str, Any] | None = None,
    tenant_id: str | None = None,
    job_id: str | None = None,
) -> Job:
    """Insert a job + one row per input file. Returns the populated Job."""
    if not file_paths:
        raise ValueError("file_paths must not be empty")
    job_id = job_id or str(uuid.uuid4())
    variables = variables or {}
    await db.execute(
        """
        INSERT INTO batch_jobs (id, agent_id, tenant_id, status, total,
                                done, variables_json)
        VALUES (?, ?, ?, 'pending', ?, 0, ?)
        """,
        (
            job_id,
            agent_id,
            tenant_id,
            len(file_paths),
            json.dumps(variables, ensure_ascii=False),
        ),
    )
    for ordinal, path in enumerate(file_paths):
        await db.execute(
            """
            INSERT INTO batch_job_files
                (job_id, ordinal, input_path, input_name, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (job_id, ordinal, path, path.rsplit("/", 1)[-1]),
        )
    await db.commit()
    job = await get_job(db, job_id)
    assert job is not None
    return job


async def get_job(db: aiosqlite.Connection, job_id: str) -> Job | None:
    cursor = await db.execute(
        "SELECT * FROM batch_jobs WHERE id = ?", (job_id,)
    )
    row = await cursor.fetchone()
    return Job.from_row(row) if row else None


async def list_files(
    db: aiosqlite.Connection, job_id: str
) -> list[BatchFile]:
    cursor = await db.execute(
        "SELECT * FROM batch_job_files WHERE job_id = ? ORDER BY ordinal",
        (job_id,),
    )
    rows = await cursor.fetchall()
    return [BatchFile.from_row(r) for r in rows]


async def set_job_status(
    db: aiosqlite.Connection, job_id: str, status: str
) -> None:
    if status not in JOB_STATUSES:
        raise ValueError(f"unknown status {status!r}")
    await db.execute(
        "UPDATE batch_jobs SET status = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (status, job_id),
    )
    await db.commit()


async def set_job_error(
    db: aiosqlite.Connection, job_id: str, message: str
) -> None:
    await db.execute(
        "UPDATE batch_jobs SET status = 'failed', error = ?, "
        "updated_at = datetime('now') WHERE id = ?",
        (message, job_id),
    )
    await db.commit()


async def increment_done(db: aiosqlite.Connection, job_id: str) -> int:
    """Atomically bump ``done`` and return the new value."""
    await db.execute(
        "UPDATE batch_jobs SET done = done + 1, "
        "updated_at = datetime('now') WHERE id = ?",
        (job_id,),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT done FROM batch_jobs WHERE id = ?", (job_id,)
    )
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def record_file_started(
    db: aiosqlite.Connection, file_row_id: int
) -> None:
    await db.execute(
        "UPDATE batch_job_files SET status = 'running', "
        "started_at = datetime('now') WHERE id = ?",
        (file_row_id,),
    )
    await db.commit()


async def record_file_done(
    db: aiosqlite.Connection,
    file_row_id: int,
    *,
    output_path: str,
    duration_ms: int,
) -> None:
    await db.execute(
        "UPDATE batch_job_files SET status = 'done', output_path = ?, "
        "duration_ms = ?, finished_at = datetime('now') WHERE id = ?",
        (output_path, duration_ms, file_row_id),
    )
    await db.commit()


async def record_file_error(
    db: aiosqlite.Connection,
    file_row_id: int,
    *,
    message: str,
    duration_ms: int,
) -> None:
    await db.execute(
        "UPDATE batch_job_files SET status = 'error', error = ?, "
        "duration_ms = ?, finished_at = datetime('now') WHERE id = ?",
        (message, duration_ms, file_row_id),
    )
    await db.commit()


async def record_file_cancelled(
    db: aiosqlite.Connection, file_row_id: int
) -> None:
    await db.execute(
        "UPDATE batch_job_files SET status = 'cancelled', "
        "finished_at = datetime('now') WHERE id = ?",
        (file_row_id,),
    )
    await db.commit()
