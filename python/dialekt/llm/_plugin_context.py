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
from typing import Any, Optional

log = logging.getLogger("dialekt.plugin_context")

_DEFAULT_BASE_URL = "http://127.0.0.1:8765"


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

    # ── Client factory ──────────────────────────────────────────────────────

    def _build_client(self):
        if self.app is not None:
            from fastapi.testclient import TestClient
            # NOTE: we deliberately do NOT enter a `with` block on the
            # TestClient. Entering it runs lifespan startup/shutdown on
            # the app, which would re-init the DB and break the running
            # server. Direct method calls on TestClient bypass lifespan
            # and just pump the ASGI app via a per-request portal.
            return TestClient(self.app)
        import httpx
        return httpx.Client(base_url=self.base_url, timeout=30.0)

    def _client_ref(self):
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
        """Close the underlying httpx.Client if we own one.

        TestClient doesn't require explicit close when never entered as
        a context manager — the ASGITransport is stateless.
        """
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


# ── Module-level default (lazy) ─────────────────────────────────────────────

_default_context: Optional[PluginContext] = None


def get_context() -> PluginContext:
    """Return the active plugin context, creating a default if needed.

    The default is built lazily from the env so that plugin imports at
    interpreter startup don't fail when DIALEKT_BACKEND_URL isn't set.
    """
    global _default_context
    if _default_context is None:
        _default_context = PluginContext()
    return _default_context


def set_context(ctx: Optional[PluginContext]) -> None:
    """Override the module-level default context.

    Production `server.py` calls this during lifespan startup with
    `PluginContext(app=app)`. Tests use it to inject a `TestClient`-
    backed context and to restore the default between suites.

    Pass `None` to reset to a freshly-built default on next `get_context()`.
    """
    global _default_context
    if _default_context is not None and _default_context is not ctx:
        # Old context might own an httpx.Client — close before replacing.
        try:
            _default_context.close()
        except Exception:
            pass
    _default_context = ctx
