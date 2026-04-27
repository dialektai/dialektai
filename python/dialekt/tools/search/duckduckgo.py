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

# DDG html-lite wraps each result in a single <div class="result"> ... </div>.
# Title + url live inside <a class="result__a" href="..."> (where href is a
# /l/?uddg= redirect URL — we unwrap it). Snippet sits in <a class="result__snippet">.
_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
    r'.*?(?:<a[^>]*class="result__snippet"[^>]*>(.*?)</a>)?',
    re.DOTALL,
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

        out: list[SearchResult] = []
        matches = _RESULT_RE.findall(resp.text)
        if not matches:
            # DDG occasionally returns an interstitial / anti-bot page
            # instead of results. Bubble that up as a clear error so the
            # router can fall back rather than returning [] silently.
            raise SearchProviderError(
                "duckduckgo: no results found (possible rate-limit / interstitial)"
            )
        total = len(matches) or 1
        for rank, (href, title_html, snippet_html) in enumerate(matches):
            if rank >= max_results:
                break
            url = _unwrap_redirect(unescape(href))
            out.append(
                SearchResult(
                    url=url,
                    title=_strip_tags(title_html),
                    snippet=_strip_tags(snippet_html or ""),
                    score=round(1.0 - (rank / total), 4),
                )
            )
        return out
