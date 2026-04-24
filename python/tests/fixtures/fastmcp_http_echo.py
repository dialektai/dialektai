"""Tiny FastMCP Streamable HTTP server used by test_mcp_http.py.

Launched as a subprocess by the test. Reads the desired port from
argv[1] and binds to 127.0.0.1:<port>. Prints "READY" on stdout
once the HTTP server is listening so the parent test can wait
without a timing race.
"""
from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP


server = FastMCP("dialekt-http-test")


@server.tool()
def add(a: int, b: int) -> int:
    """Return ``a + b``."""
    return a + b


@server.tool()
def echo(text: str) -> str:
    """Echo back the input."""
    return text


def _run(port: int) -> None:
    # FastMCP's .run(transport="streamable-http", ...) wraps uvicorn
    # but doesn't accept host/port args directly in 1.26. Use
    # streamable_http_app() + uvicorn.run for explicit control.
    import uvicorn

    app = server.streamable_http_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    s = uvicorn.Server(config)

    import asyncio

    async def _main() -> None:
        # Signal readiness right before starting to serve; uvicorn's
        # own bind check happens during serve(), so flush BEFORE so
        # parent's port-check race is short.
        print("READY", flush=True)
        await s.serve()

    asyncio.run(_main())


if __name__ == "__main__":
    _run(int(sys.argv[1]))
