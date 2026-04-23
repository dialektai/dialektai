"""
Agent import/export tests: POST /agents/import and GET /agents/{id}/export.
"""
import io
import tempfile
from pathlib import Path

import pytest

VALID_MANIFEST = """\
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"

metadata:
  id: "550e8400-e29b-41d4-a716-446655440000"
  name: "Test Import Agent"
  description: "Imported from YAML"
  version: "2.0.0"
  author:
    name: "Dias"
    email: "dias@dialekt.dev"
  created_at: "2026-04-22T10:00:00+06:00"
  updated_at: "2026-04-22T10:00:00+06:00"

model:
  preferred: "gemma3:12b"
  min_context_window: 8192
  requirements:
    min_ram_gb: 8
    min_vram_gb: 0
    recommended_ram_gb: 16
  parameters:
    temperature: 0.7
    top_p: 0.9
    max_tokens: 2048

system_prompt: |
  You are a test import agent. Be concise.

capabilities:
  groups:
    - filesystem_read
  exceptions: []

autonomy:
  recommended: "ask-before-write"
  max_allowed: "autonomous"

input:
  type: "chat"

output:
  format: "markdown"
  streaming: true
  destination:
    type: "notification"

trigger:
  type: "interactive"
"""

INVALID_MANIFEST = """\
spec_version: "1.0.1"
metadata:
  name: "Bad Agent"
"""


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


def test_import_valid_yaml(client):
    r = client.post(
        "/agents/import",
        files={"file": ("test.agent.yaml", io.BytesIO(VALID_MANIFEST.encode()), "application/x-yaml")},
    )
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    assert body["name"] == "Test Import Agent"
    assert isinstance(body["warnings"], list)


def test_import_creates_accessible_agent(client):
    r = client.post(
        "/agents/import",
        files={"file": ("test.agent.yaml", io.BytesIO(VALID_MANIFEST.encode()), "application/x-yaml")},
    )
    assert r.status_code == 200
    agent_id = r.json()["id"]

    get_r = client.get(f"/agents/{agent_id}")
    assert get_r.status_code == 200
    body = get_r.json()
    assert body["name"] == "Test Import Agent"
    assert "concise" in body["system_prompt"]
    assert body["version"] == "2.0.0"
    assert body["manifest_yaml"] is not None


def test_import_invalid_yaml_returns_422(client):
    r = client.post(
        "/agents/import",
        files={"file": ("bad.agent.yaml", io.BytesIO(INVALID_MANIFEST.encode()), "application/x-yaml")},
    )
    assert r.status_code == 422
    body = r.json()
    assert "errors" in body["detail"]
    assert len(body["detail"]["errors"]) > 0


def test_export_agent_with_manifest(client):
    import_r = client.post(
        "/agents/import",
        files={"file": ("test.agent.yaml", io.BytesIO(VALID_MANIFEST.encode()), "application/x-yaml")},
    )
    agent_id = import_r.json()["id"]

    r = client.get(f"/agents/{agent_id}/export")
    assert r.status_code == 200
    assert "yaml" in r.headers["content-type"]
    assert "Test Import Agent" in r.text
    assert "system_prompt" in r.text


def test_export_agent_without_manifest_returns_empty(client):
    create_r = client.post("/agents", json={
        "name": "Manual Agent",
        "system_prompt": "No manifest, created via API.",
    })
    agent_id = create_r.json()["id"]

    r = client.get(f"/agents/{agent_id}/export")
    assert r.status_code == 200
    # manifest_yaml is None → empty body
    assert r.text == ""


def test_export_not_found(client):
    r = client.get("/agents/nonexistent-id/export")
    assert r.status_code == 404
