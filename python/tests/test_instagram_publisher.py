"""Tests for ``dialekt.tools.social`` — Instagram Graph API publisher
and OAuth helpers.

Strategy: every test injects an ``httpx.MockTransport`` so no live
network calls happen. The transport handler asserts the request shape
(URL, method, body) and returns canned Graph responses, which is the
precise contract these modules guard.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from dialekt.tools.social import oauth_flow
from dialekt.tools.social.instagram_publisher import (
    InstagramPublisher,
    PublishError,
)
from dialekt.tools.social.oauth_flow import (
    GRAPH_HOST,
    GRAPH_VERSION,
    OAuthError,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _client(handler):
    """Build an ``httpx.AsyncClient`` driven by the given mock handler."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)


def _run(coro):
    return asyncio.run(coro)


# ── oauth_flow.build_auth_url ────────────────────────────────────────────────

def test_build_auth_url_carries_all_required_params():
    url = oauth_flow.build_auth_url(
        "12345", "http://localhost:8765/cb", state="abc",
    )
    parsed = urlparse(url)
    assert parsed.netloc == "www.facebook.com"
    assert parsed.path.endswith("/dialog/oauth")
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["12345"]
    assert qs["redirect_uri"] == ["http://localhost:8765/cb"]
    assert qs["state"] == ["abc"]
    assert qs["response_type"] == ["code"]
    scopes = qs["scope"][0].split(",")
    assert "instagram_basic" in scopes
    assert "instagram_content_publish" in scopes


def test_build_auth_url_accepts_custom_scopes():
    url = oauth_flow.build_auth_url(
        "1", "http://x", state="s", scopes=("instagram_basic",),
    )
    qs = parse_qs(urlparse(url).query)
    assert qs["scope"] == ["instagram_basic"]


# ── oauth_flow.exchange_code_for_token ───────────────────────────────────────

def test_exchange_code_for_token_calls_right_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        return httpx.Response(
            200, json={"access_token": "short-1", "expires_in": 3600},
        )

    async def run():
        async with _client(handler) as cli:
            body = await oauth_flow.exchange_code_for_token(
                "app-id", "app-sec", "code-xyz",
                "http://localhost:8765/cb", client=cli,
            )
            assert body["access_token"] == "short-1"

    _run(run())
    assert seen["method"] == "GET"
    assert f"{GRAPH_HOST}/{GRAPH_VERSION}/oauth/access_token" in seen["url"]
    qs = parse_qs(urlparse(seen["url"]).query)
    assert qs["client_id"] == ["app-id"]
    assert qs["client_secret"] == ["app-sec"]
    assert qs["code"] == ["code-xyz"]
    assert qs["redirect_uri"] == ["http://localhost:8765/cb"]


def test_exchange_for_long_lived_uses_fb_exchange_grant():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["qs"] = parse_qs(urlparse(str(request.url)).query)
        return httpx.Response(
            200,
            json={"access_token": "long-1", "expires_in": 5184000},
        )

    async def run():
        async with _client(handler) as cli:
            body = await oauth_flow.exchange_for_long_lived(
                "a", "s", "short-1", client=cli,
            )
            assert body["access_token"] == "long-1"

    _run(run())
    assert seen["qs"]["grant_type"] == ["fb_exchange_token"]
    assert seen["qs"]["fb_exchange_token"] == ["short-1"]


def test_refresh_long_lived_hits_same_endpoint_as_exchange():
    """``refresh_long_lived`` is intentionally a thin wrapper — the
    rename is documentation, not a different request shape."""
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(
            200,
            json={"access_token": "refreshed", "expires_in": 5184000},
        )

    async def run():
        async with _client(handler) as cli:
            body = await oauth_flow.refresh_long_lived("a", "s", "long-1", client=cli)
            assert body["access_token"] == "refreshed"

    _run(run())
    assert len(captured_urls) == 1
    assert "fb_exchange_token=long-1" in captured_urls[0]


