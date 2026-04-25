"""v0.26 commit 2 — persistence callback + live_status field.
Mentor pass-1 carry-over: HTTP transport pytest closes the only
ratified miss from commit 1."""
import asyncio
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import server as srv
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / ".dialekt"; d.mkdir()
        original = (srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR)
        srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = d / "x.db", d / "c.json", d
        srv._mcp_health._rows.clear()
        with TestClient(srv.app, raise_server_exceptions=True) as c:
            yield c
        srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = original


def _make(client, name, transport="stdio"):
    body = {"name": name, "transport": transport, "timeout_seconds": 30}
    body["command" if transport == "stdio" else "url"] = ["echo", "hi"] if transport == "stdio" else "https://x.test/mcp"
    return client.post("/mcp-servers", json=body).json()["id"]


def test_live_status_unknown_until_called(client):
    sid = _make(client, "a")
    assert client.get(f"/mcp-servers/{sid}").json()["live_status"] == "unknown"


@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_crashed_status_transport_agnostic(client, transport):
    """Mentor P2 carry-over: registry is transport-agnostic."""
    import server as srv
    sid = _make(client, f"s-{transport}", transport=transport)
    asyncio.new_event_loop().run_until_complete(
        srv._mcp_health.mark_crashed(f"s-{transport}", "MCPServerUnavailableError")
    )
    body = client.get(f"/mcp-servers/{sid}").json()
    assert body["live_status"] == "crashed"
    assert body["last_test_ok"] is False
    assert body["last_test_error"] == "live: MCPServerUnavailableError"


def test_recovery_clears_last_test_error(client):
    import server as srv
    sid = _make(client, "r")
    loop = asyncio.new_event_loop()
    loop.run_until_complete(srv._mcp_health.mark_crashed("r", "X"))
    loop.run_until_complete(srv._mcp_health.mark_healthy("r"))
    body = client.get(f"/mcp-servers/{sid}").json()
    assert body["last_test_ok"] is True
    assert body["last_test_error"] is None
    assert body["live_status"] == "healthy"
