"""Tavily search adapter.

Tavily is the primary provider — designed for LLM agents, returns structured
results with relevance scores out of the box. API docs: https://tavily.com/.

Endpoint: ``POST https://api.tavily.com/search``
Body: ``{"api_key", "query", "max_results", "search_depth", "include_raw_content"}``
"""

from __future__ import annotations

from typing import Any

import httpx

from .provider import SearchProvider, SearchProviderError, SearchResult


_TAVILY_URL = "https://api.tavily.com/search"


class TavilyClient(SearchProvider):
    name = "tavily"

    def __init__(
        self,
        api_key: str | None,
        *,
        timeout: float = 15.0,
        base_url: str = _TAVILY_URL,
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
                "tavily: no API key configured (set tavily_api_key in Settings)"
            )
        if not query.strip():
            raise SearchProviderError("tavily: query is empty")

        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": int(max_results),
            "search_depth": options.get("search_depth", "basic"),
            "include_raw_content": bool(options.get("include_raw_content", False)),
            "include_answer": bool(options.get("include_answer", False)),
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(self._base_url, json=payload)
        except httpx.RequestError as e:
            raise SearchProviderError(f"tavily: network error — {e}") from e

        if resp.status_code == 401:
            raise SearchProviderError("tavily: invalid API key (HTTP 401)")
        if resp.status_code == 429:
            raise SearchProviderError("tavily: rate-limited (HTTP 429)")
        if resp.status_code >= 400:
            raise SearchProviderError(
                f"tavily: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError as e:
            raise SearchProviderError(f"tavily: invalid JSON response — {e}") from e

        return [
            SearchResult(
                url=str(item.get("url", "")),
                title=str(item.get("title", "")),
                # Tavily calls the snippet "content" — normalise to snippet
                # so callers don't have to care which provider answered.
                snippet=str(item.get("content", "")),
                score=float(item.get("score", 0.0) or 0.0),
                extras={
                    k: item[k]
                    for k in ("published_date", "raw_content")
                    if k in item and item[k] is not None
                },
            )
            for item in (data.get("results") or [])
        ]
