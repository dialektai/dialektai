"""Instagram Graph API publisher.

Publishes feed posts, stories, and Reels through the Instagram Graph
API. Two-step flow on every publish:

    1. ``POST /{ig-user-id}/media`` — creates a *container* for the
       media. For images this returns immediately; for video / Reels /
       stories the container goes through ``IN_PROGRESS`` → ``FINISHED``
       and we poll its status before step 2.
    2. ``POST /{ig-user-id}/media_publish`` — promotes the container
       to a published post. Returns the public media id.

The Graph API only accepts publicly reachable HTTPS URLs for the media
itself — there is no multipart upload on the publish path. Callers
must therefore pass URLs (a separate "uploader" can stage local files
on a CDN; that's intentionally out of scope here so this module stays
trivially testable).

This module is a *pure async client*: it talks to Graph and nothing
else. Token storage, refresh scheduling, audit logging, and consent
prompts all live in the server router.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import httpx

from .oauth_flow import GRAPH_HOST, GRAPH_VERSION, OAuthError, _raise_for_graph_error

log = logging.getLogger("dialekt.tools.instagram.publish")

PublishKind = Literal["feed_post", "story", "reel"]

# Status polling: containers usually finish in a few seconds, but
# Reels can take 30s+. Cap total wait so a stuck job surfaces as a
# clear timeout rather than a hung request.
_POLL_INTERVAL_SECONDS = 2.0
_POLL_TIMEOUT_SECONDS = 120.0


class PublishError(Exception):
    """Raised on container failure, timeout, or Graph rejection."""


class InstagramPublisher:
    """Thin async wrapper around the Graph publish surface.

    One instance per call site is cheap; the underlying ``httpx`` client
    is created lazily and closed on ``aclose``. Tests inject their own
    client through the constructor to mock the transport.
    """

    def __init__(
        self,
        ig_user_id: str,
        access_token: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.ig_user_id = ig_user_id
        self.access_token = access_token
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "InstagramPublisher":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    # ── public surface ───────────────────────────────────────────────

    async def publish_feed_post(self, image_url: str, caption: str = "") -> str:
        """Publish a single image to the feed. Returns the published media id.

        Multi-image carousel and video posts are deliberately out of
        scope for v1 — they need a different container shape that
        expands surface area without serving the spec.
        """
        container_id = await self._create_container(
            {"image_url": image_url, "caption": caption}
        )
        return await self._publish_container(container_id)

    async def publish_story(self, image_url: str) -> str:
        """Publish an image to Stories. Captions aren't supported on stories."""
        container_id = await self._create_container(
            {"image_url": image_url, "media_type": "STORIES"}
        )
        await self._wait_for_container_finished(container_id)
        return await self._publish_container(container_id)

    async def publish_reel(self, video_url: str, caption: str = "") -> str:
        """Publish a Reel. Status polling is required — Reels are async-encoded."""
        container_id = await self._create_container(
            {
                "video_url": video_url,
                "media_type": "REELS",
                "caption": caption,
                "share_to_feed": "true",
            }
        )
        await self._wait_for_container_finished(container_id)
        return await self._publish_container(container_id)

    # ── Graph plumbing ───────────────────────────────────────────────

    async def _create_container(self, params: dict) -> str:
        body = {"access_token": self.access_token, **params}
        r = await self.client.post(
            f"{GRAPH_HOST}/{GRAPH_VERSION}/{self.ig_user_id}/media",
            data=body,
        )
        _raise_for_graph_error(r)
        cid = r.json().get("id")
        if not cid:
            raise PublishError(f"media container missing id: {r.text}")
        return cid

    async def _publish_container(self, container_id: str) -> str:
        r = await self.client.post(
            f"{GRAPH_HOST}/{GRAPH_VERSION}/{self.ig_user_id}/media_publish",
            data={"access_token": self.access_token, "creation_id": container_id},
        )
        _raise_for_graph_error(r)
        media_id = r.json().get("id")
        if not media_id:
            raise PublishError(f"media_publish missing id: {r.text}")
        return media_id

    async def _wait_for_container_finished(self, container_id: str) -> None:
        """Poll ``status_code`` until ``FINISHED`` (or fail). Required for
        async-processed media types (Stories, Reels, Video). Image-only
        feed posts skip this — the container is born ready.
        """
        deadline = asyncio.get_event_loop().time() + _POLL_TIMEOUT_SECONDS
        while True:
            r = await self.client.get(
                f"{GRAPH_HOST}/{GRAPH_VERSION}/{container_id}",
                params={
                    "access_token": self.access_token,
                    "fields": "status_code,status",
                },
            )
            _raise_for_graph_error(r)
            status = r.json().get("status_code")
            if status == "FINISHED":
                return
            if status in {"ERROR", "EXPIRED"}:
                raise PublishError(
                    f"container {container_id} ended in status={status}: "
                    f"{r.json().get('status', '')}"
                )
            if asyncio.get_event_loop().time() >= deadline:
                raise PublishError(
                    f"container {container_id} did not finish within "
                    f"{_POLL_TIMEOUT_SECONDS:.0f}s (last status={status})"
                )
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)


# Re-export so the server router can ``except`` on either kind without
# reaching into oauth_flow's module path.
__all__ = ["InstagramPublisher", "PublishError", "PublishKind", "OAuthError"]
