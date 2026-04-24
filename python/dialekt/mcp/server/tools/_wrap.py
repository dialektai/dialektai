"""Shared tool-call wrapper for the MCP server.

Every tool handler in the category modules runs through this:

    1. Check per-key + per-category allow (``server.is_tool_allowed``)
    2. Check rate limit (``server.check_rate_limit``)
    3. Run the handler
    4. Emit one audit row regardless of outcome

This is the server-side mirror of
:meth:`dialekt.mcp.manager.MCPClientManager.call_tool` from Этап 1 —
same rate-limit + timeout + audit discipline, adapted for the
single-process, single-session model of the server.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, TYPE_CHECKING

from dialekt.mcp.server.auth import RateLimitExceeded

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


log = logging.getLogger("dialekt.mcp.server.tools")


class ToolAccessDenied(Exception):
    """Tool call rejected by the server-side permission gate.

    Surfaces to the MCP protocol as an ``isError=true`` tool result
    carrying ``result='permission_denied'`` in the audit row.
    """


def call_tool_wrapped(
    server: "MCPServer",
    tool_name: str,
    handler: Callable[[], Any],
    *,
    extra_audit: dict[str, Any] | None = None,
) -> Any:
    """Run ``handler()`` with the full wrap. Returns the handler's
    return value.

    Errors are classified and re-raised; the audit row is always
    emitted — the only way to bypass it is to skip this wrapper,
    which no tool module does.
    """
    if not server.is_tool_allowed(tool_name):
        server.emit_audit(
            action=tool_name,
            result="permission_denied",
            error_kind="ToolAccessDenied",
            extra=extra_audit,
        )
        raise ToolAccessDenied(
            f"{tool_name!r} is not enabled for the active API key. "
            "Check [server] enabled_categories and api_keys[].enabled_tools "
            "in ~/.dialekt/mcp-server.toml."
        )

    try:
        server.check_rate_limit()
    except RateLimitExceeded as e:
        server.emit_audit(
            action=tool_name,
            result="rate_limited",
            error_kind="RateLimitExceeded",
            extra=extra_audit,
        )
        raise

    start = time.monotonic()
    try:
        result = handler()
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        server.emit_audit(
            action=tool_name,
            result="error",
            duration_ms=duration_ms,
            error_kind=type(e).__name__,
            extra=extra_audit,
        )
        raise

    duration_ms = int((time.monotonic() - start) * 1000)
    server.emit_audit(
        action=tool_name,
        result="success",
        duration_ms=duration_ms,
        extra=extra_audit,
    )
    return result
