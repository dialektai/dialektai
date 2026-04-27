"""Brave Search adapter.

Brave is the optional secondary provider — Brave indexes the web with their
own crawl, so it's a useful diversity hedge when Tavily is rate-limited or
the question hits a topic Tavily's index handles poorly.

Endpoint: ``GET https://api.search.brave.com/res/v1/web/search``
Header: ``X-Subscription-Token: <api_key>``
"""

from __future__ import annotations

from typing import Any

import httpx

from .provider import SearchProvider, SearchProviderError, SearchResult


_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveClient(SearchProvider):
    name = "brave"

    def __init__(
        self,
        api_key: str | None,
        *,
        timeout: float = 15.0,
        base_url: str = _BRAVE_URL,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._timeout = timeout
        self._base_url = base_url

    def is_configured(self) -> bool:
        return self._api_key is not None

    def search(
        self,
        query: str,
        max_results: int = 10,
        **options: Any,
    ) -> list[SearchResult]:
        if not self._api_key:
            raise SearchProviderError(
                "brave: no API key configured (set brave_search_api_key in Settings)"
            )
        if not query.strip():
            raise SearchProviderError("brave: query is empty")

        # Brave's /web/search caps `count` at 20 per call.
        params = {
            "q": query,
            "count": min(int(max_results), 20),
        }
        if "country" in options:
            params["country"] = options["country"]
        if "search_lang" in options:
            params["search_lang"] = options["search_lang"]
        if "safesearch" in options:
            params["safesearch"] = options["safesearch"]

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(self._base_url, params=params, headers=headers)
        except httpx.RequestError as e:
            raise SearchProviderError(f"brave: network error — {e}") from e

        if resp.status_code == 401:
            raise SearchProviderError("brave: invalid subscription token (HTTP 401)")
        if resp.status_code == 429:
            raise SearchProviderError("brave: rate-limited (HTTP 429)")
        if resp.status_code >= 400:
            raise SearchProviderError(
                f"brave: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError as e:
            raise SearchProviderError(f"brave: invalid JSON response — {e}") from e

        web_results = (data.get("web") or {}).get("results") or []
        out: list[SearchResult] = []
        # Brave doesn't return a relevance score, so we synthesize a
        # monotonically decreasing one from result rank — preserves the
        # "first result is best" ordering when callers sort by score.
        total = len(web_results) or 1
        for rank, item in enumerate(web_results):
            out.append(
                SearchResult(
                    url=str(item.get("url", "")),
                    title=str(item.get("title", "")),
                    snippet=str(item.get("description", "")),
                    score=round(1.0 - (rank / total), 4),
                    extras={
                        k: item[k]
                        for k in ("age", "language", "page_age")
                        if k in item and item[k] is not None
                    },
                )
            )
        return out
