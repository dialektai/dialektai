"""
Goal 8.3 — Self-correcting retry loop for tool-use agents.

When an agent generates a tool call (e.g., SQL query):
  1. Validate before executing (EXPLAIN for SQL, etc.)
  2. On failure, feed error back to LLM and retry (up to max_retries)
  3. Only the final successful result is returned to the caller.

Retries are opaque to the user (invisible in chat). They are logged for debugging.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable, Awaitable, Optional

log = logging.getLogger("dialekt.retry_loop")


# ── Back-compat shim for the R1 API ─────────────────────────────────────────
# Prior to PluginContext (2026-04-24), tests imported `_get_backend` directly
# to verify env-var plumbing. Keep the symbol so those tests — and any third-
# party integrator that copied the pattern — don't break.

def _get_backend() -> str:
    """DEPRECATED: prefer `get_context().base_url`. Kept for backward
    compatibility with test_retry_loop_config.py.
    """
    return os.environ.get("DIALEKT_BACKEND_URL", "http://localhost:8765")


class ToolCallError(Exception):
    """Raised when a tool call fails validation or execution."""


class RetryExhausted(Exception):
    """Raised when all retries fail."""
    def __init__(self, attempts: list[dict]) -> None:
        self.attempts = attempts
        super().__init__(f"All {len(attempts)} attempts failed")


async def validate_sql(conn_id: str, sql: str) -> tuple[bool, str]:
    """
    Dry-run a SELECT via EXPLAIN. Returns (ok, error_message).
    Uses the local dialekt MCP REST API.

    `retry: False` is critical — without it, /connections/{id}/query would
    call _retry_fix_sql → validate_sql → /query → _retry_fix_sql → …,
    spamming the logs with '🔄 SQL retry attempt N/3' forever until the
    client times out. The validator does its own retry here; the server
    must not try to double-retry.

    Dispatch goes through the shared PluginContext: in-process when the
    server has wired its own FastAPI app (fast, works on any port), HTTP
    fallback when running detached (DIALEKT_BACKEND_URL).
    """
    # Lazy import + call-time resolution so tests that monkeypatch
    # set_context() after module import still take effect.
    from dialekt.llm._plugin_context import get_context
    ctx = get_context()

    def _do_call():
        return ctx.post(
            f"/connections/{conn_id}/query",
            json={"sql": f"EXPLAIN {sql}", "retry": False},
            timeout=10.0,
        )

    try:
        # PluginContext exposes a sync surface (both TestClient and the
        # httpx.Client fallback are sync). Run in a thread so we don't
        # block the event loop in live-server contexts.
        r = await asyncio.to_thread(_do_call)
        data = r.json()
        if not data.get("ok", True) or r.status_code >= 400:
            return False, data.get("detail") or data.get("error") or "SQL validation failed"
        return True, ""
    except Exception as e:
        return False, str(e)


def _extract_sql(code: str) -> str | None:
    """Extract first SELECT statement from code block or raw text."""
    import re
    # Try fenced code block first
    m = re.search(r"```(?:sql|python)?\s*(SELECT[\s\S]+?)```", code, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Try bare SELECT
    m = re.search(r"(SELECT\s+[\s\S]+?;)", code, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


class SQLRetryLoop:
    """
    Wraps an LLM code-generation loop with SQL-specific validation.

    Usage (pseudo-code — integrate with Open Interpreter):
        loop = SQLRetryLoop(conn_id, max_retries=3)
        for attempt in loop.iter_attempts(user_question, llm_fn):
            ...
    """

    def __init__(self, conn_id: str, max_retries: int = 3):
        self.conn_id = conn_id
        self.max_retries = max_retries
        self.attempts: list[dict] = []

    async def validate_and_maybe_retry(
        self,
        generated_code: str,
        llm_regenerate: Callable[[str, str], Awaitable[str]],
    ) -> str:
        """
        Validate generated_code. If invalid, call llm_regenerate(original_code, error)
        and retry up to max_retries times.

        Returns the last successfully-validated code.
        Raises RetryExhausted if all attempts fail.
        """
        code = generated_code
        for attempt_n in range(self.max_retries):
            sql = _extract_sql(code)
            if sql is None:
                # No SQL found — pass through (may be prose or non-SQL code)
                log.debug(f"[retry_loop] No SQL in attempt {attempt_n+1}, passing through")
                return code

            ok, err = await validate_sql(self.conn_id, sql)
            record = {
                "attempt": attempt_n + 1,
                "sql": sql,
                "ok": ok,
                "error": err,
                "ts": time.time(),
            }
            self.attempts.append(record)

            if ok:
                if attempt_n > 0:
                    log.info(f"[retry_loop] SQL validated on attempt {attempt_n+1}")
                return code

            log.warning(f"[retry_loop] Attempt {attempt_n+1} failed: {err}")

            if attempt_n + 1 < self.max_retries:
                error_feedback = (
                    f"The SQL you generated failed validation:\n"
                    f"SQL: {sql}\n"
                    f"Error: {err}\n\n"
                    f"Please fix the SQL and try again. "
                    f"Ensure table names, column names, and syntax are correct."
                )
                code = await llm_regenerate(code, error_feedback)

        raise RetryExhausted(self.attempts)


def build_error_feedback_message(sql: str, error: str) -> str:
    """Build the feedback message injected back to the LLM on retry."""
    return (
        f"⚠️ The SQL query failed:\n"
        f"```sql\n{sql}\n```\n"
        f"Error: `{error}`\n\n"
        "Please correct the SQL and try again."
    )
