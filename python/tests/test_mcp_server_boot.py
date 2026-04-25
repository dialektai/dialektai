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


def test_register_tools_no_plugin_context_skips_backend_tools():
    """Without a PluginContext, database + agent tools can't proxy
    backend calls — their register paths early-return. File tools are
    local and still register (default allowed_file_roots is empty, so
    they refuse every path at call time; that behaviour is covered in
    test_mcp_server_file_tools)."""
    server = MCPServer(ServerConfig())
    registered = server.register_tools()
    # File tools always register (no backend dependency).
    assert "dialekt_read_file" in registered
    assert "dialekt_list_directory" in registered
    # DB + agent tools skip because no plugin_context was supplied.
    assert "dialekt_list_connections" not in registered
    assert "dialekt_list_agents" not in registered


def test_register_tools_honors_disabled_categories():
    """Disabling a category must prevent its tools from registering."""
    server = MCPServer(ServerConfig(enabled_categories=["file"]))
    registered = server.register_tools()
    assert "dialekt_read_file" in registered
    # DB + agent absent.
    for name in (
        "dialekt_list_connections",
        "dialekt_query_database",
        "dialekt_list_agents",
        "dialekt_get_agent",
    ):
        assert name not in registered


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
