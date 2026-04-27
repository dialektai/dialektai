"""Web search adapter tests.

Two tiers:

1. **Unit tests with mocked httpx** — fast, hermetic, run in the default
   suite. Cover request shape (URL / headers / body), result mapping
   (Tavily ``content`` → snippet, etc.), error handling (401 / 429 /
   network failure), and the router's resolution order.

2. **E2E tests against a real Tavily API** — gated by the
   ``TAVILY_API_KEY`` env var. Skipped automatically when no key is
   present, so CI stays green without one. Run them locally with
   ``TAVILY_API_KEY=tvly-... pytest python/tests/test_web_search.py -v``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dialekt.tools.search.brave_client import BraveClient
from dialekt.tools.search.duckduckgo import (
    DuckDuckGoClient,
    _strip_tags,
    _unwrap_redirect,
)
from dialekt.tools.search.provider import (
    SearchProviderError,
    SearchResult,
)
from dialekt.tools.search.router import (
    PROVIDER_NAMES,
    PROVIDER_PRIORITY,
    SECRET_KEY_BY_PROVIDER,
    _build_provider,
    configured_providers,
    get_provider,
    search,
)
from dialekt.tools.search.tavily_client import TavilyClient


# ── Provider base ─────────────────────────────────────────────────────────────

def test_search_result_to_dict_round_trip():
    r = SearchResult(url="https://x", title="T", snippet="S", score=0.9,
                     extras={"published_date": "2026-01-01"})
    d = r.to_dict()
    assert d["url"] == "https://x"
    assert d["score"] == 0.9
    assert d["extras"]["published_date"] == "2026-01-01"


# ── Tavily ────────────────────────────────────────────────────────────────────

def _mock_response(*, status_code=200, json_data=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or ""
    return resp


def _patch_client_post(response):
    """Patch httpx.Client so .post() returns ``response``.

    Yields the mock so tests can inspect call arguments.
    """
    client_mock = MagicMock()
    client_mock.post.return_value = response
    client_mock.__enter__.return_value = client_mock
    client_mock.__exit__.return_value = False
    return client_mock


def _patch_client_get(response):
    client_mock = MagicMock()
    client_mock.get.return_value = response
    client_mock.__enter__.return_value = client_mock
    client_mock.__exit__.return_value = False
    return client_mock


def test_tavily_unconfigured_without_key():
    c = TavilyClient(api_key=None)
    assert not c.is_configured()
    with pytest.raises(SearchProviderError):
        c.search("anything")


def test_tavily_search_request_shape_and_mapping():
    payload = {
        "results": [
            {"url": "https://a", "title": "A", "content": "snippet A", "score": 0.91,
             "published_date": "2026-04-01"},
            {"url": "https://b", "title": "B", "content": "snippet B", "score": 0.7},
        ],
    }
    client_mock = _patch_client_post(_mock_response(status_code=200, json_data=payload))
    c = TavilyClient(api_key="tvly-test")

    with patch("httpx.Client", return_value=client_mock):
        results = c.search("hello world", max_results=5, include_raw_content=True)

    # Request shape: POST to the documented URL, body carries the API key
    # in-band (Tavily reads it from JSON, not a header).
    args, kwargs = client_mock.post.call_args
    assert args[0] == "https://api.tavily.com/search"
    body = kwargs["json"]
    assert body["api_key"] == "tvly-test"
    assert body["query"] == "hello world"
    assert body["max_results"] == 5
    assert body["include_raw_content"] is True

    # Mapping: content → snippet, score preserved, extras carry published_date.
    assert len(results) == 2
    assert results[0].snippet == "snippet A"
    assert results[0].score == 0.91
    assert results[0].extras == {"published_date": "2026-04-01"}
    assert results[1].extras == {}


@pytest.mark.parametrize("status,expected_substring", [
    (401, "invalid API key"),
    (429, "rate-limited"),
    (500, "HTTP 500"),
])
def test_tavily_status_errors_become_provider_errors(status, expected_substring):
    client_mock = _patch_client_post(
        _mock_response(status_code=status, text="server says no")
    )
    c = TavilyClient(api_key="tvly-test")
    with patch("httpx.Client", return_value=client_mock):
        with pytest.raises(SearchProviderError) as ei:
            c.search("hello")
    assert expected_substring in str(ei.value)


def test_tavily_network_error_wraps_request_error():
    client_mock = MagicMock()
    client_mock.__enter__.return_value = client_mock
    client_mock.__exit__.return_value = False
    client_mock.post.side_effect = httpx.ConnectError("dns lookup failed")

    c = TavilyClient(api_key="tvly-test")
    with patch("httpx.Client", return_value=client_mock):
        with pytest.raises(SearchProviderError) as ei:
            c.search("hello")
    assert "network error" in str(ei.value)


def test_tavily_empty_query_rejected():
    c = TavilyClient(api_key="tvly-test")
    with pytest.raises(SearchProviderError, match="query is empty"):
        c.search("   ")


# ── Brave ─────────────────────────────────────────────────────────────────────

def test_brave_unconfigured_without_key():
    c = BraveClient(api_key=None)
    assert not c.is_configured()


def test_brave_search_request_shape_and_score_synthesis():
    payload = {
        "web": {
            "results": [
                {"url": "https://a", "title": "A", "description": "desc A", "age": "2 days"},
                {"url": "https://b", "title": "B", "description": "desc B"},
                {"url": "https://c", "title": "C", "description": "desc C"},
            ],
        },
    }
    client_mock = _patch_client_get(_mock_response(status_code=200, json_data=payload))
    c = BraveClient(api_key="BSA-test")

    with patch("httpx.Client", return_value=client_mock):
        results = c.search("brave probe", max_results=10)

    args, kwargs = client_mock.get.call_args
    assert args[0] == "https://api.search.brave.com/res/v1/web/search"
    headers = kwargs["headers"]
    assert headers["X-Subscription-Token"] == "BSA-test"
    params = kwargs["params"]
    assert params["q"] == "brave probe"
    assert params["count"] == 10

    # Brave returns no score, so we synthesize one — first result strongest.
    assert len(results) == 3
    assert results[0].score > results[1].score > results[2].score
    assert results[0].snippet == "desc A"
    assert results[0].extras == {"age": "2 days"}


def test_brave_count_clamped_to_20():
    """Brave caps `count` at 20 — the adapter must clamp upstream params."""
    client_mock = _patch_client_get(_mock_response(status_code=200, json_data={"web": {"results": []}}))
    c = BraveClient(api_key="BSA-test")
    with patch("httpx.Client", return_value=client_mock):
        c.search("probe", max_results=100)
    _, kwargs = client_mock.get.call_args
    assert kwargs["params"]["count"] == 20


# ── DuckDuckGo ────────────────────────────────────────────────────────────────

def test_ddg_strip_tags_unescapes_entities():
    assert _strip_tags("<b>Hello</b> &amp; <i>world</i>") == "Hello & world"


def test_ddg_unwrap_redirect_extracts_target():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Ffoo&rut=abc"
    assert _unwrap_redirect(href) == "https://example.com/foo"


def test_ddg_unwrap_redirect_passthrough_for_direct_url():
    href = "https://example.com/bar"
    assert _unwrap_redirect(href) == "https://example.com/bar"


def test_ddg_is_always_configured():
    assert DuckDuckGoClient().is_configured() is True


def test_ddg_parses_html_lite_results():
    html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.example%2F">First Result</a>
        <a class="result__snippet" href="x">Snippet for first.</a>
      </div>
      <div class="result">
        <a class="result__a" href="https://b.example/">Second &amp; ampersand</a>
        <a class="result__snippet" href="x">Second snippet.</a>
      </div>
    </body></html>
    """
    client_mock = _patch_client_post(_mock_response(status_code=200, text=html))
    client_mock.__enter__.return_value = client_mock
    c = DuckDuckGoClient()
    with patch("httpx.Client", return_value=client_mock):
        results = c.search("test", max_results=5)

    assert len(results) == 2
    assert results[0].url == "https://a.example/"
    assert results[0].title == "First Result"
    assert "first" in results[0].snippet.lower()
    assert results[1].title == "Second & ampersand"


