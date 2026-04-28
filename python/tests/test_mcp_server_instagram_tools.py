"""Tests for ``dialekt.mcp.server.tools.instagram``.

Strategy: monkeypatch the underlying :class:`InstagramPublisher` so
no live Graph API calls happen, and replace ``dialekt.secrets.
get_secret`` with a dict-backed fake. The tests assert credential
resolution, error classification, and audit row content.
"""
from __future__ import annotations

import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools import instagram as instagram_tools
from dialekt.mcp.server.tools.instagram import (
    DEFAULT_TOKEN_SECRET,
    DEFAULT_USER_ID_SECRET,
    register_instagram_tools,
)
from dialekt.tools.social import instagram_publisher


class StubPublisher:
    """Drop-in replacement for ``InstagramPublisher`` that records
    every call instead of hitting Facebook. Constructor mirrors the
    real one so the tool's ``async with`` code path works unchanged."""

    instances: list["StubPublisher"] = []

    def __init__(self, ig_user_id: str, access_token: str, *, client=None):
        self.ig_user_id = ig_user_id
        self.access_token = access_token
        self.calls: list[tuple[str, tuple, dict]] = []
        self._raise: Exception | None = None
        self._return = "MEDIA_42"
        StubPublisher.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def publish_feed_post(self, image_url, caption=""):
        self.calls.append(("feed", (image_url, caption), {}))
        if self._raise:
            raise self._raise
        return self._return

    async def publish_story(self, image_url):
        self.calls.append(("story", (image_url,), {}))
        if self._raise:
            raise self._raise
        return self._return

    async def publish_reel(self, video_url, caption=""):
        self.calls.append(("reel", (video_url, caption), {}))
        if self._raise:
            raise self._raise
        return self._return


@pytest.fixture
def stub_publisher(monkeypatch):
    StubPublisher.instances = []
    monkeypatch.setattr(
        instagram_tools.instagram_publisher, "InstagramPublisher", StubPublisher
    )
    return StubPublisher


@pytest.fixture
def fake_secrets(monkeypatch):
    store: dict[str, str] = {}

    def _get(name: str) -> str | None:
        return store.get(name)

    monkeypatch.setattr(instagram_tools.secrets_module, "get_secret", _get)
    return store


def _build_server():
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_instagram_tools(srv)
    return srv, events


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------


def test_publish_feed_uses_secrets(stub_publisher, fake_secrets):
    fake_secrets[DEFAULT_TOKEN_SECRET] = "token-abc"
    fake_secrets[DEFAULT_USER_ID_SECRET] = "1788"
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_feed"].fn
    out = tool(image_url="https://example.com/x.jpg", caption="Hello")
    assert out["media_id"] == "MEDIA_42"
    assert out["ig_user_id"] == "1788"
    assert len(stub_publisher.instances) == 1
    pub = stub_publisher.instances[0]
    assert pub.access_token == "token-abc"
    assert pub.ig_user_id == "1788"
    assert pub.calls == [("feed", ("https://example.com/x.jpg", "Hello"), {})]


def test_publish_feed_inline_creds_override_secret(stub_publisher, fake_secrets):
    fake_secrets[DEFAULT_TOKEN_SECRET] = "from-secret"
    fake_secrets[DEFAULT_USER_ID_SECRET] = "secret-user"
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_feed"].fn
    tool(
        image_url="https://example.com/x.jpg",
        access_token="inline-token",
        ig_user_id="inline-user",
    )
    pub = stub_publisher.instances[0]
    assert pub.access_token == "inline-token"
    assert pub.ig_user_id == "inline-user"


def test_publish_story(stub_publisher, fake_secrets):
    fake_secrets[DEFAULT_TOKEN_SECRET] = "t"
    fake_secrets[DEFAULT_USER_ID_SECRET] = "u"
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_story"].fn
    out = tool(image_url="https://example.com/story.jpg")
    assert out["media_id"] == "MEDIA_42"
    pub = stub_publisher.instances[0]
    assert pub.calls == [("story", ("https://example.com/story.jpg",), {})]


def test_publish_reel(stub_publisher, fake_secrets):
    fake_secrets[DEFAULT_TOKEN_SECRET] = "t"
    fake_secrets[DEFAULT_USER_ID_SECRET] = "u"
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_reel"].fn
    out = tool(video_url="https://example.com/v.mp4", caption="watch")
    assert out["media_id"] == "MEDIA_42"
    pub = stub_publisher.instances[0]
    assert pub.calls == [("reel", ("https://example.com/v.mp4", "watch"), {})]


def test_custom_secret_names(stub_publisher, fake_secrets):
    fake_secrets["iba_token"] = "T"
    fake_secrets["iba_user"] = "U"
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_feed"].fn
    out = tool(
        image_url="https://x.jpg",
        token_secret="iba_token",
        user_id_secret="iba_user",
    )
    assert out["media_id"] == "MEDIA_42"


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_missing_credentials(stub_publisher, fake_secrets):
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_feed"].fn
    out = tool(image_url="https://x.jpg")
    assert out["error"] is True
    assert out["reason"] == "missing_credentials"
    assert DEFAULT_TOKEN_SECRET in out["missing_secrets"]
    assert DEFAULT_USER_ID_SECRET in out["missing_secrets"]
    # Nothing should have been instantiated.
    assert stub_publisher.instances == []


def test_missing_only_token(stub_publisher, fake_secrets):
    fake_secrets[DEFAULT_USER_ID_SECRET] = "u"
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_feed"].fn
    out = tool(image_url="https://x.jpg")
    assert out["error"] is True
    assert out["missing_secrets"] == [DEFAULT_TOKEN_SECRET]


def test_graph_error_classified(stub_publisher, fake_secrets):
    fake_secrets[DEFAULT_TOKEN_SECRET] = "t"
    fake_secrets[DEFAULT_USER_ID_SECRET] = "u"
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_feed"].fn

    # Make the publisher raise on call.
    def factory(*a, **kw):
        p = StubPublisher(*a, **kw)
        p._raise = instagram_publisher.PublishError("Graph rejected media")
        return p

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(
            instagram_tools.instagram_publisher,
            "InstagramPublisher",
            factory,
        )
        out = tool(image_url="https://x.jpg")
    finally:
        monkey.undo()

    assert out["error"] is True
    assert out["reason"] == "graph_error"
    assert "Graph rejected media" in out["detail"]


# ---------------------------------------------------------------------------
# audit + category gating
# ---------------------------------------------------------------------------


def test_audit_records_kind_not_credentials(stub_publisher, fake_secrets):
    fake_secrets[DEFAULT_TOKEN_SECRET] = "secret-token"
    fake_secrets[DEFAULT_USER_ID_SECRET] = "secret-user"
    srv, events = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_feed"].fn
    tool(image_url="https://x.jpg")
    success = [e for e in events if e.get("result") == "success"]
    assert success
    extra = success[-1]["extra"]
    assert extra["kind"] == "feed"
    assert extra["token_secret"] == DEFAULT_TOKEN_SECRET
    # Tokens never appear in audit.
    serialised = repr(success[-1])
    assert "secret-token" not in serialised
    assert "secret-user" not in serialised


def test_instagram_category_disabled_refuses(stub_publisher, fake_secrets):
    fake_secrets[DEFAULT_TOKEN_SECRET] = "t"
    fake_secrets[DEFAULT_USER_ID_SECRET] = "u"
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(enabled_categories=["database"]),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_instagram_tools(srv)
    tool = srv.fastmcp._tool_manager._tools["dialekt_instagram_publish_feed"].fn
    with pytest.raises(ToolAccessDenied):
        tool(image_url="https://x.jpg")
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
