"""
Agent CRUD API tests: GET/POST/PATCH/DELETE /agents and mode config.
Uses FastAPI TestClient with a temp SQLite DB.
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


def test_list_agents_initially_has_general_assistant(client):
    """Migration seeds General Assistant on a fresh DB."""
    r = client.get("/agents")
    assert r.status_code == 200
    agents = r.json()
    assert len(agents) >= 1
    names = [a["name"] for a in agents]
    assert "General Assistant" in names


def test_create_agent(client):
    r = client.post("/agents", json={
        "name": "SQL Analyst",
        "description": "Runs SQL queries",
        "system_prompt": "You are a SQL expert.",
        "version": "1.0.0",
    })
    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    assert body["name"] == "SQL Analyst"


def test_create_agent_requires_name(client):
    r = client.post("/agents", json={"description": "no name"})
    assert r.status_code == 400


def test_get_agent(client):
    create_r = client.post("/agents", json={
        "name": "Fetch Test Agent",
        "system_prompt": "You fetch things.",
    })
    agent_id = create_r.json()["id"]

    r = client.get(f"/agents/{agent_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == agent_id
    assert body["name"] == "Fetch Test Agent"
    assert body["status"] == "draft"


def test_get_agent_not_found(client):
    r = client.get("/agents/nonexistent-00000000-0000")
    assert r.status_code == 404


def test_patch_agent(client):
    create_r = client.post("/agents", json={
        "name": "Patch Me",
        "system_prompt": "Original prompt.",
    })
    agent_id = create_r.json()["id"]

    r = client.patch(f"/agents/{agent_id}", json={
        "name": "Patched Agent",
        "system_prompt": "Updated prompt.",
        "status": "published",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.get(f"/agents/{agent_id}")
    body = r.json()
    assert body["name"] == "Patched Agent"
    assert body["status"] == "published"
    assert body["system_prompt"] == "Updated prompt."


def test_patch_agent_not_found(client):
    r = client.patch("/agents/nonexistent", json={"name": "X"})
    assert r.status_code == 404


def test_delete_agent(client):
    create_r = client.post("/agents", json={"name": "To Delete", "system_prompt": "bye"})
    agent_id = create_r.json()["id"]

    r = client.delete(f"/agents/{agent_id}")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.get(f"/agents/{agent_id}")
    assert r.status_code == 404


def test_delete_agent_not_found(client):
    r = client.delete("/agents/nonexistent")
    assert r.status_code == 404


def test_mode_default_is_builder(client):
    r = client.get("/config/mode")
    assert r.status_code == 200
    assert r.json()["mode"] == "builder"


def test_mode_switch(client):
    r = client.post("/config/mode", json={"mode": "user"})
    assert r.status_code == 200
    assert r.json()["mode"] == "user"

    r = client.get("/config/mode")
    assert r.json()["mode"] == "user"

    # Reset
    client.post("/config/mode", json={"mode": "builder"})


def test_mode_invalid_value(client):
    r = client.post("/config/mode", json={"mode": "superadmin"})
    assert r.status_code == 400