def test_ddg_no_results_raises_so_router_can_fall_back():
    """An interstitial / empty page should error, not silently return []."""
    client_mock = _patch_client_post(_mock_response(status_code=200, text="<html><body>No results.</body></html>"))
    c = DuckDuckGoClient()
    with patch("httpx.Client", return_value=client_mock):
        with pytest.raises(SearchProviderError):
            c.search("anything")


# ── Router ────────────────────────────────────────────────────────────────────

def test_secret_key_table_covers_every_named_provider():
    for name in PROVIDER_NAMES:
        assert name in SECRET_KEY_BY_PROVIDER


def test_router_explicit_unconfigured_provider_raises():
    with patch("dialekt.tools.search.router.get_secret", return_value=None):
        with pytest.raises(SearchProviderError, match="not configured"):
            get_provider("tavily")


def test_router_default_picks_first_configured_in_priority():
    # Only Tavily has a key — router should hand it back even though
    # PROVIDER_PRIORITY also lists Brave.
    def _key(name):
        return "tvly-real" if name == "tavily_api_key" else None

    with patch("dialekt.tools.search.router.get_secret", side_effect=_key):
        p = get_provider()
    assert p.name == "tavily"


def test_router_falls_through_to_duckduckgo_when_no_keys():
    with patch("dialekt.tools.search.router.get_secret", return_value=None):
        p = get_provider()
    assert p.name == "duckduckgo"


