"""End-to-end server test: dialekt MCPServer driven by a real MCP
client via in-memory transport.

The client side of Этап 1 already ships
``mcp.shared.memory.create_connected_server_and_client_session``
which plumbs a FastMCP instance + ``ClientSession`` together over
an in-process stream pair. This test leverages that: build a
full MCPServer (config + bound key + fake backend PluginContext +
registered tools), hand its ``fastmcp`` to the SDK helper, drive
it with a standard ``ClientSession`` and verify the round-trip.

What this proves:
- Every tool we register shows up in list_tools over the real wire
  (not just via direct .fn access).
- call_tool from a client dispatches through the server's full
  audit + permission + rate-limit pipeline.
- Exit from the session closes cleanly.

What this does NOT prove (covered elsewhere):
- Auth (validate_api_key): unit-tested in test_mcp_server_auth.py.
- CLI wiring: unit-tested in test_mcp_server_cli.py.
- Real Claude Desktop integration: manual smoke, documented in
  docs/MCP_SERVER_INTEGRATION.md.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey


# ---------------------------------------------------------------------------
# Fake PluginContext: same shape as the other tool tests, recording calls
# and returning scripted responses so the e2e runs without a real dialekt
# backend.
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    status_code: int = 200
    _json: Any = None

    def json(self) -> Any:
        return self._json


@dataclass
class _FakePluginContext:
    responses: dict[tuple[str, str], _FakeResponse] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)

    def get(self, path: str, **kw) -> _FakeResponse:
        self.calls.append({"method": "GET", "path": path})
        return self.responses.get(
            ("GET", path),
            _FakeResponse(status_code=404, _json={}),
        )

    def post(self, path: str, **kw) -> _FakeResponse:
        self.calls.append({"method": "POST", "path": path, "kw": kw})
        return self.responses.get(
            ("POST", path),
            _FakeResponse(status_code=404, _json={}),
        )


def _build_full_server(tmp_path) -> tuple[MCPServer, _FakePluginContext, list[dict]]:
    """Build an MCPServer with all three tool categories registered
    and a fake backend wired up."""
    ctx = _FakePluginContext(responses={
        ("GET", "/connections"): _FakeResponse(
            _json=[{"id": "pg1", "name": "prod", "type": "postgresql"}]
        ),
        ("GET", "/mysql-connections"): _FakeResponse(_json=[]),
        ("GET", "/ch-connections"): _FakeResponse(_json=[]),
        ("GET", "/agents"): _FakeResponse(_json=[
            {"id": "a1", "name": "SQL Analyst", "version": "1.0.0",
             "status": "published"}
        ]),
    })
    events: list[dict] = []

    # File tools need an allow-list to be useful; point at tmp_path so
    # the file-tool surface is exercised too.
    config = ServerConfig(
        allowed_file_roots=[str(tmp_path)],
    )

    server = MCPServer(
        config=config,
        plugin_context=ctx,
        audit_callback=lambda **p: events.append(p),
    )
    server.bind_active_key(ApiKey(id="e2e-client", value="x" * 32))
    server.register_tools()

    return server, ctx, events


# ---------------------------------------------------------------------------
# End-to-end round-trip.
# ---------------------------------------------------------------------------


def test_client_lists_all_registered_tools(tmp_path):
    """A real MCP client over in-memory transport sees every tool we
    registered — 5 DB + 2 file + 2 agent = 9 total."""
    async def run():
        server, _, _ = _build_full_server(tmp_path)

        async with create_connected_server_and_client_session(
            server.fastmcp,
        ) as session:
            result = await session.list_tools()
            names = {t.name for t in result.tools}
            # DB tools
            assert "dialekt_list_connections" in names
            assert "dialekt_query_database" in names
            assert "dialekt_list_tables" in names
            assert "dialekt_describe_table" in names
            assert "dialekt_search_schema" in names
            # File tools
            assert "dialekt_read_file" in names
            assert "dialekt_list_directory" in names
            # Agent tools
            assert "dialekt_list_agents" in names
            assert "dialekt_get_agent" in names
            # invoke_agent deliberately NOT in v0.20.0
            assert "dialekt_invoke_agent" not in names

            assert len(names) == 9

    asyncio.run(run())


def test_call_tool_over_wire_success(tmp_path):
    """Calling list_connections from a client returns the fake backend
    data AND records a success audit row."""
    async def run():
        server, ctx, events = _build_full_server(tmp_path)
        async with create_connected_server_and_client_session(
            server.fastmcp,
        ) as session:
            result = await session.call_tool(
                "dialekt_list_connections", {}
            )
            assert result.isError is False
            # FastMCP wraps the JSON return into TextContent; the
            # text block carries the JSON-serialised list.
            assert result.content

        # Audit row fired during the wire call.
        success = [e for e in events if e.get("result") == "success"]
        assert len(success) == 1
        assert success[0]["action"] == "dialekt_list_connections"
        assert success[0]["target"] == "e2e-client"

    asyncio.run(run())


def test_call_tool_file_read_over_wire(tmp_path):
    """File tools respect the allow-list across the wire transition."""
    target = tmp_path / "readme.txt"
    target.write_text("dialekt e2e marker")

    async def run():
        server, _, _ = _build_full_server(tmp_path)
        async with create_connected_server_and_client_session(
            server.fastmcp,
        ) as session:
            result = await session.call_tool(
                "dialekt_read_file", {"path": str(target)}
            )
            assert result.isError is False
            text_blob = result.content[0].text
            assert "dialekt e2e marker" in text_blob

    asyncio.run(run())


def test_rate_limit_trips_over_wire(tmp_path):
    """Drop the limit to 2, call 3 times, last one surfaces as a tool
    error with rate_limit semantics."""
    async def run():
        ctx = _FakePluginContext(responses={
            ("GET", "/connections"): _FakeResponse(_json=[]),
            ("GET", "/mysql-connections"): _FakeResponse(_json=[]),
            ("GET", "/ch-connections"): _FakeResponse(_json=[]),
            ("GET", "/agents"): _FakeResponse(_json=[]),
        })
        events: list[dict] = []
        config = ServerConfig(rate_limit_per_minute=2)
        server = MCPServer(
            config=config,
            plugin_context=ctx,
            audit_callback=lambda **p: events.append(p),
        )
        server.bind_active_key(ApiKey(id="e2e-rl", value="x" * 32))
        server.register_tools()

        async with create_connected_server_and_client_session(
            server.fastmcp,
        ) as session:
            # Two succeed.
            await session.call_tool("dialekt_list_connections", {})
            await session.call_tool("dialekt_list_connections", {})
            # Third trips.
            third = await session.call_tool(
                "dialekt_list_connections", {}
            )
            assert third.isError is True

        rate_limited = [e for e in events if e.get("result") == "rate_limited"]
        assert len(rate_limited) == 1
        assert rate_limited[0]["error_kind"] == "RateLimitExceeded"

    asyncio.run(run())


def test_permission_denied_over_wire(tmp_path):
    """Per-key enabled_tools allow-list rejection surfaces as a tool
    error, with a permission_denied audit row."""
    async def run():
        ctx = _FakePluginContext(responses={
            ("GET", "/connections"): _FakeResponse(_json=[]),
            ("GET", "/mysql-connections"): _FakeResponse(_json=[]),
            ("GET", "/ch-connections"): _FakeResponse(_json=[]),
            ("GET", "/agents"): _FakeResponse(_json=[]),
        })
        events: list[dict] = []
        server = MCPServer(
            config=ServerConfig(),
            plugin_context=ctx,
            audit_callback=lambda **p: events.append(p),
        )
        # Scope the key to list_agents only.
        server.bind_active_key(ApiKey(
            id="scoped",
            value="x" * 32,
            enabled_tools=["dialekt_list_agents"],
        ))
        server.register_tools()

        async with create_connected_server_and_client_session(
            server.fastmcp,
        ) as session:
            # Allowed tool works.
            ok = await session.call_tool("dialekt_list_agents", {})
            assert ok.isError is False
            # Disallowed tool returns error.
            denied = await session.call_tool(
                "dialekt_list_connections", {}
            )
            assert denied.isError is True

        pd = [e for e in events if e.get("result") == "permission_denied"]
        assert len(pd) == 1


    asyncio.run(run())
