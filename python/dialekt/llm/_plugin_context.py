"""Shared backend access for dialekt LLM plugins.

Plugins (DialektSQL, retry_loop, …) need to call back into the dialekt
server to execute queries and fetch schemas. Historically each one did
this via `httpx.post("http://localhost:8765/…")`, which:

1. doesn't work under TestClient (the FastAPI app isn't listening on
   8765 — it's in-process)
2. breaks if the server runs on a non-default port
3. adds an unnecessary network hop even when the caller IS the server

This module consolidates that access behind one `PluginContext`.

## Usage

Plugins call `get_context().post("/connections/…")` instead of doing
their own httpx work. The context resolves to one of two transports:

- **in-process:** `TestClient(app)` — used when a FastAPI instance is
  passed in (both in unit tests and at server startup).
- **http:** `httpx.Client(base_url=…)` — fallback for detached
  processes. Base URL comes from `DIALEKT_BACKEND_URL` env var
  (default `http://127.0.0.1:8765`).

Production `server.py` wires the context in its `lifespan` startup so
plugins always hit the same ASGI instance. Tests replace the context
via `set_context(PluginContext(app=…))`. The module-level default is
lazily built from env vars, preserving backward compat for any code
that runs before `set_context()` is called.

## Safety notes

`TestClient` is safe to instantiate against an already-running app:
it routes requests through an ASGITransport and runs each request in
its own anyio portal. It does NOT re-run the app's lifespan events
(we never `with` the TestClient instance), so calling it from within
the same FastAPI process doesn't double-init the DB.

A `PluginContext` caches whichever client it uses (TestClient or
httpx.Client) for the life of the context to avoid per-request setup.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

log = logging.getLogger("dialekt.plugin_context")

_DEFAULT_BASE_URL = "http://127.0.0.1:8765"


class _PersistentASGIClient:
    """A sync httpx-shaped client whose ASGI transport uses ONE long-lived
    anyio portal (and therefore one event loop) across all requests.

    Why this exists:
    ``httpx.Client(transport=ASGITransport(app))`` and
    ``fastapi.testclient.TestClient`` both spin a *fresh* anyio portal per
    request (each call goes through ``anyio.from_thread.start_blocking_portal``).
    Each portal creates a new event loop. ``asyncpg`` connection pools are
    tied to the loop they were instantiated on, so the *second* in-process
    query reliably fails with ``another operation is in progress`` because
    it's dispatched on a different loop than the pool.

    Solution: open a single ``BlockingPortal`` up-front and reuse it for
    every request via ``httpx.AsyncClient + ASGITransport`` scheduled on
    that portal. Pool built on portal-loop → all subsequent queries run
    on portal-loop → asyncpg stays happy.
    """

    def __init__(self, app: Any) -> None:
        import anyio.from_thread
        self._app = app
        # start_blocking_portal() returns a context manager; .__enter__()
        # spins up a dedicated thread + loop. We own its lifecycle and
        # tear it down in close().
        self._portal_cm = anyio.from_thread.start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        self._async_client = self._portal.call(self._build_async_client)
        # Single flag flipped by close(); race-safe enough for the
        # "worker calls _call while lifespan shutdown runs close()"
        # scenario we actually care about. Threads observing it half-
        # set just fall into the existing RuntimeError path below.
        self._closed = False

    def _build_async_client(self):
        import httpx
        transport = httpx.ASGITransport(app=self._app)
        return httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            timeout=30.0,
        )

    def _call(self, method: str, path: str, **kwargs):
        # Route the async call onto the persistent portal loop.
        # During lifespan shutdown the portal can be torn down while an
        # OI worker thread is mid-dispatch; anyio raises RuntimeError
        # ("portal is closed" or "no running event loop") from
        # portal.call(). Surface that as a transport failure that the
        # plugin layer already knows how to render, instead of letting
        # it bubble up as an unhandled exception and crash the turn.
        if self._closed:
            raise RuntimeError("PluginContext client is closed")
        async def _run():
            return await getattr(self._async_client, method)(path, **kwargs)
        try:
            return self._portal.call(_run)
        except RuntimeError as e:
            # Re-raise with clearer diagnostic so sql_language.py /
            # retry_loop.py format it as a "SQL transport error".
            raise RuntimeError(
                f"PluginContext portal unavailable ({e}) — "
                "server likely shutting down"
            ) from e

    def post(self, path, **kwargs):   return self._call("post",   path, **kwargs)
    def get(self, path, **kwargs):    return self._call("get",    path, **kwargs)
    def delete(self, path, **kwargs): return self._call("delete", path, **kwargs)
    def patch(self, path, **kwargs):  return self._call("patch",  path, **kwargs)

    def close(self) -> None:
        # Flip the flag first — any concurrent _call() checks it before
        # touching the portal and raises a clean RuntimeError.
        self._closed = True
        try:
            async def _close():
                await self._async_client.aclose()
            self._portal.call(_close)
        except Exception:
            log.debug("_PersistentASGIClient async close failed", exc_info=True)
        try:
            self._portal_cm.__exit__(None, None, None)
        except Exception:
            log.debug("_PersistentASGIClient portal teardown failed", exc_info=True)


class PluginContext:
    """Unified backend access for dialekt plugins.

    Prefer `PluginContext(app=...)` when the caller runs inside the same
    process as the FastAPI app (production + unit tests). Fall back to
    `PluginContext(base_url=...)` or no args for HTTP dispatch.
    """

    def __init__(
        self,
        app: Any = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.app = app
        # Resolve base_url at init time so that monkeypatching env in tests
        # works through explicit set_context() rather than lazy re-reads.
        self.base_url = base_url or os.environ.get(
            "DIALEKT_BACKEND_URL", _DEFAULT_BASE_URL
        )
        self._client = None  # TestClient OR httpx.Client; built on first use
        # close() is terminal — once called, any subsequent HTTP-verb method
        # raises instead of lazily rebuilding a fresh client. This prevents
        # a race where set_context(new) close()'s the old context while a
        # worker thread still holds a reference and would otherwise spin up
        # a new portal thread on next .post().
        self._closed = False

    # ── Client factory ──────────────────────────────────────────────────────

    def _build_client(self):
        if self.app is not None:
            return _PersistentASGIClient(self.app)
        import httpx
        return httpx.Client(base_url=self.base_url, timeout=30.0)

    def _client_ref(self):
        if self._closed:
            raise RuntimeError("PluginContext is closed")
        if self._client is None:
            self._client = self._build_client()
        return self._client

    # ── HTTP-shaped surface (mirrors httpx.Client for drop-in use) ─────────

    def post(self, path: str, **kwargs) -> Any:
        return self._client_ref().post(path, **kwargs)

    def get(self, path: str, **kwargs) -> Any:
        return self._client_ref().get(path, **kwargs)

    def delete(self, path: str, **kwargs) -> Any:
        return self._client_ref().delete(path, **kwargs)

    def patch(self, path: str, **kwargs) -> Any:
        return self._client_ref().patch(path, **kwargs)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def close(self) -> None:
        """Terminally close the context.

        Once closed, any subsequent `.post()` / `.get()` / etc. raises
        ``RuntimeError("PluginContext is closed")`` instead of lazily
        rebuilding a fresh client. This matters during runtime context
        swaps (lifespan shutdown, test teardown, set_context(new)) —
        without this guard a worker thread that outlives the swap would
        get a brand-new portal thread on the next call, leaking
        resources and operating against a stale context.

        TestClient doesn't require explicit close when never entered as
        a context manager — the ASGITransport is stateless — but the
        persistent-portal variant does.
        """
        if self._closed:
            return  # idempotent
        self._closed = True
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    # Best effort — a plugin context outliving its
                    # owner shouldn't bring the server down.
                    log.debug("PluginContext close failed", exc_info=True)
        self._client = None

    def describe(self) -> dict:
        """Diagnostic shape for logs / test assertions."""
        return {
            "mode": "in-process" if self.app is not None else "http",
            "base_url": self.base_url,
            "has_app": self.app is not None,
        }

    # ── MCP integration (Этап 1) ───────────────────────────────────────────

    def new_mcp_manager(self, agent_id: str, **manager_kwargs) -> Any:
        """Build a fresh ``MCPClientManager`` bound to this context.

        The caller owns the lifecycle — ``await manager.shutdown()``
        when the chat session ends. PluginContext does not cache
        managers because their lifetime is agent-session-scoped, not
        context-scoped; caching them here would leak MCP subprocesses
        and HTTP clients across sessions.

        By default the manager's audit callback forwards events to
        this context's ``POST /audit/log`` endpoint, so audit rows
        land in the SQLite ``audit_log`` table through the normal
        in-process ASGI dispatch. Callers may override
        ``audit_callback`` by passing it in ``manager_kwargs``.
        """
        from dialekt.mcp.manager import MCPClientManager

        audit_cb = manager_kwargs.pop(
            "audit_callback", self._default_audit_callback
        )
        return MCPClientManager(
            agent_id=agent_id,
            audit_callback=audit_cb,
            **manager_kwargs,
        )

    def _default_audit_callback(self, **payload) -> None:
        """Forward an audit event to ``POST /audit/log``.

        Called from ``MCPClientManager._emit_audit`` via
        ``asyncio.to_thread`` so the sync HTTP round-trip does not
        block the calling task's event loop.
        """
        self.post("/audit/log", json=payload)


# ── Module-level default (lazy, thread-safe) ────────────────────────────────
#
# Dialekt's WebSocket chat spawns one threading.Thread per active chat turn
# (server.py's run_oi). Each thread's Open Interpreter may call DialektSQL,
# which calls get_context(). Without a lock, two simultaneous first turns
# could both enter the `is None` branch and each build a PluginContext —
# the loser is orphaned (httpx.Client + background portal thread leak).
#
# Fix: double-checked locking. Fast path (already-initialised) takes no
# lock. Slow path (first init OR explicit override via set_context) holds
# _context_lock. Both paths share the lock so set_context can observe a
# consistent global.

_default_context: Optional[PluginContext] = None
_context_lock = threading.Lock()


def get_context() -> PluginContext:
    """Return the active plugin context, creating a default if needed.

    The default is built lazily from the env so that plugin imports at
    interpreter startup don't fail when DIALEKT_BACKEND_URL isn't set.

    Thread-safe via double-checked locking: the common (already-built)
    path avoids the lock entirely; the first-init path synchronises so
    concurrent callers all observe the same singleton.
    """
    global _default_context
    # Fast path — already initialised, no lock needed.
    ctx = _default_context
    if ctx is not None:
        return ctx
    # Slow path — hold the lock to build exactly one context.
    with _context_lock:
        if _default_context is None:
            _default_context = PluginContext()
        return _default_context


def set_context(ctx: Optional[PluginContext]) -> None:
    """Override the module-level default context.

    Production `server.py` calls this during lifespan startup with
    `PluginContext(app=app)`. Tests use it to inject a `TestClient`-
    backed context and to restore the default between suites.

    Pass `None` to reset to a freshly-built default on next
    `get_context()`. The previous context, if any, is close()'d before
    the swap so its httpx.Client and background portal thread don't leak.
    """
    global _default_context
    with _context_lock:
        old = _default_context
        if old is not None and old is not ctx:
            try:
                old.close()
            except Exception:
                # Best-effort cleanup — a slow/failing close must not
                # block a runtime context swap or shutdown.
                log.debug("old PluginContext close failed", exc_info=True)
        _default_context = ctx


def _reset_context_for_testing() -> None:
    """Reset the module-level singleton to ``None``, closing any live
    context first. **Test-only helper** — production code must go through
    ``set_context``.

    Exposed because the thread-safety tests below deliberately stress
    the first-init race, and they need a reliable way to put the
    singleton back into its pristine state between cases.
    """
    global _default_context
    with _context_lock:
        if _default_context is not None:
            try:
                _default_context.close()
            except Exception:
                log.debug("reset: old context close failed", exc_info=True)
        _default_context = None
