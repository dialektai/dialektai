"""Connection lifecycle for an open MCP server.

``MCPConnection`` owns the pair of resources that make up a live
connection: the transport context (stdio subprocess or HTTP stream)
and the ``mcp.ClientSession`` riding on top of it. Constructing one
is cheap; *opening* one spawns a process or dials a URL.

Skeleton in this commit — method bodies raise ``NotImplementedError``.
Real implementation lands with the transport commits (4-5).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from dialekt.mcp.auth import Credentials
from dialekt.mcp.transport import TransportSpec

if TYPE_CHECKING:
    from mcp import ClientSession


class MCPConnection:
    """Owns one live connection to an MCP server.

    Instances are expected to be obtained through ``MCPClient``, not
    constructed directly. They implement the async context manager
    protocol — ``async with conn:`` opens and initializes the
    session; exit tears it down.
    """

    def __init__(
        self,
        transport: TransportSpec,
        credentials: Credentials,
    ) -> None:
        self.transport = transport
        self.credentials = credentials
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "MCPConnection":
        raise NotImplementedError(
            "MCPConnection.__aenter__ wires up in Commits 4-5 "
            "(stdio + HTTP transports)."
        )

    async def __aexit__(self, exc_type, exc, tb) -> None:
        raise NotImplementedError(
            "MCPConnection.__aexit__ wires up in Commits 4-5."
        )

    @property
    def session(self) -> "ClientSession":
        if self._session is None:
            raise RuntimeError(
                "MCPConnection is not open — use `async with conn:` first."
            )
        return self._session
