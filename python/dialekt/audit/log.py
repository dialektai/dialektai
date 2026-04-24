"""Universal audit log for dialekt agent actions.

In v0.20.0 this records MCP tool calls. The schema is intentionally
kind-discriminated so SQL queries, file operations, and agent
lifecycle events can be appended to the same table in later releases
without a migration — only new ``kind`` values get emitted.

See ``docs/M2_MCP_DESIGN.md`` Decision 7 for rationale and the chosen
Variant B scoping.
"""
from __future__ import annotations

import json
from typing import Any

import aiosqlite


AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    agent_id    TEXT,
    binding_id  TEXT,
    kind        TEXT NOT NULL,
    target      TEXT,
    action      TEXT NOT NULL,
    result      TEXT NOT NULL,
    duration_ms INTEGER,
    error_kind  TEXT,
    extra_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_ts       ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_agent_id ON audit_log(agent_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_kind     ON audit_log(kind, ts);
"""


async def log_event(
    db: aiosqlite.Connection,
    *,
    kind: str,
    action: str,
    result: str,
    agent_id: str | None = None,
    binding_id: str | None = None,
    target: str | None = None,
    duration_ms: int | None = None,
    error_kind: str | None = None,
    extra: dict[str, Any] | None = None,
) -> int:
    """Append a row to ``audit_log``. Returns the inserted row id.

    ``kind``, ``action`` and ``result`` are required. ``kind`` is an
    unconstrained string — callers emit values like ``"mcp_tool_call"``,
    and future releases will add ``"sql_query"``, ``"file_op"``, etc.,
    without touching the schema. ``extra`` is serialized to JSON if
    provided; callers should keep it small — it is not a data store.
    """
    extra_str = (
        json.dumps(extra, separators=(",", ":"), ensure_ascii=False)
        if extra is not None
        else None
    )
    cursor = await db.execute(
        """
        INSERT INTO audit_log
            (agent_id, binding_id, kind, target, action, result,
             duration_ms, error_kind, extra_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent_id,
            binding_id,
            kind,
            target,
            action,
            result,
            duration_ms,
            error_kind,
            extra_str,
        ),
    )
    await db.commit()
    return cursor.lastrowid
