"""Facebook/Instagram Graph API OAuth helpers.

The flow is the standard server-side OAuth 2 dance against Facebook's
``graph.facebook.com`` host:

    1. ``build_auth_url`` — open in browser; user grants permissions.
    2. Redirect lands on our local callback with ``?code=...``.
    3. ``exchange_code_for_token`` — short-lived (≈1h) token.
    4. ``exchange_for_long_lived`` — 60-day token.
    5. ``refresh_long_lived`` — re-issue 60 days from "now". Should run
       within the last week before expiry; the endpoint won't refresh
       a token that already has fresh life on it.

We only support the Instagram Graph API surface (Business / Creator
accounts attached to a Facebook Page). The deprecated "Instagram Basic
Display" path is intentionally not modelled — it cannot publish.

This module is *pure I/O*: no keychain, no settings, no audit. The
server router stitches it to ``dialekt.secrets``. That separation keeps
the unit tests honest — every external call is one mockable httpx
request.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlencode

import httpx

log = logging.getLogger("dialekt.tools.instagram.oauth")

GRAPH_HOST = "https://graph.facebook.com"
GRAPH_VERSION = "v19.0"
AUTHORIZE_URL = "https://www.facebook.com/v19.0/dialog/oauth"

# Permissions required to read the user's Pages, find the Instagram
# Business account attached to one, and publish content. ``pages_*``
# perms are needed because Instagram Business is exposed *via* the
# linked Facebook Page — the IG user-id is read off the Page node.
DEFAULT_SCOPES: tuple[str, ...] = (
    "instagram_basic",
    "instagram_content_publish",
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
)

# Long-lived tokens are documented as 60 days. We refresh proactively
# within ``REFRESH_WINDOW_DAYS`` of expiry — Meta refuses to refresh a
# token that still has more than ~24h of life, so we don't refresh
# *too* eagerly either.
LONG_LIVED_TTL_DAYS = 60
REFRESH_WINDOW_DAYS = 7


class OAuthError(Exception):
    """Raised when Facebook returns a non-2xx with an ``error`` body."""


def build_auth_url(
    app_id: str,
    redirect_uri: str,
    *,
    state: str,
    scopes: Iterable[str] = DEFAULT_SCOPES,
) -> str:
    """Return the Facebook authorize URL the user must visit in a browser.

    ``state`` is round-tripped to the callback to defend against CSRF —
    the caller must persist it and verify on the way back.
    """
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": ",".join(scopes),
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(
    app_id: str,
    app_secret: str,
    code: str,
    redirect_uri: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Trade an OAuth ``code`` for a short-lived access token.

    Returns the raw JSON: ``{"access_token": ..., "token_type": ...,
    "expires_in": int}``. Raises ``OAuthError`` on a Graph-side error.
    """
    return await _get_token(
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        client=client,
    )


async def exchange_for_long_lived(
    app_id: str,
    app_secret: str,
    short_token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Upgrade a short-lived token to the 60-day long-lived variant."""
    return await _get_token(
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        client=client,
    )


async def refresh_long_lived(
    app_id: str,
    app_secret: str,
    long_token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Re-issue a long-lived token, resetting its 60-day clock.

    Same endpoint as ``exchange_for_long_lived`` — Graph treats the
    request identically whether the input is short- or long-lived.
    Kept as a separate name so callers signal intent at the call site.
    """
    return await exchange_for_long_lived(app_id, app_secret, long_token, client=client)


async def get_ig_business_account(
    access_token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Walk the FB Page → Instagram Business account graph.

    Returns ``{"page_id", "page_name", "ig_user_id", "username"}`` for
    the first Page that has a linked Instagram Business account. Raises
    ``OAuthError`` when no eligible Page is found — usually because
    the user logged in with a personal IG account.
    """
    own = client is None
    cli = client or httpx.AsyncClient(timeout=15)
    try:
        r = await cli.get(
            f"{GRAPH_HOST}/{GRAPH_VERSION}/me/accounts",
            params={
                "access_token": access_token,
                "fields": "id,name,instagram_business_account",
            },
        )
        _raise_for_graph_error(r)
        for page in r.json().get("data", []):
            iba = page.get("instagram_business_account")
            if not iba:
                continue
            ig_id = iba.get("id")
            ig_meta = await cli.get(
                f"{GRAPH_HOST}/{GRAPH_VERSION}/{ig_id}",
                params={"access_token": access_token, "fields": "username"},
            )
            _raise_for_graph_error(ig_meta)
            return {
                "page_id": page["id"],
                "page_name": page.get("name"),
                "ig_user_id": ig_id,
                "username": ig_meta.json().get("username"),
            }
    finally:
        if own:
            await cli.aclose()
    raise OAuthError(
        "no Instagram Business or Creator account attached to any of your "
        "Facebook Pages — connect one in the Instagram app first"
    )


def needs_refresh(token_expires_iso: str | None, *, now: datetime | None = None) -> bool:
    """True when the long-lived token is within ``REFRESH_WINDOW_DAYS`` of expiry.

    A missing / malformed expiry returns True so the scheduler reads it
    as "refresh now"; the worst case is a single redundant refresh,
    not a publish failure mid-run.
    """
    if not token_expires_iso:
        return True
    try:
        exp = datetime.fromisoformat(token_expires_iso.replace("Z", "+00:00"))
    except ValueError:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    cur = now or datetime.now(timezone.utc)
    return (exp - cur) <= timedelta(days=REFRESH_WINDOW_DAYS)


def expires_at_from_payload(payload: dict, *, now: datetime | None = None) -> str:
    """Convert Graph's ``expires_in`` (seconds) to an absolute ISO-8601 UTC stamp.

    Falls back to ``LONG_LIVED_TTL_DAYS`` when Graph omits the field —
    has happened on long-lived refresh responses.
    """
    cur = now or datetime.now(timezone.utc)
    secs = payload.get("expires_in")
    if isinstance(secs, (int, float)) and secs > 0:
        return (cur + timedelta(seconds=int(secs))).isoformat()
    return (cur + timedelta(days=LONG_LIVED_TTL_DAYS)).isoformat()


# ── internals ────────────────────────────────────────────────────────────────

async def _get_token(*, params: dict, client: httpx.AsyncClient | None) -> dict:
    own = client is None
    cli = client or httpx.AsyncClient(timeout=15)
    try:
        r = await cli.get(f"{GRAPH_HOST}/{GRAPH_VERSION}/oauth/access_token", params=params)
        _raise_for_graph_error(r)
        body = r.json()
        if "access_token" not in body:
            raise OAuthError(f"token endpoint returned no access_token: {body}")
        return body
    finally:
        if own:
            await cli.aclose()


def _raise_for_graph_error(response: httpx.Response) -> None:
    """Translate Facebook error JSON into a single-line ``OAuthError``."""
    if response.is_success:
        return
    try:
        err = response.json().get("error") or {}
    except Exception:
        err = {}
    msg = err.get("message") or response.text or f"HTTP {response.status_code}"
    code = err.get("code")
    sub = err.get("error_subcode")
    detail = f"{msg} [code={code} sub={sub}]" if code is not None else msg
    raise OAuthError(detail)
