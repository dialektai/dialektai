"""Tests for the bulk export/import endpoints (v0.21 commit 3).

Covers:
- GET /mcp-servers/export — JSON shape, no secret leakage, per-entry
  schema_version, Content-Disposition header for direct download
- POST /mcp-servers/import — happy path, name collision skip,
  atomic-on-validation-failure (mentor ruling §7.4),
  forward-compat schema_version handling, secrets_needed reporting
- Round-trip: create → export → wipe DB → import → state restored
"""
import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def keyring_store(monkeypatch):
    """In-memory keyring stub (matches test_mcp_servers_crud pattern)."""
    store: dict[str, str] = {}
    monkeypatch.setattr("server.set_secret", lambda name, value: store.update({name: value}) or None)
    monkeypatch.setattr("server.get_secret", store.get)
    monkeypatch.setattr("server.delete_secret", lambda name: store.pop(name, None) or None)
    return store


@pytest.fixture
def client(keyring_store):
    from fastapi.testclient import TestClient
    import server as srv
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)
        original = (srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR)
        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR = tmp_dir
        with TestClient(srv.app, raise_server_exceptions=True) as c:
            yield c
        srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = original


def _create(client, name, **overrides):
    payload = {
        "name": name,
        "transport": "stdio",
        "command": ["echo", "ok"],
        **overrides,
    }
    r = client.post("/mcp-servers", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# ── Export ───────────────────────────────────────────────────────────────


def test_export_empty_db_returns_empty_servers(client):
    r = client.get("/mcp-servers/export")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert body["servers"] == []
    assert "exported_at" in body
    # exported_by must be omitted per mentor ruling §7.3 (privacy-first)
    assert "exported_by" not in body


def test_export_includes_per_entry_schema_version(client, keyring_store):
    _create(client, "github", env_refs={"GITHUB_TOKEN": "github_token"},
            env_secrets=[{"ref": "github_token", "value": "secret_value"}])
    r = client.get("/mcp-servers/export")
    body = r.json()
    assert len(body["servers"]) == 1
    entry = body["servers"][0]
    # Mentor P1: per-entry schema_version for forward compat
    assert entry["schema_version"] == 1


def test_export_response_never_leaks_secret_values(client, keyring_store):
    """Belt-and-suspenders regression: a stored secret value must not
    appear anywhere in the export response body. Same paranoid spirit
    as test_response_never_leaks_secret_value in the CRUD suite."""
    plaintext = "GHP_PLAINTEXT_DO_NOT_LEAK_AABBCCDDEE"
    _create(client, "leak-test",
            env_refs={"GITHUB_TOKEN": "github_token"},
            env_secrets=[{"ref": "github_token", "value": plaintext}])
    r = client.get("/mcp-servers/export")
    assert plaintext not in r.text


def test_export_serves_attachment_disposition(client):
    r = client.get("/mcp-servers/export")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "dialekt-mcp-servers.json" in cd


# ── Import ───────────────────────────────────────────────────────────────


def test_import_empty_bundle_no_op(client):
    r = client.post("/mcp-servers/import", json={"version": 1, "servers": []})
    assert r.status_code == 200
    body = r.json()
    assert body == {"imported": [], "skipped": [], "secrets_needed": []}


def test_import_happy_path_single_server(client, keyring_store):
    bundle = {
        "version": 1,
        "servers": [{
            "schema_version": 1,
            "name": "imported-gh",
            "transport": "stdio",
            "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
            "env_refs": {"GITHUB_TOKEN": "github_token"},
            "cwd": None, "url": None, "auth_type": None, "auth_ref": None,
            "timeout_seconds": 30,
        }],
    }
    r = client.post("/mcp-servers/import", json=bundle)
    assert r.status_code == 200
    body = r.json()
    assert len(body["imported"]) == 1
    assert body["imported"][0]["name"] == "imported-gh"
    assert body["skipped"] == []
    # secrets_needed surfaces every (server, env_var, ref) tuple
    assert {"server": "imported-gh", "env_var": "GITHUB_TOKEN",
            "ref": "github_token"} in body["secrets_needed"]


def test_import_skips_name_collisions(client, keyring_store):
    _create(client, "existing")
    bundle = {
        "version": 1,
        "servers": [
            {"schema_version": 1, "name": "existing", "transport": "stdio",
             "command": ["echo"], "env_refs": {}, "timeout_seconds": 30},
            {"schema_version": 1, "name": "fresh", "transport": "stdio",
             "command": ["echo"], "env_refs": {}, "timeout_seconds": 30},
        ],
    }
    r = client.post("/mcp-servers/import", json=bundle)
    body = r.json()
    assert "existing" in body["skipped"]
    assert [x["name"] for x in body["imported"]] == ["fresh"]


def test_import_atomic_on_validation_failure(client, keyring_store):
    """Mentor ruling §7.4: any single Pydantic validation failure
    aborts the WHOLE import — no partial state."""
    bundle = {
        "version": 1,
        "servers": [
            {"schema_version": 1, "name": "valid-1", "transport": "stdio",
             "command": ["echo"], "env_refs": {}, "timeout_seconds": 30},
            # Bad: stdio transport but no command
            {"schema_version": 1, "name": "invalid", "transport": "stdio",
             "env_refs": {}, "timeout_seconds": 30},
            {"schema_version": 1, "name": "valid-2", "transport": "stdio",
             "command": ["echo"], "env_refs": {}, "timeout_seconds": 30},
        ],
    }
    r = client.post("/mcp-servers/import", json=bundle)
    assert r.status_code == 422
    # Verify: NEITHER valid-1 NOR valid-2 landed in the DB
    listed = client.get("/mcp-servers").json()
    names = {s["name"] for s in listed}
    assert "valid-1" not in names
    assert "valid-2" not in names


def test_import_rejects_bad_schema_version(client):
    bundle = {"version": 1, "servers": [
        {"schema_version": 99, "name": "futureproof", "transport": "stdio",
         "command": ["echo"], "env_refs": {}, "timeout_seconds": 30},
    ]}
    r = client.post("/mcp-servers/import", json=bundle)
    assert r.status_code == 422
    assert "schema_version" in r.text


def test_import_rejects_bad_envelope_version(client):
    r = client.post("/mcp-servers/import", json={"version": 99, "servers": []})
    assert r.status_code == 422


def test_import_rejects_non_object_body(client):
    """FastAPI's auto-deserialization rejects non-dict bodies with 422
    before our handler runs. Either 400 (our explicit guard) or 422
    (FastAPI's Pydantic layer) is acceptable."""
    r = client.post("/mcp-servers/import", json=[])
    assert r.status_code in (400, 422)


def test_import_rejects_missing_servers_field(client):
    r = client.post("/mcp-servers/import", json={"version": 1})
    assert r.status_code in (400, 422)


# ── Round-trip ───────────────────────────────────────────────────────────


def test_export_then_import_round_trip(client, keyring_store):
    """Create 2 servers → export → wipe DB → import → confirm shape +
    secrets_needed enumerates every credential."""
    _create(client, "alpha", env_refs={"X": "x_ref"},
            env_secrets=[{"ref": "x_ref", "value": "X_PLAINTEXT"}])
    _create(client, "beta", transport="http", url="https://example.com/mcp",
            command=None, auth_type="bearer", auth_token="BETA_BEARER",
            auth_ref="auth_token")
    # Export
    bundle = client.get("/mcp-servers/export").json()
    assert {s["name"] for s in bundle["servers"]} == {"alpha", "beta"}
    # Wipe DB
    for s in client.get("/mcp-servers").json():
        client.delete(f"/mcp-servers/{s['id']}")
    assert client.get("/mcp-servers").json() == []
    # Import
    r = client.post("/mcp-servers/import", json=bundle)
    body = r.json()
    assert {x["name"] for x in body["imported"]} == {"alpha", "beta"}
    assert body["skipped"] == []
    # secrets_needed reports both credentials
    refs = {(s["server"], s["ref"]) for s in body["secrets_needed"]}
    assert ("alpha", "x_ref") in refs
    assert ("beta", "auth_token") in refs


def test_import_does_not_carry_secrets_into_keyring(client, keyring_store):
    """Imports never include secret values — even if a malicious
    bundle were to add an `env_secrets` field, the import endpoint
    must not propagate plaintext into the keyring. The MCPServerCreate
    contract still accepts env_secrets, so this asserts behavior:
    when the bundle entry comes through the import path, env_secrets
    DEFAULT to empty regardless of what's in the JSON.
    """
    bundle = {"version": 1, "servers": [{
        "schema_version": 1, "name": "honey",
        "transport": "stdio", "command": ["echo"],
        "env_refs": {"X": "x_ref"},
        "env_secrets": [{"ref": "x_ref", "value": "INJECTED_PLAINTEXT"}],
        "timeout_seconds": 30,
    }]}
    r = client.post("/mcp-servers/import", json=bundle)
    assert r.status_code == 200
    # Even if Pydantic accepted the env_secrets field, our import
    # endpoint forces env_secrets=[] before constructing the spec.
    assert keyring_store.get("mcp.honey.x_ref") is None
    # The pilot is told they still owe this credential
    needed = {(s["server"], s["ref"]) for s in r.json()["secrets_needed"]}
    assert ("honey", "x_ref") in needed
