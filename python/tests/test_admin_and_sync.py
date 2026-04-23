"""
Tests for GET /admin/stats and /sync/* endpoints.
"""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import server as srv

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)
        original_db   = srv.DB_PATH
        original_cfg  = srv.SETTINGS_FILE
        original_ddir = srv.DIALEKT_DIR
        srv.DB_PATH       = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR   = tmp_dir
        with TestClient(srv.app, raise_server_exceptions=True) as c:
            yield c
        srv.DB_PATH       = original_db
        srv.SETTINGS_FILE = original_cfg
        srv.DIALEKT_DIR   = original_ddir


# ── Admin stats ───────────────────────────────────────────────────────────────

def test_admin_stats_returns_expected_fields(client):
    r = client.get("/admin/stats")
    assert r.status_code == 200
    body = r.json()
    assert "sessions" in body
    assert "messages" in body
    assert "agents" in body
    assert "connections" in body
    assert "db_size_bytes" in body
    assert "agents_detail" in body


def test_admin_stats_agents_detail_is_list(client):
    r = client.get("/admin/stats")
    assert isinstance(r.json()["agents_detail"], list)


def test_admin_stats_counts_seeded_agent(client):
    r = client.get("/admin/stats")
    # Migration seeds "General Assistant" so agents >= 1
    assert r.json()["agents"] >= 1


def test_admin_stats_db_size_positive(client):
    r = client.get("/admin/stats")
    assert r.json()["db_size_bytes"] > 0


def test_admin_stats_agents_detail_has_session_count(client):
    r = client.get("/admin/stats")
    for a in r.json()["agents_detail"]:
        assert "name" in a
        assert "status" in a
        assert "session_count" in a


# ── Cloud sync — unconfigured ─────────────────────────────────────────────────

def test_sync_status_unconfigured(client):
    r = client.get("/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert "message" in body


def test_sync_push_without_key_returns_402(client):
    r = client.post("/sync/push")
    assert r.status_code == 402


def test_sync_pull_without_key_returns_402(client):
    r = client.post("/sync/pull")
    assert r.status_code == 402


def test_sync_configure_requires_api_key(client):
    r = client.post("/sync/configure", json={})
    assert r.status_code == 400


def test_sync_configure_saves_key(client):
    r = client.post("/sync/configure", json={"api_key": "dialekt_test_key_12345"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_sync_status_after_configure(client):
    client.post("/sync/configure", json={"api_key": "dialekt_key_abc"})
    r = client.get("/sync/status")
    body = r.json()
    assert body["enabled"] is True
    assert "api_key_prefix" in body


def test_sync_push_with_key_returns_ok(client):
    client.post("/sync/configure", json={"api_key": "dialekt_key_push"})
    r = client.post("/sync/push")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_sync_pull_with_key_returns_ok(client):
    client.post("/sync/configure", json={"api_key": "dialekt_key_pull"})
    r = client.post("/sync/pull")
    assert r.status_code == 200
    assert r.json()["ok"] is True
