"""dialekt.mcp.server — dialekt exposed as an MCP server.

Symmetric counterpart to ``dialekt.mcp.client`` from Этап 1. Where the
client lets agents consume external MCP servers, this package lets
external MCP hosts (Claude Desktop, Cursor, custom) drive dialekt
through the Model Context Protocol.

See ``docs/M2_MCP_SERVER_DESIGN.md`` for the seven design decisions
that shaped this surface.

Public API:
- :class:`MCPServer` — the top-level server object
- :class:`ServerConfig` — parsed + validated config shape
- :func:`load_config` — read ``~/.dialekt/mcp-server.toml``

The actual tool implementations live in ``dialekt.mcp.server.tools``
(landing in subsequent commits).
"""
from dialekt.mcp.server.config import (
    DEFAULT_CONFIG_PATH,
    ApiKey,
    HttpTransportConfig,
    ServerConfig,
    StdioTransportConfig,
    TransportConfig,
    load_config,
)
from dialekt.mcp.server.server import MCPServer

__all__ = [
    "ApiKey",
    "DEFAULT_CONFIG_PATH",
    "HttpTransportConfig",
    "MCPServer",
    "ServerConfig",
    "StdioTransportConfig",
    "TransportConfig",
    "load_config",
]
