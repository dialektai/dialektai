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
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from dialekt.mcp.server.config import ServerConfig


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
    ) -> None:
        self.config = config
        self._fastmcp = FastMCP(name, instructions=instructions)
        self._registered_tools: list[str] = []

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
        """Commit 3 plugs the five DB tools in here."""
        log.debug("database tools registration is a no-op until Commit 3")

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
