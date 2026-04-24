"""The MCPServer class — dialekt's FastMCP-backed MCP server.

Thin wrapper around ``mcp.server.fastmcp.FastMCP`` that wires in our
config, audit emission, and tool registration. Actual tool
implementations live in :mod:`dialekt.mcp.server.tools` (landing in
subsequent commits).

Typical usage from the CLI entry point (``dialekt-mcp``)::

    from dialekt.mcp.server import MCPServer, load_config

    config = load_config()
    srv = MCPServer(config=config)
    srv.register_tools()
    srv.run_stdio()

``register_tools`` dispatches on ``config.enabled_categories`` —
categories not in the list contribute no tools. A category enabled
in v0.20.0 but whose implementation lives in a later commit just
registers nothing today (and the summary startup-log line flags the
gap). That keeps the boot path testable before every tool is ready.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from mcp.server.fastmcp import FastMCP

from dialekt.mcp.server.auth import RateLimiter, RateLimitExceeded
from dialekt.mcp.server.config import ApiKey, ServerConfig


log = logging.getLogger("dialekt.mcp.server")


SERVER_NAME = "dialekt"
SERVER_INSTRUCTIONS = (
    "dialekt — local AI agent platform exposed as an MCP server. "
    "Tools are grouped by category: database (list/query/describe), "
    "file (read/list under allowed_file_roots), and agent "
    "(list/get the pilot's configured agents). See docs/MCP_CLIENT_USAGE.md "
    "for the full surface."
)


class MCPServer:
    """dialekt as MCP server. Hold the FastMCP instance + config.

    Does not start anything in ``__init__`` — construction is cheap
    and side-effect-free so tests can build many instances without
    spawning or binding. ``run_stdio`` / ``run_http`` actually start
    the event loop.
    """

    def __init__(
        self,
        config: ServerConfig,
        *,
        name: str = SERVER_NAME,
        instructions: str = SERVER_INSTRUCTIONS,
        audit_callback: Optional[Callable[..., Any]] = None,
        plugin_context: Optional[Any] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._fastmcp = FastMCP(name, instructions=instructions)
        self._registered_tools: list[str] = []
        self._active_key: Optional[ApiKey] = None
        self._rate_limiter = RateLimiter(
            config.rate_limit_per_minute, clock=clock
        )
        self._audit_callback = audit_callback
        self._plugin_context = plugin_context
        self._clock = clock

    # ── Tool registration ───────────────────────────────────────────────

    def register_tools(self) -> list[str]:
        """Register every tool whose category is enabled in config.

        Returns the list of tool names that were actually registered —
        useful for tests and for the startup banner.
        """
        self._registered_tools.clear()

        enabled = set(self.config.enabled_categories)

        if "database" in enabled:
            self._register_database_tools()
        if "file" in enabled:
            self._register_file_tools()
        if "agent" in enabled:
            self._register_agent_tools()

        log.info(
            "dialekt MCP server registered %d tool(s): %s",
            len(self._registered_tools),
            sorted(self._registered_tools),
        )
        return list(self._registered_tools)

    def _register_database_tools(self) -> None:
        """Attach the 5 database tools via the tools package."""
        if self._plugin_context is None:
            log.warning(
                "database tools skipped — no plugin_context supplied; "
                "pass one to MCPServer to enable backend-proxying tools"
            )
            return
        from dialekt.mcp.server.tools.database import register_database_tools

        names = register_database_tools(self, self._plugin_context)
        self._registered_tools.extend(names)

    def _register_file_tools(self) -> None:
        """Commit 4 plugs the two file tools in here."""
        log.debug("file tools registration is a no-op until Commit 4")

    def _register_agent_tools(self) -> None:
        """Commit 5 plugs list_agents + get_agent in here."""
        log.debug("agent tools registration is a no-op until Commit 5")

    # ── Accessors used by tools / tests ─────────────────────────────────

    @property
    def fastmcp(self) -> FastMCP:
        """The underlying FastMCP instance. Tool modules mount their
        decorators on this."""
        return self._fastmcp

    @property
    def registered_tool_names(self) -> list[str]:
        return list(self._registered_tools)

    @property
    def active_key(self) -> Optional[ApiKey]:
        """The validated :class:`ApiKey` currently driving this server.

        Set via :meth:`bind_active_key` at startup (CLI entry point).
        Tools read it to (a) feed ``target`` into audit rows and
        (b) check per-key tool scoping when a key declares
        ``enabled_tools``.
        """
        return self._active_key

    def bind_active_key(self, key: ApiKey) -> None:
        """Record the validated key for the lifetime of this server.

        Raises :class:`RuntimeError` if called twice — per Decision 5
        one process serves exactly one MCP-client session, and the
        key is set once at startup.
        """
        if self._active_key is not None:
            raise RuntimeError(
                "MCPServer.active_key is already set — one process "
                "serves exactly one MCP client session"
            )
        self._active_key = key
        log.info("dialekt MCP server authenticated as key id=%r", key.id)

    # ── Call dispatch helpers ───────────────────────────────────────────

    def is_tool_allowed(self, tool_name: str) -> bool:
        """True when the active key may call ``tool_name``.

        Two gates:
          1. Server-wide category gate (``enabled_categories``) — if
             the tool's category is disabled, refuse.
          2. Per-key gate (``ApiKey.enabled_tools``) — if the key
             carries an allow-list, the tool must appear in it.

        Category membership is resolved from the tool name prefix;
        tool naming is disciplined by the ``dialekt_<category>_*`` /
        ``dialekt_query_database`` etc. convention from the design doc.
        """
        # Per-key allow-list wins when declared.
        if self._active_key and self._active_key.enabled_tools is not None:
            if tool_name not in self._active_key.enabled_tools:
                return False
        # Category gate.
        category = _infer_tool_category(tool_name)
        if category is not None and category not in self.config.enabled_categories:
            return False
        return True

    def check_rate_limit(self) -> None:
        """Record one call against the rolling 60-second window.

        Tool wrappers call this BEFORE handler dispatch so a burst
        above :attr:`ServerConfig.rate_limit_per_minute` surfaces as
        a ``rate_limited`` tool error rather than silent spam.
        """
        self._rate_limiter.check_and_record()

    def emit_audit(self, **payload) -> None:
        """Fire-and-forget audit row.

        Accepts the same kwargs shape as
        :func:`dialekt.audit.log.log_event`. ``kind`` defaults to
        ``"mcp_server_tool_call"`` and ``target`` defaults to the
        active key's id so tool handlers don't have to repeat them.
        """
        if self._audit_callback is None:
            return
        payload.setdefault("kind", "mcp_server_tool_call")
        if self._active_key is not None:
            payload.setdefault("target", self._active_key.id)
        try:
            self._audit_callback(**payload)
        except Exception:
            log.warning("audit callback failed", exc_info=True)

    # ── Run loops ───────────────────────────────────────────────────────

    def run_stdio(self) -> None:
        """Block on the stdio JSON-RPC loop. Intended for the CLI
        entry point — Claude Desktop spawns this subprocess and
        communicates over its stdin/stdout."""
        if not self.config.transport.stdio.enabled:
            raise RuntimeError(
                "stdio transport disabled in config "
                "([server.transport.stdio] enabled = false)"
            )
        log.info("dialekt MCP server starting on stdio")
        self._fastmcp.run(transport="stdio")

    def run_streamable_http(self) -> None:
        """Streamable HTTP is deferred to v0.25.0 per Decision 2."""
        raise NotImplementedError(
            "Streamable HTTP transport lands in v0.25.0 — see "
            "docs/M2_MCP_SERVER_DESIGN.md Decision 2."
        )


_CATEGORY_MARKERS: dict[str, str] = {
    # Name fragment → category. First match wins. Conservative — new
    # tools name themselves so they fit one of these patterns.
    "list_connections": "database",
    "query_database": "database",
    "list_tables": "database",
    "describe_table": "database",
    "search_schema": "database",
    "read_file": "file",
    "list_directory": "file",
    "list_agents": "agent",
    "get_agent": "agent",
}


def _infer_tool_category(tool_name: str) -> Optional[str]:
    """Map ``dialekt_<something>`` to a category string."""
    stripped = tool_name.removeprefix("dialekt_")
    for marker, category in _CATEGORY_MARKERS.items():
        if marker in stripped:
            return category
    return None
