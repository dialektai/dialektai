"""Tests for dialekt.mcp.server.tools.database.

The tools proxy to dialekt's HTTP API via a PluginContext. Tests
inject a fake PluginContext that records requests and returns
scripted responses — this exercises the full tool path end-to-end
without a real backend.
"""
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools.database import (
    _TYPE_TO_PREFIX,
    register_database_tools,
)


@dataclass
class _FakeResponse:
    status_code: int = 200
    _json: Any = None
    text: str = ""

    def json(self) -> Any:
        return self._json


@dataclass
class _FakePluginContext:
    """Records every .get/.post call; returns scripted responses per path."""
    responses: dict[tuple[str, str], _FakeResponse] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)

    def get(self, path: str, **kw) -> _FakeResponse:
        self.calls.append({"method": "GET", "path": path, "kw": kw})
        return self.responses.get(
            ("GET", path), _FakeResponse(status_code=404, _json={})
        )

    def post(self, path: str, **kw) -> _FakeResponse:
        self.calls.append({"method": "POST", "path": path, "kw": kw})
        return self.responses.get(
            ("POST", path), _FakeResponse(status_code=404, _json={})
        )


def _build_server(plugin_context):
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(),
        audit_callback=lambda **p: events.append(p),
        plugin_context=plugin_context,
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    names = register_database_tools(srv, plugin_context)
    return srv, names, events


# ---------------------------------------------------------------------------
# Registration shape.
# ---------------------------------------------------------------------------


def test_registration_returns_five_tool_names():
    ctx = _FakePluginContext()
    srv, names, _ = _build_server(ctx)
    assert set(names) == {
        "dialekt_list_connections",
        "dialekt_query_database",
        "dialekt_list_tables",
        "dialekt_describe_table",
        "dialekt_search_schema",
    }


def test_type_prefix_map_covers_three_dbs():
    assert set(_TYPE_TO_PREFIX) == {"postgres", "mysql", "clickhouse"}


# ---------------------------------------------------------------------------
# dialekt_list_connections.
# ---------------------------------------------------------------------------


def test_list_connections_combines_three_backends():
    ctx = _FakePluginContext(responses={
        ("GET", "/connections"): _FakeResponse(
            _json=[{"id": "pg1", "name": "prod", "type": "postgresql",
                    "password": "SECRET"}]
        ),
        ("GET", "/mysql-connections"): _FakeResponse(
            _json=[{"id": "mysql1", "name": "staging"}]
        ),
        ("GET", "/ch-connections"): _FakeResponse(
            _json=[{"id": "ch1", "name": "events"}]
        ),
    })
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_connections"].fn
    connections = tool()
    assert len(connections) == 3
    connection_types = {c["connection_type"] for c in connections}
    assert connection_types == {"postgres", "mysql", "clickhouse"}
    # Passwords scrubbed even if backend accidentally returns them.
    assert all("password" not in c for c in connections)


def test_list_connections_tolerates_individual_driver_failure():
    """One driver down doesn't blank the whole list."""
    ctx = _FakePluginContext(responses={
        ("GET", "/connections"): _FakeResponse(
            _json=[{"id": "pg1", "name": "prod"}]
        ),
        ("GET", "/mysql-connections"): _FakeResponse(
            status_code=500, _json={"detail": "driver down"}
        ),
        ("GET", "/ch-connections"): _FakeResponse(_json=[]),
    })
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_connections"].fn
    out = tool()
    # pg survived; mysql skipped; ch empty.
    assert len(out) == 1
    assert out[0]["connection_type"] == "postgres"


# ---------------------------------------------------------------------------
# dialekt_query_database.
# ---------------------------------------------------------------------------


def test_query_database_postgres_happy_path():
    ctx = _FakePluginContext(responses={
        ("POST", "/connections/pg1/query"): _FakeResponse(
            _json={"rows": [{"n": 1}], "row_count": 1}
        ),
    })
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_query_database"].fn
    result = tool(connection_id="pg1", sql="SELECT 1")
    assert result["row_count"] == 1
    assert result["rows"] == [{"n": 1}]
    # Verify the request went to the right prefix.
    call = ctx.calls[-1]
    assert call["method"] == "POST"
    assert call["path"] == "/connections/pg1/query"
    assert call["kw"]["json"]["sql"] == "SELECT 1"


def test_query_database_mysql_routes_to_mysql_prefix():
    ctx = _FakePluginContext(responses={
        ("POST", "/mysql-connections/my1/query"): _FakeResponse(
            _json={"rows": [], "row_count": 0}
        ),
    })
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_query_database"].fn
    tool(connection_id="my1", sql="SELECT 1", connection_type="mysql")
    assert ctx.calls[-1]["path"] == "/mysql-connections/my1/query"


