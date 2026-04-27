"""Provider router — picks the search adapter from config + secrets.

Resolution order:

1. If the caller passed an explicit ``provider=...`` and that provider is
   configured, use it. (Otherwise: error — caller asked for X, X isn't ready,
   silently swapping in something else would surprise them.)
2. Otherwise the configured default from settings.
3. Otherwise the first configured provider in PROVIDER_PRIORITY order.
4. Otherwise DuckDuckGo (no key needed).
5. Otherwise an error: "no search providers configured".

All providers fetch their secrets through ``dialekt.secrets.get_secret``,
so the keychain is the source of truth — settings.json only holds the
non-sensitive default-provider preference.
"""

from __future__ import annotations

from typing import Any

from dialekt.secrets import get_secret

from .brave_client import BraveClient
from .duckduckgo import DuckDuckGoClient
from .provider import SearchProvider, SearchProviderError, SearchResult
from .tavily_client import TavilyClient


PROVIDER_NAMES = ("tavily", "brave", "duckduckgo")
PROVIDER_PRIORITY = ("tavily", "brave", "duckduckgo")

# Secret-store key per provider. None = no key (DuckDuckGo).
SECRET_KEY_BY_PROVIDER = {
    "tavily": "tavily_api_key",
    "brave": "brave_search_api_key",
    "duckduckgo": None,
}


def _build_provider(name: str) -> SearchProvider:
    if name == "tavily":
        return TavilyClient(api_key=get_secret("tavily_api_key"))
    if name == "brave":
        return BraveClient(api_key=get_secret("brave_search_api_key"))
    if name == "duckduckgo":
        return DuckDuckGoClient()
    raise SearchProviderError(f"unknown provider: {name!r}")


def configured_providers() -> list[str]:
    """Return the names of providers that have everything they need to run.

    Mirrors what the Settings UI shows in the provider dropdown so the API
    response and the UI agree on what's wired up.
    """
    return [name for name in PROVIDER_NAMES if _build_provider(name).is_configured()]


def get_provider(name: str | None = None, *, default: str | None = None) -> SearchProvider:
    """Resolve a provider by name (with config-driven fallbacks).

    See module docstring for the resolution order.
    """
    if name:
        provider = _build_provider(name)
        if not provider.is_configured():
            raise SearchProviderError(
                f"{name}: provider is not configured (missing API key)"
            )
        return provider

    if default:
        provider = _build_provider(default)
        if provider.is_configured():
            return provider

    for candidate in PROVIDER_PRIORITY:
        provider = _build_provider(candidate)
        if provider.is_configured():
            return provider

    # Should never hit this: DuckDuckGo is_configured() == True. But the
    # check guards future refactors that might disable DDG by default.
    raise SearchProviderError("no search providers configured")


def search(
    query: str,
    max_results: int = 10,
    *,
    provider: str | None = None,
    default_provider: str | None = None,
    **options: Any,
) -> dict[str, Any]:
    """Top-level entry: resolve a provider, run the query, return a dict.

    Returns ``{provider, query, results: [SearchResult.to_dict, ...]}``.
    Errors propagate as :class:`SearchProviderError`.
    """
    p = get_provider(provider, default=default_provider)
    results = p.search(query, max_results=max_results, **options)
    return {
        "provider": p.name,
        "query": query,
        "results": [r.to_dict() for r in results],
    }


__all__ = [
    "PROVIDER_NAMES",
    "PROVIDER_PRIORITY",
    "SECRET_KEY_BY_PROVIDER",
    "configured_providers",
    "get_provider",
    "search",
]
