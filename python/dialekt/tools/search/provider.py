"""Abstract base for web search providers.

Each concrete adapter (Tavily, Brave, DuckDuckGo, …) implements ``search()``
returning a uniform list of :class:`SearchResult` objects so the FastAPI
endpoint and the agents that call it don't have to branch on provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


class SearchProviderError(RuntimeError):
    """Raised by a provider when the upstream API call fails.

    The string form is shown to the user (in Settings → Web Search → Test
    button), so messages should be readable, not stack-trace-y.
    """


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    score: float = 0.0
    # Free-form per-provider extras (e.g. published_date, source domain).
    # Kept opt-in so the response shape stays predictable across providers.
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SearchProvider(ABC):
    """Common contract for every search provider.

    Lifecycle: instantiate with whatever the provider needs (typically an
    API key, optional ``timeout`` / ``base_url``), then call ``search()``.
    A provider that needs an API key but doesn't have one must still
    instantiate cleanly — ``is_configured()`` returns False, the router
    skips it, and ``test_connection()`` reports the same to the UI.
    """

    name: str = "abstract"

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = 10,
        **options: Any,
    ) -> list[SearchResult]:
        """Run the query and return at most ``max_results`` results."""

    def is_configured(self) -> bool:
        """True if the provider has whatever it needs to call the upstream API."""
        return True

    def test_connection(self) -> dict[str, Any]:
        """Light probe used by the Settings UI's "Test" button.

        Default impl runs a 1-result query for ``"hello"``; providers that
        support a cheaper /ping or /quota call should override this.
        """
        if not self.is_configured():
            return {"ok": False, "error": "provider is not configured"}
        try:
            results = self.search("hello", max_results=1)
            return {"ok": True, "result_count": len(results)}
        except SearchProviderError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # last-resort guard for the UI button
            return {"ok": False, "error": f"unexpected: {e}"}
