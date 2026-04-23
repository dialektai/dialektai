"""
ClickHouse MCP endpoint tests — no real ClickHouse server needed.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

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


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_list_ch_connections_empty(client):
    r = client.get("/ch-connections")
    assert r.status_code == 200
    assert r.json() == []


def test_create_ch_connection(client):
    with patch("mcp_servers.clickhouse_mcp._save_password"):
        r = client.post("/ch-connections", json={
            "name": "Test CH DB", "host": "localhost",
            "database": "default", "username": "default", "password": "",
        })
    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    assert body["name"] == "Test CH DB"


def test_create_ch_missing_fields(client):
    r = client.post("/ch-connections", json={"name": "No DB"})
    assert r.status_code == 400


def test_get_ch_connection(client):
    with patch("mcp_servers.clickhouse_mcp._save_password"):
        create_r = client.post("/ch-connections", json={
            "name": "Get Test CH", "host": "localhost",
            "database": "default", "username": "default", "password": "",
        })
    conn_id = create_r.json()["id"]
    r = client.get(f"/ch-connections/{conn_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Get Test CH"
    assert "password" not in r.json()


def test_get_ch_not_found(client):
    r = client.get("/ch-connections/nonexistent")
    assert r.status_code == 404


def test_delete_ch_connection(client):
    with patch("mcp_servers.clickhouse_mcp._save_password"):
        create_r = client.post("/ch-connections", json={
            "name": "Delete Me CH", "host": "localhost",
            "database": "default", "username": "default", "password": "",
        })
    conn_id = create_r.json()["id"]
    with patch("mcp_servers.clickhouse_mcp._delete_password"):
        r = client.delete(f"/ch-connections/{conn_id}")
    assert r.status_code == 200
    assert client.get(f"/ch-connections/{conn_id}").status_code == 404


# ── SQL safety ────────────────────────────────────────────────────────────────

def test_ch_query_ddl_rejected(client):
    with patch("mcp_servers.clickhouse_mcp._save_password"):
        create_r = client.post("/ch-connections", json={
            "name": "DDL CH", "host": "localhost",
            "database": "default", "username": "default", "password": "",
        })
    conn_id = create_r.json()["id"]
    with patch("mcp_servers.clickhouse_mcp._load_password", return_value=""):
        r = client.post(f"/ch-connections/{conn_id}/query", json={"sql": "DROP TABLE t"})
    assert r.status_code == 422


def test_ch_query_system_rejected(client):
    """SYSTEM keyword is ClickHouse-specific dangerous op."""
    with patch("mcp_servers.clickhouse_mcp._save_password"):
        create_r = client.post("/ch-connections", json={
            "name": "SYS CH", "host": "localhost",
            "database": "default", "username": "default", "password": "",
        })
    conn_id = create_r.json()["id"]
    with patch("mcp_servers.clickhouse_mcp._load_password", return_value=""):
        r = client.post(f"/ch-connections/{conn_id}/query", json={"sql": "SYSTEM RELOAD DICTIONARIES"})
    assert r.status_code == 422


def test_ch_query_kill_rejected(client):
    with patch("mcp_servers.clickhouse_mcp._save_password"):
        create_r = client.post("/ch-connections", json={
            "name": "KILL CH", "host": "localhost",
            "database": "default", "username": "default", "password": "",
        })
    conn_id = create_r.json()["id"]
    with patch("mcp_servers.clickhouse_mcp._load_password", return_value=""):
        r = client.post(f"/ch-connections/{conn_id}/query", json={"sql": "KILL QUERY WHERE query_id='x'"})
    assert r.status_code == 422


def test_ch_query_empty_rejected(client):
    with patch("mcp_servers.clickhouse_mcp._save_password"):
        create_r = client.post("/ch-connections", json={
            "name": "Empty CH", "host": "localhost",
            "database": "default", "username": "default", "password": "",
        })
    conn_id = create_r.json()["id"]
    r = client.post(f"/ch-connections/{conn_id}/query", json={"sql": ""})
    assert r.status_code == 400


def test_ch_fkeys_always_empty(client):
    """ClickHouse has no FK constraints — endpoint always returns []."""
    with patch("mcp_servers.clickhouse_mcp._save_password"):
        create_r = client.post("/ch-connections", json={
            "name": "FK CH", "host": "localhost",
            "database": "default", "username": "default", "password": "",
        })
    conn_id = create_r.json()["id"]
    r = client.get(f"/ch-connections/{conn_id}/schemas/default/tables/events/fkeys")
    assert r.status_code == 200
    assert r.json() == []
