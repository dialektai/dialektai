"""FastAPI app for the dialekt GPU Relay.

Endpoints (all under ``/relay``):

  GET  /health         reachability + Ollama status. No auth.
  GET  /models         proxy GET /api/tags. Auth (Commit 2).
  POST /generate       proxy POST /api/generate. Auth + billing (C2/C3).
  POST /chat           proxy POST /api/chat. Auth + billing (C2/C3).
                       Returns StreamingResponse for ``stream=true``.
  POST /embeddings     proxy POST /api/embeddings. Auth (C2). Not billed.

Stateless: no prompts or responses persisted. Only token counts +
timestamps, landing in ``relay_usage`` once Commit 3 wires billing.

Implementation note: the relay holds a single shared
``httpx.AsyncClient`` for the lifetime of the app — Ollama keep-alive
matters for streaming throughput, and FastAPI lifespans give us a clean
construct/teardown surface.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import httpx
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from dialekt.relay import __version__
from dialekt.relay.auth import RateLimiterRegistry, RelayKeyContext, get_relay_context
from dialekt.relay.billing import maybe_record
from dialekt.relay.config import RelayConfig, load_config

log = logging.getLogger("dialekt.relay")


def create_app(config: Optional[RelayConfig] = None) -> FastAPI:
    """Build and return the relay FastAPI app.

    Tests pass a custom :class:`RelayConfig` whose ``ollama_url`` points
    at an in-memory stub; production startup goes through ``__main__``
    which loads from disk.
    """
    cfg = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Long read-timeout because Ollama generations can take minutes
        # on small models / large prompts. ``read=None`` disables it
        # entirely — we rely on the downstream client disconnecting if
        # it loses interest, which closes the upstream stream too.
        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
        client = httpx.AsyncClient(base_url=cfg.ollama_url, timeout=timeout)
        app.state.ollama = client
        app.state.config = cfg
        app.state.rate_limiter_registry = RateLimiterRegistry()

        # asyncpg pool to dialekt_cloud for relay_keys lookups. When
        # cloud_db_url is missing the relay still starts (so /relay/health
        # works for connectivity probes), but get_relay_context raises 503
        # for any authenticated endpoint.
        if cfg.cloud_db_url:
            import asyncpg
            app.state.pool = await asyncpg.create_pool(
                cfg.cloud_db_url, min_size=1, max_size=10,
            )
        else:
            app.state.pool = None
            log.warning(
                "relay started without cloud_db_url — auth disabled, "
                "/relay/{models,generate,chat,embeddings} will return 503"
            )

        log.info(
            "relay started — version=%s ollama=%s db=%s",
            __version__, cfg.ollama_url, "yes" if cfg.cloud_db_url else "no",
        )
        try:
            yield
        finally:
            await client.aclose()
            if app.state.pool is not None:
                await app.state.pool.close()

    app = FastAPI(
        title="dialekt GPU Relay",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,   # operator surface, no public Swagger
        redoc_url=None,
    )

    @app.get("/relay/health")
    async def health(request: Request) -> dict:
        client: httpx.AsyncClient = request.app.state.ollama
        ollama_reachable = False
        try:
            r = await client.get("/api/tags", timeout=2.0)
            ollama_reachable = r.status_code == 200
        except httpx.HTTPError:
            ollama_reachable = False
        return {
            "ok": True,
            "version": __version__,
            "ollama_reachable": ollama_reachable,
        }

    @app.get("/relay/models")
    async def models(
        request: Request,
        ctx: RelayKeyContext = Depends(get_relay_context),
    ) -> Response:
        client: httpx.AsyncClient = request.app.state.ollama
        r = await client.get("/api/tags")
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/json"),
        )

    @app.post("/relay/generate")
    async def generate(
        request: Request,
        ctx: RelayKeyContext = Depends(get_relay_context),
    ) -> Response:
        return await _proxy_inference(request, "/api/generate", ctx)

    @app.post("/relay/chat")
    async def chat(
        request: Request,
        ctx: RelayKeyContext = Depends(get_relay_context),
    ) -> Response:
        return await _proxy_inference(request, "/api/chat", ctx)

    @app.post("/relay/embeddings")
    async def embeddings(
        request: Request,
        ctx: RelayKeyContext = Depends(get_relay_context),
    ) -> Response:
        client: httpx.AsyncClient = request.app.state.ollama
        body = await request.body()
        r = await client.post(
            "/api/embeddings",
            content=body,
            headers={
                "content-type": request.headers.get(
                    "content-type", "application/json"
                ),
            },
        )
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/json"),
        )

    return app


async def _proxy_inference(
    request: Request,
    ollama_path: str,
    ctx: RelayKeyContext,
) -> Response:
    """Forward a /generate or /chat request to Ollama as a streamed
    pass-through, then record usage from the terminal NDJSON chunk.

    Whether the response actually streams is decided by Ollama based on
    the ``stream`` field in the request body. We always read it as a
    stream upstream so streaming clients get bytes immediately;
    non-streaming clients still see one JSON blob, just delivered
    through the same pipe.

    Billing happens in the generator's ``finally`` block: every chunk
    is appended to a buffer, and after the stream closes we look for
    the ``done: true`` line and write a ``relay_usage`` row. The
    buffer scales with the response size — typically a few KB for a
    chat reply — so the memory cost is bounded by the response and
    released as soon as the request completes.
    """
    client: httpx.AsyncClient = request.app.state.ollama
    pool = request.app.state.pool
    body_bytes = await request.body()

    # Capture the requested model from the body so billing can attribute
    # usage even if the response stream is malformed. The response's own
    # ``model`` field overrides this when present (Ollama may resolve a
    # tag to a different real model).
    request_model = "unknown"
    try:
        parsed = json.loads(body_bytes)
        if isinstance(parsed, dict) and isinstance(parsed.get("model"), str):
            request_model = parsed["model"]
    except (json.JSONDecodeError, ValueError):
        pass

    headers = {
        "content-type": request.headers.get("content-type", "application/json"),
    }

    upstream = client.build_request(
        "POST", ollama_path, content=body_bytes, headers=headers,
    )
    response = await client.send(upstream, stream=True)

    start = time.monotonic()

    async def passthrough() -> AsyncIterator[bytes]:
        captured = bytearray()
        try:
            try:
                async for chunk in response.aiter_raw():
                    captured.extend(chunk)
                    yield chunk
            except httpx.StreamConsumed:
                # MockTransport / very-small replies arrive pre-buffered.
                # See note in Commit 1 — passthrough is shape-agnostic.
                buf = response.content
                captured.extend(buf)
                yield buf
        finally:
            await response.aclose()
            # Record usage after the stream has fully closed. ``maybe_record``
            # is best-effort: missing token counts (errors, aborted runs)
            # short-circuit without an INSERT, exceptions are logged.
            if response.status_code == 200:
                await maybe_record(
                    pool, ctx,
                    request_model=request_model,
                    response_buffer=bytes(captured),
                    start_monotonic=start,
                    now_monotonic=time.monotonic(),
                )

    return StreamingResponse(
        passthrough(),
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/x-ndjson"),
    )
