"""
Tests for POST /agents/import-yaml — JSON-body manifest import used by the wizard.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

VALID_MANIFEST = """
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"

metadata:
  id: "da727a9f-fc98-4516-baf9-dac4e820fdb0"
  name: "Test Wizard Agent"
  description: "Created via wizard endpoint test"
  version: "1.0.0"
  tags: []
  language: en
  author:
    name: "test"
    email: "test@example.com"
  created_at: "2026-04-22T00:00:00+06:00"
  updated_at: "2026-04-22T00:00:00+06:00"

model:
  preferred: "llama3.2:3b"
  min_context_window: 8192
  requirements:
    min_ram_gb: 8
    min_vram_gb: 0
    recommended_ram_gb: 16
  parameters:
    temperature: 0.7
    top_p: 0.95
    max_tokens: 4096

system_prompt: |
  You are a helpful assistant.

capabilities:
  groups: []
  exceptions: []

autonomy:
  recommended: "ask-before-write"
  max_allowed: "ask-before-write"

input:
  type: "chat"

output:
  format: "markdown"
  streaming: true
  destination:
    type: "notification"

trigger:
  type: "interactive"
""".strip()

# Alternate manifests with different UUIDs for tests that create multiple agents
_M2 = VALID_MANIFEST.replace('da727a9f-fc98-4516-baf9-dac4e820fdb0', '4367740e-7694-46e7-acb2-21bd5b20892f')
_M3 = VALID_MANIFEST.replace('da727a9f-fc98-4516-baf9-dac4e820fdb0', 'f56023f5-e7ea-4070-99f0-2465695d63d9')
_M4 = VALID_MANIFEST.replace('da727a9f-fc98-4516-baf9-dac4e820fdb0', 'c9b03d47-43f6-4957-bbe6-3ebfade51288')
_M5 = VALID_MANIFEST.replace('da727a9f-fc98-4516-baf9-dac4e820fdb0', 'c5c1a939-6e99-4a38-a7a2-976718dcbcbc')


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


def test_import_yaml_creates_draft_by_default(client):
    r = client.post("/agents/import-yaml", json={"manifest_yaml": VALID_MANIFEST})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "id" in body
    assert body["name"] == "Test Wizard Agent"
    # Verify it's in the agents list
    agents = client.get("/agents").json()
    ids = [a["id"] for a in agents]
    assert body["id"] in ids


def test_import_yaml_published_status(client):
    r = client.post("/agents/import-yaml", json={
        "manifest_yaml": _M2,
        "status": "published",
    })
    assert r.status_code == 201
    agent_id = r.json()["id"]
    agent = client.get(f"/agents/{agent_id}").json()
    assert agent["status"] == "published"


def test_import_yaml_draft_status(client):
    r = client.post("/agents/import-yaml", json={
        "manifest_yaml": _M3,
        "status": "draft",
    })
    assert r.status_code == 201
    agent_id = r.json()["id"]
    agent = client.get(f"/agents/{agent_id}").json()
    assert agent["status"] == "draft"


def test_import_yaml_missing_body(client):
    r = client.post("/agents/import-yaml", json={})
    assert r.status_code == 400


def test_import_yaml_empty_string(client):
    r = client.post("/agents/import-yaml", json={"manifest_yaml": ""})
    assert r.status_code == 400


def test_import_yaml_invalid_manifest(client):
    r = client.post("/agents/import-yaml", json={"manifest_yaml": "not: valid: manifest: yaml: !!!"})
    assert r.status_code == 422


def test_import_yaml_returns_warnings_list(client):
    r = client.post("/agents/import-yaml", json={"manifest_yaml": VALID_MANIFEST})
    assert r.status_code == 201
    assert "warnings" in r.json()
    assert isinstance(r.json()["warnings"], list)


def test_import_yaml_invalid_status_coerced_to_draft(client):
    r = client.post("/agents/import-yaml", json={
        "manifest_yaml": _M4,
        "status": "superadmin",
    })
    assert r.status_code == 201
    agent_id = r.json()["id"]
    agent = client.get(f"/agents/{agent_id}").json()
    assert agent["status"] == "draft"
