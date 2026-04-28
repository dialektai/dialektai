"""Tests for ``dialekt.mcp.server.tools.bitrix``.

Mocks both the httpx transport (no live Bitrix portal) and the
``dialekt.secrets`` module (no real keychain access), so the test
suite is self-contained.
"""
from __future__ import annotations

import httpx
import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools import bitrix as bitrix_tools
from dialekt.mcp.server.tools.bitrix import (
    DEFAULT_SECRET_NAME,
    _normalise_webhook_base,
    _resolve_method,
    register_bitrix_tools,
)


WEBHOOK = "https://portal.bitrix24.kz/rest/1/abcd1234"


@pytest.fixture
def install_mock_transport(monkeypatch):
    def _install(handler):
        transport = httpx.MockTransport(handler)

        def _factory(timeout):
            return httpx.Client(
                transport=transport, timeout=timeout, follow_redirects=True
            )

        monkeypatch.setattr(bitrix_tools, "_build_client", _factory)
        return transport

    return _install


@pytest.fixture
def fake_secrets(monkeypatch):
    """Replace dialekt.secrets.get_secret with a local dict-backed
    fake so tests don't reach the OS keychain."""
    store: dict[str, str] = {}

    def _get(name: str) -> str | None:
        return store.get(name)

    monkeypatch.setattr(bitrix_tools.secrets_module, "get_secret", _get)
    return store


def _build_server():
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_bitrix_tools(srv)
    return srv, events


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_resolve_method_accepts_dotted():
    assert _resolve_method("crm.deal.add") == "crm.deal.add"


def test_resolve_method_strips_leading_slash():
    assert _resolve_method("/lists.element.add") == "lists.element.add"


def test_resolve_method_rejects_traversal():
    assert _resolve_method("../etc") is None


def test_resolve_method_rejects_path_separator():
    assert _resolve_method("crm/deal/add") is None


def test_resolve_method_rejects_empty():
    assert _resolve_method("") is None
    assert _resolve_method(None) is None


def test_normalise_webhook_strips_trailing_slash():
    assert _normalise_webhook_base(WEBHOOK + "/") == WEBHOOK


def test_normalise_webhook_rejects_non_http():
    assert _normalise_webhook_base("ftp://x") is None
    assert _normalise_webhook_base("") is None
    assert _normalise_webhook_base(None) is None


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------


def test_bitrix_call_uses_secret_when_no_url(install_mock_transport, fake_secrets):
    fake_secrets[DEFAULT_SECRET_NAME] = WEBHOOK
    captured: list[str] = []

    def handler(request: httpx.Request):
        captured.append(str(request.url))
        return httpx.Response(200, json={"result": [1, 2, 3], "total": 3})

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    out = tool(method="crm.deal.list", params={"select": ["ID"]})
    assert out["status"] == 200
    assert out["result"] == [1, 2, 3]
    assert out["total"] == 3
    assert out.get("error") is not True
    # URL should be webhook + method.json
    assert captured == [f"{WEBHOOK}/crm.deal.list.json"]


def test_bitrix_call_explicit_url_overrides_secret(install_mock_transport, fake_secrets):
    fake_secrets[DEFAULT_SECRET_NAME] = "https://wrong/rest/2/x"
    captured: list[str] = []

    def handler(request):
        captured.append(str(request.url))
        return httpx.Response(200, json={"result": "ok"})

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    out = tool(method="crm.deal.list", webhook_url=WEBHOOK)
    assert out["status"] == 200
    assert captured[0] == f"{WEBHOOK}/crm.deal.list.json"


def test_bitrix_call_passes_params_as_json(install_mock_transport, fake_secrets):
    fake_secrets[DEFAULT_SECRET_NAME] = WEBHOOK
    bodies: list[bytes] = []

    def handler(request: httpx.Request):
        bodies.append(request.content)
        return httpx.Response(200, json={"result": True})

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    tool(method="lists.element.add", params={"IBLOCK_TYPE_ID": "lists", "FIELDS": {"NAME": "x"}})
    assert b'"IBLOCK_TYPE_ID":"lists"' in bodies[0]
    assert b'"NAME":"x"' in bodies[0]


def test_bitrix_call_custom_secret_name(install_mock_transport, fake_secrets):
    fake_secrets["bitrix_iba"] = WEBHOOK

    def handler(request):
        return httpx.Response(200, json={"result": "ok"})

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    out = tool(method="crm.deal.list", secret_name="bitrix_iba")
    assert out.get("error") is not True


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_bitrix_call_missing_secret_returns_error(install_mock_transport, fake_secrets):
    install_mock_transport(lambda r: httpx.Response(200))
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    out = tool(method="crm.deal.list")
    assert out["error"] is True
    assert out["reason"] == "missing_webhook"


def test_bitrix_call_invalid_method(install_mock_transport, fake_secrets):
    fake_secrets[DEFAULT_SECRET_NAME] = WEBHOOK
    install_mock_transport(lambda r: httpx.Response(200))
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    out = tool(method="../etc/passwd")
    assert out["error"] is True
    assert out["reason"] == "invalid_method"


def test_bitrix_call_surfaces_bitrix_error(install_mock_transport, fake_secrets):
    fake_secrets[DEFAULT_SECRET_NAME] = WEBHOOK

    def handler(request):
        return httpx.Response(
            400,
            json={
                "error": "INVALID_CREDENTIALS",
                "error_description": "Wrong webhook",
            },
        )

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    out = tool(method="crm.deal.list")
    assert out["error"] is True
    assert out["bitrix_error"] == "INVALID_CREDENTIALS"
    assert "Wrong webhook" in out["error_description"]


def test_bitrix_call_handles_non_json_response(install_mock_transport, fake_secrets):
    fake_secrets[DEFAULT_SECRET_NAME] = WEBHOOK
    install_mock_transport(
        lambda r: httpx.Response(200, content=b"<html>nope</html>", headers={"content-type": "text/html"})
    )
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    out = tool(method="crm.deal.list")
    assert out["error"] is True
    assert out["reason"] == "non_json_response"


def test_bitrix_call_classifies_timeout(install_mock_transport, fake_secrets):
    fake_secrets[DEFAULT_SECRET_NAME] = WEBHOOK

    def handler(request):
        raise httpx.ConnectTimeout("simulated")

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    out = tool(method="crm.deal.list", timeout=1)
    assert out["error"] is True
    assert out["reason"] == "timeout"


# ---------------------------------------------------------------------------
# audit + category gating
# ---------------------------------------------------------------------------


def test_bitrix_call_audit_does_not_leak_url(install_mock_transport, fake_secrets):
    fake_secrets[DEFAULT_SECRET_NAME] = WEBHOOK

    def handler(request):
        return httpx.Response(200, json={"result": "ok"})

    install_mock_transport(handler)
    srv, events = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    tool(method="crm.deal.list")
    success = [e for e in events if e.get("result") == "success"]
    assert success
    extra = success[-1]["extra"]
    # method + secret_name are auditable; webhook_url is a credential.
    assert extra["method"] == "crm.deal.list"
    assert extra["secret_name"] == DEFAULT_SECRET_NAME
    assert "webhook_url" not in extra


def test_bitrix_category_disabled_refuses(install_mock_transport, fake_secrets):
    fake_secrets[DEFAULT_SECRET_NAME] = WEBHOOK
    install_mock_transport(lambda r: httpx.Response(200))
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(enabled_categories=["database"]),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_bitrix_tools(srv)
    tool = srv.fastmcp._tool_manager._tools["dialekt_bitrix_call"].fn
    with pytest.raises(ToolAccessDenied):
        tool(method="crm.deal.list")
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