def test_token_endpoint_error_raises_oauth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "Invalid OAuth code", "code": 100,
                            "error_subcode": 33}},
        )

    async def run():
        async with _client(handler) as cli:
            with pytest.raises(OAuthError) as ei:
                await oauth_flow.exchange_code_for_token(
                    "a", "s", "bad", "http://x", client=cli,
                )
            msg = str(ei.value)
            assert "Invalid OAuth code" in msg
            assert "code=100" in msg

    _run(run())


def test_token_endpoint_2xx_without_access_token_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    async def run():
        async with _client(handler) as cli:
            with pytest.raises(OAuthError):
                await oauth_flow.exchange_code_for_token(
                    "a", "s", "c", "http://x", client=cli,
                )

    _run(run())


# ── oauth_flow.get_ig_business_account ───────────────────────────────────────

def test_get_ig_business_account_walks_page_to_ig_user():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/me/accounts") or "/me/accounts?" in url:
            return httpx.Response(200, json={"data": [
                {"id": "page-1", "name": "My Page",
                 "instagram_business_account": {"id": "ig-42"}},
            ]})
        if "/ig-42" in url:
            return httpx.Response(200, json={"id": "ig-42", "username": "dias"})
        return httpx.Response(404, json={"error": {"message": "no"}})

    async def run():
        async with _client(handler) as cli:
            info = await oauth_flow.get_ig_business_account("tok", client=cli)
            assert info == {
                "page_id": "page-1", "page_name": "My Page",
                "ig_user_id": "ig-42", "username": "dias",
            }

    _run(run())


def test_get_ig_business_account_skips_pages_without_ig():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/me/accounts" in url:
            return httpx.Response(200, json={"data": [
                {"id": "page-personal", "name": "No IG"},
                {"id": "page-2", "name": "Has IG",
                 "instagram_business_account": {"id": "ig-7"}},
            ]})
        return httpx.Response(200, json={"id": "ig-7", "username": "biz"})

    async def run():
        async with _client(handler) as cli:
            info = await oauth_flow.get_ig_business_account("tok", client=cli)
            assert info["ig_user_id"] == "ig-7"
            assert info["username"] == "biz"

    _run(run())


def test_get_ig_business_account_no_eligible_page_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"id": "page-only", "name": "Personal"},
        ]})

    async def run():
        async with _client(handler) as cli:
            with pytest.raises(OAuthError) as ei:
                await oauth_flow.get_ig_business_account("tok", client=cli)
            assert "Instagram Business" in str(ei.value)

    _run(run())


# ── oauth_flow.needs_refresh + expires_at_from_payload ───────────────────────

def test_needs_refresh_true_within_window():
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    soon = (now + timedelta(days=3)).isoformat()
    assert oauth_flow.needs_refresh(soon, now=now) is True


def test_needs_refresh_false_far_out():
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    far = (now + timedelta(days=30)).isoformat()
    assert oauth_flow.needs_refresh(far, now=now) is False


@pytest.mark.parametrize("bad", [None, "", "not-a-date", "2026-99-99T00:00:00Z"])
def test_needs_refresh_returns_true_on_invalid_input(bad):
    assert oauth_flow.needs_refresh(bad) is True


def test_expires_at_from_payload_uses_expires_in_seconds():
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    iso = oauth_flow.expires_at_from_payload({"expires_in": 5184000}, now=now)
    parsed = datetime.fromisoformat(iso)
    assert (parsed - now) == timedelta(seconds=5184000)


def test_expires_at_from_payload_falls_back_to_60_days_when_missing():
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    iso = oauth_flow.expires_at_from_payload({}, now=now)
    parsed = datetime.fromisoformat(iso)
    assert (parsed - now) == timedelta(days=oauth_flow.LONG_LIVED_TTL_DAYS)


# ── InstagramPublisher.publish_feed_post ─────────────────────────────────────

