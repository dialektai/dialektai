"""Web search provider adapters — Tavily / Brave / DuckDuckGo behind a
common SearchProvider interface."""

from .provider import SearchProvider, SearchResult, SearchProviderError
from .tavily_client import TavilyClient

__all__ = [
    "SearchProvider",
    "SearchResult",
    "SearchProviderError",
    "TavilyClient",
]
