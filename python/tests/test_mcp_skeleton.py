"""Skeleton-level import + shape tests for dialekt.mcp.

This test file verifies Commit 2 deliverables only: the package is
importable, public surface is what the design document promises, and
the factory classmethods build well-typed instances. Runtime
behaviour (list_tools, call_tool, transport lifecycle) is covered by
later commit test files.
"""
import pytest


def test_package_public_api_matches_design():
    """dialekt.mcp re-exports every symbol listed in Decision 6 + client surface."""
    import dialekt.mcp as mcp

    expected = {
        "MCPClient",
        "MCPConnection",
        "TransportSpec",
        "StdioTransportSpec",
        "HttpTransportSpec",
        "Credentials",
        "NoAuth",
        "EnvVarsAuth",
        "BearerAuth",
        # 7 error classes per Decision 6 + one base
        "MCPError",
        "MCPConfigError",
        "MCPServerUnavailableError",
        "MCPToolNotFoundError",
        "MCPToolError",
        "MCPTimeoutError",
        "MCPRateLimitError",
        "MCPProtocolError",
    }
    missing = expected - set(mcp.__all__)
    assert not missing, f"missing from __all__: {missing}"
    for name in expected:
        assert hasattr(mcp, name), f"dialekt.mcp missing: {name}"


def test_error_taxonomy_is_rooted_at_mcperror():
    from dialekt.mcp import (
        MCPConfigError,
        MCPError,
        MCPProtocolError,
        MCPRateLimitError,
        MCPServerUnavailableError,
        MCPTimeoutError,
        MCPToolError,
        MCPToolNotFoundError,
    )

    assert issubclass(MCPError, RuntimeError)
    for exc in (
        MCPConfigError,
        MCPServerUnavailableError,
        MCPToolNotFoundError,
        MCPToolError,
        MCPTimeoutError,
        MCPRateLimitError,
        MCPProtocolError,
    ):
        assert issubclass(exc, MCPError)


def test_from_stdio_command_builds_stdio_transport():
    from dialekt.mcp import MCPClient, StdioTransportSpec

    client = MCPClient.from_stdio_command(
        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        env={"EXAMPLE_VAR": "v"},
        cwd="/tmp",
        timeout_seconds=15.0,
    )
    assert isinstance(client.transport, StdioTransportSpec)
    assert client.transport.kind == "stdio"
    assert client.transport.command[0] == "npx"
    assert client.transport.env == {"EXAMPLE_VAR": "v"}
    assert client.transport.cwd == "/tmp"
    assert client.transport.timeout_seconds == 15.0


def test_from_stdio_command_empty_command_rejected():
    """Validator enforces list with at least one argv element."""
    from dialekt.mcp import MCPClient
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MCPClient.from_stdio_command([])


def test_from_http_url_builds_http_transport():
    from dialekt.mcp import BearerAuth, HttpTransportSpec, MCPClient

    client = MCPClient.from_http_url(
        "https://example.com/mcp",
        auth_token="abc123",
        timeout_seconds=10.0,
    )
    assert isinstance(client.transport, HttpTransportSpec)
    assert client.transport.url == "https://example.com/mcp"
    assert client.transport.timeout_seconds == 10.0
    assert isinstance(client.credentials, BearerAuth)
    assert client.credentials.token == "abc123"


def test_from_http_url_without_token_uses_noauth():
    from dialekt.mcp import MCPClient, NoAuth

    client = MCPClient.from_http_url("https://example.com/mcp")
    assert isinstance(client.credentials, NoAuth)


def test_connection_session_access_before_open_raises():
    from dialekt.mcp import MCPConnection, NoAuth, StdioTransportSpec

    conn = MCPConnection(
        transport=StdioTransportSpec(command=["cat"]),
        credentials=NoAuth(),
    )
    with pytest.raises(RuntimeError, match="not open"):
        _ = conn.session
