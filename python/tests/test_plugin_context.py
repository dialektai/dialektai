"""Tests for dialekt.llm._plugin_context.

Covers the axes of PluginContext:
  • env-based default (DIALEKT_BACKEND_URL)
  • explicit http mode via base_url
  • in-process mode via a FastAPI app
  • module-level set_context / get_context lifecycle
  • thread-safety of the lazy-init singleton (P1 — 100-thread race test)
  • shutdown-race: _call() after close() raises a clean RuntimeError
"""
from __future__ import annotations

import threading

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


# ── Thread-safety (P1 regression) ────────────────────────────────────────────


def test_concurrent_get_context_returns_same_instance(monkeypatch):
    """100 threads concurrently call get_context() from a cold start —
    they must all observe the same PluginContext instance. Without the
    lock added in the P1 fix, two winners of the `is None` check both
    build a context and the loser's httpx.Client + portal thread leak.
    """
    monkeypatch.delenv("DIALEKT_BACKEND_URL", raising=False)
    pc = _fresh_module()
    pc._reset_context_for_testing()

    observed: list[int] = []
    N = 100
    barrier = threading.Barrier(N)

    def worker():
        barrier.wait()           # release all threads at exactly the same moment
        ctx = pc.get_context()
        observed.append(id(ctx))

    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(observed) == N, "one or more workers never reported an id"
    assert len(set(observed)) == 1, (
        f"race: threads observed {len(set(observed))} distinct "
        f"PluginContext instances — expected 1"
    )

    pc._reset_context_for_testing()


def test_set_context_closes_previous_on_replace():
    """set_context must close() the old context before swapping, so
    overrides in tests (and runtime lifecycle transitions) don't leak
    httpx.Client / portal threads.
    """
    pc = _fresh_module()

    closed_flags = []

    class _FakeContext:
        def close(self):
            closed_flags.append(True)

    first = _FakeContext()
    pc.set_context(first)
    second = _FakeContext()
    pc.set_context(second)

    assert closed_flags == [True], (
        f"expected exactly 1 close() on the first context, got {len(closed_flags)}"
    )
    # Swapping to the SAME instance must not re-close.
    pc.set_context(second)
    assert closed_flags == [True], "set_context(same) should be a no-op"

    pc._reset_context_for_testing()


def test_reset_for_testing_closes_live_context():
    """The test-only reset helper must also close whatever was live
    before clearing, so test-to-test bleed is impossible.
    """
    pc = _fresh_module()
    closed = []

    class _FakeContext:
        def close(self):
            closed.append(True)

    pc.set_context(_FakeContext())
    pc._reset_context_for_testing()

    assert closed == [True]
    # And a fresh get_context after reset must build a brand-new default.
    pc._reset_context_for_testing()
    ctx = pc.get_context()
    assert ctx is not None
    pc._reset_context_for_testing()


# ── Shutdown-race (P1.5 regression) ──────────────────────────────────────────


def test_persistent_asgi_client_raises_cleanly_after_close():
    """If an OI worker calls ctx.post() *after* lifespan shutdown has
    close()'d the PluginContext, we must raise a cohesive RuntimeError
    rather than bubbling an anyio "portal is closed" stacktrace up
    into the WS handler.
    """
    from fastapi import FastAPI
    pc = _fresh_module()

    app = FastAPI()

    @app.get("/probe")
    def _probe():
        return {"ok": True}

    ctx = pc.PluginContext(app=app)
    # Round-trip once so the portal is definitely running.
    r = ctx.get("/probe")
    assert r.status_code == 200

    # Now close and confirm a subsequent call raises cleanly.
    ctx.close()
    with pytest.raises(RuntimeError) as excinfo:
        ctx.get("/probe")
    assert "closed" in str(excinfo.value).lower()
