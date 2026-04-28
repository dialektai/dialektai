"""Per-agent RSS polling for the scheduler.

Each scheduled agent that declares ``trigger.rss_feeds: [url1, url2]``
gets its feeds checked at every cron tick BEFORE the LLM is
invoked. New items (those whose ``guid`` we haven't seen on a prior
tick) are returned to the runner so they can be injected into the
agent's prompt context. Already-seen guids are persisted in the
``agent_rss_state`` table (created by ``server.py``) so the next
tick only surfaces deltas.

The fetch+parse path is shared with ``dialekt.mcp.server.tools.rss``
(which the agent itself can also call ad-hoc through MCP). We
delegate to the sync ``_fetch_and_parse`` helper there and run it
through :func:`asyncio.to_thread` so the scheduler's event loop
isn't blocked by feedparser / httpx (both sync). One thread per
URL per tick is fine — the rate limit on cron ticks is the cron
schedule itself, and feeds are rarely more than a handful per
agent.

Storage shape — JSON array of strings, oldest first:

    {agent_id, url} → seen_guids = ["guid-a", "guid-b", ...]

We cap the persisted set at :data:`MAX_REMEMBERED_GUIDS` (500) per
{agent, url}. Rotating off the oldest entries when the cap is hit
keeps the table bounded without losing recent history. The cap is
generous enough that even a feed that publishes 50/day takes 10
days to roll over — far longer than typical poll intervals.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional, TYPE_CHECKING

from dialekt.mcp.server.tools import rss as rss_tool

if TYPE_CHECKING:
    import aiosqlite

log = logging.getLogger("dialekt.scheduler.rss_poll")


MAX_REMEMBERED_GUIDS = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _load_seen_guids(
    db: "aiosqlite.Connection", agent_id: str, url: str
) -> list[str]:
    """Return the persisted seen-guids list, oldest first. Empty list
    when the agent has never polled this URL before."""
    async with db.execute(
        "SELECT seen_guids FROM agent_rss_state WHERE agent_id = ? AND url = ?",
        (agent_id, url),
    ) as cur:
        row = await cur.fetchone()
    if row is None or not row[0]:
        return []
    try:
        parsed = json.loads(row[0])
    except (TypeError, ValueError):
        log.warning(
            "agent_rss_state row for agent=%s url=%s has unparseable seen_guids; "
            "treating as empty",
            agent_id,
            url,
        )
        return []
    if not isinstance(parsed, list):
        return []
    return [str(g) for g in parsed if g is not None]


async def _persist_seen_guids(
    db: "aiosqlite.Connection",
    agent_id: str,
    url: str,
    seen_guids: Iterable[str],
) -> None:
    """Upsert the trimmed seen-guids list and refresh ``last_polled_at``.
    Trims to :data:`MAX_REMEMBERED_GUIDS` entries (oldest first dropped)."""
    trimmed = list(seen_guids)
    if len(trimmed) > MAX_REMEMBERED_GUIDS:
        trimmed = trimmed[-MAX_REMEMBERED_GUIDS:]
    payload = json.dumps(trimmed, ensure_ascii=False)
    await db.execute(
        """
        INSERT INTO agent_rss_state (agent_id, url, seen_guids, last_polled_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(agent_id, url) DO UPDATE SET
            seen_guids     = excluded.seen_guids,
            last_polled_at = excluded.last_polled_at
        """,
        (agent_id, url, payload, _now_iso()),
    )
    await db.commit()


async def _fetch_one(url: str, timeout: float, max_items: int) -> dict:
    """Run the sync feedparser / httpx path off-loop so the scheduler
    isn't blocked while the network call is in flight."""
    return await asyncio.to_thread(
        rss_tool._fetch_and_parse,
        url,
        timeout=timeout,
        max_items=max_items,
    )


async def fetch_new_items(
    db: "aiosqlite.Connection",
    agent_id: str,
    urls: Iterable[str],
    *,
    timeout: float = 30.0,
    max_items_per_url: int = 50,
) -> dict[str, dict]:
    """For each ``url``, return ``{items: [...], error: ..., total: int}``.

    On success the returned ``items`` list contains only items NOT seen
    on any previous poll for this ``(agent_id, url)`` pair, in the same
    order they appeared in the feed. The persisted seen-guids list is
    updated atomically per URL — a fetch failure for one feed does not
    poison the state of another.

    On fetch / parse error the URL's entry carries
    ``{error: True, reason: ..., items: []}`` and the persisted state
    is left untouched, so the next tick will retry from the same
    baseline.
    """
    results: dict[str, dict] = {}
    seen_urls: set[str] = set()
    for url in urls:
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            fetched = await _fetch_one(url, timeout, max_items_per_url)
        except Exception as e:  # noqa: BLE001 — defensive boundary
            log.exception(
                "rss_poll fetch crashed for agent=%s url=%s", agent_id, url
            )
            results[url] = {
                "error": True,
                "reason": "fetch_crashed",
                "detail": str(e),
                "items": [],
                "total": 0,
            }
            continue

        if fetched.get("error"):
            results[url] = {
                "error": True,
                "reason": fetched.get("reason"),
                "detail": fetched.get("detail"),
                "status": fetched.get("status"),
                "items": [],
                "total": 0,
            }
            continue

        already_seen = await _load_seen_guids(db, agent_id, url)
        seen_set = set(already_seen)
        new_items: list[dict] = []
        new_guids_in_order: list[str] = []
        for item in fetched.get("items", []):
            guid = item.get("guid")
            if not guid or guid in seen_set:
                continue
            new_items.append(item)
            new_guids_in_order.append(guid)
            seen_set.add(guid)

        if new_guids_in_order:
            # Append new guids to the existing list so order ≈ ingestion
            # order; trim happens in _persist_seen_guids.
            updated = already_seen + new_guids_in_order
            await _persist_seen_guids(db, agent_id, url, updated)
        else:
            # Refresh last_polled_at even when nothing new — operators
            # use it to spot stale feeds.
            await _persist_seen_guids(db, agent_id, url, already_seen)

        results[url] = {
            "items": new_items,
            "total": len(new_items),
            "feed_title": fetched.get("feed_title"),
        }
    return results


def format_for_prompt(per_url: dict[str, dict]) -> Optional[str]:
    """Render the ``fetch_new_items`` result into a Markdown block the
    runner can prepend to the agent's user message. Returns ``None``
    when no URL produced any new items — caller should NOT inject an
    empty section, the agent shouldn't waste a turn on "nothing to do".
    """
    blocks: list[str] = []
    for url, payload in per_url.items():
        if payload.get("error"):
            blocks.append(
                f"- {url} → fetch error ({payload.get('reason') or 'unknown'})"
            )
            continue
        items = payload.get("items") or []
        if not items:
            continue
        blocks.append(f"### {payload.get('feed_title') or url}")
        blocks.append(f"_{len(items)} new item(s) since last poll — {url}_")
        for item in items:
            title = (item.get("title") or "").strip() or "(untitled)"
            link = item.get("link") or ""
            published = item.get("published") or ""
            line = f"- [{title}]({link})"
            if published:
                line += f" — {published}"
            blocks.append(line)
        blocks.append("")
    if not blocks:
        return None
    return "## RSS — new since last poll\n\n" + "\n".join(blocks).rstrip()
