"""Tests for ``dialekt.mcp.server.tools.rss``.

Uses :class:`httpx.MockTransport` to substitute the network layer
with canned RSS / Atom payloads, so the test suite has no external
dependency on adilet.zan.kz or any other live feed.
"""
from __future__ import annotations

import httpx
import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools import rss as rss_tools
from dialekt.mcp.server.tools.rss import (
    DEFAULT_MAX_ITEMS,
    HARD_MAX_ITEMS,
    _clamp_max_items,
    _clamp_timeout,
    _validate_url,
    register_rss_tools,
)


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample feed</title>
    <link>https://example.com/feed</link>
    <description>Sample subtitle</description>
    <item>
      <title>First item</title>
      <link>https://example.com/items/1</link>
      <guid>https://example.com/items/1</guid>
      <description>Body of the first item</description>
      <pubDate>Mon, 28 Apr 2026 09:00:00 +0000</pubDate>
      <author>alice@example.com (Alice)</author>
    </item>
    <item>
      <title>Second item</title>
      <link>https://example.com/items/2</link>
      <guid>https://example.com/items/2</guid>
      <description>Body of the second item</description>
      <pubDate>Sun, 27 Apr 2026 10:30:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom feed</title>
  <link href="https://example.com/atom"/>
  <updated>2026-04-28T12:00:00Z</updated>
  <entry>
    <title>Entry one</title>
    <link href="https://example.com/atom/1"/>
    <id>tag:example.com,2026:1</id>
    <updated>2026-04-28T11:50:00Z</updated>
    <summary>Atom body</summary>
  </entry>
</feed>
"""


@pytest.fixture
def install_mock_transport(monkeypatch):
    def _install(handler):
        transport = httpx.MockTransport(handler)

        def _factory(timeout):
            return httpx.Client(
                transport=transport, timeout=timeout, follow_redirects=True
            )

        monkeypatch.setattr(rss_tools, "_build_client", _factory)
        return transport

    return _install


def _build_server():
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_rss_tools(srv)
    return srv, events


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_clamp_timeout_default():
    assert _clamp_timeout(None) == 30.0


def test_clamp_timeout_caps_at_max():
    assert _clamp_timeout(10000) == 120.0


def test_clamp_max_items_default():
    assert _clamp_max_items(None) == DEFAULT_MAX_ITEMS


def test_clamp_max_items_caps_at_hard_max():
    assert _clamp_max_items(99999) == HARD_MAX_ITEMS


def test_clamp_max_items_replaces_zero_with_default():
    assert _clamp_max_items(0) == DEFAULT_MAX_ITEMS


def test_validate_url_rejects_bad_schemes():
    out = _validate_url("file:///etc/passwd")
    assert out is not None
    assert out["reason"] == "unsupported_scheme"


# ---------------------------------------------------------------------------
# dialekt_rss_fetch — happy paths
# ---------------------------------------------------------------------------


def test_rss_fetch_parses_rss_2(install_mock_transport):
    def handler(request):
        return httpx.Response(
            200,
            content=SAMPLE_RSS.encode("utf-8"),
            headers={"content-type": "application/rss+xml"},
        )

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    out = tool(url="https://example.com/feed.xml")
    assert out.get("error") is not True
    assert out["feed_title"] == "Sample feed"
    assert out["item_count"] == 2
    first = out["items"][0]
    assert first["title"] == "First item"
    assert first["link"] == "https://example.com/items/1"
    assert first["guid"] == "https://example.com/items/1"
    assert first["published"].startswith("2026-04-28T09:00:00")
    assert first["published"].endswith("Z")


def test_rss_fetch_parses_atom(install_mock_transport):
    def handler(request):
        return httpx.Response(
            200,
            content=SAMPLE_ATOM.encode("utf-8"),
            headers={"content-type": "application/atom+xml"},
        )

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    out = tool(url="https://example.com/atom.xml")
    assert out["feed_title"] == "Atom feed"
    assert out["item_count"] == 1
    assert out["items"][0]["guid"] == "tag:example.com,2026:1"
    assert out["items"][0]["link"] == "https://example.com/atom/1"


def test_rss_fetch_caps_items(install_mock_transport):
    items_xml = "".join(
        f"<item><title>i{i}</title><link>https://e/{i}</link>"
        f"<guid>https://e/{i}</guid></item>"
        for i in range(20)
    )
    feed = (
        f'<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<title>Big</title><link>https://e</link>"
        f"{items_xml}"
        f"</channel></rss>"
    )

    def handler(request):
        return httpx.Response(200, content=feed.encode("utf-8"))

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    out = tool(url="https://e/feed", max_items=5)
    assert out["item_count"] == 5
    assert out["truncated"] is True


def test_rss_fetch_passes_user_agent_and_custom_headers(install_mock_transport):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request):
        seen.update(dict(request.headers))
        return httpx.Response(200, content=SAMPLE_RSS.encode("utf-8"))

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    tool(url="https://example.com/feed.xml", headers={"X-Tenant": "iba"})
    assert "dialekt-mcp" in seen.get("user-agent", "")
    assert seen.get("x-tenant") == "iba"


# ---------------------------------------------------------------------------
# dialekt_rss_fetch — error paths
# ---------------------------------------------------------------------------


def test_rss_fetch_rejects_unsupported_scheme(install_mock_transport):
    install_mock_transport(lambda r: httpx.Response(200))
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    out = tool(url="file:///etc/passwd")
    assert out["error"] is True
    assert out["reason"] == "unsupported_scheme"


def test_rss_fetch_classifies_404(install_mock_transport):
    install_mock_transport(lambda r: httpx.Response(404, text="not found"))
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    out = tool(url="https://example.com/missing")
    assert out["error"] is True
    assert out["reason"] == "http_error"
    assert out["status"] == 404


def test_rss_fetch_classifies_timeout(install_mock_transport):
    def handler(request):
        raise httpx.ReadTimeout("simulated")

    install_mock_transport(handler)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    out = tool(url="https://example.com/feed", timeout=1)
    assert out["error"] is True
    assert out["reason"] == "timeout"


def test_rss_fetch_marks_bozo_on_malformed(install_mock_transport):
    install_mock_transport(
        lambda r: httpx.Response(200, content=b"<not><valid></rss>")
    )
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    out = tool(url="https://example.com/bad")
    # Even on bozo we don't raise — feedparser still returns *something*.
    # The flag lets the agent decide whether to act.
    assert out.get("bozo") is True


# ---------------------------------------------------------------------------
# audit + category gating
# ---------------------------------------------------------------------------


def test_rss_fetch_emits_audit(install_mock_transport):
    install_mock_transport(
        lambda r: httpx.Response(200, content=SAMPLE_RSS.encode("utf-8"))
    )
    srv, events = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    tool(url="https://example.com/feed.xml")
    success = [e for e in events if e.get("result") == "success"]
    assert success and success[-1]["action"] == "dialekt_rss_fetch"
    assert success[-1]["extra"]["url"] == "https://example.com/feed.xml"


def test_rss_category_disabled_refuses(install_mock_transport):
    install_mock_transport(lambda r: httpx.Response(200))
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(enabled_categories=["database"]),  # rss excluded
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_rss_tools(srv)
    tool = srv.fastmcp._tool_manager._tools["dialekt_rss_fetch"].fn
    with pytest.raises(ToolAccessDenied):
        tool(url="https://example.com/feed")
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
