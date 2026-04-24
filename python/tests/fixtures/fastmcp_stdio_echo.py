"""Tiny FastMCP server used by test_mcp_stdio.py.

Launched as a subprocess; talks MCP over stdin/stdout. Keep this
server minimal — integration tests should exercise dialekt's
transport wiring, not FastMCP behaviour. Two tools is enough:
``add`` (structured arg in, scalar out) and ``echo_env`` (reads an
env var to prove the parent's env-passing logic works).
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP


server = FastMCP("dialekt-stdio-test")


@server.tool()
def add(a: int, b: int) -> int:
    """Return ``a + b``."""
    return a + b


@server.tool()
def echo_env(name: str) -> str:
    """Return the value of env var ``name``, or empty string."""
    return os.environ.get(name, "")


if __name__ == "__main__":
    server.run(transport="stdio")
