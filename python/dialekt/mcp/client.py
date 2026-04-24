"""MCP client — dialekt's consumer side.

Used by agents (via ``PluginContext``) to talk to external MCP
servers the manifest declares. Construction goes through one of the
factory classmethods; the instance is an async context manager that
yields tool discovery + invocation.

Transport wiring is layered:

    - ``_build_session_opener`` dispatches on the transport kind and
      returns the async-context-manager factory that will open a
      ``mcp.ClientSession`` when entered.
    - For stdio → the dispatcher currently raises ``NotImplementedError``;
      Commit 4 plugs in ``mcp.client.stdio.stdio_client``.
    - For HTTP → same story, Commit 5 plugs in
      ``mcp.client.streamable_http.streamablehttp_client``.

Tests bypass transport entirely by assigning a custom
``_session_opener`` before entering the client — for example, a
``mcp.shared.memory.create_connected_server_and_client_session``
bound to an in-process ``FastMCP`` server.

See ``docs/M2_MCP_DESIGN.md`` Decisions 1, 4, 6.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from dialekt.mcp.auth import Credentials, EnvVarsAuth, NoAuth
from dialekt.mcp.errors import MCPConfigError
from dialekt.mcp.transport import (
    HttpTransportSpec,
    StdioTransportSpec,
    TransportSpec,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from mcp import ClientSession, ListToolsResult
    from mcp.types import CallToolResult


SessionOpener = Callable[[], "AbstractAsyncContextManager[ClientSession]"]


class MCPClient:
    """Declarative handle to an external MCP server.

    Construction is cheap and has no side effects — no process is
    spawned, no URL is hit, no credentials are read from the keyring.
    The connection opens only when the instance is entered as an
    async context manager::

        client = MCPClient.from_stdio_command([...])
        async with client:
            tools = await client.list_tools()
            result = await client.call_tool("name", {"arg": "value"})
    """

    def __init__(
        self,
        transport: TransportSpec,
        credentials: Credentials | None = None,
    ) -> None:
        self.transport = transport
        self.credentials = credentials or NoAuth()
        self._session: ClientSession | None = None
        self._session_ctx: AbstractAsyncContextManager[ClientSession] | None = None
        self._session_opener: SessionOpener | None = None

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
        if self._session is not None:
            raise RuntimeError("MCPClient is already open.")

        opener = self._session_opener or self._build_session_opener()
        self._session_ctx = opener()
        self._session = await self._session_ctx.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        ctx = self._session_ctx
        self._session = None
        self._session_ctx = None
        if ctx is not None:
            await ctx.__aexit__(exc_type, exc, tb)

    @property
    def session(self) -> "ClientSession":
        """The underlying ``mcp.ClientSession``. Only valid while open."""
        if self._session is None:
            raise RuntimeError(
                "MCPClient is not open — use `async with client:` first."
            )
        return self._session

    async def list_tools(self) -> "ListToolsResult":
        """Return the tool catalog the server advertises."""
        return await self.session.list_tools()

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> "CallToolResult":
        """Invoke a tool by name with structured arguments.

        Thin pass-through today; Commit 7 will add the PluginContext
        integration layer that wraps this call with rate-limiting,
        timeout handling, and audit-log emission.
        """
        return await self.session.call_tool(name, arguments or {})

    def _build_session_opener(self) -> SessionOpener:
        """Return a factory that opens a ``ClientSession`` for this transport.

        Overridden by test setup (``client._session_opener = ...``)
        and by the transport commits (4-5) which plug in the real
        stdio and HTTP session openers from the MCP SDK.
        """
        if isinstance(self.transport, StdioTransportSpec):
            raise NotImplementedError(
                "stdio transport wiring lands in Commit 4"
            )
        if isinstance(self.transport, HttpTransportSpec):
            raise NotImplementedError(
                "Streamable HTTP transport wiring lands in Commit 5"
            )
        raise MCPConfigError(
            f"unknown transport kind: {type(self.transport).__name__}"
        )
