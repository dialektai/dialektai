"""Instagram MCP tools.

Three sync tools that wrap the existing async :class:`dialekt.tools.
social.instagram_publisher.InstagramPublisher` so an agent can post
to a Business / Creator Instagram account through the standard
Graph API publish flow:

- ``dialekt_instagram_publish_feed`` — single-image feed post
- ``dialekt_instagram_publish_story`` — image-only Story
- ``dialekt_instagram_publish_reel`` — Reel from a hosted video URL

Auth is per-agent: each agent declares its own Facebook Developer
app, so the access_token + ig_user_id pair is read from
:func:`dialekt.secrets.get_secret` by default, with names
configurable per call. There is NO global "Connect Instagram"
button — every tenant pastes their own pair into the wizard, and
the wizard stores them via ``POST /agents/{id}/secrets``.

Image / video URLs must be public HTTPS — the Graph API fetches
them server-side before publishing. Local file paths are not
accepted; the agent's visual pipeline writes the asset, uploads it
via the future CDN tool, then passes the resulting URL here.

Sync wrapper rationale: every other MCP tool in this server is
synchronous (call_tool_wrapped expects a plain callable). Driving
the existing async publisher through ``asyncio.run`` per-call keeps
the MCP boundary uniform without forking a parallel async tool
registration path.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from dialekt import secrets as secrets_module
from dialekt.mcp.server.tools._wrap import call_tool_wrapped
from dialekt.tools.social import instagram_publisher

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


log = logging.getLogger("dialekt.mcp.server.tools.instagram")


DEFAULT_TOKEN_SECRET = "instagram_access_token"
DEFAULT_USER_ID_SECRET = "instagram_ig_user_id"


def _resolve_credentials(
    *,
    access_token: Optional[str],
    ig_user_id: Optional[str],
    token_secret: str,
    user_id_secret: str,
) -> tuple[Optional[str], Optional[str]]:
    """Fall back to the keychain when a credential is not passed
    explicitly. Returns ``(token, user_id)`` — either may still be
    ``None`` if neither source has it."""
    token = access_token or secrets_module.get_secret(token_secret)
    user_id = ig_user_id or secrets_module.get_secret(user_id_secret)
    return token, user_id


def _missing_creds_error(
    token: Optional[str],
    user_id: Optional[str],
    token_secret: str,
    user_id_secret: str,
) -> Optional[dict]:
    """Build a structured error when either credential is unset, or
    ``None`` when both are present."""
    missing: list[str] = []
    if not token:
        missing.append(token_secret)
    if not user_id:
        missing.append(user_id_secret)
    if not missing:
        return None
    return {
        "error": True,
        "reason": "missing_credentials",
        "detail": (
            "instagram credentials missing. Set them via "
            "POST /agents/{id}/secrets or pass access_token/ig_user_id "
            "inline."
        ),
        "missing_secrets": missing,
    }


def _publish(
    coro_factory,
    *,
    access_token: str,
    ig_user_id: str,
) -> dict:
    """Drive an async ``coro_factory(publisher)`` and return a uniform
    payload. Classifies :class:`~instagram_publisher.PublishError`
    into ``{error: true, reason: 'graph_error', detail}`` so the
    agent gets the same shape as the other tools."""
    async def _runner() -> dict:
        async with instagram_publisher.InstagramPublisher(
            ig_user_id=ig_user_id,
            access_token=access_token,
        ) as pub:
            try:
                media_id = await coro_factory(pub)
            except instagram_publisher.PublishError as e:
                return {
                    "error": True,
                    "reason": "graph_error",
                    "detail": str(e),
                }
            return {"media_id": media_id, "ig_user_id": ig_user_id}

    try:
        return asyncio.run(_runner())
    except RuntimeError as e:
        # asyncio.run inside an existing loop raises RuntimeError. The
        # MCP server in production runs sync from the FastMCP dispatcher,
        # so this path mainly fires in pytest-asyncio scope. Surface it
        # as a structured error rather than letting the exception bubble.
        return {
            "error": True,
            "reason": "event_loop_conflict",
            "detail": str(e),
        }


def register_instagram_tools(server: "MCPServer") -> list[str]:
    """Attach the three Instagram publish tools."""
    registered: list[str] = []

    def _maybe_publish(
        kind: str,
        access_token: Optional[str],
        ig_user_id: Optional[str],
        token_secret: str,
        user_id_secret: str,
        coro_factory,
    ) -> dict:
        token, user_id = _resolve_credentials(
            access_token=access_token,
            ig_user_id=ig_user_id,
            token_secret=token_secret,
            user_id_secret=user_id_secret,
        )
        err = _missing_creds_error(token, user_id, token_secret, user_id_secret)
        if err is not None:
            return err
        return _publish(coro_factory, access_token=token, ig_user_id=user_id)

    @server.fastmcp.tool(
        description=(
            "Publish a single image as an Instagram feed post. "
            "``image_url`` must be a public HTTPS URL (the Graph API "
            "fetches it server-side). ``caption`` is optional and "
            "supports the standard Instagram caption rules (hashtags, "
            "mentions). Credentials are read from secrets by default "
            "(``instagram_access_token``, ``instagram_ig_user_id``) — "
            "override secret names via ``token_secret`` / "
            "``user_id_secret`` or pass the values inline."
        )
    )
    def dialekt_instagram_publish_feed(
        image_url: str,
        caption: str = "",
        access_token: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        token_secret: str = DEFAULT_TOKEN_SECRET,
        user_id_secret: str = DEFAULT_USER_ID_SECRET,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_instagram_publish_feed",
            lambda: _maybe_publish(
                "feed",
                access_token,
                ig_user_id,
                token_secret,
                user_id_secret,
                lambda pub: pub.publish_feed_post(image_url, caption),
            ),
            extra_audit={"kind": "feed", "token_secret": token_secret},
        )

    registered.append("dialekt_instagram_publish_feed")

    @server.fastmcp.tool(
        description=(
            "Publish an image to Instagram Stories. Captions are "
            "ignored — Stories don't support them. Image URL must be "
            "public HTTPS. Same credential resolution as "
            "dialekt_instagram_publish_feed."
        )
    )
    def dialekt_instagram_publish_story(
        image_url: str,
        access_token: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        token_secret: str = DEFAULT_TOKEN_SECRET,
        user_id_secret: str = DEFAULT_USER_ID_SECRET,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_instagram_publish_story",
            lambda: _maybe_publish(
                "story",
                access_token,
                ig_user_id,
                token_secret,
                user_id_secret,
                lambda pub: pub.publish_story(image_url),
            ),
            extra_audit={"kind": "story", "token_secret": token_secret},
        )

    registered.append("dialekt_instagram_publish_story")

    @server.fastmcp.tool(
        description=(
            "Publish a Reel from a hosted video URL. Polls until the "
            "Graph API reports the container as ``FINISHED`` (max 120 s). "
            "``video_url`` must be public HTTPS. Same credential "
            "resolution as the feed/story tools. Returns the media id."
        )
    )
    def dialekt_instagram_publish_reel(
        video_url: str,
        caption: str = "",
        access_token: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        token_secret: str = DEFAULT_TOKEN_SECRET,
        user_id_secret: str = DEFAULT_USER_ID_SECRET,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_instagram_publish_reel",
            lambda: _maybe_publish(
                "reel",
                access_token,
                ig_user_id,
                token_secret,
                user_id_secret,
                lambda pub: pub.publish_reel(video_url, caption),
            ),
            extra_audit={"kind": "reel", "token_secret": token_secret},
        )

    registered.append("dialekt_instagram_publish_reel")

    return registered
