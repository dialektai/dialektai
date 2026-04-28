"""Bitrix24 webhook tool for the MCP server.

Single tool — ``dialekt_bitrix_call`` — which POSTs to a Bitrix
incoming webhook (``{webhook_url}/{method}.json``) so an agent can
drive any Bitrix REST method without a per-method MCP wrapper.
That covers the full ``crm.*``, ``lists.*``, ``iblock.*``,
``landing.*``, ``user.*`` surface, including the lists/iblock/landing
methods that community Bitrix MCP servers don't expose today.

Auth is one URL string with the embedded user-id + secret. We read
it from either:

1. ``webhook_url`` argument (explicit override, useful for tests
   and one-off calls), or
2. ``dialekt.secrets.get_secret(secret_name)`` — the agent's
   :doc:`per-agent secrets` flow stores it under
   ``bitrix_webhook_url`` (default) or whatever name the agent's
   manifest declares in ``secrets_required``.

Per https://apidocs.bitrix24.com/local-integrations/local-webhooks.html
the webhook URL already encodes the user_id + token; nothing else
goes on the wire.

We never log the webhook URL — it's a credential. Audit rows carry
``method`` only, never the URL or params.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from dialekt import secrets as secrets_module
from dialekt.mcp.server.tools._wrap import call_tool_wrapped

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


log = logging.getLogger("dialekt.mcp.server.tools.bitrix")


DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
MAX_BODY_BYTES = 10 * 1024 * 1024
ALLOWED_SCHEMES = ("http", "https")
DEFAULT_SECRET_NAME = "bitrix_webhook_url"


def _build_client(timeout: float) -> httpx.Client:
    """Single seam for tests."""
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


def _normalise_webhook_base(url: str) -> Optional[str]:
    """Strip a trailing slash + return the URL ready to be appended
    to with ``/{method}.json``. Returns ``None`` when the URL is not
    a valid http(s) endpoint."""
    if not isinstance(url, str) or not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        return None
    return url.rstrip("/")


def _resolve_method(method: str) -> Optional[str]:
    """Bitrix methods look like ``crm.deal.add`` or
    ``lists.element.update``. Block path-traversal attempts and
    leading slashes that would confuse the URL join."""
    if not isinstance(method, str) or not method:
        return None
    cleaned = method.strip().lstrip("/")
    if "/" in cleaned or ".." in cleaned:
        return None
    return cleaned


def _do_call(
    method: str,
    *,
    params: Optional[dict[str, Any]],
    webhook_url: Optional[str],
    secret_name: str,
    timeout: float,
) -> dict:
    method_clean = _resolve_method(method)
    if method_clean is None:
        return {
            "error": True,
            "reason": "invalid_method",
            "detail": "method must be a non-empty Bitrix REST name (e.g. 'crm.deal.add')",
        }

    if webhook_url is None:
        webhook_url = secrets_module.get_secret(secret_name)
    base = _normalise_webhook_base(webhook_url) if webhook_url else None
    if base is None:
        return {
            "error": True,
            "reason": "missing_webhook",
            "detail": (
                f"no webhook_url provided and secret {secret_name!r} is "
                "unset. Set it via POST /agents/{id}/secrets or pass "
                "webhook_url explicitly."
            ),
        }

    timeout_s = _clamp_timeout(timeout)
    target = f"{base}/{method_clean}.json"
    payload = params if isinstance(params, dict) else {}

    try:
        with _build_client(timeout_s) as client:
            resp = client.post(target, json=payload)
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

    raw = resp.content or b""
    truncated = False
    if len(raw) > MAX_BODY_BYTES:
        raw = raw[:MAX_BODY_BYTES]
        truncated = True

    try:
        body = resp.json() if raw else {}
    except ValueError:
        return {
            "error": True,
            "reason": "non_json_response",
            "status": resp.status_code,
            "body_bytes": len(raw),
            "preview": raw[:512].decode("utf-8", errors="replace"),
        }

    out = {
        "status": resp.status_code,
        "method": method_clean,
        "result": body.get("result"),
        "total": body.get("total"),
        "next": body.get("next"),
        "time": body.get("time"),
        "truncated": truncated,
    }
    if "error" in body or "error_description" in body:
        out["error"] = True
        out["bitrix_error"] = body.get("error")
        out["error_description"] = body.get("error_description")
    return out


def register_bitrix_tools(server: "MCPServer") -> list[str]:
    """Attach the bitrix tool. Returns the registered names."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "Call any Bitrix24 REST method through an incoming webhook. "
            "``method`` is the dotted Bitrix name (e.g. 'crm.deal.add', "
            "'lists.element.update', 'landing.landing.publication'); "
            "``params`` is the JSON object Bitrix expects. "
            "The webhook URL is read from the ``bitrix_webhook_url`` "
            "secret by default — override the secret name via "
            "``secret_name`` or pass ``webhook_url`` directly. "
            "Returns ``{status, method, result, total, next, time}`` on "
            "success or ``{error: true, reason, ...}`` for transport "
            "failures and ``{error: true, bitrix_error, error_description}`` "
            "for Bitrix-side errors."
        )
    )
    def dialekt_bitrix_call(
        method: str,
        params: Optional[dict[str, Any]] = None,
        webhook_url: Optional[str] = None,
        secret_name: str = DEFAULT_SECRET_NAME,
        timeout: Optional[float] = None,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_bitrix_call",
            lambda: _do_call(
                method,
                params=params,
                webhook_url=webhook_url,
                secret_name=secret_name,
                timeout=_clamp_timeout(timeout),
            ),
            extra_audit={"method": method, "secret_name": secret_name},
        )

    registered.append("dialekt_bitrix_call")
    return registered
