"""Basic behaviour tests for dialekt.mcp.MCPClient.

These drive an in-memory MCP server (FastMCP) through dialekt's
client using ``mcp.shared.memory.create_connected_server_and_client_session``
as the session opener. No subprocess, no network, no filesystem —
this verifies the *shape* of our client API end-to-end on the JSON-
RPC level.

Real transports (stdio, HTTP) are covered by integration tests
added in Commits 4 and 5.
"""
import asyncio

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from dialekt.mcp import MCPClient


def _build_test_server() -> FastMCP:
    """A tiny FastMCP server exposing two tools, for in-memory tests."""
    server = FastMCP("dialekt-test-server")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    @server.tool()
    def echo(text: str) -> str:
        """Echo back the input."""
        return text

    return server


def _client_with_in_memory_server(server: FastMCP) -> MCPClient:
    """Build an MCPClient wired to an in-memory FastMCP server."""
    client = MCPClient.from_stdio_command(["sentinel"])  # transport ignored
    client._session_opener = lambda: create_connected_server_and_client_session(server)
    return client


def test_list_tools_returns_advertised_tools():
    async def run():
        client = _client_with_in_memory_server(_build_test_server())
        async with client:
            result = await client.list_tools()
            names = {t.name for t in result.tools}
            assert "add" in names
            assert "echo" in names

    asyncio.run(run())


def test_call_tool_round_trip_returns_structured_result():
    async def run():
        client = _client_with_in_memory_server(_build_test_server())
        async with client:
            result = await client.call_tool("add", {"a": 2, "b": 3})
            # FastMCP returns the scalar wrapped in a TextContent list.
            assert not result.isError
            assert result.content, "tool returned empty content"
            text_item = result.content[0]
            assert getattr(text_item, "text", None) == "5"

    asyncio.run(run())


def test_call_tool_with_unknown_name_sets_is_error():
    async def run():
        client = _client_with_in_memory_server(_build_test_server())
        async with client:
            result = await client.call_tool("nonexistent_tool", {})
            assert result.isError is True

    asyncio.run(run())


def test_session_property_before_open_raises():
    client = MCPClient.from_http_url("https://example.invalid/mcp")
    with pytest.raises(RuntimeError, match="not open"):
        _ = client.session


def test_aenter_twice_raises():
    async def run():
        client = _client_with_in_memory_server(_build_test_server())
        async with client:
            with pytest.raises(RuntimeError, match="already open"):
                await client.__aenter__()

    asyncio.run(run())


def test_aexit_cleans_up_session_reference():
    async def run():
        client = _client_with_in_memory_server(_build_test_server())
        async with client:
            pass
        # After exit, session reads must fail.
        with pytest.raises(RuntimeError, match="not open"):
            _ = client.session

    asyncio.run(run())


def test_http_transport_not_yet_wired():
    async def run():
        client = MCPClient.from_http_url("https://example.invalid/mcp")
        with pytest.raises(NotImplementedError, match="Commit 5"):
            async with client:
                pass

    asyncio.run(run())
