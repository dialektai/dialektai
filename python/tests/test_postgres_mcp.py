"""
PostgreSQL MCP endpoint tests: connection CRUD + error handling.
Does NOT require a real PostgreSQL server — tests the REST layer only.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

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


# ── Connection CRUD ───────────────────────────────────────────────────────────

def test_list_connections_empty(client):
    r = client.get("/connections")
    assert r.status_code == 200
    assert r.json() == []


def test_create_connection_missing_required_fields(client):
    r = client.post("/connections", json={"name": "Test DB"})
    assert r.status_code == 400


def test_create_connection(client):
    with patch("mcp_servers.postgres_mcp._save_password") as mock_save:
        r = client.post("/connections", json={
            "name": "Test Analytics DB",
            "host": "localhost",
            "port": 5432,
            "database": "analytics",
            "username": "readonly",
            "password": "s3cr3t",
            "row_limit": 500,
        })
    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    assert body["name"] == "Test Analytics DB"
    mock_save.assert_called_once()


def test_list_connections_after_create(client):
    with patch("mcp_servers.postgres_mcp._save_password"):
        client.post("/connections", json={
            "name": "Second DB",
            "host": "db.example.com",
            "database": "prod",
            "username": "analyst",
            "password": "pw",
        })
    r = client.get("/connections")
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert "Second DB" in names


def test_get_connection(client):
    with patch("mcp_servers.postgres_mcp._save_password"):
        create_r = client.post("/connections", json={
            "name": "Get Test DB",
            "host": "localhost",
            "database": "testdb",
            "username": "user",
            "password": "pw",
        })
    conn_id = create_r.json()["id"]
    r = client.get(f"/connections/{conn_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Get Test DB"
    assert "password" not in r.json()  # password must not be returned


def test_get_connection_not_found(client):
    r = client.get("/connections/nonexistent-conn-id")
    assert r.status_code == 404


def test_patch_connection(client):
    with patch("mcp_servers.postgres_mcp._save_password"):
        create_r = client.post("/connections", json={
            "name": "Patchable DB",
            "host": "old-host.example.com",
            "database": "db",
            "username": "user",
            "password": "pw",
        })
    conn_id = create_r.json()["id"]

    with patch("mcp_servers.postgres_mcp._save_password"):
        r = client.patch(f"/connections/{conn_id}", json={
            "name": "Updated DB",
            "host": "new-host.example.com",
        })
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.get(f"/connections/{conn_id}")
    assert r.json()["name"] == "Updated DB"
    assert r.json()["host"] == "new-host.example.com"


def test_delete_connection(client):
    with patch("mcp_servers.postgres_mcp._save_password"):
        create_r = client.post("/connections", json={
            "name": "Delete Me",
            "host": "localhost",
            "database": "db",
            "username": "user",
            "password": "pw",
        })
    conn_id = create_r.json()["id"]

    with patch("mcp_servers.postgres_mcp._delete_password"):
        r = client.delete(f"/connections/{conn_id}")
    assert r.status_code == 200

    r = client.get(f"/connections/{conn_id}")
    assert r.status_code == 404


def test_delete_connection_not_found(client):
    r = client.delete("/connections/nonexistent-id")
    assert r.status_code == 404


# ── SQL tool endpoints — no real DB ───────────────────────────────────────────

def test_query_no_credentials(client):
    """Query without stored credentials returns 400, not 500."""
    with patch("mcp_servers.postgres_mcp._save_password"):
        create_r = client.post("/connections", json={
            "name": "No Creds DB",
            "host": "localhost",
            "database": "db",
            "username": "user",
            "password": "pw",
        })
    conn_id = create_r.json()["id"]

    # Simulate missing credentials
    with patch("mcp_servers.postgres_mcp._load_password", return_value=None):
        r = client.post(f"/connections/{conn_id}/query", json={"sql": "SELECT 1"})
    assert r.status_code in (400, 503)


def test_query_ddl_rejected(client):
    """DDL in query body returns 422 before any DB connection attempt."""
    with patch("mcp_servers.postgres_mcp._save_password"):
        create_r = client.post("/connections", json={
            "name": "DDL Test DB",
            "host": "localhost",
            "database": "db",
            "username": "user",
            "password": "pw",
        })
    conn_id = create_r.json()["id"]

    with patch("mcp_servers.postgres_mcp._load_password", return_value="pw"):
        r = client.post(f"/connections/{conn_id}/query", json={"sql": "DROP TABLE users"})
    assert r.status_code == 422
    assert "DDL" in r.text or "rejected" in r.text.lower()


def test_query_dml_rejected(client):
    with patch("mcp_servers.postgres_mcp._save_password"):
        create_r = client.post("/connections", json={
            "name": "DML Test DB",
            "host": "localhost",
            "database": "db",
            "username": "user",
            "password": "pw",
        })
    conn_id = create_r.json()["id"]

    with patch("mcp_servers.postgres_mcp._load_password", return_value="pw"):
        r = client.post(f"/connections/{conn_id}/query", json={"sql": "DELETE FROM users"})
    assert r.status_code == 422


def test_query_empty_sql(client):
    with patch("mcp_servers.postgres_mcp._save_password"):
        create_r = client.post("/connections", json={
            "name": "Empty SQL DB",
            "host": "localhost",
            "database": "db",
            "username": "user",
            "password": "pw",
        })
    conn_id = create_r.json()["id"]

    r = client.post(f"/connections/{conn_id}/query", json={"sql": ""})
    assert r.status_code == 400
