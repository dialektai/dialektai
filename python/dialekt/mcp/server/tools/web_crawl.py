"""Web crawler tool for the MCP server.

Single tool — ``dialekt_web_crawl`` — that drives Playwright headless
Chromium to fetch a URL with JavaScript rendered, then extracts:

- ``title`` — document title
- ``text`` — innerText of a specified selector (or ``body`` by default)
- ``links`` — list of ``{href, text}`` pairs from anchors
- ``selectors`` — dict of selector → text (or null) for caller-supplied
  CSS selectors so an agent can pull specific elements without
  re-implementing DOM traversal

Used by the website-audit agent (TZ #5) to walk iba.kz, extract
copy + recency signals, and feed pages into the LLM for review.
Also usable by content-editor agent variants when they need to
pull current page text from a CMS-backed URL.

Why Playwright (not httpx + BeautifulSoup): IBA's site is rendered
through Bitrix's templating + JS widgets; static HTML fetch loses
half the content. The HTML-to-PNG visual tool already pulls
Playwright in as a dependency, so the marginal cost is zero.

Safety:
- Only ``http`` / ``https`` schemes accepted. ``file://`` would let
  an agent bypass the file allow-list via the URL surface; the
  ``file`` category gates that on purpose.
- Body text capped at :data:`MAX_TEXT_BYTES` (5 MB) — beyond that
  the response carries ``truncated=True``. Prevents OOMing the
  MCP server on a hostile / runaway page.
- Timeouts default 30 s, capped at 120 s.
- One browser context per call — closed in ``finally`` even on
  exception so a stuck page doesn't leak Chromium processes.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING
from urllib.parse import urlparse

from dialekt.mcp.server.tools._wrap import call_tool_wrapped

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


log = logging.getLogger("dialekt.mcp.server.tools.web_crawl")


MAX_TEXT_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_TIMEOUT_MS = 30_000
MAX_TIMEOUT_MS = 120_000
DEFAULT_LINK_LIMIT = 200
HARD_LINK_LIMIT = 2000
ALLOWED_SCHEMES = ("http", "https")
DEFAULT_USER_AGENT = "dialekt-mcp-crawl/0.27 (+https://dias.now)"
DEFAULT_NETWORK_IDLE_MS = 1500


def _validate_url(url: str) -> Optional[dict]:
    if not url or not isinstance(url, str):
        return {"error": True, "reason": "invalid_url", "detail": "url is required"}
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return {
            "error": True,
            "reason": "unsupported_scheme",
            "detail": f"scheme {parsed.scheme!r} not allowed; only http/https",
        }
    if not parsed.netloc:
        return {"error": True, "reason": "invalid_url", "detail": "missing host"}
    return None


def _clamp_timeout_ms(timeout: float | int | None) -> int:
    """``timeout`` is always seconds; clamp to ms in [0, MAX_TIMEOUT_MS]."""
    if timeout is None:
        return DEFAULT_TIMEOUT_MS
    try:
        t = int(float(timeout) * 1000)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_MS
    if t <= 0:
        return DEFAULT_TIMEOUT_MS
    return min(t, MAX_TIMEOUT_MS)


def _clamp_link_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LINK_LIMIT
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LINK_LIMIT
    if n <= 0:
        return DEFAULT_LINK_LIMIT
    return min(n, HARD_LINK_LIMIT)


def _build_browser_context(timeout_ms: int):
    """Single seam — tests monkeypatch this to inject a stub browser
    that returns canned page content without launching Chromium."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except Exception:
        pw.stop()
        raise
    context = browser.new_context(user_agent=DEFAULT_USER_AGENT)
    context.set_default_timeout(timeout_ms)
    return pw, browser, context


def _do_crawl(
    url: str,
    *,
    text_selector: Optional[str],
    selectors: Optional[dict[str, str]],
    timeout_ms: int,
    link_limit: int,
) -> dict:
    """Run the crawl; returns the response dict (success or error
    payload). Caller wraps in audit + rate limiting."""
    if (err := _validate_url(url)) is not None:
        return err

    try:
        pw, browser, context = _build_browser_context(timeout_ms)
    except Exception as e:
        return {
            "error": True,
            "reason": "browser_launch_failed",
            "detail": str(e),
        }

    try:
        page = context.new_page()
        try:
            response = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        except Exception as e:
            return {
                "error": True,
                "reason": "navigation_failed",
                "detail": str(e),
            }
        try:
            page.wait_for_load_state("networkidle", timeout=DEFAULT_NETWORK_IDLE_MS)
        except Exception:
            # Network-idle timeout is non-fatal — many sites keep XHRs
            # warm. domcontentloaded already fired so the DOM is usable.
            pass

        status = response.status if response is not None else None
        title = page.title() or ""
        target_selector = text_selector or "body"
        try:
            element = page.query_selector(target_selector)
            text = element.inner_text() if element is not None else ""
        except Exception:
            text = ""

        truncated = False
        text_bytes = text.encode("utf-8")
        if len(text_bytes) > MAX_TEXT_BYTES:
            text = text_bytes[:MAX_TEXT_BYTES].decode("utf-8", errors="replace")
            truncated = True

        link_data: list[dict[str, str]] = []
        try:
            anchors = page.query_selector_all("a[href]")
            for anchor in anchors[:link_limit]:
                href = anchor.get_attribute("href") or ""
                if not href:
                    continue
                anchor_text = (anchor.inner_text() or "").strip()
                if len(anchor_text) > 200:
                    anchor_text = anchor_text[:200] + "…"
                link_data.append({"href": href, "text": anchor_text})
        except Exception:
            pass

        per_selector: dict[str, Optional[str]] = {}
        if selectors:
            for label, css in selectors.items():
                if not isinstance(label, str) or not isinstance(css, str):
                    continue
                try:
                    el = page.query_selector(css)
                    per_selector[label] = el.inner_text() if el is not None else None
                except Exception:
                    per_selector[label] = None

        return {
            "url": page.url,
            "status": status,
            "title": title,
            "text": text,
            "text_bytes": len(text_bytes),
            "truncated": truncated,
            "links": link_data,
            "link_count": len(link_data),
            "selectors": per_selector,
        }
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


def register_web_crawl_tools(server: "MCPServer") -> list[str]:
    """Attach the web_crawl tool. Returns registered names."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "Fetch a public web page with JavaScript rendered (Playwright "
            "headless Chromium) and extract structured content. Returns "
            "``{url, status, title, text, text_bytes, truncated, links: "
            "[{href, text}], link_count, selectors: {label: text}}``. "
            "``text_selector`` (default 'body') chooses which element's "
            "innerText flows into ``text``. ``selectors`` (optional dict) "
            "lets the caller pull specific elements by CSS selector. "
            "10 MB / 120 s caps; only http(s) URLs accepted."
        )
    )
    def dialekt_web_crawl(
        url: str,
        text_selector: Optional[str] = None,
        selectors: Optional[dict[str, str]] = None,
        link_limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_web_crawl",
            lambda: _do_crawl(
                url,
                text_selector=text_selector,
                selectors=selectors,
                timeout_ms=_clamp_timeout_ms(timeout),
                link_limit=_clamp_link_limit(link_limit),
            ),
            extra_audit={"url": url},
        )

    registered.append("dialekt_web_crawl")
    return registered
