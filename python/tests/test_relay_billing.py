"""Tests for relay billing (Commit 3).

Unit-level for chunk parsing + record_usage shape; HTTP-level for the
end-to-end "stream a chat → row written" path.

The fake pool records every conn.execute call so tests can assert
on the SQL + bound parameters without a live PG instance. C8 covers
the same path against a real database.
"""
from __future__ import annotations

import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from dialekt.relay.auth import RelayKeyContext
from dialekt.relay.billing import (
    count_tokens_from_ollama_final_chunk,
    find_terminal_chunk,
    maybe_record,
    record_usage,
)
from dialekt.relay.config import RelayConfig
from dialekt.relay.server import create_app


# ── helpers ────────────────────────────────────────────────────────────────


def _ollama_streaming_handler(chunks: list[bytes]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"".join(chunks),
            headers={"content-type": "application/x-ndjson"},
        )

    return handler


def _key_row(key_id=None, tenant_id=None, *, rate=120):
    return {
        "id": key_id or uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "rate_limit_per_minute": rate,
        "monthly_token_quota": None,
        "revoked_at": None,
    }


def _recording_pool(auth_row):
    """Pool that returns ``auth_row`` from fetchrow and records every
    execute call into ``pool.executions`` for assertions."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=auth_row)

    executions: list[tuple[str, tuple]] = []

    async def execute(query, *args):
        executions.append((query, args))

    conn.execute = AsyncMock(side_effect=execute)

    @asynccontextmanager
    async def transaction():
        yield

    conn.transaction = transaction

    pool = MagicMock()
    pool.close = AsyncMock()
    pool.executions = executions

    @asynccontextmanager
    async def acquire():
        yield conn

    pool.acquire = acquire
    return pool


# ── chunk parsing ──────────────────────────────────────────────────────────


def test_count_tokens_extracts_from_terminal_chunk():
    chunk = {
        "done": True, "model": "llama3",
        "prompt_eval_count": 12, "eval_count": 7,
    }
    assert count_tokens_from_ollama_final_chunk(chunk) == (12, 7)


def test_count_tokens_treats_missing_as_zero():
    assert count_tokens_from_ollama_final_chunk({"done": True}) == (0, 0)


def test_find_terminal_returns_last_done_line():
    buf = (
        b'{"message":{"content":"hi"},"done":false}\n'
        b'{"message":{"content":""},"done":true,'
        b'"prompt_eval_count":4,"eval_count":2,"model":"x"}\n'
    )
    chunk = find_terminal_chunk(buf)
    assert chunk is not None
    assert chunk["done"] is True
    assert chunk["prompt_eval_count"] == 4
    assert chunk["model"] == "x"


def test_find_terminal_returns_none_when_no_done_line():
    buf = b'{"message":{"content":"hi"},"done":false}\n'
    assert find_terminal_chunk(buf) is None


def test_find_terminal_skips_blank_lines_and_garbage():
    buf = (
        b'\n'
        b'not-json\n'
        b'{"done":false}\n'
        b'{"done":true,"prompt_eval_count":1,"eval_count":1}\n'
        b'\n'
    )
    assert find_terminal_chunk(buf) is not None


# ── record_usage shape ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_usage_writes_insert_and_bumps_last_used():
    tenant = uuid4()
    key = uuid4()
    ctx = RelayKeyContext(
        tenant_id=str(tenant),
        key_id=str(key),
        rate_limit_per_minute=120,
        monthly_token_quota=None,
    )
    pool = _recording_pool(auth_row=None)

    await record_usage(
        pool, ctx,
        model="llama3:8b",
        prompt_tokens=42, completion_tokens=99, latency_ms=1234,
    )

    queries = [q for q, _ in pool.executions]
    assert any("INSERT INTO relay_usage" in q for q in queries)
    assert any("UPDATE relay_keys SET last_used_at" in q for q in queries)

    # Bound params on the INSERT: tenant_id, key_id, model, pt, ct, latency.
    insert_args = next(
        args for q, args in pool.executions if "INSERT INTO relay_usage" in q
    )
    assert insert_args[0] == tenant
    assert insert_args[1] == key
    assert insert_args[2] == "llama3:8b"
    assert insert_args[3] == 42
    assert insert_args[4] == 99
    assert insert_args[5] == 1234


# ── maybe_record short-circuits ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_maybe_record_skips_when_no_terminal_chunk():
    pool = _recording_pool(auth_row=None)
    ctx = RelayKeyContext(str(uuid4()), str(uuid4()), 120, None)
    await maybe_record(
        pool, ctx,
        request_model="x",
        response_buffer=b'{"done":false}\n',
        start_monotonic=0.0, now_monotonic=1.0,
    )
    assert not any("INSERT" in q for q, _ in pool.executions)


@pytest.mark.asyncio
async def test_maybe_record_skips_when_zero_token_counts():
    """Aborted / cache-hit responses lack counts — don't write a
    degenerate row."""
    pool = _recording_pool(auth_row=None)
    ctx = RelayKeyContext(str(uuid4()), str(uuid4()), 120, None)
    await maybe_record(
        pool, ctx,
        request_model="x",
        response_buffer=b'{"done":true}\n',
        start_monotonic=0.0, now_monotonic=1.0,
    )
    assert not any("INSERT" in q for q, _ in pool.executions)


@pytest.mark.asyncio
async def test_maybe_record_swallows_db_errors():
    """Billing failures must not propagate — they'd surface as 500s
    to clients otherwise."""
    pool = MagicMock()
    pool.close = AsyncMock()

    @asynccontextmanager
    async def acquire():
        raise RuntimeError("db down")
        yield  # unreachable

    pool.acquire = acquire

    ctx = RelayKeyContext(str(uuid4()), str(uuid4()), 120, None)
    # Should not raise.
    await maybe_record(
        pool, ctx,
        request_model="x",
        response_buffer=b'{"done":true,"prompt_eval_count":1,"eval_count":1}\n',
        start_monotonic=0.0, now_monotonic=1.0,
    )


# ── HTTP end-to-end ─────────────────────────────────────────────────────────


@pytest.fixture
def relay_app():
    config = RelayConfig(port=3050, ollama_url="http://stub:11434")
    return create_app(config)


def test_chat_records_usage_after_stream_completes(relay_app):
    chunks = [
        b'{"message":{"role":"assistant","content":"hi"},"done":false,"model":"llama3"}\n',
        b'{"message":{"role":"assistant","content":""},"done":true,'
        b'"model":"llama3","prompt_eval_count":7,"eval_count":4}\n',
    ]
    auth_row = _key_row()
    pool = _recording_pool(auth_row=auth_row)

    with TestClient(relay_app) as tc:
        tc.app.state.ollama = httpx.AsyncClient(
            base_url="http://stub:11434",
            transport=httpx.MockTransport(_ollama_streaming_handler(chunks)),
        )
        tc.app.state.pool = pool
        with tc.stream(
            "POST",
            "/relay/chat",
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer test"},
        ) as r:
            for _ in r.iter_bytes():
                pass

    inserts = [
        args for q, args in pool.executions
        if "INSERT INTO relay_usage" in q
    ]
    assert len(inserts) == 1
    args = inserts[0]
    assert args[0] == auth_row["tenant_id"]
    assert args[1] == auth_row["id"]
    assert args[2] == "llama3"
    assert args[3] == 7   # prompt_tokens
    assert args[4] == 4   # completion_tokens
    assert args[5] >= 0   # latency_ms


def test_generate_records_usage_for_non_streaming_response(relay_app):
    """``stream=false`` returns one JSON; the proxy still picks up
    counts from the same fields."""
    body = (
        b'{"response":"hi","done":true,'
        b'"prompt_eval_count":3,"eval_count":2,"model":"phi3"}'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body,
            headers={"content-type": "application/json"},
        )

    auth_row = _key_row()
    pool = _recording_pool(auth_row=auth_row)

    with TestClient(relay_app) as tc:
        tc.app.state.ollama = httpx.AsyncClient(
            base_url="http://stub:11434",
            transport=httpx.MockTransport(handler),
        )
        tc.app.state.pool = pool
        r = tc.post(
            "/relay/generate",
            json={"model": "phi3", "prompt": "hi", "stream": False},
            headers={"Authorization": "Bearer test"},
        )

    assert r.status_code == 200
    inserts = [
        args for q, args in pool.executions
        if "INSERT INTO relay_usage" in q
    ]
    assert len(inserts) == 1
    assert inserts[0][2] == "phi3"
    assert inserts[0][3] == 3
    assert inserts[0][4] == 2
