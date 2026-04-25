"""Tests for GET /audit/log — read-side endpoint for the v0.25 MCP
audit dashboard. Covers mentor commit-1 self-check: filter combinations
incl. kind glob, 30-day cap, truncated boundary, malformed extra_json,
empty result, and that the query plan uses an index."""
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import server as srv
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / ".dialekt"
        d.mkdir()
        original = (srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR)
        srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = d / "x.db", d / "c.json", d
        with TestClient(srv.app, raise_server_exceptions=True) as c:
            yield c
        srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = original


def _post(client, **f):
    f.setdefault("kind", "mcp_tool_call"); f.setdefault("action", "x"); f.setdefault("result", "success")
    return client.post("/audit/log", json=f).json()["id"]


def test_empty_result_is_200_with_zero_rows(client):
    assert client.get("/audit/log").json() == {"rows": [], "truncated": False}


def test_kind_filter_exact_and_glob(client):
    _post(client, kind="mcp_tool_call", action="a")
    _post(client, kind="mcp_consent_decision", action="b", result="approved")
    _post(client, kind="sql_query", action="c")
    actions = lambda kind: {r["action"] for r in client.get("/audit/log", params={"kind": kind}).json()["rows"]}
    assert actions("mcp_tool_call") == {"a"}
    assert actions("mcp_*") == {"a", "b"}


def test_since_30day_cap_silently_lifts(client):
    _post(client)
    too_old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    assert len(client.get("/audit/log", params={"since": too_old}).json()["rows"]) == 1


def test_since_garbage_returns_400(client):
    assert client.get("/audit/log", params={"since": "nope"}).status_code == 400


def test_truncated_flag(client):
    for i in range(7):
        _post(client, action=f"r{i}")
    body5 = client.get("/audit/log", params={"limit": 5}).json()
    body100 = client.get("/audit/log", params={"limit": 100}).json()
    assert (len(body5["rows"]), body5["truncated"]) == (5, True)
    assert (len(body100["rows"]), body100["truncated"]) == (7, False)


def test_malformed_extra_json_is_null_not_500(client):
    import server as srv
    async def insert():
        await srv.db.execute(
            "INSERT INTO audit_log(kind, action, result, extra_json) VALUES('mcp_tool_call','bad','success',?)",
            ("{not-json,",),
        )
        await srv.db.commit()
    asyncio.new_event_loop().run_until_complete(insert())
    bad = next(r for r in client.get("/audit/log").json()["rows"] if r["action"] == "bad")
    assert bad["extra"] is None


def test_query_plan_uses_ts_index(client):
    import server as srv
    async def explain():
        cur = await srv.db.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM audit_log WHERE ts >= ? LIMIT 10",
            ("2026-01-01 00:00:00",),
        )
        return " ".join([row[3] async for row in cur])
    plan = asyncio.new_event_loop().run_until_complete(explain())
    assert "idx_audit_log_ts" in plan or "USING INDEX" in plan, plan
