"""Tests for ``dialekt.mcp.server.tools.http``.

Uses :class:`httpx.MockTransport` to intercept requests at the
transport layer — no live network — exercising the validation,
truncation, timeout, and error-classification surface that real
agents will rely on.
"""
from __future__ import annotations

import json

import httpx
import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools import http as http_tools
from dialekt.mcp.server.tools.http import (
    MAX_BODY_BYTES,
    MAX_TIMEOUT,
    _clamp_timeout,
    _validate_url,
    register_http_tools,
)


def _build_server(transport: httpx.MockTransport):
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_http_tools(srv)
    return srv, events


@pytest.fixture
def install_mock_transport(monkeypatch):
    """Monkeypatches the http_tools._build_client seam so every
    request inside the test goes through a caller-supplied
    MockTransport handler."""

    def _install(handler):
        transport = httpx.MockTransport(handler)

        def _factory(timeout):
            return httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)

        monkeypatch.setattr(http_tools, "_build_client", _factory)
        return transport

    return _install


# ---------------------------------------------------------------------------
# _validate_url
# ---------------------------------------------------------------------------


def test_validate_url_accepts_http():
    assert _validate_url("http://example.com/x") is None


def test_validate_url_accepts_https():
    assert _validate_url("https://example.com") is None


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "ftp://example.com",
    "javascript:alert(1)",
    "data:text/html,abc",
])
def test_validate_url_rejects_other_schemes(bad):
    out = _validate_url(bad)
    assert out is not None
    assert out["reason"] == "unsupported_scheme"


def test_validate_url_rejects_missing_host():
    out = _validate_url("https://")
    assert out is not None
    assert out["reason"] == "invalid_url"


def test_validate_url_rejects_empty():
    out = _validate_url("")
    assert out is not None


# ---------------------------------------------------------------------------
# _clamp_timeout
# ---------------------------------------------------------------------------


def test_clamp_timeout_default_when_none():
    assert _clamp_timeout(None) == 30.0


def test_clamp_timeout_caps_at_max():
    assert _clamp_timeout(9999) == MAX_TIMEOUT


def test_clamp_timeout_replaces_zero_with_default():
    assert _clamp_timeout(0) == 30.0


def test_clamp_timeout_passes_through_valid():
    assert _clamp_timeout(15) == 15.0


# ---------------------------------------------------------------------------
# dialekt_http_get
# ---------------------------------------------------------------------------


def test_http_get_happy_path(install_mock_transport):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"ok": True}, headers={"x-trace": "abc"})

    install_mock_transport(handler)
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_get"].fn
    out = tool(url="https://example.com/api")
    assert out["status"] == 200
    assert json.loads(out["body"]) == {"ok": True}
    assert out["headers"]["x-trace"] == "abc"
    assert out["truncated"] is False


def test_http_get_rejects_unsupported_scheme(install_mock_transport):
    install_mock_transport(lambda r: httpx.Response(200))
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_get"].fn
    out = tool(url="file:///etc/passwd")
    assert out["error"] is True
    assert out["reason"] == "unsupported_scheme"


def test_http_get_truncates_oversized_body(install_mock_transport):
    big = b"x" * (MAX_BODY_BYTES + 1024)

    def handler(request):
        return httpx.Response(200, content=big)

    install_mock_transport(handler)
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_get"].fn
    out = tool(url="https://example.com/big")
    assert out["truncated"] is True
    assert out["body_bytes"] == MAX_BODY_BYTES


def test_http_get_passes_headers(install_mock_transport):
    seen: dict[str, str] = {}

    def handler(request):
        seen.update(dict(request.headers))
        return httpx.Response(200, text="ok")

    install_mock_transport(handler)
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_get"].fn
    tool(url="https://example.com", headers={"X-Auth": "secret"})
    assert seen.get("x-auth") == "secret"


def test_http_get_classifies_timeout(install_mock_transport, monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("simulated timeout")

    install_mock_transport(handler)
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_get"].fn
    out = tool(url="https://example.com", timeout=1)
    assert out["error"] is True
    assert out["reason"] == "timeout"


def test_http_get_classifies_request_failure(install_mock_transport):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    install_mock_transport(handler)
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_get"].fn
    out = tool(url="https://example.com")
    assert out["error"] is True
    assert out["reason"] == "request_failed"
    assert out["error_kind"] == "ConnectError"


# ---------------------------------------------------------------------------
# dialekt_http_post
# ---------------------------------------------------------------------------


def test_http_post_with_json(install_mock_transport):
    payload_seen: dict = {}

    def handler(request: httpx.Request):
        payload_seen.update(json.loads(request.content))
        return httpx.Response(201, json={"id": 42})

    install_mock_transport(handler)
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_post"].fn
    out = tool(url="https://example.com/items", json={"name": "x"})
    assert out["status"] == 201
    assert payload_seen == {"name": "x"}


def test_http_post_with_raw_body(install_mock_transport):
    bodies: list[bytes] = []

    def handler(request: httpx.Request):
        bodies.append(request.content)
        return httpx.Response(200)

    install_mock_transport(handler)
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_post"].fn
    tool(url="https://example.com/raw", body="<xml/>")
    assert bodies == [b"<xml/>"]


def test_http_post_rejects_both_body_and_json(install_mock_transport):
    install_mock_transport(lambda r: httpx.Response(200))
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_post"].fn
    out = tool(url="https://example.com", body="x", json={"y": 1})
    assert out["error"] is True
    assert out["reason"] == "conflicting_body"


# ---------------------------------------------------------------------------
# dialekt_http_put
# ---------------------------------------------------------------------------


def test_http_put_happy_path(install_mock_transport):
    def handler(request):
        assert request.method == "PUT"
        return httpx.Response(204)

    install_mock_transport(handler)
    srv, _ = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_put"].fn
    out = tool(url="https://example.com/x", json={"a": 1})
    assert out["status"] == 204


# ---------------------------------------------------------------------------
# Audit + category gating
# ---------------------------------------------------------------------------


def test_http_get_emits_audit(install_mock_transport):
    install_mock_transport(lambda r: httpx.Response(200, text="ok"))
    srv, events = _build_server(transport=None)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_get"].fn
    tool(url="https://example.com/x")
    success = [e for e in events if e.get("result") == "success"]
    assert any(e["action"] == "dialekt_http_get" for e in success)
    assert success[-1]["extra"]["url"] == "https://example.com/x"


def test_http_category_disabled_refuses(install_mock_transport):
    install_mock_transport(lambda r: httpx.Response(200))
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(enabled_categories=["database"]),  # http excluded
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_http_tools(srv)
    tool = srv.fastmcp._tool_manager._tools["dialekt_http_get"].fn
    with pytest.raises(ToolAccessDenied):
        tool(url="https://example.com")
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
