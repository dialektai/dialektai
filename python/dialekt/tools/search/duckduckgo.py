"""DuckDuckGo HTML-Lite adapter — last-resort fallback that needs no API key.

DuckDuckGo doesn't publish a general web-search API; the closest official
surface is the Instant Answer API (``api.duckduckgo.com``), which only
returns curated zero-click answers, not actual search results. So we
scrape the HTML-Lite page (``html.duckduckgo.com/html/``) the way every
no-key DDG client does. It's brittle by definition — DDG can change the
markup any week — but it's a useful safety net when neither Tavily nor
Brave is configured.

This provider is intentionally **not** the default. The router only
falls through to it when no API-key provider is configured AND the
caller hasn't explicitly disabled the fallback.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from .provider import SearchProvider, SearchProviderError, SearchResult


_DDG_HTML = "https://html.duckduckgo.com/html/"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# DDG html-lite wraps each result in a <div class="result"> ... </div>. We
# slice the page into per-result blocks first, then pull title/url/snippet
# out of each block — a single sweeping regex with a lazy `.*?` and an
# optional snippet group misses snippets unpredictably.
_RESULT_BLOCK_RE = re.compile(r'<div[^>]*class="[^"]*\bresult\b[^"]*"[^>]*>', re.IGNORECASE)
_RESULT_LINK_RE = re.compile(
    r'<a[^>]*class="[^"]*\bresult__a\b[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_RESULT_SNIPPET_RE = re.compile(
    r'<a[^>]*class="[^"]*\bresult__snippet\b[^"]*"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return unescape(_TAG_RE.sub("", s)).strip()


def _unwrap_redirect(href: str) -> str:
    """DDG hides target URLs behind /l/?uddg=<encoded>. Unwrap when present."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path == "/l/":
        qs = parse_qs(parsed.query)
        target = qs.get("uddg", [None])[0]
        if target:
            return target
    return href


class DuckDuckGoClient(SearchProvider):
    name = "duckduckgo"

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        base_url: str = _DDG_HTML,
        user_agent: str = _UA,
    ) -> None:
        self._timeout = timeout
        self._base_url = base_url
        self._ua = user_agent

    def is_configured(self) -> bool:
        # No API key needed.
        return True

    def search(
        self,
        query: str,
        max_results: int = 10,
        **options: Any,
    ) -> list[SearchResult]:
        if not query.strip():
            raise SearchProviderError("duckduckgo: query is empty")

        params = {"q": query, "kl": options.get("region", "wt-wt")}
        headers = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml",
        }

        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.post(self._base_url, data=params, headers=headers)
        except httpx.RequestError as e:
            raise SearchProviderError(f"duckduckgo: network error — {e}") from e

        if resp.status_code >= 400:
            raise SearchProviderError(
                f"duckduckgo: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        # Slice the page into per-result blocks. ``re.split`` with the
        # block-opening tag as separator drops the tag itself but keeps
        # the content of each result in its own slot.
        blocks = _RESULT_BLOCK_RE.split(resp.text)[1:]  # discard pre-first-result preamble
        out: list[SearchResult] = []
        total = len(blocks) or 1
        for rank, block in enumerate(blocks):
            if rank >= max_results:
                break
            link_match = _RESULT_LINK_RE.search(block)
            if not link_match:
                continue
            href, title_html = link_match.group(1), link_match.group(2)
            snippet_match = _RESULT_SNIPPET_RE.search(block)
            snippet_html = snippet_match.group(1) if snippet_match else ""
            out.append(
                SearchResult(
                    url=_unwrap_redirect(unescape(href)),
                    title=_strip_tags(title_html),
                    snippet=_strip_tags(snippet_html),
                    score=round(1.0 - (rank / total), 4),
                )
            )

        if not out:
            # DDG occasionally returns an interstitial / anti-bot page
            # instead of results. Bubble that up as a clear error so the
            # router can fall back rather than returning [] silently.
            raise SearchProviderError(
                "duckduckgo: no results found (possible rate-limit / interstitial)"
            )
        return out