def test_publish_feed_post_creates_then_publishes():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append((request.method, url))
        if url.endswith("/ig-1/media"):
            assert request.method == "POST"
            body = parse_qs(request.content.decode())
            assert body["image_url"] == ["https://cdn/x.jpg"]
            assert body["caption"] == ["hello"]
            assert body["access_token"] == ["tok"]
            return httpx.Response(200, json={"id": "container-1"})
        if url.endswith("/ig-1/media_publish"):
            body = parse_qs(request.content.decode())
            assert body["creation_id"] == ["container-1"]
            return httpx.Response(200, json={"id": "media-77"})
        return httpx.Response(404, json={"error": {"message": "wat"}})

    async def run():
        async with _client(handler) as cli:
            async with InstagramPublisher("ig-1", "tok", client=cli) as pub:
                mid = await pub.publish_feed_post(
                    "https://cdn/x.jpg", "hello",
                )
                assert mid == "media-77"

    _run(run())
    methods = [m for m, _ in seen]
    assert methods == ["POST", "POST"]


def test_publish_feed_post_propagates_graph_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "image_url not reachable",
                                  "code": 9004}},
        )

    async def run():
        async with _client(handler) as cli:
            async with InstagramPublisher("ig-1", "tok", client=cli) as pub:
                with pytest.raises(OAuthError) as ei:
                    await pub.publish_feed_post("https://cdn/x.jpg", "")
                assert "image_url not reachable" in str(ei.value)

    _run(run())


# ── InstagramPublisher.publish_story (polls status) ──────────────────────────

def test_publish_story_polls_until_finished():
    state = {"status_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/ig-1/media"):
            body = parse_qs(request.content.decode())
            assert body["media_type"] == ["STORIES"]
            return httpx.Response(200, json={"id": "story-1"})
        if "/story-1" in url and request.method == "GET":
            state["status_calls"] += 1
            status = "FINISHED" if state["status_calls"] >= 2 else "IN_PROGRESS"
            return httpx.Response(200, json={"status_code": status})
        if url.endswith("/ig-1/media_publish"):
            return httpx.Response(200, json={"id": "media-st"})
        return httpx.Response(404)

    async def run():
        async with _client(handler) as cli:
            # Patch sleep to a no-op so the test runs in milliseconds.
            from dialekt.tools.social import instagram_publisher as ip
            orig = asyncio.sleep
            asyncio.sleep = lambda *_a, **_k: orig(0)  # type: ignore
            try:
                async with InstagramPublisher("ig-1", "tok", client=cli) as pub:
                    mid = await pub.publish_story("https://cdn/x.jpg")
                    assert mid == "media-st"
            finally:
                asyncio.sleep = orig  # type: ignore
                _ = ip  # silence unused-import linters

    _run(run())
    assert state["status_calls"] >= 2


def test_publish_reel_raises_on_container_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/ig-1/media"):
            return httpx.Response(200, json={"id": "reel-1"})
        if "/reel-1" in url and request.method == "GET":
            return httpx.Response(
                200,
                json={"status_code": "ERROR",
                      "status": "encoding failed: bitrate too high"},
            )
        return httpx.Response(404)

    async def run():
        from dialekt.tools.social import instagram_publisher as ip
        orig = asyncio.sleep
        asyncio.sleep = lambda *_a, **_k: orig(0)  # type: ignore
        try:
            async with _client(handler) as cli:
                async with InstagramPublisher("ig-1", "tok", client=cli) as pub:
                    with pytest.raises(PublishError) as ei:
                        await pub.publish_reel("https://cdn/v.mp4", "🎬")
                    assert "ERROR" in str(ei.value)
        finally:
            asyncio.sleep = orig  # type: ignore
            _ = ip

    _run(run())


# ── client lifecycle ─────────────────────────────────────────────────────────

def test_publisher_owns_client_when_none_supplied():
    """If no client is injected the publisher creates one and aclose closes it."""
    async def run():
        pub = InstagramPublisher("ig-1", "tok")
        assert pub._client is None
        cli = pub.client
        assert cli is pub._client
        await pub.aclose()
        assert pub._client is None

    _run(run())
