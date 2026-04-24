"""Tests for dialekt.llm._plugin_context.

Covers the three axes of PluginContext:
  • env-based default (DIALEKT_BACKEND_URL)
  • explicit http mode via base_url
  • in-process mode via a FastAPI app
  • module-level set_context / get_context lifecycle
"""
from __future__ import annotations

import pytest


def _fresh_module():
    """Return _plugin_context with its module-level state reset — needed
    because get_context() caches a default across tests.
    """
    import importlib
    import dialekt.llm._plugin_context as pc
    importlib.reload(pc)
    return pc


def test_default_context_reads_env(monkeypatch):
    monkeypatch.delenv("DIALEKT_BACKEND_URL", raising=False)
    pc = _fresh_module()
    ctx = pc.get_context()
    assert ctx.describe() == {
        "mode": "http",
        "base_url": "http://127.0.0.1:8765",
        "has_app": False,
    }


def test_default_context_honours_env_override(monkeypatch):
    monkeypatch.setenv("DIALEKT_BACKEND_URL", "http://localhost:9999")
    pc = _fresh_module()
    ctx = pc.get_context()
    assert ctx.base_url == "http://localhost:9999"
    assert ctx.app is None


def test_context_with_app_is_in_process():
    from fastapi import FastAPI
    pc = _fresh_module()

    app = FastAPI()

    @app.get("/probe")
    def probe():
        return {"origin": "in-process"}

    ctx = pc.PluginContext(app=app)
    assert ctx.describe()["mode"] == "in-process"
    r = ctx.get("/probe")
    assert r.status_code == 200
    assert r.json() == {"origin": "in-process"}


def test_context_without_app_uses_http(monkeypatch):
    """httpx.Client is instantiated lazily and receives the configured
    base_url. We patch httpx so the test never leaves the process.
    """
    pc = _fresh_module()
    captured: dict = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"origin": "http"}

    class _FakeHttpClient:
        def __init__(self, *, base_url, timeout):
            captured["base_url"] = base_url
            captured["timeout"] = timeout

        def get(self, path, **kw):
            captured["path"] = path
            return _FakeResp()

        def close(self):
            captured["closed"] = True

    import httpx
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)

    ctx = pc.PluginContext(base_url="http://example.test:4242")
    r = ctx.get("/health")
    assert captured["base_url"] == "http://example.test:4242"
    assert captured["path"] == "/health"
    assert r.status_code == 200

    ctx.close()
    assert captured.get("closed") is True


def test_set_context_swaps_and_closes_previous(monkeypatch):
    pc = _fresh_module()

    closed_flags = []

    class _FakeClient:
        def close(self):
            closed_flags.append(True)

    first = pc.PluginContext()
    first._client = _FakeClient()   # pretend an httpx.Client was built
    pc.set_context(first)

    # Replacing triggers close on the previous context.
    second = pc.PluginContext(base_url="http://other")
    pc.set_context(second)

    assert closed_flags == [True]
    assert pc.get_context() is second


def test_set_context_none_resets_default(monkeypatch):
    pc = _fresh_module()
    # Install a custom ctx, then reset to None — next get_context() must
    # rebuild from env defaults.
    pc.set_context(pc.PluginContext(base_url="http://custom"))
    assert pc.get_context().base_url == "http://custom"
    pc.set_context(None)
    monkeypatch.delenv("DIALEKT_BACKEND_URL", raising=False)
    assert pc.get_context().base_url == "http://127.0.0.1:8765"


def test_post_get_delete_patch_all_route_through_client():
    """All HTTP verbs we expose are thin wrappers — assert the underlying
    client receives each call.
    """
    pc = _fresh_module()

    calls = []

    class _RecordingClient:
        def post(self, path, **kw): calls.append(("POST", path))
        def get(self, path, **kw):  calls.append(("GET", path))
        def delete(self, path, **kw): calls.append(("DELETE", path))
        def patch(self, path, **kw): calls.append(("PATCH", path))
        def close(self): pass

    ctx = pc.PluginContext()
    ctx._client = _RecordingClient()

    ctx.post("/a")
    ctx.get("/b")
    ctx.delete("/c")
    ctx.patch("/d")
    assert calls == [("POST", "/a"), ("GET", "/b"), ("DELETE", "/c"), ("PATCH", "/d")]
