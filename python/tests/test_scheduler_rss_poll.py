"""Tests for ``dialekt.scheduler.rss_poll``.

Mocks the underlying ``rss_tool._fetch_and_parse`` so no live HTTP
happens, and exercises the diff/persist logic against an in-memory
aiosqlite database with the production ``agent_rss_state`` schema.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import aiosqlite
import pytest

from dialekt.scheduler import rss_poll
from dialekt.scheduler.rss_poll import (
    MAX_REMEMBERED_GUIDS,
    fetch_new_items,
    format_for_prompt,
)
from dialekt.mcp.server.tools import rss as rss_tool


AGENT_RSS_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_rss_state (
    agent_id        TEXT NOT NULL,
    url             TEXT NOT NULL,
    seen_guids      TEXT NOT NULL,
    last_polled_at  TEXT NOT NULL,
    PRIMARY KEY (agent_id, url)
);
"""


async def _connect() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    await db.executescript(AGENT_RSS_STATE_SCHEMA)
    await db.commit()
    return db


def _items(*guids: str) -> dict:
    return {
        "feed_title": "Test feed",
        "items": [
            {
                "guid": g,
                "title": f"Item {g}",
                "link": f"https://example.com/{g}",
                "summary": "",
                "published": "2026-04-28T00:00:00Z",
                "author": None,
            }
            for g in guids
        ],
    }


@pytest.fixture
def mock_fetch(monkeypatch):
    """Replace rss_tool._fetch_and_parse with a queue-based stub.

    Tests push expected (url, return) pairs and the stub pops them in
    order, asserting the call site asks for them in the expected
    sequence.
    """
    queue: dict[str, list[Any]] = {}

    def _stub(url, *, headers=None, timeout=30.0, max_items=50):
        if url not in queue or not queue[url]:
            raise AssertionError(f"unexpected fetch for {url!r}")
        result = queue[url].pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(rss_tool, "_fetch_and_parse", _stub)
    return queue


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------


def test_first_poll_returns_all_items(mock_fetch):
    async def run():
        db = await _connect()
        url = "https://example.com/feed"
        mock_fetch[url] = [_items("a", "b", "c")]
        out = await fetch_new_items(db, "agent-1", [url])
        assert out[url]["total"] == 3
        guids = [i["guid"] for i in out[url]["items"]]
        assert guids == ["a", "b", "c"]
        # Persistence happened.
        async with db.execute(
            "SELECT seen_guids FROM agent_rss_state WHERE agent_id = ? AND url = ?",
            ("agent-1", url),
        ) as cur:
            row = await cur.fetchone()
        assert json.loads(row[0]) == ["a", "b", "c"]
        await db.close()

    asyncio.run(run())


def test_subsequent_poll_only_returns_new(mock_fetch):
    async def run():
        db = await _connect()
        url = "https://example.com/feed"
        # First call: a, b, c — all new.
        mock_fetch[url] = [_items("a", "b", "c"), _items("a", "b", "c", "d", "e")]
        await fetch_new_items(db, "agent-1", [url])
        # Second call: d, e are new.
        out = await fetch_new_items(db, "agent-1", [url])
        guids = [i["guid"] for i in out[url]["items"]]
        assert guids == ["d", "e"]
        await db.close()

    asyncio.run(run())


def test_no_new_items_returns_empty(mock_fetch):
    async def run():
        db = await _connect()
        url = "https://example.com/feed"
        mock_fetch[url] = [_items("a", "b"), _items("a", "b")]
        await fetch_new_items(db, "agent-1", [url])
        out = await fetch_new_items(db, "agent-1", [url])
        assert out[url]["items"] == []
        assert out[url]["total"] == 0
        await db.close()

    asyncio.run(run())


def test_state_is_per_agent(mock_fetch):
    async def run():
        db = await _connect()
        url = "https://example.com/feed"
        # Same URL, two agents — second agent should see all items
        # despite the first agent having already polled.
        mock_fetch[url] = [_items("a", "b"), _items("a", "b")]
        await fetch_new_items(db, "agent-1", [url])
        out = await fetch_new_items(db, "agent-2", [url])
        assert [i["guid"] for i in out[url]["items"]] == ["a", "b"]
        await db.close()

    asyncio.run(run())


def test_multiple_urls_are_independent(mock_fetch):
    async def run():
        db = await _connect()
        a = "https://example.com/a"
        b = "https://example.com/b"
        mock_fetch[a] = [_items("a1", "a2")]
        mock_fetch[b] = [_items("b1")]
        out = await fetch_new_items(db, "agent-1", [a, b])
        assert {i["guid"] for i in out[a]["items"]} == {"a1", "a2"}
        assert {i["guid"] for i in out[b]["items"]} == {"b1"}
        await db.close()

    asyncio.run(run())


def test_duplicate_urls_collapsed(mock_fetch):
    async def run():
        db = await _connect()
        url = "https://example.com/feed"
        mock_fetch[url] = [_items("a")]
        # Same URL twice in the input list — should fetch only once.
        out = await fetch_new_items(db, "agent-1", [url, url])
        assert out[url]["total"] == 1
        # The mock asserts no second pop happened (queue is now empty).
        assert mock_fetch[url] == []
        await db.close()

    asyncio.run(run())


