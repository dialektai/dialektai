"""Generic HTTP tools for the MCP server.

Three tools — ``dialekt_http_get``, ``dialekt_http_post``,
``dialekt_http_put`` — wrap :mod:`httpx` so agents that need to talk
to external services (Bitrix webhooks, REST APIs, web pages for the
website-audit agent) can do so without a per-vendor MCP module per
target. Bitrix and Instagram still get their own thin tools for
ergonomics, but those wrap this one in spirit.

Safety:

- Only ``http`` and ``https`` schemes are accepted; anything else is
  refused with ``unsupported_scheme``. ``file://`` etc. would let an
  agent read arbitrary local files via the URL surface, which the
  ``file`` category gates separately for a reason.
- Response bodies are capped at :data:`MAX_BODY_BYTES` (10 MB by
  default) — beyond that the body is truncated and the response
  carries ``truncated=True``. Prevents OOMing the MCP server on a
  hostile or buggy upstream.
- Timeouts default to 30 seconds and are capped at 120 seconds — long
  enough for slow CMS endpoints, short enough that a stuck agent
  doesn't block the MCP server's rate limiter forever.

The body comes back as text decoded with the response's declared
charset (or UTF-8 with ``errors='replace'`` as fallback). Callers
that need bytes (PDFs, images) should add a future
``dialekt_http_download`` tool — out of scope here because every IBA
agent talks JSON / HTML / XML.
"""
from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from dialekt.mcp.server.tools._wrap import call_tool_wrapped

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
ALLOWED_SCHEMES = ("http", "https")


class HttpToolError(Exception):
    """Reserved for future structured failures — not raised today;
    handlers return error payloads so audit captures the call."""


def _validate_url(url: str) -> Optional[dict]:
    """Return a structured-error dict if the URL is unusable, else
    ``None``. Reused by all three verbs."""
    if not url or not isinstance(url, str):
        return {"error": True, "reason": "invalid_url", "detail": "url is required"}
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return {
            "error": True,
            "reason": "unsupported_scheme",
            "detail": (
                f"scheme {parsed.scheme!r} not allowed; "
                f"only {list(ALLOWED_SCHEMES)} are supported"
            ),
        }
    if not parsed.netloc:
        return {
            "error": True,
            "reason": "invalid_url",
            "detail": "missing host in URL",
        }
    return None


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


def _format_response(resp: httpx.Response) -> dict:
    """Pull a response into a JSON-friendly dict, honouring the body cap."""
    raw = resp.content or b""
    truncated = False
    if len(raw) > MAX_BODY_BYTES:
        raw = raw[:MAX_BODY_BYTES]
        truncated = True
    # Prefer the response's declared encoding; fall back to utf-8 with
    # replace so we never blow up on a single bad byte.
    encoding = resp.encoding or "utf-8"
    try:
        body = raw.decode(encoding, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")
    return {
        "status": resp.status_code,
        "headers": {k: v for k, v in resp.headers.items()},
        "body": body,
        "body_bytes": len(raw),
        "truncated": truncated,
        "url": str(resp.url),
    }


def _build_client(timeout: float) -> httpx.Client:
    """Single seam for tests to monkeypatch — returns the
    :class:`httpx.Client` used for one request. Production builds
    a real client; tests substitute one wired to
    :class:`httpx.MockTransport`."""
    return httpx.Client(timeout=timeout, follow_redirects=True)


def _do_request(
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    body: Optional[str] = None,
    json_body: Optional[Any] = None,
    timeout: Optional[float] = None,
) -> dict:
    if (err := _validate_url(url)) is not None:
        return err
    if body is not None and json_body is not None:
        return {
            "error": True,
            "reason": "conflicting_body",
            "detail": "pass either ``body`` (raw string) or ``json`` (object), not both",
        }
    timeout_s = _clamp_timeout(timeout)
    try:
        with _build_client(timeout_s) as client:
            resp = client.request(
                method,
                url,
                headers=headers or None,
                content=body if body is not None else None,
                json=json_body if json_body is not None else None,
            )
        return _format_response(resp)
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


def register_http_tools(server: "MCPServer") -> list[str]:
    """Attach the three HTTP tools. Returns the registered names."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "HTTP GET against an absolute http(s) URL. Follows redirects. "
            "Returns ``{status, headers, body, body_bytes, truncated, url}`` — "
            "body is text decoded with the response's declared charset, "
            "capped at 10 MB. Timeouts default to 30 s, max 120 s."
        )
    )
    def dialekt_http_get(
        url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_http_get",
            lambda: _do_request("GET", url, headers=headers, timeout=timeout),
            extra_audit={"url": url},
        )

    registered.append("dialekt_http_get")

    @server.fastmcp.tool(
        description=(
            "HTTP POST. Pass exactly one of ``body`` (raw string) or "
            "``json`` (any JSON-serialisable object). Returns the same "
            "shape as dialekt_http_get."
        )
    )
    def dialekt_http_post(
        url: str,
        body: Optional[str] = None,
        json: Optional[Any] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_http_post",
            lambda: _do_request(
                "POST", url, headers=headers, body=body, json_body=json, timeout=timeout
            ),
            extra_audit={"url": url},
        )

    registered.append("dialekt_http_post")

    @server.fastmcp.tool(
        description=(
            "HTTP PUT. Same conventions as dialekt_http_post."
        )
    )
    def dialekt_http_put(
        url: str,
        body: Optional[str] = None,
        json: Optional[Any] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_http_put",
            lambda: _do_request(
                "PUT", url, headers=headers, body=body, json_body=json, timeout=timeout
            ),
            extra_audit={"url": url},
        )

    registered.append("dialekt_http_put")

    return registered
