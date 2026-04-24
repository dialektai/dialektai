"""dialekt.mcp — Model Context Protocol integration.

Two halves, both landing in M2 Month 1:

- ``dialekt.mcp.client`` — consumer side. Talks to external MCP
  servers declared in an agent manifest's ``mcp_servers`` block.
- ``dialekt.mcp.server`` — producer side (Этап 2). Exposes dialekt
  itself as an MCP server so external hosts (Claude Desktop, etc.)
  can drive it.

This package is *not* related to ``python/mcp_servers/`` — the
latter is dialekt's internal FastAPI database connectors and is
being renamed to ``python/db_connectors/`` in a later commit. See
``docs/TERMINOLOGY_CLARIFICATION.md``.
"""
from dialekt.mcp.auth import BearerAuth, Credentials, EnvVarsAuth, NoAuth
from dialekt.mcp.client import MCPClient
from dialekt.mcp.connection import MCPConnection
from dialekt.mcp.secrets_resolver import (
    has_unresolved_refs,
    keyring_key,
    resolve_env,
    resolve_secret_refs,
)
from dialekt.mcp.errors import (
    MCPConfigError,
    MCPError,
    MCPProtocolError,
    MCPRateLimitError,
    MCPServerUnavailableError,
    MCPTimeoutError,
    MCPToolError,
    MCPToolNotFoundError,
)
from dialekt.mcp.transport import (
    HttpTransportSpec,
    StdioTransportSpec,
    TransportSpec,
)

__all__ = [
    # client
    "MCPClient",
    "MCPConnection",
    # transport
    "TransportSpec",
    "StdioTransportSpec",
    "HttpTransportSpec",
    # auth
    "Credentials",
    "NoAuth",
    "EnvVarsAuth",
    "BearerAuth",
    # secrets (Decision 2)
    "resolve_secret_refs",
    "resolve_env",
    "keyring_key",
    "has_unresolved_refs",
    # errors (Decision 6)
    "MCPError",
    "MCPConfigError",
    "MCPServerUnavailableError",
    "MCPToolNotFoundError",
    "MCPToolError",
    "MCPTimeoutError",
    "MCPRateLimitError",
    "MCPProtocolError",
]
