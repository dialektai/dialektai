"""Streamable HTTP transport opener for dialekt's MCP client.

Symmetric companion to ``transport_stdio.py``. Opens a
``mcp.client.streamable_http.streamable_http_client`` session and
layers an ``mcp.ClientSession`` on top.

See ``docs/M2_MCP_DESIGN.md`` Decisions 1 (transport), 2 (auth),
and 6 (errors).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from dialekt.mcp.auth import BearerAuth, Credentials
from dialekt.mcp.transport import HttpTransportSpec

if TYPE_CHECKING:
    pass


def _build_request_headers(credentials: Credentials) -> dict[str, str]:
    """Translate a credentials object into HTTP request headers.

    Only ``BearerAuth`` contributes today. ``NoAuth`` is empty, and
    ``EnvVarsAuth`` is a stdio-only shape that the manifest validator
    is expected to reject on HTTP transports — ignoring it silently
    here keeps the runtime defensive.
    """
    headers: dict[str, str] = {}
    if isinstance(credentials, BearerAuth):
        headers["Authorization"] = f"Bearer {credentials.token}"
    return headers


@asynccontextmanager
async def open_http_session(
    transport: HttpTransportSpec,
    credentials: Credentials,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> AsyncIterator[ClientSession]:
    """Open an initialized ``ClientSession`` over Streamable HTTP.

    Production code path passes ``http_client=None`` — the SDK
    constructs its default ``httpx.AsyncClient`` pointed at
    ``transport.url``.

    Tests can pass a pre-built ``httpx.AsyncClient`` (for example
    one using ``httpx.ASGITransport`` against a ``FastMCP`` app
    with lifespan pre-triggered) to bypass real TCP. See
    ``tests/test_mcp_http.py``.

    Error surfacing is intentionally thin in this commit — ``httpx``
    and ``streamable_http_client`` exceptions bubble unwrapped.
    Commit 7 classifies them into the dialekt taxonomy with audit
    emission.
    """
    headers = _build_request_headers(credentials)

    owns_client = False
    if http_client is None:
        http_client = httpx.AsyncClient(
            base_url=transport.url,
            timeout=transport.timeout_seconds,
            headers=headers,
        )
        owns_client = True
    else:
        # Caller-supplied client; overlay our auth headers onto its
        # default_headers so each request carries them.
        for k, v in headers.items():
            http_client.headers[k] = v

    try:
        async with streamable_http_client(
            transport.url, http_client=http_client
        ) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    finally:
        if owns_client:
            await http_client.aclose()