def test_query_database_clickhouse_routes_to_ch_prefix():
    ctx = _FakePluginContext(responses={
        ("POST", "/ch-connections/c1/query"): _FakeResponse(
            _json={"rows": [], "row_count": 0}
        ),
    })
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_query_database"].fn
    tool(connection_id="c1", sql="SELECT 1", connection_type="clickhouse")
    assert ctx.calls[-1]["path"] == "/ch-connections/c1/query"


def test_query_database_unknown_type_raises():
    ctx = _FakePluginContext()
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_query_database"].fn
    with pytest.raises(ValueError, match="Unknown connection_type"):
        tool(connection_id="x", sql="SELECT 1", connection_type="oracle")


def test_query_database_backend_error_surfaces_structured():
    ctx = _FakePluginContext(responses={
        ("POST", "/connections/pg1/query"): _FakeResponse(
            status_code=400, _json={"detail": "DROP TABLE rejected"}
        ),
    })
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_query_database"].fn
    result = tool(connection_id="pg1", sql="DROP TABLE x")
    assert result["error"] is True
    assert result["status"] == 400


# ---------------------------------------------------------------------------
# dialekt_list_tables.
# ---------------------------------------------------------------------------


def test_list_tables_nests_by_schema():
    ctx = _FakePluginContext(responses={
        ("GET", "/connections/pg1/schemas"): _FakeResponse(
            _json=["public", "private"]
        ),
        ("GET", "/connections/pg1/schemas/public/tables"): _FakeResponse(
            _json=["users", "orders"]
        ),
        ("GET", "/connections/pg1/schemas/private/tables"): _FakeResponse(
            _json=["secrets"]
        ),
    })
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_tables"].fn
    out = tool(connection_id="pg1")
    assert out == {"public": ["users", "orders"], "private": ["secrets"]}


# ---------------------------------------------------------------------------
# dialekt_describe_table.
# ---------------------------------------------------------------------------


def test_describe_table_passes_through_backend_shape():
    ctx = _FakePluginContext(responses={
        ("GET", "/connections/pg1/schemas/public/tables/users/describe"):
            _FakeResponse(_json={
                "columns": [{"name": "id", "type": "int"}],
                "primary_key": ["id"],
            }),
    })
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_describe_table"].fn
    out = tool(connection_id="pg1", schema="public", table="users")
    assert out["primary_key"] == ["id"]


# ---------------------------------------------------------------------------
# dialekt_search_schema.
# ---------------------------------------------------------------------------


def test_search_schema_calls_rag_endpoint():
    ctx = _FakePluginContext(responses={
        ("POST", "/connections/pg1/schema-rag/search"): _FakeResponse(
            _json=[{"table": "orders", "score": 0.87}]
        ),
    })
    srv, _, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_search_schema"].fn
    out = tool(connection_id="pg1", query="top customers by revenue")
    assert out[0]["table"] == "orders"


# ---------------------------------------------------------------------------
# Audit emission.
# ---------------------------------------------------------------------------


def test_success_emits_audit_row():
    ctx = _FakePluginContext(responses={
        ("GET", "/connections"): _FakeResponse(_json=[]),
        ("GET", "/mysql-connections"): _FakeResponse(_json=[]),
        ("GET", "/ch-connections"): _FakeResponse(_json=[]),
    })
    srv, _, events = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_connections"].fn
    tool()
    success = [e for e in events if e.get("result") == "success"]
    assert len(success) == 1
    assert success[0]["action"] == "dialekt_list_connections"
    assert success[0]["target"] == "test"  # active key id


def test_error_emits_audit_with_error_kind():
    ctx = _FakePluginContext()  # no responses → 404 by default, raises RuntimeError
    ctx.responses[("GET", "/connections/pg1/schemas")] = _FakeResponse(
        status_code=500, _json={"detail": "boom"}
    )
    srv, _, events = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_tables"].fn
    with pytest.raises(RuntimeError):
        tool(connection_id="pg1")
    errors = [e for e in events if e.get("result") == "error"]
    assert len(errors) == 1
    assert errors[0]["error_kind"] == "RuntimeError"


def test_permission_denied_emits_audit():
    ctx = _FakePluginContext()
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(enabled_categories=["file"]),  # DB disabled
        audit_callback=lambda **p: events.append(p),
        plugin_context=ctx,
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_database_tools(srv, ctx)

    tool = srv.fastmcp._tool_manager._tools["dialekt_list_connections"].fn
    from dialekt.mcp.server.tools._wrap import ToolAccessDenied

    with pytest.raises(ToolAccessDenied):
        tool()
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
