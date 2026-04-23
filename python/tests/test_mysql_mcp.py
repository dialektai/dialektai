"""
MySQL MCP endpoint tests — no real MySQL server needed.
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

def test_list_mysql_connections_empty(client):
    r = client.get("/mysql-connections")
    assert r.status_code == 200
    assert r.json() == []


def test_create_mysql_connection(client):
    with patch("mcp_servers.mysql_mcp._save_password"):
        r = client.post("/mysql-connections", json={
            "name": "Test MySQL DB", "host": "localhost",
            "database": "analytics", "username": "reader", "password": "s3cr3t",
        })
    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    assert body["name"] == "Test MySQL DB"


def test_create_mysql_missing_fields(client):
    r = client.post("/mysql-connections", json={"name": "Incomplete"})
    assert r.status_code == 400


def test_get_mysql_connection(client):
    with patch("mcp_servers.mysql_mcp._save_password"):
        create_r = client.post("/mysql-connections", json={
            "name": "Get Test MySQL", "host": "localhost",
            "database": "testdb", "username": "user", "password": "pw",
        })
    conn_id = create_r.json()["id"]
    r = client.get(f"/mysql-connections/{conn_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Get Test MySQL"
    assert "password" not in r.json()


def test_get_mysql_connection_not_found(client):
    r = client.get("/mysql-connections/nonexistent")
    assert r.status_code == 404


def test_patch_mysql_connection(client):
    with patch("mcp_servers.mysql_mcp._save_password"):
        create_r = client.post("/mysql-connections", json={
            "name": "Old Name", "host": "old-host",
            "database": "db", "username": "user", "password": "pw",
        })
    conn_id = create_r.json()["id"]
    with patch("mcp_servers.mysql_mcp._save_password"):
        r = client.patch(f"/mysql-connections/{conn_id}", json={"name": "New Name"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    r = client.get(f"/mysql-connections/{conn_id}")
    assert r.json()["name"] == "New Name"


def test_delete_mysql_connection(client):
    with patch("mcp_servers.mysql_mcp._save_password"):
        create_r = client.post("/mysql-connections", json={
            "name": "Delete Me", "host": "localhost",
            "database": "db", "username": "user", "password": "pw",
        })
    conn_id = create_r.json()["id"]
    with patch("mcp_servers.mysql_mcp._delete_password"):
        r = client.delete(f"/mysql-connections/{conn_id}")
    assert r.status_code == 200
    assert client.get(f"/mysql-connections/{conn_id}").status_code == 404


# ── SQL safety (mysql shares same checker) ────────────────────────────────────

def test_mysql_query_ddl_rejected(client):
    with patch("mcp_servers.mysql_mcp._save_password"):
        create_r = client.post("/mysql-connections", json={
            "name": "DDL Test", "host": "localhost",
            "database": "db", "username": "user", "password": "pw",
        })
    conn_id = create_r.json()["id"]
    with patch("mcp_servers.mysql_mcp._load_password", return_value="pw"):
        r = client.post(f"/mysql-connections/{conn_id}/query", json={"sql": "DROP TABLE users"})
    assert r.status_code == 422


def test_mysql_query_dml_rejected(client):
    with patch("mcp_servers.mysql_mcp._save_password"):
        create_r = client.post("/mysql-connections", json={
            "name": "DML Test", "host": "localhost",
            "database": "db", "username": "user", "password": "pw",
        })
    conn_id = create_r.json()["id"]
    with patch("mcp_servers.mysql_mcp._load_password", return_value="pw"):
        r = client.post(f"/mysql-connections/{conn_id}/query", json={"sql": "DELETE FROM users"})
    assert r.status_code == 422


def test_mysql_query_empty_rejected(client):
    with patch("mcp_servers.mysql_mcp._save_password"):
        create_r = client.post("/mysql-connections", json={
            "name": "Empty Test", "host": "localhost",
            "database": "db", "username": "user", "password": "pw",
        })
    conn_id = create_r.json()["id"]
    r = client.post(f"/mysql-connections/{conn_id}/query", json={"sql": ""})
    assert r.status_code == 400


def test_mysql_query_no_credentials(client):
    with patch("mcp_servers.mysql_mcp._save_password"):
        create_r = client.post("/mysql-connections", json={
            "name": "No Creds", "host": "localhost",
            "database": "db", "username": "user", "password": "pw",
        })
    conn_id = create_r.json()["id"]
    with patch("mcp_servers.mysql_mcp._load_password", return_value=None):
        r = client.post(f"/mysql-connections/{conn_id}/query", json={"sql": "SELECT 1"})
    assert r.status_code in (400, 503)