def test_router_search_returns_dict_shape():
    fake = TavilyClient(api_key="tvly-fake")
    fake_results = [SearchResult(url="https://x", title="T", snippet="S", score=0.5)]

    with (
        patch("dialekt.tools.search.router.get_secret", return_value="tvly-fake"),
        patch.object(TavilyClient, "search", return_value=fake_results),
    ):
        out = search("kz tax 2026", max_results=5)
    assert out["provider"] == "tavily"
    assert out["query"] == "kz tax 2026"
    assert out["results"] == [
        {"url": "https://x", "title": "T", "snippet": "S",
         "score": 0.5, "extras": {}},
    ]


def test_configured_providers_reports_only_keyed_or_keyless_ones():
    with patch("dialekt.tools.search.router.get_secret", return_value=None):
        names = configured_providers()
    # No keys → Tavily and Brave drop out, DuckDuckGo stays.
    assert names == ["duckduckgo"]


# ── Schema patch ──────────────────────────────────────────────────────────────

def test_runtime_capability_patch_widens_validator_schema():
    """The web_search agent manifest is the production proof; this is the
    micro-version that confirms the patch is wired before any agent runs."""
    import dialekt  # noqa: F401 — triggers patch via dialekt/__init__.py
    from dialekt_manifest.schema import CAPABILITY_GROUPS

    assert "web_search" in CAPABILITY_GROUPS


# ── E2E: real Tavily API ──────────────────────────────────────────────────────

# Skipped unless TAVILY_API_KEY is set in the environment. We deliberately
# *don't* read from the keychain here — using an env var keeps the prod
# secret out of the test path, and gives a clear opt-in signal in CI.
_TAVILY_KEY = os.environ.get("TAVILY_API_KEY")


@pytest.mark.skipif(
    not _TAVILY_KEY,
    reason="set TAVILY_API_KEY to run E2E tests against the live Tavily API",
)
def test_e2e_tavily_returns_real_results():
    c = TavilyClient(api_key=_TAVILY_KEY)
    results = c.search(
        "International Business Academy Almaty",
        max_results=3,
        search_depth="basic",
    )
    assert len(results) > 0
    for r in results:
        assert r.url.startswith("http")
        assert r.title
        # Tavily provides snippets but they can be empty for some results;
        # don't assert non-empty here. Score should at least be in [0, 1].
        assert 0.0 <= r.score <= 1.0


@pytest.mark.skipif(
    not _TAVILY_KEY,
    reason="set TAVILY_API_KEY to run E2E tests against the live Tavily API",
)
def test_e2e_tavily_test_connection_returns_ok():
    c = TavilyClient(api_key=_TAVILY_KEY)
    res = c.test_connection()
    assert res["ok"] is True
    assert "result_count" in res
