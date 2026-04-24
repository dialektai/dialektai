"""API key validation + rate limiting for the dialekt MCP server.

Two small building blocks the tool handlers (Commits 3-5) compose on
their way to :class:`MCPClientManager`-equivalent behaviour:

- :func:`validate_api_key` — constant-time lookup against
  :class:`ServerConfig`, raises :class:`AuthError` on mismatch.
- :class:`RateLimiter` — rolling 60-second window per API key id.

Stdio-transport specifics: auth happens ONCE at process startup
(Decision 5 — one process per MCP client session). The active key
carries through until the subprocess exits. The rate limiter runs
per call because that's where the meaningful bound lives.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from dialekt.mcp.server.config import ApiKey, ServerConfig


class AuthError(Exception):
    """Invalid or missing API key. CLI entry point maps this to
    exit code 2 with a user-facing stderr message."""


def validate_api_key(config: ServerConfig, provided: Optional[str]) -> ApiKey:
    """Return the matching :class:`ApiKey` or raise :class:`AuthError`.

    Called once at server startup — the CLI reads the key from
    ``--api-key`` / ``DIALEKT_MCP_API_KEY``, passes it here, and stores
    the returned :class:`ApiKey` on the :class:`MCPServer` instance.
    """
    if not provided:
        raise AuthError(
            "no API key supplied. Pass --api-key KEY or set "
            "DIALEKT_MCP_API_KEY in the environment. "
            "Open dialekt → Settings → Integrations to copy a key."
        )
    match = config.has_api_key(provided)
    if match is None:
        raise AuthError(
            "API key not recognised. Check that the key matches one "
            "of the entries in ~/.dialekt/mcp-server.toml, or rotate "
            "it via dialekt → Settings → Integrations."
        )
    return match


class RateLimiter:
    """Rolling-window call counter. Per-key instance.

    Matches the shape used by :class:`dialekt.mcp.manager.MCPClientManager`
    — 60-second window, list-of-timestamps implementation, pruned on
    each check. For v0.20.0 workloads (one pilot, one process, maybe
    a few hundred calls/hour) the linear scan is fine; future work
    can swap in a bounded deque if we see it matter in profiling.
    """

    def __init__(
        self,
        max_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_per_minute <= 0:
            raise ValueError("max_per_minute must be > 0")
        self._max = max_per_minute
        self._clock = clock
        self._window: list[float] = []

    def check_and_record(self) -> None:
        """Record a new call attempt. Raises :class:`RateLimitExceeded`
        if the 60-second window is full."""
        now = self._clock()
        cutoff = now - 60.0
        self._window = [ts for ts in self._window if ts > cutoff]
        if len(self._window) >= self._max:
            raise RateLimitExceeded(
                f"rate limit {self._max}/min exceeded"
            )
        self._window.append(now)

    def remaining(self) -> int:
        """How many more calls the caller can make in the current window.

        Prunes expired entries as a side effect. Useful for tools that
        want to surface a "you have N calls left" hint."""
        now = self._clock()
        cutoff = now - 60.0
        self._window = [ts for ts in self._window if ts > cutoff]
        return max(0, self._max - len(self._window))


class RateLimitExceeded(Exception):
    """120/min ceiling tripped. CLI / tool wrapper maps this to the
    MCP protocol's tool error channel; the LLM sees a
    ``rate_limited`` result and can back off."""
