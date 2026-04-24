"""MCP client — dialekt's consumer side.

Used by agents (via ``PluginContext``) to talk to external MCP
servers the manifest declares. Construction goes through one of the
factory classmethods; after that the instance is an async context
manager that yields tool discovery + invocation.

Skeleton in this commit. The factories and the context manager are
declared; ``list_tools`` and ``call_tool`` raise ``NotImplementedError``
— implemented in Commit 3 on top of an in-memory transport, with
real stdio / HTTP transports landing in Commits 4 and 5 respectively.

See ``docs/M2_MCP_DESIGN.md`` Decisions 1, 4, 5, 6.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dialekt.mcp.auth import Credentials, EnvVarsAuth, NoAuth
from dialekt.mcp.connection import MCPConnection
from dialekt.mcp.transport import (
    HttpTransportSpec,
    StdioTransportSpec,
    TransportSpec,
)

if TYPE_CHECKING:
    from mcp import ListToolsResult
    from mcp.types import CallToolResult


class MCPClient:
    """Declarative handle to an external MCP server.

    Construction is cheap and has no side effects — no process is
    spawned, no URL is hit, no credentials are read from the keyring.
    The connection opens only when the instance is entered as an
    async context manager.
    """

    def __init__(
        self,
        transport: TransportSpec,
        credentials: Credentials | None = None,
    ) -> None:
        self.transport = transport
        self.credentials = credentials or NoAuth()
        self._connection: MCPConnection | None = None

    @classmethod
    def from_stdio_command(
        cls,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> "MCPClient":
        """Build a client for a locally-spawned MCP server subprocess."""
        transport = StdioTransportSpec(
            command=list(command),
            env=dict(env or {}),
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )
        credentials: Credentials = (
            EnvVarsAuth(vars=dict(env)) if env else NoAuth()
        )
        return cls(transport=transport, credentials=credentials)

    @classmethod
    def from_http_url(
        cls,
        url: str,
        *,
        auth_token: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> "MCPClient":
        """Build a client for a remote Streamable HTTP MCP server."""
        transport = HttpTransportSpec(
            url=url,
            timeout_seconds=timeout_seconds,
        )
        credentials: Credentials
        if auth_token:
            from dialekt.mcp.auth import BearerAuth

            credentials = BearerAuth(token=auth_token)
        else:
            credentials = NoAuth()
        return cls(transport=transport, credentials=credentials)

    async def __aenter__(self) -> "MCPClient":
        raise NotImplementedError(
            "MCPClient.__aenter__ is implemented in Commit 3 "
            "(basic MCPClient) against an in-memory transport."
        )

    async def __aexit__(self, exc_type, exc, tb) -> None:
        raise NotImplementedError(
            "MCPClient.__aexit__ is implemented in Commit 3."
        )

    async def list_tools(self) -> "ListToolsResult":
        raise NotImplementedError("implemented in Commit 3")

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> "CallToolResult":
        raise NotImplementedError("implemented in Commit 3")
