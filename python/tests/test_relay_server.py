"""Unit tests for the dialekt GPU Relay FastAPI app.

Mocks Ollama via ``httpx.MockTransport`` injected into the app's
shared client. Tests don't need a live Ollama instance.

Auth is enforced from Commit 2 onwards. These tests stand up a
fake asyncpg pool (one valid, non-revoked key) and pass a
matching Bearer header on every authenticated call. Auth-failure
behaviour is covered in ``test_relay_auth.py``.
"""
from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from dialekt.relay.auth import hash_key
from dialekt.relay.config import RelayConfig
from dialekt.relay.server import create_app


def _client_with_mock(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="http://stub:11434",
        transport=httpx.MockTransport(handler),
    )


def _pool_with_key(plaintext: str = "test-key", *, revoked: bool = False, rate: int = 120):
    """Fake asyncpg.Pool that returns one matching key row.

    Matches by hash so the auth path's SHA-256 lookup is exercised
    end-to-end. Returns ``None`` for any other key — same shape the
    real DB would produce.
    """
    expected_hash = hash_key(plaintext)
    row = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "rate_limit_per_minute": rate,
        "monthly_token_quota": None,
        "revoked_at": "2026-01-01T00:00:00Z" if revoked else None,
    }
    conn = AsyncMock()

    async def fetchrow(_query, key_hash):
        return row if key_hash == expected_hash else None

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    pool = MagicMock()
    pool.close = AsyncMock()  # asyncpg.Pool.close is awaitable

    @asynccontextmanager
    async def acquire():
        yield conn

    pool.acquire = acquire
    return pool


AUTH_HEADER = {"Authorization": "Bearer test-key"}


@pytest.fixture
def relay_app():
    config = RelayConfig(port=3050, ollama_url="http://stub:11434")
    return create_app(config)


def test_health_ok_when_ollama_responds(relay_app):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(404)

    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _client_with_mock(handler)
        r = tc.get("/relay/health")

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["ollama_reachable"] is True
    assert body["version"]


def test_health_marks_unreachable_when_ollama_down(relay_app):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _client_with_mock(handler)
        r = tc.get("/relay/health")

    assert r.status_code == 200
    assert r.json()["ollama_reachable"] is False


def test_health_no_auth_required(relay_app):
    """Health is the operator probe — no Bearer, no DB pool needed."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _client_with_mock(handler)
        # Note: no tc.app.state.pool override; defaults to None.
        r = tc.get("/relay/health")

    assert r.status_code == 200


def test_models_proxies_ollama_tags(relay_app):
    payload = {"models": [{"name": "llama3:latest", "size": 100}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json=payload)

    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _client_with_mock(handler)
        tc.app.state.pool = _pool_with_key()
        r = tc.get("/relay/models", headers=AUTH_HEADER)

    assert r.status_code == 200
    assert r.json() == payload


def test_generate_forwards_to_api_generate(relay_app):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=(
                b'{"response":"hi","done":true,'
                b'"prompt_eval_count":3,"eval_count":2}'
            ),
            headers={"content-type": "application/json"},
        )

    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _client_with_mock(handler)
        tc.app.state.pool = _pool_with_key()
        r = tc.post(
            "/relay/generate",
            json={"model": "llama3", "prompt": "hello", "stream": False},
            headers=AUTH_HEADER,
        )

    assert r.status_code == 200
    assert captured["path"] == "/api/generate"
    assert captured["body"]["model"] == "llama3"
    assert captured["body"]["prompt"] == "hello"
    body = r.json()
    assert body["response"] == "hi"


def test_chat_streams_ndjson_back(relay_app):
    chunks = [
        b'{"message":{"role":"assistant","content":"hi"},"done":false}\n',
        b'{"message":{"role":"assistant","content":""},'
        b'"done":true,"prompt_eval_count":4,"eval_count":3}\n',
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200,
            content=b"".join(chunks),
            headers={"content-type": "application/x-ndjson"},
        )

    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _client_with_mock(handler)
        tc.app.state.pool = _pool_with_key()
        with tc.stream(
            "POST",
            "/relay/chat",
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
            headers=AUTH_HEADER,
        ) as r:
            assert r.status_code == 200
            received = b"".join(chunk for chunk in r.iter_bytes())

    assert received == b"".join(chunks)


def test_embeddings_proxies_to_api_embeddings(relay_app):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    with TestClient(relay_app) as tc:
        tc.app.state.ollama = _client_with_mock(handler)
        tc.app.state.pool = _pool_with_key()
        r = tc.post(
            "/relay/embeddings",
            json={"model": "nomic-embed-text", "prompt": "hi"},
            headers=AUTH_HEADER,
        )

    assert r.status_code == 200
    assert captured["path"] == "/api/embeddings"
    assert captured["body"]["model"] == "nomic-embed-text"
    assert r.json() == {"embedding": [0.1, 0.2, 0.3]}
