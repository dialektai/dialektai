"""Classify raw exceptions (SDK, anyio, subprocess) into the dialekt
MCP error taxonomy from ``docs/M2_MCP_DESIGN.md`` Decision 6.

The motivation: MCPClientManager wraps every call to the underlying
``mcp.ClientSession`` so the rest of dialekt never has to catch
``anyio.ClosedResourceError`` or ``BaseExceptionGroup`` or a bare
``ConnectionRefusedError``. Callers get ``MCPServerUnavailableError``
(or another named subclass) with a useful message, and the audit
log gets a single canonical ``error_kind`` column value.

This module is intentionally a thin mapping — no decisions, just
dispatch. Add new branches when a new SDK failure mode shows up;
don't absorb behaviour here.
"""
from __future__ import annotations

import builtins

from dialekt.mcp.errors import (
    MCPError,
    MCPProtocolError,
    MCPServerUnavailableError,
    MCPTimeoutError,
    MCPToolNotFoundError,
)


# BaseExceptionGroup landed in Python 3.11. Dialekt ships on 3.12 but
# the SDK supports 3.10 — use getattr so importing this module on 3.10
# remains safe even if the unwrap branch is inert there.
_BaseExceptionGroup = getattr(builtins, "BaseExceptionGroup", None)


def classify_sdk_error(exc: BaseException) -> MCPError:
    """Map an arbitrary exception from the SDK layer into an MCPError.

    Already-classified errors (``MCPError`` subclasses) pass through
    unchanged so the manager can call ``classify_sdk_error`` on every
    path uniformly.
    """
    if isinstance(exc, MCPError):
        return exc

    # ExceptionGroup — anyio task groups surface cancellations as
    # a group. Unwrap the single interesting exception if we can; a
    # group with a mix of shapes is a protocol anomaly.
    if _BaseExceptionGroup is not None and isinstance(exc, _BaseExceptionGroup):
        inner = getattr(exc, "exceptions", None)
        if inner and len(inner) == 1:
            return classify_sdk_error(inner[0])

    name = type(exc).__name__
    msg = str(exc) or name

    # Timeout-shaped exceptions come from asyncio.timeout and httpx.
    if name in ("TimeoutError", "CancelledError") or "timeout" in name.lower():
        return MCPTimeoutError(msg)

    # Connection-shaped — subprocess absent, TCP refused, DNS miss,
    # transport closed mid-handshake.
    connection_shapes = (
        "ConnectionRefusedError",
        "ConnectionError",
        "FileNotFoundError",
        "ProcessLookupError",
        "ClosedResourceError",
        "EndOfStream",
        "BrokenResourceError",
        "ConnectError",
        "ReadError",
        "WriteError",
        "RemoteProtocolError",
    )
    if name in connection_shapes:
        return MCPServerUnavailableError(msg)

    # MCP-level protocol errors.
    if name in ("McpError", "JSONRPCError") or name.startswith("InvalidRequest"):
        return MCPProtocolError(msg)

    # Tool-not-found distinction: some servers return a 404-like
    # error via MCP rather than isError=True. The dialekt call_tool
    # path already inspects isError before this classifier runs, so
    # reaching here with a "no such tool" message is rare. Keep the
    # branch for completeness.
    if "tool" in msg.lower() and (
        "not found" in msg.lower() or "unknown" in msg.lower()
    ):
        return MCPToolNotFoundError(msg)

    # Fall back: treat unknown failures as server unavailable so the
    # LLM can potentially route around them. This is safer than a
    # protocol error (which short-circuits any reconnect) and more
    # accurate than a timeout (which implies the server was still
    # talking).
    return MCPServerUnavailableError(
        f"unclassified MCP failure ({name}): {msg}"
    )
