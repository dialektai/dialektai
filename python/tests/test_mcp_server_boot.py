"""Tests for the MCPServer skeleton.

Boot-path only — actual tool behaviour ships in Commits 3/4/5 and is
tested separately. Here we verify construction is side-effect-free,
FastMCP is wired, and register_tools dispatches correctly on the
config's ``enabled_categories``.
"""
import pytest

from dialekt.mcp.server import MCPServer, ServerConfig


def test_construction_is_side_effect_free():
    """Building an MCPServer should not bind ports, spawn subprocesses,
    or touch the network. Tests rely on this to make many instances."""
    server = MCPServer(ServerConfig())
    assert server.registered_tool_names == []
    assert server.fastmcp.name == "dialekt"


def test_register_tools_noop_when_no_tools_implemented():
    """Before Commits 3/4/5 land the actual tool modules, register_tools
    is a no-op — but it must still return cleanly (not raise) so the
    boot path is testable end-to-end."""
    server = MCPServer(ServerConfig())
    registered = server.register_tools()
    assert registered == []


def test_register_tools_honors_disabled_categories():
    """Disabling 'database' should prevent the database register step
    from running — currently a no-op, but the decision point must
    already exist."""
    server = MCPServer(ServerConfig(enabled_categories=["file", "agent"]))
    registered = server.register_tools()
    assert registered == []


def test_run_stdio_refuses_when_disabled():
    server = MCPServer(ServerConfig())
    server.config.transport.stdio.enabled = False
    with pytest.raises(RuntimeError, match="stdio transport disabled"):
        server.run_stdio()


def test_run_http_not_yet_implemented():
    server = MCPServer(ServerConfig())
    with pytest.raises(NotImplementedError, match="v0.25.0"):
        server.run_streamable_http()


def test_fastmcp_is_the_sdk_class():
    """The .fastmcp property must return an actual SDK FastMCP, not a
    wrapper. Tool modules (Commits 3/4/5) attach decorators directly."""
    from mcp.server.fastmcp import FastMCP

    server = MCPServer(ServerConfig())
    assert isinstance(server.fastmcp, FastMCP)


def test_server_instructions_non_empty():
    """FastMCP requires instructions to be visible to clients. Empty
    text would surface as a bad user experience when Claude Desktop
    lists our server."""
    server = MCPServer(ServerConfig())
    # FastMCP stores this on settings.instructions.
    assert server.fastmcp.instructions  # truthy non-empty
