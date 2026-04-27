"""Web search provider adapters — Tavily / Brave / DuckDuckGo behind a
common SearchProvider interface."""

from .brave_client import BraveClient
from .duckduckgo import DuckDuckGoClient
from .provider import SearchProvider, SearchProviderError, SearchResult
from .router import (
    PROVIDER_NAMES,
    PROVIDER_PRIORITY,
    SECRET_KEY_BY_PROVIDER,
    configured_providers,
    get_provider,
    search,
)
from .tavily_client import TavilyClient

__all__ = [
    "SearchProvider",
    "SearchResult",
    "SearchProviderError",
    "TavilyClient",
    "BraveClient",
    "DuckDuckGoClient",
    "PROVIDER_NAMES",
    "PROVIDER_PRIORITY",
    "SECRET_KEY_BY_PROVIDER",
    "configured_providers",
    "get_provider",
    "search",
]