def test_items_without_guid_are_dropped(mock_fetch):
    async def run():
        db = await _connect()
        url = "https://example.com/feed"
        mock_fetch[url] = [
            {
                "feed_title": "f",
                "items": [
                    {"guid": None, "title": "ghost", "link": None, "published": None},
                    {"guid": "real", "title": "ok", "link": None, "published": None},
                ],
            }
        ]
        out = await fetch_new_items(db, "agent-1", [url])
        guids = [i["guid"] for i in out[url]["items"]]
        assert guids == ["real"]
        await db.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_http_error_does_not_persist_state(mock_fetch):
    async def run():
        db = await _connect()
        url = "https://example.com/feed"
        mock_fetch[url] = [
            {"error": True, "reason": "http_error", "status": 503},
            _items("a"),
        ]
        # First call: HTTP 503 → no items, no persistence.
        out1 = await fetch_new_items(db, "agent-1", [url])
        assert out1[url]["error"] is True
        assert out1[url]["items"] == []
        async with db.execute(
            "SELECT COUNT(*) FROM agent_rss_state WHERE agent_id=? AND url=?",
            ("agent-1", url),
        ) as cur:
            count = (await cur.fetchone())[0]
        assert count == 0

        # Second call recovers — all items are still considered new.
        out2 = await fetch_new_items(db, "agent-1", [url])
        assert out2[url]["total"] == 1
        await db.close()

    asyncio.run(run())


def test_fetch_crash_recorded_and_isolated(mock_fetch):
    async def run():
        db = await _connect()
        a = "https://example.com/a"
        b = "https://example.com/b"
        mock_fetch[a] = [RuntimeError("simulated explosion")]
        mock_fetch[b] = [_items("x")]
        out = await fetch_new_items(db, "agent-1", [a, b])
        assert out[a]["error"] is True
        assert out[a]["reason"] == "fetch_crashed"
        # Other URL still got processed.
        assert out[b]["total"] == 1
        await db.close()

    asyncio.run(run())


def test_seen_guids_capped(mock_fetch):
    async def run():
        db = await _connect()
        url = "https://example.com/feed"
        # Pre-seed with already-saved guids (one above cap).
        excess = [f"old-{i}" for i in range(MAX_REMEMBERED_GUIDS + 5)]
        await db.execute(
            "INSERT INTO agent_rss_state (agent_id, url, seen_guids, last_polled_at)"
            " VALUES (?, ?, ?, ?)",
            ("agent-1", url, json.dumps(excess), "2026-04-28T00:00:00Z"),
        )
        await db.commit()

        mock_fetch[url] = [_items("new-a", "new-b")]
        await fetch_new_items(db, "agent-1", [url])

        async with db.execute(
            "SELECT seen_guids FROM agent_rss_state WHERE agent_id=? AND url=?",
            ("agent-1", url),
        ) as cur:
            row = await cur.fetchone()
        guids = json.loads(row[0])
        assert len(guids) == MAX_REMEMBERED_GUIDS
        # Newest guids retained.
        assert guids[-1] == "new-b"
        assert guids[-2] == "new-a"
        # Oldest guids dropped.
        assert "old-0" not in guids
        await db.close()

    asyncio.run(run())


def test_unparseable_seen_guids_treated_as_empty(mock_fetch):
    async def run():
        db = await _connect()
        url = "https://example.com/feed"
        # Garbage in the column → load gracefully empties.
        await db.execute(
            "INSERT INTO agent_rss_state (agent_id, url, seen_guids, last_polled_at)"
            " VALUES (?, ?, ?, ?)",
            ("agent-1", url, "not-json{", "2026-04-28T00:00:00Z"),
        )
        await db.commit()

        mock_fetch[url] = [_items("a")]
        out = await fetch_new_items(db, "agent-1", [url])
        # Item is treated as new since the persisted state was unreadable.
        assert out[url]["total"] == 1
        await db.close()

    asyncio.run(run())


def test_empty_url_skipped(mock_fetch):
    async def run():
        db = await _connect()
        out = await fetch_new_items(db, "agent-1", ["", None])
        assert out == {}
        await db.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# format_for_prompt
# ---------------------------------------------------------------------------


def test_format_for_prompt_returns_none_when_empty():
    assert format_for_prompt({}) is None
    assert format_for_prompt({"u": {"items": []}}) is None


def test_format_for_prompt_renders_items():
    payload = {
        "https://example.com/feed": {
            "feed_title": "Sample feed",
            "items": [
                {
                    "guid": "1",
                    "title": "First",
                    "link": "https://example.com/1",
                    "published": "2026-04-28T09:00:00Z",
                },
            ],
            "total": 1,
        }
    }
    out = format_for_prompt(payload)
    assert out is not None
    assert "RSS — new since last poll" in out
    assert "Sample feed" in out
    assert "[First](https://example.com/1)" in out


def test_format_for_prompt_records_errors():
    payload = {
        "https://example.com/feed": {
            "error": True,
            "reason": "timeout",
            "items": [],
        }
    }
    out = format_for_prompt(payload)
    # Error-only payload also surfaces — operator wants to know.
    assert out is not None
    assert "fetch error (timeout)" in out
