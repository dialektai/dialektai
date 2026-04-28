"""Tests for ``dialekt.mcp.server.tools.web_crawl``.

Strategy: monkeypatch ``_build_browser_context`` so no Chromium is
launched. The stub returns canned page handles that mirror just
enough of Playwright's API for the tool to produce results — fast,
deterministic, no network.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools import web_crawl as web_crawl_tool
from dialekt.mcp.server.tools.web_crawl import (
    MAX_TEXT_BYTES,
    MAX_TIMEOUT_MS,
    _clamp_link_limit,
    _clamp_timeout_ms,
    _validate_url,
    register_web_crawl_tools,
)


class _StubElement:
    def __init__(self, text="", attrs=None):
        self._text = text
        self._attrs = attrs or {}

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        return self._attrs.get(name)


class _StubResponse:
    def __init__(self, status):
        self.status = status


class _StubPage:
    def __init__(self, *, url, status, title, body_text, anchors=None,
                 selectors=None, navigation_error=None):
        self._url = url
        self._status = status
        self._title = title
        self._body_text = body_text
        self._anchors = anchors or []
        self._selectors = selectors or {}
        self._navigation_error = navigation_error

    @property
    def url(self):
        return self._url

    def goto(self, url, timeout=None, wait_until=None):
        if self._navigation_error:
            raise self._navigation_error
        self._url = url
        return _StubResponse(self._status)

    def wait_for_load_state(self, state, timeout=None):
        return None

    def title(self):
        return self._title

    def query_selector(self, css):
        if css == "body" or css is None:
            return _StubElement(text=self._body_text)
        if css in self._selectors:
            return _StubElement(text=self._selectors[css])
        return None

    def query_selector_all(self, css):
        if css == "a[href]":
            return [
                _StubElement(text=a["text"], attrs={"href": a["href"]})
                for a in self._anchors
            ]
        return []


class _StubContext:
    def __init__(self, page):
        self._page = page

    def new_page(self):
        return self._page

    def set_default_timeout(self, ms):
        return None

    def close(self):
        return None


class _StubBrowser:
    def __init__(self, context):
        self._context = context

    def new_context(self, user_agent=None):
        return self._context

    def close(self):
        return None


class _StubPlaywright:
    def stop(self):
        return None


@pytest.fixture
def install_stub_browser(monkeypatch):
    """Returns a function that installs a fake browser context whose
    page object is built from caller-supplied parameters."""

    def _install(*, url="https://example.com/page", status=200,
                 title="Example", body_text="hello body",
                 anchors=None, selectors=None,
                 navigation_error=None,
                 launch_error=None):
        page = _StubPage(
            url=url, status=status, title=title, body_text=body_text,
            anchors=anchors, selectors=selectors,
            navigation_error=navigation_error,
        )
        context = _StubContext(page)
        browser = _StubBrowser(context)
        pw = _StubPlaywright()

        def _factory(timeout_ms):
            if launch_error:
                raise launch_error
            return pw, browser, context

        monkeypatch.setattr(web_crawl_tool, "_build_browser_context", _factory)
        return page

    return _install


def _build_server():
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_web_crawl_tools(srv)
    return srv, events


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_validate_url_accepts_https():
    assert _validate_url("https://iba.kz/training") is None


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "ftp://x",
    "javascript:alert(1)",
    "data:text/html,abc",
])
def test_validate_url_rejects_other_schemes(bad):
    out = _validate_url(bad)
    assert out is not None
    assert out["reason"] == "unsupported_scheme"


def test_validate_url_rejects_missing_host():
    out = _validate_url("https://")
    assert out["reason"] == "invalid_url"


def test_clamp_timeout_ms_default():
    assert _clamp_timeout_ms(None) == 30_000


def test_clamp_timeout_ms_caps_at_max():
    assert _clamp_timeout_ms(99999) == MAX_TIMEOUT_MS


def test_clamp_link_limit_default():
    assert _clamp_link_limit(None) == 200


def test_clamp_link_limit_hard_max():
    assert _clamp_link_limit(99999) == 2000


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------


def test_web_crawl_returns_title_text_links(install_stub_browser):
    install_stub_browser(
        url="https://iba.kz/programs/leadership",
        title="Leadership program — IBA",
        body_text="Description of leadership program with full details.",
        anchors=[
            {"href": "/about", "text": "About"},
            {"href": "https://iba.kz/contact", "text": "Contact"},
        ],
    )
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    out = tool(url="https://iba.kz/programs/leadership")
    assert out.get("error") is not True
    assert out["status"] == 200
    assert out["title"] == "Leadership program — IBA"
    assert "leadership program" in out["text"].lower()
    assert out["link_count"] == 2
    assert out["links"][0]["href"] == "/about"
    assert out["links"][1]["text"] == "Contact"
    assert out["truncated"] is False


def test_web_crawl_uses_text_selector(install_stub_browser):
    install_stub_browser(
        body_text="full body",
        selectors={"main.content": "main content text only"},
    )
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    out = tool(url="https://x.com", text_selector="main.content")
    assert out["text"] == "main content text only"


def test_web_crawl_pulls_named_selectors(install_stub_browser):
    install_stub_browser(
        body_text="body",
        selectors={"h1": "Hello", "p.lead": "Lead paragraph"},
    )
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    out = tool(
        url="https://x.com",
        selectors={"hero_title": "h1", "intro": "p.lead", "missing": ".nope"},
    )
    assert out["selectors"]["hero_title"] == "Hello"
    assert out["selectors"]["intro"] == "Lead paragraph"
    assert out["selectors"]["missing"] is None


def test_web_crawl_truncates_oversized_text(install_stub_browser):
    big = "x" * (MAX_TEXT_BYTES + 1024)
    install_stub_browser(body_text=big)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    out = tool(url="https://x.com")
    assert out["truncated"] is True
    assert len(out["text"].encode("utf-8")) <= MAX_TEXT_BYTES


def test_web_crawl_caps_link_count(install_stub_browser):
    anchors = [{"href": f"/p/{i}", "text": f"link {i}"} for i in range(50)]
    install_stub_browser(anchors=anchors)
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    out = tool(url="https://x.com", link_limit=10)
    assert out["link_count"] == 10


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_web_crawl_rejects_unsupported_scheme(install_stub_browser):
    install_stub_browser()
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    out = tool(url="file:///etc/passwd")
    assert out["error"] is True
    assert out["reason"] == "unsupported_scheme"


def test_web_crawl_browser_launch_failure(install_stub_browser):
    install_stub_browser(launch_error=RuntimeError("no chromium"))
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    out = tool(url="https://iba.kz")
    assert out["error"] is True
    assert out["reason"] == "browser_launch_failed"


def test_web_crawl_navigation_failure(install_stub_browser):
    install_stub_browser(navigation_error=RuntimeError("dns fail"))
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    out = tool(url="https://nonexistent.example.com")
    assert out["error"] is True
    assert out["reason"] == "navigation_failed"


# ---------------------------------------------------------------------------
# audit + category gating
# ---------------------------------------------------------------------------


def test_web_crawl_emits_audit(install_stub_browser):
    install_stub_browser(body_text="hi")
    srv, events = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    tool(url="https://iba.kz")
    success = [e for e in events if e.get("result") == "success"]
    assert success and success[-1]["action"] == "dialekt_web_crawl"
    assert success[-1]["extra"]["url"] == "https://iba.kz"


def test_web_crawl_category_disabled_refuses(install_stub_browser):
    install_stub_browser()
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(enabled_categories=["database"]),  # web_crawl excluded
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_web_crawl_tools(srv)
    tool = srv.fastmcp._tool_manager._tools["dialekt_web_crawl"].fn
    with pytest.raises(ToolAccessDenied):
        tool(url="https://iba.kz")
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
