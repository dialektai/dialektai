"""
Tests for new server.py endpoints:
- GET /ollama/check
- Agent binding CRUD (GET/POST/DELETE /agents/{id}/binding)
- License endpoints (GET /license/status, POST /license/save, POST /license/trial)
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


# ── /ollama/check ──────────────────────────────────────────────────────────────

def test_ollama_check_returns_expected_fields(client):
    r = client.get("/ollama/check")
    assert r.status_code == 200
    body = r.json()
    assert "installed" in body
    assert "running" in body
    assert "version" in body
    assert "install_url" in body
    assert "platform" in body


def test_ollama_check_install_url_format(client):
    r = client.get("/ollama/check")
    url = r.json()["install_url"]
    assert url.startswith("https://ollama.com/download/")


def test_ollama_check_installed_is_bool(client):
    body = client.get("/ollama/check").json()
    assert isinstance(body["installed"], bool)
    assert isinstance(body["running"], bool)


def test_ollama_check_platform_field(client):
    body = client.get("/ollama/check").json()
    assert body["platform"] in ("darwin", "linux", "windows")


# ── Agent binding endpoints ────────────────────────────────────────────────────

def _create_agent(client, name="Binding Test Agent"):
    r = client.post("/agents", json={
        "name": name,
        "description": "test",
        "system_prompt": "You are a test agent. CONN={{connection_id}}",
    })
    assert r.status_code == 201
    return r.json()["id"]


def test_get_binding_no_binding_returns_null(client):
    agent_id = _create_agent(client, "Binding Agent 1")
    r = client.get(f"/agents/{agent_id}/binding")
    assert r.status_code == 200
    body = r.json()
    assert body["connection_id"] is None
    assert body["connection_type"] is None


def test_set_binding_returns_ok(client):
    agent_id = _create_agent(client, "Binding Agent 2")
    r = client.post(f"/agents/{agent_id}/binding", json={
        "connection_id": "conn-xyz",
        "connection_type": "postgres",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["connection_id"] == "conn-xyz"


def test_get_binding_after_set(client):
    agent_id = _create_agent(client, "Binding Agent 3")
    client.post(f"/agents/{agent_id}/binding", json={"connection_id": "c2", "connection_type": "mysql"})
    r = client.get(f"/agents/{agent_id}/binding")
    assert r.json()["connection_id"] == "c2"
    assert r.json()["connection_type"] == "mysql"


def test_overwrite_binding(client):
    agent_id = _create_agent(client, "Binding Agent 4")
    client.post(f"/agents/{agent_id}/binding", json={"connection_id": "c1", "connection_type": "postgres"})
    client.post(f"/agents/{agent_id}/binding", json={"connection_id": "c2", "connection_type": "clickhouse"})
    r = client.get(f"/agents/{agent_id}/binding")
    assert r.json()["connection_id"] == "c2"
    assert r.json()["connection_type"] == "clickhouse"


def test_delete_binding(client):
    agent_id = _create_agent(client, "Binding Agent 5")
    client.post(f"/agents/{agent_id}/binding", json={"connection_id": "c3", "connection_type": "postgres"})
    client.delete(f"/agents/{agent_id}/binding")
    r = client.get(f"/agents/{agent_id}/binding")
    assert r.json()["connection_id"] is None


def test_binding_on_nonexistent_agent_returns_404(client):
    r = client.get("/agents/nonexistent-id/binding")
    assert r.status_code == 404


def test_set_binding_null_connection_id_removes_binding(client):
    agent_id = _create_agent(client, "Binding Agent 6")
    client.post(f"/agents/{agent_id}/binding", json={"connection_id": "c4", "connection_type": "postgres"})
    client.post(f"/agents/{agent_id}/binding", json={"connection_id": None})
    r = client.get(f"/agents/{agent_id}/binding")
    assert r.json()["connection_id"] is None


# ── License endpoints ──────────────────────────────────────────────────────────

def test_license_status_no_license(client):
    r = client.get("/license/status")
    assert r.status_code == 200
    body = r.json()
    assert "valid" in body
    assert "license_key" in body
    assert "trial" in body


def test_license_save_stores_key(client):
    r = client.post("/license/save", json={"license_key": "dialekt_testkey123"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # Status should now show the key
    status = client.get("/license/status").json()
    assert status["license_key"] == "dialekt_testkey123"
    assert status["valid"] is True


def test_license_save_stores_tenant(client):
    r = client.post("/license/save", json={
        "license_key": "dialekt_tenantkey",
        "tenant": {"company_name": "ACME Corp", "plan": "team", "seats_limit": 10},
    })
    assert r.status_code == 200
    status = client.get("/license/status").json()
    assert status["tenant"]["company_name"] == "ACME Corp"


def test_license_trial_starts(client):
    r = client.post("/license/trial")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["expires_in_days"] == 30


def test_license_status_after_trial(client):
    client.post("/license/trial")
    status = client.get("/license/status").json()
    assert status["trial"] is True
    assert status["trial_valid"] is True
