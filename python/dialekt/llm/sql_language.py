"""Open Interpreter Language plugin that executes SQL via the dialekt
connection API instead of a local subprocess.

Agents whose manifest declares a bound database connection (connection_id
set on agent_bindings) can emit ```sql``` code blocks; the handler POSTs
the statement to /connections/{id}/query on the same dialekt server
process. Retry logic and validation live server-side, so this shim stays
thin — we just format the result for the LLM.

Usage (from make_interpreter):
    from dialekt.llm.sql_language import DialektSQL
    interpreter.computer.terminal.languages.insert(0, DialektSQL)
    interpreter._dialekt_sql_conn = conn_id  # read by handler at run time
"""
from __future__ import annotations

import logging
import os
from typing import Iterable

log = logging.getLogger("dialekt")

DIALEKT_API = os.environ.get("DIALEKT_API", "http://127.0.0.1:8765")
MAX_DISPLAY_ROWS = 50
QUERY_TIMEOUT_SECONDS = 30.0


def _format_result(data: dict) -> str:
    """Render a /connections/{id}/query response as a markdown-ish block."""
    cols = data.get("columns") or []
    rows = data.get("rows") or []
    row_count = data.get("row_count")
    if row_count is None:
        row_count = len(rows)
    truncated = bool(data.get("truncated"))
    warning = data.get("warning")

    lines: list[str] = []
    if warning:
        lines.append(f"⚠ {warning}")

    if cols and rows:
        lines.append("| " + " | ".join(str(c) for c in cols) + " |")
        lines.append("|" + "|".join(["---"] * len(cols)) + "|")
        display = rows[:MAX_DISPLAY_ROWS]
        for row in display:
            lines.append(
                "| "
                + " | ".join("" if v is None else str(v) for v in row)
                + " |"
            )
        if len(rows) > MAX_DISPLAY_ROWS:
            lines.append(f"…({len(rows) - MAX_DISPLAY_ROWS} more rows not shown)")
    elif cols:
        lines.append("(0 rows)")

    suffix = f"row_count={row_count}"
    if truncated:
        suffix += " (truncated by row_limit)"
    lines.append("")
    lines.append(suffix)
    return "\n".join(lines).strip()


def _execute(conn_id: str, sql: str) -> Iterable[dict]:
    """POST SQL to the dialekt backend and yield OI-shaped console chunks.

    `retry: false` is passed to avoid the server-side SQLRetryLoop — the
    LLM that wrote the SQL can correct itself on the next turn if the
    statement fails, and the server's retry path currently triggers a
    recursive validate_sql → /query loop when enabled.
    """
    import httpx
    try:
        with httpx.Client(timeout=QUERY_TIMEOUT_SECONDS) as c:
            r = c.post(
                f"{DIALEKT_API}/connections/{conn_id}/query",
                json={"sql": sql.strip(), "retry": False},
            )
    except Exception as e:
        yield {
            "type": "console",
            "format": "output",
            "content": f"SQL transport error: {e}",
        }
        return

    if r.status_code >= 400:
        # Surface the server message — retry_loop already had its turn.
        body = r.text[:800]
        yield {
            "type": "console",
            "format": "output",
            "content": f"SQL error ({r.status_code}): {body}",
        }
        return

    try:
        data = r.json()
    except Exception as e:
        yield {
            "type": "console",
            "format": "output",
            "content": f"SQL: could not parse response: {e}",
        }
        return

    yield {
        "type": "console",
        "format": "output",
        "content": _format_result(data),
    }


class DialektSQL:
    """OI Language plugin for SELECT-only SQL routed through dialekt."""

    name = "SQL"
    aliases = ["sql", "postgres", "postgresql", "psql", "mysql", "clickhouse"]
    file_extension = "sql"

    def __init__(self, computer):
        # Computer is passed because our __init__ takes one arg other than self;
        # OI's Terminal._streaming_run inspects co_argcount to decide.
        self.computer = computer

    def _connection_id(self) -> str | None:
        itp = getattr(self.computer, "interpreter", None)
        return getattr(itp, "_dialekt_sql_conn", None) if itp else None

    def run(self, code: str) -> Iterable[dict]:
        conn_id = self._connection_id()
        if not conn_id:
            yield {
                "type": "console",
                "format": "output",
                "content": (
                    "No database connection is bound to this agent. "
                    "Open Settings → Connections, create one, and bind the "
                    "agent to it (POST /agents/{id}/binding) before running SQL."
                ),
            }
            return
        log.info(f"DialektSQL: executing on conn={conn_id[:8]} sql={code.strip()[:120]!r}")
        yield from _execute(conn_id, code)

    def stop(self):  # pragma: no cover — HTTP client is short-lived
        pass

    def terminate(self):  # pragma: no cover — HTTP client is short-lived
        pass
