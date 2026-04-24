"""Tests for DIALEKT_BACKEND_URL env configuration of retry_loop.

R1 from OVERNIGHT_E2E_REPORT_2026-04-24.md: the retry loop's backend URL
used to be a module-level constant hardcoded to http://localhost:8765,
so running dialekt-server on a non-default port (or validating against
a test harness on a different port) silently 404'd through all retries.

The fix reads the URL at call time via `_get_backend()`, honoring the
`DIALEKT_BACKEND_URL` env var with the 8765 default.
"""
import os

from dialekt.llm.retry_loop import _get_backend


def test_default_backend_when_env_unset(monkeypatch):
    monkeypatch.delenv("DIALEKT_BACKEND_URL", raising=False)
    assert _get_backend() == "http://localhost:8765"


def test_custom_backend_from_env(monkeypatch):
    monkeypatch.setenv("DIALEKT_BACKEND_URL", "http://localhost:9999")
    assert _get_backend() == "http://localhost:9999"


def test_env_change_picked_up_at_call_time(monkeypatch):
    """Changing the env between calls must take effect immediately —
    proves we aren't caching the value at import time.
    """
    monkeypatch.setenv("DIALEKT_BACKEND_URL", "http://localhost:7001")
    first = _get_backend()
    monkeypatch.setenv("DIALEKT_BACKEND_URL", "http://localhost:7002")
    second = _get_backend()
    assert first == "http://localhost:7001"
    assert second == "http://localhost:7002"


def test_validate_sql_uses_current_backend(monkeypatch):
    """validate_sql() posts to {_get_backend()}/connections/{id}/query.
    We stub httpx to capture the URL and assert it reflects the env.
    """
    import asyncio
    import dialekt.llm.retry_loop as rl

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        def json(self):
            return {"ok": True}

    class _FakeClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None):
            captured["url"] = url
            return _FakeResp()

    monkeypatch.setattr(rl.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setenv("DIALEKT_BACKEND_URL", "http://example.test:4242")

    asyncio.run(rl.validate_sql("conn-abc", "SELECT 1"))
    assert captured["url"] == "http://example.test:4242/connections/conn-abc/query"
