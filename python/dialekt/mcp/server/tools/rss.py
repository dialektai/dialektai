"""RSS / Atom feed tool for the MCP server.

Single tool — ``dialekt_rss_fetch`` — fetches a feed URL with httpx
(reusing the timeout + size-limit discipline of the generic http
tool) and parses it with :mod:`feedparser` into a stable, agent-
friendly shape.

Used by:

- The website analytics + KZ-legislation monitoring agents which
  need to pick out recent items between cron ticks.
- The scheduler's ``rss_poll`` integration (lands in a follow-up
  task) which runs the same fetch+parse but on an agent's
  ``trigger.rss_feeds[]`` BEFORE invoking the LLM.

Why parse here instead of letting agents call feedparser themselves:

1. Open Interpreter agents would otherwise need to reach into the
   Python sandbox, which means importing feedparser at runtime —
   this concentrates the dep into one tested code path.
2. The MCP tool surface is JSON-only; emitting normalised dict
   items with ISO-8601 timestamps avoids the agent re-formatting
   feedparser's nine-tuple ``published_parsed`` shape on every
   call.
3. Auditing — the same allow-list / rate-limit / audit row applies.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Optional, TYPE_CHECKING
from urllib.parse import urlparse

import feedparser
import httpx

from dialekt.mcp.server.tools._wrap import call_tool_wrapped

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


MAX_FEED_BYTES = 10 * 1024 * 1024  # 10 MB — same cap as http tool
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
DEFAULT_MAX_ITEMS = 50
HARD_MAX_ITEMS = 500
ALLOWED_SCHEMES = ("http", "https")
DEFAULT_USER_AGENT = "dialekt-mcp/0.27 (+https://dias.now)"


def _build_client(timeout: float) -> httpx.Client:
    """Single seam for tests to monkeypatch."""
    return httpx.Client(timeout=timeout, follow_redirects=True)


def _clamp_timeout(timeout: float | int | None) -> float:
    if timeout is None:
        return DEFAULT_TIMEOUT
    try:
        t = float(timeout)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    if t <= 0:
        return DEFAULT_TIMEOUT
    return min(t, MAX_TIMEOUT)


def _clamp_max_items(max_items: int | None) -> int:
    if max_items is None:
        return DEFAULT_MAX_ITEMS
    try:
        n = int(max_items)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ITEMS
    if n <= 0:
        return DEFAULT_MAX_ITEMS
    return min(n, HARD_MAX_ITEMS)


def _validate_url(url: str) -> Optional[dict]:
    if not url or not isinstance(url, str):
        return {"error": True, "reason": "invalid_url", "detail": "url is required"}
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return {
            "error": True,
            "reason": "unsupported_scheme",
            "detail": f"scheme {parsed.scheme!r} not allowed",
        }
    if not parsed.netloc:
        return {
            "error": True,
            "reason": "invalid_url",
            "detail": "missing host in URL",
        }
    return None


def _struct_time_to_iso(value) -> Optional[str]:
    """feedparser stores dates as :class:`time.struct_time` in UTC.
    Convert to ISO-8601 with the ``Z`` suffix for downstream
    consumers (the agent prompt + ``agent_rss_state`` table)."""
    if value is None:
        return None
    if not isinstance(value, time.struct_time):
        return None
    try:
        return dt.datetime(*value[:6], tzinfo=dt.timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    except (TypeError, ValueError):
        return None


def _normalize_entry(entry) -> dict:
    """Pull the fields agents actually use out of feedparser's
    FeedParserDict, with safe defaults so downstream code can rely
    on every key being present."""
    return {
        "guid": entry.get("id") or entry.get("guid") or entry.get("link"),
        "title": entry.get("title") or "",
        "link": entry.get("link"),
        "summary": entry.get("summary"),
        "published": _struct_time_to_iso(entry.get("published_parsed"))
        or _struct_time_to_iso(entry.get("updated_parsed")),
        "author": entry.get("author"),
    }


def _fetch_and_parse(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict:
    if (err := _validate_url(url)) is not None:
        return err
    timeout_s = _clamp_timeout(timeout)
    items_cap = _clamp_max_items(max_items)
    request_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        request_headers.update(headers)

    try:
        with _build_client(timeout_s) as client:
            resp = client.get(url, headers=request_headers)
    except httpx.TimeoutException as e:
        return {
            "error": True,
            "reason": "timeout",
            "detail": str(e),
            "timeout_seconds": timeout_s,
        }
    except httpx.RequestError as e:
        return {
            "error": True,
            "reason": "request_failed",
            "detail": str(e),
            "error_kind": type(e).__name__,
        }

    if resp.status_code >= 400:
        return {
            "error": True,
            "reason": "http_error",
            "status": resp.status_code,
            "url": str(resp.url),
        }

    raw = resp.content or b""
    if len(raw) > MAX_FEED_BYTES:
        raw = raw[:MAX_FEED_BYTES]

    parsed = feedparser.parse(raw)
    bozo = bool(parsed.get("bozo"))
    feed = parsed.get("feed", {}) or {}
    entries = parsed.get("entries", []) or []
    truncated = len(entries) > items_cap
    entries = entries[:items_cap]

    return {
        "url": str(resp.url),
        "feed_title": feed.get("title") or "",
        "feed_link": feed.get("link"),
        "feed_subtitle": feed.get("subtitle"),
        "items": [_normalize_entry(e) for e in entries],
        "item_count": len(entries),
        "truncated": truncated,
        "bozo": bozo,
    }


def register_rss_tools(server: "MCPServer") -> list[str]:
    """Attach the rss tool. Returns the registered names."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "Fetch and parse an RSS or Atom feed. Returns a stable "
            "``{feed_title, items: [{guid, title, link, summary, "
            "published, author}], item_count, truncated, bozo}`` shape "
            "with ISO-8601 ``published`` timestamps. Items are capped "
            "at ``max_items`` (default 50, hard limit 500); set "
            "``timeout`` in seconds (default 30, max 120). ``bozo=true`` "
            "signals feedparser flagged the input as malformed but "
            "items may still be usable."
        )
    )
    def dialekt_rss_fetch(
        url: str,
        max_items: Optional[int] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_rss_fetch",
            lambda: _fetch_and_parse(
                url,
                headers=headers,
                timeout=_clamp_timeout(timeout),
                max_items=_clamp_max_items(max_items),
            ),
            extra_audit={"url": url},
        )

    registered.append("dialekt_rss_fetch")
    return registered
