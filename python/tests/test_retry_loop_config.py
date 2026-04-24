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
    """validate_sql() dispatches through PluginContext. After the
    2026-04-24 consolidation the call goes via `ctx.post(path, ...)`
    (PluginContext prepends the base_url for http mode, or pumps the
    ASGI app for in-process mode). We assert the PATH alone here —
    the base URL is a PluginContext concern covered in
    test_plugin_context.py.
    """
    import asyncio
    from dialekt.llm import _plugin_context as pc
    from dialekt.llm import retry_loop as rl

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        def json(self):
            return {"ok": True}

    class _FakeContext:
        base_url = "http://example.test:4242"
        def post(self, path, json=None, **kw):
            captured["path"] = path
            captured["base_url"] = self.base_url
            return _FakeResp()
        def close(self):
            pass

    original = pc.get_context()
    pc.set_context(_FakeContext())
    try:
        asyncio.run(rl.validate_sql("conn-abc", "SELECT 1"))
    finally:
        pc.set_context(original)

    assert captured["path"] == "/connections/conn-abc/query"
    assert captured["base_url"] == "http://example.test:4242"
