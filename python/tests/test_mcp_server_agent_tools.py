"""Tests for dialekt.mcp.server.tools.agent."""
from dataclasses import dataclass, field
from typing import Any

import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools.agent import register_agent_tools


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
            ("GET", path), _FakeResponse(status_code=404, _json={})
        )

    def post(self, path: str, **kw) -> _FakeResponse:
        self.calls.append({"method": "POST", "path": path})
        return self.responses.get(
            ("POST", path), _FakeResponse(status_code=404, _json={})
        )


def _build_server(ctx, **srv_kwargs):
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(),
        audit_callback=lambda **p: events.append(p),
        plugin_context=ctx,
        **srv_kwargs,
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_agent_tools(srv, ctx)
    return srv, events


# ---------------------------------------------------------------------------
# Registration shape.
# ---------------------------------------------------------------------------


def test_registration_exposes_exactly_two_tools():
    ctx = _FakePluginContext()
    srv, _ = _build_server(ctx)
    names = set(srv.fastmcp._tool_manager._tools.keys())
    # Exactly the two read tools — invoke_agent deliberately absent.
    assert "dialekt_list_agents" in names
    assert "dialekt_get_agent" in names
    assert "dialekt_invoke_agent" not in names


# ---------------------------------------------------------------------------
# dialekt_list_agents.
# ---------------------------------------------------------------------------


def test_list_agents_trims_backend_fields():
    """We strip manifest_yaml + created_at from the list view — they're
    verbose; get_agent returns them for detail."""
    ctx = _FakePluginContext(responses={
        ("GET", "/agents"): _FakeResponse(_json=[
            {
                "id": "a1",
                "name": "SQL Analyst",
                "description": "does SQL",
                "version": "1.0.0",
                "status": "published",
                "manifest_yaml": "x" * 5000,  # big, should be dropped
                "created_at": "2026-04-01T00:00:00Z",
            },
            {
                "id": "a2",
                "name": "Report Gen",
                "description": "",
                "version": "0.1.0",
                "status": "draft",
                "manifest_yaml": "y" * 2000,
                "created_at": "2026-04-02T00:00:00Z",
            },
        ])
    })
    srv, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_agents"].fn
    out = tool()
    assert len(out) == 2
    for entry in out:
        assert set(entry.keys()) == {
            "id", "name", "description", "version", "status"
        }


def test_list_agents_backend_error_raises():
    ctx = _FakePluginContext(responses={
        ("GET", "/agents"): _FakeResponse(status_code=500, _json={}),
    })
    srv, events = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_agents"].fn
    with pytest.raises(RuntimeError, match="list_agents failed"):
        tool()
    errors = [e for e in events if e.get("result") == "error"]
    assert len(errors) == 1
    assert errors[0]["error_kind"] == "RuntimeError"


# ---------------------------------------------------------------------------
# dialekt_get_agent.
# ---------------------------------------------------------------------------


def test_get_agent_merges_binding():
    ctx = _FakePluginContext(responses={
        ("GET", "/agents/a1"): _FakeResponse(_json={
            "id": "a1",
            "name": "SQL Analyst",
            "manifest_yaml": "spec_version: ...",
        }),
        ("GET", "/agents/a1/binding"): _FakeResponse(_json={
            "connection_id": "pg-prod",
            "connection_type": "postgres",
        }),
    })
    srv, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_get_agent"].fn
    out = tool(agent_id="a1")
    assert out["id"] == "a1"
    assert out["binding"]["connection_id"] == "pg-prod"


def test_get_agent_without_binding():
    """Agent exists but no binding configured — still returns the
    agent, just without a binding key."""
    ctx = _FakePluginContext(responses={
        ("GET", "/agents/a1"): _FakeResponse(_json={
            "id": "a1",
            "name": "Orphan Agent",
        }),
        ("GET", "/agents/a1/binding"): _FakeResponse(status_code=404, _json={}),
    })
    srv, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_get_agent"].fn
    out = tool(agent_id="a1")
    assert out["id"] == "a1"
    assert "binding" not in out


def test_get_agent_not_found_returns_structured_error():
    ctx = _FakePluginContext(responses={
        ("GET", "/agents/missing"): _FakeResponse(status_code=404, _json={}),
    })
    srv, _ = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_get_agent"].fn
    out = tool(agent_id="missing")
    assert out["error"] is True
    assert out["reason"] == "not_found"


def test_get_agent_audit_carries_id():
    ctx = _FakePluginContext(responses={
        ("GET", "/agents/a1"): _FakeResponse(_json={"id": "a1"}),
        ("GET", "/agents/a1/binding"): _FakeResponse(status_code=404, _json={}),
    })
    srv, events = _build_server(ctx)
    tool = srv.fastmcp._tool_manager._tools["dialekt_get_agent"].fn
    tool(agent_id="a1")
    success = [e for e in events if e.get("result") == "success"]
    assert success[0]["extra"]["agent_id"] == "a1"
