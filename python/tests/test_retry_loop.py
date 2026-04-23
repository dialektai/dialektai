"""Tests for dialekt/llm/retry_loop.py (Goal 8.3)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import AsyncMock, patch
from dialekt.llm.retry_loop import (
    SQLRetryLoop,
    RetryExhausted,
    build_error_feedback_message,
    _extract_sql,
)


# ── _extract_sql ──────────────────────────────────────────────────────────────

def test_extract_sql_fenced_block():
    code = "```sql\nSELECT COUNT(*) FROM orders;\n```"
    assert "SELECT COUNT(*)" in (_extract_sql(code) or "")


def test_extract_sql_python_fenced():
    code = "```python\nresult = httpx.post(..., json={'sql': 'SELECT 1'})\n```\nSELECT id FROM users;"
    sql = _extract_sql(code)
    assert sql is not None


def test_extract_sql_bare():
    code = "Here is the query: SELECT id, name FROM products;"
    sql = _extract_sql(code)
    assert sql is not None
    assert "products" in sql


def test_extract_sql_no_sql():
    code = "Let me check the schema first."
    assert _extract_sql(code) is None


def test_extract_sql_case_insensitive():
    code = "select * from users;"
    sql = _extract_sql(code)
    assert sql is not None


# ── build_error_feedback_message ──────────────────────────────────────────────

def test_error_feedback_message_contains_sql():
    msg = build_error_feedback_message("SELECT * FROM foo", "column 'foo' does not exist")
    assert "SELECT * FROM foo" in msg
    assert "foo" in msg
    assert "does not exist" in msg


# ── SQLRetryLoop ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_sql_passes_first_try():
    loop = SQLRetryLoop(conn_id="test", max_retries=3)

    with patch("dialekt.llm.retry_loop.validate_sql", return_value=(True, "")):
        result = await loop.validate_and_maybe_retry(
            "```sql\nSELECT 1;\n```",
            llm_regenerate=AsyncMock(),
        )
    assert "SELECT 1" in result
    assert len(loop.attempts) == 1
    assert loop.attempts[0]["ok"] is True


@pytest.mark.asyncio
async def test_no_sql_passthrough():
    loop = SQLRetryLoop(conn_id="test", max_retries=3)
    regen = AsyncMock()

    result = await loop.validate_and_maybe_retry(
        "Let me check the schema first.",
        llm_regenerate=regen,
    )
    assert result == "Let me check the schema first."
    regen.assert_not_called()
    assert len(loop.attempts) == 0


@pytest.mark.asyncio
async def test_retry_on_failure_then_success():
    loop = SQLRetryLoop(conn_id="test", max_retries=3)
    call_count = 0

    async def mock_validate(conn_id, sql):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return False, "column xyz does not exist"
        return True, ""

    fixed_code = "```sql\nSELECT id FROM orders;\n```"

    async def regen(original, feedback):
        return fixed_code

    with patch("dialekt.llm.retry_loop.validate_sql", side_effect=mock_validate):
        result = await loop.validate_and_maybe_retry(
            "```sql\nSELECT xyz FROM orders;\n```",
            llm_regenerate=regen,
        )
    assert len(loop.attempts) == 2
    assert loop.attempts[0]["ok"] is False
    assert loop.attempts[1]["ok"] is True


@pytest.mark.asyncio
async def test_exhaust_retries_raises():
    loop = SQLRetryLoop(conn_id="test", max_retries=2)

    async def regen(original, feedback):
        return original  # keep returning bad code

    with patch("dialekt.llm.retry_loop.validate_sql", return_value=(False, "syntax error")):
        with pytest.raises(RetryExhausted) as exc_info:
            await loop.validate_and_maybe_retry(
                "```sql\nSELECT bad syntax;\n```",
                llm_regenerate=regen,
            )
    assert len(exc_info.value.attempts) == 2


@pytest.mark.asyncio
async def test_attempts_logged():
    loop = SQLRetryLoop(conn_id="test", max_retries=3)

    with patch("dialekt.llm.retry_loop.validate_sql", return_value=(True, "")):
        await loop.validate_and_maybe_retry(
            "SELECT id FROM users;",
            llm_regenerate=AsyncMock(),
        )
    assert loop.attempts[0]["attempt"] == 1
    assert "sql" in loop.attempts[0]
    assert "ts" in loop.attempts[0]


@pytest.mark.asyncio
async def test_retry_exhausted_attributes():
    loop = SQLRetryLoop(conn_id="test", max_retries=1)

    with patch("dialekt.llm.retry_loop.validate_sql", return_value=(False, "bad")):
        with pytest.raises(RetryExhausted) as exc:
            await loop.validate_and_maybe_retry(
                "SELECT bad;",
                llm_regenerate=AsyncMock(return_value="SELECT bad;"),
            )
    err = exc.value
    assert isinstance(err.attempts, list)
    assert len(err.attempts) == 1
